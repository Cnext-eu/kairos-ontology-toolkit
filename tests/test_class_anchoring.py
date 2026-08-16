# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Reference-model anchor suggestions (DD-165)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kairos_ontology.core.class_anchoring import (
    AUTO_ANCHOR_SCORE,
    SCORE_FLOOR,
    ReferenceTerm,
    rank_candidates,
    read_reference_terms,
    score_anchor,
    suggest_anchors,
)

MMT = "https://www.kairosflow.ai/ont/mmt/party"
BSP = "https://www.kairosflow.ai/ont/bsp/party"


def _term(name: str, module: str = BSP, kind: str = "class", label: str = "") -> ReferenceTerm:
    return ReferenceTerm(
        uri=f"{module}#{name}", name=name, label=label, comment="", module=module, kind=kind
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("local", "candidate", "expected"),
    [
        ("Contact", "Contact", 1.0),
        ("contact", "Contact", 0.95),
        ("Contacts", "Contact", 0.9),
        ("Party", "TransportParty", 0.8),
        ("companyRegistrationNumber", "registrationNumber", 0.8),
    ],
)
def test_score_anchor_recognised_shapes(local: str, candidate: str, expected: float) -> None:
    score, reason = score_anchor(local, _term(candidate))
    assert score == pytest.approx(expected)
    assert reason


@pytest.mark.parametrize(
    ("local", "candidate"),
    [
        # A shared head noun is the commonest way two unrelated terms look alike.
        # Scoring it produced companyBillingPostalCode -> companyCode.
        ("companyBillingPostalCode", "companyCode"),
        ("companyLegalName", "contactName"),
        ("companyEoriNumber", "imoCompanyNumber"),
        ("Booking", "Invoice"),
    ],
)
def test_score_anchor_rejects_coincidental_similarity(local: str, candidate: str) -> None:
    score, _ = score_anchor(local, _term(candidate))
    assert score < SCORE_FLOOR


def test_label_match_is_used_when_the_name_alone_says_nothing() -> None:
    """Abbreviated reference names ("TCall") only match through their label."""
    score, reason = score_anchor("TransportCall", _term("TCall", label="Transport Call"))
    assert SCORE_FLOOR <= score < AUTO_ANCHOR_SCORE
    assert "label" in reason


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def test_kind_is_never_crossed() -> None:
    pool = [_term("contactEmail", kind="property")]
    assert rank_candidates("contactEmail", "class", pool) == ()
    assert rank_candidates("contactEmail", "property", pool)


def test_archetype_tier_breaks_a_tie_between_same_named_siblings() -> None:
    """Regression: eight classes end in 'Party' and score identically on name.

    Without the tier signal the alphabetical cut dropped TransportParty -- the class the
    archetype marks required -- in favour of deprecated role overlays.
    """
    pool = [
        _term("NotifyParty", module=MMT),
        _term("MaritimeParty"),
        _term("TransportParty", module=MMT),
    ]
    tiers = {f"{MMT}#TransportParty": "required", f"{MMT}#NotifyParty": "optional"}

    ranked = rank_candidates("Party", "class", pool, tiers)

    assert ranked[0].name == "TransportParty"
    assert "required" in ranked[0].reason


def test_tier_boost_never_overturns_stronger_name_evidence() -> None:
    pool = [_term("Contact"), _term("TransportContact", module=MMT)]
    tiers = {f"{MMT}#TransportContact": "required"}
    ranked = rank_candidates("Contact", "class", pool, tiers)
    assert ranked[0].name == "Contact"


def test_grain_collision_is_annotated_but_still_ranked_on_evidence() -> None:
    """The caution belongs in the annotation, not in the ordering."""
    pool = [_term("TransportParty", module=MMT), _term("NotifyParty", module=MMT)]
    tiers = {f"{MMT}#TransportParty": "required"}
    ranked = rank_candidates("Party", "class", pool, tiers)
    assert ranked[0].name == "TransportParty"
    assert "grain collision" in ranked[0].caution
    assert not ranked[1].caution


# ---------------------------------------------------------------------------
# Inventory reading
# ---------------------------------------------------------------------------


