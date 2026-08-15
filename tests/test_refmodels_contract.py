# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Cross-repo contract tests: our loaders, run against real reference models.

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

Resolution
----------
Reference models are resolved from the installed ``kairos-ontology-referencemodels``
package first (the default in CI where it's a dev dependency).  Set
``KAIROS_REFMODELS_ROOT`` to point at a local checkout instead; otherwise the sibling
``../kairos-ontology-referencemodels`` is probed.  Local-only: nothing here fetches over
the network.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from kairos_ontology.core import archetype_loader, pattern_loader

# Unblock the installed referencemodels package — conftest.py blocks it by
# default for test isolation, but this file *needs* the real package.
sys.modules.pop("kairos_ontology_referencemodels", None)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _refmodels_root() -> Path | None:
    """Return a reference-models root, preferring the explicit override."""
    # 1. KAIROS_REFMODELS_ROOT env var (explicit override)
    override = os.environ.get("KAIROS_REFMODELS_ROOT")
    if override:
        candidate = Path(override)
        if candidate.is_dir():
            return candidate
    # 2. Installed package
    try:
        from kairos_ontology_referencemodels import refmodels_root

        root = refmodels_root()
        if root.is_dir():
            return root
    except ImportError:
        pass
    # 3. Sibling checkout for local development
    sibling = _REPO_ROOT.parent / "kairos-ontology-referencemodels"
    if sibling.is_dir():
        # Phase 1 moved data inside the package dir; try both layouts
        inner = sibling / "ontology-reference-models"
        if inner.is_dir():
            return inner
        pkg_inner = sibling / "kairos_ontology_referencemodels" / "ontology-reference-models"
        if pkg_inner.is_dir():
            return pkg_inner
        return sibling
    return None


REFMODELS_ROOT = _refmodels_root()

# Re-block the installed package so other test files that rely on conftest's
# isolation sentinel still see the "no package" state.  Importing the real
# module above bypassed the sentinel — restore it now.
import types as _types  # noqa: E402


def _raise_import_error(*a, **kw):
    raise ImportError("blocked after REFMODELS_ROOT resolved")


_block = _types.ModuleType("kairos_ontology_referencemodels")
_block.refmodels_root = _raise_import_error  # type: ignore[attr-defined]
sys.modules["kairos_ontology_referencemodels"] = _block


def _fail_if_missing_in_ci(root: Path | None, environ: dict[str, str]) -> None:
    """Raise if CI is running this module without reference models available.

    Extracted as a standalone function so it's unit-testable without needing to
    reload this module or fork a subprocess (issue #315).
    """
    if root is None and environ.get("CI"):
        raise RuntimeError(
            "kairos-ontology-referencemodels not found while running in "
            "CI (the CI environment variable is set). The package must be "
            "installed as a dev dependency (see pyproject.toml) or "
            "KAIROS_REFMODELS_ROOT must point at a checkout."
        )


_fail_if_missing_in_ci(REFMODELS_ROOT, os.environ)

pytestmark = pytest.mark.skipif(
    REFMODELS_ROOT is None,
    reason=(
        "no kairos-ontology-referencemodels found — install the package, set "
        "KAIROS_REFMODELS_ROOT, or place a checkout at ../kairos-ontology-referencemodels"
    ),
)


def _inner_root() -> Path:
    """Return the ``ontology-reference-models`` data directory.

    When resolved from the installed package, ``REFMODELS_ROOT`` already points there.
    When resolved from a sibling checkout, the data sits one level down.
    """
    inner = REFMODELS_ROOT / "ontology-reference-models"
    return inner if inner.is_dir() else REFMODELS_ROOT


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


def test_every_published_normative_unit_is_classified() -> None:
    """The live half of the coverage-ledger totality contract (``core/pattern_rules``).

    The library-independent half is ``tests/test_pattern_rules.py``, which always runs. This
    one is the alarm for the *published* library: a newly shipped anti-pattern, a renamed
    convention, or a new top-level block lands in ``unrecognized_shape`` and fails here,
    instead of being absent from every list the way #280's ``silently-dropped-relationship``
    was.

    Note that this file is ``skipif``'d and CI provides no reference-models checkout (#315),
    so this is a *local* alarm only — which is precisely why the totality assertion is not
    only here.
    """
    from kairos_ontology.core import pattern_rules

    patterns, warnings = pattern_loader.load_patterns(REFMODELS_ROOT)
    assert patterns, f"no patterns found under {REFMODELS_ROOT}"
    ledger = pattern_rules.build_ledger(patterns, warnings)

    unrecognized = [
        f"{e.pattern}/{e.key}/{e.unit}"
        for e in ledger.entries
        if e.classification == pattern_rules.UNRECOGNIZED
    ]
    assert not unrecognized, (
        "the published pattern library declares normative unit(s) this toolkit has no "
        f"recorded position on: {unrecognized}. Classify each one in "
        "core/pattern_rules.py as enforced_by or not_enforceable."
    )
    assert not ledger.stale_registry_entries, (
        "core/pattern_rules.py records a position on unit(s) the library no longer "
        f"publishes: {list(ledger.stale_registry_entries)}"
    )
    enforced = ledger.totals[pattern_rules.ENFORCED]
    assert enforced >= pattern_rules.MINIMUM_ENFORCED_UNITS, (
        f"the ledger records {enforced} enforced unit(s) over the published library; the "
        "registry must not silently lose the one check that exists"
    )


def _published_tier_enum() -> list[str]:
    schema_path = (
        _inner_root()
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

    inner = _inner_root()
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
    archetypes_dir = _inner_root() / "blueprints" / "archetypes"
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
