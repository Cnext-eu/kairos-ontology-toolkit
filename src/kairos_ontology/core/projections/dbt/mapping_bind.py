# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Graph-only binding for the structured kairos-map v2 vocabulary (DD-107)."""

from __future__ import annotations

import re
from pathlib import Path

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, SKOS, XSD

from .mapping_specs import (
    AuthoredCaseBranchFact,
    AuthoredExpressionFact,
    ColumnMappingFact,
    MAX_MAPPING_AST_DEPTH,
    MappingContractError,
    SourceMappings,
    TableMappingFact,
)

KAIROS_MAP = Namespace("https://kairos.cnext.eu/mapping#")

_MATCH_PREDICATES = {
    "exactMatch": SKOS.exactMatch,
    "closeMatch": SKOS.closeMatch,
    "narrowMatch": SKOS.narrowMatch,
    "broadMatch": SKOS.broadMatch,
    "relatedMatch": SKOS.relatedMatch,
}
_EXPRESSION_TYPES = {
    KAIROS_MAP.SourceColumnExpression: "source-column",
    KAIROS_MAP.LiteralExpression: "literal",
    KAIROS_MAP.NullExpression: "null",
    KAIROS_MAP.OperatorExpression: "operator",
    KAIROS_MAP.FunctionExpression: "function",
    KAIROS_MAP.CaseExpression: "case",
    KAIROS_MAP.MacroExpression: "macro",
}
_LEGACY_LOCAL_NAMES = frozenset(
    {
        "transform",
        "transformExpression",
        "filterCondition",
        "sourceColumns",
        "defaultValue",
        "deduplicationKey",
        "deduplicationOrder",
    }
)
_SQL_CATEGORY_PATTERNS = (
    ("mapping.raw-sql-comment", re.compile(r"--|/\*|\*/")),
    ("mapping.raw-sql-statement-separator", re.compile(r";")),
    ("mapping.raw-sql-subquery", re.compile(r"\b(?:select|with)\b", re.I)),
    ("mapping.raw-sql-join", re.compile(r"\bjoin\b", re.I)),
    ("mapping.raw-sql-window", re.compile(r"\bover\s*\(|\bwindow\b", re.I)),
    (
        "mapping.raw-sql-aggregation",
        re.compile(r"\bgroup\s+by\b|\b(?:sum|count|avg|min|max)\s*\(", re.I),
    ),
    (
        "mapping.raw-sql-grain-change",
        re.compile(
            r"\b(?:union|distinct|pivot|unpivot|explode|flatten)\b",
            re.I,
        ),
    ),
    (
        "mapping.raw-sql-ddl-dml",
        re.compile(
            r"\b(?:insert|update|delete|merge|create|alter|drop|truncate|grant|revoke)\b",
            re.I,
        ),
    ),
    (
        "mapping.nondeterministic-expression",
        re.compile(
            r"\b(?:rand|random|newid|uuid|current_timestamp|current_date|getdate|now)\s*\(?",
            re.I,
        ),
    ),
    (
        "mapping.adapter-specific-sql",
        re.compile(
            r"\b(?:openjson|json_value|get_json_object|posexplode|try_cast|try_convert)\b",
            re.I,
        ),
    ),
    (
        "mapping.technical-cleanup",
        re.compile(
            r"\b(?:cast|trim|ltrim|rtrim|json|sentinel|cdc|rename)\b",
            re.I,
        ),
    ),
)


def _error(
    code: str,
    message: str,
    *,
    resource: object = "",
    predicate: object = "",
    rule_id: str = "DD-107",
) -> MappingContractError:
    return MappingContractError(
        code,
        message,
        resource_uri=str(resource),
        predicate_uri=str(predicate),
        rule_id=rule_id,
    )


