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


def _published_tier_enum() -> list[str]:
    schema_path = (
        REFMODELS_ROOT
        / "ontology-reference-models"
        / "blueprints"
        / "archetypes"
        / "_schema"
        / "archetype.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return schema["$defs"]["tier"]["enum"]


def test_load_valid_tiers_resolves_the_published_enum() -> None:
    """The published ``$defs/tier`` enum is authoritative and must resolve exactly.

    Supersedes the original form of this test (#275), which asserted ``VALID_TIERS ==``
    the published enum. That equality was the right alarm while the enum was hardcoded, but
    it is now a false alarm: ``load_valid_tiers`` reads the published enum at runtime, so a
    tier *added* upstream (e.g. the proposed ``not_applicable``) is handled with no toolkit
    release and must not fail CI here.
    """
    assert list(archetype_loader.load_valid_tiers(REFMODELS_ROOT)) == _published_tier_enum()


def test_fallback_tiers_never_outlive_the_published_enum() -> None:
    """The offline fallback may lag the published enum, but must never exceed it.

    A tier *added* upstream is fine — we resolve it at runtime. A tier *removed* upstream
    while it lingers in :data:`VALID_TIERS` is a real bug: offline, we would keep accepting
    a retired tier. Subset, not equality, is the correct assertion after #276 Q4.
    """
    published = set(_published_tier_enum())
    stale = sorted(set(archetype_loader.VALID_TIERS) - published)
    assert not stale, (
        f"VALID_TIERS still lists tier(s) the published schema has dropped: {stale}. "
        "Offline validation would accept a retired tier — update the fallback constant."
    )


def test_discovery_outcome_groupings_exist_in_the_published_enum() -> None:
    """``design_landscape``'s semantic groupings are hardcoded against literal codes.

    ``load_outcome_codes`` deliberately never hardcodes the *list*, but the *semantics* built
    on top of it (``CONFIRMED_DISCOVERY_OUTCOMES`` / ``NON_EVIDENCE_DISCOVERY_OUTCOMES``, DD-090)
    are literals with no contract test. A published rename would leave them silently matching
    nothing — a class quietly losing its confirmed-demand evidence, with green CI. This is the
    companion to the tier check above.
    """
    from kairos_ontology.core import design_landscape

    published = set(archetype_loader.load_outcome_codes(REFMODELS_ROOT))
    grouped = (
        design_landscape.CONFIRMED_DISCOVERY_OUTCOMES
        | design_landscape.NON_EVIDENCE_DISCOVERY_OUTCOMES
    )
    missing = sorted(grouped - published)
    assert not missing, (
        f"design_landscape groups outcome code(s) absent from the published enum: {missing}. "
        "A rename in outcome-codes.yaml needs a coordinated change in design_landscape.py."
    )


def test_ontology_tier_prefixes_still_match_the_published_layout() -> None:
    """``classify_ontology_tier`` reads a directory layout that is *not* in the contract.

    Tier is derived from the path the catalog resolves a module to, because reference-models
    publishes no explicit tier field (#276 Q3). That makes it a heuristic: a reorganisation
    would silently degrade every module to ``unknown`` and quietly disable the blueprint drift
    warning. This test fails instead, and is the evidence behind the ask for an explicit tier
    declaration.
    """
    from kairos_ontology.core.archetype_topology import (
        UNKNOWN_ONTOLOGY_TIER,
        classify_ontology_tier,
    )

    inner = REFMODELS_ROOT / "ontology-reference-models"
    expected = {
        "blueprints/ontology": "blueprint",
        "derived-ontologies": "derived",
        "authoritative-ontologies": "authoritative",
    }
    for relpath, tier in expected.items():
        directory = inner / relpath
        assert directory.is_dir(), f"published layout no longer has {relpath}/"
        assert classify_ontology_tier(directory / "any.ttl", REFMODELS_ROOT) == tier

    # And a real archetype must actually resolve its blueprint module to that tier.
    archetype = archetype_loader.load_archetype(REFMODELS_ROOT, "freight-forwarder")
    from kairos_ontology.core.archetype_topology import derive_archetype_topology

    tiers = derive_archetype_topology(REFMODELS_ROOT, archetype).module_tiers
    assert "blueprint" in tiers.values(), (
        "freight-forwarder declares a blueprint module but none classified as blueprint"
    )
    assert UNKNOWN_ONTOLOGY_TIER not in tiers.values(), (
        f"published modules resolved outside every known tier prefix: "
        f"{sorted(iri for iri, t in tiers.items() if t == UNKNOWN_ONTOLOGY_TIER)}"
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
    valid_tiers = archetype_loader.load_valid_tiers(REFMODELS_ROOT)
    for archetype_id in ids:
        catalog = archetype_loader.load_archetype(REFMODELS_ROOT, archetype_id)
        assert catalog.core_concepts, f"{archetype_id}: no core concepts resolved"
        for concept in catalog.core_concepts:
            assert concept.tier in valid_tiers
