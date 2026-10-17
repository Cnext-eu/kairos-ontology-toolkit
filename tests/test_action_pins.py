# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Every GitHub Action a scaffolded workflow uses is pinned to a commit SHA (#1124).

A tag can be moved by whoever controls the action's repository, so a tag ref lets them
change the code that runs in a hub's or dataplatform's CI -- including jobs holding Azure
credentials and a hub-repository token. Security scanners fail the pull request on it, and
a repo cannot fix it locally: the workflows are managed, so an edit is either overwritten
by the next refresh or turns the file into a declared customization.

The superseded generations under ``scaffold/superseded-workflows/`` keep their tag refs on
purpose: they are the bytes older repos hold, recorded so those repos stay refreshable.
"""

from __future__ import annotations

import re

import pytest

from kairos_ontology.cli.shared import _SCAFFOLD_DIR

_USES = re.compile(r"^\s*(?:-\s+)?uses:\s+(?P<ref>\S+)(?P<rest>.*)$")
_PINNED = re.compile(r"^(?P<action>[\w.-]+/[\w.-]+(?:/[\w./-]+)?)@(?P<sha>[0-9a-f]{40})$")
_VERSION_COMMENT = re.compile(r"^ # (?P<tag>v\d+\.\d+\.\d+)$")


def _pin_problem(ref: str, rest: str) -> str | None:
    """Return why a ``uses:`` reference is not acceptable, or ``None`` when it is."""
    if ref.startswith("./"):
        return None  # a reusable workflow in the same repository
    if not _PINNED.match(ref):
        return f"{ref} is not pinned to a 40-character commit SHA"
    if not _VERSION_COMMENT.match(rest):
        return f"{ref} has no `# vX.Y.Z` comment naming the release it pins"
    return None


def _live_uses() -> list[tuple[str, int, str, str]]:
    """Every ``uses:`` line in the live scaffold, superseded generations excluded."""
    superseded = _SCAFFOLD_DIR / "superseded-workflows"
    found = []
    for path in sorted(_SCAFFOLD_DIR.rglob("*")):
        if not path.is_file() or path.is_relative_to(superseded):
            continue
        if path.suffix not in {".yml", ".yaml", ".template"}:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = _USES.match(line)
            if match:
                relative = path.relative_to(_SCAFFOLD_DIR).as_posix()
                found.append((relative, number, match["ref"], match["rest"]))
    return found


def test_the_scaffold_has_workflows_to_check():
    assert len(_live_uses()) > 20


def test_every_action_is_pinned_to_a_commit_sha():
    problems = [
        f"{path}:{line}: {problem}"
        for path, line, ref, rest in _live_uses()
        if (problem := _pin_problem(ref, rest))
    ]
    assert not problems, "\n".join(problems)


def test_one_action_is_pinned_to_one_release_everywhere():
    """A bump must reach every template, or two workflows run different code."""
    pins: dict[str, set[tuple[str, str]]] = {}
    for _path, _line, ref, rest in _live_uses():
        pinned = _PINNED.match(ref)
        comment = _VERSION_COMMENT.match(rest)
        if pinned and comment:
            pins.setdefault(pinned["action"], set()).add((pinned["sha"], comment["tag"]))
    assert pins
    mixed = {action: sorted(seen) for action, seen in pins.items() if len(seen) > 1}
    assert not mixed, mixed


@pytest.mark.parametrize(
    ("ref", "rest"),
    [
        ("astral-sh/setup-uv@v10.0.1", ""),
        ("actions/checkout@v4", " # v4.4.0"),
        ("azure/login@7184910", " # v2.3.1"),
        ("actions/checkout@11d5960a326750d5838078e36cf38b85af677262", ""),
        ("actions/checkout@11d5960a326750d5838078e36cf38b85af677262", " # v4"),
        ("actions/checkout@11D5960A326750D5838078E36CF38B85AF677262", " # v4.4.0"),
    ],
)
def test_tag_refs_and_unlabelled_shas_are_rejected(ref, rest):
    assert _pin_problem(ref, rest) is not None


@pytest.mark.parametrize(
    ("ref", "rest"),
    [
        ("actions/checkout@11d5960a326750d5838078e36cf38b85af677262", " # v4.4.0"),
        ("./.github/workflows/deploy-powerbi-semantic-model.yml", ""),
    ],
)
def test_sha_pins_and_local_workflows_are_accepted(ref, rest):
    assert _pin_problem(ref, rest) is None


def test_superseded_generations_are_not_held_to_the_rule():
    """Older repos hold tag refs; their recorded bytes must stay exactly as shipped."""
    superseded = _SCAFFOLD_DIR / "superseded-workflows"
    old = [
        line
        for path in superseded.rglob("*.template")
        for line in path.read_text(encoding="utf-8").splitlines()
        if "uses: astral-sh/setup-uv@v10.0.1" in line
    ]
    assert old, "expected the pre-#1124 generations to keep their tag refs"
