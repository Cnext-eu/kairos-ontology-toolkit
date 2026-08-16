# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Global table anchoring (DD-185).

The testbed facts these tests pin: ownership marks in the catalog are what took
known-answer accuracy from 5/6 to 6/6; sample values in the anchor prompt cost
accuracy (5/6) and tokens, so the outline is names-only; invented class names
must be rejected, never kept; and domain derivation must be bridge-aware so a
table anchored to a bridged class stays in the bridging domain instead of being
moved to the owner (a grain error).
"""

from unittest.mock import MagicMock, patch

import yaml

from kairos_ontology.core.anchor_tables import (
    ANCHOR_CONFIDENCE_FLOOR,
    ANCHORS_FILENAME,
    ClassCatalog,
    anchor_response_schema,
    build_anchor_prompt,
    derive_domain,
    load_table_anchors,
)


def catalog(**bridged):
    return ClassCatalog(
        text="- TransportCall [owned by domain 'route-schedule']: A call at a location.\n"
        "- Consignment [owned by domain 'consignment']: Goods moving together.\n"
        "- Widget [UNOWNED]: A thing.",
        index={
            "TransportCall": [
                {"module": "https://ex.org/tc", "uri": "https://ex.org/tc#TransportCall"}
            ],
            "Consignment": [
                # Deliberately two copies, the unowned one first: the live defect
                # was ownership derived from an arbitrary single copy.
                {"module": "https://ex.org/other", "uri": "https://ex.org/other#Consignment"},
                {"module": "https://ex.org/cons", "uri": "https://ex.org/cons#Consignment"},
            ],
            "Widget": [{"module": "https://ex.org/w", "uri": "https://ex.org/w#Widget"}],
        },
        owners={"https://ex.org/tc": ["route-schedule"], "https://ex.org/cons": ["consignment"]},
        bridged_from=bridged.get("bridged_from", {}),
    )


class TestDomainDerivation:
    def test_owner_wins_when_unambiguous(self):
        domain, basis, owners, bridged = derive_domain("Consignment", catalog())
        assert (domain, basis) == ("consignment", "owner")

    def test_bridge_keeps_the_table_in_the_bridging_domain(self):
        """The stops case: consignment bridges to TransportCall, route-schedule owns it.
        Affinity says consignment — the table must NOT move to the owner."""
        cat = catalog(bridged_from={"https://ex.org/tc#TransportCall": ["consignment"]})
        domain, basis, _, _ = derive_domain("TransportCall", cat, affinity_domain="consignment")
        assert domain == "consignment"
        assert basis == "bridge+affinity"

    def test_owner_wins_without_an_affinity_prior(self):
        cat = catalog(bridged_from={"https://ex.org/tc#TransportCall": ["consignment"]})
        domain, basis, _, _ = derive_domain("TransportCall", cat)
        assert (domain, basis) == ("route-schedule", "owner")

    def test_affinity_outside_the_candidates_does_not_win(self):
        """Affinity is a tie-break within legitimate candidates, not a veto."""
        domain, basis, _, _ = derive_domain("Consignment", catalog(), affinity_domain="party")
        assert (domain, basis) == ("consignment", "owner")

    def test_unowned_anchor_keeps_affinity_and_is_flagged(self):
        """The extension worklist: a real class no domain imports."""
        domain, basis, owners, bridged = derive_domain("Widget", catalog(), affinity_domain="party")
        assert (domain, basis) == ("party", "unowned")
        assert owners == [] and bridged == []


class TestPrompt:
    CHUNK = [("qargo", "stops", ["stop_id", "arrival_time"])]

    def test_contains_every_table_and_the_catalog(self):
        text = build_anchor_prompt(self.CHUNK, catalog(), 3)
        assert "TABLE qargo.stops (2 columns): stop_id, arrival_time" in text
        assert "TransportCall [owned by domain 'route-schedule']" in text

    def test_carries_the_anchoring_pattern_rules(self):
        text = build_anchor_prompt(self.CHUNK, catalog(), 3)
        assert "subclass-identity-by-role" in text
        assert "governed-code-list" in text
        assert "ONE ROW" in text

    def test_no_sample_values_anywhere(self):
        """Tested: samples cost accuracy (5/6 vs 6/6) and ~7k tokens here."""
        text = build_anchor_prompt(self.CHUNK, catalog(), 3)
        assert "samples" not in text.lower()

    def test_prefers_owned_classes_explicitly(self):
        assert "UNOWNED" in build_anchor_prompt(self.CHUNK, catalog(), 3)


class TestResponseSchema:
    def test_every_table_is_a_required_key(self):
        """The DD-177 shape: omitting a table is a schema violation."""
        fmt = anchor_response_schema(["qargo.stops", "qargo.orders"])
        anchors = fmt["json_schema"]["schema"]["properties"]["anchors"]
        assert anchors["required"] == ["qargo.stops", "qargo.orders"]
        assert anchors["additionalProperties"] is False

    def test_class_names_are_free_strings_not_enums(self):
        """1,275 candidates exceed the provider's 1,000-value enum budget (DD-177)."""
        fmt = anchor_response_schema(["t"])
        verdict = fmt["json_schema"]["schema"]["$defs"]["Verdict"]["properties"]
        assert "enum" not in verdict["anchor"]

    def test_binding_skeleton_fields_are_required(self):
        fmt = anchor_response_schema(["t"])
        verdict = fmt["json_schema"]["schema"]["$defs"]["Verdict"]
        for f in ("grain_columns", "natural_key", "load_hint"):
            assert f in verdict["required"]


