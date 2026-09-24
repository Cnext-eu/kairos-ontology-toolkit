# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Surface recorded human review the analysis pipeline would otherwise overwrite (#695).

A reviewer can characterise a source system in detail -- which of twelve ``Party*``
tables is the party anchor, which must *not* be owned by the party domain -- and record
it as ``HUB-FB-*`` modeling feedback under ``.import/modeling/feedback/``. Nothing in
``analyse-sources`` read those records, so the next re-run reproduced the contradictions
(``partyaddress -> party`` against a record saying otherwise) with no sign that a human
had already answered the question.

This does the cheap, deterministic half: after a run, list every table the run assigned
that an *open* feedback record names, beside the domain it was just given. It does not
judge whether the two disagree -- the records are prose -- it makes sure the reviewer
sees both. The durable override seam remains ``design-rulings.yaml`` (DD-192).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import analysis_paths
from .feedback_records import validate_feedback_bundle

#: Table names shorter than this are too likely to match ordinary words in prose.
_MIN_NAME_LENGTH = 4


@dataclass(frozen=True, slots=True)
class FeedbackMention:
    """One analysed table an open feedback record talks about."""

    record_id: str
    record_title: str
    system: str
    table: str
    assigned_domain: str

    def describe(self) -> str:
        return (
            f"{self.record_id}: {self.system}.{self.table} -> "
            f"{self.assigned_domain or '(unassigned)'}"
        )


def feedback_dir(hub_root: Path) -> Path:
    """``.import/modeling/feedback/`` in the repository that holds *hub_root*."""
    return Path(hub_root).parent / ".import" / "modeling" / "feedback"


def load_assignments(analysis_dir: Path) -> dict[tuple[str, str], str]:
    """``(system, table) -> primary domain`` from the affinity files in *analysis_dir*."""
    assignments: dict[tuple[str, str], str] = {}
    for system, path in analysis_paths.iter_keyed(Path(analysis_dir), analysis_paths.AFFINITY):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
        if not isinstance(document, dict):
            continue
        system = str(document.get("system") or system)
        for table in document.get("tables") or []:
            if isinstance(table, dict) and table.get("table"):
                assignments[(system, str(table["table"]))] = str(table.get("domain") or "")
    return assignments


def tables_in_open_feedback(
    hub_root: Path, assignments: dict[tuple[str, str], str]
) -> list[FeedbackMention]:
    """Every assigned table an open feedback record names, by whole-word match."""
    directory = feedback_dir(hub_root)
    if not directory.is_dir() or not assignments:
        return []
    result = validate_feedback_bundle(directory, hub_root=Path(hub_root))
    mentions: list[FeedbackMention] = []
    for record in result.records:
        if str(record.status or "").lower() != "open":
            continue
        text = f"{record.title or ''}\n{record.body or ''}"
        for (system, table), domain in sorted(assignments.items()):
            if len(table) < _MIN_NAME_LENGTH:
                continue
            if re.search(rf"(?<![\w]){re.escape(table)}(?![\w])", text, re.IGNORECASE):
                mentions.append(
                    FeedbackMention(
                        record_id=str(record.id or record.path.stem),
                        record_title=str(record.title or ""),
                        system=system,
                        table=table,
                        assigned_domain=domain,
                    )
                )
    return mentions
