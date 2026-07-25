# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused DD-106 through DD-115 vocabulary and scenario-authority tests."""

from pathlib import Path

import pytest
from pyshacl import validate
from rdflib import Graph, Literal, Namespace, OWL, RDF, RDFS

ROOT = Path(__file__).resolve().parent.parent
SCAFFOLD = ROOT / "src" / "kairos_ontology" / "scaffold"
SCENARIO = ROOT / "tests" / "scenarios" / "acme-hub"
PREP = Namespace("https://kairos.cnext.eu/preparation#")
BRONZE = Namespace("https://kairos.cnext.eu/bronze#")
EXT = Namespace("https://kairos.cnext.eu/ext#")
KMAP = Namespace("https://kairos.cnext.eu/mapping#")


def _parse(path: Path) -> Graph:
    return Graph().parse(path, format="turtle")


def _validate_ext(data: str) -> tuple[bool, str]:
    graph = Graph().parse(data=data, format="turtle")
    conforms, _, report = validate(
        graph,
        shacl_graph=_parse(SCAFFOLD / "kairos-ext-shapes.shacl.ttl"),
        inference="rdfs",
    )
    return conforms, report


def test_policy_vocabularies_and_shapes_are_declared_ontologies():
    for name in [
        "kairos-prep.ttl",
        "kairos-prep-shapes.shacl.ttl",
        "kairos-map.ttl",
        "kairos-map-shapes.shacl.ttl",
        "kairos-ext.ttl",
        "kairos-ext-shapes.shacl.ttl",
    ]:
        graph = _parse(SCAFFOLD / name)
        ontologies = set(graph.subjects(RDF.type, OWL.Ontology))
        assert len(ontologies) == 1
        ontology = next(iter(ontologies))
        assert graph.value(ontology, RDFS.label)
        assert graph.value(ontology, RDFS.comment)
        assert graph.value(ontology, OWL.versionInfo)


def test_prep_vocabulary_covers_dd106_authoring_contract():
    graph = _parse(SCAFFOLD / "kairos-prep.ttl")
    required = {
        "PreparationPolicy",
        "prepMode",
        "physicalRename",
        "cleanupRule",
        "targetType",
        "parsePolicy",
        "errorPolicy",
        "sentinelNormalization",
        "evidence",
        "rawOperationColumn",
        "rawUpdateTimestampColumn",
        "rawEffectiveTimestampColumn",
        "rawIngestionTimestampColumn",
        "rawSequenceColumn",
        "normalizedOperationField",
        "recordKeyComponent",
        "scalarJsonExtraction",
        "arrayChildContract",
        "TechnicalDedupe",
        "dedupeKeyColumn",
        "dedupeOrderTerm",
        "orderPosition",
        "sortDirection",
        "schemaChangePolicy",
        "adapterSupport",
        "adapterDeviation",
    }
    subjects = {str(subject).removeprefix(str(PREP)) for subject in graph.subjects()}
    assert required <= subjects
    assert not any("sql" in name.lower() for name in subjects)


def test_mapping_vocabulary_covers_dd107_and_removes_raw_sql_terms():
    graph = _parse(SCAFFOLD / "kairos-map.ttl")
    required = {
        "TableMapping",
        "ColumnMapping",
        "SourceColumnExpression",
        "LiteralExpression",
        "NullExpression",
        "OperatorExpression",
        "FunctionExpression",
        "CaseExpression",
        "MacroExpression",
        "outputType",
        "nullable",
        "nullPolicy",
        "determinism",
        "requiresCapability",
        "rowFilter",
    }
    subjects = {str(subject).removeprefix(str(KMAP)) for subject in graph.subjects()}
    assert required <= subjects
    assert {
        "transform",
        "transformExpression",
        "filterCondition",
        "sourceColumns",
        "defaultValue",
        "deduplicationKey",
        "deduplicationOrder",
    }.isdisjoint(subjects)