class TestRunAndArtifact:
    def _run(self, tmp_path, response_anchors):
        from kairos_ontology.core import anchor_tables as at

        vocab = tmp_path / "sources" / "qargo" / "vocabulary"
        vocab.mkdir(parents=True)
        (vocab / "stops.vocabulary.ttl").write_text("placeholder", encoding="utf-8")

        client = MagicMock()
        message = MagicMock()
        message.content = str(response_anchors).replace("'", '"').replace("None", "null")
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=message)]
        )
        with patch.object(at, "build_class_catalog", return_value=catalog(
            bridged_from={"https://ex.org/tc#TransportCall": ["consignment"]}
        )), patch.object(
            at, "build_source_outline",
            return_value=[("qargo", "stops", ["stop_id", "arrival_time"])],
        ):
            return at.run_anchor_tables(
                client=client, model="m",
                sources_dir=tmp_path / "sources",
                catalog_path=tmp_path / "catalog.xml",
                ref_models_dir=None, accelerator=None,
                analysis_dir=tmp_path / "_analysis",
            )

    def test_writes_a_provenance_stamped_loadable_artifact(self, tmp_path):
        out = self._run(tmp_path, {"anchors": {"qargo.stops": {
            "anchor": "TransportCall", "alternate": None, "confidence": 0.91,
            "grain_columns": ["stop_id"], "natural_key": ["stop_id"], "load_hint": "scd"}}})
        text = out.read_text(encoding="utf-8")
        assert "AI-ASSISTED" in text, "model-authored artifact must say so (DD-178)"
        anchors = load_table_anchors(tmp_path / "_analysis")
        entry = anchors[("qargo", "stops")]
        assert entry["anchor"] == "TransportCall"
        assert entry["grain_columns"] == ["stop_id"]
        assert entry["domain"] == "route-schedule"  # owner; no affinity prior in test

    def test_invented_class_names_are_rejected_with_evidence(self, tmp_path):
        out = self._run(tmp_path, {"anchors": {"qargo.stops": {
            "anchor": "MadeUpClass", "alternate": None, "confidence": 0.9,
            "grain_columns": [], "natural_key": [], "load_hint": None}}})
        doc = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert doc["tables"] == []
        assert "MadeUpClass" in doc["unanchored"][0]["note"]

    def test_null_anchor_lands_in_unanchored(self, tmp_path):
        out = self._run(tmp_path, {"anchors": {"qargo.stops": {
            "anchor": None, "alternate": None, "confidence": 0.1,
            "grain_columns": [], "natural_key": [], "load_hint": None}}})
        doc = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert len(doc["unanchored"]) == 1

    def test_loader_is_empty_when_no_artifact(self, tmp_path):
        assert load_table_anchors(tmp_path) == {}


