# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Prepare Kairos TMDL output for Fabric/fabric-cicd semantic model deployment."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


_PLATFORM_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/"
    "platformProperties/2.0.0/schema.json"
)
_PBISM_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/"
    "definitionProperties/1.0.0/schema.json"
)
_DEFAULT_LOGICAL_ID = "00000000-0000-0000-0000-000000000000"


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


_PARTITION_M_RE = re.compile(r"^(?P<indent>\s*)partition\s+(?P<name>.+?)\s*=\s*m\s*$")
_M_EXPRESSION_RE = re.compile(r"^\s*source\s*=")


def _is_m_partition(lines: list[str], start: int) -> bool:
    """Return True when the partition block opening at *start* is a real M partition.

    A Power Query / M partition carries an ``source =`` expression body (``= m``
    is the correct TMDL source-type keyword for it). A Direct Lake partition
    instead carries a bare ``source`` block with ``entityName:``, and must be
    declared ``= entity`` — that is the only case worth rewriting.
    """
    indent = len(lines[start]) - len(lines[start].lstrip())
    for line in lines[start + 1 :]:
        if not line.strip():
            continue
        # Dedent back to (or past) the partition keyword ends the block.
        if len(line) - len(line.lstrip()) <= indent:
            break
        if _M_EXPRESSION_RE.match(line):
            return True
    return False


def _sanitize_tmdl(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    for index, line in enumerate(lines):
        if line.lstrip().startswith("///"):
            continue
        # Direct Lake partitions must be declared "= entity", not the "= m"
        # shorthand older projector releases emitted. Never touch a genuine M
        # partition: "= m" is correct there, and rewriting it would leave an
        # entity-partition header over a Power Query "let ... in" body.
        match = _PARTITION_M_RE.match(line)
        if match and not _is_m_partition(lines, index):
            out.append(f"{match['indent']}partition {match['name']} = entity")
            continue
        out.append(line)

    while out and not out[0].strip():
        out = out[1:]

    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def package_semantic_model(root: Path) -> int:
    model_dirs = [p for p in root.rglob("*.SemanticModel") if p.is_dir()]
    if not model_dirs:
        raise ValueError(f"No *.SemanticModel directories found under: {root}")

    prepared = 0
    for model_dir in model_dirs:
        definition_dir = model_dir / "definition"
        if not definition_dir.is_dir():
            continue

        display_name = model_dir.name.removesuffix(".SemanticModel")

        # Backfill only. The Kairos gold projector already emits a complete
        # wrapper, and overwriting would (a) re-diverge the two writers and
        # (b) reset a logicalId that Fabric has since assigned. Hand-authored
        # and imported models still get one written for them.
        platform = model_dir / ".platform"
        if not platform.exists():
            _write_json(
                platform,
                {
                    "$schema": _PLATFORM_SCHEMA,
                    "metadata": {
                        "type": "SemanticModel",
                        "displayName": display_name,
                    },
                    "config": {
                        "version": "2.0",
                        "logicalId": _DEFAULT_LOGICAL_ID,
                    },
                },
            )

        pbism = model_dir / "definition.pbism"
        if not pbism.exists():
            _write_json(
                pbism,
                {
                    "$schema": _PBISM_SCHEMA,
                    "version": "4.2",
                    "settings": {},
                },
            )

        db_tmdl = definition_dir / "database.tmdl"
        if not db_tmdl.exists():
            db_tmdl.write_text("database\n\tcompatibilityLevel: 1604\n", encoding="utf-8")

        for tmdl_file in definition_dir.rglob("*.tmdl"):
            _sanitize_tmdl(tmdl_file)

        prepared += 1
        print(f"Prepared SemanticModel package: {model_dir}")

    return prepared


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="semantic-model",
        help="Root folder that contains one or more *.SemanticModel directories.",
    )
    args = parser.parse_args()

    root = Path(args.input).resolve()
    if not root.exists():
        raise SystemExit(f"Input path does not exist: {root}")

    count = package_semantic_model(root)
    print(f"Prepared {count} semantic model package(s).")


if __name__ == "__main__":
    main()
