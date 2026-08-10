# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI tests for `kairos-ontology list-patterns` (#262 §3).

Asserts machine output on stdout is parseable (clean) and diagnostics go to stderr.
"""

from __future__ import annotations

import json

import pytest
import yaml
from click.testing import CliRunner

from archetype_fixtures import build_refmodels_root
from kairos_ontology.cli.main import cli


@pytest.fixture()
def refroot(tmp_path):
    return build_refmodels_root(tmp_path)


@pytest.fixture(autouse=True)
def _skill_context(monkeypatch):
    monkeypatch.setenv("KAIROS_SKILL_CONTEXT", "1")


def _run(args):
    return CliRunner().invoke(cli, args)


def test_list_patterns_emits_clean_json(refroot):
    res = _run(["list-patterns", "--refmodels-root", str(refroot)])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)  # must parse — no diagnostics mixed in
    assert [p["id"] for p in payload["patterns"]] == ["temporal-quartet"]
    assert payload["warnings"] == []
    tq = payload["patterns"][0]
    assert tq["normativity"]["naming"] == "normative"
    assert any(a["id"] == "synonym-for-estimated-or-requested" for a in tq["anti_patterns"])
    # Progress line is on stderr, not stdout.
    assert "Reference-models root" in res.stderr


def test_list_patterns_yaml_format(refroot):
    res = _run(["list-patterns", "--format", "yaml", "--refmodels-root", str(refroot)])
    assert res.exit_code == 0, res.output
    payload = yaml.safe_load(res.stdout)
    assert payload["patterns"][0]["id"] == "temporal-quartet"


def test_single_pattern_by_id(refroot):
    res = _run(["list-patterns", "--pattern", "temporal-quartet", "--refmodels-root", str(refroot)])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert payload["pattern"]["id"] == "temporal-quartet"
    assert "patterns" not in payload  # single-pattern shape


def test_unknown_pattern_exits_nonzero(refroot):
    res = _run(["list-patterns", "--pattern", "ghost", "--refmodels-root", str(refroot)])
    assert res.exit_code == 2
    assert res.stdout.strip() == ""  # no machine output on failure


def test_malformed_pattern_warns_but_succeeds(tmp_path):
    root = build_refmodels_root(tmp_path, add_malformed_pattern=True)
    res = _run(["list-patterns", "--refmodels-root", str(root)])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    ids = [p["id"] for p in payload["patterns"]]
    assert "temporal-quartet" in ids
    assert "broken-pattern" not in ids
    assert any("broken-pattern" in w for w in payload["warnings"])
    assert "broken-pattern" in res.stderr


def test_absent_library_warns_but_succeeds(tmp_path):
    root = build_refmodels_root(tmp_path, with_patterns=False)
    res = _run(["list-patterns", "--refmodels-root", str(root)])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert payload["patterns"] == []
    assert "no 'blueprints/patterns/' library" in res.stderr
