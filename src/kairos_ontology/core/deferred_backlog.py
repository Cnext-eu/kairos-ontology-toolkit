# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The deferred backlog: column-grain ``deferred`` decisions kept in view (DD-251, #1062).

``deferred`` is defined as "in scope and modelled later; carries a reason and stays
visible as a known gap". Until DD-251 nothing downstream showed a column-grain entry
again: the DD-169 gate counted it decided, the decision sheet dropped it on every
redraft, ``generate-bindings`` and ``scaffold-extensions`` read only
``registered-extension``, ``next`` raised no action for it, and ``alignment-report`` never
read the ledger at all. The honest answer for "real data, not modelled yet" was also the
answer that ended the column's life cycle. On one hub the ledger held about 2,630 such
entries, among them airline names and codes, a party role qualifier and a container
customs status.

This module is the one reader of that backlog. :func:`load_deferred_columns` joins the
ledger with the anchors sheet (domain), the source vocabulary (row count) and the imported
Power BI models (demand), and ranks what a modeller should look at first.
:func:`decision_overlay` lays the ledger and the bindings over an alignment report so
``alignment-report`` can tell an undecided column from a deferred one from a ruled-out
one, which the memoized report itself never does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .alignment_report import AlignmentReport, UnmappedColumn, annotate_read_by
from .bound_columns import (
    BoundColumns,
    is_gap_column_decided,
    load_bound_columns,
    retired_by_binding,
)
from .sibling_columns import Sibling, column_profiles, detect_sibling, sinks
from .source_disposition import column_decision, load_dispositions, load_source_tables

#: How a decided gap column is summarised per domain. ``ruled_out`` groups the two
#: dispositions that take a column out of Silver for good.
RULED_OUT = frozenset({"not-business-data", "blueprint-gap"})

NO_DOMAIN = ""


@dataclass(frozen=True, slots=True)
class DeferredColumn:
    """One column-grain ``deferred`` ledger entry, with what ranks it."""

    system: str
    table: str
    column: str
    domain: str = NO_DOMAIN
    rationale: str = ""
    decided_by: str = ""
    #: The ``recorded_on`` date the ledger carries since DD-251; empty on older rows.
    recorded_on: str = ""
    #: The table's ``kairos-bronze:rowCount``; ``None`` when the vocabulary has none.
    row_count: int | None = None
    #: Where an imported Power BI model uses this column name (#942).
    bi_demand: tuple[str, ...] = ()
    #: The bound field on the same table this column completes (#1068), if any.
    sibling: Sibling | None = None
    #: The DD-189 profile says the column is empty or constant: it sorts last (#1068).
    sunk: bool = False
    #: The first DD-248 closure candidate the alignment found for the column: a field
    #: suggestion for the binding author, never a ledger ``bound`` row (#1068).
    suggested_property: str = ""

    @property
    def rank(self) -> tuple[int, int, int, int, str, str, str]:
        """BI demand, then not empty or constant, then a sibling of a bound field, then
        the largest table, then name order (#1068)."""
        rows = self.row_count if self.row_count is not None else -1
        return (
            0 if self.bi_demand else 1,
            1 if self.sunk else 0,
            0 if self.sibling else 1,
            -rows,
            self.system,
            self.table,
            self.column,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "table": self.table,
            "column": self.column,
            "domain": self.domain,
            "rationale": self.rationale,
            "decided_by": self.decided_by,
            "recorded_on": self.recorded_on,
            "row_count": self.row_count,
            "bi_demand": list(self.bi_demand),
            "sibling": self.sibling.to_dict() if self.sibling else None,
            "sunk": self.sunk,
            "suggested_property": self.suggested_property,
        }


