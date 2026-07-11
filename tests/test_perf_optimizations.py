# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the LLM performance helpers: concurrency, cache, cost banner."""

from __future__ import annotations

import pytest

from kairos_ontology.core._concurrency import (
    call_with_backoff,
    map_concurrent,
    _is_rate_limit_error,
)
from kairos_ontology.core._cache import SidecarCache, compute_entry_hash, open_cache
from kairos_ontology.core._cost import RECOMMENDED_MODEL, build_cost_warning, print_cost_warning


# ---------------------------------------------------------------------------
# map_concurrent
# ---------------------------------------------------------------------------


class TestMapConcurrent:
    def test_preserves_input_order(self):
        items = list(range(20))
        result = map_concurrent(lambda x: x * 2, items, max_workers=8)
        assert result == [x * 2 for x in items]

    def test_serial_path_when_single_worker(self):
        calls = []
        result = map_concurrent(lambda x: calls.append(x) or x, [3, 1, 2], max_workers=1)
        # max_workers<=1 runs in the calling thread, in input order.
        assert result == [3, 1, 2]
        assert calls == [3, 1, 2]

    def test_empty_input(self):
        assert map_concurrent(lambda x: x, [], max_workers=4) == []

    def test_exception_propagates(self):
        def boom(x):
            if x == 2:
                raise ValueError("bad")
            return x
        with pytest.raises(ValueError, match="bad"):
            map_concurrent(boom, [1, 2, 3], max_workers=4)

    def test_unordered_returns_all_results(self):
        items = list(range(10))
        result = map_concurrent(lambda x: x, items, max_workers=4, ordered=False)
        assert sorted(result) == items

    def test_on_result_reports_completion_without_changing_order(self):
        items = [3, 1, 2]
        completed = []
        result = map_concurrent(
            lambda x: x * 10,
            items,
            max_workers=3,
            on_result=completed.append,
        )
        assert result == [30, 10, 20]
        assert sorted(completed) == [10, 20, 30]


# ---------------------------------------------------------------------------
# call_with_backoff
# ---------------------------------------------------------------------------


class _FakeRateLimit(Exception):
    status_code = 429


class TestCallWithBackoff:
    def test_returns_on_success(self):
        assert call_with_backoff(lambda: 42, sleep=lambda _: None) == 42

    def test_retries_rate_limit_then_succeeds(self):
        attempts = {"n": 0}
        slept: list[float] = []

        def fn():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise _FakeRateLimit("429 too many requests")
            return "ok"

        result = call_with_backoff(fn, retries=5, base_delay=1.0, sleep=slept.append)
        assert result == "ok"
        assert attempts["n"] == 3
        assert slept == [1.0, 2.0]  # exponential schedule

    def test_non_rate_limit_propagates_immediately(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise ValueError("nope")

        with pytest.raises(ValueError):
            call_with_backoff(fn, retries=5, sleep=lambda _: None)
        assert calls["n"] == 1  # no retries for non-429

    def test_reraises_after_exhausting_retries(self):
        def fn():
            raise _FakeRateLimit("429")
        with pytest.raises(_FakeRateLimit):
            call_with_backoff(fn, retries=2, base_delay=0.0, sleep=lambda _: None)

    def test_detects_rate_limit_by_message(self):
        assert _is_rate_limit_error(RuntimeError("Error code: 429"))
        assert _is_rate_limit_error(RuntimeError("rate limit exceeded"))
        assert not _is_rate_limit_error(RuntimeError("500 server error"))


# ---------------------------------------------------------------------------
# SidecarCache
# ---------------------------------------------------------------------------


class TestSidecarCache:
    def test_put_get_flush_roundtrip(self, tmp_path):
        path = tmp_path / ".cache" / "cmd.json"
        cache = SidecarCache(path)
        cache.put("k1", {"v": 1})
        assert cache.get("k1") == {"v": 1}
        cache.flush()
        assert path.exists()

        reopened = SidecarCache(path)
        assert reopened.get("k1") == {"v": 1}

    def test_disabled_cache_never_hits(self, tmp_path):
        path = tmp_path / ".cache" / "cmd.json"
        cache = SidecarCache(path, enabled=False)
        cache.put("k", "v")
        assert cache.get("k") is None
        cache.flush()
        assert not path.exists()

    def test_corrupt_cache_is_ignored(self, tmp_path):
        path = tmp_path / ".cache" / "cmd.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        cache = SidecarCache(path)
        assert cache.get("anything") is None

    def test_open_cache_path(self, tmp_path):
        cache = open_cache(tmp_path, "analyse-sources")
        assert cache.cache_path == tmp_path / ".cache" / "analyse-sources.json"

    def test_entry_hash_is_order_independent(self):
        a = compute_entry_hash({"x": 1, "y": 2})
        b = compute_entry_hash({"y": 2, "x": 1})
        assert a == b

    def test_entry_hash_changes_with_content(self):
        a = compute_entry_hash({"samples": ["a", "b"]})
        b = compute_entry_hash({"samples": ["a", "c"]})
        assert a != b


# ---------------------------------------------------------------------------
# cost banner
# ---------------------------------------------------------------------------


class TestCostWarning:
    def test_recommends_model_when_using_other(self):
        text = build_cost_warning(
            command="propose-alignment", table_count=546,
            max_workers=8, model="gpt-4o", force=False,
        )
        assert "COSTLY" in text
        assert RECOMMENDED_MODEL in text
        assert "546" in text
        assert "gpt-4o" in text

    def test_confirms_recommended_model(self):
        text = build_cost_warning(
            command="analyse-sources", table_count=10,
            max_workers=4, model=RECOMMENDED_MODEL, force=False,
        )
        assert "recommended for this task" in text

    def test_force_changes_cache_line(self):
        text = build_cost_warning(
            command="analyse-sources", table_count=10,
            max_workers=4, model=RECOMMENDED_MODEL, force=True,
        )
        assert "BYPASSED" in text

    def test_accuracy_sensitive_changes_non_recommended_line(self):
        # WS8 (issue #182): alignment is accuracy-sensitive, so the banner must not
        # claim "no quality gain" for a higher tier — it should flag the trade-off.
        text = build_cost_warning(
            command="propose-alignment", table_count=10,
            max_workers=4, model="gpt-5.5", force=False,
            accuracy_sensitive=True,
        )
        assert "ACCURACY-SENSITIVE" in text
        assert "no quality gain" not in text

    def test_accuracy_sensitive_default_model_still_recommended(self):
        text = build_cost_warning(
            command="propose-alignment", table_count=10,
            max_workers=4, model=RECOMMENDED_MODEL, force=False,
            accuracy_sensitive=True,
        )
        assert "recommended for this task" in text

    def test_quiet_suppresses(self):
        emitted: list[str] = []
        print_cost_warning(
            command="x", table_count=1, max_workers=1, model="m",
            quiet=True, stream=emitted.append,
        )
        assert emitted == []

    def test_emits_by_default(self):
        emitted: list[str] = []
        print_cost_warning(
            command="x", table_count=1, max_workers=1, model=RECOMMENDED_MODEL,
            stream=emitted.append,
        )
        assert emitted and RECOMMENDED_MODEL in emitted[0]