def _reject_legacy_authority(graph: Graph) -> None:
    """Reject, but never interpret, every removed raw-SQL mapping term."""

    namespace = str(KAIROS_MAP)
    for subject, predicate, value in sorted(graph, key=lambda row: tuple(map(str, row))):
        predicate_text = str(predicate)
        if not predicate_text.startswith(namespace):
            continue
        local = predicate_text.removeprefix(namespace)
        if local not in _LEGACY_LOCAL_NAMES:
            continue
        lexical = str(value)
        if local in {"deduplicationKey", "deduplicationOrder"}:
            raise _error(
                "mapping.technical-cleanup",
                (
                    f"removed kairos-map:{local} authority belongs in a "
                    "contracted dbt transformation"
                ),
                resource=subject,
                predicate=predicate,
                rule_id="DD-107-transformation-routing",
            )
        for code, pattern in _SQL_CATEGORY_PATTERNS:
            if not pattern.search(lexical):
                continue
            if code == "mapping.technical-cleanup":
                message = (
                    "technical cleanup is illegal in mappings; use a contracted "
                    "dbt transformation"
                )
                rule_id = "DD-107-transformation-routing"
            elif code in {
                "mapping.raw-sql-subquery",
                "mapping.raw-sql-join",
                "mapping.raw-sql-window",
                "mapping.raw-sql-aggregation",
                "mapping.raw-sql-grain-change",
                "mapping.raw-sql-ddl-dml",
            }:
                message = (
                    "relational, statement-level, or grain-affecting SQL is illegal in "
                    "mappings; use an approved contracted dbt transformation"
                )
                rule_id = "DD-107-transformation-routing"
            else:
                message = (
                    "arbitrary, adapter-specific, or nondeterministic SQL is not a "
                    "mapping expression; author the structured v2 scalar contract"
                )
                rule_id = "DD-107-safe-expression"
            raise _error(
                code,
                message,
                resource=subject,
                predicate=predicate,
                rule_id=rule_id,
            )
        raise _error(
            "mapping.removed-raw-sql-term",
            (
                f"kairos-map:{local} was removed without a compatibility reader; "
                "author a structured TableMapping or ColumnMapping resource"
            ),
            resource=subject,
            predicate=predicate,
            rule_id="DD-107-safe-expression",
        )


def _resources(graph: Graph, subject: URIRef, predicate: URIRef) -> tuple[URIRef, ...]:
    values = tuple(graph.objects(subject, predicate))
    if any(not isinstance(value, URIRef) for value in values):
        raise _error(
            "mapping.invalid-resource-reference",
            "value must be a named IRI resource",
            resource=subject,
            predicate=predicate,
        )
    return tuple(value for value in values if isinstance(value, URIRef))


def _one_resource(
    graph: Graph,
    subject: URIRef,
    predicate: URIRef,
    *,
    required: bool = True,
) -> URIRef | None:
    values = _resources(graph, subject, predicate)
    if len(values) != (1 if required else min(len(values), 1)):
        requirement = "exactly one" if required else "at most one"
        raise _error(
            "mapping.invalid-cardinality",
            f"{requirement} named IRI is required",
            resource=subject,
            predicate=predicate,
        )
    return values[0] if values else None


def _literals(graph: Graph, subject: URIRef, predicate: URIRef) -> tuple[Literal, ...]:
    values = tuple(graph.objects(subject, predicate))
    if any(not isinstance(value, Literal) for value in values):
        raise _error(
            "mapping.invalid-literal",
            "value must be an RDF literal",
            resource=subject,
            predicate=predicate,
        )
    return tuple(value for value in values if isinstance(value, Literal))


def _one_text(
    graph: Graph,
    subject: URIRef,
    predicate: URIRef,
    *,
    required: bool = True,
) -> str:
    values = _literals(graph, subject, predicate)
    if len(values) != (1 if required else min(len(values), 1)):
        requirement = "exactly one" if required else "at most one"
        raise _error(
            "mapping.invalid-cardinality",
            f"{requirement} literal is required",
            resource=subject,
            predicate=predicate,
        )
    return str(values[0]) if values else ""


def _rdf_list(graph: Graph, subject: URIRef, predicate: URIRef) -> tuple[URIRef, ...]:
    heads = tuple(graph.objects(subject, predicate))
    if len(heads) != 1 or not isinstance(heads[0], (BNode, URIRef)):
        raise _error(
            "mapping.invalid-rdf-list",
            "arguments/branches require exactly one RDF list",
            resource=subject,
            predicate=predicate,
        )
    head = heads[0]
    result: list[URIRef] = []
    visited: set[BNode | URIRef] = set()
    cursor: object = head
    while cursor != RDF.nil:
        if not isinstance(cursor, (BNode, URIRef)) or cursor in visited:
            raise _error(
                "mapping.invalid-rdf-list",
                "arguments/branches must be one finite RDF list of named resources",
                resource=subject,
                predicate=predicate,
            )
        visited.add(cursor)
        first = tuple(graph.objects(cursor, RDF.first))
        rest = tuple(graph.objects(cursor, RDF.rest))
        if (
            len(first) != 1
            or len(rest) != 1
            or not isinstance(first[0], URIRef)
            or not isinstance(rest[0], (BNode, URIRef))
        ):
            raise _error(
                "mapping.invalid-rdf-list",
                "arguments/branches must be one finite RDF list of named resources",
                resource=subject,
                predicate=predicate,
            )
        result.append(first[0])
        cursor = rest[0]
    return tuple(result)