@dataclass
class DeferredBacklog:
    """Every column-grain ``deferred`` entry, ranked within its domain."""

    columns: list[DeferredColumn] = field(default_factory=list)
    #: Column-grain ``deferred`` rows a relation binding now names (#1069). They are
    #: modelled, so they are not backlog; the ledger row is stale and can be removed.
    retired: list[DeferredColumn] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.columns)

    @property
    def with_bi_demand(self) -> int:
        return sum(1 for c in self.columns if c.bi_demand)

    @property
    def with_siblings(self) -> int:
        return sum(1 for c in self.columns if c.sibling)

    def siblings_by_table(self) -> list[tuple[str, list[DeferredColumn]]]:
        """``("system.table", ranked siblings)``, the table with most siblings first."""
        grouped: dict[str, list[DeferredColumn]] = {}
        for column in self.columns:
            if column.sibling:
                grouped.setdefault(f"{column.system}.{column.table}", []).append(column)
        return sorted(
            ((table, sorted(cols, key=lambda c: c.rank)) for table, cols in grouped.items()),
            key=lambda kv: (-len(kv[1]), kv[0]),
        )

    def by_domain(self) -> dict[str, list[DeferredColumn]]:
        """Ranked columns per domain, largest domain first; the domainless last."""
        grouped: dict[str, list[DeferredColumn]] = {}
        for column in self.columns:
            grouped.setdefault(column.domain, []).append(column)
        ordered = sorted(
            grouped.items(), key=lambda kv: (kv[0] == NO_DOMAIN, -len(kv[1]), kv[0])
        )
        return {domain: sorted(columns, key=lambda c: c.rank) for domain, columns in ordered}

    def by_table(self, domain: str) -> dict[str, list[DeferredColumn]]:
        grouped: dict[str, list[DeferredColumn]] = {}
        for column in self.by_domain().get(domain, []):
            grouped.setdefault(f"{column.system}.{column.table}", []).append(column)
        return grouped

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "with_bi_demand": self.with_bi_demand,
            "with_siblings": self.with_siblings,
            "retired_by_binding": [c.to_dict() for c in self.retired],
            "domains": [
                {
                    "domain": domain,
                    "count": len(columns),
                    "with_bi_demand": sum(1 for c in columns if c.bi_demand),
                    "columns": [c.to_dict() for c in columns],
                }
                for domain, columns in self.by_domain().items()
            ],
        }


def load_deferred_columns(
    hub_root: Path,
    *,
    domain_of: Callable[[str, str, str], str] | None = None,
    bound: BoundColumns | None = None,
    closure_of: Callable[[str, str, str], str] | None = None,
) -> DeferredBacklog:
    """Read the deferred backlog from the ledger, joined with what ranks it.

    *domain_of* answers the domain for ``(system, table, column)`` when the caller has
    an alignment report in hand; the ledger itself carries no domain. Without it, or when
    it answers empty, the anchors sheet's domain for the table is used, then none.

    Every reader degrades to nothing rather than raising: ``next`` calls this on a hub in
    any state, and a half-written vocabulary or a missing anchors sheet must not take it
    down. Row counts come from the textual ``rowCount`` read ``validate`` uses, not from
    an rdflib parse of every source file.

    A row whose column a ``source.relation`` binding now names is retired, not backlog
    (DD-251, #1069): it goes to :attr:`DeferredBacklog.retired`. *bound* lets a caller
    that already holds the bindings' view pass it in; unreadable bindings retire nothing.

    Each backlog column is also related to its table's bound fields (#1068). ``sibling``
    names the bound field it completes, ``sunk`` says the profile found it empty or
    constant, and ``suggested_property`` carries the first closure candidate *closure_of*
    answers. The alignment report has those candidates, so only a caller holding one can
    fill it in.
    """
    root = Path(hub_root)
    try:
        recorded = load_dispositions(root)
    except Exception:  # noqa: BLE001 - a broken ledger is reported elsewhere
        return DeferredBacklog()
    deferred = [
        (key, entry)
        for key, entry in sorted(recorded.items())
        if key[2] and str(entry.get("disposition") or "") == "deferred"
    ]
    if not deferred:
        return DeferredBacklog()
    if bound is None:
        bound = _bound_columns(root)
    anchors = _anchor_domains(root)
    row_counts = _row_counts(root)
    demand = _bi_demand(root)
    profile = column_profiles(root)
    columns: list[DeferredColumn] = []
    retired: list[DeferredColumn] = []
    for (system, table, column), entry in deferred:
        domain = domain_of(system, table, column) if domain_of is not None else ""
        if not domain:
            domain = anchors.get((system, table), NO_DOMAIN)
        count = row_counts.get((system, table))
        column_profile = profile(system, table, column)
        target = retired if retired_by_binding(entry, bound, system, table, column) else columns
        target.append(
            DeferredColumn(
                system=system,
                table=table,
                column=column,
                domain=domain,
                rationale=str(entry.get("rationale") or ""),
                decided_by=str(entry.get("decided_by") or ""),
                recorded_on=str(entry.get("recorded_on") or ""),
                row_count=count if count is not None and count >= 0 else None,
                bi_demand=tuple(demand(column)),
                sibling=detect_sibling(
                    column, bound.bound_fields(system, table), profile=column_profile
                ),
                sunk=sinks(column_profile),
                suggested_property=closure_of(system, table, column) if closure_of else "",
            )
        )
    return DeferredBacklog(columns, retired)



