# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The legacy catalog graph loader has no production consumers (DD-103)."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
CORE = ROOT / "src" / "kairos_ontology" / "core"

# The per-module allow-list that lived here (2026-08) is superseded by the DD-243 parse
# inventory, ``docs/dev/dd103-single-file-parse-inventory.json``, which lists every rdflib
# parse in the package per function with a reason and is enforced by
# ``tests/test_dd103_closure_boundary.py``. Only the legacy-loader check remains here.


def test_legacy_catalog_graph_loader_has_no_production_consumers():
    offenders = []
    package = ROOT / "src" / "kairos_ontology"
    allowed = {
        package / "__init__.py",
        CORE / "catalog_utils.py",
    }
    for path in package.rglob("*.py"):
        if path in allowed:
            continue
        if "load_graph_with_catalog" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []
