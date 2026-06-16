# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the Slice 5 Power BI / source fit-gap simulation + gold seed."""

from __future__ import annotations

from pathlib import Path

from rdflib import Graph, Namespace

from kairos_ontology.claim_registry import Claim, ClaimRegistry, EvidenceSource
from kairos_ontology.pbi_fit_gap import (
    DEFER,
    FIT,
    GAP,
    PASSTHROUGH_DEPENDENCY,
    REJECT,
    SOURCE_UNUSED,
    is_source_backed,
    load_models,
    render_report,
    run_fit_gap,
    seed_gold_ext,
)
from kairos_ontology.tmdl_parser import (
    TmdlColumn,
    TmdlHierarchy,
    TmdlHierarchyLevel,
    TmdlMeasure,
    TmdlModel,
    TmdlRelationship,
    TmdlTable,
)

EXT = Namespace("https://kairos.cnext.eu/ext#")
DOMAIN_NS = "https://acme.example/ontology/sales#"


def _source_claim(cid: str, *, table: str, status: str = "approved",
                  disposition: str = "claim", source: bool = True) -> Claim:
    ev = [EvidenceSource(type="tmdl_concept_mapping", model="SalesModel", table=table)]
    if source:
        ev.append(EvidenceSource(type="source_table", system="erp", table=table.lower()))
    return Claim(
        id=cid, type="class", status=status, disposition=disposition, origin="imported",
        class_uri=f"{DOMAIN_NS}{cid.title()}", evidence_sources=ev,
    )


def _registry(*claims: Claim) -> ClaimRegistry:
    return ClaimRegistry(domain="sales", claims=list(claims))


def _model() -> TmdlModel:
    return TmdlModel(
        name="SalesModel",
        tables=[
            TmdlTable(
                name="Customer",
                columns=[TmdlColumn(name="CustomerId"), TmdlColumn(name="Name")],
            ),
            TmdlTable(
                name="Legacy",
                columns=[
                    TmdlColumn(name="OldFlag"),
                    TmdlColumn(name="SecretKey", is_hidden=True),
                ],
            ),
            TmdlTable(
                name="Sales",
                columns=[TmdlColumn(name="CustomerId"), TmdlColumn(name="Amount")],
                measures=[
                    TmdlMeasure(name="Total Sales", expression="SUM(Sales[Amount])",
                                format_string="#,##0.00"),
                    TmdlMeasure(name="Constant", expression="1"),
                ],
            ),
        ],
        relationships=[
            TmdlRelationship(from_table="Sales", from_column="CustomerId",
                             to_table="Customer", to_column="CustomerId"),
        ],
    )


# --- source-backed detection ------------------------------------------------


def test_is_source_backed():
    backed = _source_claim("c1", table="Customer", source=True)
    unbacked = _source_claim("c2", table="Customer", source=False)
    assert is_source_backed(backed)
    assert not is_source_backed(unbacked)


# --- field classification ---------------------------------------------------


def test_field_fit_when_approved_source_backed():
    reg = _registry(_source_claim("customer", table="Customer"))
    report = run_fit_gap(_model(), reg)
    fields = {f.name: f.classification for f in report.by_kind("field")}
    assert fields["Customer[CustomerId]"] == FIT
    assert fields["Customer[Name]"] == FIT


def test_field_gap_when_claim_not_source_backed():
    reg = _registry(_source_claim("customer", table="Customer", source=False))
    report = run_fit_gap(_model(), reg)
    fields = {f.name: f.classification for f in report.by_kind("field")}
    assert fields["Customer[CustomerId]"] == GAP


def test_field_gap_when_claim_only_proposed():
    reg = _registry(_source_claim("customer", table="Customer", status="proposed"))
    report = run_fit_gap(_model(), reg)
    fields = {f.name: f.classification for f in report.by_kind("field")}
    assert fields["Customer[Name]"] == GAP


def test_field_defer_and_reject_for_unclaimed_table():
    reg = _registry(_source_claim("customer", table="Customer"))
    report = run_fit_gap(_model(), reg)
    fields = {f.name: f.classification for f in report.by_kind("field")}
    # Legacy table has no claim → visible defer, hidden reject.
    assert fields["Legacy[OldFlag]"] == DEFER
    assert fields["Legacy[SecretKey]"] == REJECT


# --- measure classification -------------------------------------------------


def test_measure_fit_and_pure_calculated_defer():
    reg = _registry(
        _source_claim("customer", table="Customer"),
        _source_claim("sales", table="Sales"),
    )
    report = run_fit_gap(_model(), reg)
    measures = {f.name: f.classification for f in report.by_kind("measure")}
    assert measures["Sales[Total Sales]"] == FIT
    assert measures["Sales[Constant]"] == DEFER


def test_measure_passthrough_dependency():
    reg = _registry(
        _source_claim("customer", table="Customer"),
        _source_claim("sales", table="Sales", disposition="passthrough"),
    )
    report = run_fit_gap(_model(), reg)
    measures = {f.name: f.classification for f in report.by_kind("measure")}
    assert measures["Sales[Total Sales]"] == PASSTHROUGH_DEPENDENCY


