# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the deterministic source-delta change-management backend
(Slice 6, DD-EL-8)."""

from __future__ import annotations

from kairos_ontology.claim_registry import (
    Claim,
    ClaimRegistry,
    ContractMeta,
    dump_registry,
    load_registry,
    merge_preserving_decisions,
    write_registry,
)
from kairos_ontology.source_delta import (
    ADDITIVE,
    BREAKING,
    CHANGED_GRAIN,
    CHANGED_KEY,
    CHANGED_TYPE,
    MAPPING_ONLY,
    MAPS_TO_EXISTING_CLASS,
    NEW_CLAIM_CANDIDATE,
    NEW_COLUMN_TO_PROPERTY,
    NEW_REFERENCE_LIST,
    NEW_RELATIONSHIP,
    PASSTHROUGH_CANDIDATE,
    REMOVED_COLUMN,
    SEMANTIC_CONFLICT,
    Delta,
    ImpactReport,
    SourceColumn,
    SourceTable,
    _is_widening,
    bump_semver,
    classify_deltas,
    load_approved_targets,
    load_mapping_targets,
    load_source_tables,
    run_source_delta,
    suggest_version_bump,
)

NS = "https://acme.example/bronze/sys#"


def _col(name, dtype="nvarchar(50)", nullable=True):
    return SourceColumn(name=name, data_type=dtype, nullable=nullable, uri=f"{NS}t_{name}")


def _table(name, columns, pk=None):
    return SourceTable(
        system="sys",
        name=name,
        uri=f"{NS}{name}",
        primary_key=pk or [],
        columns=columns,
    )


# ---------------------------------------------------------------------------
# Version policy (§13.5)
# ---------------------------------------------------------------------------


class TestVersionPolicy:
    def test_bump_precedence_major_wins(self):
        deltas = [
            Delta("sys", "t", MAPS_TO_EXISTING_CLASS, MAPPING_ONLY),
            Delta("sys", "t", PASSTHROUGH_CANDIDATE, ADDITIVE),
            Delta("sys", "t", CHANGED_KEY, BREAKING),
        ]
        assert suggest_version_bump(deltas) == "major"

    def test_bump_minor_when_additive_only(self):
        deltas = [
            Delta("sys", "t", MAPS_TO_EXISTING_CLASS, MAPPING_ONLY),
            Delta("sys", "t", PASSTHROUGH_CANDIDATE, ADDITIVE),
        ]
        assert suggest_version_bump(deltas) == "minor"

    def test_bump_patch_when_mapping_only(self):
        deltas = [Delta("sys", "t", MAPS_TO_EXISTING_CLASS, MAPPING_ONLY)]
        assert suggest_version_bump(deltas) == "patch"

    def test_bump_none_when_empty(self):
        assert suggest_version_bump([]) == "none"

    def test_bump_semver(self):
        assert bump_semver("1.2.3", "major") == "2.0.0"
        assert bump_semver("1.2.3", "minor") == "1.3.0"
        assert bump_semver("1.2.3", "patch") == "1.2.4"
        assert bump_semver("1.2.3", "none") == "1.2.3"
        assert bump_semver(None, "minor") == "0.1.0"


class TestWidening:
    def test_int_widening(self):
        assert _is_widening("int", "bigint") is True
        assert _is_widening("bigint", "int") is False
        assert _is_widening("smallint", "int") is True

    def test_varchar_widening(self):
        assert _is_widening("nvarchar(50)", "nvarchar(100)") is True
        assert _is_widening("nvarchar(100)", "nvarchar(50)") is False
        assert _is_widening("nvarchar(50)", "nvarchar(max)") is True
        assert _is_widening("nvarchar(max)", "nvarchar(50)") is False

    def test_unrelated_types_not_widening(self):
        assert _is_widening("int", "nvarchar(50)") is False
        assert _is_widening("nvarchar(50)", "int") is False

    def test_identical_is_widening(self):
        assert _is_widening("int", "int") is True


# ---------------------------------------------------------------------------
# Table-level classification (§13.2)
# ---------------------------------------------------------------------------


class TestNewTableClassification:
    def test_maps_to_existing_approved_class(self):
        table = _table("Client", [_col("ClientID", "int", False), _col("Name")], pk=["ClientID"])
        mapping_targets = {table.uri: {"Client"}, f"{NS}t_Name": {"clientName"}}
        deltas = classify_deltas(
            {"Client": table}, mapping_targets, {"Client"}, {"clientName"}, set()
        )
        types = {d.delta_type for d in deltas}
        assert MAPS_TO_EXISTING_CLASS in types
        table_delta = next(d for d in deltas if d.delta_type == MAPS_TO_EXISTING_CLASS)
        assert table_delta.impact == MAPPING_ONLY
        # mapped column -> new-column-to-property; unmapped Name? Name IS mapped here.
        assert NEW_COLUMN_TO_PROPERTY in types

    def test_maps_to_unclaimed_class_is_new_claim_candidate(self):
        table = _table("Invoice", [_col("InvoiceID", "int", False)], pk=["InvoiceID"])
        mapping_targets = {table.uri: {"Invoice"}}
        deltas = classify_deltas({"Invoice": table}, mapping_targets, set(), set(), set())
        assert [d.delta_type for d in deltas] == [NEW_CLAIM_CANDIDATE]
        assert deltas[0].impact == ADDITIVE

    def test_unmapped_reference_table(self):
        table = _table(
            "ClientTypeCode", [_col("Code", "int", False), _col("Label")], pk=["Code"]
        )
        deltas = classify_deltas({"ClientTypeCode": table}, {}, set(), set(), set())
        assert deltas[0].delta_type == NEW_REFERENCE_LIST
        assert deltas[0].impact == ADDITIVE

    def test_unmapped_plain_table_is_new_claim_candidate(self):
        table = _table(
            "Shipment",
            [_col("ShipmentID", "int", False), _col("Origin"), _col("Destination")],
            pk=["ShipmentID"],
        )
        deltas = classify_deltas({"Shipment": table}, {}, set(), set(), {"Shipment"})
        assert deltas[0].delta_type == NEW_CLAIM_CANDIDATE
        assert "affinity" in deltas[0].detail


class TestColumnClassification:
    def _mapped_table(self):
        # a table mapped to an approved class, with a mix of column shapes
        table = _table(
            "Client",
            [
                _col("ClientID", "int", False),
                _col("Email"),  # unmapped, no property -> passthrough
                _col("RegionCode"),  # fk-shaped -> relationship
                _col("Name"),  # mapped -> new-column-to-property
            ],
            pk=["ClientID"],
        )
        mapping_targets = {table.uri: {"Client"}, f"{NS}t_Name": {"clientName"}}
        return table, mapping_targets

    def test_new_column_to_property(self):
        table, mt = self._mapped_table()
        deltas = classify_deltas({"Client": table}, mt, {"Client"}, {"clientName"}, set())
        d = next(x for x in deltas if x.column == "Name")
        assert d.delta_type == NEW_COLUMN_TO_PROPERTY
        assert d.impact == MAPPING_ONLY

    def test_passthrough_candidate(self):
        table, mt = self._mapped_table()
        deltas = classify_deltas({"Client": table}, mt, {"Client"}, set(), set())
        d = next(x for x in deltas if x.column == "Email")
        assert d.delta_type == PASSTHROUGH_CANDIDATE
        assert d.impact == ADDITIVE

    def test_new_relationship(self):
        table, mt = self._mapped_table()
        deltas = classify_deltas({"Client": table}, mt, {"Client"}, set(), set())
        d = next(x for x in deltas if x.column == "RegionCode")
        assert d.delta_type == NEW_RELATIONSHIP
        assert d.impact == ADDITIVE


# ---------------------------------------------------------------------------
# Changed-table classification (baseline diff)
# ---------------------------------------------------------------------------


class TestChangedTable:
    def test_changed_key_and_grain(self):
        baseline = _table("T", [_col("A", "int", False), _col("B")], pk=["A"])
        new = _table("T", [_col("A", "int", False), _col("B")], pk=["A", "B"])
        deltas = classify_deltas({"T": new}, {}, set(), set(), set(), baseline={"T": baseline})
        types = {d.delta_type for d in deltas}
        assert CHANGED_KEY in types
        assert CHANGED_GRAIN in types
        assert all(
            d.impact == BREAKING for d in deltas if d.delta_type in (CHANGED_KEY, CHANGED_GRAIN)
        )

    def test_removed_unmapped_column(self):
        baseline = _table("T", [_col("A", "int", False), _col("B"), _col("C")], pk=["A"])
        new = _table("T", [_col("A", "int", False), _col("B")], pk=["A"])
        deltas = classify_deltas({"T": new}, {}, set(), set(), set(), baseline={"T": baseline})
        d = next(x for x in deltas if x.column == "C")
        assert d.delta_type == REMOVED_COLUMN
        assert d.impact == BREAKING

    def test_removed_mapped_column_is_semantic_conflict(self):
        baseline = _table("T", [_col("A", "int", False), _col("C")], pk=["A"])
        new = _table("T", [_col("A", "int", False)], pk=["A"])
        # C was mapped -> removing it loses the modeled concept's source
        mapping_targets = {f"{NS}t_C": {"someProp"}}
        deltas = classify_deltas(
            {"T": new}, mapping_targets, set(), set(), set(), baseline={"T": baseline}
        )
        d = next(x for x in deltas if x.column == "C")
        assert d.delta_type == SEMANTIC_CONFLICT
        assert d.impact == BREAKING
        assert d.tactics  # tactics attached for breaking deltas

    def test_changed_type_breaking(self):
        baseline = _table("T", [_col("A", "int", False), _col("B", "int")], pk=["A"])
        new = _table("T", [_col("A", "int", False), _col("B", "nvarchar(50)")], pk=["A"])
        deltas = classify_deltas({"T": new}, {}, set(), set(), set(), baseline={"T": baseline})
        d = next(x for x in deltas if x.column == "B")
        assert d.delta_type == CHANGED_TYPE
        assert d.impact == BREAKING

    def test_changed_type_widening_is_additive(self):
        baseline = _table("T", [_col("A", "int", False), _col("B", "int")], pk=["A"])
        new = _table("T", [_col("A", "int", False), _col("B", "bigint")], pk=["A"])
        deltas = classify_deltas({"T": new}, {}, set(), set(), set(), baseline={"T": baseline})
        d = next(x for x in deltas if x.column == "B")
        assert d.delta_type == CHANGED_TYPE
        assert d.impact == ADDITIVE

    def test_added_column_on_changed_table(self):
        baseline = _table("T", [_col("A", "int", False)], pk=["A"])
        new = _table("T", [_col("A", "int", False), _col("Notes")], pk=["A"])
        deltas = classify_deltas({"T": new}, {}, set(), set(), set(), baseline={"T": baseline})
        d = next(x for x in deltas if x.column == "Notes")
        assert d.delta_type == PASSTHROUGH_CANDIDATE


# ---------------------------------------------------------------------------
# Impact report rendering (§13.4)
# ---------------------------------------------------------------------------


class TestImpactReport:
    def test_render_contains_required_sections(self):
        deltas = [
            Delta("sys", "T", NEW_CLAIM_CANDIDATE, ADDITIVE),
            Delta("sys", "T", CHANGED_KEY, BREAKING, detail="pk changed",
                  tactics=("version the silver table",)),
        ]
        report = ImpactReport("sys", deltas, silver_version="1.2.0", gold_version="1.0.0")
        md = report.render_markdown()
        assert "Source delta impact report" in md
        assert "Breaking changes" in md
        assert "Expected silver table additions" in md
        assert "Required approvals" in md
        assert "Suggested contract version" in md
        assert "1.2.0" in md and "2.0.0" in md  # major bump suggested
        assert report.has_breaking is True
        assert report.suggested_bump == "major"

    def test_suggested_silver_version_minor(self):
        report = ImpactReport(
            "sys", [Delta("sys", "T", PASSTHROUGH_CANDIDATE, ADDITIVE)], silver_version="1.2.0"
        )
        assert report.suggested_silver_version == "1.3.0"


# ---------------------------------------------------------------------------
# Loaders + integration against on-disk fixtures
# ---------------------------------------------------------------------------

_VOCAB = """\
@prefix bronze-sys: <https://acme.example/bronze/sys#> .
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

