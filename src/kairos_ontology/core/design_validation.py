# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Read-only, domain-scoped validators for mapping and Silver design artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from pyshacl import validate as shacl_validate
from rdflib import Graph, Namespace, RDF, URIRef

from .ontology_loader import OntologyLoadError, load_ontology
from .projections.dbt.mapping_bind import (
    bind_mapping_graph,
    expression_input_uris,
)
from .projections.dbt.canonical_hash import parse_canonical_type
from .projections.dbt.mapping_specs import AuthoredExpressionFact, MappingContractError

KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")
SH = Namespace("http://www.w3.org/ns/shacl#")


@dataclass(frozen=True, slots=True)
class DesignDiagnostic:
    """One deterministic, actionable design validation result."""

    code: str
    message: str
    resource_uri: str = ""
    predicate_uri: str = ""
    remediation: str = ""

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-compatible diagnostic."""
        return asdict(self)


def _report(kind: str, diagnostics: Iterable[DesignDiagnostic], **counts: int) -> dict:
    ordered = sorted(
        diagnostics,
        key=lambda item: (
            item.resource_uri,
            item.predicate_uri,
            item.code,
            item.message,
        ),
    )
    return {
        "schema_version": 1,
        "validator": kind,
        "passed": not ordered,
        **counts,
        "diagnostics": [item.to_dict() for item in ordered],
    }


def _mapping_error(exc: Exception) -> DesignDiagnostic:
    if isinstance(exc, MappingContractError):
        return DesignDiagnostic(
            code=exc.code,
            message=str(exc),
            resource_uri=exc.resource_uri,
            predicate_uri=exc.predicate_uri,
            remediation=(
                "Correct the named mapping resource with kairos-design-mapping, then rerun "
                "validate-mapping."
            ),
        )
    return DesignDiagnostic(
        code="mapping.invalid-turtle",
        message=str(exc),
        remediation="Correct the Turtle syntax, then rerun validate-mapping.",
    )


def _expression_nodes(
    expression: AuthoredExpressionFact | None,
) -> Iterable[AuthoredExpressionFact]:
    if expression is None:
        return
    yield expression
    for argument in expression.arguments:
        yield from _expression_nodes(argument)
    for branch in expression.branches:
        yield from _expression_nodes(branch.condition)
        yield from _expression_nodes(branch.result)
    yield from _expression_nodes(expression.else_expression)


def validate_mapping_design(
    *,
    mapping_paths: Iterable[Path],
    mapping_graph: Graph | None = None,
    source_root: Path,
    ontology_path: Path,
    catalog_path: Path | None = None,
    include_proposals: bool = False,
) -> dict:
    """Validate mapping structure and IRI resolution against one domain closure."""
    diagnostics: list[DesignDiagnostic] = []
    graph = Graph()
    selected_paths = tuple(sorted(mapping_paths))
    try:
        if mapping_graph is not None:
            graph += mapping_graph
        for path in selected_paths:
            graph.parse(path, format="turtle")
        facts = bind_mapping_graph(graph, include_proposals=include_proposals)
    except Exception as exc:  # binder intentionally exposes stable contract errors
        diagnostic = _mapping_error(exc)
        if not diagnostic.resource_uri and selected_paths:
            diagnostic = DesignDiagnostic(
                diagnostic.code,
                diagnostic.message,
                str(selected_paths[0]),
                diagnostic.predicate_uri,
                diagnostic.remediation,
            )
        return _report("mapping-design", [diagnostic], files=len(selected_paths))

    source_graph = Graph()
    for path in sorted(source_root.rglob("*.ttl")) if source_root.is_dir() else ():
        try:
            source_graph.parse(path, format="turtle")
        except Exception as exc:
            diagnostics.append(
                DesignDiagnostic(
                    "mapping.invalid-source-turtle",
                    f"Could not parse in-scope source vocabulary {path}: {exc}",
                    str(path),
                    remediation="Correct this source vocabulary with kairos-design-source.",
                )
            )
    source_tables = {
        str(item) for item in source_graph.subjects(RDF.type, KAIROS_BRONZE.SourceTable)
    }
    source_columns = {
        str(item) for item in source_graph.subjects(RDF.type, KAIROS_BRONZE.SourceColumn)
    }

    try:
        loaded = load_ontology(
            ontology_path,
            catalog_path=catalog_path,
            profile="kairos-design",
        )
        index = loaded.semantic_index
    except Exception as exc:
        diagnostics.append(
            DesignDiagnostic(
                "mapping.domain-closure-error",
                f"Could not load scoped domain closure {ontology_path}: {exc}",
                str(ontology_path),
                remediation="Resolve this domain's imports/catalog entries and retry.",
            )
        )
        return _report(
            "mapping-design",
            diagnostics,
            files=len(selected_paths),
            table_mappings=len(facts.tables),
            column_mappings=len(facts.columns),
        )

    table_targets: dict[str, list[str]] = {}
    for fact in facts.tables:
        table_targets.setdefault(fact.source_table_uri, []).append(fact.target_class_uri)
        if fact.source_table_uri not in source_tables:
            diagnostics.append(
                DesignDiagnostic(
                    "mapping.unknown-source-table",
                    f"sourceTable does not exist in scoped source vocabularies: "
                    f"{fact.source_table_uri}",
                    fact.resource_uri,
                    str(KAIROS_BRONZE.sourceTable),
                    "Import or correct the source table with kairos-design-source.",
                )
            )
        if index.class_by_uri(fact.target_class_uri) is None:
            diagnostics.append(
                DesignDiagnostic(
                    "mapping.unknown-target-class",
                    f"targetClass does not resolve in the scoped domain closure: "
                    f"{fact.target_class_uri}",
                    fact.resource_uri,
                    remediation="Correct the target IRI or the domain import closure.",
                )
            )
        for node in _expression_nodes(fact.row_filter):
            try:
                parse_canonical_type(node.output_type)
            except ValueError as exc:
                diagnostics.append(
                    DesignDiagnostic(
                        "mapping.invalid-expression-output-type",
                        f"expression outputType {node.output_type!r} is invalid: {exc}",
                        node.resource_uri,
                        remediation="Use an adapter-neutral canonical mapping type.",
                    )
                )

    column_to_table: dict[str, str] = {}
    for column in source_columns:
        tables = sorted(
            str(item) for item in source_graph.objects(URIRef(column), KAIROS_BRONZE.sourceTable)
        )
        if len(tables) == 1:
            column_to_table[column] = tables[0]

    for fact in facts.columns:
        if fact.source_column_uri not in source_columns:
            diagnostics.append(
                DesignDiagnostic(
                    "mapping.unknown-source-column",
                    f"sourceColumn does not exist in scoped source vocabularies: "
                    f"{fact.source_column_uri}",
                    fact.resource_uri,
                    remediation="Import or correct the source column with kairos-design-source.",
                )
            )
        prop = index.property_by_uri(fact.target_property_uri)
        if prop is None:
            diagnostics.append(
                DesignDiagnostic(
                    "mapping.unknown-target-property",
                    f"targetProperty does not resolve in the scoped domain closure: "
                    f"{fact.target_property_uri}",
                    fact.resource_uri,
                    remediation="Correct the target IRI or the domain import closure.",
                )
            )
        else:
            table = column_to_table.get(fact.source_column_uri)
            classes = table_targets.get(table or "", [])
            if classes and not any(
                item["property_uri"] == fact.target_property_uri
                for class_uri in classes
                for item in index.class_properties(class_uri)
            ):
                diagnostics.append(
                    DesignDiagnostic(
                        "mapping.property-outside-target-class",
                        f"targetProperty {fact.target_property_uri} is not direct or inherited "
                        f"on target class(es) {sorted(classes)}",
                        fact.resource_uri,
                        remediation="Choose a property owned by the mapped target class.",
                    )
                )
        for input_uri in expression_input_uris(fact.expression):
            if input_uri not in source_columns:
                diagnostics.append(
                    DesignDiagnostic(
                        "mapping.unknown-expression-source-column",
                        f"expression references an unknown source column: {input_uri}",
                        fact.resource_uri,
                        remediation="Correct the expression's named sourceColumn IRI.",
                    )
                )
        for node in _expression_nodes(fact.expression):
            try:
                parse_canonical_type(node.output_type)
            except ValueError as exc:
                diagnostics.append(
                    DesignDiagnostic(
                        "mapping.invalid-expression-output-type",
                        f"expression outputType {node.output_type!r} is invalid: {exc}",
                        node.resource_uri,
                        remediation="Use an adapter-neutral canonical mapping type.",
                    )
                )

    return _report(
        "mapping-design",
        diagnostics,
        files=len(selected_paths),
        table_mappings=len(facts.tables),
        column_mappings=len(facts.columns),
    )


_PACKAGED_SILVER_EXT_SHAPES = (
    Path(__file__).resolve().parent.parent / "scaffold" / "kairos-ext-shapes.shacl.ttl"
)


def resolve_silver_ext_shapes(hub_root: Path) -> tuple[Path | None, str]:
    """Resolve the Silver-ext SHACL shape source for a hub.

    Prefers the hub-local managed shape, then the packaged canonical shape.
    Returns ``(path, source)`` where ``source`` is ``"hub-local"``,
    ``"packaged"``, or ``""`` when neither is available.
    """
    hub_local = hub_root / "model" / "shapes" / "kairos-ext-shapes.shacl.ttl"
    if hub_local.is_file():
        return hub_local, "hub-local"
    if _PACKAGED_SILVER_EXT_SHAPES.is_file():
        return _PACKAGED_SILVER_EXT_SHAPES, "packaged"
    return None, ""


def validate_silver_extension(
    *,
    extension_path: Path | None,
    extension_graph: Graph | None = None,
    ontology_path: Path,
    shapes_path: Path,
    catalog_path: Path | None = None,
) -> dict:
    """Validate exactly one Silver extension and its scoped domain closure."""
    try:
        extension = Graph()
        if extension_graph is not None:
            extension += extension_graph
        elif extension_path is not None:
            extension.parse(extension_path, format="turtle")
        else:
            raise ValueError("Provide extension_path or extension_graph.")
    except Exception as exc:
        return _report(
            "silver-extension",
            [
                DesignDiagnostic(
                    "silver.invalid-turtle",
                    str(exc),
                    str(extension_path or "<generated-silver-scaffold>"),
                    remediation="Correct this Silver extension's Turtle syntax.",
                )
            ],
        )
    try:
        loaded = load_ontology(
            ontology_path,
            catalog_path=catalog_path,
            profile="rdfs",
        )
    except OntologyLoadError as exc:
        root_errors = [item for item in exc.result.diagnostics if item.code == "root_parse_error"]
        if root_errors:
            error = root_errors[0]
            diagnostic = DesignDiagnostic(
                "silver.domain-load-error",
                error.message,
                error.source_path or str(ontology_path),
                remediation="Correct the domain ontology path or Turtle syntax.",
            )
        else:
            details = "; ".join(
                item.message for item in exc.result.diagnostics if item.level == "error"
            )
            diagnostic = DesignDiagnostic(
                "silver.domain-closure-error",
                details or str(exc),
                str(ontology_path),
                remediation="Resolve this domain's required imports and catalog entries.",
            )
        return _report(
            "silver-extension",
            [diagnostic],
        )
    except Exception as exc:
        resource = str(catalog_path or ontology_path)
        remediation = (
            "Correct the catalog path or XML syntax and retry."
            if catalog_path is not None
            else "Correct the domain ontology path or Turtle syntax."
        )
        return _report(
            "silver-extension",
            [
                DesignDiagnostic(
                    "silver.domain-closure-error",
                    str(exc),
                    resource,
                    remediation=remediation,
                )
            ],
        )

    data = Graph()
    data += loaded.graph
    data += extension
    shapes = Graph()
    if not shapes_path.is_file():
        return _report(
            "silver-extension",
            [
                DesignDiagnostic(
                    "silver.shapes-missing",
                    f"Silver SHACL shape file not found: {shapes_path}",
                    str(shapes_path),
                    remediation=(
                        "Restore model/shapes/kairos-ext-shapes.shacl.ttl (e.g. run "
                        "'kairos-ontology update'), pass an explicit --shapes path, or "
                        "reinstall the toolkit so the packaged canonical shape is present."
                    ),
                )
            ],
        )
    try:
        # Resolve to a file URI so an absolute Windows drive-letter path (e.g.
        # "G:\\...") is never mis-parsed by rdflib as a URL scheme ("g").
        resolved_shapes = shapes_path.resolve(strict=True)
        shapes.parse(location=resolved_shapes.as_uri(), format="turtle")
    except Exception as exc:
        return _report(
            "silver-extension",
            [
                DesignDiagnostic(
                    "silver.shapes-load-error",
                    str(exc),
                    str(shapes_path),
                    remediation="Correct the Silver SHACL shape path or Turtle syntax.",
                )
            ],
        )

    try:
        conforms, report_graph, _ = shacl_validate(
            data,
            shacl_graph=shapes,
            inference="rdfs",
            abort_on_first=False,
        )
    except Exception as exc:
        return _report(
            "silver-extension",
            [
                DesignDiagnostic(
                    "silver.shacl-execution-error",
                    str(exc),
                    str(extension_path or "<generated-silver-scaffold>"),
                    remediation="Correct the SHACL engine inputs or execution environment.",
                )
            ],
        )
    diagnostics: list[DesignDiagnostic] = []
    if not conforms:
        for result in report_graph.subjects(RDF.type, SH.ValidationResult):
            focus = str(
                report_graph.value(result, SH.focusNode)
                or extension_path
                or "<generated-silver-scaffold>"
            )
            path = str(report_graph.value(result, SH.resultPath) or "")
            message = str(report_graph.value(result, SH.resultMessage) or "SHACL violation")
            diagnostics.append(
                DesignDiagnostic(
                    "silver.shacl-violation",
                    message,
                    focus,
                    path,
                    "Update the named Silver resource with kairos-design-silver.",
                )
            )
    return _report("silver-extension", diagnostics)
