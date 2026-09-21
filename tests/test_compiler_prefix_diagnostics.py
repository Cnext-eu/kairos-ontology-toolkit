# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""DD-133 prefix-ambiguity diagnostics: same-file conflicts are blocking errors, imported-only
ambiguity is a non-fatal warning that lists candidate ``@prefix`` declarations."""

from __future__ import annotations

import os

from pathlib import Path
from types import SimpleNamespace

from kairos_ontology.core.compiler.kernel import (
    _declared_prefixes,
    _prefix_alternatives,
    _prefix_diagnostics,
    _read_declared_prefixes,
)
from kairos_ontology.core.compiler.result import DiagnosticSeverity


def _loaded(*paths: Path) -> SimpleNamespace:
    return SimpleNamespace(
        sources=tuple(
            SimpleNamespace(manifest=SimpleNamespace(source_path=str(path))) for path in paths
        )
    )


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_imported_only_ambiguous_prefix_is_a_warning_with_candidates(tmp_path):
    root = _write(
        tmp_path / "root.ttl",
        "@prefix party: <https://example.test/party#> .\n",
    )
    _write(
        tmp_path / "imported_a.ttl",
        "@prefix shared: <https://example.test/one#> .\n",
    )
    _write(
        tmp_path / "imported_b.ttl",
        "@prefix shared: <https://example.test/two#> .\n",
    )
    loaded = _loaded(root, tmp_path / "imported_a.ttl", tmp_path / "imported_b.ttl")

    diagnostics = _prefix_diagnostics(loaded, root)

    assert len(diagnostics) == 1
    item = diagnostics[0]
    assert item.code == "safety.prefix-ambiguous"
    assert item.severity is DiagnosticSeverity.WARNING
    assert "https://example.test/one#" in item.message
    assert "https://example.test/two#" in item.message
    assert "@prefix shared: <https://example.test/one#> ." in item.message
    assert "@prefix shared: <https://example.test/two#> ." in item.message


def test_root_declared_prefix_suppresses_imported_ambiguity(tmp_path):
    root = _write(
        tmp_path / "root.ttl",
        "@prefix shared: <https://example.test/one#> .\n",
    )
    _write(
        tmp_path / "imported_a.ttl",
        "@prefix shared: <https://example.test/one#> .\n",
    )
    _write(
        tmp_path / "imported_b.ttl",
        "@prefix shared: <https://example.test/two#> .\n",
    )
    loaded = _loaded(root, tmp_path / "imported_a.ttl", tmp_path / "imported_b.ttl")

    diagnostics = _prefix_diagnostics(loaded, root)

    assert diagnostics == ()


def test_same_file_prefix_conflict_is_a_blocking_error(tmp_path):
    root = _write(
        tmp_path / "root.ttl",
        "@prefix dup: <https://example.test/one#> .\n@prefix dup: <https://example.test/two#> .\n",
    )
    loaded = _loaded(root)

    diagnostics = _prefix_diagnostics(loaded, root)

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "safety.prefix-ambiguous"
    assert diagnostics[0].severity is DiagnosticSeverity.ERROR


def test_prefix_alternatives_suggests_the_unambiguous_prefix_for_the_same_namespace(tmp_path):
    """Issue #674: three imports share `party:` with no root declaration; `bsp:` is the
    one prefix unambiguously bound to the namespace the failed `party:` token meant."""
    root = _write(tmp_path / "root.ttl", "")
    _write(
        tmp_path / "bsp.ttl",
        "@prefix party: <https://example.test/bsp/party#> .\n"
        "@prefix bsp: <https://example.test/bsp/party#> .\n",
    )
    _write(
        tmp_path / "dcsa.ttl",
        "@prefix party: <https://example.test/dcsa/party#> .\n",
    )
    _write(
        tmp_path / "rail.ttl",
        "@prefix party: <https://example.test/rail/party#> .\n",
    )
    loaded = _loaded(
        root, tmp_path / "bsp.ttl", tmp_path / "dcsa.ttl", tmp_path / "rail.ttl"
    )

    alternatives = _prefix_alternatives(loaded, root)

    assert alternatives == {"party": ("bsp",)}


def test_prefix_alternatives_is_empty_when_no_safe_alternative_exists(tmp_path):
    root = _write(tmp_path / "root.ttl", "")
    _write(tmp_path / "a.ttl", "@prefix party: <https://example.test/a/party#> .\n")
    _write(tmp_path / "b.ttl", "@prefix party: <https://example.test/b/party#> .\n")
    loaded = _loaded(root, tmp_path / "a.ttl", tmp_path / "b.ttl")

    assert _prefix_alternatives(loaded, root) == {}

class TestDeclaredPrefixesIsCached:
    """#944 -- one domain's plan build called this 13,464 times against 36 files.

    Each call stat'd, read and regex-scanned a whole Turtle file, over the vendored
    reference-model corpus: ~3.7s of self time in an 11.4s build, the largest single entry
    in the profile. Caching the parse took the same build from 8.6s to 2.0s.
    """

    def test_a_second_read_of_the_same_file_does_not_reparse(self, tmp_path):
        path = _write(tmp_path / "a.ttl", "@prefix ex: <https://ex.test/a#> .\n")
        _read_declared_prefixes.cache_clear()
        assert _declared_prefixes(str(path)) == {"ex": ("https://ex.test/a#",)}
        after_first = _read_declared_prefixes.cache_info()
        assert _declared_prefixes(str(path)) == {"ex": ("https://ex.test/a#",)}
        after_second = _read_declared_prefixes.cache_info()
        assert after_second.misses == after_first.misses, "the file was read twice"
        assert after_second.hits == after_first.hits + 1

    def test_a_rewritten_file_is_reread(self, tmp_path):
        """The stat stays on every call, which is what makes the cache safe.

        Keying on the path alone would serve a stale answer here -- to a test that edits a
        fixture, or to any process that outlives one CLI invocation.
        """
        path = _write(tmp_path / "b.ttl", "@prefix ex: <https://ex.test/one#> .\n")
        _read_declared_prefixes.cache_clear()
        assert _declared_prefixes(str(path)) == {"ex": ("https://ex.test/one#",)}
        os.utime(path, (0, 0))  # force a distinct mtime regardless of clock resolution
        _write(path, "@prefix ex: <https://ex.test/two#> .\n")
        assert _declared_prefixes(str(path)) == {"ex": ("https://ex.test/two#",)}

    def test_the_returned_mapping_is_safe_to_mutate(self, tmp_path):
        """A caller editing the result must not corrupt every later cache hit."""
        path = _write(tmp_path / "c.ttl", "@prefix ex: <https://ex.test/c#> .\n")
        _read_declared_prefixes.cache_clear()
        first = _declared_prefixes(str(path))
        first["injected"] = ("https://ex.test/injected#",)
        assert _declared_prefixes(str(path)) == {"ex": ("https://ex.test/c#",)}

    def test_a_missing_or_non_turtle_path_is_still_empty(self, tmp_path):
        """Unchanged behaviour: the old guard was is_file() plus a suffix check."""
        assert _declared_prefixes("") == {}
        assert _declared_prefixes(str(tmp_path / "absent.ttl")) == {}
        assert _declared_prefixes(str(_write(tmp_path / "d.txt", "@prefix ex: <x> ."))) == {}