bronze-sys:tblOrder a kairos-bronze:SourceTable ;
    rdfs:label "tblOrder" ;
    kairos-bronze:tableName "tblOrder" ;
    kairos-bronze:primaryKeyColumns "OrderID" .

bronze-sys:tblOrder_OrderID a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze-sys:tblOrder ;
    kairos-bronze:columnName "OrderID" ;
    kairos-bronze:dataType "int" ;
    kairos-bronze:nullable "false"^^xsd:boolean .

bronze-sys:tblOrder_Total a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze-sys:tblOrder ;
    kairos-bronze:columnName "Total" ;
    kairos-bronze:dataType "decimal(18,2)" ;
    kairos-bronze:nullable "true"^^xsd:boolean .
"""

_MAPPING = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix bronze-sys: <https://acme.example/bronze/sys#> .
@prefix acme: <https://acme.example/ontology/sales#> .

bronze-sys:tblOrder skos:exactMatch acme:Order .
bronze-sys:tblOrder_Total skos:exactMatch acme:orderTotal .
"""


class TestLoaders:
    def test_load_source_tables(self, tmp_path):
        sources = tmp_path / "sources"
        sources.mkdir()
        (sources / "sys.vocabulary.ttl").write_text(_VOCAB, encoding="utf-8")
        tables = load_source_tables(sources, system="sys")
        assert set(tables) == {"tblOrder"}
        t = tables["tblOrder"]
        assert t.primary_key == ["OrderID"]
        assert {c.name for c in t.columns} == {"OrderID", "Total"}
        assert t.column("OrderID").nullable is False

    def test_load_mapping_targets(self, tmp_path):
        mappings = tmp_path / "mappings"
        mappings.mkdir()
        (mappings / "sys.ttl").write_text(_MAPPING, encoding="utf-8")
        targets = load_mapping_targets(mappings)
        assert targets["https://acme.example/bronze/sys#tblOrder"] == {"Order"}

    def test_load_approved_targets_and_contract(self, tmp_path):
        claims = tmp_path / "claims"
        claims.mkdir()
        registry = ClaimRegistry(
            domain="sales",
            contract=ContractMeta(silver_version="2.1.0", gold_version="1.0.0"),
            claims=[
                Claim(id="c1", type="class", status="approved",
                      class_uri="https://acme.example/ontology/sales#Order"),
                Claim(id="p1", type="property", status="approved",
                      property_uri="https://acme.example/ontology/sales#orderTotal"),
                Claim(id="c2", type="class", status="proposed",
                      class_uri="https://acme.example/ontology/sales#Draft"),
            ],
        )
        write_registry(registry, claims / "sales-claims.yaml")
        approved_classes, approved_props, contracts = load_approved_targets(claims)
        assert approved_classes == {"Order"}
        assert approved_props == {"orderTotal"}
        assert contracts["sales"].silver_version == "2.1.0"

    def test_run_source_delta_end_to_end(self, tmp_path):
        sources = tmp_path / "sources"
        sources.mkdir()
        (sources / "sys.vocabulary.ttl").write_text(_VOCAB, encoding="utf-8")
        mappings = tmp_path / "mappings"
        mappings.mkdir()
        (mappings / "sys.ttl").write_text(_MAPPING, encoding="utf-8")
        claims = tmp_path / "claims"
        claims.mkdir()
        write_registry(
            ClaimRegistry(
                domain="sales",
                contract=ContractMeta(silver_version="2.1.0"),
                claims=[
                    Claim(id="c1", type="class", status="approved",
                          class_uri="https://acme.example/ontology/sales#Order"),
                ],
            ),
            claims / "sales-claims.yaml",
        )
        report = run_source_delta("sys", sources, mappings, claims)
        # tblOrder maps to approved Order -> mapping-only table delta
        table_delta = next(d for d in report.deltas if d.column is None)
        assert table_delta.delta_type == MAPS_TO_EXISTING_CLASS
        assert report.silver_version == "2.1.0"


