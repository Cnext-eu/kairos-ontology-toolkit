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
        # closes_gap / grain_collisions are not first-class fields but must survive.
        assert "closes_gap" in pattern.extra
        assert pattern.extra["closes_gap"] == [8]
        assert "closes_gap" in pattern.to_payload()

    def test_anti_patterns_surfaced(self, refroot):
        pattern = load_pattern(refroot, "temporal-quartet")
        ids = [a["id"] for a in pattern.anti_patterns]
        assert "synonym-for-estimated-or-requested" in ids

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
