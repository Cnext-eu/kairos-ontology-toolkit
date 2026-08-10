# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Cross-repo contract tests: our loaders, run against a real reference-models checkout.

Every other test of the loaders in this repo uses synthetic fixtures
(``tests/archetype_fixtures.py``). Fixtures prove the loaders behave correctly given a
well-formed input; they cannot prove that what
``kairos-ontology-referencemodels`` actually publishes *is* well-formed.

Why this file exists
--------------------
``blueprints/patterns/temporal-quartet/pattern.yaml`` shipped in reference-models v1.13.0
as invalid YAML and stayed broken for two minor versions. Nothing here misbehaved:
:func:`load_patterns` returned a warning and ``kairos-ontology list-patterns`` printed it
to stderr, exactly as designed. It survived because no test in either repo ever pointed a
loader at a real checkout, so the library's only *normative* naming pattern was absent
from the ``kairos-design-domain`` flow and both CIs stayed green.

The mirror of this file lives in the reference-models repo at
``tests/test_toolkit_contract.py``.

Skipping
--------
Skipped when no reference-models checkout is on the machine, so CI here keeps no
cross-repo dependency. Set ``KAIROS_REFMODELS_ROOT`` to point at one; otherwise the
sibling ``../kairos-ontology-referencemodels`` is probed. Local-only: nothing here
fetches over the network.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from kairos_ontology.core import archetype_loader, pattern_loader

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: Marker files that identify a reference-models checkout root (mirrors the contract
#: markers ``archetype_loader`` itself probes for).
_MARKERS = (
    Path("ontology-reference-models") / "catalog-v001.xml",
    Path("ontology-reference-models") / "blueprints" / "archetypes",
)


def _refmodels_root() -> Path | None:
    """Return a reference-models repo root, or None when none is available."""
    override = os.environ.get("KAIROS_REFMODELS_ROOT")
    candidates = [Path(override)] if override else []
    candidates.append(_REPO_ROOT.parent / "kairos-ontology-referencemodels")
    for candidate in candidates:
        if all((candidate / marker).exists() for marker in _MARKERS):
            return candidate
    return None


REFMODELS_ROOT = _refmodels_root()

pytestmark = pytest.mark.skipif(
    REFMODELS_ROOT is None,
    reason=(
        "no kairos-ontology-referencemodels checkout found — set KAIROS_REFMODELS_ROOT or "
        "place one at ../kairos-ontology-referencemodels"
    ),
)


def test_every_published_pattern_loads() -> None:
    """The regression test for the reference-models v1.13.0 defect.

    :func:`load_pattern` is the fail-fast path, so an unparseable published
    ``pattern.yaml`` becomes a red build here instead of a pattern that silently never
    reaches the design flow.
    """
    ids = pattern_loader.list_patterns(REFMODELS_ROOT)
    assert ids, f"no patterns found under {REFMODELS_ROOT} — is this a reference-models root?"
    for pattern_id in ids:
        pattern = pattern_loader.load_pattern(REFMODELS_ROOT, pattern_id)
        assert pattern.id == pattern_id


def test_bulk_load_of_published_patterns_warns_about_nothing() -> None:
    """Leniency is correct behaviour and a useless signal — assert it has nothing to say.

    :func:`load_patterns` degrades gracefully so advisory surfacing never breaks the
    design loop. That is right for a caller and wrong as a quality gate: a skipped
    pattern is an absent pattern. A published library should produce no warnings at all.
    """
    patterns, warnings = pattern_loader.load_patterns(REFMODELS_ROOT)
    assert warnings == [], f"published patterns were skipped: {warnings}"
    assert len(patterns) == len(pattern_loader.list_patterns(REFMODELS_ROOT))


def test_normative_patterns_expose_naming_conventions() -> None:
    """A pattern claiming normative naming must actually carry the conventions.

    ``temporal-quartet`` declared ``normativity.naming: normative`` throughout the period
    its file could not be parsed — the claim and the payload were independently
    plausible and jointly useless.
    """
    for pattern in pattern_loader.load_patterns(REFMODELS_ROOT)[0]:
        if pattern.normativity.get("naming") == "normative":
            assert pattern.naming_conventions, (
                f"{pattern.id}: declares normative naming but exposes no naming_conventions"
            )


def test_valid_tiers_matches_the_published_schema() -> None:
    """``VALID_TIERS`` is our copy of the published ``$defs/tier`` enum.

    The duplication is deliberate (the loader must validate without reaching for the
    schema on every call) but was unenforced, so a tier added on the publishing side —
    e.g. the proposed ``not_applicable`` — would break us at the next ref-model bump with
    no warning. This test makes the two repos disagree loudly and at the right moment.
    """
    schema_path = (
        REFMODELS_ROOT
        / "ontology-reference-models"
        / "blueprints"
        / "archetypes"
        / "_schema"
        / "archetype.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    published_tiers = schema["$defs"]["tier"]["enum"]
    assert sorted(archetype_loader.VALID_TIERS) == sorted(published_tiers), (
        "VALID_TIERS has diverged from the published archetype.schema.json $defs/tier — "
        "a tier change requires a coordinated PR in both repos"
    )


def test_every_published_archetype_loads() -> None:
    """Published catalogs must survive our schema validation and URI resolution."""
    archetypes_dir = (
        REFMODELS_ROOT / "ontology-reference-models" / "blueprints" / "archetypes"
    )
    ids = sorted(
        path.stem for path in archetypes_dir.glob("*.yaml") if not path.name.startswith(".")
    )
    assert ids, "no archetype catalogs found"
    for archetype_id in ids:
        catalog = archetype_loader.load_archetype(REFMODELS_ROOT, archetype_id)
        assert catalog.core_concepts, f"{archetype_id}: no core concepts resolved"
        for concept in catalog.core_concepts:
            assert concept.tier in archetype_loader.VALID_TIERS
