# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for privacy-safe persisted source sample artifacts."""

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from rdflib import Graph, Namespace

from kairos_ontology.cli.main import cli
from kairos_ontology.core.source_privacy import (
    KAIROS_BRONZE,
    run_source_privacy,
)


def _build_source_dir(tmp_path: Path) -> Path:
    source_dir = tmp_path / "integration" / "sources" / "crm"
    source_dir.mkdir(parents=True)
    (source_dir / "_manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "version": "1.1",
                "system": "crm",
                "tables": ["contacts"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (source_dir / "contacts.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "contacts",
                "columns": [
                    {"name": "email", "data_type": "varchar(255)"},
                    {"name": "status", "data_type": "varchar(20)"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (source_dir / "contacts.samples.yaml").write_text(
        yaml.safe_dump(
            {
                "table": "contacts",
                "rows": [
                    {
                        "email": "person@example.com",
                        "status": "active",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (source_dir / "crm.vocabulary.ttl").write_text(
        """\
@prefix crm: <https://kairos.cnext.eu/source/crm#> .
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .

crm:contacts a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "contacts" .

crm:contacts_email a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable crm:contacts ;
    kairos-bronze:columnName "email" ;
    kairos-bronze:dataType "varchar(255)" ;
    kairos-bronze:sampleValues "person@example.com" .
""",
        encoding="utf-8",
    )
    return source_dir


def test_check_reports_locations_without_values(tmp_path):
    source_dir = _build_source_dir(tmp_path)

    report = run_source_privacy(source_dir)

    assert not report.passed
    assert len(report.findings) == 2
    assert {finding.kind for _, finding in report.findings} == {"email"}
    assert all(finding.column == "email" for _, finding in report.findings)


def test_fix_rewrites_yaml_and_turtle_then_passes(tmp_path):
    source_dir = _build_source_dir(tmp_path)

    report = run_source_privacy(source_dir, fix=True)

    assert len(report.changed_files) == 2
    assert run_source_privacy(source_dir).passed
    samples_raw = (source_dir / "contacts.samples.yaml").read_text(encoding="utf-8")
    ttl_raw = (source_dir / "crm.vocabulary.ttl").read_text(encoding="utf-8")
    assert "person@example.com" not in samples_raw
    assert "person@example.com" not in ttl_raw

    samples = yaml.safe_load(samples_raw)
    assert samples["rows"][0]["email"] == (
        "<redacted kind=email source=contacts.email datatype=varchar(255)>"
    )
    graph = Graph()
    graph.parse(data=ttl_raw, format="turtle")
    crm = Namespace("https://kairos.cnext.eu/source/crm#")
    assert str(graph.value(crm["contacts_email"], KAIROS_BRONZE.sampleValues)) == (
        "<redacted kind=email source=contacts.email datatype=varchar(255)>"
    )


def test_cli_blocks_then_fixes_without_echoing_values(tmp_path):
    source_dir = _build_source_dir(tmp_path)
    runner = CliRunner()
    env = {"KAIROS_SKILL_CONTEXT": "1"}

    check = runner.invoke(
        cli,
        ["source-privacy", "--sources", str(source_dir)],
        env=env,
    )
    assert check.exit_code == 1
    assert "contacts.email [email]" in check.output
    assert "person@example.com" not in check.output

    fix = runner.invoke(
        cli,
        ["source-privacy", "--sources", str(source_dir), "--fix"],
        env=env,
    )
    assert fix.exit_code == 0
    assert "privacy-safe" in fix.output
    assert "person@example.com" not in fix.output


def test_orphaned_table_yaml_is_checked_and_fixed(tmp_path):
    source_dir = _build_source_dir(tmp_path)
    orphan = source_dir / "legacy_contacts.yaml"
    orphan.write_text(
        yaml.safe_dump(
            {
                "name": "legacy_contacts",
                "columns": [
                    {
                        "name": "payload",
                        "data_type": "json",
                        "samples": [{"owner_email": "legacy@example.com"}],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = run_source_privacy(source_dir)

    assert any(path == orphan for path, _ in report.findings)
    run_source_privacy(source_dir, fix=True)
    assert "legacy@example.com" not in orphan.read_text(encoding="utf-8")
    assert run_source_privacy(source_dir).passed


def test_fix_rolls_back_all_files_when_publication_fails(tmp_path, monkeypatch):
    source_dir = _build_source_dir(tmp_path)
    samples_path = source_dir / "contacts.samples.yaml"
    ttl_path = source_dir / "crm.vocabulary.ttl"
    original_samples = samples_path.read_text(encoding="utf-8")
    original_ttl = ttl_path.read_text(encoding="utf-8")

    from kairos_ontology.core import source_privacy

    real_replace = source_privacy.os.replace
    failed = False

    def fail_second_publish(source, destination):
        nonlocal failed
        if Path(destination) == ttl_path and not failed:
            failed = True
            raise OSError("simulated publish failure")
        return real_replace(source, destination)

    monkeypatch.setattr(source_privacy.os, "replace", fail_second_publish)

    with pytest.raises(OSError, match="simulated publish failure"):
        run_source_privacy(source_dir, fix=True)

    assert samples_path.read_text(encoding="utf-8") == original_samples
    assert ttl_path.read_text(encoding="utf-8") == original_ttl
