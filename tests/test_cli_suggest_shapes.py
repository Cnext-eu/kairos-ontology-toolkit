# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI integration tests for the `suggest-shapes` command (DD-076)."""

from pathlib import Path

from click.testing import CliRunner

from kairos_ontology.cli.main import cli

_VOCAB = """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .

<#tblParties> a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblParties" .

<#tblParties_Email> a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "Email" ;
    kairos-bronze:dataType "nvarchar(200)" ;
    kairos-bronze:sampleValues "jane.doe@acme.com | bob@globex.com" ;
    kairos-bronze:belongsToTable <#tblParties> .
"""


def _write_vocab(tmp_path: Path) -> Path:
    src = tmp_path / "crm" / "crm.vocabulary.ttl"
    src.parent.mkdir(parents=True)
    src.write_text(_VOCAB, encoding="utf-8")
    return src


def test_suggest_shapes_writes_draft(tmp_path):
    src = _write_vocab(tmp_path)
    out = tmp_path / "draft.ttl"
    result = CliRunner().invoke(
        cli, ["suggest-shapes", "--source", str(src), "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "NodeShape" in text
    assert "datatype" in text
    # PII email must be masked, never echoed raw.
    assert "jane.doe@acme.com" not in text
    assert "bob@globex.com" not in text


def test_suggest_shapes_refuses_overwrite(tmp_path):
    src = _write_vocab(tmp_path)
    out = tmp_path / "draft.ttl"
    runner = CliRunner()
    first = runner.invoke(cli, ["suggest-shapes", "--source", str(src), "--out", str(out)])
    assert first.exit_code == 0
    second = runner.invoke(cli, ["suggest-shapes", "--source", str(src), "--out", str(out)])
    assert second.exit_code == 1
    assert "Refusing to overwrite" in second.output


def test_suggest_shapes_force_overwrites(tmp_path):
    src = _write_vocab(tmp_path)
    out = tmp_path / "draft.ttl"
    runner = CliRunner()
    runner.invoke(cli, ["suggest-shapes", "--source", str(src), "--out", str(out)])
    result = runner.invoke(
        cli, ["suggest-shapes", "--source", str(src), "--out", str(out), "--force"]
    )
    assert result.exit_code == 0, result.output
