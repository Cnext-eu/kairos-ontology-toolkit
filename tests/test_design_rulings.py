# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""DD-192 design rulings: loading boundaries, catalog guard, prompt injection.

Pins the §6c boundaries: only human-decided rulings feed the prompt (a model
may propose one, an unconfirmed proposal is inert); a ruling never introduces
a class (an unresolvable target is skipped and reported); rejections need no
resolution to be actionable; and an absent file is a silent no-op, never an
error.
"""

from __future__ import annotations

import yaml

from kairos_ontology.core.design_rulings import (
    DesignRuling,
    load_design_rulings,
    partition_resolvable,
    render_rulings_prompt,
    rulings_path,
)


def _write(tmp_path, entries):
    path = tmp_path / "design-rulings.yaml"
    path.write_text(yaml.safe_dump(entries), encoding="utf-8")
    return path


RULING = {
    "id": "DR-001", "kind": "disambiguation",
    "scope": {"class_pair": ["Shipment", "TransportMovement"],
              "applies_when": "one row per executed physical movement"},
    "ruling": "TransportMovement",
    "rationale": "DCSA Shipment is the commercial object.",
    "decided_by": "user", "date": "2026-08-19",
}


class TestLoading:
    def test_absent_file_is_a_silent_noop(self, tmp_path):
        result = load_design_rulings(tmp_path / "nope.yaml")
        assert result.rulings == [] and result.skipped == []

    def test_human_decided_ruling_loads(self, tmp_path):
        result = load_design_rulings(_write(tmp_path, [RULING]))
        [r] = result.rulings
        assert (r.id, r.ruling, r.kind) == ("DR-001", "TransportMovement",
                                            "disambiguation")
        assert r.class_pair == ("Shipment", "TransportMovement")

    def test_model_proposed_ruling_is_inert_and_reported(self, tmp_path):
        proposal = {**RULING, "id": "DR-AI", "decided_by": "ai"}
        result = load_design_rulings(_write(tmp_path, [RULING, proposal]))
        assert [r.id for r in result.rulings] == ["DR-001"]
        [skipped] = result.skipped
        assert skipped["id"] == "DR-AI" and "human-decided" in skipped["reason"]

    def test_unknown_kind_and_missing_target_are_skipped(self, tmp_path):
        bad_kind = {**RULING, "id": "DR-K", "kind": "mandate"}
        no_target = {**RULING, "id": "DR-T", "ruling": ""}
        result = load_design_rulings(_write(tmp_path, [bad_kind, no_target]))
        assert result.rulings == []
        assert {s["id"] for s in result.skipped} == {"DR-K", "DR-T"}

    def test_rulings_path_is_sibling_discovery(self, tmp_path):
        sources = tmp_path / "integration" / "sources"
        assert rulings_path(sources) == (
            tmp_path / "integration" / "discovery" / "design-rulings.yaml"
        )


class TestCatalogGuard:
    def _ruling(self, kind="disambiguation", target="TransportMovement"):
        return DesignRuling(id="DR-X", kind=kind, ruling=target, rationale="",
                            applies_when="", class_pair=())

    def test_unresolvable_target_is_skipped_a_ruling_never_introduces_a_class(self):
        applicable, skipped = partition_resolvable(
            [self._ruling(target="MadeUpClass")], {"TransportMovement"})
        assert applicable == []
        assert "never introduces a class" in skipped[0]["reason"]

    def test_rejection_rulings_need_no_resolution(self):
        applicable, skipped = partition_resolvable(
            [self._ruling(kind="rejection", target="VendorPseudoEntity")],
            {"TransportMovement"})
        assert len(applicable) == 1 and skipped == []


class TestPromptInjection:
    def test_render_outranks_and_carries_the_condition(self):
        r = DesignRuling(
            id="DR-001", kind="disambiguation", ruling="TransportMovement",
            rationale="commercial vs execution",
            applies_when="row chaining present",
            class_pair=("Shipment", "TransportMovement"))
        text = render_rulings_prompt([r])
        assert "OUTRANK" in text
        assert "when row chaining present" in text
        assert "never re-litigate" in text
        assert render_rulings_prompt([]) == ""

    def test_anchor_prompt_carries_the_rulings_section(self):
        from kairos_ontology.core.anchor_tables import ClassCatalog, build_anchor_prompt

        catalog = ClassCatalog(text="- T [UNOWNED]: t", index={}, owners={},
                               bridged_from={})
        with_rulings = build_anchor_prompt(
            [("s", "t", ["c"])], catalog, 1, rulings_text="RULING-MARK")
        without = build_anchor_prompt([("s", "t", ["c"])], catalog, 1)
        assert "RULING-MARK" in with_rulings
        assert "RULING-MARK" not in without