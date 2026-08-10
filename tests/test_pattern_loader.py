# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for kairos_ontology.core.pattern_loader (#262 §3)."""

from __future__ import annotations

import pytest

from archetype_fixtures import build_refmodels_root
from kairos_ontology.core.pattern_loader import (
    Pattern,
    PatternError,
    list_patterns,
    load_pattern,
    load_patterns,
)


@pytest.fixture()
def refroot(tmp_path):
    return build_refmodels_root(tmp_path)


class TestListPatterns:
    def test_lists_pattern_ids(self, refroot):
        assert list_patterns(refroot) == ["temporal-quartet"]

    def test_excludes_schema_dir(self, refroot):
        # _schema/ is present in the fixture but must never be listed as a pattern.
        assert "_schema" not in list_patterns(refroot)

    def test_empty_when_library_absent(self, tmp_path):
        root = build_refmodels_root(tmp_path, with_patterns=False)
        assert list_patterns(root) == []


class TestLoadPattern:
    def test_loads_single_pattern(self, refroot):
        pattern = load_pattern(refroot, "temporal-quartet")
        assert isinstance(pattern, Pattern)
        assert pattern.id == "temporal-quartet"
        assert pattern.normativity["naming"] == "normative"
        assert pattern.problem
        assert pattern.applicability

    def test_preserves_unknown_keys_in_extra(self, refroot):
        pattern = load_pattern(refroot, "temporal-quartet")
        # closes_gap is pattern-specific: not a first-class field, but it must survive and
        # still reach consumers through the payload flatten.
        assert "closes_gap" in pattern.extra
        assert pattern.extra["closes_gap"] == [8]
        assert "closes_gap" in pattern.to_payload()

    def test_anti_patterns_surfaced(self, refroot):
        pattern = load_pattern(refroot, "temporal-quartet")
        ids = [a["id"] for a in pattern.anti_patterns]
        assert "synonym-for-estimated-or-requested" in ids

    def test_grain_collisions_are_first_class(self, refroot):
        """Every published pattern ships ``grain_collisions``, so it is a field, not ``extra``.

        It carries the "do not subclass / do not merge" boundaries the design skill must state
        (#276 Q1), and is the field a future attestation's ``grain_collisions_encountered``
        mirrors.
        """
        pattern = load_pattern(refroot, "temporal-quartet")
        assert "grain_collisions" not in pattern.extra
        assert pattern.grain_collisions[0]["against"].endswith("#RequestedWindow")
        assert pattern.to_payload()["grain_collisions"] == pattern.grain_collisions

    def test_grain_collisions_default_to_empty_when_absent(self, tmp_path):
        root = build_refmodels_root(tmp_path)
        path = root / "blueprints" / "patterns" / "temporal-quartet" / "pattern.yaml"
        path.write_text("id: temporal-quartet\nproblem: minimal\n", encoding="utf-8")
        assert load_pattern(root, "temporal-quartet").grain_collisions == []

    def test_grain_collisions_tolerate_both_published_shapes(self, tmp_path):
        """The published library mixes mappings and bare prose strings.

        ``multimodal-order-leg`` ships ``{against, reason}`` mappings while
        ``governed-code-list`` and ``qualified-role-assignment`` ship plain strings. Nothing
        may assume one shape — the field stays untyped and consumers must handle both.
        """
        root = build_refmodels_root(tmp_path)
        path = root / "blueprints" / "patterns" / "temporal-quartet" / "pattern.yaml"
        path.write_text(
            "id: temporal-quartet\n"
            "problem: minimal\n"
            "grain_collisions:\n"
            '  - against: "https://example.org/ont/x#Thing"\n'
            '    reason: "distinct grain"\n'
            '  - "A bare prose collision with no keys at all."\n',
            encoding="utf-8",
        )
        collisions = load_pattern(root, "temporal-quartet").grain_collisions
        assert isinstance(collisions[0], dict) and collisions[0]["against"].endswith("#Thing")
        assert isinstance(collisions[1], str)


class TestPatternQualityWarnings:
    """Valid YAML is only the floor — a pattern can parse and still be hollow (#262)."""

    def _write(self, root, body: str):
        path = root / "blueprints" / "patterns" / "temporal-quartet" / "pattern.yaml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_normative_naming_without_conventions_warns(self, tmp_path):
        root = build_refmodels_root(tmp_path)
        self._write(
            root,
            "id: temporal-quartet\nproblem: p\nnormativity:\n  naming: normative\n",
        )
        patterns, warnings = load_patterns(root)
        assert len(patterns) == 1  # still returned — advisory, never fatal
        assert any("ships no naming_conventions" in w for w in warnings)

    def test_anti_pattern_without_rejection_reason_warns(self, tmp_path):
        root = build_refmodels_root(tmp_path)
        self._write(
            root,
            "id: temporal-quartet\nproblem: p\nanti_patterns:\n"
            "  - id: synonym-for-estimated\n    description: d\n",
        )
        _, warnings = load_patterns(root)
        assert any(
            "synonym-for-estimated" in w and "no rejection_reason" in w for w in warnings
        )

    def test_naming_conventions_as_mapping_warns(self, tmp_path):
        """The library's own structural rule: naming_conventions is a list of entries."""
        root = build_refmodels_root(tmp_path)
        self._write(
            root,
            "id: temporal-quartet\nproblem: p\nnaming_conventions:\n  qualifiers: [requested]\n",
        )
        _, warnings = load_patterns(root)
        assert any("expected a list of entries" in w for w in warnings)

    def test_advisory_naming_without_conventions_is_quiet(self, tmp_path):
        """Only a *normative* naming claim with nothing behind it is a defect."""
        root = build_refmodels_root(tmp_path)
        self._write(root, "id: temporal-quartet\nproblem: p\nnormativity:\n  naming: advisory\n")
        _, warnings = load_patterns(root)
        assert warnings == []

    def test_healthy_fixture_pattern_warns_about_nothing(self, refroot):
        _, warnings = load_patterns(refroot)
        assert warnings == []

    def test_missing_pattern_raises(self, refroot):
        with pytest.raises(PatternError):
            load_pattern(refroot, "does-not-exist")

    def test_malformed_pattern_raises(self, tmp_path):
        root = build_refmodels_root(tmp_path, add_malformed_pattern=True)
        with pytest.raises(PatternError):
            load_pattern(root, "broken-pattern")


class TestLoadPatterns:
    def test_load_all_happy_path(self, refroot):
        patterns, warnings = load_patterns(refroot)
        assert [p.id for p in patterns] == ["temporal-quartet"]
        assert warnings == []

    def test_malformed_pattern_skipped_with_warning(self, tmp_path):
        root = build_refmodels_root(tmp_path, add_malformed_pattern=True)
        patterns, warnings = load_patterns(root)
        # The valid pattern still loads; the broken one is skipped, not raised.
        assert "temporal-quartet" in [p.id for p in patterns]
        assert "broken-pattern" not in [p.id for p in patterns]
        assert any("broken-pattern" in w for w in warnings)

    def test_empty_library_returns_empty(self, tmp_path):
        root = build_refmodels_root(tmp_path, with_patterns=False)
        assert load_patterns(root) == ([], [])
