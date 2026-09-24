# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Source-table disposition ledger (DD-164).

The blueprint deliberately scopes which domains exist, so a hub will always hold source
tables that no blueprint domain claims. Today that produces a silent fork: the table is
either dropped ("no canonical entity") or force-fitted by minting a local class in
whichever domain happened to be in scope. Both outcomes are unrecorded, and a real run
produced both *for the same table* — ``comments`` (3,149 rows) was dropped from
``claims`` as having no canonical home while a local ``Comment`` class appeared in four
other domains.

This module removes the silent fork by making the decision an artifact. Every source
table above :data:`DEFAULT_ROW_THRESHOLD` rows must be either bound or carry an explicit
disposition; an unbound, undisposed table is an error, not an omission.

The point is not to force every table into the ontology. ``not-business-data`` is a
perfectly good answer — it just has to be an answer someone wrote down, with a reason,
rather than the absence of one.
"""

from __future__ import annotations

import copy
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import analysis_paths, yaml_io

SCHEMA_VERSION = 1

#: Tables smaller than this are not worth a human decision; below it an unbound table is
#: reported as informational only. Tuned to sit under the smallest table in the CLdN run
#: that was silently dropped while carrying real business content.
DEFAULT_ROW_THRESHOLD = 100

#: The pre-5.22 single ledger for every source system. Still read, and split into one
#: ``src-<system>.table-dispositions.yaml`` per system by the first write or by
#: ``update`` (#943, DD-235); see :func:`ledger_path` for where decisions are written.
LEGACY_LEDGER_FILENAME = "table-dispositions.yaml"
DISPOSITIONS_RELPATH = analysis_paths.ANALYSIS_RELPATH / LEGACY_LEDGER_FILENAME

#: Dispositions whose cascade onto the table's own columns is the point of recording
#: them (#881).
#:
#: A table-grain decision used to retire every gap column in that table from the DD-169
#: gate, whatever the decision said. That reasoning holds for exactly two values:
#: ``not-business-data`` (the table is not business data, so neither are its columns) and
#: ``blueprint-gap`` (a claim about the reference model, which is a claim about what the
#: columns needed).
#:
#: It does not hold for the rest, and the omissions were the damaging ones:
#:
#: * ``deferred`` means "in scope, not modelled yet" -- precisely the state DD-169 exists
#:   to keep raising. It is also the only value that is not an assertion about the data
#:   being junk or the blueprint being broken, so it is what an operator reaches for.
#: * ``bound`` and ``registered-extension`` assert the table *is* being modelled. They
#:   are when the gate matters most: an EntityBinding either maps a column or silently
#:   leaves it behind, and by then the omission looks like a completed mapping.
#:
#: On one real hub, 40 table-grain ``deferred`` records retired 1,643 columns and the
#: gate never fired once.
CASCADING_DISPOSITIONS: frozenset[str] = frozenset({"not-business-data", "blueprint-gap"})

#: Table-grain dispositions that mean "do not generate a binding for this table" (#918).
#:
#: ``bound`` is deliberately absent: it is the one table-grain value that asserts a binding
#: *exists*, so skipping on it would make the ledger self-defeating. The other three each
#: say, in their own way, that the table is not being modelled — not business data, a gap
#: in the reference model, or in scope but not yet.
#:
#: Distinct from :data:`CASCADING_DISPOSITIONS`, which answers a different question: which
#: table-grain values also answer for the table's *columns* in the DD-169 gate (#881).
#: ``deferred`` is here and not there, because "in scope, not modelled yet" is a reason to
#: skip generation and is not a reason to stop asking about the columns.
NON_GENERATING_DISPOSITIONS: frozenset[str] = frozenset(
    {"not-business-data", "blueprint-gap", "deferred"}
)

#: The closed set of answers. Each is a decision someone can defend in review.
DISPOSITIONS: dict[str, str] = {
    # Derived, never recorded: `audit_source_dispositions` reads it from
    # integration/bindings/ before it consults this ledger, so authoring the binding is
    # what states it. A table-grain row saying `bound` adds nothing the bindings
    # directory does not already say, and used to silence the table's columns (#881).
    "bound": "An EntityBinding maps this table to a canonical class.",
    # Grain matters here, and the two answers are different commands (#883):
    #   table-grain   the table is a concept the archetype catalog lacks -> register it
    #                 with 'register-concept', which mints a CLASS and rejects a URI the
    #                 catalog already has.
    #   column-grain  the column is a fact an existing class has no property for -> the
    #                 hub declares a property for it (DD-170), drafted from the ledger by
    #                 'scaffold-extensions'. register-concept cannot serve this case and
    #                 pointing at it is what left 501 such decisions with no consumer.
    "registered-extension": (
        "Real business data outside the archetype catalog. At table grain, a concept to "
        "register with 'kairos-ontology register-concept'; at column grain, a hub-local "
        "property on an existing class, drafted with 'kairos-ontology "
        "scaffold-extensions'."
    ),
    "deferred": ("In scope and modelled later; carries a reason and stays visible as a known gap."),
    "not-business-data": (
        "Metadata, schema-lookup, workflow, or scratch table with no canonical meaning."
    ),
    "blueprint-gap": (
        "Real business data the accelerator blueprint has no domain for — a reference-model "
        "defect to file upstream rather than a hub-side modelling choice."
    ),
}

#: Dispositions a human (or an attributed agent) must justify in prose.
_REQUIRES_RATIONALE = frozenset({"deferred", "not-business-data", "blueprint-gap"})

_ROW_COUNT_RE = re.compile(r"kairos-bronze:rowCount\s+(\d+)")
_TABLE_NAME_RE = re.compile(r'kairos-bronze:tableName\s+"((?:[^"\\]|\\.)*)"')
# One ``kairos-bronze:SourceTable`` block: everything from the type assertion to the
# statement-terminating " ." at the start of a line's end.
_SOURCE_TABLE_BLOCK_RE = re.compile(
    r"a\s+kairos-bronze:SourceTable\s*;(.*?)\.\s*$",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class DispositionDiagnostic:
    level: str  # "error" | "warning" | "info"
    code: str
    message: str
    system: str
    table: str
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "system": self.system,
            "table": self.table,
            "remediation": self.remediation,
        }


@dataclass
class DispositionReport:
    schema_version: int = SCHEMA_VERSION
    diagnostics: list[DispositionDiagnostic] = field(default_factory=list)
    tables_total: int = 0
    tables_bound: int = 0
    tables_disposed: int = 0
    tables_undecided: int = 0
    notices: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[DispositionDiagnostic]:
        return [d for d in self.diagnostics if d.level == "error"]

    @property
    def warnings(self) -> list[DispositionDiagnostic]:
        return [d for d in self.diagnostics if d.level == "warning"]

    @property
    def is_blocking(self) -> bool:
        return bool(self.errors)

    def coverage(self) -> float:
        """Fraction of tables with *any* recorded outcome — bound or explicitly disposed."""
        if not self.tables_total:
            return 1.0
        return round((self.tables_bound + self.tables_disposed) / self.tables_total, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "totals": {
                "tables": self.tables_total,
                "bound": self.tables_bound,
                "disposed": self.tables_disposed,
                "undecided": self.tables_undecided,
            },
            "decision_coverage": self.coverage(),
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "notices": list(self.notices),
        }


def load_source_tables(sources_dir: Path) -> dict[tuple[str, str], int]:
    """Return ``{(system, table): row_count}`` for every imported source table.

    Row counts are read textually from the ``kairos-bronze:rowCount`` triple rather than
    through a graph parse: this is a size lookup used to rank human attention, not
    semantic access, and it must stay cheap enough to run inside ``validate``.
    A table with no recorded count is reported as ``-1`` (unknown) and always warrants a
    decision, since "we do not know how big it is" is not evidence that it is empty.
    """
    tables: dict[tuple[str, str], int] = {}
    if not sources_dir.is_dir():
        return tables
    for system_dir in sorted(sources_dir.iterdir()):
        if not system_dir.is_dir() or system_dir.name.startswith(("_", ".")):
            continue
        for path in sorted(system_dir.glob("*.ttl")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for block in _SOURCE_TABLE_BLOCK_RE.finditer(text):
                body = block.group(1)
                # ``tableName`` is the physical name an EntityBinding's ``source.relation``
                # refers to ("qargo.companies"); the subject IRI is a PascalCase-ified
                # variant of it and would never match.
                name_match = _TABLE_NAME_RE.search(body)
                if name_match is None:
                    continue
                count_match = _ROW_COUNT_RE.search(body)
                tables[(system_dir.name, name_match.group(1))] = (
                    int(count_match.group(1)) if count_match else -1
                )
    return tables


def load_bound_relations(bindings_dir: Path, hub_root: Path) -> set[tuple[str, str]]:
    """Return ``{(system, table)}`` for every source table an EntityBinding already maps.

    Two authored forms bind a table and both count (#939). ``source.relation`` names one
    relation outright. ``source.dbtModel`` -- DD-133 §3d's mechanism for a binding whose
    grain needs relational work first -- names a contracted model, and every source table
    that model's SQL reads is read, mapped and emitted to Silver just as directly. Seeing
    only the first form, this audit reported those tables as undecided, and the only ways
    to silence it were a ledger row the ledger's own documentation calls unnecessary
    ("authoring the binding is what states it") or one it calls redundant. It also cost
    the #925 ``bound-and-ruled-out`` conflict, computed from this same set: a
    ``dbtModel``-bound table that was *also* ruled out read as merely unbound.

    Model SQL is scanned with the compiler's :func:`extract_source_pairs`, the single
    extraction authority, so this audit can never disagree with the two closure walks
    about which sources a model reads. Only the selected model is scanned, not its
    transitive ``ref()`` closure: resolving that needs a parsed ``EntityBinding`` and
    raises on the first defect, which is the compiler's job, not an advisory audit's. A
    source table reached only through an upstream ``ref()``ed model is therefore still
    reported undecided.

    *hub_root* resolves the binding's repository-relative ``sqlPath``. An unreadable path
    is skipped rather than raised on, matching this function's existing posture toward a
    malformed binding.
    """
    bound: set[tuple[str, str]] = set()
    if not bindings_dir.is_dir():
        return bound
    for path in sorted(bindings_dir.glob("*.yaml")):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:  # defensive: a malformed binding is the compiler's problem
            continue
        if not isinstance(payload, dict):
            continue
        raw_source = payload.get("source")
        source: dict[str, Any] = raw_source if isinstance(raw_source, dict) else {}
        relation = source.get("relation")
        if isinstance(relation, str) and "." in relation:
            system, _, table = relation.partition(".")
            bound.add((system.strip(), table.strip()))
        bound |= _dbt_model_source_pairs(source, hub_root)
    return bound


def _dbt_model_source_pairs(source: dict[str, Any], hub_root: Path) -> set[tuple[str, str]]:
    """Return the source tables a ``source.dbtModel`` binding's own SQL reads.

    Split out so the two authored source forms read as the independent alternatives they
    are, and so the compiler import stays local: ``source_disposition`` is imported by
    ``validate`` and by hub inspection, neither of which should pull in the compiler to
    read a ledger.
    """
    from .compiler.dbt_source import extract_source_pairs

    model = source.get("dbtModel")
    sql_path = model.get("sqlPath") if isinstance(model, dict) else None
    if not isinstance(sql_path, str) or not sql_path.strip():
        return set()
    try:
        text = (Path(hub_root) / sql_path).read_text(encoding="utf-8")
    except Exception:  # defensive: an unresolvable sqlPath is the compiler's problem
        return set()
    return set(extract_source_pairs(text))


def column_decision(
    recorded: dict[tuple[str, str, str], dict[str, Any]],
    system: str,
    table: str,
    column: str,
) -> dict[str, Any] | None:
    """The ledger entry that decides one column for the DD-169 gate, or ``None``.

    The one definition of "this column is decided" (#948). A column-grain entry always
    decides it; a table-grain entry decides it only when its disposition is in
    :data:`CASCADING_DISPOSITIONS` (#881). The gate, the decision sheet and the
    auto-disposition pass all ask this, so a helper that reports nothing to decide
    while the gate blocks cannot happen again.

    ``recorded`` is :func:`load_dispositions` output.
    """
    if column:
        entry = recorded.get((system, table, column))
        if entry is not None:
            return entry
    table_entry = recorded.get((system, table, ""))
    if (
        table_entry is not None
        and str(table_entry.get("disposition") or "") in CASCADING_DISPOSITIONS
    ):
        return table_entry
    return None


def non_cascading_table_entries(
    recorded: dict[tuple[str, str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Table-grain entries that no longer answer for their table's columns (#881, #948).

    A hub that recorded table-grain ``deferred``, ``bound`` or ``registered-extension``
    before #881 had those entries silence the DD-169 gate for every column in the table.
    They no longer do, so on upgrade the gate starts blocking on columns the operator
    believes are decided. ``update`` reports them so the change is not a surprise.
    """
    return [
        entry
        for (_system, _table, column), entry in sorted(recorded.items())
        if not column and str(entry.get("disposition") or "") not in CASCADING_DISPOSITIONS
    ]


def _yaml_load(text: str) -> Any:
    """Parse ledger YAML with the C loader when available (#943).

    A real hub's ledger ran to 799 KB, and every ``validate``, ``compile`` and
    ``generate-bindings`` reads it. The C loader parses the same document to the same
    value about five times faster; the pure-Python one is the fallback.
    """
    return yaml_io.safe_load(text)


def _yaml_dump(payload: Any) -> str:
    """Serialise the ledger with the C dumper when available; output is byte-identical."""
    dumper = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
    return yaml.dump(payload, Dumper=dumper, sort_keys=False, allow_unicode=True)


def _atomic_write(path: Path, text: str) -> None:
    """Replace *path* in one step, so an interrupted run never leaves half a ledger."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def ledger_path(hub_root: Path, system: str) -> Path:
    """Where *system*'s dispositions are written: ``src-<system>.table-dispositions.yaml``."""
    return analysis_paths.keyed_path(
        analysis_paths.analysis_dir(hub_root), analysis_paths.TABLE_DISPOSITIONS, system
    )


def ledger_files(analysis_dir: Path) -> list[Path]:
    """Every ledger file under *analysis_dir*: the pre-5.22 single file first, then one per
    system, so a per-system entry wins where both record the same key (#943)."""
    directory = Path(analysis_dir)
    files: list[Path] = []
    legacy = directory / LEGACY_LEDGER_FILENAME
    if legacy.is_file():
        files.append(legacy)
    files.extend(
        analysis_paths.iter_keyed_paths(directory, analysis_paths.TABLE_DISPOSITIONS)
    )
    return files


def _read_rows(path: Path) -> list[dict[str, Any]]:
    """One ledger file's entries; raises on unparseable YAML so a writer never drops it."""
    payload = _yaml_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return []
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a disposition ledger (expected a mapping).")
    return [row for row in payload.get("tables") or [] if isinstance(row, dict)]


def _entry_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("system")), str(row.get("table")), str(row.get("column") or ""))


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write one system's ledger sorted by grain, or remove it once it holds nothing."""
    if not rows:
        path.unlink(missing_ok=True)
        return
    payload = {"schema_version": SCHEMA_VERSION, "tables": sorted(rows, key=_entry_key)}
    _atomic_write(path, _yaml_dump(payload))


def split_legacy_ledger(hub_root: Path, *, dry_run: bool = False) -> dict[str, int]:
    """Move the pre-5.22 single ledger into one file per source system (#943).

    One file for every system meant every decision rewrote every other system's
    decisions -- 1,113 of them took twelve minutes. Entries keep their exact content;
    where a system's file already holds the same key, that entry wins, because it was
    written after the upgrade. Entries with no ``system`` cannot be placed and keep the
    legacy file alive, holding only them.

    Called by every writer before it writes and by ``update``, so the two layouts never
    both hold live decisions for long. Returns ``{system: entries_moved}``.
    """
    directory = analysis_paths.analysis_dir(hub_root)
    legacy = directory / LEGACY_LEDGER_FILENAME
    if not legacy.is_file():
        return {}
    rows = _read_rows(legacy)
    by_system: dict[str, list[dict[str, Any]]] = {}
    orphans: list[dict[str, Any]] = []
    for row in rows:
        system = str(row.get("system") or "").strip()
        (by_system.setdefault(system, []) if system else orphans).append(row)
    moved = {system: len(entries) for system, entries in sorted(by_system.items())}
    if dry_run:
        return moved
    for system, entries in by_system.items():
        target = ledger_path(hub_root, system)
        current = {_entry_key(r): r for r in (_read_rows(target) if target.is_file() else [])}
        merged = {_entry_key(r): r for r in entries}
        merged.update(current)
        _write_rows(target, list(merged.values()))
    if orphans:
        _atomic_write(legacy, _yaml_dump({"schema_version": SCHEMA_VERSION, "tables": orphans}))
    else:
        legacy.unlink()
    return moved


#: ``load_dispositions`` results, keyed by every ledger file's ``(path, mtime_ns, size)``
#: (#968). ``compile --all`` asked for the ledger twice per domain -- 30 parses of a
#: 0.99 MB file on a 15-domain hub, 36% of the run -- and nothing in between changed it.
_DISPOSITIONS_CACHE: dict[tuple, dict[tuple[str, str, str], dict[str, Any]]] = {}


def _ledger_stamp(paths: list[Path]) -> tuple:
    stamp = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        stamp.append((str(path.resolve()), stat.st_mtime_ns, stat.st_size))
    return tuple(stamp)


def load_dispositions(hub_root: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Read every ledger file, or ``{}`` when the hub has not written one yet.

    Keys are ``(system, table, column)``, with ``""`` for a table-grain entry. An
    unreadable file contributes nothing rather than failing the reader; the writers,
    which must not silently drop a file's contents, refuse instead.

    Memoised per process on each file's path, modification time and size, so a write
    in the same process (``record_dispositions``) is seen by the next read. A deep copy
    is returned: callers may mutate what they get without touching the cache.
    """
    paths = ledger_files(analysis_paths.analysis_dir(hub_root))
    stamp = _ledger_stamp(paths)
    cached = _DISPOSITIONS_CACHE.get(stamp)
    if cached is None:
        cached = _load_dispositions_uncached(paths)
        _DISPOSITIONS_CACHE.clear()
        _DISPOSITIONS_CACHE[stamp] = cached
    return copy.deepcopy(cached)


def _load_dispositions_uncached(
    paths: list[Path],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    recorded: dict[tuple[str, str, str], dict[str, Any]] = {}
    for path in paths:
        try:
            rows = _read_rows(path)
        except Exception:
            continue
        for entry in rows:
            system = str(entry.get("system") or "").strip()
            table = str(entry.get("table") or "").strip()
            if system and table:
                recorded[(system, table, str(entry.get("column") or ""))] = entry
    return recorded


def audit_source_dispositions(
    *,
    hub_root: Path,
    row_threshold: int = DEFAULT_ROW_THRESHOLD,
) -> DispositionReport:
    """Require an explicit outcome for every source table of consequence."""
    hub_root = Path(hub_root)
    sources_dir = hub_root / "integration" / "sources"
    tables = load_source_tables(sources_dir)
    report = DispositionReport(tables_total=len(tables))
    if not tables:
        report.notices.append(
            f"No imported source tables found under {sources_dir}; nothing to decide."
        )
        return report

    bound = load_bound_relations(hub_root / "integration" / "bindings", hub_root)
    recorded = load_dispositions(hub_root)

    for (system, table), row_count in sorted(tables.items()):
        key = (system, table)
        if key in bound:
            # A bound table normally needs no ledger row -- authoring the binding is what
            # states `bound`. But a table that is bound *and* ruled out is a contradiction
            # the hub cannot act on, and it used to pass silently: this branch returned
            # before the ledger was read, so a stale binding for a dispositioned table
            # counted as bound and shipped to Silver (#925).
            conflict = recorded.get((*key, ""))
            ruling = str((conflict or {}).get("disposition") or "")
            if ruling in NON_GENERATING_DISPOSITIONS:
                report.diagnostics.append(
                    DispositionDiagnostic(
                        level="error",
                        code="disposition.bound-and-ruled-out",
                        message=(
                            f"{system}.{table} is bound by a binding in integration/bindings/ "
                            f"and also recorded as '{ruling}' in the ledger. The binding wins: "
                            "compile reads the directory, so the table reaches Silver despite "
                            "the ruling."
                        ),
                        system=system,
                        table=table,
                        remediation=(
                            "Delete the binding if the ruling stands (re-running "
                            "generate-bindings now does this), or clear the ledger row if "
                            "the table is genuinely in scope."
                        ),
                    )
                )
                continue
            report.tables_bound += 1
            continue

        entry = recorded.get((*key, ""))
        if entry is not None:
            disposition = str(entry.get("disposition") or "").strip()
            if disposition not in DISPOSITIONS:
                report.diagnostics.append(
                    DispositionDiagnostic(
                        level="error",
                        code="disposition.unknown-value",
                        message=(
                            f"{system}.{table} records disposition '{disposition}', which is "
                            f"not one of: {', '.join(sorted(DISPOSITIONS))}."
                        ),
                        system=system,
                        table=table,
                        remediation="Use one of the closed disposition values.",
                    )
                )
                continue
            if disposition in _REQUIRES_RATIONALE and not str(entry.get("rationale") or "").strip():
                report.diagnostics.append(
                    DispositionDiagnostic(
                        level="error",
                        code="disposition.missing-rationale",
                        message=(
                            f"{system}.{table} is recorded as '{disposition}' with no rationale."
                        ),
                        system=system,
                        table=table,
                        remediation=(
                            "State why, in one sentence. A reviewer cannot tell a considered "
                            "skip from an overlooked table without it."
                        ),
                    )
                )
                continue
            report.tables_disposed += 1
            continue

        report.tables_undecided += 1
        size = "unknown size" if row_count < 0 else f"{row_count:,} rows"
        significant = row_count < 0 or row_count >= row_threshold
        report.diagnostics.append(
            DispositionDiagnostic(
                level="error" if significant else "warning",
                code="disposition.undecided-source-table",
                message=(
                    f"Source table {system}.{table} ({size}) is neither bound nor given an "
                    "explicit disposition."
                ),
                system=system,
                table=table,
                remediation=(
                    "Record the outcome with 'kairos-ontology source-disposition set "
                    f"--system {system} --table {table} --disposition <"
                    + "|".join(sorted(DISPOSITIONS))
                    + '> --rationale "..."\'. If it holds real business data the blueprint '
                    "has no home for, prefer 'registered-extension' (and run "
                    "'kairos-ontology register-concept') or 'blueprint-gap' over dropping it."
                ),
            )
        )

    return report


def clear_dispositions(
    hub_root: Path,
    *,
    tables: set[tuple[str, str]] | None = None,
    column: str | None = None,
    disposition: str | None = None,
    decided_by: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove matching disposition entries, returning what was (or would be) removed.

    Deferring a column is a decision, and so is undeferring it. A blanket
    ``deferred`` applied to a core operational table does clear the DD-169 gate,
    but it parks the very columns the hub exists to model — so there has to be a
    way to take it back that is as auditable as recording it was.

    Filters are conjunctive and all optional; ``decided_by`` is the important one
    in practice, because it lets an agent's blanket answers be withdrawn without
    touching a decision a human actually made. ``column`` matches one column-grain
    entry by name; ``""`` matches table-grain entries only.
    """

    def matches(entry: dict[str, Any]) -> bool:
        if tables is not None:
            if (str(entry.get("system") or ""), str(entry.get("table") or "")) not in tables:
                return False
        if column is not None and str(entry.get("column") or "") != column:
            return False
        if disposition is not None and str(entry.get("disposition") or "") != disposition:
            return False
        if decided_by is not None and str(entry.get("decided_by") or "") != decided_by:
            return False
        return True

    if not dry_run:
        split_legacy_ledger(hub_root)
    removed_count = kept_count = 0
    by_table: dict[str, int] = {}
    for path in ledger_files(analysis_paths.analysis_dir(hub_root)):
        rows = _read_rows(path)
        kept = [e for e in rows if not matches(e)]
        for entry in rows:
            if matches(entry):
                key = f"{entry.get('system')}.{entry.get('table')}"
                by_table[key] = by_table.get(key, 0) + 1
        removed_count += len(rows) - len(kept)
        kept_count += len(kept)
        if len(kept) != len(rows) and not dry_run:
            _write_rows(path, kept)
    return {"removed": removed_count, "kept": kept_count, "by_table": by_table}


@dataclass(frozen=True)
class DispositionInput:
    """One decision to record; the arguments of :func:`record_disposition`."""

    system: str
    table: str
    disposition: str
    rationale: str = ""
    decided_by: str = "user"
    evidence: tuple[str, ...] = ()
    column: str = ""
    proposed_property: dict[str, str] | None = None


def _ledger_entry(decision: DispositionInput) -> dict[str, Any]:
    """Validate one decision and render the entry it writes."""
    if decision.disposition not in DISPOSITIONS:
        raise ValueError(
            f"Unknown disposition {decision.disposition!r}; "
            f"expected one of {sorted(DISPOSITIONS)}."
        )
    if decision.disposition == "bound" and not decision.column:
        raise ValueError(
            "'bound' is not recorded in the ledger: the DD-164 audit reads it from "
            "integration/bindings/ before it looks here, so authoring the EntityBinding "
            "is what states it. Recording it as a table-grain row adds nothing and used "
            "to retire the table's columns from the DD-169 gate (#881). Author the "
            "binding, or record why the table is not being bound."
        )
    if decision.disposition in _REQUIRES_RATIONALE and not decision.rationale.strip():
        raise ValueError(f"Disposition {decision.disposition!r} requires a rationale.")
    if not decision.system.strip():
        raise ValueError("A disposition needs the source system it belongs to.")

    entry: dict[str, Any] = {
        "system": decision.system,
        "table": decision.table,
        # Column-grain entries sit in the same file as the system's table-grain ones
        # (DD-169): a reviewer reads everything one source's tables and columns were
        # decided not to model in one place.
        **({"column": decision.column} if decision.column else {}),
        "disposition": decision.disposition,
        "rationale": decision.rationale,
        "decided_by": decision.decided_by,
    }
    proposed = decision.proposed_property
    if proposed and proposed.get("name"):
        entry["proposed_property"] = {
            key: str(proposed[key])
            for key in ("name", "range", "on_class", "why")
            if proposed.get(key)
        }
    if decision.evidence:
        entry["evidence"] = list(decision.evidence)
    return entry


def record_dispositions(
    hub_root: Path,
    decisions: Iterable[DispositionInput],
    *,
    progress: Callable[[str, int], None] | None = None,
) -> list[Path]:
    """Write or replace many dispositions, reading and writing each system's file once.

    The batch path (#943). Recording one decision at a time re-read and re-wrote the
    whole ledger per decision, so a 1,113-column decision sheet spent twelve minutes on
    YAML round trips. Every decision is validated before anything is written, so a bad
    one never leaves half a batch recorded. *progress* is called with ``(system, count)``
    as each system's file is written. Returns the files written, in system order.

    Replacement is at the same grain: ``(system, table, column)`` is the identity.
    Matching on ``(system, table)`` alone once made every column-grain write delete the
    table's other columns, so a run recording 224 column dispositions kept about one
    per table.
    """
    entries = [_ledger_entry(decision) for decision in decisions]
    if not entries:
        return []
    split_legacy_ledger(hub_root)
    by_system: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_system.setdefault(entry["system"], []).append(entry)
    written: list[Path] = []
    for system in sorted(by_system):
        path = ledger_path(hub_root, system)
        rows = {_entry_key(r): r for r in (_read_rows(path) if path.is_file() else [])}
        for entry in by_system[system]:
            rows[_entry_key(entry)] = entry
        _write_rows(path, list(rows.values()))
        if progress is not None:
            progress(system, len(by_system[system]))
        written.append(path)
    return written


def record_disposition(
    *,
    hub_root: Path,
    system: str,
    table: str,
    disposition: str,
    rationale: str = "",
    decided_by: str = "user",
    evidence: tuple[str, ...] = (),
    column: str = "",
    proposed_property: dict[str, str] | None = None,
) -> Path:
    """Write or replace one disposition, returning the system's ledger path.

    *proposed_property* is the hub-local property ``propose-alignment`` drafted for this
    column (``name``/``range``/``on_class``/``why``). Kept structured rather than only
    named in the prose rationale: a ``registered-extension`` decision is a commitment to
    author that property, and the next stage should be able to read it rather than parse
    an English sentence out of the ledger (#883).

    For more than a handful of decisions use :func:`record_dispositions`, which reads and
    writes each system's file once instead of once per decision.
    """
    (path,) = record_dispositions(
        hub_root,
        [
            DispositionInput(
                system=system,
                table=table,
                disposition=disposition,
                rationale=rationale,
                decided_by=decided_by,
                evidence=tuple(evidence),
                column=column,
                proposed_property=proposed_property,
            )
        ],
    )
    return path
