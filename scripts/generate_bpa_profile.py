#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Generate ``docs/guide/BPA_PROFILE.md`` from the Kairos BPA profile (DD-238).

The guide is a projection of ``core/projections/dbt/bpa_profile.py``, so it is derived
rather than written, and ``tests/test_bpa_profile.py`` fails when the two disagree.

Usage::

    python scripts/generate_bpa_profile.py            # write the file
    python scripts/generate_bpa_profile.py --check    # exit 1 if it is out of date
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from kairos_ontology.core.projections.dbt.bpa_profile import (  # noqa: E402
    render_profile_markdown,
)

GUIDE = REPO / "docs" / "guide" / "BPA_PROFILE.md"


def main(argv: list[str]) -> int:
    text = render_profile_markdown()
    if "--check" in argv:
        current = GUIDE.read_text(encoding="utf-8") if GUIDE.is_file() else ""
        if current.replace("\r\n", "\n") != text:
            print(f"{GUIDE.relative_to(REPO)} is out of date; run {Path(__file__).name}")
            return 1
        return 0
    GUIDE.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {GUIDE.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
