# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Business validation document: facts, narrative check, layout, SVG and Word (DD-254)."""

from __future__ import annotations

import io
import json
import shutil
import struct
import zipfile
import zlib
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.projections.business_doc import (
    BusinessDocError,
    build_facts,
    business_type,
    cardinality_code,
    facts_json,
    validate_narrative,
)
from kairos_ontology.core.projections.business_doc.diagram_svg import end_marks, render_svg
from kairos_ontology.core.projections.business_doc.layout import (
    LinkSpec,
    NodeSpec,
    label_size,
    layout_figure,
    overlaps,
)

_V5_HUB = Path(__file__).parent / "scenarios" / "v5-hub"
_PREFIXES = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix kext: <https://kairos.cnext.eu/ext#> .
@prefix ship: <https://example.test/ontology/shipment#> .
@prefix party: <https://example.test/ontology/party#> .
@prefix ref: <https://example.test/ontology/refdata#> .
"""
_SHIPMENT = (
    _PREFIXES
    + """
<https://example.test/ontology/shipment> a owl:Ontology ;
    owl:versionInfo "0.3.0" ;
    owl:imports <https://example.test/ontology/party>, <https://example.test/ontology/refdata> .

ship:Shipment a owl:Class ; rdfs:label "Shipment" ;
    rdfs:comment "Goods moved for one customer." ;
    rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ship:hasLeg ; owl:minCardinality 1 ] .
ship:Leg a owl:Class ; rdfs:label "Transport leg" .

ship:shipmentNumber a owl:DatatypeProperty, owl:FunctionalProperty ;
    rdfs:domain ship:Shipment ; rdfs:range xsd:string ; rdfs:label "Shipment number" .
ship:grossWeight a owl:DatatypeProperty ;
    rdfs:domain ship:Shipment ; rdfs:range xsd:decimal ; rdfs:label "Gross weight" .
ship:oldReference a owl:DatatypeProperty ; owl:deprecated true ;
    rdfs:domain ship:Shipment ; rdfs:range xsd:string ; rdfs:label "Old reference" .
ship:transportMode a owl:ObjectProperty, owl:FunctionalProperty ;
    rdfs:domain ship:Shipment ; rdfs:range ref:TransportModeCode ; rdfs:label "Transport mode" .
ship:hasLeg a owl:ObjectProperty ; owl:inverseOf ship:legOf ;
    rdfs:domain ship:Shipment ; rdfs:range ship:Leg ; rdfs:label "has leg" .
ship:legOf a owl:ObjectProperty, owl:FunctionalProperty ;
    rdfs:domain ship:Leg ; rdfs:range ship:Shipment ; rdfs:label "is leg of" .
ship:customer a owl:ObjectProperty, owl:FunctionalProperty ;
    rdfs:domain ship:Shipment ; rdfs:range party:Customer ; rdfs:label "is shipped for" .
ship:departure a owl:DatatypeProperty ;
    rdfs:domain ship:Leg ; rdfs:range xsd:dateTime ; rdfs:label "Departure" .
"""
)
_PARTY = (
    _PREFIXES
    + """
<https://example.test/ontology/party> a owl:Ontology .
party:Customer a owl:Class ; rdfs:label "Customer" .
"""
)
_REFDATA = (
    _PREFIXES
    + """
<https://example.test/ontology/refdata> a owl:Ontology .
ref:TransportModeCode a owl:Class ; rdfs:label "Transport mode code" ;
    kext:isReferenceData true .
"""
)
_CATALOG = """<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <uri name="https://example.test/ontology/party" uri="party.ttl"/>
  <uri name="https://example.test/ontology/refdata" uri="refdata.ttl"/>
