# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Stateless v5 compiler kernel (DD-133)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD
import yaml

from kairos_ontology import __version__

from ..ontology_loader import load_ontology
from ..ontology_ops import list_classes
from ..projections.dbt import (
    BoundSources,
    normalize_contract,
    plan_materialization,
    render_project,
    shape_project,
)
from ..projections.dbt.context import ActiveSourceScope
from ..projections.dbt.canonical_hash import temporal_match_count_column
from ..projections.dbt.diagnostics import ExecutionMode
from ..projections.dbt.mapping_specs import SourceMappings
from ..projections.dbt.policy_normalize import _source_type
from ..projections.dbt.policy_specs import (
    AuthoredValuesFact,
    CanonicalTypeKind,
    CanonicalTypeSpec,
    TemporalRelationshipFact,
)
from ..projections.dbt.specs import (
    ColumnSpec,
    JoinSpec,
    SourceBindingsFact,
    SourceSystemFact,
)
from ..projections.shared import ForeignKeyAuthoringFact
from .adapter import (
    ResolutionContext,
    ResolvedClass,
    ResolvedColumn,
    ResolvedProperty,
    ResolvedRelation,
    adapt_binding,
)
from .bindings import EntityBinding, ExprColumn, load_entity_binding
from .compile import CompileMode
from .ir import CanonicalProjectIR, EntityBindingSpec
from .quality import run_safety_kernel
from .result import (
    CompileDiagnostic,
    CompileDiagnostics,
    CompileError,
    CompileResult,
    ExplainEntity,
    ExplainReport,
    SourceLocation,
    order_compile_diagnostics,
)
from .scope import BuildScope, ProvenanceInput

_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")
_V5_EXCLUDED_ARTIFACTS = frozenset(
    {
        "contracts/dq-runtime-result-contract.schema.json",
    }
)
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


