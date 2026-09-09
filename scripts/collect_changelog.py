# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Assemble ``changelog.d/`` fragments into ``CHANGELOG.md``'s ``[Unreleased]`` section.

Why fragments exist: every PR used to edit the same few lines of ``CHANGELOG.md``, directly
under ``## [Unreleased]``. Any two PRs open at once therefore conflicted on it -- not
semantically, just textually, because they both inserted at the same anchor. With four
parallel PRs the cost is three rebases that change nothing about the code under review.

A fragment is one file per change, so two PRs never touch the same path. The releaser runs
this once when cutting a release, which is the only moment ``CHANGELOG.md`` needs to change.

Usage::

    python scripts/collect_changelog.py            # print the assembled section, change nothing
    python scripts/collect_changelog.py --apply    # write it into CHANGELOG.md, delete fragments

``CHANGELOG.md`` is LF-terminated and this writes it back the same way: the repository sets
``core.autocrlf=false`` and has no ``.gitattributes``, so a translated rewrite would show up
as a whole-file whitespace diff.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FRAGMENTS = REPO / "changelog.d"
CHANGELOG = REPO / "CHANGELOG.md"
UNRELEASED = "## [Unreleased]"

#: Section order for the assembled output. Keep a Changelog's six, plus the ones this
#: changelog actually uses. Matched on the heading's first word, so a qualified heading
#: (``### Removed (BREAKING)``) sorts with its base word instead of falling to the end.
#: Anything unrecognised is appended alphabetically rather than dropped -- the script must
#: never silently lose an authored entry.
SECTION_ORDER = (
    "Added",
    "Changed",
    "Deprecated",
    "Removed",
    "Fixed",
    "Security",
    "Performance",
    "Documentation",
    "Decisions",
    "Notes",
    "Known",
)

HEADING = re.compile("^### (.+)$", re.MULTILINE)


def fragment_paths(directory: Path = FRAGMENTS) -> list[Path]:
    """Return every fragment, sorted by name; README.md is documentation, not a fragment."""
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("*.md") if p.name.lower() != "readme.md")


def parse_fragment(text: str) -> dict[str, list[str]]:
    """Split one fragment into ``{section heading: [body lines]}``.

    A fragment with no ``###`` heading is an authoring mistake worth failing on rather than
    guessing at -- there is no sensible default section, and putting it under the wrong one
    is worse than saying so.
    """
    matches = list(HEADING.finditer(text))
    if not matches:
        raise ValueError("fragment has no '### Section' heading")
    sections: dict[str, list[str]] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip("\n").rstrip()
        if not body:
            raise ValueError(f"section {match.group(1)!r} has no content")
        sections.setdefault(match.group(1).strip(), []).append(body)
    return sections


def _rank(heading: str) -> tuple[int, str]:
    first = heading.split(" ", 1)[0].split("(", 1)[0].strip()
    if first in SECTION_ORDER:
        return (SECTION_ORDER.index(first), heading)
    return (len(SECTION_ORDER), heading)


def assemble(paths: list[Path]) -> str:
    """Return the merged section bodies, ordered, or an empty string when there are none."""
    merged: dict[str, list[str]] = {}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        try:
            sections = parse_fragment(text)
        except ValueError as exc:
            raise ValueError(f"{path.name}: {exc}") from exc
        for heading, bodies in sections.items():
            merged.setdefault(heading, []).extend(bodies)
    if not merged:
        return ""
    blocks = []
    for heading in sorted(merged, key=_rank):
        blocks.append("### " + heading + "\n" + "\n".join(merged[heading]))
    return "\n\n".join(blocks)


def apply(section: str, changelog: Path = CHANGELOG) -> str:
    """Return ``CHANGELOG.md`` with *section* inserted directly under ``## [Unreleased]``.

    Inserted above whatever is already there, so a release that was partly written by hand
    keeps its content and ordering; this only ever adds.
    """
    text = changelog.read_text(encoding="utf-8")
    if UNRELEASED not in text:
        raise ValueError(f"{changelog.name} has no {UNRELEASED} heading")
    head, _, tail = text.partition(UNRELEASED)
    return head + UNRELEASED + "\n\n" + section + "\n\n" + tail.lstrip("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write into CHANGELOG.md and delete the fragments (default: print only)",
    )
    args = parser.parse_args(argv)

    paths = fragment_paths(FRAGMENTS)
    if not paths:
        print("no fragments under changelog.d/ -- nothing to collect")
        return 0
    try:
        section = assemble(paths)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not args.apply:
        print(f"{len(paths)} fragment(s) would be merged into {UNRELEASED}:\n")
        print(section)
        return 0

    CHANGELOG.write_text(apply(section), encoding="utf-8", newline="")
    for path in paths:
        path.unlink()
    print(f"merged {len(paths)} fragment(s) into {CHANGELOG.name} and removed them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