def test_passthrough_with_normalization_fails_shacl():
    data = _parse(SCAFFOLD / "kairos-prep.ttl")
    data.parse(
        data="""
            @prefix ex: <https://example.test/#> .
            @prefix prep: <https://kairos.cnext.eu/preparation#> .
            @prefix bronze: <https://kairos.cnext.eu/bronze#> .
            ex:table a bronze:SourceTable .
            ex:column a bronze:SourceColumn .
            ex:policy a prep:PreparationPolicy ;
                prep:sourceTable ex:table ;
                prep:prepMode "passthrough" ;
                prep:schemaChangePolicy "fail" ;
                prep:recordKeyPolicy ex:key ;
                prep:physicalRename ex:rename .
            ex:key a prep:RecordKeyPolicy ;
                prep:sourceScope "source" ;
                prep:tableScope "table" ;
                prep:recordKeyComponent ex:column ;
                prep:recordKeyOutput ex:keyOutput .
            ex:keyOutput a prep:PreparedColumn ;
                prep:targetColumnName "_source_record_key" ;
                prep:targetType "string" .
            ex:rename a prep:PhysicalRename ;
                prep:sourceColumn ex:column ;
                prep:targetColumnName "safe_name" .
        """,
        format="turtle",
    )
    conforms, _, report = validate(
        data,
        shacl_graph=_parse(SCAFFOLD / "kairos-prep-shapes.shacl.ttl"),
        inference="rdfs",
    )
    assert not conforms
    assert "passthrough cannot contain normalization" in report


def test_mapped_source_table_without_prep_policy_fails_shacl():
    data = _parse(SCAFFOLD / "kairos-prep.ttl")
    data.parse(
        data="""
            @prefix ex: <https://example.test/#> .
            @prefix bronze: <https://kairos.cnext.eu/bronze#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            ex:table a bronze:SourceTable ;
                skos:exactMatch ex:Entity .
        """,
        format="turtle",
    )
    conforms, _, report = validate(
        data,
        shacl_graph=_parse(SCAFFOLD / "kairos-prep-shapes.shacl.ttl"),
        inference="rdfs",
    )
    assert not conforms
    assert "Every mapped source table" in report


def test_scenario_has_one_valid_prep_policy_per_source_table():
    shapes = _parse(SCAFFOLD / "kairos-prep-shapes.shacl.ttl")
    vocabulary = _parse(SCAFFOLD / "kairos-prep.ttl")
    for source in ["adminpulse", "billingpro", "crmsystem", "logisticspro"]:
        data = Graph()
        data += vocabulary
        data += _parse(
            SCENARIO / "integration" / "sources" / source / f"{source}.vocabulary.ttl"
        )
        data += _parse(
            SCENARIO / "integration" / "preparation" / f"{source}-prep.ttl"
        )
        conforms, _, report = validate(data, shacl_graph=shapes, inference="rdfs")
        assert conforms, report
        tables = set(data.subjects(RDF.type, BRONZE.SourceTable))
        governed = list(data.objects(None, PREP.sourceTable))
        assert len(governed) == len(tables)
        assert set(governed) == tables


