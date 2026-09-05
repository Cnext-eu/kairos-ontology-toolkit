# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the `suggest-type` CLI command."""

from __future__ import annotations

import json

from click.testing import CliRunner

from kairos_ontology.cli.main import cli


def _run(*args: str):
    return CliRunner().invoke(cli, ["suggest-type", *args])


def test_suggest_type_varchar_max_returns_string():
    result = _run("varchar(max)")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["canonical_kind"] == "string"


def test_suggest_type_int_returns_int32():
    result = _run("int")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["canonical_kind"] == "int32"


def test_suggest_type_datetime_returns_timestamp():
    result = _run("datetime")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["canonical_kind"] == "timestamp"


def test_suggest_type_decimal_with_precision_and_scale():
    result = _run("decimal(18,4)")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["canonical_kind"] == "decimal"
    assert payload["precision"] == 18
    assert payload["scale"] == 4


def test_suggest_type_unrecognized_raises_error():
    result = _run("foobar")
    assert result.exit_code != 0
    assert "Unrecognized source type" in result.output


def test_suggest_type_appears_in_cli_help():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "suggest-type" in result.output
