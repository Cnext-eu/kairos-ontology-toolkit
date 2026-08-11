# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Stateless v5 compiler kernel (DD-133)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from dataclasses import replace

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD
import yaml

from kairos_ontology import __version__

from ..ontology_loader import SemanticProfile, load_ontology
from ..ontology_ops import PropertyInfo, list_classes
from ..projections.uri_utils import camel_to_snake
from ..projections.dbt import (
    BoundSources,
    normalize_contract,
    plan_materialization,
    render_canonical_project,
    shape_project,
)
from ..projections.dbt.context import ActiveSourceScope
from ..projections.dbt.canonical_hash import temporal_match_count_column
from ..projections.dbt.diagnostics import ExecutionMode
from ..projections.dbt.mapping_specs import SourceMappings
from ..projections.dbt.mapping_renderers import quote_mapping_identifier
from ..projections.dbt.policy_bind import EXT as _EXT_NS
from ..projections.dbt.policy_bind import _data_quality_rules, bind_policy_facts
from ..projections.dbt.policy_normalize import _source_type
from ..projections.dbt.policy_specs import (
    AuthoredValuesFact,
    CanonicalTypeKind,
    CanonicalTypeSpec,
    MultiSourcePolicyFact,
    TemporalRelationshipFact,
)
from ..projections.dbt.specs import (
    ColumnSpec,
    JoinSpec,
    SourceBindingsFact,
    SourceSystemFact,
    SilverModelKind,
)
from ..projections.shared import ForeignKeyAuthoringFact
from .adapter import (
    ResolutionContext,
    ResolvedClass,
    ResolvedColumn,
    ResolvedProperty,
    ResolvedRelation,
    adapt_binding,
    object_property_in_fields_message,
)
from .bindings import (
    EntityBinding,
    ExprColumn,
    RelationshipSpec,
    TechnicalField,
    load_entity_binding,
)
from .compile import CompileMode
from .conformance import ConformancePlan, ConformanceTypeContract, build_conformance_plan
from .dbt_source import resolve_dbt_model_source
from .ir import CanonicalProjectIR, EntityBindingSpec
from .plan import CompileEntityPlan, CompilePlan, PlannedCompileArtifact
from .quality import run_safety_kernel
from .result import (
    CompileDiagnostic,
    CompileDiagnostics,
    CompileError,
    CompileResult,
    ExplainConformance,
    ExplainDataQuality,
    ExplainEntity,
    ExplainLoad,
    ExplainQualityCheck,
    ExplainRelationship,
    ExplainReport,
    ExplainTechnicalField,
    SourceLocation,
    order_compile_diagnostics,
)
from .result import DiagnosticSeverity
from .scope import BuildScope, ProvenanceInput
from .temporal import adapt_temporal_relationships

logger = logging.getLogger(__name__)


def _codes_of(
    diagnostics: tuple[CompileDiagnostic, ...] | list[CompileDiagnostic],
) -> tuple[str, ...]:
    """Extract diagnostic codes for compact debug trace lines."""
    return tuple(d.code for d in diagnostics)


_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")
_XSD_TYPES = {
    str(XSD.string): "string",
    str(XSD.boolean): "boolean",
    str(XSD.integer): "bigint",
    str(XSD.int): "int",
    str(XSD.long): "bigint",
    str(XSD.decimal): "decimal(38, 10)",
    str(XSD.float): "float",
    str(XSD.double): "double",
    str(XSD.date): "date",
    str(XSD.dateTime): "timestamp",
}


def _literal(graph: Graph, subject: URIRef, predicate: URIRef, default: str = "") -> str:
    value = graph.value(subject, predicate)
    return str(value) if value is not None else default


def _qnames(graph: Graph, uri: URIRef) -> tuple[str, ...]:
    values = {str(uri)}
    try:
        prefix, _, name = graph.namespace_manager.compute_qname(uri, generate=False)
        values.add(f"{prefix}:{name}")
    except KeyError:
        pass
    return tuple(sorted(values))


_PREFIX_DECLARATION = re.compile(r"(?im)^\s*@prefix\s+([^:\s]*)\s*:\s*<([^>]*)>\s*\.")


def _namespace_local(uri: str) -> tuple[str, str]:
    if "#" in uri:
        namespace, local = uri.rsplit("#", 1)
        return f"{namespace}#", local
    namespace, local = uri.rsplit("/", 1) if "/" in uri else ("", uri)
    return (f"{namespace}/" if namespace else "", local)


def _declared_prefixes(source_path: str) -> dict[str, tuple[str, ...]]:
    """Return explicitly authored Turtle prefixes from one source file."""
    if not source_path:
        return {}
    path = Path(source_path)
    if not path.is_file() or path.suffix.lower() not in {".ttl", ".turtle"}:
        return {}
    text = path.read_text(encoding="utf-8")
    prefixes: dict[str, list[str]] = {}
    for match in _PREFIX_DECLARATION.finditer(text):
        prefixes.setdefault(match.group(1), []).append(match.group(2))
    return {prefix: tuple(namespaces) for prefix, namespaces in prefixes.items()}


def _prefix_diagnostics(loaded, root_path: Path) -> tuple[CompileDiagnostic, ...]:
    diagnostics: list[CompileDiagnostic] = []
    for source in loaded.sources:
        path = source.manifest.source_path
        for prefix, namespaces in sorted(_declared_prefixes(path).items()):
            distinct = tuple(dict.fromkeys(namespaces))
            if len(distinct) > 1:
                diagnostics.append(
                    CompileDiagnostic(
                        code="safety.prefix-ambiguous",
                        message=(
                            f"prefix '{prefix or ':'}' is declared with multiple namespaces "
                            f"in {path}: {', '.join(distinct)}"
                        ),
                        location=SourceLocation(path=path),
                    )
                )
    imported: dict[str, set[str]] = {}
    root = str(root_path.resolve())
    root_prefixes = {
        prefix
        for source in loaded.sources
        if source.manifest.source_path and str(Path(source.manifest.source_path).resolve()) == root
        for prefix in _declared_prefixes(source.manifest.source_path)
    }
    for source in loaded.sources:
        path = source.manifest.source_path
        if not path or str(Path(path).resolve()) == root:
            continue
        for prefix, namespaces in _declared_prefixes(path).items():
            if prefix in root_prefixes:
                continue
            imported.setdefault(prefix, set()).update(namespaces)
    for prefix, namespaces in sorted(imported.items()):
        if len(namespaces) > 1:
            label = prefix or ":"
            candidates = " ".join(
                f"@prefix {prefix}: <{namespace}> ." for namespace in sorted(namespaces)
            )
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.prefix-ambiguous",
                    message=(
                        f"imported prefix '{label}' maps to multiple namespaces "
                        f"without a root declaration: {', '.join(sorted(namespaces))}. "
                        f"The imported prefix is not bound for resolution; declare one "
                        f"candidate in the root ontology to disambiguate: {candidates}"
                    ),
                    location=SourceLocation(path=str(root_path)),
                    severity=DiagnosticSeverity.WARNING,
                )
            )
    return tuple(diagnostics)


def _declared_prefix_aliases(loaded, root_path: Path, uri: str) -> tuple[str, ...]:
    """Return bindable declared-prefix aliases for ``uri``.

    Root-declared prefixes take precedence over imported prefixes. Imported duplicate prefixes
    are bindable only when every declaration points at the same namespace. The empty prefix is
    emitted as ``:Local``.
    """
    namespace, local = _namespace_local(uri)
    root = str(root_path.resolve())
    root_prefixes: dict[str, str] = {}
    imported_prefixes: dict[str, set[str]] = {}
    for source in loaded.sources:
        path = source.manifest.source_path
        if not path:
            continue
        declarations = _declared_prefixes(path)
        if str(Path(path).resolve()) == root:
            for prefix, namespaces in declarations.items():
                if namespaces:
                    root_prefixes[prefix] = namespaces[-1]
        else:
            for prefix, namespaces in declarations.items():
                imported_prefixes.setdefault(prefix, set()).update(namespaces)
    aliases: set[str] = set()
    for prefix, declared_namespace in root_prefixes.items():
        if declared_namespace == namespace:
            aliases.add(f"{prefix}:{local}" if prefix else f":{local}")
    for prefix, namespaces in imported_prefixes.items():
        if prefix in root_prefixes or len(namespaces) != 1:
            continue
        declared_namespace = next(iter(namespaces))
        if declared_namespace == namespace:
            aliases.add(f"{prefix}:{local}" if prefix else f":{local}")
    return tuple(sorted(aliases))


def _source_relations(paths: tuple[Path, ...]) -> tuple[ResolvedRelation, ...]:
    relations: list[ResolvedRelation] = []
    for path in paths:
        graph = Graph()
        graph.parse(path, format="turtle")
        for table in sorted(graph.subjects(RDF.type, _BRONZE.SourceTable), key=str):
            system = graph.value(table, _BRONZE.sourceSystem)
            system_uri = str(system or f"{table}#system")
            system_ref = URIRef(system_uri)
            system_label = _literal(graph, system_ref, RDFS.label) or system_ref.split("#")[-1]
            table_name = _literal(graph, table, _BRONZE.tableName) or str(table).split("#")[-1]
            primary_keys = {
                item.strip()
                for item in _literal(graph, table, _BRONZE.primaryKeyColumns).split(",")
                if item.strip()
            }
            columns: list[ResolvedColumn] = []
            column_nodes = set(graph.subjects(_BRONZE.sourceTable, table))
            column_nodes.update(graph.subjects(_BRONZE.belongsToTable, table))
            for column in sorted(column_nodes, key=str):
                name = _literal(graph, column, _BRONZE.columnName) or str(column).split("#")[-1]
                nullable_value = graph.value(column, _BRONZE.nullable)
                columns.append(
                    ResolvedColumn(
                        name=name,
                        data_type=_literal(graph, column, _BRONZE.dataType, "string"),
                        nullable=bool(nullable_value.toPython()) if nullable_value else True,
                        is_primary_key=name in primary_keys,
                    )
                )
            refs = {table_name, f"{system_label}.{table_name}"}
            refs.update(_qnames(graph, table))
            for ref in sorted(refs):
                relations.append(
                    ResolvedRelation(
                        ref=ref,
                        uri=str(table),
                        system_label=system_label,
                        table_name=table_name,
                        columns=tuple(columns),
                        database=_literal(graph, system_ref, _BRONZE.database, "raw_db"),
                        schema=_literal(graph, system_ref, _BRONZE.schema, "dbo"),
                        connection_type=_literal(graph, system_ref, _BRONZE.connectionType, "jdbc"),
                        system_uri=system_uri,
                    )
                )
    unique = {(item.ref, item.uri): item for item in relations}
    return tuple(unique[key] for key in sorted(unique))


def _binding_source_ref(text: str) -> str:
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return ""
    if not isinstance(document, dict) or not isinstance(document.get("source"), dict):
        return ""
    return str(document["source"].get("relation", ""))


def _binding_dbt_paths(text: str) -> tuple[str, str]:
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return "", ""
    source = document.get("source") if isinstance(document, dict) else None
    model = source.get("dbtModel") if isinstance(source, dict) else None
    if not isinstance(model, dict):
        return "", ""
    return str(model.get("sqlPath", "")), str(model.get("contractPath", ""))