</catalog>
"""


@pytest.fixture
def shipment_hub(tmp_path: Path) -> Path:
    hub = tmp_path / "ontology-hub"
    ontologies = hub / "model" / "ontologies"
    ontologies.mkdir(parents=True)
    (ontologies / "shipment.ttl").write_text(_SHIPMENT, encoding="utf-8")
    (ontologies / "party.ttl").write_text(_PARTY, encoding="utf-8")
    (ontologies / "refdata.ttl").write_text(_REFDATA, encoding="utf-8")
    (ontologies / "catalog-v001.xml").write_text(_CATALOG, encoding="utf-8")
    (hub / "kairos.yaml").write_text("name: example-hub\n", encoding="utf-8")
    return hub


@pytest.fixture
def v5_hub(tmp_path: Path) -> Path:
    hub = tmp_path / "ontology-hub"
    shutil.copytree(_V5_HUB, hub)
    (hub / "kairos.yaml").write_text(
        "name: v5-customer-hub\nadapter: fabric-warehouse\n", encoding="utf-8"
    )
    return hub


def _narrative() -> dict:
    return {
        "document": {"version": 2, "date": "2026-10-01", "previous_version": 1},
        "what_changed": ["The transport leg is now its own entity."],
        "glossary": [
            {"term": "Shipment", "meaning": "Goods moved for one customer.", "owned_by": "Shipment"}
        ],
        "domain_view": {
            "rows": {"party": "A shipment is shipped for one customer."},
            "why": ["A customer is mastered by the party domain."],
        },
        "figures": [
            {
                "id": "3.1",
                "title": "Shipment and its legs",
                "entities": ["ship:Shipment", "ship:Leg", "party:Customer"],
                "gaps": [{"id": "G1", "near": "ship:Shipment"}],
            },
        ],
        "relationships": {
            "R1": {
                "one": "Each shipment is shipped for zero or one customer.",
                "other": "Each customer has zero or more shipments.",
            },
            "R2": {
                "one": "Each shipment has one or more transport legs.",
                "other": "Each transport leg is part of zero or one shipment.",
            },
        },
        "entities": {
            "ship:Shipment": {
                "heading": "Shipment (the consignment)",
                "definition": "Goods moved for **one** customer.",
                "why": ["A shipment has at least one leg."],
                "field_groups": [
                    {
                        "title": "Classification",
                        "properties": ["ship:shipmentNumber", "ship:transportMode"],
                    },
                    {"title": "Quantities", "properties": ["ship:grossWeight"]},
                ],
                "field_meanings": {"ship:grossWeight": "Total weight in kilograms."},
                "held_references": {"ship:shipmentNumber": "The carrier's booking."},
            },
            "https://example.test/ontology/shipment#Leg": {
                "definition": "One movement of the goods.",
                "omitted": [{"property": "ship:departure", "reason": "Shown in v3."}],
            },
        },
        "gaps": [{"id": "G1", "concept": "Means of transport", "today": "Not held."}],
        "decisions": [{"id": "D1", "question": "Is a leg ever shared?", "current": "No."}],
        "review_remarks": [{"id": 1, "remark": "Define leg.", "answer": "See section 1."}],
    }


def _png() -> bytes:
    """A valid 1x1 white PNG, so Word tests need no browser."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
        + chunk(b"IEND", b"")
    )


# --------------------------------------------------------------------------------------
# Pure mappings.
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("bounds", "code"),
    [
        ((None, None), "0n"),
        ((0, None), "0n"),
        ((1, None), "1n"),
        ((None, 1), "01"),
        ((0, 1), "01"),
        ((1, 1), "1"),
        ((2, 5), "1n"),
    ],
)
def test_owl_bounds_map_to_line_end_codes(bounds, code):
    assert cardinality_code(*bounds) == code


@pytest.mark.parametrize(
    ("contract_type", "range_uri", "expected"),
    [
        ("string(64)", None, "Text"),
        ("int64", None, "Whole number"),
        ("decimal(18,3)", None, "Decimal"),
        ("timestamp", None, "Date and time (UTC)"),
        ("date", None, "Date"),
        (None, "http://www.w3.org/2001/XMLSchema#boolean", "Yes/No"),
        (None, "http://www.w3.org/2001/XMLSchema#dateTime", "Date and time (UTC)"),
        (None, "https://example.test/Other", "Text"),
    ],
)
def test_business_types_are_readable(contract_type, range_uri, expected):
    assert business_type(contract_type, range_uri) == expected


