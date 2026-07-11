# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Architecture guard: enforce the one-way core -> (never) mdm dependency.

The ontology ``core`` package must not depend on the design-time ``mdm`` package.
MDM is an *additive* extension consumer of core, so imports may only flow
``mdm -> core``, never the reverse. This keeps the ontology/MDM boundary
structural rather than conventional and allows the ``mdm`` subpackage to be
lifted into a separate repository later without untangling core.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_CORE_DIR = Path(__file__).resolve().parent.parent / "src" / "kairos_ontology" / "core"

# Matches any import that reaches the mdm package from within core:
#   from kairos_ontology.mdm...      (absolute)
#   import kairos_ontology.mdm...    (absolute)
#   from ..mdm...                    (relative, core/* -> package.mdm)
#   from ...mdm...                   (relative, core/projections/* -> package.mdm)
_FORBIDDEN = re.compile(
    r"(from\s+kairos_ontology\.mdm|import\s+kairos_ontology\.mdm|from\s+\.\.+mdm(\.|\s|$))"
)


def _core_py_files() -> list[Path]:
    return sorted(p for p in _CORE_DIR.rglob("*.py"))


def test_core_dir_exists():
    assert _CORE_DIR.is_dir(), f"expected core package at {_CORE_DIR}"


@pytest.mark.parametrize("py_file", _core_py_files(), ids=lambda p: p.name)
def test_core_does_not_import_mdm(py_file: Path):
    text = py_file.read_text(encoding="utf-8")
    offending = [
        f"{py_file.name}:{i}: {line.strip()}"
        for i, line in enumerate(text.splitlines(), start=1)
        if _FORBIDDEN.search(line)
    ]
    assert not offending, (
        "core/ must not import from kairos_ontology.mdm (one-way boundary):\n"
        + "\n".join(offending)
    )
