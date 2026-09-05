# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""One-shot migration: split the decision log into one file per decision.

Ran once to turn a 15,680-line ``docs/design/toolkit-design-decisions.md`` into a slim
index plus 217 files under ``docs/design/decisions/``. Kept in the tree so the mechanical
transformation is reviewable next to its result; it is safe to delete once that review is
done, and running it again on the already-split log is a no-op (it finds no ``## DD-NNN``
headings).

Usage::

    python scripts/split_decision_log.py            # dry run, prints the audit
    python scripts/split_decision_log.py --apply     # write the files

Every read and write goes through ``newline=""`` so the log's CRLF endings survive: the
repository has no ``.gitattributes`` and ``core.autocrlf=false``, so a translated rewrite
would show up as a 15,000-line whitespace diff.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "docs" / "design" / "toolkit-design-decisions.md"
DECISIONS = REPO / "docs" / "design" / "decisions"

MAX_FILENAME = 100  # keep Windows paths short; 15 titles exceed this

HEADING_RE = re.compile(r"^## (DD-\d+): (.+?)\r?$", re.MULTILINE)
FRAGMENT_RE = re.compile(r"\]\(#([^)]+)\)")
SIBLING_RE = re.compile(r"\]\((?!#|\.\.|https?:|/)([A-Za-z0-9_.-]+\.md)(#[^)]*)?\)")
TRAILING_RULE_RE = re.compile(r"(?:\r?\n)+---(?:\r?\n)*\Z")


def read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def github_anchor(heading: str) -> str:
    """Identical to ``_github_anchor()`` in tests/test_design_decisions_consistency.py.

    The filenames have to equal the anchors GitHub already generated, because every
    ``](#dd-nnn-...)`` link in the log is rewritten by looking the fragment up here.
    """
    anchor = heading.lower()
    anchor = re.sub(r"[^a-z0-9_ -]", "", anchor)
    return anchor.strip().replace(" ", "-")


def slug_for(anchor: str, taken: set[str]) -> str:
    name = anchor
    if len(name) + 3 > MAX_FILENAME:
        name = name[: MAX_FILENAME - 3]
        if "-" in name:
            name = name.rsplit("-", 1)[0]
        name = name.rstrip("-")
    candidate, suffix = name, 2
    while candidate in taken:
        candidate, suffix = f"{name}-{suffix}", suffix + 1
    taken.add(candidate)
    return candidate


def main() -> int:
    apply = "--apply" in sys.argv
    content = read(LOG)

    matches = list(HEADING_RE.finditer(content))
    print(f"entries found: {len(matches)}")
    if not matches:
        print("nothing to do -- the log is already split")
        return 0

    entries = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        dd_id, title = match.group(1), match.group(2).strip()
        entries.append(
            {
                "id": dd_id,
                "anchor": github_anchor(f"{dd_id}: {title}"),
                "body": content[match.start() : end],
            }
        )

    taken: set[str] = set()
    for entry in entries:
        entry["file"] = slug_for(entry["anchor"], taken) + ".md"

    by_anchor = {entry["anchor"]: entry for entry in entries}
    if len(by_anchor) != len(entries):
        raise SystemExit("FATAL: two decisions slugify to the same anchor")

    longest = max(entries, key=lambda entry: len(entry["file"]))
    print(f"longest filename: {len(longest['file'])} chars ({longest['id']})")
    print(f"truncated slugs: {sum(1 for e in entries if e['file'][:-3] != e['anchor'])}")

    unresolved: dict[str, int] = {}
    for match in FRAGMENT_RE.finditer(content):
        if match.group(1) not in by_anchor:
            unresolved[match.group(1)] = unresolved.get(match.group(1), 0) + 1
    print(f"in-page fragment links: {len(FRAGMENT_RE.findall(content))}")
    for fragment, count in sorted(unresolved.items()):
        print(f"  !! #{fragment} x{count} resolves to no DD heading -- left untouched")

    for entry in entries:
        body = TRAILING_RULE_RE.sub("", entry["body"]).rstrip("\r\n")
        body = "#" + body[2:]  # '## DD-NNN: ...' -> '# DD-NNN: ...'
        # sibling docs/design/*.md links move one directory down
        body = SIBLING_RE.sub(lambda m: f"](../{m.group(1)}{m.group(2) or ''})", body)
        # in-page fragments become sibling files inside decisions/
        body = FRAGMENT_RE.sub(
            lambda m: (
                f"]({by_anchor[m.group(1)]['file']})" if m.group(1) in by_anchor else m.group(0)
            ),
            body,
        )
        if apply:
            DECISIONS.mkdir(parents=True, exist_ok=True)
            write(DECISIONS / entry["file"], body + "\r\n")
    print(f"decision files: {len(entries)}")

    index_text = FRAGMENT_RE.sub(
        lambda m: (
            f"](decisions/{by_anchor[m.group(1)]['file']})"
            if m.group(1) in by_anchor
            else m.group(0)
        ),
        content[: matches[0].start()],
    )
    if apply:
        write(LOG, index_text.rstrip("\r\n") + "\r\n")

    print("APPLIED" if apply else "DRY RUN (pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