def _expression_kind(graph: Graph, resource: URIRef) -> str:
    kinds = tuple(
        kind
        for class_uri, kind in _EXPRESSION_TYPES.items()
        if (resource, RDF.type, class_uri) in graph
    )
    if len(kinds) != 1:
        raise _error(
            "mapping.invalid-expression-kind",
            "expression must have exactly one approved concrete expression class",
            resource=resource,
            predicate=RDF.type,
        )
    return kinds[0]


def _expression(
    graph: Graph,
    resource: URIRef,
    *,
    active: frozenset[str] = frozenset(),
    depth: int = 1,
) -> AuthoredExpressionFact:
    resource_uri = str(resource)
    if depth > MAX_MAPPING_AST_DEPTH:
        raise _error(
            "mapping.expression-too-deep",
            f"expression AST exceeds the maximum depth of {MAX_MAPPING_AST_DEPTH}",
            resource=resource,
            rule_id="DD-107-ast-depth",
        )
    if resource_uri in active:
        raise _error(
            "mapping.expression-cycle",
            "expression graphs must be acyclic",
            resource=resource,
        )
    nested_active = active | {resource_uri}
    kind = _expression_kind(graph, resource)
    output_type = _one_text(graph, resource, KAIROS_MAP.outputType)
    nullable = _one_text(graph, resource, KAIROS_MAP.nullable)
    null_policy = _one_text(graph, resource, KAIROS_MAP.nullPolicy)
    determinism = _one_text(graph, resource, KAIROS_MAP.determinism)
    capabilities = tuple(
        sorted(str(value) for value in _literals(graph, resource, KAIROS_MAP.requiresCapability))
    )
    if not capabilities:
        raise _error(
            "mapping.missing-capability-requirement",
            "every expression node must declare at least one adapter capability",
            resource=resource,
            predicate=KAIROS_MAP.requiresCapability,
        )

    source_column_uri = ""
    literal_lexical = ""
    literal_datatype = ""
    operation = ""
    macro_uri = ""
    arguments: tuple[AuthoredExpressionFact, ...] = ()
    branches: tuple[AuthoredCaseBranchFact, ...] = ()
    else_expression: AuthoredExpressionFact | None = None

    if kind == "source-column":
        source = _one_resource(graph, resource, KAIROS_MAP.sourceColumn)
        assert source is not None
        source_column_uri = str(source)
    elif kind == "literal":
        values = _literals(graph, resource, KAIROS_MAP.literalValue)
        if len(values) != 1:
            raise _error(
                "mapping.invalid-cardinality",
                "literal expressions require exactly one typed literalValue",
                resource=resource,
                predicate=KAIROS_MAP.literalValue,
            )
        literal_lexical = str(values[0])
        literal_datatype = str(values[0].datatype or XSD.string)
    elif kind in {"operator", "function", "macro"}:
        arguments = tuple(
            _expression(graph, item, active=nested_active, depth=depth + 1)
            for item in _rdf_list(graph, resource, KAIROS_MAP.arguments)
        )
        if kind == "operator":
            operation = _one_text(graph, resource, KAIROS_MAP.operator)
        elif kind == "function":
            operation = _one_text(graph, resource, KAIROS_MAP.function)
        else:
            macro = _one_resource(graph, resource, KAIROS_MAP.macro)
            assert macro is not None
            macro_uri = str(macro)
    elif kind == "case":
        branch_facts: list[AuthoredCaseBranchFact] = []
        for branch in _rdf_list(graph, resource, KAIROS_MAP.branches):
            if (branch, RDF.type, KAIROS_MAP.CaseBranch) not in graph:
                raise _error(
                    "mapping.invalid-case-branch",
                    "CASE branch resources must be typed kairos-map:CaseBranch",
                    resource=branch,
                    predicate=RDF.type,
                )
            condition = _one_resource(graph, branch, KAIROS_MAP.when)
            result = _one_resource(graph, branch, KAIROS_MAP.then)
            assert condition is not None and result is not None
            branch_facts.append(
                AuthoredCaseBranchFact(
                    resource_uri=str(branch),
                    condition=_expression(
                        graph,
                        condition,
                        active=nested_active,
                        depth=depth + 1,
                    ),
                    result=_expression(
                        graph,
                        result,
                        active=nested_active,
                        depth=depth + 1,
                    ),
                )
            )
        branches = tuple(branch_facts)
        else_resource = _one_resource(graph, resource, KAIROS_MAP.elseExpression)
        assert else_resource is not None
        else_expression = _expression(
            graph,
            else_resource,
            active=nested_active,
            depth=depth + 1,
        )

    return AuthoredExpressionFact(
        resource_uri=resource_uri,
        kind=kind,
        output_type=output_type,
        nullable=nullable,
        null_policy=null_policy,
        determinism=determinism,
        capabilities=capabilities,
        source_column_uri=source_column_uri,
        literal_lexical=literal_lexical,
        literal_datatype=literal_datatype,
        operation=operation,
        macro_uri=macro_uri,
        arguments=arguments,
        branches=branches,
        else_expression=else_expression,
    )


