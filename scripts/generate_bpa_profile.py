#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Generate the files derived from the Kairos BPA profile (DD-238).

* ``docs/guide/BPA_PROFILE.md`` -- the rule table;
* the dataplatform's advisory BPA notebook template, which embeds the profile so it can
  classify Semantic Link Labs findings (#982).

Each is a projection of ``core/projections/dbt/bpa_profile.py``, so it is derived rather
than written, and ``tests/test_bpa_profile.py`` fails when one disagrees.

Usage::

    python scripts/generate_bpa_profile.py            # write the files
    python scripts/generate_bpa_profile.py --check    # exit 1 if any is out of date
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from kairos_ontology.core.projections.dbt.bpa_notebook import (  # noqa: E402
    NOTEBOOK_TEMPLATE,
    PLATFORM_TEMPLATE,
    render_notebook_content,
    render_platform,
)
from kairos_ontology.core.projections.dbt.bpa_profile import (  # noqa: E402
    render_profile_markdown,
)

GUIDE = REPO / "docs" / "guide" / "BPA_PROFILE.md"


def outputs() -> dict[Path, str]:
    return {
        GUIDE: render_profile_markdown(),
        NOTEBOOK_TEMPLATE: render_notebook_content(),
        PLATFORM_TEMPLATE: render_platform(),
    }


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
