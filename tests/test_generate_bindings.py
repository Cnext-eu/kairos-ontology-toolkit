# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""DD-191 binding generation from the design sheet.

Pins the kernel-verified rules: reuse-first target class from the sheet's
anchor URI; module-scoped property resolution (unresolvable → reported gap,
never a guess); object-property mappings routed to technicalFields, never
fields; duplicate property claims deduped by confidence; grain/identity
materialized with profile types; profile-proven quality only; contract
validation BEFORE writing; existing bindings never overwritten without force.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kairos_ontology.core import generate_bindings as gb
from kairos_ontology.core.compiler.bindings import load_entity_binding

CLASS_URI = "https://ref.test/ont/consignment#Consignment"

SHEET_ENTRY = {
    "system": "src", "table": "goods", "anchor": "Consignment",
    "anchor_uri": CLASS_URI, "domain": "consignment",
    "grain_columns": ["good_id"], "natural_key": ["good_id"],
    "status": "proposed", "schema_hash": "abc",
    "relationships": [
        {"to_table": "src.orders", "local_column": "order_id", "evidence": "fk-inclusion"}
    ],
    "secondary_entities": [
        {"class": "TradeParty", "grain_columns": ["customer_id"], "columns": ["customer_id"]}
    ],
    "flags": [],
}

ALIGNMENT_TABLE = {
    "system": "src", "table": "goods", "ref_class": "Consignment",
    "columns": [
        {"column": "descr", "data_type": "varchar(max)",
         "ref_property": "goodsDescription", "confidence": 0.9},
        {"column": "descr_alt", "data_type": "varchar(max)",
         "ref_property": "goodsDescription", "confidence": 0.4},   # duplicate claim
        {"column": "consignee", "data_type": "varchar(max)",
         "ref_property": "hasConsignee", "confidence": 0.8},       # object property
        {"column": "mystery", "data_type": "varchar(max)",
         "ref_property": "notInModule", "confidence": 0.7},        # unresolvable
        {"column": "plain", "data_type": "varchar(max)",
         "ref_property": "", "confidence": 0.0},                   # unmapped
    ],
    "custom_columns": [],
}

PROFILE = {
    "schema_version": 1, "system": "src", "basis": "import-extract(full)",
    "data_maturity": "production",
    "tables": {"goods": {"rows": 10, "table_tags": [], "columns": {
        "good_id": {"type": "int64", "null_ratio": 0.0, "distinct": 10,
                    "distinct_ratio": 1.0, "tags": ["unique", "id-like"]},
        "order_id": {"type": "int64", "null_ratio": 0.1, "distinct": 4,
                     "distinct_ratio": 0.44, "tags": ["id-like"]},
    }}},
}


def _pools(_catalog_path, class_uri):
    assert class_uri == CLASS_URI
    return (
        {"goodsDescription": "https://ref.test/ont/consignment#goodsDescription"},
        {"hasConsignee"},
    )