def _bound_columns(hub_root: Path) -> BoundColumns:
    from .bound_columns import EMPTY_BOUND_COLUMNS

    try:
        return load_bound_columns(hub_root / "integration" / "bindings", hub_root)
    except Exception:  # noqa: BLE001 - advisory join; a broken binding is reported by compile
        return EMPTY_BOUND_COLUMNS


def _anchor_domains(hub_root: Path) -> dict[tuple[str, str], str]:
    try:
        from .anchor_tables import load_table_anchors

        anchors = load_table_anchors(hub_root / "integration" / "sources" / "_analysis")
    except Exception:  # noqa: BLE001 - advisory join
        return {}
    return {key: str(row.get("domain") or "") for key, row in anchors.items()}


def _row_counts(hub_root: Path) -> dict[tuple[str, str], int]:
    try:
        return load_source_tables(hub_root / "integration" / "sources")
    except Exception:  # noqa: BLE001 - advisory join
        return {}


def _bi_demand(hub_root: Path) -> Callable[[str], list[str]]:
    try:
        from .bi_demand import load_bi_demand

        demand = load_bi_demand(hub_root)
    except Exception:  # noqa: BLE001 - advisory join
        return lambda column: []
    return lambda column: demand.describe(column, limit=3)


# ---------------------------------------------------------------------------
# The decision overlay for alignment-report
# ---------------------------------------------------------------------------


@dataclass
class DecisionOverlay:
    """The ledger and the bindings laid over one alignment report.

    ``status`` holds, per gap column, ``undecided``, ``bound`` (a ledger row or a binding
    that names it, DD-250), or the recorded disposition. Built from the same predicate the
    DD-169 gate uses, so the report cannot list a column the gate does not, or hide one it
    does.
    """

    status: dict[tuple[str, str, str], str] = field(default_factory=dict)
    bound: BoundColumns | None = None
    backlog: DeferredBacklog = field(default_factory=DeferredBacklog)

    def status_of(self, column: UnmappedColumn) -> str:
        return self.status.get((column.system, column.table, column.column), "undecided")

    def undecided(self, report: AlignmentReport) -> list[UnmappedColumn]:
        """The gate's view: undecided gap columns, with the dbtModel-chain evidence on."""
        columns = [c for c in report.gap_columns if self.status_of(c) == "undecided"]
        if self.bound is None:
            return columns
        return [annotate_read_by(c, self.bound) for c in columns]

    def domain_totals(self, report: AlignmentReport) -> dict[str, dict[str, int]]:
        """Per domain: how the gap columns split by decision state."""
        totals: dict[str, dict[str, int]] = {}
        for domain in report.domains:
            counts = {"deferred": 0, "ruled_out": 0, "extension": 0, "bound": 0, "undecided": 0}
            for column in domain.gap_columns:
                status = self.status_of(column)
                if status == "deferred":
                    counts["deferred"] += 1
                elif status in RULED_OUT:
                    counts["ruled_out"] += 1
                elif status == "registered-extension":
                    counts["extension"] += 1
                elif status == "bound":
                    counts["bound"] += 1
                else:
                    counts["undecided"] += 1
            totals[domain.domain] = counts
        return totals


def decision_overlay(report: AlignmentReport, hub_root: Path) -> DecisionOverlay:
    """Build the overlay for *report* from the hub at *hub_root*."""
    root = Path(hub_root)
    recorded = load_dispositions(root)
    bound = load_bound_columns(root / "integration" / "bindings", root)
    status: dict[tuple[str, str, str], str] = {}
    domains: dict[tuple[str, str, str], str] = {}
    closure: dict[tuple[str, str, str], str] = {}
    for domain in report.domains:
        for column in domain.gap_columns:
            key = (column.system, column.table, column.column)
            domains.setdefault(key, domain.domain)
            if column.closure_candidates and key not in closure:
                first = column.closure_candidates[0]
                closure[key] = str(first.get("name") or first.get("uri") or "")
            decided = is_gap_column_decided(recorded, bound, *key)
            if decided == "binding":
                status[key] = "bound"
            elif decided == "ledger":
                entry = column_decision(recorded, *key) or {}
                status[key] = str(entry.get("disposition") or "undecided")
            else:
                status[key] = "undecided"
    backlog = load_deferred_columns(
        root,
        domain_of=lambda system, table, column: domains.get((system, table, column), ""),
        bound=bound,
        closure_of=lambda system, table, column: closure.get((system, table, column), ""),
    )
    return DecisionOverlay(status=status, bound=bound, backlog=backlog)
