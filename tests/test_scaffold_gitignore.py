# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for scaffold .gitignore behavior."""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _check_ignore(repo: Path, path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-v", path],
        check=False,
        capture_output=True,
        text=True,
    )


def _is_ignored(repo: Path, path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), "check-ignore", path],
        check=False,
        capture_output=True,
        text=True,
    )


def test_scaffold_gitignore_ignores_output_but_preserves_gitkeep(tmp_path: Path) -> None:
    template = REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "gitignore.template"
    (tmp_path / ".gitignore").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, capture_output=True)

    for root in ("ontology-hub-publish",):
        marker = tmp_path / root / "medallion" / "dbt" / ".gitkeep"
        generated = tmp_path / root / "medallion" / "dbt" / "dbt_project.yml"
        marker.parent.mkdir(parents=True)
        marker.write_text("", encoding="utf-8")
        generated.write_text("name: generated\n", encoding="utf-8")

        ignored = _check_ignore(tmp_path, generated.relative_to(tmp_path).as_posix())
        preserved = _is_ignored(tmp_path, marker.relative_to(tmp_path).as_posix())

        assert ignored.returncode == 0, ignored.stderr
        assert "ontology-hub-publish/**" in ignored.stdout
        assert preserved.returncode == 1


def test_scaffold_gitignore_ignores_import_directory(tmp_path: Path) -> None:
    """Raw client evidence in ``.import/`` must be gitignored (#453)."""
    template = REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "gitignore.template"
    (tmp_path / ".gitignore").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, capture_output=True)

    evidence = tmp_path / ".import" / "seed_sources.csv"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("col_a,col_b\n1,2\n", encoding="utf-8")

    ignored = _check_ignore(tmp_path, ".import/seed_sources.csv")
    assert ignored.returncode == 0, ignored.stderr


def test_scaffold_gitignore_ignores_nested_import_directory(tmp_path: Path) -> None:
    """#591: a nested ``.import/`` (e.g. a hub inside a monorepo) must also be
    ignored -- the raw-evidence pattern is depth-agnostic, not just top-level."""
    template = REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "gitignore.template"
    (tmp_path / ".gitignore").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, capture_output=True)

    evidence = tmp_path / "ontology-hub" / ".import" / "businessdiscovery" / "report.xlsx"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("x", encoding="utf-8")

    ignored = _check_ignore(tmp_path, evidence.relative_to(tmp_path).as_posix())
    assert ignored.returncode == 0, ignored.stderr


def test_scaffold_gitignore_tracks_import_modeling_directory(tmp_path: Path) -> None:
    """#591: ``.import/modeling/`` holds toolkit-managed, git-tracked OKF-style
    records (e.g. modeling-feedback) -- unlike the rest of ``.import/``, which stays
    gitignored raw client evidence."""
    template = REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "gitignore.template"
    (tmp_path / ".gitignore").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, capture_output=True)

    feedback = tmp_path / ".import" / "modeling" / "feedback" / "HUB-FB-20260823-abc123.md"
    feedback.parent.mkdir(parents=True)
    feedback.write_text("x", encoding="utf-8")
    evidence = tmp_path / ".import" / "businessdiscovery" / "report.xlsx"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("x", encoding="utf-8")

    tracked = _is_ignored(tmp_path, feedback.relative_to(tmp_path).as_posix())
    ignored = _is_ignored(tmp_path, evidence.relative_to(tmp_path).as_posix())
    assert tracked.returncode == 1, tracked.stdout
    assert ignored.returncode == 0, ignored.stdout