# --------------------------------------------------------------------------------------
# Facts.
# --------------------------------------------------------------------------------------
def test_facts_read_the_closure(shipment_hub):
    facts = build_facts(shipment_hub, "shipment")

    assert facts["schema_version"] == 1
    assert facts["model_version"] == "0.3.0"
    assert [e["iri"] for e in facts["entities"]] == ["ship:Shipment", "ship:Leg"]
    shipment = facts["entities"][0]
    fields = {f["property"]: f for f in shipment["fields"]}
    assert fields["ship:oldReference"]["deprecated"] is True
    assert fields["ship:transportMode"]["code_list"] == {
        "iri": "ref:TransportModeCode",
        "label": "Transport mode code",
    }
    assert fields["ship:grossWeight"]["datatype"] == "Decimal"
    assert shipment["identification"]["technical_id"]["column"] == "shipment_sk"

    rels = {r["property"]: r for r in facts["relationships"]}
    # The hasLeg/legOf inverse pair is one relationship, kept in its IRI-first direction.
    assert set(rels) == {"ship:customer", "ship:hasLeg"}
    assert rels["ship:hasLeg"]["inverse"] == "ship:legOf"
    assert (rels["ship:hasLeg"]["from_card"], rels["ship:hasLeg"]["to_card"]) == ("01", "1n")
    assert (rels["ship:customer"]["from_card"], rels["ship:customer"]["to_card"]) == ("0n", "01")
    assert [r["id"] for r in facts["relationships"]] == ["R1", "R2"]

    assert facts["externals"] == [
        {
            "iri": "party:Customer",
            "uri": "https://example.test/ontology/party#Customer",
            "label": "Customer",
            "domain": "party",
        }
    ]
    assert facts["neighbour_domains"] == [
        {"domain": "party", "master_of": ["Customer"], "relationships": ["R1"]}
    ]
    assert [c["iri"] for c in facts["code_lists"]] == ["ref:TransportModeCode"]


def test_facts_are_byte_identical_and_hashed(shipment_hub):
    first = facts_json(build_facts(shipment_hub, "shipment"))
    second = facts_json(build_facts(shipment_hub, "shipment"))
    assert first == second
    assert len(json.loads(first)["facts_hash"]) == 64


def test_facts_carry_bindings_contract_and_silver_mismatch(v5_hub):
    facts = build_facts(v5_hub, "party")

    customer = next(e for e in facts["entities"] if e["iri"] == "party:Customer")
    assert customer["sources"] == ["crm"]
    assert customer["bindings"] == ["crm-customer"]
    assert customer["identification"]["business_key"]["columns"] == ["customer_id"]
    assert all(f["in_silver"] for f in customer["fields"])
    rel = facts["relationships"][0]
    assert rel["silver_cardinality"] == "many-to-one"
    assert any("R1" in w and "functional" in w for w in facts["warnings"])


def test_an_unknown_entity_or_domain_is_refused(shipment_hub):
    with pytest.raises(BusinessDocError, match="not a class"):
        build_facts(shipment_hub, "shipment", entities=["ship:Nothing"])
    with pytest.raises(BusinessDocError, match="no domain ontology"):
        build_facts(shipment_hub, "billing")


def test_entities_can_be_chosen(shipment_hub):
    facts = build_facts(shipment_hub, "shipment", entities=["ship:Leg"])
    assert [e["iri"] for e in facts["entities"]] == ["ship:Leg"]
    # Shipment is now outside the core set: an external end of the legOf relationship.
    assert [e["iri"] for e in facts["externals"]] == ["ship:Shipment"]
    assert facts["neighbour_domains"] == []