def _local_from_uri(uri: str) -> str:
    return uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _declared_namespace_for_prefix(loaded, root_path: Path, prefix: str) -> str | None:
    """Return the namespace bound to *prefix* across the resolved closure, if unambiguous.

    Inverse of ``_declared_prefix_aliases`` (namespace -> qname): the loaded graph's own
    ``namespace_manager`` does **not** carry the source Turtle's ``@prefix`` bindings (only
    rdflib's built-in defaults), so — exactly like ``_declared_prefix_aliases`` already
    does — prefix declarations are read directly from each closure member's raw text.
    Root-declared prefixes take precedence; an imported prefix is usable only when every
    declaration across the closure agrees on the same namespace.
    """
    root = str(root_path.resolve())
    root_namespace: str | None = None
    imported_namespaces: set[str] = set()
    for source in loaded.sources:
        path = source.manifest.source_path
        if not path:
            continue
        namespaces = _declared_prefixes(path).get(prefix)
        if not namespaces:
            continue
        if str(Path(path).resolve()) == root:
            root_namespace = namespaces[-1]
        else:
            imported_namespaces.update(namespaces)
    if root_namespace is not None:
        return root_namespace
    if len(imported_namespaces) == 1:
        return next(iter(imported_namespaces))
    return None


def _index_class_by_token(loaded, root_path: Path, index, token: str):
    """Resolve *token* (a full IRI or a ``prefix:Local`` qname) against *index*.

    DD-144: ``index`` already covers the *entire* resolved ``owl:imports`` closure (DD-103
    builds it from the full merged graph, not just the domain's own locally-declared
    classes) — an accelerator class an author references without a local
    ``rdfs:subClassOf`` is already indexed, it is simply never looked up unless asked for
    directly. This is that lookup, used as a fallback only for tokens that do not match any
    locally-declared class.
    """
    if index is None:
        return None
    if "://" in token or token.startswith("urn:"):
        return index.class_by_uri(token)
    if ":" not in token:
        return None
    prefix, _, local = token.partition(":")
    namespace = _declared_namespace_for_prefix(loaded, root_path, prefix)
    if namespace is None:
        return None
    return index.class_by_uri(namespace + local)


def _class_index_properties(index, class_uri: str, graph: Graph) -> tuple[PropertyInfo, ...]:
    """Return direct + subclass-inherited datatype/object properties for a bound class.

    Uses the DD-103 semantic index closure (``class_properties``) so inherited and
    cross-namespace imported properties resolve without local redeclaration. Excludes
    annotation/rdf properties. The exact-domain/namespace helpers in ``ontology_ops`` do not
    walk the subclass hierarchy and must not be used for structure-aware binding resolution.
    """
    if index is None:
        return ()
    resolved: list[PropertyInfo] = []
    for row in index.class_properties(class_uri):
        if row.get("property_type") not in {"object", "datatype"}:
            continue
        prop_uri = row["property_uri"]
        record = index.property_by_uri(prop_uri)
        is_object_property = row["property_type"] == "object"
        ranges = tuple(row.get("ranges") or ())
        # ``ranges`` (DD-103 semantic index) keeps only ``URIRef`` objects, so it is empty
        # both for a missing ``rdfs:range`` and for a class-expression range (a blank node:
        # ``owl:unionOf`` / ``owl:Restriction`` / ``owl:oneOf``). Falling back to
        # ``xsd:string`` is the right default for a *datatype* property, but for an object
        # property it fabricates a scalar range that makes the property byte-identical to a
        # real string attribute -- which erased the relationship when authored under
        # ``fields:`` and made the range check in ``_relationship_diagnostics`` reject the
        # correct ``relationships:`` authoring (issue #280). An object property with no
        # resolvable named range therefore carries no range at all, and the
        # ``prop.range_uri and ...`` guard short-circuits honestly.
        range_uri = ranges[0] if ranges else ("" if is_object_property else str(XSD.string))
        resolved.append(
            PropertyInfo(
                uri=prop_uri,
                name=row["name"],
                label=record.label if record is not None else row["name"],
                comment=record.comment if record is not None else "",
                range_uri=range_uri,
                range_name=_local_from_uri(range_uri),
                is_object_property=is_object_property,
            )
        )
    return tuple(resolved)


def _ontology_symbols(
    ontology_path: Path, hub_root: Path, referenced_tokens: frozenset[str] = frozenset()
) -> tuple[
    Graph,
    str,
    str,
    str,
    tuple[ResolvedClass, ...],
    tuple[ResolvedProperty, ...],
    tuple[str, ...],
    tuple[CompileDiagnostic, ...],
]:
    # DD-108/DD-103: resolve binding symbols against a non-asserted (RDFS) profile so that
    # subclass-inherited and cross-namespace imported properties become bindable via the
    # semantic index closure. ASSERTED would leave inherited_properties empty.
    loaded = load_ontology(ontology_path, identity_root=hub_root, profile=SemanticProfile.RDFS)
    # DD-133: same-file prefix conflicts remain blocking errors, but an imported-only ambiguous
    # prefix is never bound for resolution (see ``_declared_prefix_aliases``), so it is surfaced
    # as a non-fatal warning with candidate ``@prefix`` declarations rather than failing compile.
    prefix_diagnostics = _prefix_diagnostics(loaded, ontology_path)
    prefix_errors = tuple(
        item for item in prefix_diagnostics if item.severity is DiagnosticSeverity.ERROR
    )
    prefix_warnings = tuple(
        item for item in prefix_diagnostics if item.severity is not DiagnosticSeverity.ERROR
    )
    if prefix_errors:
        raise CompileError(prefix_errors)
    graph = loaded.graph
    index = loaded.semantic_index
    first_class = next(graph.subjects(RDF.type, OWL.Class), None)
    first_class_uri = str(first_class or "")
    namespace = (
        first_class_uri.rsplit("#", 1)[0] + "#"
        if "#" in first_class_uri
        else (
            first_class_uri.rsplit("/", 1)[0] + "/"
            if "/" in first_class_uri
            else "urn:kairos:ontology:"
        )
    )
    ontology = next(graph.subjects(RDF.type, OWL.Ontology), URIRef(namespace.rstrip("#/")))
    version = _literal(graph, ontology, OWL.versionInfo, "0.0.0")
    classes: list[ResolvedClass] = []
    properties: dict[tuple[str, str], ResolvedProperty] = {}
    domain_prefix = ontology_path.stem
    for info in list_classes(graph, namespace):
        class_refs = set(_qnames(graph, URIRef(info.uri)))
        class_refs.update(_declared_prefix_aliases(loaded, ontology_path, info.uri))
        class_refs.add(f"{domain_prefix}:{info.name}")
        parent_uris = tuple(
            sorted(
                str(parent)
                for parent in graph.objects(URIRef(info.uri), RDFS.subClassOf)
                if isinstance(parent, URIRef)
            )
        )
        for ref in sorted(class_refs):
            classes.append(
                ResolvedClass(
                    ref,
                    info.uri,
                    info.name,
                    info.label,
                    info.comment,
                    parent_uris,
                )
            )
        for prop in _class_index_properties(index, info.uri, graph):
            data_type = _XSD_TYPES.get(prop.range_uri, prop.range_uri)
            property_refs = set(_qnames(graph, URIRef(prop.uri)))
            property_refs.update(_declared_prefix_aliases(loaded, ontology_path, prop.uri))
            property_refs.add(f"{domain_prefix}:{prop.name}")
            for ref in sorted(property_refs):
                key = (ref, prop.uri)
                previous = properties.get(key)
                domains = tuple(sorted({*(previous.domain_uris if previous else ()), info.uri}))
                properties[key] = ResolvedProperty(
                    ref=ref,
                    uri=prop.uri,
                    column_name=camel_to_snake(prop.name),
                    data_type=data_type,
                    description=prop.comment,
                    is_object_property=prop.is_object_property,
                    domain_uris=domains,
                    range_uri=prop.range_uri,
                )
    # DD-144: accelerator-direct binding resolution. The local-namespace pass above never
    # sees an imported (e.g. accelerator) class an author references without a local
    # ``rdfs:subClassOf`` — but ``index``/``graph`` already cover the full resolved
    # ``owl:imports`` closure (DD-103), so the class is already indexed. Resolve only the
    # tokens actually referenced by a binding in this compile scope and not already covered
    # by a local class, so this never floods ``classes``/``properties`` with an accelerator's
    # entire term universe. A token that resolves neither locally nor here still falls
    # through to the existing ``binding.unknown-class``/``binding.unknown-property``
    # diagnostics unchanged.
    resolved_refs = {item.ref for item in classes}
    for token in sorted(referenced_tokens - resolved_refs):
        record = _index_class_by_token(loaded, ontology_path, index, token)
        if record is None:
            continue
        classes.append(
            ResolvedClass(token, record.uri, record.name, record.label, record.comment, ())
        )
        for prop in _class_index_properties(index, record.uri, graph):
            data_type = _XSD_TYPES.get(prop.range_uri, prop.range_uri)
            property_refs = set(_qnames(graph, URIRef(prop.uri)))
            property_refs.update(_declared_prefix_aliases(loaded, ontology_path, prop.uri))
            for ref in sorted(property_refs):
                key = (ref, prop.uri)
                previous = properties.get(key)
                domains = tuple(sorted({*(previous.domain_uris if previous else ()), record.uri}))
                properties[key] = ResolvedProperty(
                    ref=ref,
                    uri=prop.uri,
                    column_name=camel_to_snake(prop.name),
                    data_type=data_type,
                    description=prop.comment,
                    is_object_property=prop.is_object_property,
                    domain_uris=domains,
                    range_uri=prop.range_uri,
                )
    closure_paths = tuple(
        sorted(
            str(source.manifest.source_path)
            for source in loaded.sources
            if source.manifest.source_path
        )
    )
    return (
        graph,
        namespace,
        str(ontology),
        version,
        tuple(classes),
        tuple(properties.values()),
        closure_paths or (str(ontology_path),),
        prefix_warnings,
    )


