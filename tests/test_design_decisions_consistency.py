# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Validate the decision log: index table ↔ one file per decision.

The log was split from a single 15k-line file into ``docs/dev/decisions/dd-NNN-*.md``,
with ``toolkit-design-decisions.md`` kept as the index. These tests are the only thing
stopping the two halves from drifting apart.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_DOCS = Path(__file__).resolve().parent.parent / "docs"
_INDEX_FILE = _DOCS / "dev" / "toolkit-design-decisions.md"
_DECISIONS_DIR = _DOCS / "dev" / "decisions"

_MAX_FILENAME = 100

_ROW_RE = re.compile(
    r"^\|\s*\[(?P<id>DD-\d+)\]\((?P<href>[^)]+)\)\s*\|"
    r"\s*(?P<title>[^|]+?)\s*\|\s*(?P<status>[^|]*?)\s*\|\s*(?P<date>[^|]*?)\s*\|",
    re.MULTILINE,
)
_HEADING_RE = re.compile(r"^# (DD-\d+):\s*(.+)$", re.MULTILINE)
_STATUS_RE = re.compile(r"^\*\*Status:\*\*\s*(.+?)\s*$", re.MULTILINE)
_DATE_RE = re.compile(r"^\*\*Date:\*\*\s*(.+?)\s*$", re.MULTILINE)
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_INLINE_CODE = re.compile(r"`([^`]*)`")


def _github_anchor(heading: str) -> str:
    """Approximate GitHub Markdown anchor generation.

    GitHub: lowercase, strip everything except a-z 0-9 underscore space hyphen,
    then replace spaces with hyphens. Characters like — + & = become nothing,
    and surrounding spaces naturally produce double hyphens. Underscores are a
    real GitHub word character and survive slugification (e.g. a heading
    containing `row_count` slugs to `...-row_count-...`, not `...-rowcount-...`)
    -- a prior version of this helper stripped them, which produced false
    positives against correctly-authored links (DD-211) while letting a
    genuinely broken one (DD-156, missing its underscores) pass unnoticed.
    """
    anchor = heading.lower()
    anchor = re.sub(r"[^a-z0-9_ -]", "", anchor)
    return anchor.strip().replace(" ", "-")


def _expected_filename(dd_id: str, title: str) -> str:
    """The slug rule documented in the index header."""
    name = _github_anchor(f"{dd_id}: {title}")
    if len(name) + 3 > _MAX_FILENAME:
        name = name[: _MAX_FILENAME - 3]
        if "-" in name:
            name = name.rsplit("-", 1)[0]
        name = name.rstrip("-")
    return f"{name}.md"


def _normalise(text: str) -> str:
    """Compare prose ignoring inline-code ticks and link markup.

    An index cell says ``~~Superseded by DD-014~~`` while the decision file links
    the same reference. Both must mean the same thing; neither has to be spelled
    the same way.
    """
    return _INLINE_CODE.sub(r"\1", _MD_LINK.sub(r"\1", text)).strip()


def _agrees(index_value: str, file_value: str) -> bool:
    """The index may summarise the file, but must never contradict it.

    A row saying ``Accepted`` against a file saying ``Accepted (amended by
    DD-215)`` is a summary and is fine; ``2026-08-16`` against ``2026-08-17``
    is a contradiction and is not. So require the file value to *start with*
    the index value, on a word boundary.
    """
    if not file_value.startswith(index_value):
        return False
    remainder = file_value[len(index_value) :]
    return remainder == "" or not remainder[0].isalnum()


@pytest.fixture(scope="module")
def index_rows() -> list[dict[str, str]]:
    text = _INDEX_FILE.read_text(encoding="utf-8")
    rows = [match.groupdict() for match in _ROW_RE.finditer(text)]
    assert rows, "no index rows parsed -- the table shape changed"
    return rows


@pytest.fixture(scope="module")
def decision_files() -> list[Path]:
    # ``*-companion.md`` is the long-form background beside a record, not a record:
    # it carries no ``# DD-NNN:`` heading and has no index row of its own.
    files = sorted(
        path
        for path in _DECISIONS_DIR.glob("*.md")
        if path.name != "TEMPLATE.md" and not path.name.endswith("-companion.md")
    )
    assert files, "no decision files found"
    return files


def test_template_exists() -> None:
    """The index header tells authors to copy it, so it has to be there."""
    assert (_DECISIONS_DIR / "TEMPLATE.md").is_file()


def test_every_index_row_resolves_to_a_file(index_rows) -> None:
    missing = [
        f"{row['id']}: href {row['href']!r} does not exist"
        for row in index_rows
        if not (_INDEX_FILE.parent / row["href"]).is_file()
    ]
    assert not missing, "index rows pointing at nothing:\n" + "\n".join(missing)


def test_every_decision_file_is_indexed(index_rows, decision_files) -> None:
    indexed = {Path(row["href"]).name for row in index_rows}
    orphans = [path.name for path in decision_files if path.name not in indexed]
    assert not orphans, "decision files missing from the index:\n" + "\n".join(orphans)


def test_each_file_has_exactly_one_decision_heading(decision_files) -> None:
    bad = []
    for path in decision_files:
        headings = _HEADING_RE.findall(path.read_text(encoding="utf-8"))
        if len(headings) != 1:
            bad.append(f"{path.name}: found {len(headings)} '# DD-NNN:' headings, want 1")
    assert not bad, "\n".join(bad)


