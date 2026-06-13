# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the import-results session file writer."""

from __future__ import annotations

from pathlib import Path

from kairos_ontology.import_session import (
    IMPORT_SESSION_DIR,
    render_import_session_md,
    write_import_session,
)
from kairos_ontology.import_source import ChangeReport, ColumnChange

TABLES = [
    {"name": "customer", "columns": [{"name": "id"}, {"name": "name"}]},
    {"name": "order", "columns": [{"name": "id"}]},
]


def test_render_flatfile_happy_path():
    md = render_import_session_md(
        "erp",
        "flatfile",
        TABLES,
        output_paths=["integration/sources/erp"],
        next_step="Run import-source",
        toolkit_version="9.9.9",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    assert "# Source Import Results: erp" in md
    assert "**Import method:** flatfile" in md
    assert "**Toolkit version:** 9.9.9" in md
    assert "| 1 | customer | 2 |" in md
    assert "| 2 | order | 1 |" in md
    assert "## Next Steps" in md
    assert "Run import-source" in md
    # flatfile has no change report section
    assert "## Change Report" not in md


def test_render_import_source_fresh():
    md = render_import_session_md("nms", "yaml-import", TABLES, change_report=None)
    assert "## Change Report" in md
    assert "Fresh vocabulary generated" in md


def test_render_import_source_with_changes():
    report = ChangeReport(
        added_tables=["invoice"],
        added_columns=[ColumnChange(table="customer", column="email", change_type="added")],
        type_changes=[
            ColumnChange(
                table="customer",
                column="id",
                change_type="type_changed",
                old_value="int",
                new_value="bigint",
            )
        ],
    )
    md = render_import_session_md(
        "nms", "yaml-import", TABLES, change_report=report, enrich=True
    )
    assert "**New tables:** invoice" in md
    assert "**Added columns:** customer.email" in md
    assert "customer.id: int → bigint" in md
    assert "## Enrichment" in md


def test_render_no_changes():
    report = ChangeReport()
    md = render_import_session_md("nms", "yaml-import", TABLES, change_report=report)
    assert "No changes — vocabulary already in sync." in md


def test_render_empty_tables():
    md = render_import_session_md("erp", "flatfile", [])
    assert "| - | _(none)_ | 0 |" in md


def test_write_import_session_creates_file(tmp_path: Path):
    out = write_import_session(
        tmp_path,
        "erp",
        "flatfile",
        TABLES,
        output_paths=["integration/sources/erp"],
    )
    assert out is not None
    assert out.parent == tmp_path / IMPORT_SESSION_DIR
    assert out.name.startswith("import-erp-")
    assert out.suffix == ".md"
    content = out.read_text(encoding="utf-8")
    assert "# Source Import Results: erp" in content


def test_write_import_session_overwrites_same_day(tmp_path: Path):
    first = write_import_session(tmp_path, "erp", "flatfile", TABLES)
    second = write_import_session(tmp_path, "erp", "flatfile", TABLES)
    assert first == second
    assert len(list((tmp_path / IMPORT_SESSION_DIR).glob("import-erp-*.md"))) == 1


def test_write_import_session_skips_without_hub():
    assert write_import_session(None, "erp", "flatfile", TABLES) is None


def test_run_import_flatfile_writes_session(tmp_path: Path, monkeypatch):
    # Build a minimal hub (model/ontologies/ marks the hub root).
    hub = tmp_path / "hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    csv = tmp_path / "customers.csv"
    csv.write_text("id,name\n1,acme\n2,globex\n", encoding="utf-8")

    monkeypatch.chdir(hub)

    from kairos_ontology.import_flatfile import run_import_flatfile

    run_import_flatfile(source_path=csv, system_name="erp")

    sessions = list((hub / IMPORT_SESSION_DIR).glob("import-erp-*.md"))
    assert len(sessions) == 1
    assert "**Import method:** flatfile" in sessions[0].read_text(encoding="utf-8")