def resolve_scope(hub_root: Path, domain: str) -> tuple[BuildScope, ResolutionContext]:
    """Discover and load the deterministic v5 compile scope."""
    candidate = hub_root.resolve()
    root = candidate
    if not (root / "integration").is_dir() or not (root / "model").is_dir():
        root = next(
            (
                parent
                for parent in (candidate, *candidate.parents)
                if (parent / "kairos.yaml").is_file()
            ),
            candidate,
        )
    discovered_bindings = tuple(sorted((root / "integration" / "bindings").glob("*.binding.yaml")))
    binding_paths = tuple(
        path
        for path in discovered_bindings
        if _binding_domain(path.read_text(encoding="utf-8")) in {None, domain}
    )
    ontology_path = root / "model" / "ontologies" / f"{domain}.ttl"
    requested_sources = {
        _binding_source_ref(path.read_text(encoding="utf-8")) for path in binding_paths
    }
    source_paths = tuple(
        path
        for path in sorted((root / "integration" / "sources").glob("**/*.ttl"))
        if requested_sources & {relation.ref for relation in _source_relations((path,))}
    )
    if not binding_paths or not ontology_path.is_file():
        if not binding_paths:
            # Ontology-only waypoint: the hub has a valid ontology slice but no
            # EntityBinding authored yet. Distinct from a genuine source-resolution
            # failure so a CI gate can tell an expected early stage apart from a
            # broken binding. Still blocking (an un-emittable hub stays non-zero).
            raise CompileError(
                [
                    CompileDiagnostic(
                        code="scope.no-bindings-authored",
                        message=(
                            "compile scope is incomplete: no EntityBinding documents "
                            "authored yet (author a binding to resolve a source)"
                        ),
                        location=SourceLocation(path=str(root)),
                    )
                ]
            )
        raise CompileError(
            [
                CompileDiagnostic(
                    code="safety.source-unresolved",
                    message=f"compile scope is incomplete: missing {ontology_path}",
                    location=SourceLocation(path=str(root)),
                )
            ]
        )
    config_path = root / "kairos.yaml"
    if not config_path.is_file():
        raise CompileError(
            [
                CompileDiagnostic(
                    code="safety.adapter-unsupported",
                    message="v5 compile requires kairos.yaml with an explicit adapter",
                    location=SourceLocation(path=str(config_path)),
                )
            ]
        )
    referenced_tokens = frozenset(
        token
        for path in binding_paths
        for token in _binding_referenced_class_tokens(path.read_text(encoding="utf-8"))
    )
    (
        graph,
        namespace,
        ontology_iri,
        version,
        classes,
        properties,
        ontology_paths,
        prefix_warnings,
    ) = _ontology_symbols(ontology_path, root, referenced_tokens)
    relations = list(_source_relations(source_paths))
    template_root = Path(__file__).resolve().parents[2] / "templates" / "dbt"
    inputs = [
        ProvenanceInput(str(path.relative_to(root)), path.read_text(encoding="utf-8"))
        for path in (*binding_paths, *source_paths)
    ]
    gold_extension = root / "model" / "extensions" / f"{domain}-gold-ext.ttl"
    if gold_extension.is_file():
        inputs.append(
            ProvenanceInput(
                str(gold_extension.relative_to(root)).replace("\\", "/"),
                gold_extension.read_text(encoding="utf-8"),
            )
        )
    for path in binding_paths:
        text = path.read_text(encoding="utf-8")
        sql_path, contract_path = _binding_dbt_paths(text)
        if not sql_path and not contract_path:
            continue
        try:
            binding = load_entity_binding(text, path=str(path))
            relation = resolve_dbt_model_source(binding, root)
            relations.append(relation)
            for authored_path in (sql_path, contract_path):
                resolved_path = (root / authored_path).resolve()
                inputs.append(
                    ProvenanceInput(
                        str(resolved_path.relative_to(root)).replace("\\", "/"),
                        resolved_path.read_text(encoding="utf-8"),
                    )
                )
        except CompileError:
            # The entity-local compile pass replays this resolution and preserves its
            # precise binding pointer while allowing unrelated safe entities to proceed.
            continue
    for path_text in ontology_paths:
        path = Path(path_text)
        if path.is_file():
            inputs.append(
                ProvenanceInput(
                    str(path.relative_to(root)) if path.is_relative_to(root) else path.name,
                    path.read_text(encoding="utf-8"),
                )
            )
    for path in sorted(template_root.rglob("*")):
        if path.is_file():
            inputs.append(
                ProvenanceInput(
                    f"templates/{path.relative_to(template_root).as_posix()}",
                    path.read_text(encoding="utf-8"),
                )
            )
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    adapter = str(config.get("adapter", ""))
    if adapter not in {"fabric", "databricks"}:
        raise CompileError(
            [
                CompileDiagnostic(
                    code="safety.adapter-unsupported",
                    message=f"adapter '{adapter}' is not supported by the v5 compiler",
                    location=SourceLocation(path=str(config_path)),
                )
            ]
        )
    inputs.append(ProvenanceInput("kairos.yaml", config_path.read_text(encoding="utf-8")))
    scope = BuildScope(
        domain=domain,
        hub_root=str(root),
        api_version="kairos.eu/v5",
        adapter=adapter,
        namespace=namespace,
        toolkit_version=__version__,
        binding_paths=tuple(str(path) for path in binding_paths),
        ontology_paths=ontology_paths,
        inputs=tuple(inputs),
        prefix_warnings=prefix_warnings,
    )
    context = ResolutionContext(
        domain=domain,
        namespace=namespace,
        ontology_name=domain,
        ontology_iri=ontology_iri,
        ontology_version=version,
        template_root=str(template_root),
        target_platform=adapter,
        relations=tuple(relations),
        classes=classes,
        properties=properties,
        data_quality_rules=_data_quality_rules(
            graph, _EXT_NS, frozenset(item.uri for item in classes)
        ),
    )
    return scope, context


def _merge_systems(bounds: tuple[BoundSources, ...]) -> tuple[SourceSystemFact, ...]:
    systems: dict[str, SourceSystemFact] = {}
    for bound in bounds:
        for system in bound.systems:
            previous = systems.get(system.uri)
            systems[system.uri] = (
                system
                if previous is None
                else replace(
                    previous,
                    tables=tuple(
                        {table.uri: table for table in (*previous.tables, *system.tables)}[key]
                        for key in sorted(
                            {table.uri for table in (*previous.tables, *system.tables)}
                        )
                    ),
                )
            )
    return tuple(systems[key] for key in sorted(systems))


def _resolved_binding_relation(
    binding: EntityBinding, context: ResolutionContext
) -> ResolvedRelation | None:
    ref = (
        binding.source.dbt_model.name
        if binding.source.dbt_model is not None
        else binding.source.relation
    )
    return context.relation(ref)


def _relationship_ref_uri(graph: Graph, ref: str, context: ResolutionContext) -> str:
    if ref.startswith(("http://", "https://", "urn:")):
        return ref
    if ":" in ref:
        prefix, local = ref.split(":", 1)
        namespace = graph.namespace_manager.store.namespace(prefix)
        return f"{namespace}{local}" if namespace is not None else ""
    return f"{context.namespace}{ref}" if ref else ""


def _relationship_target_class(
    relationship: RelationshipSpec, context: ResolutionContext, hub_root: str | Path
) -> ResolvedClass | None:
    target = context.klass(relationship.target)
    if target is not None:
        return target
    ontology_path = Path(hub_root) / "model" / "ontologies" / f"{context.domain}.ttl"
    if not ontology_path.is_file():
        return None
    loaded = load_ontology(
        ontology_path,
        identity_root=Path(hub_root),
        profile=SemanticProfile.RDFS,
    )
    uri = _relationship_ref_uri(loaded.graph, relationship.target, context)
    if not uri and ":" in relationship.target:
        prefix, local = relationship.target.split(":", 1)
        uri = next(
            (
                f"{namespaces[0]}{local}"
                for source in loaded.sources
                for namespaces in (_declared_prefixes(source.manifest.source_path).get(prefix, ()),)
                if namespaces
            ),
            "",
        )
    node = URIRef(uri) if uri else None
    if node is None or (node, RDF.type, OWL.Class) not in loaded.graph:
        return None
    _, local = _namespace_local(uri)
    return ResolvedClass(
        relationship.target,
        uri,
        local,
        _literal(loaded.graph, node, RDFS.label, local),
        _literal(loaded.graph, node, RDFS.comment, ""),
    )


def _source_types_compatible(left: str, right: str) -> bool:
    left_type = _source_type(left)
    right_type = _source_type(right)
    return left_type is not None and right_type is not None and left_type.kind is right_type.kind


def _conformance_contract(
    binding: EntityBinding, context: ResolutionContext
) -> ConformanceTypeContract:
    relation = _resolved_binding_relation(binding, context)
    columns = {column.name: column for column in relation.columns} if relation else {}

    def source_types(names: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            (
                _source_type(columns[name].data_type).kind.value
                if name in columns and _source_type(columns[name].data_type) is not None
                else ""
            )
            for name in names
        )

    properties = tuple(
        sorted(
            (
                field.property,
                (
                    _source_type(prop.data_type).kind.value
                    if prop is not None and _source_type(prop.data_type) is not None
                    else prop.data_type
                    if prop is not None
                    else ""
                ),
            )
            for field in binding.fields
            for prop in (context.property(field.property),)
        )
    )
    return ConformanceTypeContract(
        grain=source_types(binding.grain.columns),
        identity=source_types(binding.identity.source_key),
        properties=properties,
    )


def _conformance_plans(
    bindings: tuple[EntityBinding, ...],
    context: ResolutionContext,
    scope: BuildScope,
) -> tuple[tuple[ConformancePlan, ...], tuple[CompileDiagnostic, ...], frozenset[str]]:
    remaining = set(range(len(bindings)))
    groups: list[list[EntityBinding]] = []
    while remaining:
        component = {remaining.pop()}
        changed = True
        while changed:
            changed = False
            target_values = {bindings[index].target_class for index in component}
            group_values = {
                bindings[index].conformance.group
                for index in component
                if bindings[index].conformance is not None
            }
            additions = {
                index
                for index in remaining
                if bindings[index].target_class in target_values
                or (
                    bindings[index].conformance is not None
                    and bindings[index].conformance.group in group_values
                )
            }
            if additions:
                component.update(additions)
                remaining.difference_update(additions)
                changed = True
        groups.append([bindings[index] for index in sorted(component)])
    plans: list[ConformancePlan] = []
    diagnostics: list[CompileDiagnostic] = []
    blocked: set[str] = set()
    input_by_name = {item.name.replace("\\", "/"): item for item in scope.inputs}
    for members in groups:
        needs_plan = len(members) > 1 or any(member.conformance is not None for member in members)
        if not needs_plan:
            continue
        provenance = {}
        for member in members:
            relative = str(Path(member.source_path).resolve().relative_to(scope.hub_root)).replace(
                "\\", "/"
            )
            values = [input_by_name[relative]] if relative in input_by_name else []
            relation = _resolved_binding_relation(member, context)
            if relation is not None:
                values.extend(
                    item
                    for item in scope.inputs
                    if relation.table_name in item.content or relation.uri in item.content
                )
            provenance[member.name] = tuple(values)
        try:
            plans.append(
                build_conformance_plan(
                    members,
                    type_contracts={
                        member.name: _conformance_contract(member, context) for member in members
                    },
                    provenance_inputs=provenance,
                )
            )
        except CompileError as exc:
            diagnostics.extend(exc.diagnostics)
            blocked.update(member.name for member in members)
    return tuple(plans), tuple(diagnostics), frozenset(blocked)


def _foreign_keys(
    bindings: tuple[EntityBinding, ...], context: ResolutionContext, hub_root: str | Path
) -> tuple[ForeignKeyAuthoringFact, ...]:
    class_by_ref = {
        binding.target_class: context.klass(binding.target_class) for binding in bindings
    }
    facts: list[ForeignKeyAuthoringFact] = []
    for binding in bindings:
        domain_class = context.klass(binding.target_class)
        for relationship in binding.relationships:
            prop = context.property(relationship.property)
            target = class_by_ref.get(relationship.target)
            if target is None and relationship.external_reference is not None:
                target = _relationship_target_class(relationship, context, hub_root)
            if domain_class is None or prop is None or target is None:
                continue
            facts.append(
                ForeignKeyAuthoringFact(
                    property_uri=prop.uri,
                    domain_value=domain_class.uri,
                    domain_is_uri=True,
                    range_value=target.uri,
                    range_is_uri=True,
                    foreign_key_on=None,
                    silver_foreign_key=True,
                    silver_column_name=relationship.on[0].local if relationship.on else None,
                    is_functional=relationship.cardinality in {"many-to-one", "one-to-one"},
                    max_cardinality_classes=(
                        frozenset({domain_class.uri})
                        if relationship.cardinality in {"many-to-one", "one-to-one"}
                        else frozenset()
                    ),
                    junction_table_name=None,
                    nullable=relationship.missing_parent != "error",
                    conditional_on_type="",
                )
            )
    return tuple(facts)


def _authored(resource: str, predicate: str, value: str) -> AuthoredValuesFact:
    return AuthoredValuesFact(resource, predicate, (value,))


