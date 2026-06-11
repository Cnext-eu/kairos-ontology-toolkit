# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Prepare Kairos TMDL output for Fabric/fabric-cicd semantic model deployment."""

from __future__ import annotations

import argparse
import json
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


def _sanitize_tmdl(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    for line in lines:
        if line.lstrip().startswith("///"):
            continue
        # Fabric parser does not accept Kairos shorthand "partition <name> = m".
        out.append(line.replace(" = m", " = entity") if "partition " in line else line)

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

        _write_json(
            model_dir / ".platform",
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

        _write_json(
            model_dir / "definition.pbism",
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