def _match_type(
    graph: Graph,
    resource: URIRef,
    source: URIRef,
    target: URIRef,
) -> str:
    match_type = _one_text(graph, resource, KAIROS_MAP.matchType)
    predicate = _MATCH_PREDICATES.get(match_type)
    if predicate is None:
        raise _error(
            "mapping.invalid-match-type",
            f"matchType must be one of {sorted(_MATCH_PREDICATES)}",
            resource=resource,
            predicate=KAIROS_MAP.matchType,
        )
    if (source, predicate, target) not in graph:
        raise _error(
            "mapping.missing-skos-alignment",
            "the structured mapping must be accompanied by its declared SKOS alignment",
            resource=resource,
            predicate=predicate,
        )
    return match_type


def _mapping_resources(graph: Graph, class_uri: URIRef) -> tuple[URIRef, ...]:
    subjects = tuple(graph.subjects(RDF.type, class_uri))
    if any(not isinstance(subject, URIRef) for subject in subjects):
        raise _error(
            "mapping.unnamed-contract",
            "mapping contracts must use stable named IRIs, not blank nodes",
            predicate=RDF.type,
        )
    return tuple(sorted((item for item in subjects if isinstance(item, URIRef)), key=str))


def bind_mapping_graph(graph: Graph, *, include_proposals: bool = False) -> SourceMappings:
    """Copy approved/legacy mapping facts, optionally including authoring proposals."""

    _reject_legacy_authority(graph)
    table_facts: list[TableMappingFact] = []
    column_facts: list[ColumnMappingFact] = []
    represented_alignments: set[tuple[URIRef, URIRef, URIRef]] = set()

    for resource in _mapping_resources(graph, KAIROS_MAP.TableMapping):
        source = _one_resource(graph, resource, KAIROS_MAP.sourceTable)
        target = _one_resource(graph, resource, KAIROS_MAP.targetClass)
        assert source is not None and target is not None
        match_type = _match_type(graph, resource, source, target)
        represented_alignments.add((source, _MATCH_PREDICATES[match_type], target))
        review_state = _one_text(
            graph,
            resource,
            KAIROS_MAP.reviewState,
            required=False,
        )
        if review_state and review_state not in {"proposed", "approved", "out-of-scope"}:
            raise _error(
                "mapping.invalid-review-state",
                "reviewState must be proposed, approved, or out-of-scope",
                resource=resource,
                predicate=KAIROS_MAP.reviewState,
            )
        filter_resource = _one_resource(
            graph,
            resource,
            KAIROS_MAP.rowFilter,
            required=False,
        )
        fact = TableMappingFact(
            resource_uri=str(resource),
            source_table_uri=str(source),
            target_class_uri=str(target),
            mapping_type=_one_text(graph, resource, KAIROS_MAP.mappingType),
            match_type=match_type,
            row_filter=(
                _expression(graph, filter_resource) if filter_resource is not None else None
            ),
        )
        if include_proposals or review_state in {"", "approved"}:
            table_facts.append(fact)

    for resource in _mapping_resources(graph, KAIROS_MAP.ColumnMapping):
        source = _one_resource(graph, resource, KAIROS_MAP.sourceColumn)
        target = _one_resource(graph, resource, KAIROS_MAP.targetProperty)
        assert source is not None and target is not None
        match_type = _match_type(graph, resource, source, target)
        represented_alignments.add((source, _MATCH_PREDICATES[match_type], target))
        review_state = _one_text(
            graph,
            resource,
            KAIROS_MAP.reviewState,
            required=False,
        )
        if review_state and review_state not in {"proposed", "approved", "out-of-scope"}:
            raise _error(
                "mapping.invalid-review-state",
                "reviewState must be proposed, approved, or out-of-scope",
                resource=resource,
                predicate=KAIROS_MAP.reviewState,
            )
        expression_resource = _one_resource(
            graph,
            resource,
            KAIROS_MAP.expression,
            required=False,
        )
        fact = ColumnMappingFact(
            resource_uri=str(resource),
            source_column_uri=str(source),
            target_property_uri=str(target),
            match_type=match_type,
            expression=(
                _expression(graph, expression_resource) if expression_resource is not None else None
            ),
        )
        if include_proposals or review_state in {"", "approved"}:
            column_facts.append(fact)

    all_alignments = {
        (subject, predicate, target)
        for predicate in _MATCH_PREDICATES.values()
        for subject, target in graph.subject_objects(predicate)
        if isinstance(subject, URIRef) and isinstance(target, URIRef)
    }
    uncontracted = sorted(
        all_alignments - represented_alignments,
        key=lambda row: tuple(map(str, row)),
    )
    if uncontracted:
        subject, predicate, target = uncontracted[0]
        raise _error(
            "mapping.uncontracted-skos-alignment",
            (
                f"SKOS alignment {subject} -> {target} has no named v2 "
                "TableMapping or ColumnMapping contract"
            ),
            resource=subject,
            predicate=predicate,
        )

    return SourceMappings(
        tables=tuple(table_facts),
        columns=tuple(column_facts),
        namespaces=tuple(
            sorted(
                (str(prefix), str(namespace)) for prefix, namespace in graph.namespaces() if prefix
            )
        ),
    )