def _relationship_policies(
    bindings: tuple[EntityBinding, ...], context: ResolutionContext
) -> tuple[TemporalRelationshipFact, ...]:
    facts: list[TemporalRelationshipFact] = []
    for binding in bindings:
        adapted = adapt_temporal_relationships(binding)
        for relationship in adapted:
            prop = context.property(relationship.property_uri)
            if prop is None:
                continue
            uri = prop.uri
            mode = relationship.mode.value
            parent_time = relationship.parent_time
            facts.append(
                TemporalRelationshipFact(
                    property_uri=uri,
                    mode=_authored(uri, "silverForeignKeyTemporalMode", mode),
                    as_of_column=(
                        _authored(
                            uri,
                            "silverForeignKeyAsOfColumn",
                            parent_time.child_event_time_column,
                        )
                        if parent_time is not None
                        and parent_time.child_event_time_column is not None
                        else None
                    ),
                    interval=(
                        _authored(uri, "silverForeignKeyInterval", parent_time.interval.value)
                        if mode == "as-of" and parent_time is not None
                        else None
                    ),
                    time_zone=(
                        _authored(uri, "silverForeignKeyTimeZone", "UTC")
                        if mode == "as-of"
                        else None
                    ),
                    precision=(
                        _authored(uri, "silverForeignKeyPrecision", "microsecond")
                        if mode == "as-of"
                        else None
                    ),
                    cardinality=_authored(
                        uri,
                        "silverForeignKeyCardinality",
                        relationship.match_count.lookup_cardinality.value,
                    ),
                    missing_action=_authored(
                        uri,
                        "silverForeignKeyMissingPolicy",
                        (
                            "fail"
                            if relationship.missing_parent_action.value == "error"
                            else "unknown-member"
                        ),
                    ),
                    ambiguous_action=_authored(
                        uri,
                        "silverForeignKeyAmbiguousPolicy",
                        (
                            "fail"
                            if relationship.ambiguous_parent_action.value == "error"
                            else "retry"
                        ),
                    ),
                    late_parent_action=_authored(
                        uri,
                        "silverForeignKeyLateParentPolicy",
                        (
                            "fail"
                            if parent_time is None
                            or parent_time.late_parent_action.value == "error"
                            else (
                                "unknown-member"
                                if parent_time.late_parent_action.value == "null"
                                else "retry"
                            )
                        ),
                    ),
                    change_detection=_authored(
                        uri,
                        "silverForeignKeyChangeDetection",
                        str(bool(relationship.participates_in_change_detection)).lower(),
                    ),
                )
            )
    return tuple(facts)


def merge_bound_sources(
    bounds: tuple[BoundSources, ...],
    bindings: tuple[EntityBinding, ...],
    context: ResolutionContext,
    *,
    hub_root: str | Path,
    conformance_plans: tuple[ConformancePlan, ...] = (),
) -> BoundSources:
    """Merge independently adapted entities into one immutable domain input."""
    base = bounds[0]
    policy = base.policy_facts
    gold_extension = Path(hub_root) / "model" / "extensions" / f"{context.domain}-gold-ext.ttl"
    downstream_policy = (
        bind_policy_facts(
            Graph(),
            ontology_uri=context.ontology_iri,
            gold_extension=str(gold_extension),
        )
        if gold_extension.is_file()
        else None
    )
    plan_by_target = {
        group.target_class: group for plan in conformance_plans for group in plan.groups
    }
    bound_by_name = dict(zip((binding.name for binding in bindings), bounds, strict=True))

    multi_source: list[MultiSourcePolicyFact] = []
    multi_ref_by_class: dict[str, str] = {}
    precedence_by_class: dict[str, tuple[str, ...]] = {}
    deduplicated_classes: set[str] = set()
    for target_ref, group in sorted(plan_by_target.items()):
        target = context.klass(target_ref)
        if target is None:
            continue
        resource = f"binding:conformance:{group.group}"
        source_refs = tuple(
            bound_by_name[source.binding_name]
            .policy_facts.identities[0]
            .source_identities.values[0]
            for source in group.sources
        )
        deduplicate = group.union.mode == "deduplicate"
        multi_source.append(
            MultiSourcePolicyFact(
                resource_uri=resource,
                branch_relationship=_authored(
                    resource,
                    "branchRelationship",
                    "exactly-equivalent" if deduplicate else "disjoint",
                ),
                normalization=_authored(
                    resource,
                    "normalization",
                    "EntityBinding fields conform to one canonical target contract",
                ),
                source_precedence=_authored(
                    resource,
                    "sourcePrecedence",
                    (
                        f"declared-order:{','.join(source_refs)}"
                        if deduplicate
                        else "not-applicable-disjoint"
                    ),
                ),
                conflict=_authored(
                    resource,
                    "conflict",
                    "block" if deduplicate else "retain-branch-values",
                ),
                collision=_authored(
                    resource,
                    "collision",
                    "block" if deduplicate else "retain-source-scoped-identities",
                ),
                deletion=_authored(resource, "deletion", "retain-other-branches"),
                late_arrival=_authored(resource, "lateArrival", "reconcile-on-arrival"),
                reconciliation_tests=_authored(
                    resource,
                    "reconciliationTests",
                    f"binding-conformance:{group.group}",
                ),
            )
        )
        multi_ref_by_class[target.uri] = resource
        precedence_by_class[target.uri] = source_refs
        if deduplicate:
            deduplicated_classes.add(target.uri)

    identities = []
    identities_by_uri: dict[str, list] = {}
    for bound in bounds:
        for identity in bound.policy_facts.identities:
            identities_by_uri.setdefault(identity.resource_uri, []).append(identity)
    for uri, members in sorted(identities_by_uri.items()):
        first = members[0]
        source_refs = tuple(
            dict.fromkeys(value for member in members for value in member.source_identities.values)
        )
        identities.append(
            replace(
                first,
                source_identities=replace(first.source_identities, values=source_refs),
                strategy=(
                    _authored(uri, "identityStrategy", "deterministic-integration-key")
                    if uri in deduplicated_classes
                    else first.strategy
                ),
                key_scope=(
                    _authored(uri, "keyScope", "domain")
                    if uri in deduplicated_classes
                    else first.key_scope
                ),
                driving_source=(
                    _authored(uri, "drivingSource", precedence_by_class[uri][0])
                    if uri in precedence_by_class
                    else first.driving_source
                ),
                multi_source_policy_refs=(
                    _authored(uri, "multiSourcePolicy", multi_ref_by_class[uri])
                    if uri in multi_ref_by_class
                    else first.multi_source_policy_refs
                ),
            )
        )

    classes = {item.uri: item for bound in bounds for item in bound.classes}
    silver_by_model = {}
    schema_by_model = {}
    conformance_branches: dict[str, list] = {}
    conformance_bases: dict[str, object] = {}
    for binding, bound in zip(bindings, bounds, strict=True):
        for model in bound.silver_candidates:
            if binding.target_class not in plan_by_target:
                silver_by_model[model.identity.model_name] = model
                continue
            source = model.sources[0]
            branch_name = (
                f"{model.identity.model_name}__from_"
                f"{''.join(c if c.isalnum() else '_' for c in source.source_name).lower()}"
                f"__{''.join(c if c.isalnum() else '_' for c in source.table_name).lower()}"
            )
            branch = replace(
                model,
                identity=replace(
                    model.identity,
                    model_name=branch_name,
                    artifact_path=(
                        model.identity.artifact_path.rsplit("/", 1)[0] + f"/{branch_name}.sql"
                    ),
                ),
                kind=SilverModelKind.SOURCE_BRANCH,
            )
            conformance_branches.setdefault(binding.target_class, []).append(branch)
            conformance_bases.setdefault(binding.target_class, model)
        for model in bound.schema_candidates:
            schema_by_model.setdefault(model.name, model)
    for target_ref, branches in sorted(conformance_branches.items()):
        base_model = conformance_bases[target_ref]
        group = plan_by_target[target_ref]
        first_binding = next(binding for binding in bindings if binding.target_class == target_ref)
        integration_columns = tuple(
            context.property(field.property).column_name
            for field in first_binding.fields
            if isinstance(field.expression, ExprColumn)
            and field.expression.column in group.union.deduplicate_by
            and context.property(field.property) is not None
        )
        union = replace(
            base_model,
            kind=SilverModelKind.UNION,
            columns=tuple(
                replace(column, mapping_resource_uri="", expression=column.name)
                for column in base_model.columns
            ),
            sources=(),
            source_models=tuple(branch.identity.model_name for branch in branches),
            integration_key_expression=", ".join(integration_columns) or "_source_record_key",
        )
        for branch in branches:
            if branch.identity.model_name in silver_by_model:
                raise ValueError(
                    "conformance branch model name collision: "
                    f"{branch.identity.model_name!r} for {target_ref!r}"
                )
            silver_by_model[branch.identity.model_name] = branch
        silver_by_model[union.identity.model_name] = union

    class_sources: dict[str, list] = {}
    for bound in bounds:
        for class_uri, sources in bound.source_bindings.class_to_sources:
            class_sources.setdefault(class_uri, []).extend(sources)
    return replace(
        base,
        classes=tuple(classes[key] for key in sorted(classes)),
        systems=_merge_systems(bounds),
        virtual_table_uris=frozenset(uri for bound in bounds for uri in bound.virtual_table_uris),
        mappings=SourceMappings(
            tables=tuple(item for bound in bounds for item in bound.mappings.tables),
            columns=tuple(item for bound in bounds for item in bound.mappings.columns),
            namespaces=base.mappings.namespaces,
        ),
        source_bindings=SourceBindingsFact(
            active_contracts=(),
            virtual_table_uris=frozenset(),
            class_to_sources=tuple(
                (
                    class_uri,
                    tuple(
                        {
                            (source.table_uri, source.source_name, source.table_name): source
                            for source in sources
                        }[key]
                        for key in sorted(
                            {
                                (source.table_uri, source.source_name, source.table_name)
                                for source in sources
                            }
                        )
                    ),
                )
                for class_uri, sources in sorted(class_sources.items())
            ),
            folded_source_targets=(),
            warnings=(),
        ),
        binding_observations=tuple(
            {item.class_uri: item for bound in bounds for item in bound.binding_observations}[key]
            for key in sorted(
                {item.class_uri for bound in bounds for item in bound.binding_observations}
            )
        ),
        foreign_key_facts=_foreign_keys(bindings, context, hub_root),
        silver_candidates=tuple(silver_by_model[key] for key in sorted(silver_by_model)),
        schema_candidates=tuple(schema_by_model[key] for key in sorted(schema_by_model)),
        policy_facts=replace(
            policy,
            identities=tuple(identities),
            multi_source=tuple(multi_source),
            incremental=tuple(item for bound in bounds for item in bound.policy_facts.incremental),
            hashes=tuple(item for bound in bounds for item in bound.policy_facts.hashes),
            temporal_relationships=_relationship_policies(bindings, context),
            data_quality=context.data_quality_rules,
            gold=downstream_policy.gold if downstream_policy is not None else policy.gold,
            adapter_support=(
                downstream_policy.adapter_support
                if downstream_policy is not None
                else policy.adapter_support
            ),
            deviations=(
                downstream_policy.deviations if downstream_policy is not None else policy.deviations
            ),
        ),
        active_source_scope=ActiveSourceScope(
            tuple(item for bound in bounds for item in bound.active_source_scope.tables)
        ),
    )


def _relationship_output_column(
    binding: EntityBinding, source_column: str, context: ResolutionContext
) -> str | None:
    for field in binding.fields:
        if isinstance(field.expression, ExprColumn) and field.expression.column == source_column:
            prop = context.property(field.property)
            return prop.column_name if prop is not None else None
    return None