class TestAlignmentConsumption:
    """The floor and pool checks in _propose_alignments, tested at their contract."""

    def test_floor_constant_is_sane(self):
        assert 0 < ANCHOR_CONFIDENCE_FLOOR < 1

    def test_anchored_status_is_distinct_from_confirmed(self):
        """An LLM anchor must never masquerade as a human confirmation."""
        from kairos_ontology.core.propose_alignment import align_table
        import inspect

        sig = inspect.signature(align_table)
        assert sig.parameters["anchor_status"].default == "confirmed"
        assert sig.parameters["anchor_confidence"].default is None

    def test_artifact_filename_is_stable(self):
        assert ANCHORS_FILENAME == "table-anchors.yaml"


class TestExcludedColumns:
    """DD-164 column dispositions feed the anchor prompt (the tenant_id case)."""

    def _ledger(self, tmp_path, entries):
        import yaml as _y

        (tmp_path / "table-dispositions.yaml").write_text(
            _y.safe_dump({"tables": entries}), encoding="utf-8"
        )
        from kairos_ontology.core.anchor_tables import load_excluded_columns

        return load_excluded_columns(tmp_path)

    def test_not_business_data_columns_are_excluded(self, tmp_path):
        excluded = self._ledger(
            tmp_path,
            [{"system": "qargo", "table": "stops", "column": "tenant_id",
              "disposition": "not-business-data"}],
        )
        assert ("qargo", "stops", "tenant_id") in excluded

    def test_system_wide_wildcard_excludes_everywhere(self, tmp_path):
        """A SaaS tenant discriminator appears in every table the vendor ships."""
        from kairos_ontology.core.anchor_tables import _is_excluded

        excluded = self._ledger(
            tmp_path,
            [{"system": "qargo", "table": "", "column": "tenant_id",
              "disposition": "not-business-data"}],
        )
        assert _is_excluded(excluded, "qargo", "stops", "tenant_id")
        assert _is_excluded(excluded, "qargo", "companies", "tenant_id")
        assert not _is_excluded(excluded, "qlik", "orders", "tenant_id")

    def test_table_dispositions_without_column_do_not_exclude(self, tmp_path):
        """Table-grain scope decisions are a different mechanism; leave them alone."""
        assert self._ledger(
            tmp_path,
            [{"system": "qargo", "table": "stops", "disposition": "not-business-data"}],
        ) == set()

    def test_outline_drops_excluded_columns(self, tmp_path, monkeypatch):
        from kairos_ontology.core import anchor_tables as at

        vocab = tmp_path / "qargo" / "vocabulary"
        vocab.mkdir(parents=True)
        (vocab / "stops.vocabulary.ttl").write_text("x", encoding="utf-8")
        monkeypatch.setattr(
            at, "parse_source_vocabulary",
            lambda _p: {"stops": [{"name": "tenant_id"}, {"name": "stop_id"}]},
        )
        outline = at.build_source_outline(
            tmp_path, excluded_columns={("qargo", "", "tenant_id")}
        )
        assert outline == [("qargo", "stops", ["stop_id"])]


class TestDuplicateNameDerivation:
    def test_ownership_aggregates_across_copies(self):
        """Consignment exists in an unowned module AND mmt/consignment; the owned
        copy must decide, whatever order the copies arrived in."""
        domain, basis, owners, _ = derive_domain("Consignment", catalog())
        assert (domain, basis) == ("consignment", "owner")
        assert owners == ["consignment"]