def test_ext_vocabulary_has_new_authorities_and_no_obsolete_terms():
    graph = _parse(SCAFFOLD / "kairos-ext.ttl")
    subjects = {str(subject).removeprefix(str(EXT)) for subject in graph.subjects()}
    required = {
        "identityStrategy",
        "entityInstanceIriPolicy",
        "keyScope",
        "drivingSource",
        "changeDetectionStrategy",
        "contributionLineagePolicy",
        "multiSourcePolicy",
        "incrementalPolicy",
        "scd2TimeBasis",
        "hashPolicy",
        "silverForeignKeyMissingPolicy",
        "dataQualityRule",
        "goldProductProfile",
        "goldSourceModel",
        "goldSourceVersion",
        "factType",
        "bridgeGrain",
        "bridgeEndpointBinding",
        "Measure",
        "measureDataType",
        "measureValidationEvidence",
        "measureLifecycleState",
        "measureDependency",
        "CalendarProfile",
        "calendarApprovalStatus",
        "SecurityPolicy",
        "securityTestEvidence",
    }
    removed = {
        "includeNaturalKeyColumn",
        "surrogateKeyStrategy",
        "silverSourceRef",
        "inlineRefThreshold",
        "generateDateDimension",
        "generateTimeIntelligence",
        "goldColumnName",
        "goldDataType",
        "goldExclude",
        "goldInheritanceStrategy",
        "hierarchyLevel",
        "hierarchyName",
        "degenerateDimension",
        "olsRestricted",
        "incrementalColumn",
        "rolePlayingAs",
    }
    assert required <= subjects
    assert removed.isdisjoint(subjects)
    assert (EXT.contractedTransformationRef, RDF.type, OWL.AnnotationProperty) in graph
    assert (
        next(graph.subjects(RDF.type, OWL.Ontology)),
        OWL.imports,
        Namespace("https://kairos.cnext.eu/")["mdm"],
    ) in graph


def test_fresh_hub_extension_templates_do_not_contain_retired_terms():
    retired = {
        "surrogateKeyStrategy",
        "includeNaturalKeyColumn",
        "inlineRefThreshold",
        "partitionBy",
        "clusterBy",
        "gdprSatelliteOf",
        "auditEnvelope",
        "generateDateDimension",
        "rolePlayingAs",
    }
    templates = SCAFFOLD / "ontology-hub" / "model" / "extensions"
    for name in ["silver-ext.ttl.template", "gold-ext.ttl.template"]:
        text = (templates / name).read_text(encoding="utf-8")
        assert retired.isdisjoint(text.split()), name
        assert not any(term in text for term in retired), name


def test_entity_instance_iri_policy_is_declared_and_shaped():
    vocabulary = _parse(SCAFFOLD / "kairos-ext.ttl")
    assert (
        EXT.entityInstanceIriPolicy,
        RDF.type,
        OWL.AnnotationProperty,
    ) in vocabulary

    conforms, report = _validate_ext(
        """
        @prefix ex: <https://example.test/#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        ex:Entity
            kairos-ext:businessGrain "one entity" ;
            kairos-ext:identityStrategy "business-key" ;
            kairos-ext:entityInstanceIriPolicy "sometimes" ;
            kairos-ext:keyScope "domain" ;
            kairos-ext:sourceIdentity ex:key ;
            kairos-ext:changeDetectionStrategy "compare-columns" ;
            kairos-ext:lineagePolicy "source-record-and-load" .
        """
    )
    assert not conforms
    assert "entityInstanceIriPolicy" in report


