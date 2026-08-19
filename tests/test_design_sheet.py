# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""DD-190 design-sheet semantics on table-anchors.yaml.

Pins: the three new model outputs are validated deterministically (invented
secondary classes, same-grain clusters, unknown/self relationship targets and
non-column join inputs are all dropped and counted); a human-confirmed entry
with an unchanged schema is pinned — preserved verbatim and EXCLUDED from the
model call; a confirmed entry whose schema changed releases its pin to
``stale-confirmed`` with the previous values kept; and a human-confirmed sheet
anchor bypasses the alignment confidence floor (a decision is not a score).
"""

from unittest.mock import MagicMock, patch

import yaml

from kairos_ontology.core.anchor_tables import (
    ANCHORS_FILENAME,
    ClassCatalog,
    anchor_response_schema,
    load_table_anchors,
    sheet_schema_hash,
)


def catalog():
    return ClassCatalog(
        text="- TransportCall [owned by domain 'route-schedule']: A call.\n"
        "- Consignment [owned by domain 'consignment']: Goods moving together.",
        index={
            "TransportCall": [
                {"module": "https://ex.org/tc", "uri": "https://ex.org/tc#TransportCall"}
            ],
            "Consignment": [
                {"module": "https://ex.org/cons", "uri": "https://ex.org/cons#Consignment"}
            ],
        },
        owners={
            "https://ex.org/tc": ["route-schedule"],
            "https://ex.org/cons": ["consignment"],
        },
        bridged_from={},
    )


STOPS_COLS = ["stop_id", "consignment_id", "tenant_id"]
VERDICT = {
    "anchor": "TransportCall",
    "alternate": None,
    "confidence": 0.9,
    "grain_columns": ["stop_id"],
    "natural_key": ["stop_id"],
    "load_hint": "scd",
    "relationships": [],
    "secondary_entities": [],
    "flags": [],
}


def _run(tmp_path, response_anchors, outline=None):
    from kairos_ontology.core import anchor_tables as at

    vocab = tmp_path / "sources" / "qargo" / "vocabulary"
    vocab.mkdir(parents=True, exist_ok=True)
    (vocab / "stops.vocabulary.ttl").write_text("# no triples\n", encoding="utf-8")

    client = MagicMock()
    message = MagicMock()
    message.content = str(response_anchors).replace("'", '"').replace("None", "null")
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=message)]
    )
    outline = outline or [
        ("qargo", "stops", STOPS_COLS),
        ("qargo", "consignments", ["consignment_id", "order_ref"]),
    ]
    with patch.object(at, "build_class_catalog", return_value=catalog()), patch.object(
        at, "build_source_outline", return_value=outline
    ):
        at.run_anchor_tables(
            client=client, model="m",
            sources_dir=tmp_path / "sources",
            catalog_path=tmp_path / "catalog.xml",
            ref_models_dir=None, accelerator=None,
            analysis_dir=tmp_path / "_analysis",
        )
    return client, load_table_anchors(tmp_path / "_analysis")


class TestSchema:
    def test_sheet_outputs_are_required(self):
        verdict = anchor_response_schema(["t"])["json_schema"]["schema"]["$defs"]["Verdict"]
        for f in ("relationships", "secondary_entities", "flags"):
            assert f in verdict["required"]

    def test_relationship_evidence_is_a_closed_enum(self):
        verdict = anchor_response_schema(["t"])["json_schema"]["schema"]["$defs"]["Verdict"]
        rel = verdict["properties"]["relationships"]["items"]
        assert rel["properties"]["evidence"]["enum"] == ["fk-inclusion", "name"]


class TestValidation:
    def test_relationships_validated_against_estate_and_columns(self, tmp_path):
        v = dict(VERDICT)
        v["relationships"] = [
            {"to_table": "qargo.consignments", "local_column": "consignment_id",
             "evidence": "fk-inclusion"},                       # kept
            {"to_table": "qargo.stops", "local_column": "stop_id",
             "evidence": "name"},                               # self → dropped
            {"to_table": "qargo.ghost", "local_column": "stop_id",
             "evidence": "name"},                               # unknown table → dropped
            {"to_table": "qargo.consignments", "local_column": "nope",
             "evidence": "name"},                               # non-column → dropped
        ]
        _, anchors = _run(tmp_path, {"anchors": {
            "qargo.stops": v,
            "qargo.consignments": {**VERDICT, "anchor": "Consignment",
                                   "grain_columns": ["consignment_id"]},
        }})
        rels = anchors[("qargo", "stops")]["relationships"]
        assert rels == [{"to_table": "qargo.consignments",
                         "local_column": "consignment_id", "evidence": "fk-inclusion"}]

    def test_secondary_entities_same_grain_and_invented_are_dropped(self, tmp_path):
        v = dict(VERDICT)
        v["secondary_entities"] = [
            {"class": "Consignment", "grain_columns": ["consignment_id"],
             "columns": ["consignment_id"]},                    # kept (own grain)
            {"class": "Consignment", "grain_columns": ["stop_id"],
             "columns": ["stop_id"]},                           # same-grain → dropped
            {"class": "MadeUp", "grain_columns": ["consignment_id"],
             "columns": ["consignment_id"]},                    # invented → dropped
        ]
        v["flags"] = ["versioned", "not-a-flag"]
        _, anchors = _run(tmp_path, {"anchors": {
            "qargo.stops": v,
            "qargo.consignments": {**VERDICT, "anchor": "Consignment",
                                   "grain_columns": ["consignment_id"]},
        }})
        entry = anchors[("qargo", "stops")]
        assert [s["class"] for s in entry["secondary_entities"]] == ["Consignment"]
        assert entry["flags"] == ["versioned"], "unknown flags dropped"
        assert entry["status"] == "proposed"
        assert entry["schema_hash"] == sheet_schema_hash(STOPS_COLS)


class TestStickiness:
    def _seed_confirmed(self, tmp_path, schema_hash):
        analysis = tmp_path / "_analysis"
        analysis.mkdir(parents=True, exist_ok=True)
        (analysis / ANCHORS_FILENAME).write_text(
            yaml.safe_dump({"schema_version": 2, "tables": [{
                "system": "qargo", "table": "stops", "anchor": "TransportCall",
                "anchor_uri": "https://ex.org/tc#TransportCall",
                "domain": "route-schedule", "grain_columns": ["stop_id"],
                "natural_key": ["stop_id"], "status": "confirmed",
                "schema_hash": schema_hash,
            }]}),
            encoding="utf-8",
        )

    def test_confirmed_unchanged_entry_is_pinned_and_excluded_from_the_call(
        self, tmp_path
    ):
        self._seed_confirmed(tmp_path, sheet_schema_hash(STOPS_COLS))
        client, anchors = _run(tmp_path, {"anchors": {
            "qargo.consignments": {**VERDICT, "anchor": "Consignment",
                                   "grain_columns": ["consignment_id"]},
        }})
        entry = anchors[("qargo", "stops")]
        assert entry["status"] == "confirmed", "pinned entry preserved verbatim"
        prompt = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "qargo.stops" not in prompt, "pinned table excluded from the model call"
        assert "qargo.consignments" in prompt

    def test_schema_change_releases_the_pin_to_stale_confirmed(self, tmp_path):
        self._seed_confirmed(tmp_path, "0000000000000000")  # hash of a different schema
        _, anchors = _run(tmp_path, {"anchors": {
            "qargo.stops": {**VERDICT, "anchor": "Consignment",
                            "grain_columns": ["stop_id"]},
            "qargo.consignments": {**VERDICT, "anchor": "Consignment",
                                   "grain_columns": ["consignment_id"]},
        }})
        entry = anchors[("qargo", "stops")]
        assert entry["status"] == "stale-confirmed"
        assert entry["anchor"] == "Consignment", "fresh proposal recorded"
        assert entry["previous"]["anchor"] == "TransportCall", (
            "the human decision is kept for review, never silently dropped"
        )

    def test_unanchored_reproposal_keeps_previous_confirmed_values(self, tmp_path):
        self._seed_confirmed(tmp_path, "0000000000000000")
        _, anchors = _run(tmp_path, {"anchors": {
            "qargo.stops": {**VERDICT, "anchor": None},
            "qargo.consignments": {**VERDICT, "anchor": "Consignment",
                                   "grain_columns": ["consignment_id"]},
        }})
        entry = anchors[("qargo", "stops")]
        assert entry["status"] == "stale-confirmed"
        assert entry["anchor"] == "TransportCall", "previous values survive"
        assert "no anchor" in entry["note"]


class TestFloorBypass:
    """resolve_global_anchor (DD-185/DD-190): the actual application logic."""

    def test_confirmed_sheet_anchor_bypasses_the_confidence_floor(self):
        from kairos_ontology.core.propose_alignment import resolve_global_anchor

        ga = {"anchor": "TransportCall", "confidence": 0.05, "status": "confirmed"}
        assert resolve_global_anchor(ga, {"TransportCall"}) == (
            "TransportCall", "sheet-confirmed", "applied",
        ), "a human decision is not a model score — no floor applies"

    def test_confirmed_but_out_of_pool_is_still_not_applied(self):
        from kairos_ontology.core.propose_alignment import resolve_global_anchor

        ga = {"anchor": "TransportCall", "confidence": 0.99, "status": "confirmed"}
        assert resolve_global_anchor(ga, {"Other"}) == (None, "", "outside_pool"), (
            "alignment has no properties to offer for an out-of-pool class; "
            "forcing it would produce a plausible-empty mapping"
        )

    def test_unpinned_low_confidence_stays_below_the_floor(self):
        from kairos_ontology.core.propose_alignment import resolve_global_anchor

        ga = {"anchor": "TransportCall", "confidence": 0.05, "status": "proposed"}
        assert resolve_global_anchor(ga, {"TransportCall"}) == (
            None, "", "low_confidence",
        )

    def test_unpinned_confident_in_pool_applies_as_anchored(self):
        from kairos_ontology.core.propose_alignment import resolve_global_anchor

        ga = {"anchor": "TransportCall", "confidence": 0.9}
        assert resolve_global_anchor(ga, {"TransportCall"}) == (
            "TransportCall", "anchored", "applied",
        ), "model-applied anchors record 'anchored', never 'confirmed' (DD-185)"