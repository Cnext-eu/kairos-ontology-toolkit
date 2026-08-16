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
    assert "No unredacted PII found" in fix.output
    assert "person@example.com" not in fix.output
    # A clean result must state its coverage rather than imply universal discovery (#415):
    # the patterns actually checked — coordinates now among them (#423) — and the
    # residual gap (abbreviated lat/lon/geo column names, WKT geometries).
    assert "Patterns checked:" in fix.output
    assert "email" in fix.output
    assert "location" in fix.output
    assert "Coordinates checked: latitude/longitude/lng/coordinate" in fix.output
    assert "Still not checked:" in fix.output


def test_coordinate_columns_are_found_and_fixed(tmp_path):
    """Latitude/longitude values are caught in YAML and Turtle artifacts (#423)."""
    source_dir = tmp_path / "sources"
    source_dir.mkdir(parents=True)
    (source_dir / "stops.samples.yaml").write_text(
        yaml.safe_dump(
            {
                "table": "stops",
                "rows": [
                    {
                        "latitude": 51.334217,
                        "longitude": 4.123456,
                        "coordinates": "51.33, 4.12",
                        "status": "open",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (source_dir / "tms.vocabulary.ttl").write_text(
        """\
@prefix tms: <https://kairos.cnext.eu/source/tms#> .
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .

tms:stops a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "stops" .

tms:stops_latitude a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable tms:stops ;
    kairos-bronze:columnName "latitude" ;
    kairos-bronze:dataType "decimal(9,6)" ;
    kairos-bronze:sampleValues "51.334217" .
""",
        encoding="utf-8",
    )

    report = run_source_privacy(source_dir)

    assert not report.passed
    assert {finding.kind for _, finding in report.findings} == {"location"}
    assert "location" in report.checked_kinds

    run_source_privacy(source_dir, fix=True)
    samples_raw = (source_dir / "stops.samples.yaml").read_text(encoding="utf-8")
    ttl_raw = (source_dir / "tms.vocabulary.ttl").read_text(encoding="utf-8")
    assert "51.334217" not in samples_raw
    assert "51.33" not in samples_raw
    assert "kind=location" in samples_raw
    assert "51.334217" not in ttl_raw
    assert "kind=location" in ttl_raw
    assert "open" in samples_raw  # non-coordinate values survive
    assert run_source_privacy(source_dir).passed


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


def test_generic_name_column_not_flagged_on_non_person_table(tmp_path):
    """A bare ``Name`` column on a table with no person/driver subject must not
    be flagged as PII by ``find_source_data_privacy_issues``.

    Regression: ``import-source`` called ``detect_sample_pii_kind`` without the
    table context that ``import-flatfile`` uses, so generic ``Name`` columns on
    tables such as ``TransportStop`` (value ``"Loading place"``) were false
    positives that blocked source import.
    """
    from kairos_ontology.core.source_privacy import find_source_data_privacy_issues
    from kairos_ontology.core._samples import detect_sample_pii_kind

    data = {
        "tables": [
            {
                "name": "TransportStop",
                "columns": [
                    {
                        "name": "Name",
                        "data_type": "nvarchar(100)",
                        "samples": ["Loading place", "Unloading place"],
                    }
                ],
            }
        ]
    }

    assert find_source_data_privacy_issues(data) == []
    assert detect_sample_pii_kind("Name", "Loading place", context_name="TransportStop") is None


class TestAnalyseSourcesPiiGate:
    """DD-166: analyse-sources must not ship unredacted samples to a third party.

    The module had no privacy check at all — redaction happened earlier, at import, and
    the send step trusted that ordering. Ordering is not a control.
    """

    def _hub(self, tmp_path):
        sources = tmp_path / "integration" / "sources" / "crm"
        sources.mkdir(parents=True)
        # A ref-models dir must exist: that check runs before the gate, and both are
        # pre-LLM, so the ordering does not matter for safety.
        refs = tmp_path / "ontology-reference-models"
        (refs / "accelerator-packs").mkdir(parents=True)
        return tmp_path / "integration" / "sources", refs

    def test_gate_blocks_and_names_no_values(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock, patch

        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli

        root, refs = self._hub(tmp_path)
        finding = MagicMock()
        finding.kind = "email"
        report = MagicMock()
        report.passed = False
        report.findings = [(root / "crm" / "crm.vocabulary.ttl", finding)]
        report.files_scanned = 1

        with patch("kairos_ontology.core.source_privacy.run_source_privacy", return_value=report):
            result = CliRunner().invoke(
                cli,
                [
                    "analyse-sources",
                    "--sources", str(root),
                    "--ref-models", str(refs),
                    "--accelerator", "logistics",
                ],
            )

        assert result.exit_code == 1, result.output
        assert "Refusing to send source samples" in result.output
        assert "email" in result.output
        assert "source-privacy --fix" in result.output

    def test_clean_sources_are_not_blocked_by_the_gate(self, tmp_path):
        """A passing scan must fall through; the gate is not allowed to be the failure."""
        from unittest.mock import MagicMock, patch

        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli

        root, refs = self._hub(tmp_path)
        report = MagicMock()
        report.passed = True
        report.findings = []
        report.files_scanned = 1

        with patch("kairos_ontology.core.source_privacy.run_source_privacy", return_value=report):
            result = CliRunner().invoke(
                cli,
                [
                    "analyse-sources",
                    "--sources", str(root),
                    "--ref-models", str(refs),
                    "--accelerator", "logistics",
                ],
            )

        assert "Refusing to send source samples" not in result.output