def test_identity_shape_accepts_valid_single_and_exact_equivalence_contracts():
    single, single_report = _validate_ext(
        """
        @prefix ex: <https://example.test/#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        ex:Entity
            kairos-ext:businessGrain "one entity" ;
            kairos-ext:identityStrategy "business-key" ;
            kairos-ext:entityInstanceIriPolicy "emit" ;
            kairos-ext:keyScope "domain" ;
            kairos-ext:sourceIdentity ex:key ;
            kairos-ext:naturalKey "business_id" ;
            kairos-ext:changeDetectionStrategy "compare-columns" ;
            kairos-ext:lineagePolicy "source-record-and-load" .
        """
    )
    assert single, single_report

    exact, exact_report = _validate_ext(
        """
        @prefix ex: <https://example.test/#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        ex:Entity
            kairos-ext:businessGrain "one conformed entity" ;
            kairos-ext:identityStrategy "deterministic-integration-key" ;
            kairos-ext:entityInstanceIriPolicy "emit" ;
            kairos-ext:keyScope "domain" ;
            kairos-ext:sourceIdentity ex:keyA, ex:keyB ;
            kairos-ext:drivingSource ex:keyA ;
            kairos-ext:naturalKey "business_id" ;
            kairos-ext:changeDetectionStrategy "compare-columns" ;
            kairos-ext:lineagePolicy "source-record-and-load" ;
            kairos-ext:multiSourcePolicy ex:Sources .
        ex:Sources a kairos-ext:MultiSourcePolicy ;
            kairos-ext:branchRelationship "exactly-equivalent" ;
            kairos-ext:normalizationPolicy "reviewed exact normalization" ;
            kairos-ext:sourcePrecedence "declared-order:https://example.test/#keyA,https://example.test/#keyB" ;
            kairos-ext:attributeConflictPolicy "quarantine" ;
            kairos-ext:keyCollisionPolicy "quarantine" ;
            kairos-ext:branchDeletionPolicy "delete-when-all-branches-deleted" ;
            kairos-ext:branchLateArrivalPolicy "reconcile-on-arrival" ;
            kairos-ext:reconciliationTest "exact-equivalence-test" .
        """
    )
    assert exact, exact_report


@pytest.mark.parametrize(
    ("identity_body", "expected"),
    [
        (
            """
            kairos-ext:identityStrategy "surrogate-only" ;
            kairos-ext:keyScope "source-table" ;
            kairos-ext:naturalKey "invented_key" ;
            kairos-ext:reconciliationLimitation "manual only" ;
            """,
            "surrogate-only identity forbids naturalKey",
        ),
        (
            """
            kairos-ext:identityStrategy "business-key" ;
            kairos-ext:keyScope "domain" ;
            kairos-ext:naturalKey "business_id" ;
            kairos-ext:drivingSource ex:keyA ;
            """,
            "single-source identity deterministically uses only-source",
        ),
        (
            """
            kairos-ext:identityStrategy "business-key" ;
            kairos-ext:keyScope "domain" ;
            kairos-ext:naturalKey "business_id" ;
            kairos-ext:sourceIdentity ex:keyB ;
            kairos-ext:multiSourcePolicy ex:Sources ;
            """,
            "multi-contributor identity requires one drivingSource",
        ),
    ],
)
def test_identity_shape_rejects_strategy_and_driving_field_contradictions(
    identity_body: str,
    expected: str,
):
    conforms, report = _validate_ext(
        f"""
        @prefix ex: <https://example.test/#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        ex:Entity
            kairos-ext:businessGrain "one entity" ;
            kairos-ext:entityInstanceIriPolicy "emit" ;
            kairos-ext:sourceIdentity ex:keyA ;
            {identity_body}
            kairos-ext:changeDetectionStrategy "compare-columns" ;
            kairos-ext:lineagePolicy "source-record-and-load" .
        ex:Sources a kairos-ext:MultiSourcePolicy ;
            kairos-ext:branchRelationship "overlapping" ;
            kairos-ext:normalizationPolicy "reviewed normalization" ;
            kairos-ext:sourcePrecedence "none-without-approved-exact-equivalence" ;
            kairos-ext:attributeConflictPolicy "retain-branch-values" ;
            kairos-ext:keyCollisionPolicy "retain-source-scoped-identities" ;
            kairos-ext:branchDeletionPolicy "retain-other-branches" ;
            kairos-ext:branchLateArrivalPolicy "reconcile-on-arrival" ;
            kairos-ext:reconciliationTest "branch-test" .
        """
    )
    assert not conforms
    assert expected in report


@pytest.mark.parametrize(
    ("annotation", "value"),
    [
        ("scdType", '"1"'),
        ("identityStrategy", '"business-key"'),
    ],
)
def test_common_silver_materialization_annotations_trigger_identity_shape(
    annotation: str,
    value: str,
):
    conforms, report = _validate_ext(
        f"""
        @prefix ex: <https://example.test/#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        ex:Entity kairos-ext:{annotation} {value} .
        """
    )
    assert not conforms
    assert "businessGrain" in report


