# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Concept-level source evidence for discovery judgments (issue #507)."""

from __future__ import annotations

from pathlib import Path

import yaml

from kairos_ontology.core.conformance_artifact import (
    advise_artifact,
    data_driven_build_errors,
)
from kairos_ontology.core.conformance_evidence import (
    KIND_AFFINITY,
    KIND_ALIGNMENT,
    collect_concept_source_evidence,
    concept_domains_from_outcomes,
)

_BOOKING = "https://example.org/ont/booking#Booking"
_GHOST = "https://example.org/ont/booking#GhostConcept"
_URIS = (_BOOKING, _GHOST, "https://example.org/ont/party#BookingParty")


def _analysis_dir(hub: Path) -> Path:
    path = hub / "integration" / "sources" / "_analysis"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_alignment(hub: Path, *tables: dict, domain: str = "logistics") -> None:
    _analysis_dir(hub).joinpath(f"{domain}-alignment.yaml").write_text(
        yaml.safe_dump({"domain": domain, "tables": list(tables)}, sort_keys=False),
        encoding="utf-8",
    )


def _write_affinity(hub: Path, system: str, *tables: dict) -> None:
    _analysis_dir(hub).joinpath(f"{system}-affinity.yaml").write_text(
        yaml.safe_dump(
            {"schema_version": 2, "system": system, "tables": list(tables)}, sort_keys=False
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Alignment evidence -- the direct, concept-level signal
# ---------------------------------------------------------------------------


def test_bare_ref_class_local_name_matches_a_concept_uri(tmp_path: Path) -> None:
    """`ref_class` is usually a bare local name, not a URI -- matching must handle that."""
    _write_alignment(tmp_path, {"system": "qargo", "table": "bookings", "ref_class": "Booking"})

    evidence = collect_concept_source_evidence(_URIS, tmp_path)

    assert set(evidence) == {_BOOKING}
    assert evidence[_BOOKING].kind == KIND_ALIGNMENT
    assert evidence[_BOOKING].tables == ("qargo.bookings",)


def test_full_uri_ref_class_matches_exactly(tmp_path: Path) -> None:
    _write_alignment(tmp_path, {"system": "qargo", "table": "bookings", "ref_class": _BOOKING})

    assert set(collect_concept_source_evidence(_URIS, tmp_path)) == {_BOOKING}


def test_likely_entity_uri_is_preferred_over_ref_class(tmp_path: Path) -> None:
    _write_alignment(
        tmp_path,
        {
            "system": "qargo",
            "table": "bookings",
            "ref_class": "Booking",
            "likely_entity_uri": _GHOST,
        },
    )

    assert set(collect_concept_source_evidence(_URIS, tmp_path)) == {_GHOST}


def test_class_outside_the_concept_set_yields_no_evidence(tmp_path: Path) -> None:
    _write_alignment(tmp_path, {"system": "qargo", "table": "x", "ref_class": "SomethingElse"})

    assert collect_concept_source_evidence(_URIS, tmp_path) == {}


def test_ambiguous_local_name_is_skipped_not_guessed(tmp_path: Path) -> None:
    """Picking one of two same-named concepts would put fabricated evidence in a review."""
    uris = ("https://a.example/ont#Booking", "https://b.example/ont#Booking")
    _write_alignment(tmp_path, {"system": "qargo", "table": "bookings", "ref_class": "Booking"})

    assert collect_concept_source_evidence(uris, tmp_path) == {}


def test_tables_across_several_alignment_files_accumulate(tmp_path: Path) -> None:
    _write_alignment(
        tmp_path, {"system": "qargo", "table": "bookings", "ref_class": "Booking"}, domain="a"
    )
    _write_alignment(
        tmp_path, {"system": "qlik", "table": "orders", "ref_class": "Booking"}, domain="b"
    )

    assert collect_concept_source_evidence(_URIS, tmp_path)[_BOOKING].tables == (
        "qargo.bookings",
        "qlik.orders",
    )


def test_missing_or_corrupt_analysis_never_raises(tmp_path: Path) -> None:
    assert collect_concept_source_evidence(_URIS, tmp_path) == {}
    _analysis_dir(tmp_path).joinpath("broken-alignment.yaml").write_text("{[", encoding="utf-8")
    assert collect_concept_source_evidence(_URIS, tmp_path) == {}


# ---------------------------------------------------------------------------
# Affinity evidence -- the weaker, domain-mediated signal
# ---------------------------------------------------------------------------


def test_affinity_evidence_requires_a_likely_domains_tag(tmp_path: Path) -> None:
    _write_affinity(tmp_path, "qargo", {"table": "charges", "domain": "cost-accounting"})

    assert collect_concept_source_evidence(_URIS, tmp_path) == {}

    evidence = collect_concept_source_evidence(
        _URIS, tmp_path, concept_domains={_GHOST: ["cost-accounting"]}
    )
    assert evidence[_GHOST].kind == KIND_AFFINITY
    assert evidence[_GHOST].tables == ("qargo.charges",)
    assert evidence[_GHOST].domains == ("cost-accounting",)


def test_cross_cutting_concept_gets_no_affinity_evidence(tmp_path: Path) -> None:
    """An empty likely_domains means cross-cutting; matching every domain would fabricate it."""
    _write_affinity(tmp_path, "qargo", {"table": "charges", "domain": "cost-accounting"})

    assert collect_concept_source_evidence(_URIS, tmp_path, concept_domains={_GHOST: []}) == {}


def test_secondary_domains_count_as_affinity(tmp_path: Path) -> None:
    _write_affinity(
        tmp_path,
        "qargo",
        {"table": "charges", "domain": "finance", "secondary_domains": [{"domain": "revenue"}]},
    )

    evidence = collect_concept_source_evidence(
        _URIS, tmp_path, concept_domains={_GHOST: ["revenue"]}
    )
    assert evidence[_GHOST].tables == ("qargo.charges",)


def test_alignment_wins_over_affinity_for_the_same_concept(tmp_path: Path) -> None:
    _write_alignment(tmp_path, {"system": "qargo", "table": "ghosts", "ref_class": "GhostConcept"})
    _write_affinity(tmp_path, "qlik", {"table": "other", "domain": "logistics"})

    evidence = collect_concept_source_evidence(
        _URIS, tmp_path, concept_domains={_GHOST: ["logistics"]}
    )
    assert evidence[_GHOST].kind == KIND_ALIGNMENT
    assert evidence[_GHOST].tables == ("qargo.ghosts",)


def test_concept_domains_from_outcomes_projects_only_usable_entries() -> None:
    assert concept_domains_from_outcomes(
        [
            {"uri": _GHOST, "likely_domains": ["finance", " ", "ops"]},
            {"uri": _BOOKING, "likely_domains": None},
            {"likely_domains": ["x"]},
            "not a mapping",
        ]
    ) == {_GHOST: ["finance", "ops"]}


def test_describe_names_real_tables_not_a_bare_count(tmp_path: Path) -> None:
    """A warning the reviewer cannot act on is a warning they will ignore."""
    _write_alignment(tmp_path, {"system": "qargo", "table": "bookings", "ref_class": "Booking"})

    assert "qargo.bookings" in collect_concept_source_evidence(_URIS, tmp_path)[_BOOKING].describe()


# ---------------------------------------------------------------------------
# advise_artifact / data_driven_build_errors
# ---------------------------------------------------------------------------


def _artifact(outcome: str, *, tier: str = "optional", rationale: str = "") -> dict:
    return {
        "core_concepts": [
            {
                "uri": _GHOST,
                "label": "Ghost",
                "tier": tier,
                "outcome": outcome,
                "rationale": rationale,
            }
        ]
    }


def _evidence(tmp_path: Path) -> dict:
    _write_alignment(tmp_path, {"system": "qargo", "table": "ghosts", "ref_class": "GhostConcept"})
    return collect_concept_source_evidence(_URIS, tmp_path)


def test_contradicted_optional_not_applicable_is_advised(tmp_path: Path) -> None:
    warnings = advise_artifact(_artifact("not-applicable"), _evidence(tmp_path))

    assert len(warnings) == 1
    assert "Ghost" in warnings[0] and "qargo.ghosts" in warnings[0]


def test_required_tier_is_not_advised(tmp_path: Path) -> None:
    """A required concept is in scope regardless of what the sources contain."""
    assert advise_artifact(_artifact("not-applicable", tier="required"), _evidence(tmp_path)) == []


def test_other_outcomes_are_not_advised(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    for outcome in ("conforms", "partial", "deviates", "conforms-with-rename"):
        assert advise_artifact(_artifact(outcome), evidence) == []


def test_no_evidence_means_no_advisory(tmp_path: Path) -> None:
    assert advise_artifact(_artifact("not-applicable"), {}) == []
    assert advise_artifact(_artifact("not-applicable"), None) == []


def test_build_errors_require_a_real_rationale(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    concepts = _artifact("not-applicable")["core_concepts"]

    assert data_driven_build_errors(concepts, evidence)

    concepts[0]["rationale"] = "Road-only carrier; the concept is rail-specific."
    assert data_driven_build_errors(concepts, evidence) == []


def test_a_scaffold_sentinel_rationale_does_not_satisfy_the_gate(tmp_path: Path) -> None:
    """An unedited `<CONFIRM_RATIONALE>` is the absence of a decision, not a decision."""
    concepts = _artifact("not-applicable", rationale="<CONFIRM_RATIONALE>")["core_concepts"]

    assert data_driven_build_errors(concepts, _evidence(tmp_path))