@pytest.fixture()
def hub(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(gb, "_class_pools", _pools)
    hub = tmp_path / "hub"
    analysis = hub / "integration" / "sources" / "_analysis"
    analysis.mkdir(parents=True)
    (hub / "catalog-v001.xml").write_text("<catalog/>", encoding="utf-8")
    (analysis / "table-anchors.yaml").write_text(
        yaml.safe_dump({"schema_version": 2, "tables": [SHEET_ENTRY]}),
        encoding="utf-8",
    )
    (analysis / "consignment-alignment.yaml").write_text(
        yaml.safe_dump({"domain": "consignment", "tables": [ALIGNMENT_TABLE]}),
        encoding="utf-8",
    )
    srcdir = hub / "integration" / "sources" / "src"
    srcdir.mkdir(parents=True)
    (srcdir / "src.profile.yaml").write_text(yaml.safe_dump(PROFILE), encoding="utf-8")
    return hub


def _run(hub, **kwargs):
    return gb.run_generate_bindings(hub, **kwargs)


class TestGeneration:
    def test_draft_is_written_and_loads_through_the_compiler_contract(self, hub):
        report = _run(hub)
        [g] = [g for g in report.generated if g.outcome == "written"]
        assert g.binding_name == "src-goods-to-consignment"
        text = g.path.read_text(encoding="utf-8")
        binding = load_entity_binding(text, path=str(g.path))
        assert binding.target_class == CLASS_URI, "reuse-first: reference IRI directly"

    def test_field_routing_rules(self, hub):
        report = _run(hub)
        doc = yaml.safe_load(report.generated[0].path.read_text(encoding="utf-8"))
        fields = {f["expression"]: f["property"] for f in doc["fields"]}
        # best-confidence column kept for the duplicated property
        assert fields == {"descr": "https://ref.test/ont/consignment#goodsDescription"}
        assert {"system": "src", "table": "goods", "property": "goodsDescription",
                "kept": "descr", "dropped": "descr_alt"} in report.duplicate_property_claims
        # unresolvable property reported, never guessed
        assert any(u["property"] == "notInModule" for u in report.unresolved_properties)
        technical = {t["name"]: t for t in doc["technicalFields"]}
        # object-property mapping → FK carrier, not a field
        assert technical["consignee"]["purpose"] == "relationship"
        # sheet relationship column → FK carrier with profile type/nullability
        assert technical["order_id"]["purpose"] == "relationship"
        assert technical["order_id"]["type"] == "int64"
        assert technical["order_id"]["nullable"] is True
        # grain column materialized for identity with profile type
        assert technical["good_id"]["purpose"] == "identity"
        assert technical["good_id"]["type"] == "int64"

    def test_profile_proven_quality_only(self, hub):
        report = _run(hub)
        doc = yaml.safe_load(report.generated[0].path.read_text(encoding="utf-8"))
        kinds = {q["kind"] for q in doc["quality"]}
        assert kinds == {"not-null", "unique"}, "grain measured non-null and unique"

    def test_secondary_entities_become_worklist_not_bindings(self, hub):
        report = _run(hub)
        assert report.secondary_entity_worklist == [
            {"system": "src", "table": "goods", "class": "TradeParty",
             "grain_columns": ["customer_id"], "columns": ["customer_id"]}
        ]
        assert len([g for g in report.generated if g.outcome == "written"]) == 1


class TestGuards:
    def test_existing_binding_is_never_overwritten_without_force(self, hub):
        first = _run(hub)
        path = first.generated[0].path
        path.write_text("# hand-edited\n" + path.read_text(encoding="utf-8"),
                        encoding="utf-8")
        second = _run(hub)
        assert second.generated[0].outcome == "exists"
        assert path.read_text(encoding="utf-8").startswith("# hand-edited")
        forced = _run(hub, force=True)
        assert forced.generated[0].outcome == "written"
        assert not path.read_text(encoding="utf-8").startswith("# hand-edited")

    def test_dry_run_validates_but_writes_nothing(self, hub):
        report = _run(hub, dry_run=True)
        assert report.generated[0].outcome == "would-write"
        assert not report.generated[0].path.exists()

    def test_rejected_sheet_rows_are_not_generated(self, hub):
        analysis = hub / "integration" / "sources" / "_analysis"
        doc = yaml.safe_load((analysis / "table-anchors.yaml").read_text("utf-8"))
        doc["tables"][0]["status"] = "rejected"
        (analysis / "table-anchors.yaml").write_text(yaml.safe_dump(doc), "utf-8")
        report = _run(hub)
        assert report.generated == []

    def test_missing_alignment_is_a_reported_skip(self, hub):
        analysis = hub / "integration" / "sources" / "_analysis"
        (analysis / "consignment-alignment.yaml").unlink()
        report = _run(hub)
        assert report.generated[0].outcome == "skipped"
        assert "propose-alignment" in report.generated[0].note

    def test_empty_grain_is_skipped_not_reported_invalid(self, hub):
        """#565: an empty grain is a property of the row (nothing to identify a
        record by), not a defect in the draft -- must never reach the validator
        and come back as 'invalid'."""
        analysis = hub / "integration" / "sources" / "_analysis"
        doc = yaml.safe_load((analysis / "table-anchors.yaml").read_text("utf-8"))
        doc["tables"][0]["grain_columns"] = []      # would violate the closed contract
        doc["tables"][0]["natural_key"] = []
        (analysis / "table-anchors.yaml").write_text(yaml.safe_dump(doc), "utf-8")
        report = _run(hub)
        assert report.generated[0].outcome == "skipped"
        assert "no grain identified" in report.generated[0].note

    def test_zero_scalar_fields_with_fk_carrier_is_skipped(self, hub):
        """#565: this generator never emits relationships:, so a table with zero
        scalar field mappings is unconditionally unwritable -- must be skipped,
        never sent to the validator to fail with a generic schema error. An FK
        carrier's presence only changes the reason text, never the outcome."""
        analysis = hub / "integration" / "sources" / "_analysis"
        alignment_path = analysis / "consignment-alignment.yaml"
        doc = yaml.safe_load(alignment_path.read_text("utf-8"))
        for table_dict in doc.get("tables", []):
            table_dict["columns"] = []
        alignment_path.write_text(yaml.safe_dump(doc), "utf-8")
        report = _run(hub)
        assert report.generated[0].outcome == "skipped"
        assert "no scalar fields mapped" in report.generated[0].note
        assert "deferred to propose-relationships" in report.generated[0].note

    def test_zero_scalar_fields_with_no_fk_carrier_at_all_is_skipped(self, hub):
        """Same outcome with no FK carrier evidence anywhere -- just a plainer
        reason, since there's no relationship wiring to defer to begin with."""
        analysis = hub / "integration" / "sources" / "_analysis"
        alignment_path = analysis / "consignment-alignment.yaml"
        align_doc = yaml.safe_load(alignment_path.read_text("utf-8"))
        for table_dict in align_doc.get("tables", []):
            table_dict["columns"] = []
        alignment_path.write_text(yaml.safe_dump(align_doc), "utf-8")

        anchors_path = analysis / "table-anchors.yaml"
        anchors_doc = yaml.safe_load(anchors_path.read_text("utf-8"))
        anchors_doc["tables"][0]["relationships"] = []
        anchors_path.write_text(yaml.safe_dump(anchors_doc), "utf-8")

        report = _run(hub)
        assert report.generated[0].outcome == "skipped"
        assert report.generated[0].note == "no scalar fields mapped for this table"
        assert not (hub / "integration" / "bindings").exists()

    def test_missing_sheet_is_a_hard_error_naming_the_fix(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="anchor-tables"):
            _run(tmp_path / "hub")


# ---------------------------------------------------------------------------
# A column aligned to another class is a decision, not a missing property (#887)
# ---------------------------------------------------------------------------


ANCHOR = "https://ref.example.com/ont/cargo#CargoItem"


def _sheet_entry():
    return {
        "system": "src",
        "table": "cargo",
        "anchor_uri": ANCHOR,
        "domain": "roro",
        "grain_columns": ["REFXX"],
        "natural_key": ["REFXX"],
    }


def _alignment(columns):
    return {"system": "src", "table": "cargo", "ref_class": "CargoItem", "columns": columns}


def _column(name, prop, ref_class):
    return {"column": name, "ref_property": prop, "ref_class": ref_class,
            "data_type": "varchar(50)", "confidence": 0.9}


class TestColumnsAlignedToAnotherClass:
    """The measured case: a 155-column cargo table where the aligner put 18 columns on
    Weight, Dimension, HandlingInstructions and ShippingMarks. Binding those onto the
    anchor would be a grain error dressed as coverage; counting them as 'property does
    not resolve' hid a modelling decision behind a lookup failure."""

    def _run(self, columns, monkeypatch):
        from kairos_ontology.core import generate_bindings as module

        monkeypatch.setattr(
            module, "_class_pools",
            lambda *_a, **_k: ({"cargoDescription": f"{ANCHOR[:-9]}#cargoDescription"}, set()),
        )
        monkeypatch.setattr(module, "hub_local_properties", lambda *_a, **_k: {})
        report = module.GenerateBindingsReport()
        doc, reason = module.generate_binding_doc(
            _sheet_entry(), _alignment(columns), catalog_path=Path("unused"),
            profile=None, report=report,
        )
        return doc, reason, report

    def test_it_lands_on_the_secondary_worklist_not_the_unresolved_list(self, monkeypatch):
        columns = [
            _column("GOODDESCRIPTION", "cargoDescription", "CargoItem"),
            _column("GROSSWEIGHT", "weightValue", "Weight"),
        ]

        _doc, _reason, report = self._run(columns, monkeypatch)

        assert [i["class"] for i in report.secondary_entity_worklist] == ["Weight"]
        assert report.unresolved_properties == []

    def test_the_note_names_the_decision_to_make(self, monkeypatch):
        columns = [
            _column("GOODDESCRIPTION", "cargoDescription", "CargoItem"),
            _column("GROSSWEIGHT", "weightValue", "Weight"),
        ]

        _doc, _reason, report = self._run(columns, monkeypatch)
        note = report.secondary_entity_worklist[0]["note"]

        assert "secondary entity at its own grain" in note
        assert "hub-local property on the anchor" in note

    def test_it_is_not_bound_onto_the_anchor(self, monkeypatch):
        """Putting a weight value on a cargo-item row is a grain error, not coverage."""
        columns = [
            _column("GOODDESCRIPTION", "cargoDescription", "CargoItem"),
            _column("GROSSWEIGHT", "weightValue", "Weight"),
        ]

        doc, _reason, _report = self._run(columns, monkeypatch)

        assert [f["expression"] for f in doc["fields"]] == ["GOODDESCRIPTION"]

    def test_a_genuinely_missing_property_is_still_unresolved(self, monkeypatch):
        """Same anchor class, property nothing has — a lookup failure, not a decision."""
        columns = [
            _column("GOODDESCRIPTION", "cargoDescription", "CargoItem"),
            _column("MYSTERY", "noSuchProperty", "CargoItem"),
        ]

        _doc, _reason, report = self._run(columns, monkeypatch)

        assert report.secondary_entity_worklist == []
        assert [i["property"] for i in report.unresolved_properties] == ["noSuchProperty"]

    def test_a_column_with_no_recorded_class_is_still_unresolved(self, monkeypatch):
        columns = [
            _column("GOODDESCRIPTION", "cargoDescription", "CargoItem"),
            _column("MYSTERY", "noSuchProperty", ""),
        ]

        _doc, _reason, report = self._run(columns, monkeypatch)

        assert report.secondary_entity_worklist == []
        assert len(report.unresolved_properties) == 1


# ---------------------------------------------------------------------------
# hub_local_properties against a real ontology, not a mock (#887)
# ---------------------------------------------------------------------------


REF_CLASS = "https://ref.example.com/ont/cargo#CargoItem"

REF_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix : <https://ref.example.com/ont/cargo#> .

<https://ref.example.com/ont/cargo> a owl:Ontology .

:CargoItem a owl:Class ;
    rdfs:label "Cargo Item"@en ;
    rdfs:comment "A unit of cargo."@en .

:cargoDescription a owl:DatatypeProperty ;
    rdfs:label "Cargo description"@en ;
    rdfs:comment "Free text."@en ;
    rdfs:domain :CargoItem ;
    rdfs:range xsd:string .
"""

DOMAIN_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix : <https://acme.com/ont/roro#> .

<https://acme.com/ont/roro> a owl:Ontology ;
    owl:imports <https://ref.example.com/ont/cargo> .

:billOfLadingNumber a owl:DatatypeProperty ;
    rdfs:label "Bill of lading number"@en ;
    rdfs:comment "The B/L reference."@en ;
    rdfs:domain <https://ref.example.com/ont/cargo#CargoItem> ;
    rdfs:range xsd:string .

:carrierOfRecord a owl:ObjectProperty ;
    rdfs:label "Carrier of record"@en ;
    rdfs:comment "Who carries it."@en ;
    rdfs:domain <https://ref.example.com/ont/cargo#CargoItem> ;
    rdfs:range <https://ref.example.com/ont/cargo#CargoItem> .
"""

MASTER_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .

<https://acme.com/ont/master> a owl:Ontology ;
    owl:imports <https://acme.com/ont/roro> .
"""

CATALOG = """\
<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <uri name="https://acme.com/ont/roro" uri="model/ontologies/roro.ttl"/>
  <uri name="https://ref.example.com/ont/cargo" uri="model/ontologies/ref-cargo.ttl"/>
</catalog>
"""


def _hub(tmp_path):
    ontologies = tmp_path / "model" / "ontologies"
    ontologies.mkdir(parents=True)
    (ontologies / "_master.ttl").write_text(MASTER_TTL, encoding="utf-8")
    (ontologies / "roro.ttl").write_text(DOMAIN_TTL, encoding="utf-8")
    (ontologies / "ref-cargo.ttl").write_text(REF_TTL, encoding="utf-8")
    (tmp_path / "catalog-v001.xml").write_text(CATALOG, encoding="utf-8")
    return tmp_path


class TestHubLocalPropertiesAgainstARealOntology:
    """Exercised, not mocked.

    Every other test of the binding generator mocks this function, which is precisely
    how a regression got through: the switch to the DD-103 canonical loader read the
    property URI under the wrong key, so the pool came back empty however correctly the
    hub had authored its properties, and the mocks never noticed.
    """

    def test_a_hub_property_declared_on_a_reference_class_is_found(self, tmp_path):
        from kairos_ontology.core.generate_bindings import hub_local_properties

        found = hub_local_properties(_hub(tmp_path), REF_CLASS)

        assert "billOfLadingNumber" in found
        assert found["billOfLadingNumber"] == "https://acme.com/ont/roro#billOfLadingNumber"

    def test_the_reference_models_own_properties_are_not_returned(self, tmp_path):
        """_class_pools already supplies those; this adds only what the hub authored."""
        from kairos_ontology.core.generate_bindings import hub_local_properties

        assert "cargoDescription" not in hub_local_properties(_hub(tmp_path), REF_CLASS)

    def test_an_object_property_is_not_offered_as_a_scalar_field(self, tmp_path):
        from kairos_ontology.core.generate_bindings import hub_local_properties

        assert "carrierOfRecord" not in hub_local_properties(_hub(tmp_path), REF_CLASS)

    def test_a_hub_with_no_master_yields_nothing_rather_than_failing(self, tmp_path):
        from kairos_ontology.core.generate_bindings import hub_local_properties

        assert hub_local_properties(tmp_path, REF_CLASS) == {}

    def test_no_hub_root_is_not_an_error(self):
        from kairos_ontology.core.generate_bindings import hub_local_properties

        assert hub_local_properties(None, REF_CLASS) == {}


# ---------------------------------------------------------------------------
# An identity column's type comes from the source vocabulary (#914)
# ---------------------------------------------------------------------------


VOCAB_TTL = """\
@prefix kairos-bronze: <https://kairos.example/bronze#> .
@prefix src: <https://acme.example/src#> .

src:orders_ORDER_ID a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "ORDER_ID" ;
    kairos-bronze:dataType "string" ;
    kairos-bronze:sourceTable src:orders .

src:orders_ttSysStartTime a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "ttSysStartTime" ;
    kairos-bronze:dataType "timestamp" ;
    kairos-bronze:sourceTable src:orders .

src:shipments_QTY a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "QTY" ;
    kairos-bronze:dataType "decimal(10,2)" ;
    kairos-bronze:sourceTable src:shipments .
"""


class TestSourceColumnTypes:
    """`technicalFields.type` is checked by the compiler against the source column's
    physical type. The alignment only carries a type for columns it *mapped*, and an
    identity column is very often one it did not -- an audit or system-versioning column
    is excluded from alignment by construction. Falling through to `_canonical_type("")`
    yields "string", so generate-bindings emitted bindings its own compiler rejected:

        [error] technical-field.type-incompatible: technical field 'ttSysStartTime'
        declares type 'string' but source column has incompatible physical type 'timestamp'
    """

    @staticmethod
    def _sources(tmp_path):
        system = tmp_path / "src"
        system.mkdir(parents=True)
        (system / "src.vocabulary.ttl").write_text(VOCAB_TTL, encoding="utf-8")
        return tmp_path

    def test_types_are_read_per_table(self, tmp_path):
        from kairos_ontology.core.generate_bindings import load_source_column_types

        types = load_source_column_types(self._sources(tmp_path), "src")

        assert types["orders"] == {"ORDER_ID": "string", "ttSysStartTime": "timestamp"}
        assert types["shipments"] == {"QTY": "decimal(10,2)"}

    def test_a_system_versioning_column_is_typed_timestamp_not_string(self, tmp_path):
        """The exact column that failed the compile on a real hub."""
        from kairos_ontology.core.generate_bindings import load_source_column_types

        types = load_source_column_types(self._sources(tmp_path), "src")

        assert types["orders"]["ttSysStartTime"] == "timestamp"

    def test_a_missing_vocabulary_yields_nothing_rather_than_failing(self, tmp_path):
        """A hub mid-import should lose a type hint, not the whole generation run."""
        from kairos_ontology.core.generate_bindings import load_source_column_types

        assert load_source_column_types(tmp_path, "nosuchsystem") == {}

    def test_an_unreadable_vocabulary_yields_nothing(self, tmp_path):
        from kairos_ontology.core.generate_bindings import load_source_column_types

        system = tmp_path / "src"
        system.mkdir(parents=True)
        (system / "src.vocabulary.ttl").write_bytes(b"\xff\xfe not utf-8 \xff")

        assert load_source_column_types(tmp_path, "src") == {}

    def test_a_column_with_no_declared_type_is_skipped(self, tmp_path):
        from kairos_ontology.core.generate_bindings import load_source_column_types

        system = tmp_path / "src"
        system.mkdir(parents=True)
        (system / "src.vocabulary.ttl").write_text(
            '@prefix kairos-bronze: <https://kairos.example/bronze#> .\n'
            '@prefix src: <https://acme.example/src#> .\n\n'
            'src:orders_X a kairos-bronze:SourceColumn ;\n'
            '    kairos-bronze:columnName "X" ;\n'
            '    kairos-bronze:sourceTable src:orders .\n',
            encoding="utf-8",
        )

        assert load_source_column_types(tmp_path, "src") == {}
