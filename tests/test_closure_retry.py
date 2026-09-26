# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The targeted closure retry (DD-248 §4, #1051).

A column the model left ``custom`` while a same-named property sat past the prompt's cut
gets one more chance: a call for those columns only, the table's class pinned, the
candidate classes as the pool with the candidates listed first. Not a wider prompt.
"""

import json
from unittest import mock

from kairos_ontology.core import propose_alignment as pa
from kairos_ontology.core.propose_alignment import build_domain_alignments

from tests.test_propose_alignment import analysis_dir, sources_dir  # noqa: F401 - fixtures

BSP = "https://ref.example/ont/bsp#"


def _cls(name, *props):
    return {
        "uri": f"{BSP}{name}",
        "name": name,
        "label": name,
        "comment": "",
        "properties": [
            {"uri": f"{BSP}{p}", "name": p, "label": p, "range": "string", "type": "datatype"}
            for p in props
        ],
    }


CONTRACT = _cls("SalesContract", "contractIdentifier", "effectiveDate")
PARTY = _cls("TradeParty", "partyName")
#: ``internalCode`` sits past the sixtieth property, so the first prompt never lists it.
REGISTER = _cls(
    "InternalRegister", *[f"filler{i:02d}" for i in range(pa.MAX_REF_PROPERTIES_PER_PROMPT)],
    "internalCode",
)
INVENTORY = [CONTRACT, PARTY, REGISTER]

CANDIDATES = {
    "InternalCode": [
        {"uri": f"{BSP}internalCode", "name": "internalCode", "class": "InternalRegister",
         "score": 1.0, "match": "exact"}
    ]
}


class TestPlan:
    def test_anchor_first_then_owners_with_candidates_listed_first(self):
        pool, columns = pa.closure_retry_plan(
            CANDIDATES, INVENTORY, anchor_class="SalesContract", max_classes=12
        )

        assert [c["name"] for c in pool] == ["SalesContract", "InternalRegister"]
        assert pool[1]["properties"][0]["name"] == "internalCode"
        assert columns == ["InternalCode"]
        # The originals are untouched and the pool entry keeps every other key.
        assert REGISTER["properties"][-1]["name"] == "internalCode"
        assert pool[1]["uri"] == REGISTER["uri"]

    def test_no_resolvable_anchor_means_no_retry(self):
        assert pa.closure_retry_plan(CANDIDATES, INVENTORY, anchor_class="") == ([], [])
        assert pa.closure_retry_plan(CANDIDATES, INVENTORY, anchor_class="Nope") == ([], [])
        assert pa.closure_retry_plan({}, INVENTORY, anchor_class="SalesContract") == ([], [])

    def test_owners_are_ranked_and_cut_and_unserved_columns_dropped(self):
        owners = [_cls(f"Owner{i}", f"prop{i}") for i in range(4)]
        candidates = {
            "A": [{"uri": f"{BSP}prop0", "score": 0.9}, {"uri": f"{BSP}prop1", "score": 0.8}],
            "B": [{"uri": f"{BSP}prop0", "score": 0.8}],
            "C": [{"uri": f"{BSP}prop2", "score": 0.95}],
            "D": [{"uri": f"{BSP}prop3", "score": 0.85}],
        }
        pool, columns = pa.closure_retry_plan(
            candidates, [CONTRACT, *owners], anchor_class="SalesContract", max_classes=3
        )
        # Owner0 serves two columns; then by best score: Owner2 (0.95) beats Owner3 and Owner1.
        assert [c["name"] for c in pool] == ["SalesContract", "Owner0", "Owner2"]
        assert columns == ["A", "B", "C"]


class TestMerge:
    def test_a_mapped_answer_replaces_the_custom_entry_and_drops_its_candidates(self):
        first = {
            "ref_class": "SalesContract",
            "column_alignments": [
                {"column": "ContractNo", "alignment": "semantic", "ref_property": "x"},
                {"column": "InternalCode", "alignment": "custom", "ref_property": ""},
            ],
            "closure_candidates": dict(CANDIDATES),
        }
        retry = {
            "column_alignments": [
                {"column": "InternalCode", "alignment": "semantic",
                 "ref_class": "InternalRegister", "ref_property": "internalCode",
                 "confidence": 0.8},
            ]
        }
        merged = pa.merge_closure_retry(first, retry, ["InternalCode"])

        assert merged["column_alignments"][1]["ref_property"] == "internalCode"
        assert merged["column_alignments"][1]["closure_retry"] is True
        assert merged["closure_candidates"] == {}
        assert first["column_alignments"][1]["alignment"] == "custom"  # input untouched

    def test_a_custom_answer_leaves_the_first_pass_alone(self):
        first = {
            "column_alignments": [{"column": "InternalCode", "alignment": "custom"}],
            "closure_candidates": dict(CANDIDATES),
        }
        retry = {"column_alignments": [{"column": "InternalCode", "alignment": "custom"}]}
        merged = pa.merge_closure_retry(first, retry, ["InternalCode"])
        assert merged["column_alignments"] == first["column_alignments"]
        assert merged["closure_candidates"] == CANDIDATES


def _client(calls):
    """Answer the first pass per table, and the pinned retry with a mapping."""

    def create(**kwargs):
        prompt = kwargs["messages"][1]["content"]
        calls.append(prompt)
        if "STEP 1 (already decided)" in prompt:
            payload = {
                "ref_class": "SalesContract",
                "ref_class_confidence": 0.9,
                "column_alignments": [
                    {"column": "InternalCode", "ref_class": "InternalRegister",
                     "ref_property": "internalCode", "alignment": "semantic",
                     "confidence": 0.8, "rationale": "the register code"},
                ],
            }
        elif "tblContracts" in prompt:
            payload = {
                "ref_class": "SalesContract",
                "ref_class_confidence": 0.9,
                "column_alignments": [
                    {"column": "ContractNo", "ref_class": "SalesContract",
                     "ref_property": "contractIdentifier", "alignment": "semantic",
                     "confidence": 0.9, "rationale": ""},
                    {"column": "ValidFrom", "ref_class": "SalesContract",
                     "ref_property": "effectiveDate", "alignment": "semantic",
                     "confidence": 0.9, "rationale": ""},
                    {"column": "InternalCode", "ref_property": "", "alignment": "custom",
                     "confidence": 0.0, "rationale": "nothing listed fits"},
                ],
            }
        else:
            payload = {
                "ref_class": "TradeParty",
                "ref_class_confidence": 0.9,
                "column_alignments": [
                    {"column": "PartyName", "ref_class": "TradeParty",
                     "ref_property": "partyName", "alignment": "exact",
                     "confidence": 0.95, "rationale": ""},
                ],
            }
        return mock.MagicMock(
            choices=[mock.MagicMock(message=mock.MagicMock(content=json.dumps(payload)))]
        )

    client = mock.MagicMock()
    client.chat.completions.create = create
    return client


def _run(analysis, sources, calls, **kwargs):
    with (
        mock.patch(
            "kairos_ontology.core.propose_alignment.get_ai_client",
            return_value=_client(calls),
        ),
        mock.patch("kairos_ontology.core.propose_alignment.require_ai_provider"),
        mock.patch(
            "kairos_ontology.core.propose_alignment.extract_ref_model_inventory",
            return_value=[dict(c) for c in INVENTORY],
        ),
    ):
        alignments = build_domain_alignments(
            analysis_dir=analysis, sources_dir=sources, catalog_path=None,
            without_anchors=True, force=True, **kwargs,
        )
    return next(a for a in alignments if a.domain == "commercial")


class TestEndToEnd:
    def test_the_retry_re_offers_the_cut_property_with_the_class_pinned(
        self, analysis_dir, sources_dir  # noqa: F811
    ):
        calls: list[str] = []
        commercial = _run(analysis_dir, sources_dir, calls)

        retry_prompts = [p for p in calls if "STEP 1 (already decided)" in p]
        assert len(retry_prompts) == 1
        [retry] = retry_prompts
        assert "this table IS 'SalesContract'" in retry
        assert "InternalCode" in retry and "ContractNo" not in retry  # only the candidate column
        assert "internalCode" in retry  # listed now, first under its class
        assert retry.index("internalCode") < retry.index("filler00")

        [table] = commercial.tables
        mapped = {c.column: c for c in table.columns}
        assert mapped["InternalCode"].ref_property == "internalCode"
        assert mapped["InternalCode"].closure_retry is True
        assert mapped["ContractNo"].closure_retry is None
        assert [c["column"] for c in table.custom_columns] == []
        emitted = pa.alignment_to_dict(commercial)
        cols = {c["column"]: c for c in emitted["tables"][0]["columns"]}
        assert cols["InternalCode"]["closure_retry"] is True
        assert "closure_retry" not in cols["ContractNo"]

    def test_without_the_retry_the_candidate_stays_on_the_custom_column(
        self, analysis_dir, sources_dir  # noqa: F811
    ):
        calls: list[str] = []
        commercial = _run(analysis_dir, sources_dir, calls, closure_retry=False)

        assert not any("STEP 1 (already decided)" in p for p in calls)
        [table] = commercial.tables
        [custom] = table.custom_columns
        assert custom["column"] == "InternalCode"
        assert [c["name"] for c in custom["closure_candidates"]] == ["internalCode"]
        assert custom["closure_candidates"][0]["class"] == "InternalRegister"
