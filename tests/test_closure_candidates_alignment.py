# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""A custom column carries the closure properties the prompt never showed (DD-248, #1051)."""

from kairos_ontology.core import propose_alignment as pa
from kairos_ontology.core.closure_lookup import terms_from_ref_classes

BSP = "https://ref.example/ont/bsp#"


def _cls(name, *props):
    return {
        "uri": f"{BSP}{name}",
        "name": name,
        "properties": [
            {"uri": f"{BSP}{p}", "name": p, "label": "", "type": "datatype"} for p in props
        ],
    }


def _custom(column):
    return {"column": column, "alignment": "custom", "confidence": 0.0, "ref_property": ""}


PARTY = _cls("Party", "partyName", "legalName")
CONTRACT = _cls("Contract", "contractNumber", "effectiveDate")
COLUMNS = [{"name": n, "data_type": "varchar"} for n in ("LEGAL_NAME", "CONTRACT_NBR", "PARTY_NAME")]


def test_a_property_outside_the_shown_pool_is_a_candidate():
    result = {"column_alignments": [_custom("LEGAL_NAME"), _custom("CONTRACT_NBR")]}

    found = pa.closure_candidates_for_result(
        result, terms_from_ref_classes([PARTY, CONTRACT]), shown_pool=[PARTY], columns=COLUMNS
    )

    # legalName was on the prompt (Party is in the pool) and the model declined it: a
    # verdict, not a pool artefact. contractNumber was never shown.
    assert found == {
        "CONTRACT_NBR": [
            {"uri": f"{BSP}contractNumber", "name": "contractNumber", "class": "Contract",
             "score": 1.0, "match": "exact"}
        ]
    }


def test_a_property_past_the_prompt_cut_counts_as_not_shown():
    wide = _cls("Party", *[f"filler{i}" for i in range(pa.MAX_REF_PROPERTIES_PER_PROMPT)], "legalName")
    result = {"column_alignments": [_custom("LEGAL_NAME")]}

    found = pa.closure_candidates_for_result(
        result, terms_from_ref_classes([wide]), shown_pool=[wide], columns=COLUMNS
    )

    assert [c["name"] for c in found["LEGAL_NAME"]] == ["legalName"]


def test_the_table_vendor_prefix_is_stripped_and_mapped_columns_are_ignored():
    columns = [{"name": f"XX_{c['name']}", "data_type": "varchar"} for c in COLUMNS]
    result = {
        "column_alignments": [
            _custom("XX_LEGAL_NAME"),
            {"column": "XX_PARTY_NAME", "alignment": "exact", "ref_property": "partyName"},
        ]
    }

    found = pa.closure_candidates_for_result(
        result, terms_from_ref_classes([PARTY, CONTRACT]), shown_pool=[CONTRACT], columns=columns
    )

    assert set(found) == {"XX_LEGAL_NAME"}
    assert found["XX_LEGAL_NAME"][0]["match"] == "exact"


def test_an_empty_closure_or_no_custom_columns_yields_nothing():
    result = {"column_alignments": [_custom("LEGAL_NAME")]}
    assert pa.closure_candidates_for_result(
        result, terms_from_ref_classes([]), shown_pool=[], columns=COLUMNS
    ) == {}
    assert pa.closure_candidates_for_result(
        {"column_alignments": []}, terms_from_ref_classes([PARTY]), shown_pool=[], columns=COLUMNS
    ) == {}


def test_the_custom_column_entry_carries_the_candidates_only_when_present():
    ca = {"column": "LEGAL_NAME", "alignment": "custom", "confidence": 0.0, "rationale": ""}
    with_candidates = pa._build_custom_column(
        ca, "varchar", confidence_floor=0.5,
        closure_candidates=[{"uri": f"{BSP}legalName", "name": "legalName", "class": "Party",
                             "score": 1.0, "match": "exact"}],
    )
    without = pa._build_custom_column(ca, "varchar", confidence_floor=0.5, closure_candidates=None)

    assert with_candidates["closure_candidates"][0]["name"] == "legalName"
    assert "closure_candidates" not in without


def test_the_disclosure_line_counts_the_classes_the_shortlist_cut():
    columns = [{"name": "LEGAL_NAME", "data_type": "varchar", "samples": []}]
    prompt = pa.build_alignment_prompt("companies", columns, [PARTY], omitted_classes=3)
    assert "3 further class(es)" in prompt
    assert "further class(es)" not in pa.build_alignment_prompt("companies", columns, [PARTY])


def test_the_class_scorer_sees_every_property():
    wide = _cls("Party", *[f"filler{i}" for i in range(pa.MAX_REF_PROPERTIES_PER_PROMPT)], "legalName")
    score = pa._score_ref_class(
        wide,
        table_tokens=set(),
        column_tokens={"legal", "name"},
        likely_entity_tokens=set(),
        indicative_tokens=set(),
    )
    assert score > 0
