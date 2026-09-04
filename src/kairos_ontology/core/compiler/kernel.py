# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Stateless v5 compiler kernel (DD-133)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from dataclasses import dataclass, replace

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD
import yaml

from kairos_ontology import __version__

from ..adapters import UnsupportedAdapterError, resolve_adapter
from ..hub_config import HubConfigError, load_hub_config
from ..ontology_loader import SemanticProfile, load_ontology
from ..ontology_ops import PropertyInfo, list_classes
from ..projections.uri_utils import camel_to_snake, dbt_source_name
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
from ..projections.dbt.policy_normalize import PolicyNormalizationError, _source_type
from ..projections.dbt.silver_contract import canonical_type_label
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
    system_fact_for_relation,
)
from .contract_conformance import (
    contract_binding_diagnostics,
    contract_resolution_diagnostics,
    models_by_class,
)
from .contract_emission import (
    apply_column_names,
    expand_binding,
    mark_padded_columns,
    padded_column_names,
)
from .contracts import SilverContract, load_silver_contract
from .bindings import (
    EntityBinding,
    ExprCase,
    ExprColumn,
    ExprFunction,
    ExprMacro,
    ExprOperator,
    Expression,
    FieldMapping,
    RelationshipSpec,
    TechnicalField,
    load_entity_binding,
)
from .compile import CompileMode
from .conformance import ConformancePlan, ConformanceTypeContract, build_conformance_plan
from .dbt_source import (
    SEED_PROPERTIES_SUFFIXES,
    SUPPORTED_SOURCE_FORMS,
    check_target_class_match,
    extract_refs,
    extract_sources,
    resolve_dbt_model_dependency_paths,
    resolve_dbt_model_source,
)
from .ir import CanonicalProjectIR, EntityBindingSpec
from .plan import CompileEntityPlan, CompilePlan, PlannedCompileArtifact, PlannedDbtDependency
from .quality import run_safety_kernel
from .result import (
    CompileDiagnostic,
    CompileDiagnostics,
    CompileError,
    CompileResult,
    ExplainConformance,
    ExplainDataQuality,
    ExplainEntity,
    ExplainGrainMechanism,
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


def _ambiguous_imported_prefix_origins(
    loaded, root_path: Path
) -> dict[str, dict[str, tuple[str, ...]]]:
    """Return ambiguous imported prefixes as ``{prefix: {namespace: declaring paths}}``.

    The single walk behind :func:`_ambiguous_imported_prefixes`. It also records *which
    file* declared each candidate namespace: naming only the namespaces left diagnosing
    a collision to grepping the vendored reference models by hand (#699), and
    ``source.manifest.source_path`` is already in hand here, so the provenance costs
    nothing to collect.
    """
    imported: dict[str, dict[str, set[str]]] = {}
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
            for namespace in namespaces:
                imported.setdefault(prefix, {}).setdefault(namespace, set()).add(path)
    return {
        prefix: {
            namespace: tuple(sorted(paths))
            for namespace, paths in sorted(by_namespace.items())
        }
        for prefix, by_namespace in imported.items()
        if len(by_namespace) > 1
    }


def _ambiguous_imported_prefixes(loaded, root_path: Path) -> dict[str, tuple[str, ...]]:
    """Return imported prefixes (no root declaration) bound to 2+ distinct namespaces.

    Shared by :func:`_prefix_diagnostics` (to raise ``safety.prefix-ambiguous``) and the
    ``safety.class-unresolved`` cross-reference (#674): both need the same "which
    prefixes are ambiguous, and which namespaces do they candidate for" data, computed
    once so the two diagnostics can never disagree about it.
    """
    return {
        prefix: tuple(by_namespace)
        for prefix, by_namespace in _ambiguous_imported_prefix_origins(loaded, root_path).items()
    }


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
    origins_by_prefix = _ambiguous_imported_prefix_origins(loaded, root_path)
    for prefix, origins in sorted(origins_by_prefix.items()):
        label = prefix or ":"
        namespaces = tuple(origins)
        candidates = " ".join(
            f"@prefix {prefix}: <{namespace}> ." for namespace in namespaces
        )
        # Name the declaring files, not just the namespaces: without them, finding
        # the collision meant grepping the vendored reference models by hand (#699).
        declared_by = "; ".join(
            f"{namespace} declared in {', '.join(paths)}"
            for namespace, paths in origins.items()
        )
        diagnostics.append(
            CompileDiagnostic(
                code="safety.prefix-ambiguous",
                message=(
                    f"imported prefix '{label}' maps to multiple namespaces "
                    f"without a root declaration: {', '.join(namespaces)} "
                    f"({declared_by}). "
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
    return _compute_declared_prefix_aliases(loaded, root_path, uri)


def declared_prefix_aliases(loaded, root_path: Path, uri: str) -> tuple[str, ...]:
    """Public wrapper of :func:`_declared_prefix_aliases` (issue #445).

    Exposes the compiler's bindable-prefix-alias computation so the inspection CLI
    can surface "usable class tokens" without triggering a full ``compile --check``.
    Accepts the same arguments the compiler kernel uses internally: ``loaded`` (an
    :class:`OntologyLoadResult`), the root ontology ``root_path``, and a class or
    property ``uri``.
    """
    return _compute_declared_prefix_aliases(loaded, root_path, uri)


def _safe_prefix_bindings(loaded, root_path: Path) -> dict[str, str]:
    """Return every prefix -> namespace binding safe to resolve for ANY local name.

    Root-declared prefixes always win (last declaration per prefix, matching Turtle's
    own last-wins semantics); an imported prefix is included only when every source in
    the closure that declares it agrees on one namespace. Shared by
    :func:`_compute_declared_prefix_aliases` (URI-specific aliases) and
    :func:`_prefix_alternatives` (the ``safety.class-unresolved`` "did you mean"
    cross-reference, #674) so both agree on what counts as a safe binding.
    """
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
    bindings = dict(root_prefixes)
    for prefix, namespaces in imported_prefixes.items():
        if prefix in root_prefixes or len(namespaces) != 1:
            continue
        bindings[prefix] = next(iter(namespaces))
    return bindings


def _prefix_alternatives(loaded, root_path: Path) -> dict[str, tuple[str, ...]]:
    """Return ambiguous prefix -> other prefixes safely bound to one of its candidate
    namespaces, e.g. ``{"party": ("bsp",)}`` (#674). Threaded into
    :class:`~.adapter.ResolutionContext` so a ``binding.unknown-class`` diagnostic can
    suggest the disambiguated alternative for an ambiguous-prefix token.
    """
    safe_bindings = _safe_prefix_bindings(loaded, root_path)
    result: dict[str, tuple[str, ...]] = {}
    for prefix, namespaces in _ambiguous_imported_prefixes(loaded, root_path).items():
        alternatives = tuple(
            sorted(
                other_prefix
                for other_prefix, other_namespace in safe_bindings.items()
                if other_prefix != prefix and other_namespace in namespaces
            )
        )
        if alternatives:
            result[prefix] = alternatives
    return result


def _compute_declared_prefix_aliases(loaded, root_path: Path, uri: str) -> tuple[str, ...]:
    """Implementation shared by the private and public aliases (issue #445)."""
    namespace, local = _namespace_local(uri)
    aliases = {
        f"{prefix}:{local}" if prefix else f":{local}"
        for prefix, declared_namespace in _safe_prefix_bindings(loaded, root_path).items()
        if declared_namespace == namespace
    }
    return tuple(sorted(aliases))


def _source_relations_for_path(path: Path) -> tuple[ResolvedRelation, ...]:
    """Parse one bronze source file exactly once into its ``ResolvedRelation`` set."""
    relations: list[ResolvedRelation] = []
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
    return tuple(relations)


def _dedupe_relations(relations: list[ResolvedRelation]) -> tuple[ResolvedRelation, ...]:
    unique = {(item.ref, item.uri): item for item in relations}
    return tuple(unique[key] for key in sorted(unique))


def _source_relations(paths: tuple[Path, ...]) -> tuple[ResolvedRelation, ...]:
    relations: list[ResolvedRelation] = []
    for path in paths:
        relations.extend(_source_relations_for_path(path))
    return _dedupe_relations(relations)


def _could_match_any_ref(text: str, requested_sources: frozenset[str]) -> bool:
    """Cheap byte-level pre-filter: can a file with *text* contribute a requested ref?

    Every ``ResolvedRelation.ref`` is built only from bytes physically present in that
    same file: a ``bronze:tableName``/``rdfs:label`` literal (or its URI fragment
    fallback), or a qname whose local segment equals that fragment and is resolved only
    against this file's own ``@prefix`` declarations -- each source file gets its own
    fresh ``Graph()`` (see ``_source_relations_for_path``), so there is no cross-file
    state a match could hide in. So if none of the requested refs' local segments appear
    as a raw substring of the file's text, a full RDF parse of this file cannot produce a
    match. A false positive (the substring appears without a real match) only costs one
    otherwise-unavoidable parse; a false negative is impossible. The caller reads each
    candidate file once and shares the text with ``_could_match_any_source_pair``.
    """
    for ref in requested_sources:
        local = ref.rsplit(".", 1)[-1].rsplit(":", 1)[-1]
        if local and local in text:
            return True
    return False


def _relation_matches_source_pair(
    relation: ResolvedRelation, pairs: frozenset[tuple[str, str]] | set[tuple[str, str]]
) -> bool:
    return any(
        dbt_source_name(relation.system_label) == source_name and relation.table_name == table_name
        for source_name, table_name in pairs
    )


def _could_match_any_source_pair(text: str, pairs: set[tuple[str, str]]) -> bool:
    """Cheap byte-level pre-filter: can a file with *text* declare a requested table?

    Same reasoning as ``_could_match_any_ref``: a relation's ``table_name`` is built only
    from bytes physically present in the same file (a ``bronze:tableName`` literal or the
    table URI's fragment fallback), so a file containing none of the requested table
    names as a raw substring cannot produce a match. False positives only cost one parse;
    false negatives are impossible.
    """
    return any(table_name and table_name in text for _, table_name in pairs)


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


def _domain_namespace(loaded, graph: Graph) -> str:
    """Return the namespace ``list_classes``/the domain-prefix token treat as this
    domain's own vocabulary, deterministically (#600).

    Only named classes are candidates (a BNode never names a namespace); they are
    sorted, and a class from the root ontology's own IRI wins over one dragged in by
    the RDFS import closure -- otherwise the "first" class could be a reference-model
    term and the domain would adopt e.g. FIBO's namespace.
    """
    named_classes = sorted(
        (
            subject
            for subject in graph.subjects(RDF.type, OWL.Class)
            if isinstance(subject, URIRef)
        ),
        key=str,
    )
    root_iri = next(
        (entry.ontology_iri for entry in loaded.manifest if entry.import_depth == 0), None
    )
    first_class_uri = next(
        (str(c) for c in named_classes if root_iri and str(c).startswith(root_iri)),
        str(named_classes[0]) if named_classes else "",
    )
    return (
        first_class_uri.rsplit("#", 1)[0] + "#"
        if "#" in first_class_uri
        else (
            first_class_uri.rsplit("/", 1)[0] + "/"
            if "/" in first_class_uri
            else "urn:kairos:ontology:"
        )
    )


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
    dict[str, tuple[str, ...]],
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
    # The namespace decides what `list_classes` treats as this domain's own vocabulary;
    # deterministic derivation matters because picking it must not depend on graph
    # iteration order (#600) -- see `_domain_namespace`.
    namespace = _domain_namespace(loaded, graph)
    root_iri = next(
        (entry.ontology_iri for entry in loaded.manifest if entry.import_depth == 0), None
    )
    # Same ordering hazard: a closure holds many owl:Ontology subjects, and `version`
    # below is read off whichever one this picks.
    declared_ontologies = sorted(
        (
            subject
            for subject in graph.subjects(RDF.type, OWL.Ontology)
            if isinstance(subject, URIRef)
        ),
        key=str,
    )
    ontology = next(
        (o for o in declared_ontologies if root_iri and str(o) == root_iri),
        declared_ontologies[0] if declared_ontologies else URIRef(namespace.rstrip("#/")),
    )
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
        _prefix_alternatives(loaded, ontology_path),
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
    requested_sources = frozenset(
        _binding_source_ref(path.read_text(encoding="utf-8")) for path in binding_paths
    )
    # #584: resolve contracted dbt bindings *before* the vocabulary scan so their
    # dependency closures' {{ source('name', 'table') }} pairs can widen vocabulary
    # discovery. A purely-contracted domain has no source.relation refs, so without this
    # it would parse zero vocabularies and its physical source() reads could never be
    # validated or declared. Seed CSV dependencies (#586) join the provenance inputs here
    # at their hub-relative names.
    dbt_relations: list[ResolvedRelation] = []
    dbt_provenance: list[ProvenanceInput] = []
    contracted_source_pairs: set[tuple[str, str]] = set()
    for path in binding_paths:
        text = path.read_text(encoding="utf-8")
        sql_path, contract_path = _binding_dbt_paths(text)
        if not sql_path and not contract_path:
            continue
        try:
            binding = load_entity_binding(text, path=str(path))
            dependency_paths = resolve_dbt_model_dependency_paths(binding, root)
            relation = resolve_dbt_model_source(binding, root, dependency_paths=dependency_paths)
            authored_paths = (*dependency_paths, (root / contract_path).resolve())
            binding_provenance: list[ProvenanceInput] = []
            binding_pairs: frozenset[tuple[str, str]] = frozenset()
            for resolved_path in authored_paths:
                try:
                    content = resolved_path.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    # A dependency that exists but cannot be read/decoded (e.g. a cp1252
                    # seed CSV export) is a binding problem, not a crash: mirror
                    # dbt_source's unreadable-dependency diagnostic so the enclosing
                    # replay contract below applies unchanged.
                    raise CompileError(
                        [
                            CompileDiagnostic(
                                code="dbt-source.dependency-unresolved",
                                message=(f"could not read dbt dependency {resolved_path}: {exc}"),
                                location=SourceLocation(
                                    path=str(path),
                                    pointer="/source/dbtModel/sqlPath",
                                ),
                            )
                        ]
                    ) from exc
                if resolved_path.suffix.lower() == ".sql":
                    # resolve_dbt_model_dependency_paths above already failed closed on an
                    # unparseable source() call, so only resolved pairs remain here.
                    binding_pairs |= extract_sources(content).pairs
                binding_provenance.append(
                    ProvenanceInput(
                        str(resolved_path.relative_to(root)).replace("\\", "/"),
                        content,
                    )
                )
        except CompileError:
            # The entity-local compile pass replays this resolution and preserves its
            # precise binding pointer while allowing unrelated safe entities to proceed.
            continue
        dbt_relations.append(relation)
        dbt_provenance.extend(binding_provenance)
        contracted_source_pairs.update(binding_pairs)
    # Parse each hub source file at most once: each candidate is read once and a cheap
    # byte-level pre-filter (_could_match_any_ref/_could_match_any_source_pair) skips a
    # full RDF parse for files that provably cannot contribute a requested ref or
    # contracted source() pair; the parse result for files that do match is kept
    # (parsed_source_relations) so the final relation list below doesn't re-parse them.
    parsed_source_relations: dict[Path, tuple[ResolvedRelation, ...]] = {}
    source_paths_list: list[Path] = []
    for candidate_path in sorted((root / "integration" / "sources").glob("**/*.ttl")):
        candidate_text = candidate_path.read_text(encoding="utf-8", errors="replace")
        if not _could_match_any_ref(
            candidate_text, requested_sources
        ) and not _could_match_any_source_pair(candidate_text, contracted_source_pairs):
            continue
        file_relations = _source_relations_for_path(candidate_path)
        if requested_sources & {relation.ref for relation in file_relations} or any(
            _relation_matches_source_pair(relation, contracted_source_pairs)
            for relation in file_relations
        ):
            parsed_source_relations[candidate_path] = file_relations
            source_paths_list.append(candidate_path)
    source_paths = tuple(source_paths_list)
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
        prefix_alternatives,
    ) = _ontology_symbols(ontology_path, root, referenced_tokens)
    relations = list(
        _dedupe_relations(
            [relation for path in source_paths for relation in parsed_source_relations[path]]
        )
    )
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
    relations.extend(dbt_relations)
    inputs.extend(dbt_provenance)
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
    try:
        config = load_hub_config(root, strict=True)
    except HubConfigError as exc:
        raise CompileError(
            [
                CompileDiagnostic(
                    code="safety.adapter-unsupported",
                    message=str(exc),
                    location=SourceLocation(path=str(config_path)),
                )
            ]
        ) from exc
    authored_adapter = str(config.get("adapter", ""))
    try:
        # DD-215: resolves the deprecated `fabric` spelling and rejects everything else
        # without a fallback -- notably `fabric-lakehouse`, which must never be handed
        # the T-SQL profile just because it is also Fabric.
        adapter, deprecation = resolve_adapter(authored_adapter)
    except UnsupportedAdapterError as exc:
        raise CompileError(
            [
                CompileDiagnostic(
                    code="safety.adapter-unsupported",
                    message=str(exc),
                    location=SourceLocation(path=str(config_path)),
                )
            ]
        ) from exc
    if deprecation is not None:
        logger.warning("kairos.yaml %s", deprecation)
    inputs.append(ProvenanceInput("kairos.yaml", config_path.read_text(encoding="utf-8")))
    # DD-213: declared Silver contracts join the closure, including foreign-domain ones a
    # cross-domain relationship points at. They are provenance inputs because they decide
    # emitted column sets, names, and order -- a contract edit must change the hash.
    relationship_targets = frozenset(
        target
        for path in binding_paths
        for target in _binding_relationship_targets(path.read_text(encoding="utf-8"))
    )
    contract_paths = discover_contract_paths(root, domain, relationship_targets)
    for path in contract_paths:
        inputs.append(
            ProvenanceInput(
                str(path.relative_to(root)).replace("\\", "/"),
                path.read_text(encoding="utf-8"),
            )
        )
    scope = BuildScope(
        domain=domain,
        hub_root=str(root),
        api_version="kairos.eu/v5",
        adapter=adapter,
        namespace=namespace,
        toolkit_version=__version__,
        binding_paths=tuple(str(path) for path in binding_paths),
        ontology_paths=ontology_paths,
        contract_paths=tuple(str(path) for path in contract_paths),
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
        prefix_alternatives=prefix_alternatives,
    )
    return scope, context


def _merge_systems(
    bounds: tuple[BoundSources, ...],
    extra_systems: tuple[SourceSystemFact, ...] = (),
) -> tuple[SourceSystemFact, ...]:
    """Merge per-binding systems plus *extra_systems* (contracted source() reads, #584)."""
    systems: dict[str, SourceSystemFact] = {}
    candidates = [system for bound in bounds for system in bound.systems]
    candidates.extend(extra_systems)
    for system in candidates:
        previous = systems.get(system.uri)
        systems[system.uri] = (
            system
            if previous is None
            else replace(
                previous,
                tables=tuple(
                    {table.uri: table for table in (*previous.tables, *system.tables)}[key]
                    for key in sorted({table.uri for table in (*previous.tables, *system.tables)})
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
    # Bounded parameters, read from the SOURCE column rather than the ontology property
    # (issue #681). `properties` above deliberately uses `prop.data_type`, which is the
    # declared range -- `xsd:string`, which has no width by construction -- so the width a
    # union has to carry only exists here.
    property_parameters = tuple(
        sorted(
            (field.property, canonical_type_label(source_type))
            for field in binding.fields
            if isinstance(field.expression, ExprColumn)
            for column in (columns.get(field.expression.column),)
            if column is not None
            for source_type in (_source_type(column.data_type),)
            if source_type is not None
            and (
                source_type.length is not None
                or source_type.precision is not None
                or source_type.scale is not None
            )
        )
    )
    return ConformanceTypeContract(
        grain=source_types(binding.grain.columns),
        identity=source_types(binding.identity.source_key),
        properties=properties,
        property_parameters=property_parameters,
    )


def _conformance_plans(
    bindings: tuple[EntityBinding, ...],
    context: ResolutionContext,
    scope: BuildScope,
    governed_classes: frozenset[str] = frozenset(),
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
                    governed_classes=governed_classes,
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
    extra_systems: tuple[SourceSystemFact, ...] = (),
    contracted_input_uris: frozenset[str] = frozenset(),
) -> BoundSources:
    """Merge independently adapted entities into one immutable domain input.

    *extra_systems*/*contracted_input_uris* carry physical tables read via
    ``{{ source() }}`` inside contracted dbt model closures (#584) so the shared
    per-system source catalogs declare them without granting mapping authority.
    """
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
        systems=_merge_systems(bounds, extra_systems),
        virtual_table_uris=frozenset(uri for bound in bounds for uri in bound.virtual_table_uris),
        contracted_input_uris=(
            frozenset(uri for bound in bounds for uri in bound.contracted_input_uris)
            | contracted_input_uris
        ),
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


def _relationship_technical_field_matches(
    binding: EntityBinding, source_column: str
) -> tuple[TechnicalField, ...]:
    """Return every authored technical field bound directly to ``source_column``.

    More than one match is genuinely ambiguous rather than a collision:
    ``_technical_field_safety_diagnostics`` makes ``(source column, purpose)`` the uniqueness
    key, so one source column may legitimately carry several technical fields under distinct
    purposes -- each with its own output ``name``. Nothing in the join contract picks between
    them, so the caller reports the ambiguity instead of resolving it silently.
    """
    return tuple(
        technical_field
        for technical_field in binding.technical_fields
        if isinstance(technical_field.expression, ExprColumn)
        and technical_field.expression.column == source_column
    )


def _relationship_output_column(
    binding: EntityBinding, source_column: str, context: ResolutionContext
) -> str | None:
    """Return the parent model's *output* column for an authored parent-side join column.

    #334 / DD-139: ``join.foreign`` resolves against authored technical fields exactly as it
    does against ``fields:``. Mapped fields keep precedence. There is deliberately no
    ``purpose`` filter -- ``adapter.py`` materializes every technical field regardless of
    purpose, so every one of them is a valid join target.

    A technical field renames its source column (``name`` is the output, ``expression`` binds
    the source), so the match is on the bound source column while the *returned* value is
    ``technical_field.name`` -- symmetric with the mapped-field branch returning
    ``prop.column_name``. Returning ``join.foreign`` verbatim would render a predicate against
    a column the parent model does not emit under that name.
    """
    for field in binding.fields:
        if isinstance(field.expression, ExprColumn) and field.expression.column == source_column:
            prop = context.property(field.property)
            return prop.column_name if prop is not None else None
    matches = _relationship_technical_field_matches(binding, source_column)
    return matches[0].name if len(matches) == 1 else None


def _wire_relationships(
    bounds: tuple[BoundSources, ...],
    bindings: tuple[EntityBinding, ...],
    context: ResolutionContext,
    hub_root: str | Path,
) -> tuple[tuple[BoundSources, ...], tuple[CompileDiagnostic, ...]]:
    """Wire resolved relationships into join specs and surrogate FK columns.

    Every condition below is also checked by ``_relationship_diagnostics``, which runs on
    each binding *before* it is admitted into ``bounds``/``bindings`` here and blocks the
    whole binding (with the matching diagnostic code) if any relationship fails one of
    them (#334, #335). For three of the four conditions, that makes this defensive rather
    than the primary gate: by the time a binding reaches this function, none of its
    relationships should be able to trip them. The fourth -- an internal relationship
    whose target binding is ``None`` -- is **not** fully defensive: it resolves the target
    binding from ``by_target`` (built from ``valid_bindings``, i.e. bindings that survived
    *every* check), whereas ``_relationship_diagnostics`` resolves the same lookup from
    ``selected_by_name`` (a snapshot of every *selected* binding, taken once before the
    per-binding blocking loop runs). If a relationship's target binding is later blocked
    for a reason unrelated to that relationship, the two views disagree and this specific
    branch fires for real through the public compile path -- see
    ``tests/test_wire_relationships_diagnostics.py::
    test_wire_relationships_endpoint_diagnostic_is_reachable_when_target_blocked_unrelated``.
    It does not change the compile's pass/fail outcome even then: ``quality.py``'s
    pre-existing, independent, non-suppressible ``run_safety_kernel`` already blocks that
    same scenario with its own ``safety.relationship-endpoint`` (checked from the final,
    fully-resolved blocked set), so the observable effect is a second, redundant
    diagnostic with the same code for the same cause -- not a new silent drop and not a
    new compile failure. Deduplicating that redundancy is left alone deliberately (doing
    it safely would mean weakening the non-suppressible kernel, or suppressing this
    fallback in a way that also hides the cases -- an unresolved target *property* or
    target *class* -- that ``run_safety_kernel`` does not cover).

    All four conditions raise a diagnostic instead of a bare ``continue`` anyway, so that
    if the upstream gate for the other three is ever weakened or bypassed by a future
    change, the relationship is dropped loudly rather than silently (#338 -- the same
    ``silently-dropped-relationship`` anti-pattern the reference-models pattern library
    names on the ``deferred-relationship`` pattern, and that ``core/pattern_rules.py``
    records as enforced via ``safety.relationship-endpoint``).
    """

    def quote(value: str) -> str:
        return (
            f"`{value.replace('`', '``')}`"
            if context.target_platform == "databricks"
            else (f"[{value.replace(']', ']]')}]")
        )

    by_target = {binding.target_class: binding for binding in bindings}
    wired: list[BoundSources] = []
    diagnostics: list[CompileDiagnostic] = []
    for bound, binding in zip(bounds, bindings, strict=True):
        joins: list[JoinSpec] = []
        fk_columns: list[ColumnSpec] = []
        relation = _resolved_binding_relation(binding, context)
        # Relationships are wired in two passes so a binding with more than one
        # relationship landing on the same generated FK/join name (two relationships to the
        # same target class, or two ``externalReference`` relationships to the same system --
        # #351) can be disambiguated. The first pass runs every existing defensive check
        # unchanged and only resolves what the target model/columns/description *would* be;
        # nothing is named yet. Once every relationship has resolved, target-model
        # collisions are counted across the whole binding, and the second pass (below the
        # loop) assigns names: a target hit by exactly one relationship keeps today's plain
        # ``{target}_sk``/alias (no behavior change for the common case), while a target hit
        # by more than one relationship qualifies both the FK column and the join alias with
        # the relationship's own resolved property name so they no longer collide.
        pending: list[tuple] = []
        for rel_index, relationship in enumerate(binding.relationships):
            pointer = f"/relationships/{rel_index}"
            external = relationship.external_reference
            target_binding = by_target.get(relationship.target)
            target_class = _relationship_target_class(relationship, context, hub_root)
            prop = context.property(relationship.property)
            if relation is None:
                # Defensive: adapt_binding already requires the source relation to
                # resolve (as "safety.source-unresolved") before a binding reaches
                # _wire_relationships at all.
                diagnostics.append(
                    CompileDiagnostic(
                        code="safety.source-unresolved",
                        message=(
                            f"relationship '{relationship.property}' on binding "
                            f"'{binding.name}' was dropped during wiring: the binding's "
                            "source relation does not resolve"
                        ),
                        location=SourceLocation(path=binding.source_path, pointer=pointer),
                    )
                )
                continue
            if (
                target_class is None
                or prop is None
                or (external is None and target_binding is None)
            ):
                # target_class/prop unresolved: defensive. _relationship_diagnostics
                # already rejects those as "safety.relationship-endpoint" before this
                # binding is admitted here.
                #
                # target_binding is None (external is None): NOT fully defensive.
                # _relationship_diagnostics resolves the same lookup from
                # selected_by_name (every selected binding, snapshotted once, before the
                # per-binding blocking loop runs); by_target here is built from
                # valid_bindings (bindings that survived every check). If the target
                # binding is later blocked for a reason unrelated to this relationship,
                # the two views disagree and this branch fires for real through the
                # public compile path -- see the docstring above and
                # tests/test_wire_relationships_diagnostics.py (#338). Pass/fail is
                # unaffected either way: quality.py's
                # non-suppressible run_safety_kernel independently blocks that same
                # scenario with its own "safety.relationship-endpoint", so this is a
                # redundant, not incorrect, second diagnostic in that specific case.
                diagnostics.append(
                    CompileDiagnostic(
                        code="safety.relationship-endpoint",
                        message=(
                            f"relationship '{relationship.property}' on binding "
                            f"'{binding.name}' was dropped during wiring: its target "
                            "class, property, or in-scope target binding does not resolve"
                        ),
                        location=SourceLocation(path=binding.source_path, pointer=pointer),
                    )
                )
                continue
            if external is None and len(relationship.on) != 1:
                # Defensive: _relationship_diagnostics already rejects a composite
                # (non-external) join as "safety.adapter-unsupported" before this binding
                # is admitted here.
                diagnostics.append(
                    CompileDiagnostic(
                        code="safety.adapter-unsupported",
                        message=(
                            f"relationship '{relationship.property}' on binding "
                            f"'{binding.name}' was dropped during wiring: composite "
                            "relationship joins are deferred beyond the v5 first slice"
                        ),
                        location=SourceLocation(path=binding.source_path, pointer=pointer),
                    )
                )
                continue
            if external is None:
                join = relationship.on[0]
                assert target_binding is not None
                target_columns = (
                    _relationship_output_column(target_binding, join.foreign, context),
                )
                if target_columns[0] is None:
                    # Defensive: _relationship_diagnostics already rejects a foreign join
                    # column the target binding doesn't map to exactly one output column
                    # as "safety.relationship-endpoint" before this binding is admitted
                    # here.
                    diagnostics.append(
                        CompileDiagnostic(
                            code="safety.relationship-endpoint",
                            message=(
                                f"relationship '{relationship.property}' on binding "
                                f"'{binding.name}' was dropped during wiring: join "
                                f"column '{join.foreign}' is not mapped by the target "
                                "binding"
                            ),
                            location=SourceLocation(
                                path=binding.source_path, pointer=f"{pointer}/join/0"
                            ),
                        )
                    )
                    continue
                target_model = target_class.name.lower()
                description = f"Surrogate reference to {target_class.name}"
            else:
                target_columns = tuple(item.column for item in external.key)
                target_model = external.name
                description = f"Surrogate reference to external {external.domain}.{external.name}"
            pending.append((relationship, prop, target_model, target_columns, description))
        target_model_counts: dict[str, int] = {}
        for _, _, target_model, _, _ in pending:
            target_model_counts[target_model] = target_model_counts.get(target_model, 0) + 1
        for relationship, prop, target_model, target_columns, description in pending:
            # #351: a target hit by exactly one relationship keeps the original
            # ``{target}_sk`` column/alias unchanged. A target hit by more than one
            # relationship (two relationships to the same class, or two
            # ``externalReference`` relationships to the same system) is qualified with the
            # relationship's own resolved property column name so the generated FK column
            # and join alias no longer collide between them.
            join_key = (
                f"{prop.column_name}_{target_model}"
                if target_model_counts[target_model] > 1
                else target_model
            )
            fk_column = f"{join_key}_sk"
            joins.append(
                JoinSpec(
                    join_type="left",
                    alias=join_key,
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
                    expression=f"{quote(join_key)}.{quote(f'{target_model}_sk')}",
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
    return tuple(wired), tuple(diagnostics)


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
                    # #351: the join alias is not always the bare ``target_model`` any
                    # more -- ``_wire_relationships`` qualifies it with the relationship's
                    # own property name when more than one relationship targets the same
                    # model, to avoid a duplicate-alias/duplicate-FK-column collision. Look
                    # up the alias it actually assigned instead of re-deriving it here, so
                    # this stays correct however that disambiguation is computed. The
                    # target's own surrogate key column is unaffected by that renaming --
                    # it always lives on the joined side as ``{target_model}_sk``.
                    join = next(
                        (item for item in model.joins if item.relationship_uri == prop.uri),
                        None,
                    )
                    alias = join.alias if join is not None else target_model
                    replacements[temporal_match_count_column(prop.uri)] = (
                        f"COUNT({quote(alias)}."
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
    # #617/#619: this function adds runtime FK match-count columns to silver_models
    # *after* shape_project() already snapshotted silver_registry from the
    # pre-augmentation columns -- refresh the registry here too, or gold_shape.py's
    # DD-110-parity drift check compares a stale registry against the real columns.
    updated_columns = dict(shaped.silver_registry.columns)
    for model in models:
        if model.identity.model_name in updated_columns:
            updated_columns[model.identity.model_name] = frozenset(
                column.name for column in model.columns
            )
    registry = replace(shaped.silver_registry, columns=tuple(sorted(updated_columns.items())))
    return replace(
        shaped, silver_models=tuple(models), schema_documents=documents, silver_registry=registry
    )


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


def _expression_source_columns(expression: Expression) -> tuple[str, ...]:
    """Return every source column referenced by an authored expression."""
    ordered: list[str] = []

    def walk(expr: Expression) -> None:
        if isinstance(expr, ExprColumn):
            ordered.append(expr.column)
        elif isinstance(expr, (ExprOperator, ExprFunction, ExprMacro)):
            for arg in expr.args:
                walk(arg)
        elif isinstance(expr, ExprCase):
            for branch in expr.branches:
                walk(branch.when)
                walk(branch.then)
            if expr.else_ is not None:
                walk(expr.else_)

    walk(expression)
    return tuple(dict.fromkeys(ordered))


def _explain_grain(binding: EntityBinding) -> tuple[ExplainGrainMechanism, ...]:
    """Classify how each grain column is materialized (DD-159 additive grain audit).

    Mirrors ``adapter._resolve_identity_output_columns`` classification but for
    **grain** columns, and is explain-only (no diagnostics).  The mechanism labels
    let a reviewer see whether a grain column is carried by a direct ontology
    property, a DD-139 technical field, an expression, or nothing at all.
    """
    mechanisms: list[ExplainGrainMechanism] = []
    for column in binding.grain.columns:
        direct_targets = [
            field.property
            for field in binding.fields
            if isinstance(field.expression, ExprColumn) and field.expression.column == column
        ]
        distinct_direct = list(dict.fromkeys(direct_targets))
        if len(distinct_direct) == 1:
            mechanisms.append(
                ExplainGrainMechanism(
                    column=column,
                    mechanism="direct-field",
                    output=distinct_direct[0],
                )
            )
            continue
        if len(distinct_direct) > 1:
            mechanisms.append(
                ExplainGrainMechanism(
                    column=column,
                    mechanism="direct-field",
                    output=", ".join(distinct_direct),
                )
            )
            continue
        technical_targets = [
            tech.name
            for tech in binding.technical_fields
            if isinstance(tech.expression, ExprColumn) and tech.expression.column == column
        ]
        distinct_technical = list(dict.fromkeys(technical_targets))
        if len(distinct_technical) == 1:
            mechanisms.append(
                ExplainGrainMechanism(
                    column=column,
                    mechanism="technical-field",
                    output=distinct_technical[0],
                )
            )
            continue
        if len(distinct_technical) > 1:
            mechanisms.append(
                ExplainGrainMechanism(
                    column=column,
                    mechanism="technical-field",
                    output=", ".join(distinct_technical),
                )
            )
            continue
        expression_targets = list(
            dict.fromkeys(
                field.property
                for field in binding.fields
                if not isinstance(field.expression, ExprColumn)
                and column in _expression_source_columns(field.expression)
            )
        )
        if expression_targets:
            mechanisms.append(
                ExplainGrainMechanism(
                    column=column,
                    mechanism="expression-only",
                    output=", ".join(expression_targets),
                )
            )
        else:
            mechanisms.append(
                ExplainGrainMechanism(
                    column=column,
                    mechanism="absent",
                    output="",
                )
            )
    return tuple(mechanisms)


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
    fields_by_property_uri: dict[str, FieldMapping] = {}
    fields_by_output_name: dict[str, FieldMapping] = {}
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
        if prop is not None:
            # #343: ``semantic_outputs`` in ``_technical_field_safety_diagnostics`` is built
            # with ``setdefault`` over exactly this loop's ``fields:`` entries, so two entries
            # resolving to the same property -- or to different properties whose output
            # columns collide -- silently discard the second entry instead of erroring. That
            # is dormant only because today's column matcher requires exact name equality, so
            # nothing yet produces two ``fields:`` entries for one property; it becomes
            # reachable the instant any future name-relaxing matcher lands.
            duplicate_property = fields_by_property_uri.get(prop.uri)
            if duplicate_property is not None:
                diagnostics.append(
                    CompileDiagnostic(
                        code="field.duplicate-property",
                        message=(
                            f"property '{field.property}' is mapped by more than one "
                            f"fields: entry (also mapped at '{duplicate_property.pointer}'); "
                            "each property may be mapped by at most one fields: entry"
                        ),
                        location=SourceLocation(path=binding.source_path, pointer=field.pointer),
                        rule_id="DD-133-safety",
                    )
                )
            else:
                fields_by_property_uri[prop.uri] = field
                lower_output = prop.column_name.lower()
                duplicate_output = fields_by_output_name.get(lower_output)
                if duplicate_output is not None:
                    diagnostics.append(
                        CompileDiagnostic(
                            code="field.output-collision",
                            message=(
                                f"fields: entry for property '{field.property}' produces "
                                f"output column '{prop.column_name}' which collides "
                                f"(case-insensitively) with the output column already "
                                f"produced by property '{duplicate_output.property}'"
                            ),
                            location=SourceLocation(
                                path=binding.source_path, pointer=field.pointer
                            ),
                            rule_id="DD-133-safety",
                        )
                    )
                else:
                    fields_by_output_name[lower_output] = field
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


def _unrealized_relationship_diagnostics(
    binding: EntityBinding,
) -> tuple[CompileDiagnostic, ...]:
    """Warn when relationship-purpose technical fields exist but no relationship does (#491).

    ``technicalFields`` with ``purpose: relationship`` is the documented way to carry a
    foreign-key column into Silver when the join cannot be authored yet (a not-yet-bound
    cross-domain parent, or the unsupported self-reference shape -- DD-139). Authoring the
    carrier and never following up with the ``relationships:`` entry is legal and silent,
    and it produces exactly the failure the CLdN hub shipped: 27 bindings, every FK column
    materialized, zero joins, every silver model isolated.

    Warning severity, deliberately: the binding is correct and emittable, the FK column is
    really there, and a hub may legitimately stage carriers before the parent domain is
    bound. Warnings never fail a compile (``CompileResult.succeeded``), so this reports the
    gap without blocking a staged rollout.

    This cannot fire when the FK column was authored with a different ``purpose`` (the
    CLdN ``Qlik-routes`` binding marks every carrier ``purpose: identity``);
    ``kairos-ontology propose-relationships`` covers that case by matching join keys
    against other bindings directly.
    """
    if binding.relationships:
        return ()
    carriers = [
        technical_field
        for technical_field in binding.technical_fields
        if technical_field.purpose == "relationship"
    ]
    if not carriers:
        return ()
    names = ", ".join(sorted(technical_field.name for technical_field in carriers))
    return (
        CompileDiagnostic(
            code="relationship.unrealized-technical-field",
            severity=DiagnosticSeverity.WARNING,
            message=(
                f"binding '{binding.name}' carries {len(carriers)} technical field(s) with "
                f"purpose 'relationship' ({names}) but authors no relationships: entry, so "
                "the foreign key reaches Silver as a raw column with no join, no surrogate "
                "key, and no orphan window. Run 'kairos-ontology propose-relationships' to "
                "derive the entry, or keep the carrier deliberately if the parent is not "
                "bound yet."
            ),
            location=SourceLocation(path=binding.source_path, pointer="/relationships"),
            rule_id="DD-139",
        ),
    )


def _duplicate_virtual_sources(
    bindings: list[EntityBinding], hub_root: str, context: ResolutionContext
) -> dict[str, tuple[str, ...]]:
    """Map each ``meta.kairos.virtual_source_iri`` claimed twice to the binding names claiming it.

    Issue #503: ``virtual_source_iri`` identifies one contracted dbt model's output. Two
    contracted models sharing one IRI make the identifier meaningless -- every consumer that
    keys on it (provenance, the emitted ``system_uri``) silently conflates two different
    grains. Nothing checked it; only the IRI's *shape* was validated.

    This is a **pre-pass** so a duplicate is attributable to both participants, rather than
    only to whichever binding the per-binding loop happens to reach second. It reuses each
    binding's ``ResolvedRelation`` from ``context`` (already computed once by
    ``resolve_scope``) instead of re-reading the contract and re-walking the SQL dependency
    closure here; resolution failures are swallowed on purpose -- that same binding is
    resolved again inside the loop, where the failure is reported once with its precise
    pointer.

    Scope is the **selected domain only**. A per-domain compile cannot see peer domains'
    bindings, so hub-wide uniqueness is `validate-dbt-contracts`' job; the diagnostic says so.
    """

    claimants: dict[str, list[str]] = {}
    for binding in bindings:
        if binding.source.dbt_model is None:
            continue
        relation = context.relation(binding.source.dbt_model.name)
        if relation is None or relation.connection_type != "dbt":
            try:
                relation = resolve_dbt_model_source(binding, hub_root)
            except CompileError:
                continue
        claimants.setdefault(relation.uri, []).append(binding.name)
    return {uri: tuple(sorted(names)) for uri, names in claimants.items() if len(set(names)) > 1}


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


def _binding_relationship_targets(text: str) -> frozenset[str]:
    """Read only the relationship target classes before full closed-schema validation.

    Used by scope resolution to decide which *foreign-domain* Silver contracts (DD-213)
    must join the closure: a relationship FK column embeds the parent's model name, so the
    parent's declared ``modelName`` is authoritative for this domain's column names.
    """
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return frozenset()
    if not isinstance(document, dict):
        return frozenset()
    relationships = document.get("relationships")
    if not isinstance(relationships, list):
        return frozenset()
    return frozenset(
        str(item["target"])
        for item in relationships
        if isinstance(item, dict) and isinstance(item.get("target"), str)
    )


def discover_contract_paths(
    root: Path, domain: str, relationship_targets: frozenset[str]
) -> tuple[Path, ...]:
    """Return the Silver contracts in scope, selected domain first (DD-213).

    A foreign-domain contract joins the closure only when it declares a class this
    domain's bindings actually point a relationship at -- so an unrelated domain's
    contract edit never churns this domain's provenance hash.
    """
    contracts_dir = root / "model" / "contracts"
    if not contracts_dir.is_dir():
        return ()
    own = contracts_dir / f"{domain}.contract.yaml"
    selected: list[Path] = [own] if own.is_file() else []
    if not relationship_targets:
        return tuple(selected)
    for path in sorted(contracts_dir.glob("*.contract.yaml")):
        if path == own:
            continue
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(document, dict):
            continue
        entities = document.get("entities")
        if not isinstance(entities, list):
            continue
        declared = {
            str(entity["class"])
            for entity in entities
            if isinstance(entity, dict) and isinstance(entity.get("class"), str)
        }
        if declared & relationship_targets:
            selected.append(path)
    return tuple(selected)


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
        if external is not None and external.domain.strip().lower() == binding.domain.lower():
            # #335: ``externalReference`` is the *cross*-domain escape hatch. A same-domain
            # reference bypasses every join guarantee at once: nothing checks that
            # ``ref('<external.name>')`` resolves to a model that exists, ``join.foreign`` is
            # never resolved against the parent binding's outputs, and ``quality.py`` skips the
            # in-scope-target check whenever ``external_reference is not None`` -- switching off
            # ``silently-dropped-relationship``, the one enforced normative pattern unit.
            diagnostics.append(
                CompileDiagnostic(
                    code="relationship.external-reference-same-domain",
                    message=(
                        f"relationship '{relationship.property}' declares an externalReference "
                        f"in domain '{external.domain}', which is this binding's own domain "
                        f"'{binding.domain}'; externalReference names the other domain that "
                        "materializes the parent. An in-scope parent must be joined through "
                        "target/join so the join columns, the referenced model, and the "
                        "silently-dropped-relationship check are all validated"
                    ),
                    location=SourceLocation(
                        path=binding.source_path,
                        pointer=f"{pointer}/externalReference/domain",
                    ),
                    rule_id="DD-133-safety",
                )
            )
            continue
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
        if external is None and target_class.uri == source_class.uri:
            # #334: unblocking ``join.foreign`` against technical fields also unblocks self-joins
            # (a surrogate parent key is typically technical). ``_wire_relationships`` would emit
            # ``ref('<own model>')`` inside that same model -- a dbt dependency cycle -- plus a
            # second ``<model>_sk`` column colliding with the model's own surrogate key: the
            # collision guard in ``_binding_safety_diagnostics`` only reserves the generated FK
            # when ``external_reference is not None``, so it never sees this case. Reject rather
            # than convert a compile-time error into a broken dbt project (#342).
            own_model = target_class.name.lower()
            diagnostics.append(
                CompileDiagnostic(
                    code="relationship.self-reference-unsupported",
                    message=(
                        f"relationship '{relationship.property}' points "
                        f"'{binding.target_class}' at itself; a self-referential relationship is "
                        f"not supported yet: the generated join would emit ref('{own_model}') "
                        f"inside the '{own_model}' model (a dbt dependency cycle) and a second "
                        f"'{own_model}_sk' column colliding with that model's own surrogate key. "
                        "Supported alternative: drop this relationships: entry and carry the "
                        f"foreign key as a technicalFields: entry with purpose 'relationship' "
                        "(DD-139) — the column reaches Silver, and the hierarchy resolves with a "
                        "self-join downstream in Gold, where the parent side is a separate model "
                        "and no cycle exists"
                    ),
                    location=SourceLocation(path=binding.source_path, pointer=pointer),
                    rule_id="DD-133-safety",
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
                ambiguous = _relationship_technical_field_matches(target_binding, join.foreign)
                if len(ambiguous) > 1:
                    names = ", ".join(f"'{item.name}'" for item in ambiguous)
                    diagnostics.append(
                        CompileDiagnostic(
                            code="technical-field.relationship-target-ambiguous",
                            message=(
                                f"relationship foreign column '{join.foreign}' is carried by "
                                f"{len(ambiguous)} technical fields in the target binding "
                                f"({names}); the join cannot pick one output column "
                                "unambiguously -- carry the parent join column as exactly one "
                                "technical field or as a mapped field"
                            ),
                            location=SourceLocation(path=binding.source_path, pointer=join_pointer),
                            rule_id="DD-139",
                        )
                    )
                    continue
                diagnostics.append(
                    CompileDiagnostic(
                        code="safety.relationship-endpoint",
                        message=(
                            f"relationship foreign column '{join.foreign}' is not "
                            "mapped by the target binding (neither a mapped field nor an "
                            "authored technical field carries it)"
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
    if shaped.gold_product is not None and materialized.gold is not None:
        # `render_project` already renders these into the medallion project, and the
        # medallion `dbt_project.yml` already carries a `models/gold/<domain>` config
        # block -- but the compile result is intersected with this planned set, so
        # omitting them here silently dropped every Gold dbt model before anything was
        # written, leaving Gold with no packaging path at all (issue #665). Shared with
        # the renderer's own completeness check so the two sets cannot drift.
        from ..projections.dbt.gold_render import gold_dbt_artifact_paths

        paths.update(gold_dbt_artifact_paths(shaped.gold_product, materialized.gold))
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


@dataclass(frozen=True, slots=True)
class _DbtDependencyClosure:
    """One valid contracted binding's plan-authoritative dependency closure."""

    binding: EntityBinding
    sql_paths: tuple[str, ...]
    seed_paths: tuple[str, ...]
    #: Optional ``seeds/<name>.yml`` column-docs siblings of ``seed_paths`` (#586 stage b).
    seed_properties_paths: tuple[str, ...]
    source_pairs: tuple[tuple[str, str], ...]


def _dbt_dependency_closures(
    bindings: tuple[EntityBinding, ...],
    scope: BuildScope,
) -> tuple[tuple[_DbtDependencyClosure, ...], tuple[CompileDiagnostic, ...]]:
    """Walk each contracted binding's ``ref()`` closure over the immutable scope inputs.

    Mirrors ``dbt_source._dependency_sql_paths``' filesystem walk (same regexes, same
    seed/ambiguity rules, same exact-stem ``ref()`` matching) but consumes only
    ``scope.inputs``, keeping the CompilePlan the single authority for emitted bytes
    (#580). Returns each binding's SQL paths, seed CSV leaves (#586), those seeds'
    optional column-docs siblings (#586 stage b), and extracted ``source()`` pairs (#584).
    """
    if not any(binding.source.dbt_model is not None for binding in bindings):
        # Ordinary relation-backed domains skip the input indexing entirely.
        return (), ()
    inputs = {item.name.replace("\\", "/"): item.content for item in scope.inputs}
    # Lookup is by exact stem (dbt matches ref() names exactly); the emitted-project
    # collision checks in _planned_dbt_dependencies remain casefolded.
    seeds_prefix = "integration/transforms/dbt/seeds/"
    sql_inputs: dict[str, list[str]] = {}
    seed_inputs: dict[str, list[str]] = {}
    seed_properties_inputs: dict[str, list[str]] = {}
    for path in inputs:
        if path.startswith("integration/transforms/dbt/models/") and path.endswith(".sql"):
            sql_inputs.setdefault(Path(path).stem, []).append(path)
        elif path.startswith(seeds_prefix) and path.endswith(".csv"):
            seed_inputs.setdefault(Path(path).stem, []).append(path)
        elif path.startswith(seeds_prefix) and Path(path).suffix in SEED_PROPERTIES_SUFFIXES:
            seed_properties_inputs.setdefault(Path(path).stem, []).append(path)
    closures: list[_DbtDependencyClosure] = []
    diagnostics: list[CompileDiagnostic] = []
    for binding in bindings:
        model = binding.source.dbt_model
        if model is None:
            continue
        sql_paths: list[str] = []
        seed_paths: list[str] = []
        seed_properties_paths: list[str] = []
        pairs: set[tuple[str, str]] = set()
        pending = [model.sql_path.replace("\\", "/")]
        visited: set[str] = set()
        while pending:
            sql_path = pending.pop()
            if sql_path in visited:
                continue
            visited.add(sql_path)
            sql_paths.append(sql_path)
            sql_content = inputs.get(sql_path)
            if sql_content is None:
                continue
            extraction = extract_sources(sql_content)
            pairs.update(extraction.pairs)
            if extraction.unparsed:
                # Same fail-closed verdict the filesystem walk reaches, via the one shared
                # extraction helper: an unreadable source() call would emit a project whose
                # source is never declared (#584).
                diagnostics.append(
                    CompileDiagnostic(
                        code="dbt-source.source-unparsed",
                        message=(
                            f"dbt SQL dependency {sql_path!r} contains a source() call whose "
                            f"arguments could not be resolved statically: "
                            f"{SUPPORTED_SOURCE_FORMS}"
                        ),
                        location=SourceLocation(
                            path=binding.source_path,
                            pointer="/source/dbtModel/sqlPath",
                        ),
                    )
                )
            for ref_name in sorted(extract_refs(sql_content)):
                sql_candidates = sql_inputs.get(ref_name, [])
                seed_candidates = seed_inputs.get(ref_name, [])
                if sql_candidates and seed_candidates:
                    diagnostics.append(
                        CompileDiagnostic(
                            code="dbt-source.dependency-ambiguous",
                            message=(
                                f"dbt ref({ref_name!r}) resolves to both an authored model "
                                "SQL file and an authored seed CSV file in the immutable "
                                "CompilePlan input closure"
                            ),
                            location=SourceLocation(
                                path=binding.source_path,
                                pointer="/source/dbtModel/sqlPath",
                            ),
                        )
                    )
                    continue
                if len(sql_candidates) == 1:
                    pending.append(sql_candidates[0])
                    continue
                if len(seed_candidates) == 1:
                    if seed_candidates[0] not in seed_paths:
                        seed_paths.append(seed_candidates[0])
                        # Column docs ride along with their seed. Exactly one candidate is
                        # required for the same reason the filesystem walk requires it:
                        # two spellings would make dbt load duplicate seeds: entries.
                        docs_candidates = seed_properties_inputs.get(ref_name, [])
                        if len(docs_candidates) == 1:
                            seed_properties_paths.append(docs_candidates[0])
                        elif docs_candidates:
                            diagnostics.append(
                                CompileDiagnostic(
                                    code="dbt-source.dependency-ambiguous",
                                    message=(
                                        f"dbt seed {ref_name!r} has more than one "
                                        "column-docs document in the immutable CompilePlan "
                                        "input closure; author exactly one"
                                    ),
                                    location=SourceLocation(
                                        path=binding.source_path,
                                        pointer="/source/dbtModel/sqlPath",
                                    ),
                                )
                            )
                    continue
                diagnostics.append(
                    CompileDiagnostic(
                        code="dbt-source.dependency-unresolved",
                        message=(
                            f"dbt ref({ref_name!r}) is absent or ambiguous in the "
                            "immutable CompilePlan input closure (searched authored "
                            "models and seeds)"
                        ),
                        location=SourceLocation(
                            path=binding.source_path,
                            pointer="/source/dbtModel/sqlPath",
                        ),
                    )
                )
        closures.append(
            _DbtDependencyClosure(
                binding=binding,
                sql_paths=tuple(sql_paths),
                seed_paths=tuple(sorted(seed_paths)),
                seed_properties_paths=tuple(sorted(seed_properties_paths)),
                source_pairs=tuple(sorted(pairs)),
            )
        )
    return tuple(closures), tuple(diagnostics)


def _contracted_source_tables(
    closures: tuple[_DbtDependencyClosure, ...],
    context: ResolutionContext,
) -> tuple[tuple[SourceSystemFact, ...], frozenset[str], tuple[CompileDiagnostic, ...]]:
    """Resolve contracted ``source()`` pairs against physical vocabulary relations (#584).

    Each resolved pair yields a canonical single-table ``SourceSystemFact`` (built by the
    same helper relation-backed bindings use, so declarations are byte-identical across
    domains) plus its table URI for ``contracted_input_uris``. An unresolvable pair is a
    blocking diagnostic: emitting the closure without declaring its source would fail
    offline ``dbt parse``.
    """
    if not any(closure.source_pairs for closure in closures):
        # No contracted source() reads: skip building the physical-relation index.
        return (), frozenset(), ()
    physical: dict[tuple[str, str], dict[str, ResolvedRelation]] = {}
    for relation in context.relations:
        if relation.connection_type == "dbt":
            continue
        key = (dbt_source_name(relation.system_label), relation.table_name)
        physical.setdefault(key, {})[relation.uri] = relation
    systems: list[SourceSystemFact] = []
    uris: set[str] = set()
    diagnostics: list[CompileDiagnostic] = []
    for closure in closures:
        for source_name, table_name in closure.source_pairs:
            matches = physical.get((source_name, table_name), {})
            if not matches:
                diagnostics.append(
                    CompileDiagnostic(
                        code="dbt-source.source-unresolved",
                        message=(
                            f"source({source_name!r}, {table_name!r}) in the contracted dbt "
                            "dependency closure does not match any physical source "
                            "vocabulary table; the source name must be the toolkit's "
                            "snake_case rendering of the vocabulary system label and the "
                            "table must match its declared tableName exactly"
                        ),
                        location=SourceLocation(
                            path=closure.binding.source_path or "<binding>",
                            pointer="/source/dbtModel/sqlPath",
                        ),
                    )
                )
                continue
            if len(matches) > 1:
                diagnostics.append(
                    CompileDiagnostic(
                        code="dbt-source.source-ambiguous",
                        message=(
                            f"source({source_name!r}, {table_name!r}) in the contracted dbt "
                            "dependency closure matches more than one physical source "
                            f"vocabulary table: {', '.join(sorted(matches))}"
                        ),
                        location=SourceLocation(
                            path=closure.binding.source_path or "<binding>",
                            pointer="/source/dbtModel/sqlPath",
                        ),
                    )
                )
                continue
            relation = next(iter(matches.values()))
            if relation.uri in uris:
                continue
            uris.add(relation.uri)
            systems.append(system_fact_for_relation(relation))
    return tuple(systems), frozenset(uris), tuple(diagnostics)


def _planned_dbt_dependencies(
    closures: tuple[_DbtDependencyClosure, ...],
    scope: BuildScope,
    generated_paths: tuple[str, ...],
) -> tuple[tuple[PlannedDbtDependency, ...], tuple[CompileDiagnostic, ...]]:
    """Select contracted SQL/seed/properties bytes from the immutable compile input closure."""
    if not closures:
        # Ordinary relation-backed domains skip the selection indexes entirely.
        return (), ()
    inputs = {item.name.replace("\\", "/"): item.content for item in scope.inputs}
    selected: dict[str, dict[str, object]] = {}
    model_paths: dict[str, str] = {}
    diagnostics: list[CompileDiagnostic] = []
    generated_by_path = {path.casefold(): path for path in generated_paths}
    generated_models = {
        Path(path).stem.casefold(): path
        for path in generated_paths
        if path.startswith("models/") and path.endswith(".sql")
    }

    def select_dependency(
        binding: EntityBinding,
        source_path: str,
        *,
        kind: str,
        model_name: str = "",
    ) -> None:
        normalized_source = source_path.replace("\\", "/")
        prefix = "integration/transforms/dbt/"
        content = inputs.get(normalized_source)
        if content is None or not normalized_source.startswith(prefix):
            diagnostics.append(
                CompileDiagnostic(
                    code="dbt-source.path-unresolved",
                    message=(
                        f"selected dbt {kind} file {normalized_source!r} is absent from "
                        "the immutable CompilePlan input closure"
                    ),
                    location=SourceLocation(
                        path=binding.source_path,
                        pointer=(
                            "/source/dbtModel/contractPath"
                            if kind == "properties"
                            else "/source/dbtModel/sqlPath"
                        ),
                    ),
                )
            )
            return

        emit_path = normalized_source.removeprefix(prefix)
        collision_key = emit_path.casefold()
        generated_path = generated_by_path.get(collision_key)
        if generated_path is not None:
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.artifact-collision",
                    message=(
                        f"contracted dbt dependency {emit_path!r} collides with generated "
                        f"artifact {generated_path!r}"
                    ),
                    location=SourceLocation(path=binding.source_path),
                )
            )
            return

        previous = selected.get(collision_key)
        if previous is not None:
            if previous["path"] != emit_path or previous["content"] != content:
                diagnostics.append(
                    CompileDiagnostic(
                        code="safety.artifact-collision",
                        message=(
                            "contracted dbt dependency paths collide with conflicting "
                            f"bytes: {previous['path']!r} and {emit_path!r}"
                        ),
                        location=SourceLocation(path=binding.source_path),
                    )
                )
                return
            previous_names = set(previous["binding_names"])
            previous_names.add(binding.name)
            previous["binding_names"] = tuple(sorted(previous_names))
            return

        if model_name:
            model_key = model_name.casefold()
            previous_model_path = model_paths.get(model_key)
            generated_model_path = generated_models.get(model_key)
            if previous_model_path is not None and previous_model_path != emit_path:
                diagnostics.append(
                    CompileDiagnostic(
                        code="safety.artifact-collision",
                        message=(
                            f"contracted dbt model name {model_name!r} resolves to both "
                            f"{previous_model_path!r} and {emit_path!r}"
                        ),
                        location=SourceLocation(
                            path=binding.source_path,
                            pointer="/source/dbtModel/name",
                        ),
                    )
                )
                return
            if generated_model_path is not None:
                diagnostics.append(
                    CompileDiagnostic(
                        code="safety.artifact-collision",
                        message=(
                            f"contracted dbt model name {model_name!r} collides with "
                            f"generated model {generated_model_path!r}"
                        ),
                        location=SourceLocation(
                            path=binding.source_path,
                            pointer="/source/dbtModel/name",
                        ),
                    )
                )
                return
            model_paths[model_key] = emit_path

        selected[collision_key] = {
            "path": emit_path,
            "source_path": normalized_source,
            "content": content,
            "kind": kind,
            "model_name": model_name,
            "binding_names": (binding.name,),
        }

    for closure in closures:
        model = closure.binding.source.dbt_model
        if model is None:
            continue
        for sql_path in closure.sql_paths:
            select_dependency(
                closure.binding,
                sql_path,
                kind="sql",
                model_name=Path(sql_path).stem,
            )
        for seed_path in closure.seed_paths:
            # Seeds share dbt's ref() namespace with models, so they carry a model_name
            # and participate in the same casefolded name-collision checks above.
            select_dependency(
                closure.binding,
                seed_path,
                kind="seed",
                model_name=Path(seed_path).stem,
            )
        for seed_properties_path in closure.seed_properties_paths:
            # Deliberately no model_name: a properties document is not a dbt resource, so
            # claiming its seed's name here would trip the model-name collision check above
            # against the CSV that legitimately owns it (same rule as "properties").
            select_dependency(
                closure.binding,
                seed_properties_path,
                kind="seed_properties",
            )
        select_dependency(closure.binding, model.contract_path, kind="properties")

    dependencies = tuple(
        PlannedDbtDependency(
            path=str(item["path"]),
            source_path=str(item["source_path"]),
            content=str(item["content"]),
            kind=str(item["kind"]),
            model_name=str(item["model_name"]),
            binding_names=tuple(item["binding_names"]),
        )
        for item in sorted(selected.values(), key=lambda item: str(item["path"]))
    )
    return dependencies, tuple(diagnostics)


def _load_domain_contract(
    scope: BuildScope, domain: str
) -> tuple[SilverContract | None, list[CompileDiagnostic]]:
    """Load the selected domain's declared Silver contract, if it has one (DD-213).

    A contract-load failure is reported and treated as *ungoverned* rather than fatal in
    this slice: Gate A is advisory until contract-driven emission lands, so a malformed
    contract must not be able to stop a hub compiling.
    """
    for path_text in scope.contract_paths:
        path = Path(path_text)
        if path.stem != f"{domain}.contract":
            continue
        try:
            return load_silver_contract(path.read_text(encoding="utf-8"), path=str(path)), []
        except CompileError as exc:
            return None, list(exc.diagnostics)
    # No advisory is emitted for an ungoverned domain. DD-213 §6 promises that a domain
    # without a contract "compiles exactly as it does today", and a diagnostic that fires
    # on every compile of every existing hub is not that -- it is noise that every
    # downstream consumer asserting on the diagnostic stream would have to learn to ignore.
    # Governance status is a question you ask (the contract file either exists or does
    # not), not something every compile has to answer unprompted.
    return None, []


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
    # DD-213 Gate A. A domain with no contract stays ungoverned and compiles exactly as it
    # did before, with one advisory -- adoption is incremental by construction, never a
    # clean break.
    domain_contract, contract_diagnostics = _load_domain_contract(scope, domain)
    diagnostics.extend(contract_diagnostics)
    if domain_contract is not None:
        # Contract-pinned column names replace the camel_to_snake default, which is what
        # decouples an ontology rename from a physical column rename. An unpinned contract
        # leaves the context untouched and emits byte-identically to no contract at all.
        context = apply_column_names(context, domain_contract)
        diagnostics.extend(
            contract_resolution_diagnostics(
                domain_contract, context, severity=DiagnosticSeverity.ERROR
            )
        )
    specs: list[EntityBindingSpec] = []
    valid_bindings: list[EntityBinding] = []
    # The bindings exactly as authored, parallel to ``valid_bindings``. Gate A must judge
    # what the author wrote: ``valid_bindings`` carries the contract-expanded form, in which
    # every padded property already looks mapped, so checking coverage against it would make
    # required-property-unmapped and optional-property-undeclared permanently unreachable.
    authored_bindings: list[EntityBinding] = []
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
        tuple(selected_bindings),
        context,
        scope,
        governed_classes=(
            frozenset(entity.target_class for entity in domain_contract.entities)
            if domain_contract is not None
            else frozenset()
        ),
    )
    diagnostics.extend(conformance_diagnostics)
    selected_by_name = {binding.name: binding for binding in selected_bindings}
    duplicate_virtual_sources = _duplicate_virtual_sources(
        selected_bindings, scope.hub_root, context
    )
    for binding in selected_bindings:
        if binding.name in conformance_blocked:
            specs.append(EntityBindingSpec(binding=binding, blocked=True))
            continue
        # #491: an authoring advisory, not a safety rule -- emitted outside the blocking
        # path below so it can never block a binding. ``_binding_safety_diagnostics``
        # returns blocking diagnostics only; adding a warning to it would silently block
        # every binding that carries one (see the severity guard below).
        diagnostics.extend(_unrealized_relationship_diagnostics(binding))
        binding_safety = _binding_safety_diagnostics(binding, context)
        if binding_safety:
            diagnostics.extend(binding_safety)
            # Guard the contract rather than assume it: only an ERROR blocks. Without this
            # a future non-error diagnostic added to _binding_safety_diagnostics would
            # block the binding purely by being present.
            if any(item.severity is DiagnosticSeverity.ERROR for item in binding_safety):
                specs.append(EntityBindingSpec(binding=binding, blocked=True))
                continue
        if binding.source.dbt_model is not None:
            try:
                # resolve_scope already resolved this binding's dbt model once (for
                # provenance hashing) and its ResolvedRelation is carried on
                # context.relations -- reuse it instead of re-reading the contract and
                # re-walking the SQL dependency closure. Only trust the lookup when it is
                # unambiguously the dbt-resolved relation (connection_type == "dbt"); fall
                # back to a fresh resolution otherwise (binding failed in resolve_scope, or
                # an implausible ref collision with a bronze source relation).
                relation = context.relation(binding.source.dbt_model.name)
                if relation is None or relation.connection_type != "dbt":
                    relation = resolve_dbt_model_source(binding, scope.hub_root)
                # #503: the binding's target.class and the contract's meta.kairos.target_class
                # are two independent declarations of one fact. Compared here, not inside
                # resolve_dbt_model_source, because the comparison needs the *resolved* class
                # URI and that module has no ResolutionContext. _binding_safety_diagnostics
                # above has already blocked this binding if the class does not resolve, so
                # klass() is non-None by the time we get here -- guarded anyway rather than
                # asserted, so a future reordering degrades to "check skipped" instead of
                # AttributeError.
                target = context.klass(binding.target_class)
                if target is not None:
                    check_target_class_match(binding, relation.target_class, target.uri)
            except CompileError as exc:
                diagnostics.extend(exc.diagnostics)
                specs.append(EntityBindingSpec(binding=binding, blocked=True))
                continue
            claimants = duplicate_virtual_sources.get(relation.uri)
            if claimants is not None:
                diagnostics.append(
                    CompileDiagnostic(
                        code="dbt-source.virtual-source-duplicate",
                        message=(
                            f"virtual_source_iri {relation.uri!r} is claimed by more than one "
                            f"contracted dbt model in this domain (bindings: "
                            f"{', '.join(claimants)}). Give each contracted model its own IRI. "
                            "This compile only sees domain "
                            f"'{domain}' -- run 'kairos-ontology validate-dbt-contracts' for "
                            "hub-wide uniqueness."
                        ),
                        location=SourceLocation(
                            path=binding.source_path or "<binding>",
                            pointer="/source/dbtModel/contractPath",
                        ),
                    )
                )
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
            # DD-213: expand a governed binding to the contract's full property list, in the
            # contract's declared order, padding what this source does not supply. Every
            # branch in a conformance group therefore has identical columns, which is what
            # makes the union's `base_model` invariant under binding filename order.
            padded_columns: frozenset[str] = frozenset()
            authored_binding = binding
            contract_entity = (
                domain_contract.entity_for(binding.target_class)
                if domain_contract is not None
                else None
            )
            if contract_entity is not None:
                padded_columns = padded_column_names(binding, contract_entity, context)
                binding = expand_binding(binding, contract_entity, context)
            bound = adapt_binding(binding, context)
            bound = mark_padded_columns(bound, padded_columns)
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
            authored_bindings.append(authored_binding)
            bounds.append(bound)
            specs.append(EntityBindingSpec(binding=binding))
        except CompileError as exc:
            diagnostics.extend(_adapter_safety_diagnostic(item) for item in exc.diagnostics)
            specs.append(EntityBindingSpec(binding=binding, blocked=True))
            logger.debug(
                "binding blocked (adapter): %s codes=%s", path.name, _codes_of(exc.diagnostics)
            )
        except PolicyNormalizationError as exc:
            # Preserve the error's own specific code (e.g. `identity.authored-key-not-supplied`)
            # rather than flattening every normalization failure into a generic
            # `safety.type-incompatible`, which hides the actual DD-108/DD-109/... rule that
            # fired behind an opaque message string.
            diagnostics.append(
                CompileDiagnostic(
                    code=exc.code,
                    message=str(exc),
                    location=SourceLocation(path=binding.source_path),
                    rule_id=exc.rule_id,
                )
            )
            specs.append(EntityBindingSpec(binding=binding, blocked=True))
            logger.debug("binding blocked (normalization): %s error=%s", path.name, exc)
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
    # #584/#586: one plan-authoritative walk of every valid contracted binding's ref()
    # closure over scope.inputs -- feeding both the shared source-catalog declarations
    # (via merge_bound_sources) and the emitted dependency selection below.
    dbt_closures, closure_diagnostics = _dbt_dependency_closures(tuple(valid_bindings), scope)
    contracted_systems, contracted_input_uris, contracted_diagnostics = _contracted_source_tables(
        dbt_closures, context
    )
    diagnostics.extend(contracted_diagnostics)
    contract = None
    shaped = None
    materialized = None
    if bounds:
        try:
            wired_bounds, wiring_diagnostics = _wire_relationships(
                tuple(bounds), tuple(valid_bindings), context, scope.hub_root
            )
            diagnostics.extend(wiring_diagnostics)
            merged = merge_bound_sources(
                wired_bounds,
                tuple(valid_bindings),
                context,
                hub_root=scope.hub_root,
                conformance_plans=conformance_plans,
                extra_systems=contracted_systems,
                contracted_input_uris=contracted_input_uris,
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
    # DD-213 Gate A. Deliberately AFTER shaping, not inside the binding loop: the
    # scaffolder reads types from the shaped project, so checking against the adapter's
    # pre-shape candidates would compare two different stages and reject a contract the
    # scaffolder had just generated from this very hub.
    if domain_contract is not None:
        shaped_models = models_by_class(shaped.silver_models) if shaped is not None else {}
        for binding in authored_bindings:
            resolved_class = context.klass(binding.target_class)
            diagnostics.extend(
                contract_binding_diagnostics(
                    binding,
                    domain_contract,
                    model=(
                        shaped_models.get(resolved_class.uri)
                        if resolved_class is not None
                        else None
                    ),
                    severity=DiagnosticSeverity.ERROR,
                )
            )

    artifact_paths = _planned_artifact_paths(shaped, materialized, tuple(valid_bindings), context)
    dbt_dependencies, dependency_diagnostics = _planned_dbt_dependencies(
        dbt_closures, scope, artifact_paths
    )
    diagnostics.extend(closure_diagnostics)
    diagnostics.extend(dependency_diagnostics)
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
        dbt_dependencies=dbt_dependencies,
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
                grain_mechanisms=_explain_grain(entity.binding),
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
                        property=rel.property,
                        join=tuple(f"{join.local}={join.foreign}" for join in rel.on),
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
