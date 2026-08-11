# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Totality tests for the pattern-coverage ledger (``core/pattern_rules``).

This file is the library-*independent* half of the coverage contract and runs everywhere,
always. The live-library half lives in ``tests/test_refmodels_contract.py``, which is
``skipif``'d on a reference-models checkout being present and is therefore skipped in CI
(#315) — putting the totality assertion only there would make it a test that cannot fail.

Three traps this file exists to avoid, all of which produce a green test that proves nothing:

1. Enumerating the loader's *promoted* dataclass fields instead of the raw parsed mapping.
   That tests ``pattern_loader``'s field list, not the library: a normative block under a
   key the loader keeps in ``extra`` (``naming_rule`` today) would be outside the ledger
   while coverage read as complete.
2. Omitting a minimum ``enforced_by`` count. Totality alone is satisfied by an empty
   registry, because every unit would fall through to ``not_enforceable``/
   ``unrecognized_shape``.
3. Living in a file CI never executes.
"""

from __future__ import annotations

import pytest

from archetype_fixtures import build_refmodels_root
from kairos_ontology.core.pattern_loader import Pattern, load_patterns
from kairos_ontology.core.pattern_rules import (
    CLASSIFICATIONS,
    DESCRIPTIVE_KEYS,
    ENFORCED,
    MINIMUM_ENFORCED_UNITS,
    NOT_ENFORCEABLE,
    RULE_REGISTRY,
    UNRECOGNIZED,
    build_ledger,
    coverage_entries,
)


@pytest.fixture()
def library(tmp_path):
    """A synthetic library holding all three shapes the ledger must handle.

    ``temporal-quartet`` (normative naming + a ``naming_rule`` the loader never promotes),
    ``deferred-relationship`` (the one enforced anti-pattern), and ``future-pattern``
    (published in a shape this toolkit has never seen).
    """
    root = build_refmodels_root(tmp_path, add_enforced_pattern=True, add_future_shape_pattern=True)
    patterns, warnings = load_patterns(root)
    return patterns, warnings


def test_every_normative_unit_maps_to_exactly_one_classification(library):
    """The ledger is total and unambiguous over every enumerated unit.

    Fails today (``core.pattern_rules`` does not exist on main). Non-vacuous afterwards: a
    classification outside the closed set, a duplicate unit key, or an entry with no stated
    justification each turn it red.
    """
    patterns, _ = library
    entries = coverage_entries(patterns)
    assert entries, "the ledger enumerated no units at all"

    seen: set[tuple[str, str, str]] = set()
    for entry in entries:
        assert entry.classification in CLASSIFICATIONS, entry
        key = (entry.pattern, entry.key, entry.unit)
        assert key not in seen, f"unit enumerated twice: {key}"
        seen.add(key)
        if entry.classification == ENFORCED:
            assert entry.diagnostic_code, f"{key}: enforced with no diagnostic code"
            assert entry.home, f"{key}: enforced with no home"
        else:
            assert entry.reason, f"{key}: {entry.classification} with no stated reason"


def test_ledger_accounts_for_every_raw_top_level_key(library):
    """Totality is measured against the **raw** mapping, unknown keys included.

    This is trap 1. A key is acceptable only if it is a declared descriptive key, produced at
    least one ledger entry, or carries no value at all. Nothing may simply not be looked at.

    Fails today (module absent). Non-vacuous afterwards: drop the unknown-key branch from
    ``enumerate_units`` and ``future-pattern``'s ``constraint_rules`` disappears, turning this
    red.
    """
    patterns, _ = library
    entries = coverage_entries(patterns)
    for pattern in patterns:
        produced = {e.key for e in entries if e.pattern == pattern.id}
        for key, value in pattern.to_payload().items():
            assert key in DESCRIPTIVE_KEYS or key in produced or not value, (
                f"{pattern.id}: top-level key '{key}' carries a value but reached no ledger "
                "entry and is not a declared descriptive key — coverage would read as "
                "complete while this block was invisible"
            )


def test_ledger_reads_blocks_the_loader_does_not_promote(library):
    """``naming_rule`` is a normative MUST that lives in ``Pattern.extra``, not a field.

    The guard against trap 1 stated directly: if the ledger ever enumerates
    ``Pattern.__dataclass_fields__`` rather than :meth:`Pattern.to_payload`, this unit
    vanishes and the test goes red.
    """
    patterns, _ = library
    assert "naming_rule" not in Pattern.__dataclass_fields__, (
        "naming_rule is now a promoted field — this test's premise needs re-pointing at "
        "whatever block still lands in extra"
    )
    quartet = next(p for p in patterns if p.id == "temporal-quartet")
    assert "naming_rule" in quartet.extra
    units = {(e.key, e.unit) for e in coverage_entries([quartet])}
    assert ("naming_rule", "naming_rule") in units


def test_unknown_top_level_key_lands_in_unrecognized_shape(library):
    """Forward compatibility: reference models release independently of the toolkit.

    ``future-pattern`` publishes a ``constraint_rules`` block this release has never seen. It
    must surface as ``unrecognized_shape`` — the bucket whose absence is why #280 went
    unnoticed — never be dropped.
    """
    patterns, _ = library
    future = next(p for p in patterns if p.id == "future-pattern")
    entries = coverage_entries([future])
    unknown = [e for e in entries if e.key == "constraint_rules"]
    assert unknown, "an unknown top-level normative block was dropped from the ledger"
    assert all(e.classification == UNRECOGNIZED for e in unknown)
    assert all(e.reason for e in unknown)


def test_unregistered_anti_pattern_lands_in_unrecognized_shape(library):
    """A *new anti-pattern in a known block* is the #280 shape exactly.

    ``silently-dropped-relationship`` was in no list at all. An anti-pattern the registry has
    never classified must therefore be loud, not absent.
    """
    patterns, _ = library
    future = next(p for p in patterns if p.id == "future-pattern")
    entry = next(e for e in coverage_entries([future]) if e.unit == "brand-new-anti-pattern")
    assert entry.classification == UNRECOGNIZED
    assert entry.kind == "anti_pattern"


def test_at_least_one_unit_is_enforced(library):
    """Trap 2: totality is satisfiable by an empty registry, so assert the floor.

    Fails today (module absent). Non-vacuous afterwards: delete the single ``enforced_by``
    entry from :data:`RULE_REGISTRY` and every unit still classifies — totality stays green
    and only this assertion goes red.
    """
    patterns, _ = library
    entries = coverage_entries(patterns)
    enforced = [e for e in entries if e.classification == ENFORCED]
    assert len(enforced) >= MINIMUM_ENFORCED_UNITS, (
        f"the ledger records {len(enforced)} enforced unit(s); at least "
        f"{MINIMUM_ENFORCED_UNITS} toolkit check exists, so an empty column means the "
        "registry lost it, not that enforcement went away"
    )


def test_the_enforced_unit_is_the_relationship_endpoint_check(library):
    """The one honest entry, asserted against the code that actually implements it.

    Non-vacuous: remove the ``binding.object-property-in-fields`` remap from the kernel and
    this goes red, so the registry cannot keep claiming a check that no longer exists.
    """
    from kairos_ontology.core.compiler.kernel import _adapter_safety_diagnostic
    from kairos_ontology.core.compiler.quality import SAFETY_RULE_CODES
    from kairos_ontology.core.compiler.result import CompileDiagnostic, SourceLocation

    patterns, _ = library
    entry = next(
        e
        for e in coverage_entries(patterns)
        if e.pattern == "deferred-relationship" and e.unit == "silently-dropped-relationship"
    )
    assert entry.classification == ENFORCED
    assert entry.home == "compiler"
    assert entry.rejection_reason, "an enforced unit must record the reason it stands for"
    assert entry.diagnostic_code in SAFETY_RULE_CODES

    remapped = _adapter_safety_diagnostic(
        CompileDiagnostic(
            code="binding.object-property-in-fields",
            message="an object property authored under fields:",
            location=SourceLocation(path="x.yaml", pointer="/fields/0"),
        )
    )
    assert remapped.code == entry.diagnostic_code


def test_enforced_registry_reason_matches_the_published_text(library):
    """Recorded ``rejection_reason`` must still be the library's, or the ledger warns.

    The ledger quotes the library rather than paraphrasing it; a reword upstream is surfaced
    as drift instead of silently redefining what the check stands for.
    """
    patterns, warnings = library
    ledger = build_ledger(patterns, warnings)
    assert not [w for w in ledger.warnings if "rejection_reason has changed" in w]


def test_loader_quality_warnings_reach_the_ledger(tmp_path):
    """A skipped pattern is an *absent* pattern — coverage over it would read as complete.

    ``load_patterns`` is lenient by design (correct: nothing here is enforced), so the
    warnings must appear in the ledger payload, not only on stderr.
    """
    root = build_refmodels_root(tmp_path, add_enforced_pattern=True, add_malformed_pattern=True)
    patterns, warnings = load_patterns(root)
    ledger = build_ledger(patterns, warnings)
    assert any("broken-pattern" in w for w in ledger.warnings)
    assert any("broken-pattern" in w for w in ledger.to_payload()["warnings"])


def test_totals_are_closed_and_sum_to_the_unit_count(library):
    """Every classification is always present in the totals, including the empty ones."""
    patterns, warnings = library
    totals = build_ledger(patterns, warnings).totals
    assert set(CLASSIFICATIONS) <= set(totals)
    assert sum(totals[name] for name in CLASSIFICATIONS) == totals["units"]


def test_stale_registry_entries_are_reported_not_hidden(library):
    """A registry entry matching no published unit is a claim about a rule that is gone."""
    patterns, warnings = library
    ledger = build_ledger(patterns, warnings)
    # The synthetic library ships neither governed-code-list nor multimodal-order-leg, so the
    # registry's entries for them must show up as stale rather than be quietly ignored.
    assert any(s.startswith("governed-code-list/") for s in ledger.stale_registry_entries)


def test_registry_verdicts_are_self_consistent():
    """The toolkit-owned registry may only say ``enforced_by`` or ``not_enforceable``.

    ``unrecognized_shape`` is what *absence* from the registry means; recording it explicitly
    would let a real gap be laundered into a deliberate-looking classification.
    """
    for key, verdict in RULE_REGISTRY.items():
        assert verdict.classification in (ENFORCED, NOT_ENFORCEABLE), key
        if verdict.classification == ENFORCED:
            assert verdict.diagnostic_code and verdict.home and verdict.rejection_reason, key
            assert not verdict.reason, key
        else:
            assert verdict.reason, key
            assert not verdict.diagnostic_code, key
