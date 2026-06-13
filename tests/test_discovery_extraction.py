# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for per-document business-discovery extraction tracking (DD-060)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.discovery_extraction import (
    EXTRACTION_VERSION,
    DiscoveryStatusReport,
    check_discovery_docs,
    extraction_filename,
    iter_discovery_documents,
    load_extraction,
    slugify_source_name,
    write_extraction,
)
from kairos_ontology.inventory import compute_source_hash


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_doc(directory: Path, name: str, content: bytes = b"hello") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / name
    p.write_bytes(content)
    return p


def _write_extraction_for(doc: Path, extraction_dir: Path, *, sha: str | None) -> Path:
    data = {
        "version": EXTRACTION_VERSION,
        "source_file": doc.name,
        "source_path": str(doc),
        "source_sha256": sha,
        "strategy": "company-terminology-v1",
        "summary": "test",
        "extracted_terms": [],
        "status": "processed",
    }
    return write_extraction(data, extraction_dir / extraction_filename(doc))


# --------------------------------------------------------------------------- #
# slugify / filename
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name,expected",
    [
        ("Abbreviations.pdf", "abbreviations-pdf"),
        ("Cargo Glossary.PDF", "cargo-glossary-pdf"),
        ("weird__name!!.docx", "weird-name-docx"),
        ("report.pdf", "report-pdf"),
        ("report.docx", "report-docx"),
    ],
)
def test_slugify_source_name(name, expected):
    assert slugify_source_name(name) == expected


def test_extraction_filename_suffix():
    assert extraction_filename("Abbreviations.pdf") == "abbreviations-pdf.extraction.yaml"


def test_same_stem_different_ext_no_collision():
    assert extraction_filename("report.pdf") != extraction_filename("report.docx")


# --------------------------------------------------------------------------- #
# write / load round-trip
# --------------------------------------------------------------------------- #
def test_write_load_round_trip(tmp_path):
    doc = _make_doc(tmp_path / "import", "doc.pdf")
    out = _write_extraction_for(doc, tmp_path / "_extractions", sha=compute_source_hash(doc))
    assert out.exists()
    loaded = load_extraction(out)
    assert loaded["source_file"] == "doc.pdf"
    assert loaded["version"] == EXTRACTION_VERSION
    # YAML is real YAML, not string-concatenated
    raw = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert raw["status"] == "processed"


def test_load_extraction_rejects_non_mapping(tmp_path):
    bad = tmp_path / "bad.extraction.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_extraction(bad)


# --------------------------------------------------------------------------- #
# document discovery
# --------------------------------------------------------------------------- #
def test_iter_discovery_documents_filters(tmp_path):
    imp = tmp_path / "import"
    _make_doc(imp, "a.pdf")
    _make_doc(imp, "README.md")
    _make_doc(imp, ".hidden")
    (imp / "subdir").mkdir()
    docs = [p.name for p in iter_discovery_documents(imp)]
    assert docs == ["a.pdf"]


def test_iter_discovery_documents_missing_dir(tmp_path):
    assert iter_discovery_documents(tmp_path / "nope") == []


# --------------------------------------------------------------------------- #
# check_discovery_docs classification
# --------------------------------------------------------------------------- #
def test_check_unprocessed(tmp_path):
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    _make_doc(imp, "new.pdf")
    report = check_discovery_docs(import_dir=imp, extraction_dir=ext)
    assert report.unprocessed == ["new.pdf"]
    assert report.has_work is True


def test_check_ok(tmp_path):
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    doc = _make_doc(imp, "doc.pdf")
    _write_extraction_for(doc, ext, sha=compute_source_hash(doc))
    report = check_discovery_docs(import_dir=imp, extraction_dir=ext)
    assert report.ok == ["doc.pdf"]
    assert report.has_work is False
    assert report.has_warnings is False


def test_check_changed(tmp_path):
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    doc = _make_doc(imp, "doc.pdf", content=b"original")
    _write_extraction_for(doc, ext, sha=compute_source_hash(doc))
    doc.write_bytes(b"modified content")  # hash now differs
    report = check_discovery_docs(import_dir=imp, extraction_dir=ext)
    assert report.changed == ["doc.pdf"]
    assert report.has_work is True


def test_check_unverifiable(tmp_path):
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    doc = _make_doc(imp, "doc.pdf")
    _write_extraction_for(doc, ext, sha=None)  # no stored hash
    report = check_discovery_docs(import_dir=imp, extraction_dir=ext)
    assert report.unverifiable == ["doc.pdf"]
    assert report.has_warnings is True
    assert report.has_work is False


def test_check_orphan(tmp_path):
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    imp.mkdir(parents=True)
    ext.mkdir(parents=True)
    (ext / "ghost-pdf.extraction.yaml").write_text(
        "version: '1.0'\nsource_sha256: abc\n", encoding="utf-8"
    )
    report = check_discovery_docs(import_dir=imp, extraction_dir=ext)
    assert report.orphan == ["ghost-pdf.extraction.yaml"]
    assert report.has_warnings is True


def test_report_defaults_empty():
    r = DiscoveryStatusReport()
    assert not r.has_work
    assert not r.has_warnings


# --------------------------------------------------------------------------- #
# CLI: discovery-status
# --------------------------------------------------------------------------- #
def test_cli_discovery_status_ok(tmp_path):
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    doc = _make_doc(imp, "doc.pdf")
    _write_extraction_for(doc, ext, sha=compute_source_hash(doc))
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discovery-status", "--import-dir", str(imp), "--extraction-dir", str(ext)],
    )
    assert result.exit_code == 0
    assert "up to date" in result.output


def test_cli_discovery_status_strict_blocks_on_new(tmp_path):
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    _make_doc(imp, "new.pdf")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "discovery-status",
            "--import-dir", str(imp),
            "--extraction-dir", str(ext),
            "--strict",
        ],
    )
    assert result.exit_code == 1
    assert "NEW" in result.output


def test_cli_discovery_status_warn_only_never_blocks(tmp_path):
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    _make_doc(imp, "new.pdf")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "discovery-status",
            "--import-dir", str(imp),
            "--extraction-dir", str(ext),
            "--strict",
            "--warn-only",
        ],
    )
    assert result.exit_code == 0


def test_cli_discovery_status_no_import_dir(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "discovery-status",
            "--import-dir", str(tmp_path / "missing"),
            "--extraction-dir", str(tmp_path / "ext"),
        ],
    )
    assert result.exit_code == 0
    assert "nothing to process" in result.output
