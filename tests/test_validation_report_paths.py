# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""`validation-report.json` carries repo-relative paths, not machine-local ones (#822).

The report embedded the resolved absolute path of every ontology file:

    "file": "G:\\\\Git\\\\Client-Ontology-Hub\\\\ontology-hub\\\\model\\\\ontologies\\\\customs.ttl"

Two costs. It leaks the developer's filesystem layout into an artifact routinely pasted
into issues, PRs and support threads. And a hub that deliberately tracks the report -- a
per-hub decision the gitignore template explicitly allows -- saw ~130 lines rewrite on
every other checkout, so the file ping-ponged between contributors.

Paths are now rendered against the repo root with forward slashes, which is how
`_dangling_refs` and the drift gate already report, and is what a reviewer can click.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kairos_ontology.core.validator import run_validation

_HUB = Path(__file__).parent / "scenarios" / "v5-hub"


def _reported_paths(document) -> set[str]:
    """Every path-shaped value in the report, including the dict *keys* under
    `shacl.semantic_context` -- which are file paths too, and were missed by a first pass
    that only looked at `"file"` values."""
    found: set[str] = set()
    if isinstance(document, dict):
        for key, value in document.items():
            if key == "file" and isinstance(value, str):
                found.add(value)
            if isinstance(key, str) and key.endswith(".ttl"):
                found.add(key)
            found |= _reported_paths(value)
    elif isinstance(document, list):
        for item in document:
            found |= _reported_paths(item)
    return found


def _run(tmp_path: Path, *, repo_root: Path | None) -> dict:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(_HUB, repo / "ontology-hub")
    report = repo / "report.json"
    hub = repo / "ontology-hub"
    try:
        run_validation(
            ontologies_path=hub / "model" / "ontologies",
            shapes_path=hub / "model" / "shapes",
            catalog_path=hub / "catalog-v001.xml",
            do_syntax=True,
            do_shacl=True,
            do_consistency=False,
            report_path=report,
            repo_root=repo_root if repo_root is None else repo,
        )
    except SystemExit:
        pass  # the fixture hub has authoring findings; the report is what matters here
    return json.loads(report.read_text(encoding="utf-8"))


def _looks_absolute(path: str) -> bool:
    return path.startswith("/") or (len(path) > 1 and path[1] == ":")


def test_no_reported_path_is_absolute(tmp_path):
    paths = _reported_paths(_run(tmp_path, repo_root=tmp_path))
    assert paths, "the fixture produced no path-bearing findings; the test proves nothing"
    assert not [item for item in paths if _looks_absolute(item)], sorted(paths)


def test_paths_are_anchored_at_the_repo_root(tmp_path):
    """Repo-relative rather than hub-relative: `ontology-hub/model/...` matches how the
    drift gate and the dbt ref scan report, and is clickable in a pull request."""
    paths = _reported_paths(_run(tmp_path, repo_root=tmp_path))
    assert all(item.startswith("ontology-hub/") for item in paths), sorted(paths)


def test_paths_use_forward_slashes(tmp_path):
    r"""`.as_posix()` unconditionally: a `str()` of a relative Windows path still contains
    backslashes and would differ across platforms, defeating the comparability this is for."""
    paths = _reported_paths(_run(tmp_path, repo_root=tmp_path))
    assert not [item for item in paths if "\\" in item], sorted(paths)


def test_a_library_caller_passing_no_root_keeps_the_previous_output(tmp_path):
    """`run_validation` is a documented library entry point with direct callers, so the
    new argument defaults to off rather than changing their output."""
    paths = _reported_paths(_run(tmp_path, repo_root=None))
    assert paths
    assert all(_looks_absolute(item) for item in paths), sorted(paths)


@pytest.mark.parametrize("outside", [True, False])
def test_a_file_outside_the_repo_falls_back_rather_than_raising(tmp_path, outside):
    """`relative_to` raises for a path outside the anchor. A report is diagnostic output;
    it must not be the thing that fails the run."""
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(_HUB, repo / "ontology-hub")
    anchor = repo if not outside else tmp_path / "somewhere-else"
    report = repo / "report.json"
    hub = repo / "ontology-hub"
    try:
        run_validation(
            ontologies_path=hub / "model" / "ontologies",
            shapes_path=hub / "model" / "shapes",
            catalog_path=hub / "catalog-v001.xml",
            do_syntax=True,
            do_shacl=False,
            do_consistency=False,
            report_path=report,
            repo_root=anchor,
        )
    except SystemExit:
        pass
    assert report.is_file()
    paths = _reported_paths(json.loads(report.read_text(encoding="utf-8")))
    assert paths
    if outside:
        # The fallback is the absolute path, not a `../..` climb out of the anchor.
        assert all(Path(p).is_absolute() and ".." not in Path(p).parts for p in paths), paths
    else:
        assert all(not Path(p).is_absolute() for p in paths), paths


def test_the_markdown_sibling_is_repo_relative_too(tmp_path: Path):
    """#822 fixed the JSON report; the Markdown one written beside it by default still
    embedded the absolute checkout path in its options table and its file list."""
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(_HUB, repo / "ontology-hub")
    hub = repo / "ontology-hub"
    markdown = repo / "report.md"
    try:
        run_validation(
            ontologies_path=hub / "model" / "ontologies",
            shapes_path=hub / "model" / "shapes",
            catalog_path=hub / "catalog-v001.xml",
            do_syntax=True,
            do_shacl=False,
            do_consistency=False,
            report_path=repo / "report.json",
            markdown_report_path=markdown,
            repo_root=repo,
        )
    except SystemExit:
        pass
    text = markdown.read_text(encoding="utf-8")
    assert str(repo) not in text
    assert str(repo.resolve()) not in text
    assert "`ontology-hub/model/ontologies/party.ttl`" in text
    assert "| `ontologies` | ontology-hub/model/ontologies |" in text