def test_file_heading_status_and_date_match_the_index(index_rows) -> None:
    mismatches = []
    for row in index_rows:
        path = _INDEX_FILE.parent / row["href"]
        if not path.is_file():
            continue  # reported by test_every_index_row_resolves_to_a_file
        text = path.read_text(encoding="utf-8")

        heading = _HEADING_RE.search(text)
        if heading is None:
            mismatches.append(f"{row['id']}: no '# DD-NNN:' heading in {path.name}")
            continue
        if heading.group(1) != row["id"]:
            mismatches.append(f"{row['id']}: file {path.name} declares {heading.group(1)}")
        if _normalise(heading.group(2)) != _normalise(row["title"]):
            mismatches.append(
                f"{row['id']}: index title {_normalise(row['title'])!r} != "
                f"file title {_normalise(heading.group(2))!r}"
            )

        for label, pattern in (("status", _STATUS_RE), ("date", _DATE_RE)):
            found = pattern.search(text)
            if found is None:
                mismatches.append(f"{row['id']}: no **{label.title()}:** line in {path.name}")
            elif not _agrees(_normalise(row[label]), _normalise(found.group(1))):
                mismatches.append(
                    f"{row['id']}: index {label} {_normalise(row[label])!r} contradicts "
                    f"file {label} {_normalise(found.group(1))!r}"
                )
    assert not mismatches, "index <-> file drift:\n" + "\n".join(mismatches)


def test_filenames_follow_the_documented_slug_rule(index_rows) -> None:
    wrong = []
    for row in index_rows:
        expected = _expected_filename(row["id"], _normalise(row["title"]))
        actual = Path(row["href"]).name
        if actual != expected:
            wrong.append(f"{row['id']}: file is {actual!r}, slug rule wants {expected!r}")
    assert not wrong, "filenames disagree with the rule in the index header:\n" + "\n".join(wrong)


def test_ids_are_sequential(index_rows) -> None:
    ids = [int(row["id"].removeprefix("DD-")) for row in index_rows]
    expected = list(range(1, max(ids) + 1))
    missing = sorted(set(expected) - set(ids))
    duplicates = sorted({value for value in ids if ids.count(value) > 1})

    issues = []
    if missing:
        issues.append(f"Missing IDs: {missing}")
    if duplicates:
        issues.append(f"Duplicate IDs: {duplicates}")
    assert not issues, "index ID sequence issues:\n" + "\n".join(issues)


def test_no_in_page_decision_anchors_survive() -> None:
    """The split turned every ``](#dd-nnn-...)`` fragment into a relative path.

    A reintroduced fragment is a link that silently lands at the top of whatever
    file it sits in, so guard the whole docs tree rather than one file.
    """
    offenders = []
    for path in sorted(_DOCS.rglob("*.md")):
        if "temp" in path.relative_to(_DOCS).parts:
            continue  # untracked scratch space, gitignored
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "](#dd-" in line:
                offenders.append(f"{path.relative_to(_DOCS.parent)}:{number}")
    assert not offenders, (
        "in-page DD anchors are dead after the split; use decisions/dd-nnn-....md:\n"
        + "\n".join(offenders)
    )


def test_no_tracked_doc_links_into_gitignored_scratch() -> None:
    """``docs/temp/`` is gitignored, so a link into it resolves only for its author.

    Four tracked ADRs cited change-request documents that live there: the reasoning was
    real, but every reader who cloned the repository followed the citation to nothing.
    Cite the substance instead, or commit the source.
    """
    offenders = [
        f"{path.relative_to(_DOCS.parent).as_posix()}:{lineno}"
        for path in sorted(_DOCS.rglob("*.md"))
        if "temp" not in path.parts
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"docs/temp/[A-Za-z0-9_.-]+", line)
    ]
    assert not offenders, "tracked documents linking into gitignored docs/temp/:\n" + "\n".join(
        offenders
    )


def test_a_companion_sits_beside_the_decision_it_expands() -> None:
    """Long-form design documents used to live one directory up from their ADR, under a
    different slug for the same DD number -- two parallel stores with no stated authority.

    They are now ``dd-NNN-<adr-slug>-companion.md`` beside the record they expand, so the
    relationship is in the filename.
    """
    orphans = [
        companion.name
        for companion in sorted(_DECISIONS_DIR.glob("*-companion.md"))
        if not (_DECISIONS_DIR / f"{companion.name[: -len('-companion.md')]}.md").is_file()
    ]
    assert not orphans, f"companions with no decision record: {orphans}"

    stragglers = [path.name for path in sorted(_DOCS.glob("dev/dd-*.md"))]
    assert not stragglers, f"decision documents outside decisions/: {stragglers}"


def test_no_relative_link_in_docs_dangles() -> None:
    """Every relative link under ``docs/`` must resolve on disk.

    Reorganising ``docs/`` into ``guide/`` (operating a hub) and ``dev/`` (building the
    toolkit) moved ~250 files, and folding the long-form design documents in beside their
    ADRs renamed ten more. Relative links do not survive that by themselves -- eighteen
    broke -- and nothing would have reported it.
    """
    placeholders = {"dd-xxx-slug.md", "dd-NNN-short-slug.md"}
    offenders = []
    for path in sorted(_DOCS.rglob("*.md")):
        if "temp" in path.parts:
            continue  # gitignored scratch; guarded separately
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for target in re.findall(r"\]\((?!https?://|mailto:|#)([^)#]+)", line):
                if Path(target).name in placeholders:
                    continue
                if not (path.parent / target).exists():
                    rel = path.relative_to(_DOCS.parent).as_posix()
                    offenders.append(f"{rel}:{lineno} -> {target}")
    assert not offenders, "dangling relative links in docs/:\n" + "\n".join(offenders)