def bind_mapping_documents(mappings_dir: Path | None) -> SourceMappings:
    """Parse mapping Turtle files and return graph-free authored facts."""

    if mappings_dir is None or not mappings_dir.is_dir():
        return SourceMappings((), ())
    graph = Graph()
    for path in sorted(mappings_dir.rglob("*.ttl")):
        try:
            graph.parse(path, format="turtle")
        except Exception as exc:
            raise _error(
                "mapping.invalid-turtle",
                f"could not parse {path}: {exc}",
                resource=path,
                rule_id="DD-107-vocabulary",
            ) from exc
    return bind_mapping_graph(graph)


def expression_input_uris(expression: AuthoredExpressionFact | None) -> tuple[str, ...]:
    """Return deterministic source-symbol references from an authored AST."""

    if expression is None:
        return ()
    values = {expression.source_column_uri} if expression.source_column_uri else set()
    for argument in expression.arguments:
        values.update(expression_input_uris(argument))
    for branch in expression.branches:
        values.update(expression_input_uris(branch.condition))
        values.update(expression_input_uris(branch.result))
    values.update(expression_input_uris(expression.else_expression))
    return tuple(sorted(values))


def expression_summary(expression: AuthoredExpressionFact | None) -> str:
    """Return a SQL-free human-readable expression summary for reports."""

    if expression is None:
        return "direct source-column reference"
    if expression.kind == "source-column":
        return f"column <{expression.source_column_uri}>"
    if expression.kind == "literal":
        return f"typed literal ({expression.output_type})"
    if expression.kind == "null":
        return f"typed null ({expression.output_type})"
    if expression.kind == "case":
        return f"CASE ({len(expression.branches)} branches)"
    if expression.kind == "macro":
        return f"macro <{expression.macro_uri}>"
    return f"{expression.kind} {expression.operation}"


def mapping_context(facts: SourceMappings) -> tuple[dict, dict[str, str]]:
    """Build the retained bind-only facade without introducing SQL authority."""

    table_maps: dict[str, list[dict]] = {}
    for mapping in facts.tables:
        table_maps.setdefault(mapping.source_table_uri, []).append(
            {
                "mapping_id": mapping.resource_uri,
                "target_uri": mapping.target_class_uri,
                "mapping_type": mapping.mapping_type,
                "match_type": mapping.match_type,
                "filter_expression": mapping.row_filter,
            }
        )
    column_maps: dict[str, list[dict]] = {}
    for mapping in facts.columns:
        column_maps.setdefault(mapping.source_column_uri, []).append(
            {
                "mapping_id": mapping.resource_uri,
                "target_uri": mapping.target_property_uri,
                "match_type": mapping.match_type,
                "expression_fact": mapping.expression,
                "referenced_column_uris": expression_input_uris(mapping.expression)
                or (mapping.source_column_uri,),
                "expression_summary": expression_summary(mapping.expression),
            }
        )
    return (
        {"table_maps": table_maps, "column_maps": column_maps},
        dict(facts.namespaces),
    )
