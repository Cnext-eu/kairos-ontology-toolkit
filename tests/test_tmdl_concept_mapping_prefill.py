# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""`import-tmdl` proposes a `reference_model_match` instead of shipping 368 empty rows (#762).

Concept-mapping worksheets were written 100% empty, and nothing downstream infers the field
— `design-landscape` says plainly that it performs no classification of its own. So on a
hub with a large legacy estate it reported no BI weight at all until hundreds of rows were
triaged by hand: 368 on the reported hub, across 18 PBIP exports.

The proposal is deliberately lexical and deterministic, reusing the matcher `suggest-anchor`
already uses. It is written as `action: candidate` and **not** counted as BI weight until a
modeller confirms it: the signal exists to say what the business actually reports on, and
letting a name guess vote on that would invert its meaning. Confirming a proposal is far
cheaper than authoring one, which is where the saving is.
"""

from __future__ import annotations

import yaml

from kairos_ontology.core.class_anchoring import ReferenceTerm
from kairos_ontology.core.import_tmdl import (
    generate_concept_mapping,
    propose_reference_matches,
)
from kairos_ontology.core.tmdl_parser import TmdlModel, TmdlTable


def _model(*names: str) -> TmdlModel:
    model = TmdlModel(name="Sales")
    model.tables = [TmdlTable(name=name) for name in names]
    return model


def _tables(document: str) -> dict[str, dict]:
    return {item["tmdl_name"]: item for item in yaml.safe_load(document)["tables"]}


class TestWorksheetShape:
    def test_a_proposal_is_marked_candidate_and_carries_its_reasoning(self):
        document = generate_concept_mapping(
            _model("d_Customer"),
            {"d_Customer": ("TransportParty", 0.8, "qualified form")},
        )
        entry = _tables(document)["d_Customer"]

        assert entry["reference_model_match"] == "TransportParty"
        assert entry["action"] == "candidate"
        assert entry["match_confidence"] == 0.8
        # The reason travels with the proposal: a modeller confirming it needs to know
        # what it was based on, not just that something was guessed.
        assert entry["match_reason"] == "qualified form"

    def test_a_table_with_no_proposal_is_unchanged(self):
        entry = _tables(generate_concept_mapping(_model("f_Sales"), {}))["f_Sales"]
        assert entry["reference_model_match"] == ""
        assert entry["action"] == ""
        assert "match_confidence" not in entry

    def test_no_proposals_reproduces_the_previous_output(self):
        """The argument is optional, so a caller that does not pass it is unaffected."""
        assert generate_concept_mapping(_model("d_Customer")) == generate_concept_mapping(
            _model("d_Customer"), None
        )

    def test_the_header_explains_what_candidate_means(self):
        document = generate_concept_mapping(_model("d_Customer"))
        assert "candidate" in document
        assert "NOT a decision" in document


class TestProposer:
    """`propose_reference_matches` against a hand-built term pool."""

    @staticmethod
    def _pool(*names: str) -> list[ReferenceTerm]:
        return [
            ReferenceTerm(
                uri=f"https://example.test/ref#{name}",
                name=name,
                label=name,
                comment="",
                module="ref",
                kind="class",
            )
            for name in names
        ]

    def _propose(self, model, pool, monkeypatch, tmp_path):
        catalog = tmp_path / "catalog-v001.xml"
        catalog.write_text("<catalog/>", encoding="utf-8")
        monkeypatch.setattr(
            "kairos_ontology.core.class_anchoring.read_reference_terms",
            lambda *a, **k: pool,
        )
        return propose_reference_matches(model, catalog)

    def test_a_bi_role_prefix_is_stripped_before_matching(self, monkeypatch, tmp_path):
        """`d_`/`f_` encode table role, never the concept's name."""
        result = self._propose(
            _model("d_Customer"), self._pool("Customer"), monkeypatch, tmp_path
        )
        assert result["d_Customer"][0] == "Customer"

    def test_a_tie_is_left_to_the_modeller(self, monkeypatch, tmp_path):
        """Two equally-good reference classes is the judgement this pass supports, not
        one it should pre-empt."""
        pool = self._pool("Customer") + [
            ReferenceTerm(
                uri="https://example.test/other#Customer",
                name="Customer",
                label="Customer",
                comment="",
                module="other",
                kind="class",
            )
        ]
        assert self._propose(_model("d_Customer"), pool, monkeypatch, tmp_path) == {}

    def test_a_weak_match_is_not_proposed(self, monkeypatch, tmp_path):
        """A proposal below the floor costs more to read than it saves."""
        result = self._propose(
            _model("d_Widget"), self._pool("Consignment"), monkeypatch, tmp_path
        )
        assert result == {}

    def test_no_catalog_means_no_proposals_rather_than_an_error(self, tmp_path):
        """`import-tmdl` runs against an export outside the hub; the catalog may be
        absent, and this pass is advisory."""
        assert propose_reference_matches(_model("d_Customer"), None) == {}
        assert propose_reference_matches(_model("d_Customer"), tmp_path / "missing.xml") == {}
