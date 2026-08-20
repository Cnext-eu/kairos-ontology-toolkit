# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Raw (unredacted) source sample values for the alignment LLM prompt (issue #562).

Two separate things share the word "samples" in this codebase, and they have
always been separate on-disk representations:

1. The **committed** ``<system>.vocabulary.ttl`` (and its per-table copies),
   written once at import time by ``import_source.py``/``import_flatfile.py``
   via ``source_privacy.sanitize_source_data``/``redact_sample_rows``. These
   are permanently redacted — that redaction is not a default that can be
   toggled after the fact, because the raw values were never persisted there
   to begin with. This is also what the alignment LLM prompt has always read
   its sample evidence from (``propose_alignment.py``'s column formatting),
   so the model has only ever seen the already-redacted values.
2. **This module**: a separate, gitignored channel (``.import/raw-samples/``,
   already gitignored by the scaffold's ``.gitignore`` alongside
   ``.import/businessdiscovery/``) that captures the pre-redaction values at
   the same import step, purely so the alignment prompt can see real signal
   instead of a masked token where PII redaction previously replaced it
   outright. Nothing here changes what gets committed to the repository or
   what a human reviewer sees in a generated artifact -- ``example_values``
   in ``*-alignment.yaml`` is a separate, already-existing PII-masking
   decision (``core/_samples.py``).

``KAIROS_ALIGNMENT_SEND_RAW_SAMPLES`` (default: on, DD-205) governs this
channel end to end: off means the writer does not create the file at all at
import time -- not just "the reader will ignore it" -- so an operator who
wants no raw PII ever written to local disk gets that by turning it off
*before* importing. The reader treats a missing file identically to a
disabled setting: both mean the LLM prompt falls back to the committed,
redacted values, exactly as it always has.

This is a deliberate, maintainer-authorized default (client sample values
reach the configured LLM provider by default once a hub imports sources).
See DD-205 for the authorization record.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ENV_SEND_RAW_SAMPLES = "KAIROS_ALIGNMENT_SEND_RAW_SAMPLES"

#: Cap per column -- this is prompt evidence, not a data dump. Mirrors the
#: existing cap in core/_samples.py (MAX_SAMPLES_PER_COLUMN) so neither
#: channel unilaterally grows the prompt further than the other already does.
MAX_RAW_SAMPLES_PER_COLUMN = 10

_SCHEMA_VERSION = 1


def raw_samples_enabled() -> bool:
    """Default on (issue #562, DD-205): set KAIROS_ALIGNMENT_SEND_RAW_SAMPLES=0 to disable."""
    return os.environ.get(ENV_SEND_RAW_SAMPLES, "1").strip().lower() not in {"0", "false", "no"}


def _raw_samples_path(hub_root: Path, system: str) -> Path:
    return Path(hub_root) / ".import" / "raw-samples" / f"{system}.json"


def extract_raw_samples_from_schema(data: dict[str, Any]) -> dict[str, dict[str, list[Any]]]:
    """Extract ``{table: {column: [raw values]}}`` from an import-source schema dict.

    Must be called on *data* before ``sanitize_source_data`` mutates it --
    that function deep-copies before redacting, so the caller's own reference
    stays raw, but only until the caller itself stops using it.
    """
    out: dict[str, dict[str, list[Any]]] = {}
    for table in data.get("tables", []) or []:
        table_name = str(table.get("name", "") or "")
        if not table_name:
            continue
        columns: dict[str, list[Any]] = {}
        for column in table.get("columns", []) or []:
            column_name = str(column.get("name", "") or "")
            if not column_name:
                continue
            values = column.get("samples") or column.get("enum_values") or []
            if values:
                columns[column_name] = list(values)
        if columns:
            out[table_name] = columns
    return out


def extract_raw_samples_from_tables(
    tables: list[dict[str, Any]],
) -> dict[str, dict[str, list[Any]]]:
    """Extract ``{table: {column: [raw values]}}`` from import-flatfile's table list.

    Must be called before ``write_source_dir`` redacts its own deep copy.
    """
    out: dict[str, dict[str, list[Any]]] = {}
    for table in tables:
        table_name = str(table.get("name", "") or "")
        if not table_name:
            continue
        columns: dict[str, list[Any]] = {}
        for column in table.get("columns", []) or []:
            column_name = str(column.get("name", "") or "")
            values = column.get("samples") or []
            if column_name and values:
                columns[column_name] = list(values)
        if columns:
            out[table_name] = columns
    return out


def write_raw_samples(
    hub_root: Path | None,
    system: str,
    table_columns: dict[str, dict[str, list[Any]]],
) -> Path | None:
    """Write the raw sample-values sidecar for *system*. Returns the path, or
    ``None`` when disabled, when there is nothing to write, or when *hub_root*
    could not be resolved (never fabricates a hub-relative path from cwd)."""
    if not raw_samples_enabled() or hub_root is None or not table_columns:
        return None
    path = _raw_samples_path(hub_root, system)
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "system": system,
        "tables": {
            table: {
                column: [str(v) for v in values[:MAX_RAW_SAMPLES_PER_COLUMN]]
                for column, values in columns.items()
            }
            for table, columns in table_columns.items()
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write raw-samples sidecar for %s: %s", system, exc)
        return None
    return path


def get_raw_columns(hub_root: Path, system: str, table: str) -> dict[str, list[str]]:
    """Return ``{column: [raw values]}`` for *table*, or ``{}`` when disabled,
    absent, or unreadable -- always a safe fallback to the redacted values."""
    if not raw_samples_enabled():
        return {}
    path = _raw_samples_path(hub_root, system)
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict):
        return {}
    tables = doc.get("tables")
    if not isinstance(tables, dict):
        return {}
    columns = tables.get(table)
    return columns if isinstance(columns, dict) else {}
