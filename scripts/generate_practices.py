#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Generate the practices catalogue pages (DD-240).

``docs/guide/practices/<area>.md``, one per area, is a projection of
``src/kairos_ontology/practices/``, so it is derived rather than written, and
``tests/test_practices_catalogue.py`` fails when one disagrees. Run
``scripts/sync_dev_skills.py`` afterwards to ship them to hubs as ``docs/toolkit/practices/``.

Usage::

    python scripts/generate_practices.py            # write the pages
    python scripts/generate_practices.py --check    # exit 1 if any is out of date
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from kairos_ontology.practices import AREAS, render_area_markdown  # noqa: E402

PAGES = REPO / "docs" / "guide" / "practices"


def outputs() -> dict[Path, str]:
    return {PAGES / f"{area}.md": render_area_markdown(area) for area in AREAS}


def main(argv: list[str]) -> int:
    stale = []
    for path, text in outputs().items():
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if current.replace("\r\n", "\n") == text:
            continue
        if "--check" in argv:
            stale.append(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(REPO)}")
    for path in stale:
        print(f"{path.relative_to(REPO)} is out of date; run {Path(__file__).name}")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
