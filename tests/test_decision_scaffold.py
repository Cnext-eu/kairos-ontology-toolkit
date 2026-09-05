# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the scaffolded OKF decision-log bundle."""

import shutil
from pathlib import Path

from kairos_ontology.cli.shared import _SCAFFOLD_DIR, _managed_scaffold_map
from kairos_ontology.core.decision_records import build_index_markdown, validate_decision_bundle

DECISION_SCAFFOLD = _SCAFFOLD_DIR / "ontology-hub" / "decisions"


def test_decision_scaffold_source_files_exist() -> None:
    assert (DECISION_SCAFFOLD / "README.md").is_file()
    assert (DECISION_SCAFFOLD / "HUB-DD-template.md.template").is_file()
    assert (DECISION_SCAFFOLD / "index.md").is_file()
    assert (DECISION_SCAFFOLD / "index.md").read_text(encoding="utf-8") == build_index_markdown([])


def test_decision_scaffold_managed_registry_entries() -> None:
    managed = _managed_scaffold_map()

    assert "ontology-hub/decisions/README.md" in managed
    assert "ontology-hub/decisions/HUB-DD-template.md.template" in managed
    assert "ontology-hub/decisions/index.md" not in managed


def test_empty_decision_scaffold_validates_cleanly(tmp_path: Path) -> None:
    decisions = tmp_path / "decisions"
    shutil.copytree(DECISION_SCAFFOLD, decisions)

    result = validate_decision_bundle(decisions)

    assert result.errors == []
    assert result.records == []