# --------------------------------------------------------------------------------------
# Narrative validation.
# --------------------------------------------------------------------------------------
def test_a_complete_narrative_validates(shipment_hub):
    assert validate_narrative(build_facts(shipment_hub, "shipment"), _narrative()) == []


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda n: n["relationships"].update({"R9": {"one": "x", "other": "y"}}),
            "R9: no such relationship",
        ),
        (lambda n: n["relationships"].pop("R2"), "R2: needs both"),
        (lambda n: n["figures"][0]["entities"].remove("ship:Leg"), "ship:Leg is in no figure"),
        (lambda n: n["figures"][0]["entities"].append("ship:Ghost"), "not an entity"),
        (
            lambda n: n["entities"]["ship:Shipment"]["field_groups"].pop(1),
            "ship:grossWeight is in no field group",
        ),
        (
            lambda n: n["entities"]["ship:Shipment"]["field_groups"][1]["properties"].append(
                "ship:oldReference"
            ),
            "deprecated",
        ),
        (
            lambda n: n["entities"]["https://example.test/ontology/shipment#Leg"]["omitted"][
                0
            ].update({"reason": ""}),
            "has no reason",
        ),
        (lambda n: n["entities"].pop("ship:Shipment"), "entities.ship:Shipment: missing"),
        (lambda n: n["entities"]["ship:Shipment"].pop("definition"), "definition: missing"),
        (lambda n: n["document"].update({"date": "1 October"}), "not an ISO date"),
        (lambda n: n["gaps"].append({"id": "G1"}), "used twice"),
        (lambda n: n["domain_view"]["rows"].update({"billing": "x"}), "not a neighbour"),
    ],
)
def test_a_narrative_that_adds_or_drops_a_fact_fails_closed(shipment_hub, mutate, message):
    narrative = _narrative()
    mutate(narrative)
    errors = validate_narrative(build_facts(shipment_hub, "shipment"), narrative)
    assert any(message in error for error in errors), errors


def test_an_omitted_relationship_needs_no_figure(shipment_hub):
    narrative = _narrative()
    narrative["figures"][0]["entities"].remove("party:Customer")
    narrative["relationships"].pop("R1")
    narrative["omitted"] = [{"item": "R1", "reason": "Reviewed with the party domain."}]
    assert validate_narrative(build_facts(shipment_hub, "shipment"), narrative) == []


# --------------------------------------------------------------------------------------
# Layout and SVG.
# --------------------------------------------------------------------------------------
def _dense_figure():
    nodes = [
        NodeSpec("core:A", "Shipment"),
        NodeSpec("core:B", "Transport leg"),
        NodeSpec("core:C", "Booking"),
    ]
    nodes += [
        NodeSpec(f"ext:{i}", f"External {i}", "party domain", (), "external") for i in range(6)
    ]
    links = [
        LinkSpec("R1", "core:A", "core:B", "01", "1n", "R1 has leg"),
        LinkSpec("R2", "core:A", "core:C", "0n", "01", "R2 is booked as"),
        LinkSpec("R3", "ext:0", "ext:2", "0n", "1", "R3 sits in"),
    ]
    links += [
        LinkSpec(
            f"R{4 + i}",
            "core:A" if i % 2 else "core:B",
            f"ext:{i}",
            "0n",
            "01",
            f"R{4 + i} role {i}",
        )
        for i in range(6)
    ]
    links.append(LinkSpec("R10", "ext:0", "ext:1", "0n", "0n", "R10 across"))
    return nodes, links