@pytest.mark.parametrize(
    ("annotation", "value"),
    [
        ("goldTableType", '"dimension"'),
        ("goldInclude", "true"),
    ],
)
def test_common_gold_materialization_annotations_trigger_table_shape(
    annotation: str,
    value: str,
):
    conforms, report = _validate_ext(
        f"""
        @prefix ex: <https://example.test/#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        ex:Entity kairos-ext:{annotation} {value} .
        """
    )
    assert not conforms
    assert "goldTableType" in report


def _measure_data(state: str, *, expression: bool, dependency: bool) -> str:
    expression_triple = (
        'kairos-ext:measureExpression "SUM([amount])" ;' if expression else ""
    )
    dependency_triple = (
        "kairos-ext:measureColumnDependency ex:amount ;" if dependency else ""
    )
    return f"""
        @prefix ex: <https://example.test/#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        ex:Measure a kairos-ext:Measure ;
            kairos-ext:measureId "example.total" ;
            kairos-ext:measureDefinition "A reviewed business definition." ;
            {expression_triple}
            {dependency_triple}
            kairos-ext:measureLifecycleState "{state}" ;
            kairos-ext:measureDataType "decimal" ;
            kairos-ext:measureFormatString "#,##0.00" ;
            kairos-ext:measureFolder "Examples" ;
            kairos-ext:measureOwnerRole "Data Owner" ;
            kairos-ext:measureValidationTest "example-measure-test" ;
            kairos-ext:measureValidationEvidence "dq-run:example" .
    """


def test_intent_measure_may_omit_expression_and_dependencies():
    conforms, report = _validate_ext(
        _measure_data("intent", expression=False, dependency=False)
    )
    assert conforms, report


@pytest.mark.parametrize("state", ["provisional", "validated", "approved"])
@pytest.mark.parametrize(
    ("expression", "dependency"),
    [(False, True), (True, False)],
)
def test_later_measure_states_require_expression_and_dependencies(
    state: str,
    expression: bool,
    dependency: bool,
):
    conforms, report = _validate_ext(
        _measure_data(state, expression=expression, dependency=dependency)
    )
    assert not conforms
    assert "require DAX, dependencies, type, format, and folder" in report


def test_scenario_silver_authorities_declare_entity_instance_iri_policy():
    for name in [
        "client-silver-ext.ttl",
        "invoice-silver-ext.ttl",
        "logistics-silver-ext.ttl",
    ]:
        graph = _parse(SCENARIO / "model" / "extensions" / name)
        entities = set(graph.subjects(EXT.identityStrategy, None))
        assert entities
        for entity in entities:
            policies = set(graph.objects(entity, EXT.entityInstanceIriPolicy))
            assert policies in ({Literal("emit")}, {Literal("omit")}), (name, entity)


def test_scenario_uses_prep_array_authority_and_first_class_gold_policy():
    prep = _parse(
        SCENARIO / "integration" / "preparation" / "billingpro-prep.ttl"
    )
    assert list(prep.subjects(RDF.type, PREP.ArrayChildContract))

    mapping_text = (
        SCENARIO / "model" / "mappings" / "billingpro-to-invoice.ttl"
    ).read_text(encoding="utf-8")
    assert "preparation/billingpro#> ." in mapping_text
    assert "tblInvoiceLine_LineDetails" not in mapping_text

    gold = _parse(SCENARIO / "model" / "extensions" / "invoice-gold-ext.ttl")
    assert list(gold.triples((None, EXT.goldProductProfile, None)))
    assert list(gold.subjects(RDF.type, EXT.Measure))
    conforms, _, report = validate(
        gold,
        shacl_graph=_parse(SCAFFOLD / "kairos-ext-shapes.shacl.ttl"),
        inference="rdfs",
    )
    assert conforms, report
