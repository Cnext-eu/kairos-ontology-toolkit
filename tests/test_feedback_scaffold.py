# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the scaffolded modeling-feedback bundle (issue #588)."""

import shutil
from pathlib import Path

from kairos_ontology.cli.shared import _SCAFFOLD_DIR, _managed_scaffold_map
from kairos_ontology.core.feedback_records import build_index_markdown, validate_feedback_bundle

FEEDBACK_SCAFFOLD = _SCAFFOLD_DIR / "import" / "businessdiscovery" / "insights"


def test_feedback_scaffold_source_files_exist() -> None:
    assert (FEEDBACK_SCAFFOLD / "README.md").is_file()
    assert (FEEDBACK_SCAFFOLD / "FEEDBACK-template.md.template").is_file()
    assert (FEEDBACK_SCAFFOLD / "index.md").is_file()
    assert (FEEDBACK_SCAFFOLD / "index.md").read_text(encoding="utf-8") == build_index_markdown([])


def test_feedback_scaffold_managed_registry_entries() -> None:
    managed = _managed_scaffold_map()

    assert ".import/businessdiscovery/insights/README.md" in managed
    assert ".import/businessdiscovery/insights/FEEDBACK-template.md.template" in managed
    assert ".import/businessdiscovery/insights/index.md" not in managed


def test_empty_feedback_scaffold_validates_cleanly(tmp_path: Path) -> None:
    insights = tmp_path / "insights"
    shutil.copytree(FEEDBACK_SCAFFOLD, insights)

    result = validate_feedback_bundle(insights)

    assert result.errors == []
    assert result.records == []
