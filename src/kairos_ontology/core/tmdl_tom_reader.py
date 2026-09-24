# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Read a Power BI TMDL model with the Microsoft TOM SDK (#879, DD-237).

``import-tmdl`` used to read exports with a hand-rolled line-and-regex parser. Three of
the four bugs from one dogfood session were bugs the real engine does not have: a flat
layout read as zero tables (#874), fenced DAX stored as expression text (#875), and an
export missing its table files read as a well-formed empty model (#807). This module
asks ``TmdlSerializer.DeserializeDatabaseFromFolder`` -- the engine Power BI Desktop and
Fabric use -- and maps its reading onto the same ``tmdl_parser`` dataclasses every
downstream consumer already reads, so the engineering pack and concept mapping keep
their shape.

The .NET SDK is therefore a prerequisite for BI import. Without ``dotnet`` this raises
:class:`TomUnavailableError` naming the install, rather than falling back to the old
parser: a fallback nobody tests is where the two readings would quietly diverge.

An export TOM refuses raises :class:`TmdlRejectedError` with the engine's own message.
That is deliberate: Power BI Desktop refuses such a model too, so reading it anyway
produced evidence about a model nobody can open.

``harvest-gold`` still uses ``tmdl_parser`` for the in-memory TMDL the toolkit itself
generated; that is a separate path and a separate decision.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from .tmdl_parser import (
    TmdlColumn,
    TmdlMeasure,
    TmdlModel,
    TmdlPartition,
    TmdlRelationship,
    TmdlTable,
    model_name_for_definition_dir,
    parse_model_table_refs,
)

#: TOM ``DataType`` names -> the TMDL spellings ``tmdl_parser`` stored.
_DATA_TYPES = {
    "String": "string",
    "Int64": "int64",
    "Double": "double",
    "Decimal": "decimal",
    "DateTime": "dateTime",
    "Boolean": "boolean",
    "Binary": "binary",
    "Variant": "variant",
    "Unknown": "",
    "Automatic": "",
}

#: TOM ``RelationshipEndCardinality`` names -> TMDL spellings.
_CARDINALITY = {"One": "one", "Many": "many", "None": ""}


class TomUnavailableError(RuntimeError):
    """The TOM SDK cannot run here: no ``dotnet``, or the SDK itself failed to start."""


class TmdlRejectedError(ValueError):
    """TOM refused the export: Power BI Desktop would not open it either."""


def _first_lower(name: str) -> str:
    return name[:1].lower() + name[1:] if name else ""


def _tom_payload(folder: Path) -> dict[str, Any]:
    from .projections.dbt.tmdl_validate import _invoke_validator

    if shutil.which("dotnet") is None:
        raise TomUnavailableError(
            "import-tmdl reads Power BI models with the Microsoft TOM SDK, which needs the "
            ".NET 8 SDK on PATH (https://dotnet.microsoft.com/download). Install it and "
            "re-run; the first run builds the bundled reader once (NuGet access needed)."
        )
    payload = _invoke_validator(folder, "--inventory")
    status = payload.get("status")
    if status == "pass" and isinstance(payload.get("model"), dict):
        return payload
    message = str(payload.get("message") or "no detail")
    if status == "fail":
        raise TmdlRejectedError(
            f"the TOM SDK rejected {folder} ({payload.get('error_type', 'error')}): {message}. "
            "Power BI Desktop refuses such a model too; re-export it complete -- the "
            "definition folder with model.tmdl and every table file."
        )
    if "ClientHostingManager" in message:
        # Seen on Linux runners when the SDK tries to report a problem with the export:
        # its native hosting layer fails to initialise, so the real finding is lost.
        raise TomUnavailableError(
            f"the TOM SDK could not run: {message}. On Linux this usually means the SDK "
            "hit a problem in the export and could not initialise its native hosting to "
            "report it; open the model in Power BI Desktop, or re-export it complete, "
            "and re-run."
        )
    raise TomUnavailableError(f"the TOM SDK could not run: {message}")


def _to_model(payload: dict[str, Any], name: str) -> TmdlModel:
    raw = payload["model"]
    model = TmdlModel(
        name=name,
        compatibility_level=int(raw.get("compatibility_level") or 0),
        default_mode=_first_lower(str(raw.get("default_mode") or "")),
    )
    for table_raw in raw.get("tables") or []:
        table = TmdlTable(
            name=table_raw["name"],
            lineage_tag=table_raw.get("lineage_tag") or "",
            description=table_raw.get("description") or "",
            annotations=dict(table_raw.get("annotations") or {}),
            is_hidden=bool(table_raw.get("is_hidden")),
        )
        for column in table_raw.get("columns") or []:
            table.columns.append(
                TmdlColumn(
                    name=column["name"],
                    data_type=_DATA_TYPES.get(str(column.get("data_type")), ""),
                    format_string=column.get("format_string") or "",
                    source_column=column.get("source_column") or "",
                    is_hidden=bool(column.get("is_hidden")),
                    lineage_tag=column.get("lineage_tag") or "",
                    description=column.get("description") or "",
                    is_key=bool(column.get("is_key")),
                    display_folder=column.get("display_folder") or "",
                    annotations=dict(column.get("annotations") or {}),
                )
            )
        for measure in table_raw.get("measures") or []:
            table.measures.append(
                TmdlMeasure(
                    name=measure["name"],
                    expression=measure.get("expression") or "",
                    format_string=measure.get("format_string") or "",
                    description=measure.get("description") or "",
                    display_folder=measure.get("display_folder") or "",
                    lineage_tag=measure.get("lineage_tag") or "",
                    is_hidden=bool(measure.get("is_hidden")),
                    annotations=dict(measure.get("annotations") or {}),
                )
            )
        for partition in table_raw.get("partitions") or []:
            mode = str(partition.get("mode") or "")
            table.partitions.append(
                TmdlPartition(
                    name=partition.get("name") or "",
                    # "Default" means "inherit the model's", which TMDL leaves unwritten.
                    mode="" if mode == "Default" else mode.lower(),
                    source_type=str(partition.get("source_type") or "").lower(),
                )
            )
        model.tables.append(table)
    for relationship in raw.get("relationships") or []:
        model.relationships.append(
            TmdlRelationship(
                name=relationship.get("name") or "",
                from_table=relationship.get("from_table") or "",
                from_column=relationship.get("from_column") or "",
                to_table=relationship.get("to_table") or "",
                to_column=relationship.get("to_column") or "",
                from_cardinality=_CARDINALITY.get(str(relationship.get("from_cardinality")), ""),
                to_cardinality=_CARDINALITY.get(str(relationship.get("to_cardinality")), ""),
                cross_filtering=_first_lower(str(relationship.get("cross_filtering") or "")),
                is_active=bool(relationship.get("is_active", True)),
            )
        )
    return model


def read_model_folder(definition_dir: Path) -> TmdlModel:
    """Read one ``definition`` folder (or flat export folder) through the TOM SDK."""
    definition_dir = Path(definition_dir)
    payload = _tom_payload(definition_dir)
    model = _to_model(payload, model_name_for_definition_dir(definition_dir))
    # TOM accepts a `ref table` pointer to a table the export does not contain -- the
    # pointer only orders tables -- so the SDK alone would hide a partial export as
    # quietly as the old glob did (#807). model.tmdl still names every table it expects.
    model_file = definition_dir / "model.tmdl"
    if model_file.is_file():
        read = {table.name.casefold() for table in model.tables}
        model.unresolved_table_refs = [
            name
            for name in parse_model_table_refs(model_file.read_text(encoding="utf-8"))
            if name.casefold() not in read
        ]
    return model


def read_single_table_file(path: Path) -> TmdlModel:
    """Read one loose ``.tmdl`` file by staging it as the only table of a stub model.

    TOM reads folders, not files. A lone table file is a real input -- an engineer
    pasting one table's definition -- so it is placed under ``tables/`` beside a minimal
    ``model.tmdl``, which TOM accepts. A relationship-only file cannot stand alone: its
    endpoints do not exist, and TOM says so.
    """
    path = Path(path)
    with tempfile.TemporaryDirectory(prefix="kairos-tmdl-file-") as tmp:
        root = Path(tmp)
        (root / "tables").mkdir()
        (root / "model.tmdl").write_text("model Model\n", encoding="utf-8")
        shutil.copy2(path, root / "tables" / path.name)
        payload = _tom_payload(root)
    return _to_model(payload, path.stem)
