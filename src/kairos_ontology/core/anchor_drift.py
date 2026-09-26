# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""What moved between two `anchor-tables` runs on the same evidence (#877).

Anchoring is not reproducible at the prompt size it actually operates at. DD-177 measured
this first on a 23 KB alignment prompt and chose a shape-constrained response over a seed
it had shown could not deliver determinism; `anchor-tables` runs a **121 KB** prompt and
nobody had measured it. Back to back on one hub, with the prompt byte-identical across
processes and the same seed sent and honoured:

===========================  =========
field                        stable on
===========================  =========
``anchor`` (the class)       27 of 39
``natural_key``              26 of 39
``grain_columns``            29 of 39
``domain``                    34 of 39
``confidence``                 3 of 39
===========================  =========

Two tables were given entirely disjoint natural keys, and one was anchored in one run and
left unanchored in the next.

That is not a defect to fix here — provider-side determinism is not on offer at this size,
which DD-177 already records. The defect is that a re-run **overwrote every unpinned row
in silence**, so nobody could see it happen. DD-190 built sticky review statuses on the
premise that "review effort concentrates where it belongs", and never said where that is:
on a first run all rows are ``proposed`` and look alike, and the unstable ones are
indistinguishable from the stable ones without running twice and diffing by hand.

So this reports the diff. Deterministic, no extra model call, and it turns an invisible
overwrite into the review queue DD-190 assumes the operator already has. ``natural_key``
is called out separately because it is not an advisory label: it flows into the
EntityBinding's identity and the silver contract's uniqueness test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Fields worth reporting, in the order a reviewer should read them: what the table *is*,
#: then how its rows are identified, then where it lives, then how confident the model was.
TRACKED_FIELDS: tuple[str, ...] = (
    "anchor",
    "natural_key",
    "grain_columns",
    "domain",
    "load_hint",
)

#: Reported as a count only. It moves on almost every row and says nothing actionable on
#: its own -- listing it per table would bury the fields that matter.
NOISY_FIELDS: tuple[str, ...] = ("confidence",)


@dataclass
class AnchorDrift:
    """What changed for one table between the previous run and this one."""

    system: str
    table: str
    changed: dict[str, tuple[Any, Any]] = field(default_factory=dict)

    @property
    def relation(self) -> str:
        return f"{self.system}.{self.table}"

    def describe(self) -> str:
        parts = []
        for name, (was, now) in sorted(self.changed.items()):
            parts.append(f"{name}: {_render(was)} → {_render(now)}")
        return f"{self.relation}: " + "; ".join(parts)


@dataclass
class AnchorDriftReport:
    """Everything that moved, and everything that did not."""

    drifted: list[AnchorDrift] = field(default_factory=list)
    unchanged: int = 0
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    confidence_moved: int = 0

    @property
    def is_first_run(self) -> bool:
        """No previous artifact: nothing to compare, which is not drift."""
        return not (self.drifted or self.unchanged or self.added or self.removed)

    def counts(self) -> dict[str, int]:
        """How many tables moved, per field, for the one-line summary."""
        counts: dict[str, int] = {}
        for item in self.drifted:
            for name in item.changed:
                counts[name] = counts.get(name, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    def to_dict(self) -> dict[str, Any]:
        return {
            "unchanged": self.unchanged,
            "confidence_moved": self.confidence_moved,
            "added": list(self.added),
            "removed": list(self.removed),
            "changed": [
                {
                    "system": item.system,
                    "table": item.table,
                    **{
                        name: {"was": was, "now": now}
                        for name, (was, now) in sorted(item.changed.items())
                    },
                }
                for item in self.drifted
            ],
        }


def _render(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(str(v) for v in value) + "]"
    return str(value)


def _normalise(value: Any) -> Any:
    """Compare lists by content and scalars by string, so formatting is not drift."""
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return "" if value is None else str(value)


def compare_anchor_runs(
    previous: dict[tuple[str, str], dict[str, Any]],
    current: list[dict[str, Any]],
) -> AnchorDriftReport:
    """Diff the previous ``table-anchors.yaml`` against the rows about to replace it.

    *previous* is :func:`~kairos_ontology.core.anchor_tables.load_table_anchors`' mapping;
    *current* is the freshly built ``tables`` list. A first run (no previous artifact)
    reports nothing: there is no drift, only a beginning.
    """
    report = AnchorDriftReport()
    if not previous:
        return report

    seen: set[tuple[str, str]] = set()
    for row in current:
        key = (str(row.get("system") or ""), str(row.get("table") or ""))
        seen.add(key)
        before = previous.get(key)
        if before is None:
            report.added.append(f"{key[0]}.{key[1]}")
            continue
        changed: dict[str, tuple[Any, Any]] = {}
        for name in TRACKED_FIELDS:
            was, now = _normalise(before.get(name)), _normalise(row.get(name))
            if was != now:
                changed[name] = (before.get(name), row.get(name))
        for name in NOISY_FIELDS:
            if _normalise(before.get(name)) != _normalise(row.get(name)):
                report.confidence_moved += 1
        if changed:
            report.drifted.append(AnchorDrift(key[0], key[1], changed))
        else:
            report.unchanged += 1

    for key in previous:
        if key not in seen:
            report.removed.append(f"{key[0]}.{key[1]}")
    report.drifted.sort(key=lambda item: item.relation)
    report.added.sort()
    report.removed.sort()
    return report


def render_drift_summary(report: AnchorDriftReport, *, limit: int = 12) -> list[str]:
    """Console lines for a re-run, or ``[]`` when nothing moved."""
    if report.is_first_run:
        return []
    if not (report.drifted or report.added or report.removed):
        return [
            f"  ⚓ no drift since the last run — {report.unchanged} entr"
            f"{'y' if report.unchanged == 1 else 'ies'} unchanged"
        ]

    counts = report.counts()
    headline = ", ".join(f"{count} {name}" for name, count in counts.items())
    if not report.drifted:
        # Only tables added or gone -- the usual --only-new run (#1050). Nothing moved,
        # so there is no drift to headline and no reproducibility warning to give.
        lines = [
            f"  ⚓ no existing entry moved since the last run — {report.unchanged} unchanged"
        ]
        if report.added:
            lines.append(f"     newly anchored: {', '.join(report.added[:6])}")
        if report.removed:
            lines.append(f"     no longer present: {', '.join(report.removed[:6])}")
        return lines
    lines = [
        f"  ⚓ DRIFT since the last run: {headline} changed across "
        f"{len(report.drifted)} table(s); {report.unchanged} unchanged.",
    ]
    if "natural_key" in counts:
        lines.append(
            "     natural_key is not advisory — it becomes the binding's identity and "
            "the silver contract's uniqueness test."
        )
    for item in report.drifted[:limit]:
        lines.append(f"       {item.describe()}")
    if len(report.drifted) > limit:
        lines.append(f"       … and {len(report.drifted) - limit} more")
    if report.added:
        lines.append(f"     newly anchored: {', '.join(report.added[:6])}")
    if report.removed:
        lines.append(f"     no longer present: {', '.join(report.removed[:6])}")
    lines.append(
        "     Anchoring is not reproducible at this prompt size (DD-177). Pin the rows "
        "you have judged with status: confirmed so a re-run stops moving them, or run "
        "with --only-new to anchor only tables that have no entry yet."
    )
    return lines