def _ontology_symbols(
    ontology_path: Path, hub_root: Path
) -> tuple[
    Graph, str, str, str, tuple[ResolvedClass, ...], tuple[ResolvedProperty, ...], tuple[str, ...]
]:
    loaded = load_ontology(ontology_path, identity_root=hub_root)
    graph = loaded.graph
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
        class_refs.add(f"{domain_prefix}:{info.name}")
        for ref in sorted(class_refs):
            classes.append(ResolvedClass(ref, info.uri, info.name, info.label, info.comment))
        for prop in info.properties:
            data_type = _XSD_TYPES.get(prop.range_uri, prop.range_uri)
            property_refs = set(_qnames(graph, URIRef(prop.uri)))
            property_refs.add(f"{domain_prefix}:{prop.name}")
            for ref in sorted(property_refs):
                key = (ref, prop.uri)
                previous = properties.get(key)
                domains = tuple(sorted({*(previous.domain_uris if previous else ()), info.uri}))
                properties[key] = ResolvedProperty(
                    ref=ref,
                    uri=prop.uri,
                    column_name=prop.name,
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
        missing = "bindings" if not binding_paths else str(ontology_path)
        raise CompileError(
            [
                CompileDiagnostic(
                    code="safety.source-unresolved",
                    message=f"compile scope is incomplete: missing {missing}",
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
    graph, namespace, ontology_iri, version, classes, properties, ontology_paths = (
        _ontology_symbols(ontology_path, root)
    )
    relations = _source_relations(source_paths)
    template_root = Path(__file__).resolve().parents[2] / "templates" / "dbt"
    inputs = [
        ProvenanceInput(str(path.relative_to(root)), path.read_text(encoding="utf-8"))
        for path in (*binding_paths, *source_paths)
    ]
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
    if adapter != "fabric":
        raise CompileError(
            [
                CompileDiagnostic(
                    code="safety.adapter-unsupported",
                    message=f"adapter '{adapter}' is not supported by the v5 first slice",
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
    )
    context = ResolutionContext(
        domain=domain,
        namespace=namespace,
        ontology_name=domain,
        ontology_iri=ontology_iri,
        ontology_version=version,
        template_root=str(template_root),
        target_platform=adapter,
        relations=relations,
        classes=classes,
        properties=properties,
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


def _foreign_keys(
    bindings: tuple[EntityBinding, ...], context: ResolutionContext
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
        for relationship in binding.relationships:
            prop = context.property(relationship.property)
            if prop is None:
                continue
            uri = prop.uri
            facts.append(
                TemporalRelationshipFact(
                    property_uri=uri,
                    mode=_authored(uri, "silverForeignKeyTemporalMode", "none"),
                    as_of_column=None,
                    interval=None,
                    time_zone=None,
                    precision=None,
                    cardinality=_authored(
                        uri,
                        "silverForeignKeyCardinality",
                        "exactly-one" if relationship.missing_parent == "error" else "zero-or-one",
                    ),
                    missing_action=_authored(
                        uri,
                        "silverForeignKeyMissingPolicy",
                        "fail" if relationship.missing_parent == "error" else "unknown-member",
                    ),
                    ambiguous_action=_authored(
                        uri,
                        "silverForeignKeyAmbiguousPolicy",
                        "fail" if relationship.ambiguous_parent == "error" else "retry",
                    ),
                    late_parent_action=_authored(uri, "silverForeignKeyLateParentPolicy", "fail"),
                    change_detection=_authored(uri, "silverForeignKeyChangeDetection", "false"),
                )
            )
    return tuple(facts)


def merge_bound_sources(
    bounds: tuple[BoundSources, ...],
    bindings: tuple[EntityBinding, ...],
    context: ResolutionContext,
) -> BoundSources:
    """Merge independently adapted entities into one immutable domain input."""
    base = bounds[0]
    policy = base.policy_facts
    return replace(
        base,
        classes=tuple(item for bound in bounds for item in bound.classes),
        systems=_merge_systems(bounds),
        mappings=SourceMappings(
            tables=tuple(item for bound in bounds for item in bound.mappings.tables),
            columns=tuple(item for bound in bounds for item in bound.mappings.columns),
            namespaces=base.mappings.namespaces,
        ),
        source_bindings=SourceBindingsFact(
            active_contracts=(),
            virtual_table_uris=frozenset(),
            class_to_sources=tuple(
                item for bound in bounds for item in bound.source_bindings.class_to_sources
            ),
            folded_source_targets=(),
            warnings=(),
        ),
        binding_observations=tuple(item for bound in bounds for item in bound.binding_observations),
        foreign_key_facts=_foreign_keys(bindings, context),
        silver_candidates=tuple(item for bound in bounds for item in bound.silver_candidates),
        schema_candidates=tuple(item for bound in bounds for item in bound.schema_candidates),
        policy_facts=replace(
            policy,
            preparations=tuple(
                item for bound in bounds for item in bound.policy_facts.preparations
            ),
            identities=tuple(item for bound in bounds for item in bound.policy_facts.identities),
            temporal_relationships=_relationship_policies(bindings, context),
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
) -> tuple[BoundSources, ...]:
    by_target = {binding.target_class: binding for binding in bindings}
    wired: list[BoundSources] = []
    for bound, binding in zip(bounds, bindings, strict=True):
        joins: list[JoinSpec] = []
        fk_columns: list[ColumnSpec] = []
        relation = context.relation(binding.source.relation)
        for relationship in binding.relationships:
            target_binding = by_target.get(relationship.target)
            target_class = context.klass(relationship.target)
            prop = context.property(relationship.property)
            if (
                relation is None
                or target_binding is None
                or target_class is None
                or prop is None
                or len(relationship.on) != 1
            ):
                continue
            join = relationship.on[0]
            target_column = _relationship_output_column(target_binding, join.foreign, context)
            if target_column is None:
                continue
            target_model = target_class.name.lower()
            fk_column = f"{target_model}_sk"
            joins.append(
                JoinSpec(
                    join_type="left",
                    alias=target_model,
                    condition="",
                    referenced_model=f"{{{{ ref('{target_model}') }}}}",
                    fk_column=fk_column,
                    source_alias="src",
                    source_column_uris=(relation.column_uri(join.local),),
                    target_columns=(target_column,),
                    relationship_uri=prop.uri,
                    temporal_mode="none",
                )
            )
            fk_columns.append(
                ColumnSpec(
                    name=fk_column,
                    expression=f"[{target_model}].[{target_model}_sk]",
                    data_type="string",
                    nullable=relationship.missing_parent != "error",
                    role="foreign-key",
                    description=f"Surrogate reference to {target_class.name}",
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
            partition = ", ".join(f"[src].[{column}]" for column in binding.grain.columns)
            for relationship in binding.relationships:
                prop = context.property(relationship.property)
                target = context.klass(relationship.target)
                if prop is not None and target is not None:
                    replacements[temporal_match_count_column(prop.uri)] = (
                        f"COUNT([{target.name.lower()}].[{target.name.lower()}_sk]) "
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


def _adapter_safety_diagnostic(item: CompileDiagnostic) -> CompileDiagnostic:
    code_map = {
        "binding.unknown-relation": "safety.source-unresolved",
        "binding.unknown-column": "safety.column-unresolved",
        "binding.unknown-key-column": "safety.column-unresolved",
        "binding.unknown-class": "safety.class-unresolved",
        "binding.unknown-property": "safety.property-unresolved",
        "binding.unsupported-dbt-model-source": "safety.adapter-unsupported",
        "binding.unknown-identity-strategy": "safety.identity-incomplete",
    }
    code = code_map.get(item.code)
    if code is None:
        return item
    return replace(item, code=code)


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


def _relationship_diagnostics(
    binding: EntityBinding,
    selected: dict[str, EntityBinding],
    context: ResolutionContext,
) -> tuple[CompileDiagnostic, ...]:
    diagnostics: list[CompileDiagnostic] = []
    relation = context.relation(binding.source.relation)
    local_columns = {column.name: column for column in relation.columns} if relation else {}
    targets = {item.target_class: item for item in selected.values()}
    for index, relationship in enumerate(binding.relationships):
        pointer = f"/relationships/{index}"
        target_binding = targets.get(relationship.target)
        target_relation = (
            context.relation(target_binding.source.relation) if target_binding is not None else None
        )
        prop = context.property(relationship.property)
        source_class = context.klass(binding.target_class)
        target_class = context.klass(relationship.target)
        if prop is None or target_binding is None:
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.relationship-endpoint",
                    message=(
                        f"relationship '{relationship.property}' target "
                        f"'{relationship.target}' does not resolve in compile scope"
                    ),
                    location=SourceLocation(path=binding.source_path, pointer=pointer),
                )
            )
            continue
        if (
            source_class is None
            or target_class is None
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
        if len(relationship.on) != 1:
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
        for join_index, join in enumerate(relationship.on):
            local = local_columns.get(join.local)
            foreign = foreign_columns.get(join.foreign)
            join_pointer = f"{pointer}/join/{join_index}"
            if local is None or foreign is None:
                missing = join.local if local is None else join.foreign
                side = "local" if local is None else "foreign"
                diagnostics.append(
                    CompileDiagnostic(
                        code="safety.column-unresolved",
                        message=f"relationship {side} column '{missing}' does not resolve",
                        location=SourceLocation(path=binding.source_path, pointer=join_pointer),
                    )
                )
                continue
            if _source_type(local.data_type) != _source_type(foreign.data_type):
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
    for binding in bindings:
        relation = context.relation(binding.source.relation)
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
                f"  select count(*) as n from {{{{ source('{relation.system_label}', "
                f"'{relation.table_name}') }}}}\n"
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
            target_binding = targets.get(relationship.target) if relationship else None
            parent = (
                context.relation(target_binding.source.relation)
                if target_binding is not None
                else None
            )
            if relationship is None or parent is None:
                continue
            predicates = " and ".join(
                f"child.[{join.local}] = parent.[{join.foreign}]" for join in relationship.on
            )
            missing = relationship.on[0].foreign
            suffix = "" if check_index == 0 else f"_{check_index + 1}"
            path = f"tests/{binding.domain}/{model_name}__referential{suffix}.sql"
            artifacts[path] = (
                "-- DD-133 focused source referential check\n"
                f"select child.* from {{{{ source('{relation.system_label}', "
                f"'{relation.table_name}') }}}} as child\n"
                f"left join {{{{ source('{parent.system_label}', "
                f"'{parent.table_name}') }}}} as parent on {predicates}\n"
                f"where child.[{relationship.on[0].local}] is not null "
                f"and parent.[{missing}] is null\n"
            )
    return artifacts


def compile_domain(
    hub_root: str | Path, domain: str, mode: CompileMode | str = CompileMode.CHECK
) -> CompileResult:
    """Compile one domain entirely in memory, collecting independent binding failures."""
    selected_mode = CompileMode(mode)
    try:
        scope, context = resolve_scope(Path(hub_root), domain)
    except CompileError as exc:
        return CompileResult(domain, selected_mode.value, CompileDiagnostics(exc.diagnostics))
    diagnostics: list[CompileDiagnostic] = []
    specs: list[EntityBindingSpec] = []
    valid_bindings: list[EntityBinding] = []
    bounds: list[BoundSources] = []
    selected_bindings: list[EntityBinding] = []
    for path_text in scope.binding_paths:
        path = Path(path_text)
        text = path.read_text(encoding="utf-8")
        declared_domain = _binding_domain(text)
        if declared_domain not in {None, domain}:
            continue
        try:
            binding = load_entity_binding(text, path=str(path))
        except CompileError as exc:
            diagnostics.extend(exc.diagnostics)
            continue
        if binding.domain != domain:
            continue
        selected_bindings.append(binding)
    if not selected_bindings and not diagnostics:
        diagnostics.append(
            CompileDiagnostic(
                code="safety.source-unresolved",
                message=f"no EntityBinding documents select domain '{domain}'",
                location=SourceLocation(path=scope.hub_root),
            )
        )
    selected_by_name = {binding.name: binding for binding in selected_bindings}
    for binding in selected_bindings:
        relationship_diagnostics = _relationship_diagnostics(binding, selected_by_name, context)
        if relationship_diagnostics:
            diagnostics.extend(relationship_diagnostics)
            specs.append(EntityBindingSpec(binding=binding, blocked=True))
            continue
        try:
            bound = adapt_binding(binding, context)
            valid_bindings.append(binding)
            bounds.append(bound)
            specs.append(EntityBindingSpec(binding=binding, bound=bound))
        except CompileError as exc:
            diagnostics.extend(_adapter_safety_diagnostic(item) for item in exc.diagnostics)
            specs.append(EntityBindingSpec(binding=binding, blocked=True))
    artifacts: dict[str, str] = {}
    if bounds:
        try:
            wired_bounds = _wire_relationships(tuple(bounds), tuple(valid_bindings), context)
            merged = merge_bound_sources(wired_bounds, tuple(valid_bindings), context)
            contract = normalize_contract(merged, ExecutionMode.FAIL_FAST)
            shaped = _project_relationship_match_counts(
                shape_project(contract), tuple(valid_bindings), context
            )
            materialized = plan_materialization(contract, shaped)
            rendered = render_project(shaped, materialized)
            artifacts = {
                path: content
                for path, content in rendered.items()
                if isinstance(path, str)
                and not path.startswith("__")
                and path not in _V5_EXCLUDED_ARTIFACTS
                and not (path.startswith("metadata/") and "release" in path)
                and isinstance(content, str)
            }
            artifacts.update(_focused_quality_artifacts(tuple(valid_bindings), context))
        except Exception as exc:  # downstream contracts expose several precise exception types
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.type-incompatible",
                    message=f"projection normalization failed: {exc}",
                )
            )
    artifact_paths = tuple(sorted(artifacts))
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
    explain = ExplainReport(
        domain=domain,
        provenance_hash=ir.provenance_hash,
        binding_paths=scope.binding_paths,
        ontology_paths=scope.ontology_paths,
        entities=tuple(
            ExplainEntity(
                name=spec.binding.name,
                source=spec.binding.source.relation or spec.binding.source.dbt_model,
                target_class=spec.binding.target_class,
                grain=spec.binding.grain.columns,
                identity_strategy=spec.binding.identity.strategy,
                fields=_explain_field(spec.binding),
                relationships=tuple(rel.target for rel in spec.binding.relationships),
                blocked=spec.blocked,
            )
            for spec in specs
        ),
        artifact_paths=artifact_paths,
    )
    return CompileResult(
        domain=domain,
        mode=selected_mode.value,
        diagnostics=CompileDiagnostics(ordered),
        provenance_hash=ir.provenance_hash,
        artifacts=tuple(sorted(artifacts.items())),
        explain=explain,
        ir=ir,
    )