def _write_inventory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "bsp-party-inventory.yaml").write_text(
        yaml.safe_dump(
            {
                "classes": [
                    {
                        "uri": f"{BSP}#Contact",
                        "name": "Contact",
                        "label": "Contact",
                        "properties": [
                            {"uri": f"{BSP}#contactEmail", "name": "contactEmail"},
                            # Inherited entries repeat a parent's property and would
                            # attribute it to the wrong module.
                            {
                                "uri": f"{MMT}#partyName",
                                "name": "partyName",
                                "inherited": True,
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_read_reference_terms_skips_inherited_properties(tmp_path: Path) -> None:
    _write_inventory(tmp_path)
    names = {(t.name, t.kind) for t in read_reference_terms(tmp_path)}
    assert ("Contact", "class") in names
    assert ("contactEmail", "property") in names
    assert ("partyName", "property") not in names


def test_read_reference_terms_without_inventories_is_empty(tmp_path: Path) -> None:
    assert read_reference_terms(tmp_path / "nope") == []


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------


def _write_domain(directory: Path, *, body: str, imports: tuple[str, ...]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    joined = " ,\n        ".join(f"<{i}>" for i in imports)
    (directory / "party.ttl").write_text(
        "@prefix : <https://example.com/ont/party#> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n\n"
        "<https://example.com/ont/party> a owl:Ontology ;\n"
        '    rdfs:label "party"@en ;\n'
        '    owl:versionInfo "1.0.0" ;\n'
        f"    owl:imports {joined} .\n\n" + body,
        encoding="utf-8",
    )


def test_suggest_anchors_offers_a_paste_ready_line_for_an_exact_match(tmp_path: Path) -> None:
    onto, inv = tmp_path / "ontologies", tmp_path / "inventories"
    _write_inventory(inv)
    _write_domain(
        onto,
        body=':Contact a owl:Class ;\n    rdfs:label "Contact"@en ;\n'
        '    rdfs:comment "A contact."@en .\n',
        imports=(BSP,),
    )

    report = suggest_anchors(ontologies_dir=onto, domain="party", inventory_dir=inv)

    assert report.unanchored == 1
    assert len(report.confident) == 1
    assert report.confident[0].turtle_line() == f"rdfs:subClassOf <{BSP}#Contact> ;"


def test_suggest_anchors_withholds_turtle_for_a_weak_match(tmp_path: Path) -> None:
    onto, inv = tmp_path / "ontologies", tmp_path / "inventories"
    _write_inventory(inv)
    _write_domain(
        onto,
        body=':BusinessContact a owl:Class ;\n    rdfs:label "Business Contact"@en ;\n'
        '    rdfs:comment "A contact."@en .\n',
        imports=(BSP,),
    )

    report = suggest_anchors(ontologies_dir=onto, domain="party", inventory_dir=inv)

    suggestion = report.suggestions[0]
    assert suggestion.candidates and not suggestion.confident
    assert suggestion.turtle_line().startswith("#")
    assert "choose deliberately" in suggestion.turtle_line()


def test_suggest_anchors_ignores_modules_the_domain_does_not_import(tmp_path: Path) -> None:
    """An anchor into an unimported module would fail the managed-import check."""
    onto, inv = tmp_path / "ontologies", tmp_path / "inventories"
    _write_inventory(inv)
    _write_domain(
        onto,
        body=':Contact a owl:Class ;\n    rdfs:label "Contact"@en ;\n'
        '    rdfs:comment "A contact."@en .\n',
        imports=("https://www.kairosflow.ai/ont/imo/party",),
    )

    report = suggest_anchors(ontologies_dir=onto, domain="party", inventory_dir=inv)

    assert report.suggestions == []
    assert any("materialized inventory" in n for n in report.notices)


def test_already_anchored_terms_are_counted_not_resuggested(tmp_path: Path) -> None:
    onto, inv = tmp_path / "ontologies", tmp_path / "inventories"
    _write_inventory(inv)
    _write_domain(
        onto,
        body=':Contact a owl:Class ;\n    rdfs:label "Contact"@en ;\n'
        '    rdfs:comment "A contact."@en ;\n'
        f"    rdfs:subClassOf <{BSP}#Contact> .\n",
        imports=(BSP,),
    )

    report = suggest_anchors(ontologies_dir=onto, domain="party", inventory_dir=inv)

    assert report.already_anchored == 1
    assert report.unanchored == 0


def test_missing_domain_and_missing_inventories_report_notices(tmp_path: Path) -> None:
    absent = suggest_anchors(ontologies_dir=tmp_path, domain="nope", inventory_dir=tmp_path)
    assert absent.notices and not absent.suggestions

    onto = tmp_path / "ontologies"
    _write_domain(onto, body="", imports=(BSP,))
    no_inv = suggest_anchors(ontologies_dir=onto, domain="party", inventory_dir=tmp_path / "nope")
    assert any("generate-inventory" in n for n in no_inv.notices)