def test_measure_gap_when_field_ungoverned():
    # Sales table has no claim → its Amount field is defer → measure degrades to gap.
    reg = _registry(_source_claim("customer", table="Customer"))
    report = run_fit_gap(_model(), reg)
    measures = {f.name: f.classification for f in report.by_kind("measure")}
    assert measures["Sales[Total Sales]"] == GAP


# --- relationship classification --------------------------------------------


def test_relationship_fit_when_both_endpoints_fit():
    reg = _registry(
        _source_claim("customer", table="Customer"),
        _source_claim("sales", table="Sales"),
    )
    report = run_fit_gap(_model(), reg)
    rels = report.by_kind("relationship")
    assert len(rels) == 1
    assert rels[0].classification == FIT


def test_relationship_gap_when_endpoint_unclaimed():
    reg = _registry(_source_claim("customer", table="Customer"))
    report = run_fit_gap(_model(), reg)
    assert report.by_kind("relationship")[0].classification == GAP


# --- source supply without demand -------------------------------------------


def test_source_supply_without_demand():
    # An approved source-backed claim with NO tmdl evidence → source-unused.
    unused = Claim(
        id="unused", type="class", status="approved", disposition="claim",
        origin="imported", class_uri=f"{DOMAIN_NS}Unused",
        evidence_sources=[EvidenceSource(type="source_table", system="erp", table="orphan")],
    )
    reg = _registry(_source_claim("customer", table="Customer"), unused)
    report = run_fit_gap(_model(), reg)
    unused_findings = report.by_kind("source-unused")
    assert len(unused_findings) == 1
    assert unused_findings[0].classification == SOURCE_UNUSED
    assert "erp" in unused_findings[0].reason


# --- markdown rendering -----------------------------------------------------


def test_render_report_has_sections_and_guardrail():
    reg = _registry(_source_claim("customer", table="Customer"))
    md = render_report(run_fit_gap(_model(), reg))
    assert "# Power BI / source fit-gap — sales" in md
    assert "evidence, not authority" in md
    assert "## Summary" in md
    assert "## Fields" in md
    assert "## Measures" in md
    assert "## Relationships" in md


# --- gold seed --------------------------------------------------------------


def _gold_model() -> TmdlModel:
    return TmdlModel(
        name="SalesModel",
        tables=[
            TmdlTable(
                name="Sales",
                measures=[
                    TmdlMeasure(name="Total Sales", expression="SUM(Sales[Amount])",
                                format_string="#,##0.00"),
                ],
                hierarchies=[
                    TmdlHierarchy(
                        name="Geography",
                        levels=[
                            TmdlHierarchyLevel(name="Country", column="Country", ordinal=0),
                            TmdlHierarchyLevel(name="City", column="City", ordinal=1),
                        ],
                    )
                ],
            )
        ],
    )


def test_seed_gold_ext_emits_measure_and_hierarchy_annotations():
    ttl = seed_gold_ext(_gold_model(), "sales", namespace=DOMAIN_NS)
    assert ttl.startswith("# CANDIDATE gold-extension seed")
    assert "evidence, not authority" in ttl

    graph = Graph()
    graph.parse(data=ttl, format="turtle")

    DOMAIN = Namespace(DOMAIN_NS)
    exprs = list(graph.objects(DOMAIN.totalSales, EXT.measureExpression))
    assert [str(e) for e in exprs] == ["SUM(Sales[Amount])"]
    fmts = list(graph.objects(DOMAIN.totalSales, EXT.measureFormatString))
    assert [str(f) for f in fmts] == ["#,##0.00"]

    # Hierarchy levels become hierarchyName + hierarchyLevel on the level column.
    names = list(graph.objects(DOMAIN.country, EXT.hierarchyName))
    assert [str(n) for n in names] == ["Geography"]
    levels = list(graph.objects(DOMAIN.city, EXT.hierarchyLevel))
    assert [int(level_value) for level_value in levels] == [2]


def test_seed_gold_ext_derives_namespace_from_registry():
    reg = _registry(_source_claim("customer", table="Customer"))
    ttl = seed_gold_ext(_gold_model(), "sales", registry=reg)
    graph = Graph()
    graph.parse(data=ttl, format="turtle")
    DOMAIN = Namespace(DOMAIN_NS)
    assert list(graph.objects(DOMAIN.totalSales, EXT.measureExpression))


# --- source loading ---------------------------------------------------------


def test_load_models_standalone_file(tmp_path: Path):
    tmdl = tmp_path / "Sales.tmdl"
    tmdl.write_text(
        "table Sales\n"
        "\tcolumn Amount\n"
        "\t\tdataType: double\n"
        "\tmeasure 'Total' = SUM(Sales[Amount])\n",
        encoding="utf-8",
    )
    models = load_models(tmdl)
    assert len(models) == 1
    assert models[0].tables[0].name == "Sales"
    assert models[0].tables[0].measures[0].name == "Total"
