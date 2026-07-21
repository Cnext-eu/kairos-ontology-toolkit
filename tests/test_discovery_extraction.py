# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for per-document business-discovery extraction tracking (DD-060)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.discovery_extraction import (
    EXTRACTION_VERSION,
    DiscoveryStatusReport,
    check_discovery_docs,
    extraction_filename,
    iter_discovery_documents,
    load_extraction,
    normalize_source_key,
    slugify_source_name,
    source_relative_path,
    write_extraction,
)
from kairos_ontology.core.inventory import compute_source_hash


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
        ("Process Flow.PNG", "process-flow-png"),
    ],
)
def test_slugify_source_name(name, expected):
    assert slugify_source_name(name) == expected


def test_extraction_filename_suffix():
    assert extraction_filename("Abbreviations.pdf") == "abbreviations-pdf.extraction.yaml"
    assert extraction_filename("Process Flow.PNG") == "process-flow-png.extraction.yaml"


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
    _make_doc(imp, "process-flow.png")
    _make_doc(imp, "README.md")
    _make_doc(imp, ".hidden")
    (imp / "subdir").mkdir()
    docs = [p.name for p in iter_discovery_documents(imp)]
    assert docs == ["a.pdf", "process-flow.png"]


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


# --------------------------------------------------------------------------- #
# Nested (recursive) discovery — DD-060 recursive support
# --------------------------------------------------------------------------- #
def _write_extraction_rel(
    rel: str,
    extraction_dir: Path,
    *,
    sha: str | None,
    source_path: str | None = None,
    filename: str | None = None,
) -> Path:
    """Write an extraction record using canonical relative-path provenance."""
    stored = source_path if source_path is not None else f".import/businessdiscovery/{rel}"
    data = {
        "version": EXTRACTION_VERSION,
        "source_file": Path(rel).name,
        "source_path": stored,
        "source_sha256": sha,
        "strategy": "company-terminology-v1",
        "summary": "test",
        "extracted_terms": [],
        "status": "processed",
    }
    name = filename or extraction_filename(rel, relative_path=rel)
    return write_extraction(data, extraction_dir / name)


def test_iter_discovery_documents_recursive_and_ordered(tmp_path):
    imp = tmp_path / "import"
    _make_doc(imp, "top.pdf")
    _make_doc(imp / "sub", "b.pdf")
    _make_doc(imp / "sub", "a.pdf")
    _make_doc(imp / "deep" / "nested", "c.pdf")
    rels = [source_relative_path(p, imp) for p in iter_discovery_documents(imp)]
    assert rels == ["deep/nested/c.pdf", "sub/a.pdf", "sub/b.pdf", "top.pdf"]


def test_iter_skips_nested_readme_and_dotdirs(tmp_path):
    imp = tmp_path / "import"
    _make_doc(imp, "keep.pdf")
    _make_doc(imp / "sub", "README.md")
    _make_doc(imp / "sub", "real.pdf")
    _make_doc(imp / ".git", "config")
    _make_doc(imp / "sub" / ".hidden", "secret.pdf")
    rels = [source_relative_path(p, imp) for p in iter_discovery_documents(imp)]
    assert rels == ["keep.pdf", "sub/real.pdf"]


def test_extraction_filename_nested_is_collision_safe():
    # Same basename in different folders → distinct extraction files.
    a = extraction_filename("a.pdf", relative_path="sub1/a.pdf")
    b = extraction_filename("a.pdf", relative_path="sub2/a.pdf")
    assert a != b
    assert a.endswith(".extraction.yaml")
    # Slug-collision resistance: different paths that slugify alike stay distinct.
    x = extraction_filename("b.pdf", relative_path="a/b.pdf")
    y = extraction_filename("b.pdf", relative_path="a-b.pdf")  # top-level, basename-based
    assert x != y


def test_extraction_filename_nested_stays_within_component_limit():
    rel = "/".join(["deeply-nested-folder"] * 20) + "/document.pdf"
    name = extraction_filename("document.pdf", relative_path=rel)
    assert len(name.encode("utf-8")) <= 255
    assert name.endswith(".extraction.yaml")


def test_extraction_filename_toplevel_backward_compatible():
    # A top-level relative path keeps the legacy basename-derived filename.
    assert extraction_filename("doc.pdf", relative_path="doc.pdf") == "doc-pdf.extraction.yaml"
    assert extraction_filename("doc.pdf") == "doc-pdf.extraction.yaml"


def test_normalize_source_key_variants(tmp_path):
    imp = tmp_path / "import"
    imp.mkdir(parents=True)
    assert normalize_source_key(".import/businessdiscovery/sub/a.pdf", imp) == "sub/a.pdf"
    assert normalize_source_key(r".import\businessdiscovery\sub\a.pdf", imp) == "sub/a.pdf"
    doc = _make_doc(imp / "sub", "a.pdf")
    assert normalize_source_key(str(doc), imp) == "sub/a.pdf"
    assert normalize_source_key("", imp) is None