def _wire_relationships(
    bounds: tuple[BoundSources, ...],
    bindings: tuple[EntityBinding, ...],
    context: ResolutionContext,
    hub_root: str | Path,
) -> tuple[BoundSources, ...]:
    def quote(value: str) -> str:
        return (
            f"`{value.replace('`', '``')}`"
            if context.target_platform == "databricks"
            else (f"[{value.replace(']', ']]')}]")
        )

    by_target = {binding.target_class: binding for binding in bindings}
    wired: list[BoundSources] = []
    for bound, binding in zip(bounds, bindings, strict=True):
        joins: list[JoinSpec] = []
        fk_columns: list[ColumnSpec] = []
        relation = _resolved_binding_relation(binding, context)
        for relationship in binding.relationships:
            external = relationship.external_reference
            target_binding = by_target.get(relationship.target)
            target_class = _relationship_target_class(relationship, context, hub_root)
            prop = context.property(relationship.property)
            if (
                relation is None
                or target_class is None
                or prop is None
                or (external is None and target_binding is None)
                or (external is None and len(relationship.on) != 1)
            ):
                continue
            if external is None:
                join = relationship.on[0]
                assert target_binding is not None
                target_columns = (
                    _relationship_output_column(target_binding, join.foreign, context),
                )
                if target_columns[0] is None:
                    continue
                target_model = target_class.name.lower()
                description = f"Surrogate reference to {target_class.name}"
            else:
                target_columns = tuple(item.column for item in external.key)
                target_model = external.name
                description = f"Surrogate reference to external {external.domain}.{external.name}"
            fk_column = f"{target_model}_sk"
            joins.append(
                JoinSpec(
                    join_type="left",
                    alias=target_model,
                    condition="",
                    referenced_model=f"{{{{ ref('{target_model}') }}}}",
                    fk_column=fk_column,
                    source_alias="src",
                    source_column_uris=tuple(
                        relation.column_uri(join.local) for join in relationship.on
                    ),
                    target_columns=target_columns,
                    relationship_uri=prop.uri,
                    temporal_mode=relationship.mode.replace("non-temporal", "none"),
                    as_of_column=(
                        relationship.temporal.child_event_time
                        if relationship.temporal is not None
                        else ""
                    ),
                    parent_valid_from_column=(
                        relationship.temporal.parent_valid_from
                        if relationship.temporal is not None
                        else "_business_valid_from"
                    ),
                    parent_valid_to_column=(
                        relationship.temporal.parent_valid_to
                        if relationship.temporal is not None
                        else "_business_valid_to"
                    ),
                )
            )
            fk_columns.append(
                ColumnSpec(
                    name=fk_column,
                    expression=f"{quote(target_model)}.{quote(f'{target_model}_sk')}",
                    data_type="string",
                    canonical_type=CanonicalTypeSpec(CanonicalTypeKind.STRING),
                    nullable=relationship.missing_parent != "error",
                    role="foreign-key",
                    description=description,
                    tests=("not_null",) if relationship.missing_parent == "error" else (),
                    provenance=(f"relationship:{prop.uri}", "rule:DD-133"),
                )
            )
        silver = tuple(
            replace(
                model,
                columns=(*model.columns, *fk_columns),
                joins=(*model.joins, *joins),
            )
            for model in bound.silver_candidates
        )
        schema = tuple(
            replace(model, columns=(*model.columns, *fk_columns))
            for model in bound.schema_candidates
        )
        wired.append(replace(bound, silver_candidates=silver, schema_candidates=schema))
    return tuple(wired)


def _project_relationship_match_counts(shaped, bindings, context):
    def quote(value: str) -> str:
        return (
            f"`{value.replace('`', '``')}`"
            if context.target_platform == "databricks"
            else (f"[{value.replace(']', ']]')}]")
        )

    by_model = {
        context.klass(binding.target_class).name.lower(): binding
        for binding in bindings
        if context.klass(binding.target_class) is not None
    }
    models = []
    for model in shaped.silver_models:
        binding = by_model.get(model.identity.model_name)
        columns = model.columns
        if binding is not None:
            replacements: dict[str, tuple[str, str]] = {}
            partition = ", ".join(
                f"{quote('src')}.{quote(column)}" for column in binding.grain.columns
            )
            for relationship in binding.relationships:
                prop = context.property(relationship.property)
                target = context.klass(relationship.target)
                external = relationship.external_reference
                target_model = (
                    external.name
                    if external is not None
                    else target.name.lower()
                    if target is not None
                    else ""
                )
                if prop is not None and target_model:
                    replacements[temporal_match_count_column(prop.uri)] = (
                        f"COUNT({quote(target_model)}."
                        f"{quote(f'{target_model}_sk')}) "
                        f"OVER (PARTITION BY {partition})",
                        prop.uri,
                    )
            columns = tuple(
                (
                    replace(
                        column,
                        expression=replacements[column.name][0],
                        default_expression="",
                        runtime_generated=False,
                    )
                    if column.name in replacements
                    else column
                )
                for column in columns
            )
            columns = tuple(
                {column.name: column for column in reversed(columns)}[name]
                for name in dict.fromkeys(column.name for column in columns)
            )
            names = {column.name for column in columns}
            columns = (
                *columns,
                *(
                    ColumnSpec(
                        name=name,
                        expression=expression,
                        canonical_type=CanonicalTypeSpec(CanonicalTypeKind.INT64),
                        nullable=False,
                        role="foreign-key",
                        description=f"Match count for {property_uri}",
                        provenance=(
                            f"relationship:{property_uri}",
                            "rule:DD-109-temporal-fk",
                        ),
                        include_in_change_detection=False,
                    )
                    for name, (expression, property_uri) in replacements.items()
                    if name not in names
                ),
            )
        models.append(replace(model, columns=columns))
    count_columns = {
        model.identity.model_name: tuple(
            column
            for column in model.columns
            if column.name.startswith("_kairos_fk_") and column.name.endswith("_match_count")
        )
        for model in models
    }
    documents = tuple(
        replace(
            document,
            models=tuple(
                replace(
                    model,
                    columns=(
                        *model.columns,
                        *(
                            column
                            for column in count_columns.get(model.name, ())
                            if column.name not in {item.name for item in model.columns}
                        ),
                    ),
                )
                for model in document.models
            ),
        )
        for document in shaped.schema_documents
    )
    return replace(shaped, silver_models=tuple(models), schema_documents=documents)


def _explain_field(binding: EntityBinding) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            field.property,
            (
                field.expression.column
                if isinstance(field.expression, ExprColumn)
                else type(field.expression).__name__
            ),
        )
        for field in binding.fields
    )


def _explain_technical_field(binding: EntityBinding) -> tuple[ExplainTechnicalField, ...]:
    """Return DD-139 technical outputs, explicitly labelled apart from ontology ``fields``."""
    return tuple(
        ExplainTechnicalField(
            name=technical_field.name,
            expression=(
                technical_field.expression.column
                if isinstance(technical_field.expression, ExprColumn)
                else type(technical_field.expression).__name__
            ),
            type=technical_field.type,
            nullable=technical_field.nullable,
            purpose=technical_field.purpose,
        )
        for technical_field in binding.technical_fields
    )


def _quality_model_name(context: ResolutionContext, target_class: str) -> str:
    """Return the deterministic silver model name for a target class, or empty."""
    klass = context.klass(target_class)
    if klass is None:
        return ""
    return "".join(char if char.isalnum() else "_" for char in klass.name).strip("_").lower()


def _explain_quality(
    binding: EntityBinding,
    context: ResolutionContext,
    emitted_paths: set[str],
) -> tuple[tuple[ExplainQualityCheck, ...], tuple[str, ...]]:
    """Explain authored focused DQ checks and the tests each one actually emits.

    ``reconcile-rowcount`` and ``referential`` checks emit a focused singular dbt test file;
    the returned ``emitted_test`` is set only when that file is actually in the plan's artifact
    set (``emitted_paths``). ``not-null`` and ``unique`` become generic dbt schema tests carried
    in the model's ``schema.yml`` rather than standalone files.
    """
    model_name = _quality_model_name(context, binding.target_class)
    checks: list[ExplainQualityCheck] = []
    emitted_tests: list[str] = []
    referential_index = 0
    for check in binding.quality:
        emitted = ""
        if check.kind == "reconcile-rowcount" and model_name:
            candidate = f"tests/{binding.domain}/{model_name}__reconcile_rowcount.sql"
            emitted = candidate if candidate in emitted_paths else ""
        elif check.kind == "referential" and model_name:
            suffix = "" if referential_index == 0 else f"_{referential_index + 1}"
            candidate = f"tests/{binding.domain}/{model_name}__referential{suffix}.sql"
            referential_index += 1
            emitted = candidate if candidate in emitted_paths else ""
        elif check.kind in {"not-null", "unique"}:
            emitted = check.kind.replace("-", "_")
        if emitted and emitted.endswith(".sql"):
            emitted_tests.append(emitted)
        checks.append(
            ExplainQualityCheck(
                kind=check.kind,
                columns=check.columns,
                pointer=check.pointer,
                emitted_test=emitted,
            )
        )
    return tuple(checks), tuple(sorted(set(emitted_tests)))


def _adapter_safety_diagnostic(item: CompileDiagnostic) -> CompileDiagnostic:
    code_map = {
        "binding.unknown-relation": "safety.source-unresolved",
        "binding.unknown-column": "safety.column-unresolved",
        "binding.unknown-key-column": "safety.column-unresolved",
        "binding.unknown-class": "safety.class-unresolved",
        "binding.ambiguous-class": "safety.class-unresolved",
        "binding.unknown-property": "safety.property-unresolved",
        # #280: an object property under ``fields:`` is a misplaced relationship endpoint.
        # ``safety.relationship-endpoint`` already carries exactly that meaning, so the
        # closed 13-code ``SAFETY_RULE_CODES`` catalogue stays closed.
        "binding.object-property-in-fields": "safety.relationship-endpoint",
        "binding.unsupported-dbt-model-source": "safety.adapter-unsupported",
        "binding.unknown-identity-strategy": "safety.identity-incomplete",
    }
    code = code_map.get(item.code)
    if code is None and item.code.startswith("expression."):
        code = "safety.expression-unsafe"
    if code is None:
        return item
    return replace(item, code=code)


def _structural_safety_diagnostic(item: CompileDiagnostic) -> CompileDiagnostic:
    if item.code.startswith("expression."):
        return replace(item, code="safety.expression-unsafe")
    if item.code != "binding.schema":
        return item
    message = item.message
    pointer = item.location.pointer
    if pointer.startswith("/grain") or "'grain' is a required property" in message:
        return replace(item, code="safety.grain-missing")
    if pointer.startswith("/identity") or "'identity' is a required property" in message:
        return replace(item, code="safety.identity-incomplete")
    if pointer.startswith("/load") or "'load' is a required property" in message:
        return replace(item, code="safety.incremental-identity-incomplete")
    return item


