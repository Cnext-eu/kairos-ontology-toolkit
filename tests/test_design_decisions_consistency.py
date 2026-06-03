# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Validate design-decisions.md TOC ↔ body consistency.

Catches drift between the Index table and the actual ## DD-NNN headings.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_DD_FILE = Path(__file__).resolve().parent.parent / "docs" / "design" / "toolkit-design-decisions.md"


def _github_anchor(heading: str) -> str:
    """Approximate GitHub Markdown anchor generation.

    GitHub: lowercase, strip everything except a-z 0-9 space hyphen,
    then replace spaces with hyphens. Characters like — + & = become nothing,
    and surrounding spaces naturally produce double hyphens.
    """
    anchor = heading.lower()
    # Keep only a-z, 0-9, spaces, and hyphens
    anchor = re.sub(r"[^a-z0-9 -]", "", anchor)
    anchor = anchor.strip().replace(" ", "-")
    return anchor


def _parse_toc_entries(content: str) -> list[tuple[str, str, str]]:
    """Return list of (id, title, anchor) from the TOC table."""
    entries = []
    for m in re.finditer(
        r"\|\s*\[(?P<id>DD-\d+)\]\(#(?P<anchor>[^)]+)\)\s*\|\s*(?P<title>[^|]+?)\s*\|",
        content,
    ):
        entries.append((m.group("id"), m.group("title").strip(), m.group("anchor")))
    return entries


def _parse_body_headings(content: str) -> list[tuple[str, str]]:
    """Return list of (id, title) from ## DD-NNN headings."""
    headings = []
    for m in re.finditer(r"^## (DD-\d+):\s*(.+)$", content, re.MULTILINE):
        headings.append((m.group(1), m.group(2).strip()))
    return headings


@pytest.fixture()
def dd_content():
    if not _DD_FILE.exists():
        pytest.skip("design-decisions.md not found")
    return _DD_FILE.read_text(encoding="utf-8")


def test_toc_entries_match_body_headings(dd_content):
    """Every TOC entry must have a matching body heading with the same DD-ID and title."""
    toc = _parse_toc_entries(dd_content)
    body = _parse_body_headings(dd_content)

    body_by_id = {dd_id: title for dd_id, title in body}

    mismatches = []
    for dd_id, toc_title, _ in toc:
        if dd_id not in body_by_id:
            mismatches.append(f"{dd_id}: in TOC but no body heading found")
        else:
            # Strip markdown formatting for comparison (backticks, etc.)
            clean_toc = re.sub(r"`([^`]*)`", r"\1", toc_title)
            clean_body = re.sub(r"`([^`]*)`", r"\1", body_by_id[dd_id])
            if clean_toc != clean_body:
                mismatches.append(
                    f"{dd_id}: TOC title '{clean_toc}' ≠ body title '{clean_body}'"
                )

    assert not mismatches, "TOC ↔ body title mismatches:\n" + "\n".join(mismatches)


def test_body_headings_all_in_toc(dd_content):
    """Every body heading must have a corresponding TOC entry."""
    toc = _parse_toc_entries(dd_content)
    body = _parse_body_headings(dd_content)

    toc_ids = {dd_id for dd_id, _, _ in toc}
    missing = [f"{dd_id}: {title}" for dd_id, title in body if dd_id not in toc_ids]

    assert not missing, "Body headings missing from TOC:\n" + "\n".join(missing)


def test_toc_anchors_resolve(dd_content):
    """Each TOC anchor link must match the expected GitHub-generated anchor."""
    toc = _parse_toc_entries(dd_content)
    body = _parse_body_headings(dd_content)

    body_anchors = {}
    for dd_id, title in body:
        full_heading = f"{dd_id}: {title}"
        body_anchors[dd_id] = _github_anchor(full_heading)

    broken = []
    for dd_id, _, toc_anchor in toc:
        if dd_id in body_anchors:
            expected = body_anchors[dd_id]
            if toc_anchor != expected:
                broken.append(
                    f"{dd_id}: anchor '#{toc_anchor}' should be '#{expected}'"
                )

    assert not broken, "Broken TOC anchor links:\n" + "\n".join(broken)


def test_toc_ids_sequential(dd_content):
    """DD-IDs in the TOC should be sequential (no gaps, no duplicates)."""
    toc = _parse_toc_entries(dd_content)
    ids = [int(dd_id.replace("DD-", "")) for dd_id, _, _ in toc]

    if not ids:
        pytest.skip("No TOC entries found")

    expected = list(range(1, max(ids) + 1))
    missing = set(expected) - set(ids)
    duplicates = [x for x in ids if ids.count(x) > 1]

    issues = []
    if missing:
        issues.append(f"Missing IDs: {sorted(missing)}")
    if duplicates:
        issues.append(f"Duplicate IDs: {sorted(set(duplicates))}")

    assert not issues, "TOC ID sequence issues:\n" + "\n".join(issues)