def test_layout_has_no_overlapping_boxes_or_labels_and_is_stable():
    nodes, links = _dense_figure()
    figure = layout_figure(nodes, links)
    assert figure == layout_figure(nodes, links)

    boxes = [(b.x, b.y, b.w, b.h) for b in figure.boxes]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            assert not overlaps(a, b)
    labels = [e.label_box for e in figure.edges if e.label_box]
    assert len(labels) == len(links)
    for i, a in enumerate(labels):
        assert not any(overlaps(a, box) for box in boxes)
        for b in labels[i + 1 :]:
            assert not overlaps(a, b)
    for x, y, w, h in labels:  # inside the figure
        assert x >= 0 and y >= 0 and x + w <= figure.width and y + h <= figure.height
    # No label sits on a line, and no two line ends on one box side touch.
    segments = [
        (min(p[0], q[0]), min(p[1], q[1]), abs(q[0] - p[0]) + 0.1, abs(q[1] - p[1]) + 0.1)
        for e in figure.edges
        for p, q in zip(e.points, e.points[1:])
    ]
    for label in labels:
        assert not any(overlaps(label, segment) for segment in segments)
    ends = sorted((e.points[i][0], e.points[i][1]) for e in figure.edges for i in (0, -1))
    for (x1, y1), (x2, y2) in zip(ends, ends[1:]):
        assert x1 != x2 or abs(y2 - y1) >= 20.0
    # Every vertical run has its own lane.
    lanes = [
        p[0]
        for e in figure.edges
        for p, q in zip(e.points, e.points[1:])
        if p[0] == q[0] and p[1] != q[1]
    ]
    assert len(lanes) == len(set(lanes))
    assert render_svg(figure) == render_svg(layout_figure(nodes, links))


def test_label_size_grows_with_text():
    assert label_size("a much longer role label")[0] > label_size("short")[0]


@pytest.mark.parametrize(
    ("card", "circles", "lines"),
    [("1", 0, 2), ("01", 1, 1), ("1n", 0, 4), ("0n", 1, 3)],
)
def test_line_end_glyphs(card, circles, lines):
    marks = end_marks((0.0, 0.0), (100.0, 0.0), card)
    assert sum(1 for kind, _ in marks if kind == "circle") == circles
    assert sum(1 for kind, _ in marks if kind == "line") == lines


def test_card_a_is_drawn_at_a_end():
    figure = layout_figure(
        [NodeSpec("a", "A"), NodeSpec("b", "B", kind="external")],
        [LinkSpec("R1", "a", "b", "0n", "1", "R1")],
        legend=False,
    )
    edge = figure.edges[0]
    a_box = next(b for b in figure.boxes if b.key == "a")
    start = edge.points[0]
    assert start[0] in (a_box.x, a_box.right)
    # The zero-or-more circle is next to A, so A's end carries card_a.
    circle = next(g for kind, g in end_marks(start, edge.points[1], "0n") if kind == "circle")
    assert abs(circle[0] - start[0]) == pytest.approx(24.0)


# --------------------------------------------------------------------------------------
# Word.
# --------------------------------------------------------------------------------------
def test_docx_structure_and_determinism(shipment_hub):
    docx = pytest.importorskip("docx")
    from kairos_ontology.core.projections.business_doc.render_docx import render_document

    facts = build_facts(shipment_hub, "shipment")
    first = render_document(facts, _narrative(), rasterize=lambda svg, w, h: _png())
    second = render_document(facts, _narrative(), rasterize=lambda svg, w, h: _png())

    def body(blob: bytes) -> bytes:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            return archive.read("word/document.xml") + archive.read("docProps/core.xml")

    assert body(first.docx) == body(second.docx)
    assert first.warnings == []
    assert sorted(first.svgs) == [
        "shipment-validation-v2-figure-1.svg",
        "shipment-validation-v2-figure-3.1.svg",
    ]

    document = docx.Document(io.BytesIO(first.docx))
    headings = [p.text for p in document.paragraphs if p.style.name.startswith("Heading")]
    for expected in (
        "1 Terms used in this document",
        "2 The shipment domain and its neighbours",
        "3 Logical data model",
        "Figure 3.1: Shipment and its legs",
        "Relationships in Figure 3.1",
        "4 Shipment (the consignment)",
        "5 Transport leg",
        "6 Gaps and open decisions",
        "7 Confirmation",
        "Appendix A Review remarks and answers",
        "Identification",
    ):
        assert expected in headings, headings
    headers = {tuple(c.text for c in t.rows[0].cells) for t in document.tables}
    assert (
        "Field",
        "Meaning",
        "Data type & format",
        "Code list",
        "Yes",
        "No",
        "Comment",
    ) in headers
    assert (
        "#",
        "Read in one direction",
        "Read in the other direction",
        "Yes",
        "No",
        "Comment",
    ) in headers
    assert len(document.inline_shapes) == 2
    assert document.core_properties.created.date().isoformat() == "2026-10-01"
    text = "\n".join(c.text for t in document.tables for r in t.rows for c in r.cells)
    assert "Old reference" not in text  # deprecated fields are left out
    assert "Transport mode code" in text
    assert "Total weight in kilograms." in text