def _binding_safety_diagnostics(
    binding: EntityBinding, context: ResolutionContext
) -> tuple[CompileDiagnostic, ...]:
    diagnostics: list[CompileDiagnostic] = []
    relation = _resolved_binding_relation(binding, context)
    columns = {column.name for column in relation.columns} if relation is not None else set()
    if binding.load.incremental is not None:
        merge_identity = binding.load.incremental.merge_identity
        if merge_identity != binding.identity.source_key or any(
            column not in columns for column in merge_identity
        ):
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.incremental-identity-incomplete",
                    message=(
                        "incremental mergeIdentity must resolve and exactly match "
                        "identity.sourceKey"
                    ),
                    location=SourceLocation(
                        path=binding.source_path,
                        pointer="/load/incremental/mergeIdentity",
                    ),
                    rule_id="DD-109-incremental",
                )
            )
    reserved = {
        "_business_valid_from",
        "_business_valid_to",
        "_cdc_operation",
        "_cdc_sequence",
        "_ingested_at",
        "_is_current",
        "_record_hash",
        "_source_record_key",
        "_source_updated_at",
        (
            f"{context.klass(binding.target_class).name.lower()}_sk"
            if context.klass(binding.target_class) is not None
            else ""
        ),
    }
    for field in binding.fields:
        prop = context.property(field.property)
        if prop is not None and prop.is_object_property:
            # #280: mirrors the adapter's ``binding.object-property-in-fields`` rejection so
            # ``compile --check`` still reports it when this binding is blocked before
            # ``adapt_binding`` ever runs. Same family as a misplaced relationship endpoint.
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.relationship-endpoint",
                    message=object_property_in_fields_message(field.property, prop),
                    location=SourceLocation(path=binding.source_path, pointer=field.pointer),
                    rule_id="DD-133-safety",
                )
            )
        if prop is not None and prop.column_name.lower() in reserved:
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.identity-role-collision",
                    message=(
                        f"mapped property column '{prop.column_name}' collides with a "
                        "compiler-owned identity/runtime role"
                    ),
                    location=SourceLocation(path=binding.source_path, pointer=field.pointer),
                    rule_id="DD-133-safety",
                )
            )
    for index, relationship in enumerate(binding.relationships):
        generated_fk = (
            f"{relationship.external_reference.name}_sk"
            if relationship.external_reference is not None
            else ""
        )
        reserved_with_external = {*reserved, generated_fk}
        for join_index, join in enumerate(relationship.on):
            if join.local.lower() not in reserved_with_external:
                continue
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.identity-role-collision",
                    message=(
                        f"relationship local column '{join.local}' collides with a "
                        "compiler-owned identity/runtime role"
                    ),
                    location=SourceLocation(
                        path=binding.source_path,
                        pointer=f"/relationships/{index}/join/{join_index}/local",
                    ),
                    rule_id="DD-133-safety",
                )
            )
    diagnostics.extend(_technical_field_safety_diagnostics(binding, context, reserved))
    return tuple(diagnostics)


def _technical_field_safety_diagnostics(
    binding: EntityBinding, context: ResolutionContext, reserved: set[str]
) -> tuple[CompileDiagnostic, ...]:
    """DD-139 technical-field validation: collisions, reserved names, ambiguous reuse.

    A technical field is materialized exactly like a semantic ``fields:`` entry (DD-107), so
    its authored output ``name`` must not collide -- case-insensitively -- with a mapped
    property's output column, another technical field, or a compiler-owned runtime/identity
    role. Reusing the same direct source column across multiple technical fields is allowed
    only when each reuse asserts a distinct ``purpose``; the same (source column, purpose)
    pair authored twice is ambiguous about which output the identity/quality/relationship
    consumer should resolve to.
    """
    diagnostics: list[CompileDiagnostic] = []
    semantic_outputs: dict[str, str] = {}
    for field in binding.fields:
        prop = context.property(field.property)
        if prop is not None:
            semantic_outputs.setdefault(prop.column_name.lower(), prop.column_name)
    technical_seen: dict[str, TechnicalField] = {}
    technical_by_source: dict[str, dict[str, TechnicalField]] = {}
    for index, technical_field in enumerate(binding.technical_fields):
        name_pointer = f"/technicalFields/{index}/name"
        lower = technical_field.name.lower()
        if lower in reserved:
            diagnostics.append(
                CompileDiagnostic(
                    code="technical-field.output-collision",
                    message=(
                        f"technical field output column '{technical_field.name}' collides "
                        "with a compiler-owned identity/runtime role"
                    ),
                    location=SourceLocation(path=binding.source_path, pointer=name_pointer),
                    rule_id="DD-139",
                )
            )
        semantic_match = semantic_outputs.get(lower)
        if semantic_match is not None:
            diagnostics.append(
                CompileDiagnostic(
                    code="technical-field.output-collision",
                    message=(
                        f"technical field output column '{technical_field.name}' collides "
                        f"(case-insensitively) with mapped property output column "
                        f"'{semantic_match}'"
                    ),
                    location=SourceLocation(path=binding.source_path, pointer=name_pointer),
                    rule_id="DD-139",
                )
            )
        previous = technical_seen.get(lower)
        if previous is not None:
            diagnostics.append(
                CompileDiagnostic(
                    code="technical-field.output-collision",
                    message=(
                        f"technical field output column '{technical_field.name}' collides "
                        f"(case-insensitively) with technical field '{previous.name}'"
                    ),
                    location=SourceLocation(path=binding.source_path, pointer=name_pointer),
                    rule_id="DD-139",
                )
            )
        else:
            technical_seen[lower] = technical_field
        if isinstance(technical_field.expression, ExprColumn):
            column = technical_field.expression.column
            by_purpose = technical_by_source.setdefault(column, {})
            duplicate = by_purpose.get(technical_field.purpose)
            if duplicate is not None:
                diagnostics.append(
                    CompileDiagnostic(
                        code="technical-field.duplicate-source-ambiguous",
                        message=(
                            f"source column '{column}' is used by technical fields "
                            f"'{duplicate.name}' and '{technical_field.name}' with the same "
                            f"purpose '{technical_field.purpose}'; duplicate source use requires "
                            "distinct, unambiguous purposes"
                        ),
                        location=SourceLocation(
                            path=binding.source_path,
                            pointer=f"/technicalFields/{index}/expression",
                        ),
                        rule_id="DD-139",
                    )
                )
            else:
                by_purpose[technical_field.purpose] = technical_field
    return tuple(diagnostics)


