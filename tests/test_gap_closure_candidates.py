# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""A closure candidate stops the gap sheet drafting a local property (DD-248, #1051).

On a 15-domain hub ``draft-gap-decisions --suggest`` proposed ``registered-extension``
for 204 of 223 open names, and a deterministic lookup found 50-80 of them already had a
property in the import closure. These tests pin the three refusals: the rule never drafts
an extension over a candidate, the model is shown the candidate and told not to, and
``--accept-proposals`` leaves such an entry for a human.
"""

import json

import yaml

from kairos_ontology.core.alignment_report import (
    REASON_CLOSURE_CANDIDATE,
    GapGroup,
    UnmappedColumn,
)
from kairos_ontology.core.gap_decisions import (
    GapProposal,
    accept_proposals,
    build_decision_sheet,
    group_into_families,
    propose_for_group,
    suggest_family_dispositions,
    suggest_loose_dispositions,
)
from kairos_ontology.core.prompt_context import render_closure_candidates

LEGAL = {
    "uri": "urn:bsp#legalName", "name": "legalName", "class": "Party",
    "score": 1.0, "match": "exact",
}
TRADING = {
    "uri": "urn:bsp#tradingName", "name": "tradingName", "class": "Party",
    "score": 0.84, "match": "near",
}
DRAFT = {"name": "legalName", "range": "xsd:string", "on_class": "Party", "why": "..."}


def _group(column, *, tables=1, candidates=(), proposal=None):
    return GapGroup(
        column=column,
        occurrences=[
            UnmappedColumn(
                system="src", table=f"t{i}", column=column, data_type="varchar",
                reason=REASON_CLOSURE_CANDIDATE, domain="party",
                proposal=dict(proposal or {}), closure_candidates=tuple(candidates),
            )
            for i in range(tables)
        ],
    )


class _CapturingClient:
    """Captures each prompt and answers ``registered-extension`` for every key."""

    def __init__(self):
        self.prompts: list[str] = []
        outer = self

        class _Completions:
            @staticmethod
            def create(**kwargs):
                outer.prompts.append(kwargs["messages"][0]["content"])
                schema = kwargs["response_format"]["json_schema"]["schema"]
                [top] = schema["properties"]  # "columns" or "families"
                keys = schema["properties"][top]["required"]
                payload = {
                    top: {
                        key: {"coherent": True, "proposed_disposition": "registered-extension",
                              "reasoning": "a real business fact"}
                        for key in keys
                    }
                }

                class _Message:
                    content = json.dumps(payload)

                class _Choice:
                    message = _Message()

                class _Response:
                    choices = [_Choice()]

                return _Response()

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


class TestRuleProposal:
    def test_a_candidate_pre_empts_the_drafted_property_rule(self):
        drafted = propose_for_group(_group("LEGAL_NAME", candidates=[LEGAL], proposal=DRAFT))

        assert drafted.proposed_disposition == ""
        assert drafted.confidence == "low"
        assert "Party.legalName (exact)" in drafted.reasoning
        assert "before registering an extension" in drafted.reasoning
        entry = drafted.to_entry()
        assert entry["closure_candidates"] == [LEGAL]
        assert entry["suggested_properties"] == [DRAFT]  # the draft is kept as evidence

    def test_a_candidate_pre_empts_both_blueprint_gap_rules(self):
        identifier = propose_for_group(_group("CUSTOMER_REF", tables=3, candidates=[TRADING]))
        wide = propose_for_group(_group("LEGAL_NAME", tables=6, candidates=[LEGAL]))

        assert identifier.proposed_disposition == ""
        assert wide.proposed_disposition == ""
        assert "tradingName (near 0.84)" in identifier.reasoning

    def test_free_text_and_blobs_still_rule_but_carry_the_candidates(self):
        note = propose_for_group(_group("REMARK", candidates=[LEGAL]))
        assert note.proposed_disposition == "not-business-data"
        assert note.to_entry()["closure_candidates"] == [LEGAL]

    def test_without_candidates_the_drafted_property_rule_is_unchanged(self):
        drafted = propose_for_group(_group("LEGAL_NAME", proposal=DRAFT))
        assert drafted.proposed_disposition == "registered-extension"
        assert "closure_candidates" not in drafted.to_entry()


class TestFamilies:
    def test_a_family_unions_its_members_candidates(self):
        members = [
            GapProposal("pickup_legal_name", "party", 1, ["t"], ["varchar"], "", "low", "",
                        closure_candidates=[{**LEGAL, "score": 0.9, "match": "near"}]),
            GapProposal("pickup_trading_name", "party", 1, ["t"], ["varchar"], "", "low", "",
                        closure_candidates=[TRADING, LEGAL]),
            GapProposal("pickup_city_name", "party", 1, ["t"], ["varchar"], "", "low", ""),
        ]
        [family], loose = group_into_families(members)

        assert loose == []
        assert family["closure_candidates"] == [LEGAL, TRADING]  # best score per uri
        assert family["members_with_closure_candidates"] == [
            "pickup_legal_name", "pickup_trading_name",
        ]


class TestSuggestPrompts:
    def test_the_loose_prompt_shows_the_candidate_and_forbids_an_extension(self):
        sheet = {
            "families": [],
            "decisions": [
                {"column": "LEGAL_NAME", "domain": "party", "decision": "",
                 "proposed_disposition": "", "occurrences": 1, "tables": ["src.t0"],
                 "data_types": ["varchar"], "closure_candidates": [LEGAL, TRADING]},
                {"column": "MYSTERY", "domain": "party", "decision": "",
                 "proposed_disposition": "", "occurrences": 1, "tables": ["src.t0"],
                 "data_types": ["varchar"]},
            ],
        }
        client = _CapturingClient()

        suggest_loose_dispositions(sheet, client=client, model="m")

        [prompt] = client.prompts
        assert (
            "CLOSURE CANDIDATES: Party.legalName (exact) <urn:bsp#legalName>; "
            "Party.tradingName (near 0.84) <urn:bsp#tradingName>"
        ) in prompt
        assert "Do not answer registered-extension for that" in prompt
        mystery_line = next(line for line in prompt.splitlines() if "party::MYSTERY" in line)
        assert "CLOSURE CANDIDATES" not in mystery_line

    def test_the_family_prompt_shows_the_candidates(self):
        sheet = {
            "families": [
                {"family": "pickup", "domain": "party", "decision": "", "distinct_names": 3,
                 "source_columns": 3, "members": ["pickup_a", "pickup_b", "pickup_c"],
                 "data_types": ["varchar"], "closure_candidates": [LEGAL]},
            ],
            "decisions": [],
        }
        client = _CapturingClient()

        suggest_family_dispositions(sheet, client=client, model="m")

        [prompt] = client.prompts
        assert "CLOSURE CANDIDATES: Party.legalName (exact) <urn:bsp#legalName>" in prompt
        assert "Do not answer registered-extension for that family" in " ".join(prompt.split())

    def test_render_closure_candidates(self):
        assert render_closure_candidates([LEGAL, TRADING]) == (
            "Party.legalName (exact) <urn:bsp#legalName>; "
            "Party.tradingName (near 0.84) <urn:bsp#tradingName>"
        )
        assert render_closure_candidates([LEGAL, TRADING], limit=1) == (
            "Party.legalName (exact) <urn:bsp#legalName>"
        )
        assert render_closure_candidates([]) == ""


class TestAcceptProposalsHold:
    def _sheet(self):
        return {
            "families": [
                {"family": "pickup", "domain": "party", "decision": "",
                 "proposed_disposition": "registered-extension", "closure_candidates": [LEGAL]},
            ],
            "decisions": [
                {"column": "A", "domain": "party", "decision": "",
                 "proposed_disposition": "registered-extension", "closure_candidates": [LEGAL]},
                {"column": "B", "domain": "party", "decision": "",
                 "proposed_disposition": "", "closure_candidates": [LEGAL]},
                {"column": "C", "domain": "party", "decision": "",
                 "proposed_disposition": "deferred", "closure_candidates": [LEGAL]},
                {"column": "D", "domain": "party", "decision": "",
                 "proposed_disposition": "registered-extension"},
            ],
        }

    def test_an_extension_over_a_candidate_is_held_and_the_rest_accepted(self):
        sheet = self._sheet()

        counts = accept_proposals(sheet)

        assert counts == {
            "held-for-closure-candidate": 3, "deferred": 1, "registered-extension": 1,
        }
        assert sheet["families"][0]["decision"] == ""
        assert [e["decision"] for e in sheet["decisions"]] == [
            "", "", "deferred", "registered-extension",
        ]


class TestEndToEnd:
    def test_candidates_on_an_alignment_reach_the_sheet(self, tmp_path):
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True)
        (analysis / "party-alignment.yaml").write_text(
            yaml.safe_dump(
                {
                    "domain": "party",
                    "tables": [
                        {
                            "system": "src", "table": "companies", "ref_class": "Party",
                            "columns": [],
                            "custom_columns": [
                                {"column": "LEGAL_NAME", "data_type": "varchar",
                                 "proposed_local_property": DRAFT,
                                 "closure_candidates": [LEGAL]},
                                {"column": "MYSTERY", "data_type": "varchar"},
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        sheet = build_decision_sheet(tmp_path)

        assert sheet["summary"]["with_closure_candidates"] == 1
        assert "closure_candidates" in sheet["how_to_use"]
        by_column = {e["column"]: e for e in sheet["decisions"]}
        assert by_column["LEGAL_NAME"]["closure_candidates"] == [LEGAL]
        assert by_column["LEGAL_NAME"]["proposed_disposition"] == ""
        assert "closure_candidates" not in by_column["MYSTERY"]