def test_docx_without_a_browser_keeps_the_svg_and_warns(shipment_hub):
    pytest.importorskip("docx")
    from kairos_ontology.core.projections.business_doc.render_docx import render_document

    result = render_document(build_facts(shipment_hub, "shipment"), _narrative(), rasterize=None)
    assert len(result.warnings) == 2
    assert all("see shipment-validation-v2-figure-" in w for w in result.warnings)


def test_a_missing_extra_names_the_install_command(shipment_hub, monkeypatch):
    import builtins

    from kairos_ontology.core.projections.business_doc.render_docx import render_document

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "docx" or name.startswith("docx."):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    facts = build_facts(shipment_hub, "shipment")
    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(BusinessDocError, match="uv sync --extra business-doc"):
        render_document(facts, _narrative())


# --------------------------------------------------------------------------------------
# CLI.
# --------------------------------------------------------------------------------------
def _run(hub: Path, monkeypatch, *args: str):
    # KAIROS_CHROME at a path that does not exist: no browser, so no test spawns one.
    monkeypatch.chdir(hub.parent)
    return CliRunner().invoke(
        cli,
        ["business-doc", *args],
        env={"KAIROS_SKILL_CONTEXT": "1", "KAIROS_CHROME": str(hub / "no-browser")},
    )


def test_cli_facts_writes_the_facts_file(shipment_hub, monkeypatch):
    result = _run(shipment_hub, monkeypatch, "shipment", "--facts", "--format", "json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    path = Path(payload["facts"])
    assert path == shipment_hub.parent / "ontology-hub-publish" / "business" / "shipment" / (
        "business-doc.facts.json"
    )
    assert json.loads(path.read_text(encoding="utf-8"))["facts_hash"] == payload["facts_hash"]


def test_cli_render_refuses_a_narrative_that_does_not_match(shipment_hub, monkeypatch):
    narrative = _narrative()
    narrative["relationships"]["R7"] = {"one": "a", "other": "b"}
    path = shipment_hub.parent / "narrative.yaml"
    path.write_text(yaml.safe_dump(narrative), encoding="utf-8")
    result = _run(
        shipment_hub,
        monkeypatch,
        "shipment",
        "--render",
        "--narrative",
        str(path),
        "--format",
        "json",
    )
    assert result.exit_code == 1
    assert any("R7" in e for e in json.loads(result.output)["errors"])


def test_cli_render_writes_the_document(shipment_hub, monkeypatch):
    pytest.importorskip("docx")
    path = shipment_hub.parent / "narrative.yaml"
    path.write_text(yaml.safe_dump(_narrative()), encoding="utf-8")
    result = _run(
        shipment_hub,
        monkeypatch,
        "shipment",
        "--render",
        "--narrative",
        str(path),
        "--no-pdf",
        "--format",
        "json",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert Path(payload["document"]).name == "shipment-validation-v2.docx"
    assert Path(payload["document"]).is_file()
    assert payload["pdf"] is None
    assert any("headless" in w for w in payload["warnings"])


def test_cli_needs_a_mode(shipment_hub, monkeypatch):
    result = _run(shipment_hub, monkeypatch, "shipment")
    assert result.exit_code == 2
    assert "--facts or --render" in result.output
