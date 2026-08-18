# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""When an anchor decided the class, the pool is derived from it, not lexically scored.

`_score_ref_class` ranks classes by how many of their **properties** match the table's
columns. That answers *"which class holds columns like mine"*. Anchoring asks *"what is
this table"*. Conflating the two inverts the answer whenever a table is largely made of
some other class's properties -- measured on a live hub, ``Address`` scored **44** against
``TradeParty``'s **20** for a *companies* table, because a companies table is mostly
address columns. No amount of denoising fixes that: `Address` genuinely does hold those
properties. The question was wrong.

DD-185 already answers the identity question globally, against the full catalog, and
`anchor_override` already pins the result in the prompt. What was missing is that the
*pool* was still built by the scorer, so a lexically-similar but unrelated class kept
contributing properties to STEP 2 -- and on a weak result the run widened to the full
~1200-class inventory, which the anchor makes pointless.

The lexical path is deliberately untouched for un-anchored tables and `--without-anchors`
runs, so this is additive rather than a swap.
"""

from __future__ import annotations

from typing import Any

from kairos_ontology.core.propose_alignment import (
    MAX_REF_CLASSES_PER_PROMPT,
    _select_ref_classes_for_table,
    anchor_derived_class_pool,
)


def _cls(name: str, props: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "uri": f"https://example.test/ont#{name}",
        "label": name,
        "comment": "",
        "properties": [{"name": p, "label": p, "range": "string"} for p in props],
        **extra,
    }


# The measured inversion, reproduced at fixture scale: a companies table whose columns
# are overwhelmingly address-shaped, while what a row IS remains a trade party.
ADDRESS = _cls("Address", ["street", "city", "postalCode", "country", "state", "region"])
TRADE_PARTY = _cls("TradeParty", ["legalName", "vatNumber"])
COMPANIES_COLUMNS = [
    {"name": c}
    for c in (
        "billing_city",
        "billing_country",
        "billing_postal_code",
        "billing_street",
        "billing_state",
        "legal_name",
    )
]


class TestTheInversionIsBypassed:
    def test_the_lexical_scorer_really_does_prefer_address(self):
        """Establish the premise: without this change the wrong class ranks first.

        If this ever stops holding, the fixture no longer reproduces the defect and the
        test below is proving nothing.
        """
        ranked = _select_ref_classes_for_table(
            "companies",
            COMPANIES_COLUMNS,
            [ADDRESS, TRADE_PARTY],
            likely_entity="",
            max_classes=2,
        )
        assert [c["name"] for c in ranked][0] == "Address"

    def test_the_anchor_decides_instead(self):
        pool = anchor_derived_class_pool("TradeParty", [ADDRESS, TRADE_PARTY])
        assert [c["name"] for c in pool] == ["TradeParty"]

    def test_a_lexically_dominant_class_does_not_enter_the_pool(self):
        """Address is not merely outranked -- it is not offered at all.

        It has no declared bridge and is not a specialization, so nothing authorises it
        to contribute properties to this table.
        """
        pool = anchor_derived_class_pool("TradeParty", [ADDRESS, TRADE_PARTY])
        assert "Address" not in {c["name"] for c in pool}


class TestPoolComposition:
    def test_anchor_is_always_first(self):
        others = [_cls(f"Other{i}", ["x"]) for i in range(5)]
        pool = anchor_derived_class_pool("TradeParty", others + [TRADE_PARTY])
        assert pool[0]["name"] == "TradeParty"

    def test_specializations_are_included(self):
        """A refinement of the anchor is the same thing, more precisely stated."""
        consignee = _cls("Consignee", ["deliveryInstruction"])
        anchor = _cls(
            "TradeParty",
            ["legalName"],
            specializations=[{"name": "Consignee", "uri": consignee["uri"]}],
        )
        pool = anchor_derived_class_pool("TradeParty", [anchor, consignee, ADDRESS])
        names = [c["name"] for c in pool]
        assert names[0] == "TradeParty"
        assert "Consignee" in names
        assert "Address" not in names

    def test_specializations_given_as_bare_strings_also_resolve(self):
        consignee = _cls("Consignee", ["deliveryInstruction"])
        anchor = _cls("TradeParty", ["legalName"], specializations=["Consignee"])
        pool = anchor_derived_class_pool("TradeParty", [anchor, consignee])
        assert "Consignee" in {c["name"] for c in pool}

    def test_declared_bridge_anchors_are_included(self):
        """DD-181: the blueprint already authorised this domain to reference them."""
        bridged = _cls("TransportCall", ["portOfCall"], bridge_target_domain="route-schedule")
        pool = anchor_derived_class_pool("TradeParty", [TRADE_PARTY, ADDRESS, bridged])
        names = {c["name"] for c in pool}
        assert names == {"TradeParty", "TransportCall"}

    def test_a_missing_specialization_target_is_skipped_not_fabricated(self):
        anchor = _cls("TradeParty", ["legalName"], specializations=[{"name": "NotResolvable"}])
        pool = anchor_derived_class_pool("TradeParty", [anchor])
        assert [c["name"] for c in pool] == ["TradeParty"]

    def test_no_duplicates_when_a_class_is_both_bridge_and_specialization(self):
        shared = _cls("Consignee", ["x"], bridge_target_domain="customs")
        anchor = _cls("TradeParty", ["legalName"], specializations=[{"name": "Consignee"}])
        pool = anchor_derived_class_pool("TradeParty", [anchor, shared])
        assert [c["name"] for c in pool].count("Consignee") == 1

    def test_the_cap_is_respected_and_keeps_the_anchor(self):
        bridges = [
            _cls(f"Bridged{i}", ["x"], bridge_target_domain="other") for i in range(20)
        ]
        pool = anchor_derived_class_pool("TradeParty", [TRADE_PARTY] + bridges, max_classes=5)
        assert len(pool) == 5
        assert pool[0]["name"] == "TradeParty"

    def test_default_cap_matches_the_prompt_budget(self):
        bridges = [
            _cls(f"Bridged{i}", ["x"], bridge_target_domain="other") for i in range(40)
        ]
        pool = anchor_derived_class_pool("TradeParty", [TRADE_PARTY] + bridges)
        assert len(pool) == MAX_REF_CLASSES_PER_PROMPT

    def test_zero_or_negative_cap_means_uncapped(self):
        bridges = [_cls(f"B{i}", ["x"], bridge_target_domain="o") for i in range(30)]
        pool = anchor_derived_class_pool("TradeParty", [TRADE_PARTY] + bridges, max_classes=0)
        assert len(pool) == 31


class TestFallsBackRatherThanSendingAPoolWithoutTheAnchor:
    """An empty return is the signal to use the lexical path, not an error."""

    def test_unresolvable_anchor_returns_empty(self):
        assert anchor_derived_class_pool("NotInThisDomain", [ADDRESS, TRADE_PARTY]) == []

    def test_blank_anchor_returns_empty(self):
        for blank in ("", "   ", None):
            assert anchor_derived_class_pool(blank, [ADDRESS]) == []  # type: ignore[arg-type]

    def test_empty_ref_classes_returns_empty(self):
        assert anchor_derived_class_pool("TradeParty", []) == []

    def test_anchor_match_is_case_insensitive(self):
        """Anchors arrive as model output; case must not decide whether the pool works."""
        assert anchor_derived_class_pool("tradeparty", [TRADE_PARTY])[0]["name"] == "TradeParty"
        assert anchor_derived_class_pool("  TradeParty  ", [TRADE_PARTY])[0]["name"] == "TradeParty"

    def test_first_wins_on_a_duplicated_name(self):
        """Two modules can declare the same local name; pick one deterministically."""
        a = _cls("TradeParty", ["legalName"])
        b = dict(_cls("TradeParty", ["other"]), uri="https://elsewhere.test/ont#TradeParty")
        pool = anchor_derived_class_pool("TradeParty", [a, b])
        assert len(pool) == 1
        assert pool[0]["uri"] == a["uri"]


class TestTheRetryIsGatedOnTheAnchor:
    """A weak result on an anchored table is a gap signal, not a cue to widen."""

    def test_the_orchestrator_guards_the_retry_on_anchor_override(self):
        """Read the source: the guard has to be on the retry condition itself.

        Asserted structurally rather than behaviourally because reaching the retry needs
        a full LLM-backed run; the guard is one token and its absence is what shipped.
        """
        import inspect

        from kairos_ontology.core import propose_alignment

        src = inspect.getsource(propose_alignment)
        marker = "if not anchor_override and len(shortlist_classes) < len("
        assert marker in src, (
            "the full-inventory retry must be gated on anchor_override; without it an "
            "anchored table still widens to the whole ~1200-class inventory"
        )


# ---------------------------------------------------------------------------
# Integration: the orchestrator must actually send the derived pool
# ---------------------------------------------------------------------------
# The unit tests above prove the pool function. They cannot prove it is wired in,
# which is where the value is -- the function existing while the orchestrator still
# calls the scorer would look identical in a unit run.

import json
from unittest import mock

import pytest

import yaml

from kairos_ontology.core.propose_alignment import build_domain_alignments

DOMAIN_URI = "https://example.test/ont#"


def _hub(tmp_path, *, anchor: str | None, confidence: float = 0.95):
    analysis = tmp_path / "_analysis"
    analysis.mkdir()
    analysis.joinpath("alpha-affinity.yaml").write_text(
        yaml.safe_dump(
            {
                "system": "alpha",
                "schema_version": 2,
                "analysed_at": "2026-08-18T10:00:00Z",
                "model_used": "test-model",
                "tables": [
                    {
                        "table": "companies",
                        "total_columns": 1,
                        "domain": "party",
                        "domain_uris": [DOMAIN_URI],
                        "confidence": 0.9,
                        # Deliberately NOT the anchor: affinity's guess is the thing
                        # the anchored path is supposed to stop depending on.
                        "likely_entity": "Company",
                        "indicative_columns": ["billing_city"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    tables = []
    if anchor:
        tables = [
            {"system": "alpha", "table": "companies", "anchor": anchor, "confidence": confidence}
        ]
    analysis.joinpath("table-anchors.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "generated_by": "anchor-tables",
                "table_count": 1,
                "tables": tables,
                "unanchored": [],
                "excluded": [],
            }
        ),
        encoding="utf-8",
    )

    sources = tmp_path / "sources" / "alpha"
    sources.mkdir(parents=True)
    sources.joinpath("alpha.vocabulary.ttl").write_text(
        "@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .\n"
        '<#t0> a kairos-bronze:SourceTable ; kairos-bronze:tableName "companies" .\n'
        '<#c0> a kairos-bronze:SourceColumn ; kairos-bronze:columnName "billing_city" ;\n'
        '    kairos-bronze:dataType "nvarchar(50)" ; kairos-bronze:belongsToTable <#t0> .\n',
        encoding="utf-8",
    )
    return analysis, tmp_path / "sources"


# A property unique to the ADDRESS fixture. Asserting on the class *name* is useless:
# the prompt's static instructions include the example "hasBillingAddress -> Address"
# (propose_alignment.py:1977), so the word appears in every prompt ever built.
ADDRESS_ONLY_PROPERTY = "postalCode"


def _run_capturing_prompt(analysis, sources, *, without_anchors=False):
    """Run alignment and return the user prompt the model was sent."""
    prompts: list[str] = []

    def create_completion(*_a, **kw):
        prompts.append("\n".join(str(m.get("content", "")) for m in kw.get("messages", [])))
        payload = {
            "ref_class": "TradeParty",
            "ref_class_confidence": 0.9,
            "column_alignments": [],
        }
        return mock.MagicMock(
            choices=[mock.MagicMock(message=mock.MagicMock(content=json.dumps(payload)))]
        )

    client = mock.MagicMock()
    client.chat.completions.create = create_completion
    with (
        mock.patch("kairos_ontology.core.propose_alignment.get_ai_client", return_value=client),
        mock.patch("kairos_ontology.core.propose_alignment.require_ai_provider"),
        mock.patch(
            "kairos_ontology.core.propose_alignment.extract_ref_model_inventory",
            return_value=[ADDRESS, TRADE_PARTY],
        ),
    ):
        build_domain_alignments(
            analysis_dir=analysis,
            sources_dir=sources,
            catalog_path=None,
            without_anchors=without_anchors,
        )
    assert prompts, "the model was never called"
    return prompts[0]


class TestOrchestratorUsesTheDerivedPool:
    def test_an_anchored_table_is_not_offered_the_lexically_dominant_class(self, tmp_path):
        analysis, sources = _hub(tmp_path, anchor="TradeParty")
        prompt = _run_capturing_prompt(analysis, sources)
        assert "TradeParty" in prompt
        assert ADDRESS_ONLY_PROPERTY not in prompt, (
            "the Address class reached the prompt, so the pool is still lexically scored"
        )

    def test_an_unanchored_table_keeps_the_lexical_path(self, tmp_path):
        """The fallback must be untouched: Address is offered again, as before.

        Needs the opt-out because an artifact with no anchored tables is exactly what the
        5.11.0 precondition refuses -- which is itself worth asserting here.
        """
        analysis, sources = _hub(tmp_path, anchor=None)
        with pytest.raises(ValueError, match="Refusing to align without global table anchors"):
            _run_capturing_prompt(analysis, sources)
        prompt = _run_capturing_prompt(analysis, sources, without_anchors=True)
        assert ADDRESS_ONLY_PROPERTY in prompt

    def test_a_low_confidence_anchor_does_not_derive_the_pool(self, tmp_path):
        """Below ANCHOR_CONFIDENCE_FLOOR the anchor is advisory, so the pool is scored."""
        analysis, sources = _hub(tmp_path, anchor="TradeParty", confidence=0.2)
        prompt = _run_capturing_prompt(analysis, sources)
        assert ADDRESS_ONLY_PROPERTY in prompt

    def test_an_anchor_outside_the_domain_pool_falls_back(self, tmp_path):
        """anchor-tables works against the full catalog; a domain may not hold the class."""
        analysis, sources = _hub(tmp_path, anchor="TransportCall")
        prompt = _run_capturing_prompt(analysis, sources)
        assert ADDRESS_ONLY_PROPERTY in prompt