def _binding_domain(text: str) -> str | None:
    """Read only the scope discriminator before full closed-schema validation."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(document, dict):
        return None
    metadata = document.get("metadata")
    return str(metadata.get("domain", "")) if isinstance(metadata, dict) else None


def _binding_tier(text: str) -> str:
    """Read only the ``metadata.tier`` discriminator before full closed-schema validation.

    Absence means ``canonical`` (today's only behavior before ``metadata.tier`` existed).
    """
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return "canonical"
    if not isinstance(document, dict):
        return "canonical"
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        return "canonical"
    return str(metadata.get("tier", "canonical"))


def _binding_target_class(text: str) -> str:
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return ""
    if not isinstance(document, dict):
        return ""
    target = document.get("target")
    return str(target.get("class", "")) if isinstance(target, dict) else ""


def _binding_referenced_class_tokens(text: str) -> tuple[str, ...]:
    """Read every class token a binding names, before full closed-schema validation.

    DD-144: the entity's own ``target.class`` plus every relationship's ``target`` — a
    relationship may point at another entity's (possibly accelerator-direct) class, so its
    token needs the same fallback resolution opportunity in ``_ontology_symbols`` as the
    entity target does. Best-effort only: an unparsable or malformed document yields no
    tokens here and is reported through the normal schema-validation diagnostics instead.
    """
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return ()
    if not isinstance(document, dict):
        return ()
    tokens: list[str] = []
    target = document.get("target")
    if isinstance(target, dict):
        target_class = target.get("class")
        if target_class:
            tokens.append(str(target_class))
    relationships = document.get("relationships")
    if isinstance(relationships, list):
        for relationship in relationships:
            if isinstance(relationship, dict) and relationship.get("target"):
                tokens.append(str(relationship["target"]))
    return tuple(tokens)


def _external_target_domain(hub_root: str, current_domain: str, target_class: str) -> str | None:
    binding_dir = Path(hub_root) / "integration" / "bindings"
    for path in sorted(binding_dir.glob("*.binding.yaml")):
        text = path.read_text(encoding="utf-8")
        domain = _binding_domain(text)
        if not domain or domain == current_domain:
            continue
        if _binding_target_class(text) == target_class:
            return domain
    return None


def _relationship_diagnostics(
    binding: EntityBinding,
    selected: dict[str, EntityBinding],
    context: ResolutionContext,
    hub_root: str,
) -> tuple[CompileDiagnostic, ...]:
    diagnostics: list[CompileDiagnostic] = []
    relation = _resolved_binding_relation(binding, context)
    if relation is None:
        return ()
    local_columns = {column.name: column for column in relation.columns} if relation else {}
    targets = {item.target_class: item for item in selected.values()}
    for index, relationship in enumerate(binding.relationships):
        pointer = f"/relationships/{index}"
        external = relationship.external_reference
        target_binding = targets.get(relationship.target)
        target_relation = (
            _resolved_binding_relation(target_binding, context)
            if target_binding is not None
            else None
        )
        prop = context.property(relationship.property)
        source_class = context.klass(binding.target_class)
        target_class = _relationship_target_class(relationship, context, hub_root)
        if external is None and target_binding is None:
            external_domain = _external_target_domain(hub_root, context.domain, relationship.target)
            if external_domain:
                message = (
                    f"relationship '{relationship.property}' target "
                    f"'{relationship.target}' is bound in domain '{external_domain}', outside "
                    "this domain's compile scope; declare an external reference "
                    "(DD-133 §7) or move the target in-scope"
                )
            else:
                message = (
                    f"relationship '{relationship.property}' target "
                    f"'{relationship.target}' does not resolve in compile scope; "
                    "cross-domain targets require a declared external reference"
                )
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.relationship-endpoint",
                    message=message,
                    location=SourceLocation(path=binding.source_path, pointer=pointer),
                )
            )
            continue
        if prop is None:
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.relationship-endpoint",
                    message=f"relationship property '{relationship.property}' does not resolve",
                    location=SourceLocation(path=binding.source_path, pointer=pointer),
                )
            )
            continue
        if external is not None and target_class is None:
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.relationship-endpoint",
                    message=(
                        f"relationship '{relationship.property}' target "
                        f"'{relationship.target}' does not resolve as an ontology class"
                    ),
                    location=SourceLocation(path=binding.source_path, pointer=pointer),
                )
            )
            continue
        if source_class is None:
            continue
        if (
            target_class is None
            or (prop.domain_uris and source_class.uri not in prop.domain_uris)
            or (prop.range_uri and prop.range_uri != target_class.uri)
        ):
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.relationship-endpoint",
                    message=(
                        f"relationship '{relationship.property}' is incompatible with "
                        f"'{binding.target_class}' -> '{relationship.target}'"
                    ),
                    location=SourceLocation(path=binding.source_path, pointer=pointer),
                )
            )
            continue
        if external is not None:
            declared_key = tuple(item.column for item in external.key)
            authored_foreign = tuple(join.foreign for join in relationship.on)
            if authored_foreign != declared_key:
                diagnostics.append(
                    CompileDiagnostic(
                        code="safety.relationship-endpoint",
                        message=(
                            "relationship externalReference key mismatch: join.foreign "
                            f"{authored_foreign!r} must exactly match declared key "
                            f"{declared_key!r}"
                        ),
                        location=SourceLocation(
                            path=binding.source_path,
                            pointer=f"{pointer}/externalReference/key",
                        ),
                    )
                )
                continue
        if relationship.temporal is not None:
            if (
                relationship.mode == "as-of"
                and relationship.temporal.child_event_time not in local_columns
            ):
                diagnostics.append(
                    CompileDiagnostic(
                        code="safety.column-unresolved",
                        message=(
                            "temporal child event-time column "
                            f"'{relationship.temporal.child_event_time}' does not resolve"
                        ),
                        location=SourceLocation(
                            path=binding.source_path,
                            pointer=f"{pointer}/temporal/childEventTime",
                        ),
                    )
                )
        if relationship.ambiguous_parent != "error":
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.adapter-unsupported",
                    message="ambiguousParent 'first' is deferred beyond the v5 first slice",
                    location=SourceLocation(
                        path=binding.source_path, pointer=f"{pointer}/ambiguousParent"
                    ),
                )
            )
            continue
        if external is None and len(relationship.on) != 1:
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.adapter-unsupported",
                    message="composite relationship joins are deferred beyond the v5 first slice",
                    location=SourceLocation(path=binding.source_path, pointer=f"{pointer}/join"),
                )
            )
            continue
        foreign_columns = (
            {column.name: column for column in target_relation.columns} if target_relation else {}
        )
        external_types = (
            {item.column: item.type for item in external.key} if external is not None else {}
        )
        for join_index, join in enumerate(relationship.on):
            local = local_columns.get(join.local)
            foreign = foreign_columns.get(join.foreign)
            join_pointer = f"{pointer}/join/{join_index}"
            if local is None:
                diagnostics.append(
                    CompileDiagnostic(
                        code="safety.column-unresolved",
                        message=f"relationship local column '{join.local}' does not resolve",
                        location=SourceLocation(path=binding.source_path, pointer=join_pointer),
                    )
                )
                continue
            if external is None and foreign is None:
                diagnostics.append(
                    CompileDiagnostic(
                        code="safety.column-unresolved",
                        message=f"relationship foreign column '{join.foreign}' does not resolve",
                        location=SourceLocation(path=binding.source_path, pointer=join_pointer),
                    )
                )
                continue
            if external is not None:
                key_type = external_types.get(join.foreign, "")
                if not key_type or not _source_types_compatible(local.data_type, key_type):
                    diagnostics.append(
                        CompileDiagnostic(
                            code="safety.type-incompatible",
                            message=(
                                f"relationship local column '{join.local}' "
                                f"({local.data_type}) is incompatible with external key "
                                f"'{join.foreign}' ({key_type})"
                            ),
                            location=SourceLocation(path=binding.source_path, pointer=join_pointer),
                        )
                    )
                continue
            if foreign is not None and _source_type(local.data_type) != _source_type(
                foreign.data_type
            ):
                diagnostics.append(
                    CompileDiagnostic(
                        code="safety.type-incompatible",
                        message=(
                            f"relationship columns '{join.local}' ({local.data_type}) and "
                            f"'{join.foreign}' ({foreign.data_type}) have incompatible types"
                        ),
                        location=SourceLocation(path=binding.source_path, pointer=join_pointer),
                    )
                )
            if (
                target_binding is not None
                and _relationship_output_column(target_binding, join.foreign, context) is None
            ):
                diagnostics.append(
                    CompileDiagnostic(
                        code="safety.relationship-endpoint",
                        message=(
                            f"relationship foreign column '{join.foreign}' is not "
                            "mapped by the target binding"
                        ),
                        location=SourceLocation(path=binding.source_path, pointer=join_pointer),
                    )
                )
    relationship_columns = [
        {join.local for join in relationship.on} for relationship in binding.relationships
    ]
    for check in binding.quality:
        if check.kind == "referential" and set(check.columns) not in relationship_columns:
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.relationship-endpoint",
                    message=(
                        "referential quality columns must exactly match one "
                        "authored relationship join"
                    ),
                    location=SourceLocation(path=binding.source_path, pointer=check.pointer),
                )
            )
    return tuple(diagnostics)


def _focused_quality_artifacts(
    bindings: tuple[EntityBinding, ...], context: ResolutionContext
) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    targets = {binding.target_class: binding for binding in bindings}

    def source_sql(relation: ResolvedRelation) -> str:
        if relation.connection_type == "dbt":
            return f"{{{{ ref({json.dumps(relation.table_name)}) }}}}"
        return (
            f"{{{{ source({json.dumps(relation.system_label)}, "
            f"{json.dumps(relation.table_name)}) }}}}"
        )

    def parent_sql(relationship: RelationshipSpec) -> str:
        external = relationship.external_reference
        if external is not None:
            return f"{{{{ ref({json.dumps(external.name)}) }}}}"
        target_binding = targets.get(relationship.target)
        parent = (
            _resolved_binding_relation(target_binding, context)
            if target_binding is not None
            else None
        )
        return source_sql(parent) if parent is not None else ""

    for binding in bindings:
        relation = _resolved_binding_relation(binding, context)
        klass = context.klass(binding.target_class)
        if relation is None or klass is None:
            continue
        model_name = (
            "".join(char if char.isalnum() else "_" for char in klass.name).strip("_").lower()
        )
        if any(check.kind == "reconcile-rowcount" for check in binding.quality):
            path = f"tests/{binding.domain}/{model_name}__reconcile_rowcount.sql"
            artifacts[path] = (
                "-- DD-133 focused source-to-model row-count reconciliation\n"
                "with source_count as (\n"
                f"  select count(*) as n from {source_sql(relation)}\n"
                "), model_count as (\n"
                f"  select count(*) as n from {{{{ ref('{model_name}') }}}}\n"
                ")\n"
                "select source_count.n as source_rows, model_count.n as model_rows\n"
                "from source_count cross join model_count\n"
                "where source_count.n <> model_count.n\n"
            )
        referential = [check for check in binding.quality if check.kind == "referential"]
        for check_index, check in enumerate(referential):
            relationship = next(
                (
                    item
                    for item in binding.relationships
                    if set(check.columns) == {join.local for join in item.on}
                ),
                None,
            )
            if relationship is None:
                continue
            parent_ref = parent_sql(relationship)
            if not parent_ref:
                continue
            adapter = context.target_platform
            predicates = " and ".join(
                f"child.{quote_mapping_identifier(join.local, adapter)} = "
                f"parent.{quote_mapping_identifier(join.foreign, adapter)}"
                for join in relationship.on
            )
            missing = relationship.on[0].foreign
            local = quote_mapping_identifier(relationship.on[0].local, adapter)
            missing_identifier = quote_mapping_identifier(missing, adapter)
            suffix = "" if check_index == 0 else f"_{check_index + 1}"
            path = f"tests/{binding.domain}/{model_name}__referential{suffix}.sql"
            artifacts[path] = (
                "-- DD-133 focused source referential check\n"
                f"select child.* from {source_sql(relation)} as child\n"
                f"left join {parent_ref} as parent on {predicates}\n"
                f"where child.{local} is not null "
                f"and parent.{missing_identifier} is null\n"
            )
    return artifacts


def _focused_quality_artifact_paths(
    bindings: tuple[EntityBinding, ...], context: ResolutionContext
) -> set[str]:
    paths: set[str] = set()
    targets = {binding.target_class: binding for binding in bindings}
    for binding in bindings:
        klass = context.klass(binding.target_class)
        if klass is None:
            continue
        model_name = (
            "".join(char if char.isalnum() else "_" for char in klass.name).strip("_").lower()
        )
        if any(check.kind == "reconcile-rowcount" for check in binding.quality):
            paths.add(f"tests/{binding.domain}/{model_name}__reconcile_rowcount.sql")
        referential = [check for check in binding.quality if check.kind == "referential"]
        for check_index, check in enumerate(referential):
            relationship = next(
                (
                    item
                    for item in binding.relationships
                    if set(check.columns) == {join.local for join in item.on}
                ),
                None,
            )
            if relationship is None or (
                relationship.external_reference is None and targets.get(relationship.target) is None
            ):
                continue
            suffix = "" if check_index == 0 else f"_{check_index + 1}"
            paths.add(f"tests/{binding.domain}/{model_name}__referential{suffix}.sql")
    return paths


def _planned_artifact_paths(
    shaped,
    materialized,
    bindings: tuple[EntityBinding, ...],
    context: ResolutionContext,
) -> tuple[str, ...]:
    """Collect canonical v5 renderer destinations from typed plans."""
    if shaped is None or materialized is None:
        return ()
    paths = (
        {source.artifact_path for source in shaped.source_catalogs}
        | {
            model.identity.artifact_path
            for model in shaped.silver_models
            if model.identity.outcome.value == "generated"
        }
        | {document.artifact_path for document in shaped.schema_documents}
        | {f"macros/{name}" for name in shaped.macros.names}
        | _focused_quality_artifact_paths(bindings, context)
    )
    if materialized.silver is not None and materialized.silver.models:
        paths.update(
            (
                materialized.silver.ddl_artifact_path,
                materialized.silver.constraint_artifact_path,
                materialized.silver.erd_artifact_path,
                materialized.silver.parity_artifact_path,
            )
        )
    if materialized.project.emit:
        paths.update(("README.md", "dbt_project.yml", "packages.yml"))
    for quality in materialized.quality_models:
        for rule in quality.rules:
            paths.add(rule.result_artifact_path)
            paths.add(rule.test_artifact_path)
        if quality.quarantines_rows:
            paths.add(quality.evaluated_artifact_path)
            paths.add(quality.quarantine_artifact_path)
    if materialized.policy is not None and materialized.quality_models:
        paths.add("contracts/dq-runtime-result-contract.schema.json")
    return tuple(sorted(path for path in paths if path))


def build_compile_plan(hub_root: str | Path, domain: str) -> CompilePlan:
    """Build the canonical graph-free plan without rendering or writing artifacts."""
    scope, context = resolve_scope(Path(hub_root), domain)
    logger.debug(
        "compile scope resolved: domain=%s binding_paths=%d provenance=%s",
        domain,
        len(scope.binding_paths),
        scope.provenance_hash(),
    )
    diagnostics: list[CompileDiagnostic] = list(scope.prefix_warnings)
    specs: list[EntityBindingSpec] = []
    valid_bindings: list[EntityBinding] = []
    bounds: list[BoundSources] = []
    selected_bindings: list[EntityBinding] = []
    for path_text in scope.binding_paths:
        path = Path(path_text)
        text = path.read_text(encoding="utf-8")
        declared_domain = _binding_domain(text)
        if declared_domain not in {None, domain}:
            logger.debug(
                "binding skipped (domain mismatch): %s declared=%s", path.name, declared_domain
            )
            continue
        try:
            binding = load_entity_binding(text, path=str(path))
        except CompileError as exc:
            diagnostics.extend(_structural_safety_diagnostic(item) for item in exc.diagnostics)
            logger.debug(
                "binding blocked (structural errors): %s codes=%s",
                path.name,
                _codes_of(exc.diagnostics),
            )
            continue
        if binding.domain != domain:
            logger.debug("binding skipped (binding.domain mismatch): %s", path.name)
            continue
        selected_bindings.append(binding)
    if not selected_bindings and not diagnostics:
        diagnostics.append(
            CompileDiagnostic(
                code="scope.no-bindings-authored",
                message=f"no EntityBinding documents select domain '{domain}'",
                location=SourceLocation(path=scope.hub_root),
            )
        )
    conformance_plans, conformance_diagnostics, conformance_blocked = _conformance_plans(
        tuple(selected_bindings), context, scope
    )
    diagnostics.extend(conformance_diagnostics)
    selected_by_name = {binding.name: binding for binding in selected_bindings}
    for binding in selected_bindings:
        if binding.name in conformance_blocked:
            specs.append(EntityBindingSpec(binding=binding, blocked=True))
            continue
        binding_safety = _binding_safety_diagnostics(binding, context)
        if binding_safety:
            diagnostics.extend(binding_safety)
            specs.append(EntityBindingSpec(binding=binding, blocked=True))
            continue
        if binding.source.dbt_model is not None:
            try:
                resolve_dbt_model_source(binding, scope.hub_root)
            except CompileError as exc:
                diagnostics.extend(exc.diagnostics)
                specs.append(EntityBindingSpec(binding=binding, blocked=True))
                continue
        try:
            adapt_temporal_relationships(binding)
        except CompileError as exc:
            diagnostics.extend(exc.diagnostics)
            specs.append(EntityBindingSpec(binding=binding, blocked=True))
            continue
        relationship_diagnostics = _relationship_diagnostics(
            binding, selected_by_name, context, scope.hub_root
        )
        if relationship_diagnostics:
            diagnostics.extend(relationship_diagnostics)
            specs.append(EntityBindingSpec(binding=binding, blocked=True))
            continue
        try:
            bound = adapt_binding(binding, context)
            relationship_hash_is_deferred = any(
                relationship.temporal is not None
                and relationship.temporal.change_detection == "include"
                for relationship in binding.relationships
            )
            if not relationship_hash_is_deferred:
                individual_contract = normalize_contract(bound, ExecutionMode.FAIL_FAST)
                individual_shape = shape_project(individual_contract)
                plan_materialization(individual_contract, individual_shape)
            valid_bindings.append(binding)
            bounds.append(bound)
            specs.append(EntityBindingSpec(binding=binding))
        except CompileError as exc:
            diagnostics.extend(_adapter_safety_diagnostic(item) for item in exc.diagnostics)
            specs.append(EntityBindingSpec(binding=binding, blocked=True))
            logger.debug(
                "binding blocked (adapter): %s codes=%s", path.name, _codes_of(exc.diagnostics)
            )
        except Exception as exc:
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.type-incompatible",
                    message=f"entity normalization failed: {exc}",
                    location=SourceLocation(path=binding.source_path),
                )
            )
            specs.append(EntityBindingSpec(binding=binding, blocked=True))
            logger.debug("binding blocked (normalization): %s error=%s", path.name, exc)
    logger.debug(
        "binding selection: selected=%d valid=%d blocked=%d",
        len(selected_bindings),
        len(valid_bindings),
        sum(1 for s in specs if s.blocked),
    )
    contract = None
    shaped = None
    materialized = None
    if bounds:
        try:
            wired_bounds = _wire_relationships(
                tuple(bounds), tuple(valid_bindings), context, scope.hub_root
            )
            merged = merge_bound_sources(
                wired_bounds,
                tuple(valid_bindings),
                context,
                hub_root=scope.hub_root,
                conformance_plans=conformance_plans,
            )
            contract = normalize_contract(merged, ExecutionMode.FAIL_FAST)
            shaped = _project_relationship_match_counts(
                shape_project(contract), tuple(valid_bindings), context
            )
            materialized = plan_materialization(contract, shaped)
        except Exception as exc:  # downstream contracts expose several precise exception types
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.type-incompatible",
                    message=f"projection normalization failed: {exc}",
                    location=SourceLocation(path=scope.hub_root),
                )
            )
    artifact_paths = _planned_artifact_paths(shaped, materialized, tuple(valid_bindings), context)
    conformance_owner = {
        group.target_class: group.sources[0].binding_name
        for plan in conformance_plans
        for group in plan.groups
    }
    specs = [
        replace(
            spec,
            artifact_paths=(
                ()
                if spec.blocked
                else tuple(
                    path
                    for path in artifact_paths
                    if path.endswith(
                        "/"
                        + (
                            context.klass(spec.binding.target_class).name.lower()
                            if context.klass(spec.binding.target_class)
                            else spec.binding.name.replace("-", "_")
                        )
                        + ".sql"
                    )
                    and (
                        spec.binding.target_class not in conformance_owner
                        or conformance_owner[spec.binding.target_class] == spec.binding.name
                    )
                )
            ),
        )
        for spec in specs
    ]
    ir = CanonicalProjectIR(
        domain=domain,
        entities=tuple(specs),
        provenance_hash=scope.provenance_hash(),
        scope=scope,
        artifact_paths=artifact_paths,
    )
    diagnostics.extend(run_safety_kernel(ir))
    ordered = order_compile_diagnostics(diagnostics)
    binding_paths = {spec.binding.source_path for spec in specs}
    entity_plans = tuple(
        CompileEntityPlan(
            binding=spec.binding,
            diagnostics=tuple(
                item for item in ordered if item.location.path == spec.binding.source_path
            ),
            artifact_paths=spec.artifact_paths,
            blocked=spec.blocked,
        )
        for spec in specs
    )
    project_diagnostics = tuple(item for item in ordered if item.location.path not in binding_paths)
    return CompilePlan(
        scope=scope,
        resolution=context,
        bindings=tuple(selected_bindings),
        normalized_contract=contract,
        shaped_project=shaped,
        silver_registry=shaped.silver_registry if shaped is not None else None,
        materialization_plan=materialized,
        planned_artifacts=tuple(
            PlannedCompileArtifact(
                path=path,
                entity_name=next(
                    (
                        entity.binding.name
                        for entity in entity_plans
                        if path in entity.artifact_paths
                    ),
                    "",
                ),
            )
            for path in artifact_paths
        ),
        entities=entity_plans,
        project_diagnostics=project_diagnostics,
        diagnostics=CompileDiagnostics(ordered),
        project_ir=ir,
        blocked=CompileDiagnostics(ordered).has_errors,
    )


def _explain_data_quality(quality: object) -> tuple[ExplainDataQuality, ...]:
    """Explain rendered DD-115 class-attached DQ rules for one silver model."""
    if quality is None:
        return ()
    quarantine = quality.quarantine_artifact_path if quality.quarantines_rows else ""
    return tuple(
        ExplainDataQuality(
            rule_id=item.rule.rule_id.value,
            kind=item.rule.check.check_kind.value.value,
            scope=item.rule.scope.value,
            action=item.rule.action.value.value,
            severity=item.rule.severity.value.value,
            result_model=item.result_artifact_path,
            result_test=item.test_artifact_path,
            quarantine=quarantine,
        )
        for item in quality.rules
    )


def _explain_plan(plan: CompilePlan, artifact_paths: tuple[str, ...]) -> ExplainReport:
    """Build the explicit serializable explain view of a typed compile plan."""
    valid_bindings = tuple(entity.binding for entity in plan.entities if not entity.blocked)
    emitted_quality_paths = _focused_quality_artifact_paths(valid_bindings, plan.resolution)
    explained_quality = {
        entity.binding.name: _explain_quality(
            entity.binding, plan.resolution, emitted_quality_paths
        )
        for entity in plan.entities
        if not entity.blocked
    }
    quality_by_model = {}
    materialized = plan.materialization_plan
    if materialized is not None:
        quality_by_model = {item.model_name: item for item in materialized.quality_models}
    return ExplainReport(
        domain=plan.domain,
        provenance_hash=plan.provenance_hash,
        binding_paths=plan.scope.binding_paths,
        ontology_paths=plan.scope.ontology_paths,
        entities=tuple(
            ExplainEntity(
                name=entity.binding.name,
                source=(
                    entity.binding.source.relation
                    or (
                        entity.binding.source.dbt_model.name
                        if entity.binding.source.dbt_model is not None
                        else ""
                    )
                ),
                target_class=entity.binding.target_class,
                grain=entity.binding.grain.columns,
                identity_strategy=entity.binding.identity.strategy,
                fields=_explain_field(entity.binding),
                technical_fields=_explain_technical_field(entity.binding),
                relationships=tuple(rel.target for rel in entity.binding.relationships),
                source_kind=(
                    "dbt-model" if entity.binding.source.dbt_model is not None else "relation"
                ),
                load=ExplainLoad(
                    mode=entity.binding.load.mode,
                    scd=entity.binding.load.scd,
                    merge_identity=(
                        entity.binding.load.incremental.merge_identity
                        if entity.binding.load.incremental is not None
                        else ()
                    ),
                    canonical_hash_inputs=(
                        entity.binding.load.incremental.canonical_hash_inputs
                        if entity.binding.load.incremental is not None
                        else ()
                    ),
                ),
                relationship_shapes=tuple(
                    ExplainRelationship(
                        target=rel.target,
                        mode=rel.mode,
                        cardinality=rel.cardinality,
                        temporal=rel.temporal is not None,
                    )
                    for rel in entity.binding.relationships
                ),
                conformance=(
                    ExplainConformance(
                        group=entity.binding.conformance.group,
                        source_precedence=entity.binding.conformance.source_precedence,
                        conflict=entity.binding.conformance.conflict,
                        union_mode=entity.binding.conformance.union.mode,
                    )
                    if entity.binding.conformance is not None
                    else None
                ),
                quality=explained_quality.get(entity.binding.name, ((), ()))[0],
                emitted_tests=explained_quality.get(entity.binding.name, ((), ()))[1],
                data_quality=_explain_data_quality(
                    quality_by_model.get(
                        _quality_model_name(plan.resolution, entity.binding.target_class)
                    )
                ),
                blocked=entity.blocked,
            )
            for entity in plan.entities
        ),
        artifact_paths=artifact_paths,
    )


def render_compile_plan(plan: CompilePlan) -> tuple[tuple[str, str], ...]:
    """Render one already-built plan without resolving or rebuilding compiler phases."""
    if not plan.can_render:
        return ()
    artifacts = render_canonical_project(plan.shaped_project, plan.materialization_plan)
    valid_bindings = tuple(entity.binding for entity in plan.entities if not entity.blocked)
    artifacts.update(_focused_quality_artifacts(valid_bindings, plan.resolution))
    return tuple(sorted(artifacts.items()))


def compile_plan_result(
    plan: CompilePlan,
    mode: CompileMode | str = CompileMode.CHECK,
    *,
    render: bool | None = None,
) -> CompileResult:
    """Create an explicit compatibility/result view without rebuilding ``plan``.

    Check and explain views remain byte-free by default; emit renders once from the typed
    plan. ``compile_domain`` opts into rendering for all modes to retain its established
    artifact-bearing result contract.
    """
    selected_mode = CompileMode(mode)
    should_render = selected_mode is CompileMode.EMIT if render is None else render
    try:
        artifacts = render_compile_plan(plan) if should_render else ()
        diagnostics = plan.diagnostics
    except Exception as exc:
        diagnostic = CompileDiagnostic(
            code="compiler.render-failed",
            message=f"projection rendering failed: {exc}",
            location=SourceLocation(path=plan.scope.hub_root),
        )
        diagnostics = CompileDiagnostics(
            order_compile_diagnostics((*plan.diagnostics.items, diagnostic))
        )
        artifacts = ()
    artifact_paths = tuple(path for path, _ in artifacts)
    return CompileResult(
        domain=plan.domain,
        mode=selected_mode.value,
        diagnostics=diagnostics,
        provenance_hash=plan.provenance_hash,
        artifacts=artifacts,
        explain=_explain_plan(plan, artifact_paths or plan.artifact_paths),
        ir=plan.project_ir,
        plan=plan,
    )


def compile_domain(
    hub_root: str | Path | CompilePlan,
    domain: str | None = None,
    mode: CompileMode | str = CompileMode.CHECK,
) -> CompileResult:
    """Return a compatibility result view over one canonical compile plan."""
    selected_mode = CompileMode(mode)
    cached_plan = isinstance(hub_root, CompilePlan)
    logger.debug(
        "compile domain: domain=%s mode=%s cached_plan=%s",
        domain or "",
        selected_mode.value,
        cached_plan,
    )
    try:
        plan = hub_root if cached_plan else build_compile_plan(hub_root, domain or "")
    except CompileError as exc:
        logger.debug(
            "compile domain aborted (compile errors): codes=%s", _codes_of(exc.diagnostics)
        )
        return CompileResult(domain or "", selected_mode.value, CompileDiagnostics(exc.diagnostics))
    return compile_plan_result(plan, selected_mode, render=True)