# ---------------------------------------------------------------------------
# Registry ContractMeta round-trip + merge preservation
# ---------------------------------------------------------------------------


class TestContractMeta:
    def test_empty_contract_not_serialized(self):
        reg = ClaimRegistry(domain="d")
        assert "contract" not in reg.to_dict()

    def test_contract_round_trip(self):
        reg = ClaimRegistry(
            domain="d", contract=ContractMeta(silver_version="1.0.0", gold_version="0.2.0")
        )
        loaded = ClaimRegistry.from_dict(reg.to_dict())
        assert loaded.contract.silver_version == "1.0.0"
        assert loaded.contract.gold_version == "0.2.0"

    def test_contract_yaml_round_trip(self, tmp_path):
        reg = ClaimRegistry(domain="d", contract=ContractMeta(silver_version="3.0.0"))
        path = tmp_path / "d-claims.yaml"
        write_registry(reg, path)
        assert "contract:" in path.read_text(encoding="utf-8")
        assert load_registry(path).contract.silver_version == "3.0.0"

    def test_merge_preserves_existing_contract(self):
        existing = ClaimRegistry(domain="d", contract=ContractMeta(silver_version="2.0.0"))
        new = ClaimRegistry(domain="d")  # regeneration carries no contract
        merged = merge_preserving_decisions(new, existing)
        assert merged.contract.silver_version == "2.0.0"

    def test_merge_new_contract_wins_when_set(self):
        existing = ClaimRegistry(domain="d", contract=ContractMeta(silver_version="2.0.0"))
        new = ClaimRegistry(domain="d", contract=ContractMeta(silver_version="2.1.0"))
        merged = merge_preserving_decisions(new, existing)
        assert merged.contract.silver_version == "2.1.0"

    def test_byte_stable_without_contract(self):
        reg = ClaimRegistry(domain="d", claims=[Claim(id="c1", type="class")])
        # dumping twice is identical and contains no contract key
        out = dump_registry(reg)
        assert "contract" not in out
        assert dump_registry(ClaimRegistry.from_dict(reg.to_dict())) == out