def test_nested_ok_matched_by_source_path(tmp_path):
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    doc = _make_doc(imp / "sub", "report.pdf")
    _write_extraction_rel("sub/report.pdf", ext, sha=compute_source_hash(doc))
    report = check_discovery_docs(import_dir=imp, extraction_dir=ext)
    assert report.ok == ["sub/report.pdf"]
    assert report.orphan == []
    assert report.has_warnings is False


def test_nested_matched_with_windows_separators_in_provenance(tmp_path):
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    doc = _make_doc(imp / "sub", "report.pdf")
    _write_extraction_rel(
        "sub/report.pdf",
        ext,
        sha=compute_source_hash(doc),
        source_path=r".import\businessdiscovery\sub\report.pdf",
    )
    report = check_discovery_docs(import_dir=imp, extraction_dir=ext)
    assert report.ok == ["sub/report.pdf"]
    assert report.orphan == []


def test_nested_changed_and_unprocessed(tmp_path):
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    changed_doc = _make_doc(imp / "sub", "c.pdf", content=b"orig")
    _write_extraction_rel("sub/c.pdf", ext, sha=compute_source_hash(changed_doc))
    changed_doc.write_bytes(b"different")
    _make_doc(imp / "sub", "new.pdf")  # no extraction
    report = check_discovery_docs(import_dir=imp, extraction_dir=ext)
    assert report.changed == ["sub/c.pdf"]
    assert report.unprocessed == ["sub/new.pdf"]
    assert report.has_work is True


def test_nested_unverifiable(tmp_path):
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    _make_doc(imp / "sub", "d.pdf")
    _write_extraction_rel("sub/d.pdf", ext, sha=None)
    report = check_discovery_docs(import_dir=imp, extraction_dir=ext)
    assert report.unverifiable == ["sub/d.pdf"]
    assert report.has_warnings is True


def test_nested_valid_record_not_reported_orphan(tmp_path):
    # Regression: a valid nested extraction must not be orphaned just because
    # the source lives in a subfolder.
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    doc = _make_doc(imp / "workbooks", "big.xlsx")
    _write_extraction_rel("workbooks/big.xlsx", ext, sha=compute_source_hash(doc))
    report = check_discovery_docs(import_dir=imp, extraction_dir=ext)
    assert report.orphan == []
    assert report.ok == ["workbooks/big.xlsx"]


def test_legacy_basename_extraction_matches_only_its_nested_provenance(tmp_path):
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    first = _make_doc(imp / "one", "same.pdf")
    _make_doc(imp / "two", "same.pdf")
    _write_extraction_rel(
        "one/same.pdf",
        ext,
        sha=compute_source_hash(first),
        filename=extraction_filename("same.pdf"),
    )

    report = check_discovery_docs(import_dir=imp, extraction_dir=ext)

    assert report.unprocessed == ["two/same.pdf"]
    assert report.ok == ["one/same.pdf"]
    assert report.orphan == []


def test_truly_orphan_nested_extraction_still_flagged(tmp_path):
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    imp.mkdir(parents=True)
    _write_extraction_rel("sub/gone.pdf", ext, sha="abc")
    report = check_discovery_docs(import_dir=imp, extraction_dir=ext)
    assert len(report.orphan) == 1
    assert report.ok == []


def test_conflicting_provenance_detected(tmp_path):
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    doc = _make_doc(imp / "sub", "e.pdf")
    sha = compute_source_hash(doc)
    _write_extraction_rel("sub/e.pdf", ext, sha=sha, filename="first.extraction.yaml")
    _write_extraction_rel("sub/e.pdf", ext, sha=sha, filename="second.extraction.yaml")
    report = check_discovery_docs(import_dir=imp, extraction_dir=ext)
    assert report.conflict == ["sub/e.pdf"]
    assert report.orphan == []  # both consumed, neither dangling
    assert report.has_warnings is True


def test_legacy_toplevel_record_preserved(tmp_path):
    # A pre-existing top-level record written with the legacy basename filename
    # and no usable source_path is still matched by filename.
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    doc = _make_doc(imp, "legacy.pdf")
    _write_extraction_for(doc, ext, sha=compute_source_hash(doc))
    report = check_discovery_docs(import_dir=imp, extraction_dir=ext)
    assert report.ok == ["legacy.pdf"]
    assert report.orphan == []


def test_cli_discovery_status_reports_nested_path(tmp_path):
    imp = tmp_path / "import"
    ext = tmp_path / "_extractions"
    _make_doc(imp / "sub", "new.pdf")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discovery-status", "--import-dir", str(imp), "--extraction-dir", str(ext)],
    )
    assert result.exit_code == 0
    assert "sub/new.pdf" in result.output
