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
    """Projection targets outside the dbt+Power BI release lane (DD-206) stay
    ignored by the blanket ``ontology-hub-publish/**`` pattern, with only their
    directory-marker ``.gitkeep`` preserved."""
    template = REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "gitignore.template"
    (tmp_path / ".gitignore").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, capture_output=True)

    for root in ("ontology-hub-publish",):
        marker = tmp_path / root / "neo4j" / ".gitkeep"
        generated = tmp_path / root / "neo4j" / "graph.cypher"
        marker.parent.mkdir(parents=True)
        marker.write_text("", encoding="utf-8")
        generated.write_text("CREATE (n)\n", encoding="utf-8")

        ignored = _check_ignore(tmp_path, generated.relative_to(tmp_path).as_posix())
        preserved = _is_ignored(tmp_path, marker.relative_to(tmp_path).as_posix())

        assert ignored.returncode == 0, ignored.stderr
        assert "ontology-hub-publish/**" in ignored.stdout
        assert preserved.returncode == 1


def test_scaffold_gitignore_tracks_only_the_dbt_package(tmp_path: Path) -> None:
    """The dbt package is the one tracked lane; everything else is ignored.

    It has to be: a dataplatform consumes it as a dbt package pinned by ``git`` +
    ``revision`` + ``subdirectory``, which ``dbt deps`` resolves out of the committed
    tree at that tag -- untracked, the path does not exist at the revision. The Power BI
    PBIP output used to be tracked too, but ``package-powerbi-release`` renders and zips
    it in CI from the compile plan, so nothing needs it committed.
    """
    template = REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "gitignore.template"
    (tmp_path / ".gitignore").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, capture_output=True)

    root = tmp_path / "ontology-hub-publish"
    dbt_file = root / "medallion" / "dbt" / "dbt_project.yml"
    ignored_lanes = {
        "powerbi": root / "powerbi" / "party" / "definition.pbism",
        "neo4j": root / "neo4j" / "graph.cypher",
        "reports": root / "reports" / "details" / "party.md",
    }
    for path in (dbt_file, *ignored_lanes.values()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated\n", encoding="utf-8")

    tracked = _is_ignored(tmp_path, dbt_file.relative_to(tmp_path).as_posix())
    assert tracked.returncode == 1, f"the dbt package must stay tracked: {tracked.stdout}"

    for lane, path in ignored_lanes.items():
        ignored = _check_ignore(tmp_path, path.relative_to(tmp_path).as_posix())
        assert ignored.returncode == 0, f"{lane} is tracked: {ignored.stderr}"


def test_erds_live_in_the_tracked_hub_tree(tmp_path: Path) -> None:
    """The ERDs moved into ``ontology-hub/model/contracts/diagrams`` precisely so they
    stay reviewable once the publish root is ignored in full -- nothing in the template
    may ignore them."""
    template = REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "gitignore.template"
    (tmp_path / ".gitignore").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, capture_output=True)

    diagrams = tmp_path / "ontology-hub" / "model" / "contracts" / "diagrams"
    diagrams.mkdir(parents=True)
    for name in (
        "party-erd.mmd",
        "party-gold-erd.mmd",
        "party-contract-erd.mmd",
        "master-erd.mmd",
        "master-gold-erd.mmd",
    ):
        (diagrams / name).write_text("erDiagram\n", encoding="utf-8")
        tracked = _is_ignored(tmp_path, (diagrams / name).relative_to(tmp_path).as_posix())
        assert tracked.returncode == 1, f"{name} is ignored: {tracked.stdout}"


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
