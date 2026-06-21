# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Write source-import results as a markdown session file.

When `import-source` or `import-flatfile` runs against an ontology hub, this
module records what was imported into
`ontology-hub/.sessions-design-import/import-{system}-{YYYY-MM-DD}.md`. This is
an import audit log, separate from OKF lifecycle state under `.kairos-state/`.

The writer is best-effort: it never raises and is skipped when no hub root is
detected (e.g. when running outside a hub).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

IMPORT_SESSION_DIR = ".sessions-design-import"


def _table_rows(tables: list[dict[str, Any]] | None) -> list[tuple[str, int]]:
    """Extract (table_name, column_count) pairs from a list of table dicts."""
    rows: list[tuple[str, int]] = []
    for tbl in tables or []:
        name = str(tbl.get("name", "?"))
        columns = tbl.get("columns") or []
        rows.append((name, len(columns)))
    return rows


def _toolkit_version() -> str:
    try:
        from . import __version__

        return __version__
    except Exception:  # pragma: no cover - defensive
        return "unknown"


def render_import_session_md(
    system_name: str,
    method: str,
    tables: list[dict[str, Any]] | None,
    *,
    change_report: Any | None = None,
    enrich: bool = False,
    output_paths: list[str] | None = None,
    toolkit_version: str | None = None,
    timestamp: str | None = None,
    next_step: str | None = None,
) -> str:
    """Render an import-results session file as markdown.

    Args:
        system_name: Source system name.
        method: Import method (``flatfile`` or ``yaml-import``).
        tables: List of table dicts (each with ``name`` and ``columns``).
        change_report: Optional ``ChangeReport`` (import-source merge mode).
        enrich: Whether enrichment passes were applied.
        output_paths: Paths written by the import.
        toolkit_version: Toolkit version string (default: detected).
        timestamp: ISO-8601 timestamp (default: now, UTC).
        next_step: Suggested follow-up command.

    Returns:
        The rendered markdown document.
    """
    ts = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
    version = toolkit_version or _toolkit_version()
    rows = _table_rows(tables)

    lines: list[str] = []
    lines.append(f"# Source Import Results: {system_name}")
    lines.append("")
    lines.append(f"**Generated:** {ts}")
    lines.append("**Status:** Complete")
    lines.append(f"**Toolkit version:** {version}")
    lines.append(f"**Import method:** {method}")
    if output_paths:
        lines.append(f"**Output:** {', '.join(output_paths)}")
    lines.append("")

    lines.append("## Tables Imported")
    lines.append("")
    lines.append("| # | Table | Columns |")
    lines.append("|---|---|---|")
    if rows:
        for i, (name, count) in enumerate(rows, start=1):
            lines.append(f"| {i} | {name} | {count} |")
    else:
        lines.append("| - | _(none)_ | 0 |")
    lines.append("")

    # Change report section (import-source merge mode)
    if change_report is not None:
        lines.append("## Change Report")
        lines.append("")
        if getattr(change_report, "has_changes", False):
            lines.append(f"Summary: {change_report.summary()}")
            lines.append("")
            if change_report.added_tables:
                lines.append(f"- **New tables:** {', '.join(change_report.added_tables)}")
            if change_report.removed_tables:
                lines.append(
                    f"- **Deprecated tables:** {', '.join(change_report.removed_tables)}"
                )
            if change_report.added_columns:
                added = ", ".join(f"{c.table}.{c.column}" for c in change_report.added_columns)
                lines.append(f"- **Added columns:** {added}")
            if change_report.removed_columns:
                removed = ", ".join(
                    f"{c.table}.{c.column}" for c in change_report.removed_columns
                )
                lines.append(f"- **Removed columns:** {removed}")
            if change_report.type_changes:
                typed = ", ".join(
                    f"{c.table}.{c.column}: {c.old_value} → {c.new_value}"
                    for c in change_report.type_changes
                )
                lines.append(f"- **Type changes:** {typed}")
        else:
            lines.append("No changes — vocabulary already in sync.")
        lines.append("")
    elif method == "yaml-import":
        lines.append("## Change Report")
        lines.append("")
        lines.append("Fresh vocabulary generated (no prior file to merge with).")
        lines.append("")

    # Enrichment section
    if enrich:
        lines.append("## Enrichment")
        lines.append("")
        lines.append(
            "Inference enrichment applied (enum / format / FK detection). "
            "Review suggestions in the generated vocabulary before mapping."
        )
        lines.append("")

    # Next steps
    if next_step:
        lines.append("## Next Steps")
        lines.append("")
        lines.append(f"- {next_step}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_import_session(
    hub_root: Path | None,
    system_name: str,
    method: str,
    tables: list[dict[str, Any]] | None,
    *,
    change_report: Any | None = None,
    enrich: bool = False,
    output_paths: list[str] | None = None,
    next_step: str | None = None,
    timestamp: str | None = None,
) -> Path | None:
    """Write an import-results session file under ``.sessions-design-import/``.

    Best-effort: returns ``None`` (and logs) when no hub root is given or on any
    write error. Same-day re-runs overwrite the existing file.

    Returns:
        The path written, or ``None`` if skipped/failed.
    """
    if hub_root is None:
        return None
    try:
        session_dir = Path(hub_root) / IMPORT_SESSION_DIR
        session_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_file = session_dir / f"import-{system_name}-{date_str}.md"
        content = render_import_session_md(
            system_name,
            method,
            tables,
            change_report=change_report,
            enrich=enrich,
            output_paths=output_paths,
            timestamp=timestamp,
            next_step=next_step,
        )
        out_file.write_text(content, encoding="utf-8")
        logger.info("Wrote import session file: %s", out_file)
        return out_file
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not write import session file: %s", exc)
        return None
