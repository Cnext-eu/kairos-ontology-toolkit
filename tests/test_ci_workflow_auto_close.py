# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Static meta-test for the auto-close-issues workflow (issue #578).

``.github/workflows/auto-close-issues.yml`` closes issues referenced in a
merged PR's parenthetical groups ("(#123)"). Two incidents shaped its logic:

* PR #425 closed deliberately-deferred follow-ups ("deferred to #422") — fixed
  by only closing *parenthetical* references not preceded by a non-fixing word.
* PR #577 ("(DD-203, #562 P2)") closed #562 even though only Problem 2 of a
  four-problem issue was fixed — fixed by skipping references with a
  partial-fix qualifier directly after the number (P2, P3+P4, "Problem 2").

CI is Python-only, so the workflow's inline JavaScript never runs under test.
Instead this test extracts the regex literals from the workflow file text
(pinning the workflow to this test — drift fails loudly), ports them to
Python ``re`` (the patterns are syntax-compatible), and reimplements the
decision loop as a pure function exercised against the exact incidents.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "auto-close-issues.yml"


def _workflow_text() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


def _extract_js_regex(name: str) -> re.Pattern[str]:
    """Extract ``const <name> = /pattern/flags;`` from the inline script.

    The extraction is what pins the workflow to this test: if someone renames
    or rewrites a regex in the workflow, this raises instead of silently
    testing a stale copy.
    """
    text = _workflow_text()
    match = re.search(
        rf"const {re.escape(name)} = /(?P<pattern>.+)/(?P<flags>[a-z]*);",
        text,
    )
    assert match, f"regex literal 'const {name} = /…/' not found in {_WORKFLOW}"
    flags = re.IGNORECASE if "i" in match.group("flags") else 0
    return re.compile(match.group("pattern"), flags)


def _decide_closures(title: str, body: str, pr_number: int) -> set[int]:
    """Python port of the workflow's decision loop.

    Returns the set of issue numbers the workflow would auto-close for a
    merged PR with the given title/body. Mirrors the inline JavaScript:
    closing-keyword pre-pass, parenthetical scan, 90-char non-fixing
    lookback, and per-number partial-fix qualifier check.
    """
    closing_keyword = _extract_js_regex("closingKeyword")
    non_fixing = _extract_js_regex("NON_FIXING")
    partial_qualifier = _extract_js_regex("PARTIAL_QUALIFIER")
    group_pattern = _extract_js_regex("groupPattern")

    combined = f"{title}\n{body}"

    # Closing keywords: GitHub has already closed these itself.
    closed_numbers = {m.group(2) for m in closing_keyword.finditer(combined)}

    to_close: set[int] = set()
    for group in group_pattern.finditer(combined):
        preceding = combined[max(0, group.start() - 90) : group.start()]
        is_non_fixing = bool(non_fixing.search(preceding))
        inner = group.group(1)
        for m in re.finditer(r"#(\d+)", inner):
            num = m.group(1)
            if num == str(pr_number):  # the PR's own squash-title suffix
                continue
            if num in closed_numbers:  # GitHub already closed it
                continue
            if is_non_fixing:
                continue
            trailing = inner[m.end() :]
            if partial_qualifier.search(trailing):  # partial fix — stays open
                continue
            to_close.add(int(num))
    return to_close


def test_workflow_yaml_is_valid() -> None:
    data = yaml.safe_load(_workflow_text())
    assert isinstance(data, dict)
    assert data.get("name") == "Auto-close referenced issues"


def test_workflow_contains_the_pinned_regexes() -> None:
    """All four regex literals must be present and extractable."""
    for name in ("closingKeyword", "NON_FIXING", "PARTIAL_QUALIFIER", "groupPattern"):
        _extract_js_regex(name)


@pytest.mark.parametrize(
    ("title", "body", "pr_number", "expected"),
    [
        pytest.param(
            "feat: collapse the affinity AI-provider role into alignment "
            "(DD-203, #562 P2) (#577)",
            "",
            577,
            set(),
            id="p-qualifier-the-577-incident",
        ),
        pytest.param(
            "feat: source sample values default on (DD-205, #562 P3+P4) (#579)",
            "",
            579,
            set(),
            id="p-plus-p-list-qualifier",
        ),
        pytest.param(
            "fix: something partial (#562 Problem 2) (#600)",
            "",
            600,
            set(),
            id="long-form-problem-qualifier",
        ),
        pytest.param(
            "fix: rdfs:domain owl:Thing gets its own diagnostic (DD-204, #328) (#576)",
            "",
            576,
            {328},
            id="unqualified-reference-still-closes",
        ),
        pytest.param(
            "fix: some change (#430)",
            "The remaining cleanup is deferred to (#422).",
            430,
            set(),
            id="non-fixing-lookback-no-regression-of-425-fix",
        ),
        pytest.param(
            "fix: something (#286, #338) (#402)",
            "",
            402,
            {286, 338},
            id="multiple-numbers-in-one-group",
        ),
        pytest.param(
            "fix: something (relates to #100 somehow) (#101)",
            "Closes #100",
            101,
            set(),
            id="closing-keyword-pre-pass-excludes-github-native-close",
        ),
        # The qualifier check is per *number*, not per group: one scoped
        # reference must not spare its unqualified neighbours (nor the reverse).
        # Without these two cases a regression to a per-group decision — the
        # very thing the exec-with-index rewrite replaced — still passes.
        pytest.param(
            "fix: partial one, whole other (#562 P2, #563) (#601)",
            "",
            601,
            {563},
            id="qualifier-scopes-only-its-own-number",
        ),
        pytest.param(
            "fix: whole one, partial other (#562, #563 P2) (#602)",
            "",
            602,
            {562},
            id="qualifier-scopes-only-its-own-number-reversed",
        ),
    ],
)
def test_decision_loop(title: str, body: str, pr_number: int, expected: set[int]) -> None:
    assert _decide_closures(title, body, pr_number) == expected
