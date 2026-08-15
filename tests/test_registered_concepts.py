# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Hub-side registration of source-discovered concepts (issue #505, Layer B)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kairos_ontology.core.registered_concepts import (
    REGISTERED_RELPATH,
    RegisteredConceptError,
    read_registered,
    register_concept,
    registered_open_questions,
    validate_registered,
    write_registered,
)

_URI = "https://acme.example/ont/logistics#PlanningZone"
_CATALOG_URI = "https://example.org/ont/booking#Booking"


def _register(hub: Path, **overrides):
    kwargs = {
        "uri": _URI,
        "label": "Planning Zone",
        "source_system": "qlik",
        "source_evidence": ["planning_zones", "zone_assignments"],
        "rationale": "Qlik reports scope capacity by zone; 1000 rows across 2 tables.",
        "likely_domains": ["logistics"],
    }
    kwargs.update(overrides)
    return register_concept(hub, **kwargs)


# ---------------------------------------------------------------------------
# register_concept
# ---------------------------------------------------------------------------


def test_registration_writes_a_versioned_artifact(tmp_path: Path) -> None:
    path, entry = _register(tmp_path)

    assert path == tmp_path / REGISTERED_RELPATH
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert [c["uri"] for c in document["concepts"]] == [_URI]
    assert entry.tier == "optional"
    assert entry.source_evidence == ("planning_zones", "zone_assignments")
    assert entry.registered_at


def test_registered_tier_is_always_optional(tmp_path: Path) -> None:
    """The source data argued this concept in; no blueprint recommended it."""
    _, entry = _register(tmp_path)

    assert entry.tier == "optional"
    assert validate_registered([{**entry.to_dict(), "tier": "required"}])


def test_a_catalog_concept_cannot_be_registered(tmp_path: Path) -> None:
    """Registering one would route it around the archetype coverage checks entirely."""
    with pytest.raises(RegisteredConceptError, match="already a core concept"):
        _register(tmp_path, uri=_CATALOG_URI, catalog_uris=[_CATALOG_URI])


def test_a_non_concept_uri_is_rejected(tmp_path: Path) -> None:
    for bad in ("PlanningZone", "https://acme.example/", "ftp://acme.example/ont#Zone", ""):
        with pytest.raises(RegisteredConceptError):
            _register(tmp_path, uri=bad)


def test_re_registration_requires_force(tmp_path: Path) -> None:
    """A second run must not silently overwrite a human's recorded rationale."""
    _register(tmp_path)

    with pytest.raises(RegisteredConceptError, match="already registered"):
        _register(tmp_path, rationale="Different reason.")

    _, entry = _register(tmp_path, rationale="Different reason.", force=True)
    assert entry.rationale == "Different reason."
    assert len(read_registered(tmp_path)) == 1


def test_several_registrations_accumulate_and_stay_sorted(tmp_path: Path) -> None:
    _register(tmp_path, uri="https://acme.example/ont/logistics#TariffScale", label="Tariff")
    _register(tmp_path)

    assert [c["uri"] for c in read_registered(tmp_path)] == [
        _URI,
        "https://acme.example/ont/logistics#TariffScale",
    ]


def test_evidence_and_rationale_are_both_mandatory(tmp_path: Path) -> None:
    """Registration is a claim about source data; unevidenced or unexplained, it is a guess."""
    with pytest.raises(RegisteredConceptError, match="source_evidence"):
        _register(tmp_path, source_evidence=[])
    with pytest.raises(RegisteredConceptError, match="rationale"):
        _register(tmp_path, rationale="   ")


def test_bad_decided_by_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RegisteredConceptError, match="decided-by"):
        _register(tmp_path, decided_by="robot")


# ---------------------------------------------------------------------------
# read / validate
# ---------------------------------------------------------------------------


def test_absent_file_is_empty_not_an_error(tmp_path: Path) -> None:
    assert read_registered(tmp_path) == []


def test_a_malformed_file_raises_rather_than_silently_erasing_registrations(
    tmp_path: Path,
) -> None:
    path = tmp_path / REGISTERED_RELPATH
    path.parent.mkdir(parents=True)
    path.write_text("{[", encoding="utf-8")

    with pytest.raises(RegisteredConceptError):
        read_registered(tmp_path)


def test_an_unknown_schema_version_raises(tmp_path: Path) -> None:
    path = write_registered(tmp_path, [])
    path.write_text(
        yaml.safe_dump({"schema_version": 99, "concepts": []}), encoding="utf-8"
    )

    with pytest.raises(RegisteredConceptError, match="schema_version"):
        read_registered(tmp_path)


def test_validate_reports_duplicates_and_bad_confidence() -> None:
    base = {
        "uri": _URI,
        "label": "Planning Zone",
        "tier": "optional",
        "rationale": "why",
        "source_evidence": ["t"],
    }
    errors = validate_registered([base, {**base, "confidence": 1.5}])

    assert any("duplicate registration" in e for e in errors)
    assert any("confidence" in e for e in errors)


# ---------------------------------------------------------------------------
# DD-148 gating
# ---------------------------------------------------------------------------


def test_ai_registration_without_confidence_is_an_open_question(tmp_path: Path) -> None:
    """Adding a concept the blueprint omitted is a larger authority than judging one it had."""
    _, entry = _register(tmp_path, decided_by="ai")

    questions = registered_open_questions([entry.to_dict()])
    assert len(questions) == 1
    assert questions[0]["reason"] == "missing confidence"
    assert questions[0]["registered"] is True


def test_ai_registration_with_confidence_is_resolved(tmp_path: Path) -> None:
    _, entry = _register(tmp_path, decided_by="ai", confidence=0.9)

    assert registered_open_questions([entry.to_dict()]) == []


def test_needs_confirmation_reopens_a_confident_registration(tmp_path: Path) -> None:
    _, entry = _register(tmp_path, decided_by="ai", confidence=0.9, needs_confirmation=True)

    assert registered_open_questions([entry.to_dict()])[0]["reason"] == "needs_confirmation"


def test_a_user_registration_is_never_an_open_question(tmp_path: Path) -> None:
    _, entry = _register(tmp_path, decided_by="user")

    assert registered_open_questions([entry.to_dict()]) == []


def test_domain_scoping_matches_open_questions_semantics(tmp_path: Path) -> None:
    _, tagged = _register(tmp_path, decided_by="ai", likely_domains=["logistics"])
    _, cross = _register(
        tmp_path,
        uri="https://acme.example/ont/logistics#Zone2",
        decided_by="ai",
        likely_domains=[],
        force=True,
    )

    assert registered_open_questions([tagged.to_dict()], domains=["finance"]) == []
    assert registered_open_questions([tagged.to_dict()], domains=["logistics"])
    # Untagged means cross-cutting -- in scope for every domain, the safe default.
    assert registered_open_questions([cross.to_dict()], domains=["finance"])
