# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic Stage-0 source profiling (DD-189).

Profiles raw ``.import/`` extracts (Parquet/CSV) BEFORE any model call and
writes per-column statistics and signal tags. Measured motivation (signal-first
validation runs, 2026-08-19): with profile tags in the anchoring outline the
model reproduced the hand-confirmed grain on 9/9 golden tables; without them it
keyed **every** table on the SaaS tenant discriminator (0/9) — the exact live
DD-185 failure that previously needed a hand-maintained disposition ledger
entry. Profiling detects that class of column (``const``/``low-card``) from the
data itself, and drops always-empty columns from model context entirely
(~12% of the measured estate — pure name-bait carrying no signal).

Privacy posture: statistics only. A null ratio, a cardinality, a value-shape
class or an inclusion ratio is not PII; raw values never leave this module and
are never written to the artifact.

Basis discipline (§4.4 of the signal-first proposal): every profile records the
evidence basis it was computed from — ``import-extract(full)`` today; a later
dataplatform re-profile writes ``platform`` and diffs against this one as a
release verification gate. Sample-basis caveats therefore stay attached to the
numbers instead of being lost.

Data-maturity gate: dropping an always-empty column is only sound when the
extract is declared production-grade. The hub declares ``data_maturity`` in
``kairos.yaml`` (``production`` | ``test``); under anything but ``production``
the same tags are computed but downgrade to advisory — nothing is excluded.
Exclusions are never silent either way: the artifact carries the full excluded
list, and consumers echo counts.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)

PROFILE_SCHEMA_VERSION = 1

#: Non-null values inspected per column for value-shape classification.
SHAPE_SAMPLE = 200
#: Max distinct values retained per unique column for inclusion testing.
KEY_SET_CAP = 500_000
#: Distinct candidate values sampled for one inclusion test.
FK_SAMPLE = 1_000
#: Sampled inclusion ratio required for an ``fk?`` tag.
FK_THRESHOLD = 0.98
#: Distinct-count ceiling for a ``low-card(n)`` tag.
LOW_CARD_MAX = 50
#: Row ceiling + code-like density for the ``code-list?`` table tag.
CODE_LIST_MAX_ROWS = 500

_VERSION_COLS = {"updated_at", "modified_at", "valid_from", "valid_to",
                 "version", "row_version"}
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}|$)")
_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_KEYISH_NAME = re.compile(r"(^|_)(id|key|code|number|no)$", re.IGNORECASE)

Reporter = Callable[..., None]


def _noop_report(_msg: str, _level: str = "info") -> None:
    return None


def read_data_maturity(hub_root: Path | None) -> str:
    """Return the hub's declared ``data_maturity`` from ``kairos.yaml``.

    ``"unspecified"`` when absent — consumers must then treat exclusions as
    advisory and say so, never guess production.
    """
    if hub_root is None:
        return "unspecified"
    for candidate in (hub_root / "kairos.yaml", hub_root.parent / "kairos.yaml"):
        try:
            config = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        except OSError:
            continue
        value = str(config.get("data_maturity") or "").strip().lower()
        if value:
            return value if value in {"production", "test"} else "unspecified"
    return "unspecified"


# ---------------------------------------------------------------------------
# Per-column classification
# ---------------------------------------------------------------------------


def _shape_tags(name: str, arr: Any, distinct: int, non_null: int) -> list[str]:
    """Classify value shape from arrow type + a bounded sample.

    Values are inspected in memory only; none is returned or persisted.
    """
    import pyarrow as pa

    if pa.types.is_boolean(arr.type):
        return ["bool"]
    if pa.types.is_temporal(arr.type):
        return ["date-like"]
    tags: list[str] = []
    sample = [str(v) for v in arr.drop_null().slice(0, SHAPE_SAMPLE).to_pylist()
              if v is not None]
    if pa.types.is_floating(arr.type) or pa.types.is_decimal(arr.type):
        tags.append("measure-like")
    elif pa.types.is_integer(arr.type):
        ratio = distinct / non_null if non_null else 0.0
        tags.append("id-like" if ratio > 0.95 or _KEYISH_NAME.search(name)
                    else "measure-like")
    elif sample:
        avg_len = sum(len(s) for s in sample) / len(sample)
        if all(_UUID.match(s) for s in sample[:20]):
            tags.append("id-like")
        elif all(_ISO_DATE.match(s) for s in sample[:20]):
            tags.append("date-like")
        elif sample[0].lstrip().startswith(("{", "[")) and avg_len > 20:
            tags.append("json")
        elif avg_len <= 12 and distinct <= 100:
            tags.append("code-like")
        elif avg_len > 40:
            tags.append("free-text")
        elif _KEYISH_NAME.search(name) and non_null and distinct / non_null > 0.9:
            tags.append("id-like")
    return tags


def profile_table(path: Path) -> tuple[dict[str, Any], dict[str, set[str]]]:
    """Profile one extract file.

    Returns ``(table profile, key sets)`` where key sets hold the distinct
    values of proven-unique columns for the cross-table inclusion pass. Key
    sets stay in memory; they are never written anywhere.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    table = _read_extract(path)
    rows = table.num_rows
    columns: dict[str, dict[str, Any]] = {}
    key_sets: dict[str, set[str]] = {}

    for name in table.column_names:
        arr = table[name]
        nulls = arr.null_count
        # Empty strings count toward emptiness: a production column of "" is
        # as unused as a column of NULLs.
        if pa.types.is_string(arr.type) or pa.types.is_large_string(arr.type):
            empty_str = pc.sum(
                pc.equal(pc.utf8_trim_whitespace(arr.fill_null("")), "")
            ).as_py() or 0
            effective_nulls = max(nulls, empty_str)
        else:
            effective_nulls = nulls
        non_null = rows - effective_nulls
        # An all-null column can materialize as arrow's `null` type, which has
        # no count_distinct kernel — and its distinct count is 0 by definition.
        distinct = (
            pc.count_distinct(arr, mode="only_valid").as_py() if non_null else 0
        )

        tags: list[str] = []
        if rows == 0 or non_null == 0:
            tags.append("empty")
        elif distinct == 1:
            tags.append("const")
        else:
            if distinct == non_null:
                tags.append("unique")
            elif distinct <= LOW_CARD_MAX:
                tags.append(f"low-card({distinct})")
            tags += _shape_tags(name, arr, distinct, non_null)

        # Temporal columns are excluded from key-set candidacy on two grounds:
        # containment-matching a timestamp against another table's timestamp
        # is never a meaningful join (unlike an identifier), and a tz-aware
        # timestamp's `to_pylist()` needs a tz database Windows does not ship
        # by default (ArrowInvalid without the `tzdata` package) -- a crash
        # on real data (frachtv5 CargoWise) that a temporal value could never
        # have usefully produced a key set for anyway.
        if ("unique" in tags and non_null and distinct <= KEY_SET_CAP
                and not pa.types.is_temporal(arr.type)):
            key_sets[name] = {str(v) for v in arr.drop_null().to_pylist()}

        columns[name] = {
            "type": str(arr.type),
            "null_ratio": round(effective_nulls / rows, 4) if rows else 1.0,
            "distinct": distinct,
            "distinct_ratio": round(distinct / non_null, 4) if non_null else 0.0,
            "tags": tags,
        }

    table_tags: list[str] = []
    if rows == 0:
        table_tags.append("empty-table")
    versionish = _VERSION_COLS & {c.lower() for c in table.column_names}
    non_unique_ids = [
        c for c, meta in columns.items()
        if _KEYISH_NAME.search(c)
        and "unique" not in meta["tags"] and "empty" not in meta["tags"]
    ]
    if versionish and non_unique_ids:
        table_tags.append("versioned?")
    code_like = sum(1 for m in columns.values() if "code-like" in m["tags"])
    if rows and rows <= CODE_LIST_MAX_ROWS and code_like >= max(2, len(columns) // 3):
        table_tags.append("code-list?")

    return {"rows": rows, "table_tags": table_tags, "columns": columns}, key_sets


def _read_extract(path: Path):
    """Read one extract as an arrow table. Parquet and CSV only (v1)."""
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        import pyarrow.parquet as pq

        return pq.read_table(path)
    if suffix == ".csv":
        import pyarrow.csv as pacsv

        return pacsv.read_csv(path)
    raise ValueError(f"unsupported extract type for profiling: {path.name}")


# ---------------------------------------------------------------------------
# Cross-table inclusion pass
# ---------------------------------------------------------------------------


def add_inclusion_tags(
    profiles: dict[str, dict[str, Any]],
    key_sets: dict[tuple[str, str], set[str]],
    paths: dict[str, Path],
) -> int:
    """Tag sampled ``col ⊆ other.unique_col`` containment as ``fk?->table.col``.

    Deterministic join evidence for anchoring/relationship proposal: this is
    the tier-2 signal the name-equality matcher cannot supply.
    """
    found = 0
    for tbl, prof in profiles.items():
        for col, meta in prof["columns"].items():
            if {"empty", "const", "unique"} & set(meta["tags"]):
                continue
            if not (_KEYISH_NAME.search(col) or "id-like" in meta["tags"]):
                continue
            arr = _read_extract(paths[tbl]).column(col)
            sample = {str(v) for v in arr.drop_null().slice(0, FK_SAMPLE * 5).to_pylist()}
            sample = set(sorted(sample)[:FK_SAMPLE])
            if len(sample) < 2:
                continue
            for (other_tbl, key_col), values in sorted(key_sets.items()):
                if other_tbl == tbl:
                    continue
                hit = sum(1 for v in sample if v in values) / len(sample)
                if hit >= FK_THRESHOLD:
                    meta["tags"].append(f"fk?->{other_tbl}.{key_col}")
                    found += 1
    return found


# ---------------------------------------------------------------------------
# Run + artifact
# ---------------------------------------------------------------------------

_EXTRACT_GLOBS = ("*.parquet", "*.csv")


def run_profile_sources(
    import_dir: Path,
    system: str,
    out_dir: Path,
    *,
    data_maturity: str = "unspecified",
    report: Reporter | None = None,
) -> Path:
    """Profile every supported extract under *import_dir* for one system.

    Writes ``<system>.profile.yaml`` into *out_dir* (the system's
    ``integration/sources/<system>/`` directory) and returns the path. The
    artifact carries statistics and tags only — never a data value.
    """
    say = report or _noop_report
    files: list[Path] = []
    skipped: list[str] = []
    for entry in sorted(import_dir.iterdir()):
        if entry.is_file() and any(entry.match(g) for g in _EXTRACT_GLOBS):
            files.append(entry)
        elif entry.is_file():
            skipped.append(entry.name)
    if not files:
        raise FileNotFoundError(
            f"no profilable extracts (parquet/csv) under {import_dir}"
        )

    profiles: dict[str, dict[str, Any]] = {}
    all_key_sets: dict[tuple[str, str], set[str]] = {}
    paths: dict[str, Path] = {}
    for path in files:
        name = path.stem
        prof, key_sets = profile_table(path)
        profiles[name] = prof
        paths[name] = path
        for col, values in key_sets.items():
            all_key_sets[(name, col)] = values
        say(
            f"  📊 {name}: {prof['rows']} rows, {len(prof['columns'])} cols"
            + (f", tags={prof['table_tags']}" if prof["table_tags"] else "")
        )

    n_fk = add_inclusion_tags(profiles, all_key_sets, paths)
    n_empty = sum(1 for p in profiles.values()
                  for m in p["columns"].values() if "empty" in m["tags"])
    n_const = sum(1 for p in profiles.values()
                  for m in p["columns"].values() if "const" in m["tags"])
    say(f"  📊 inclusion pass: {n_fk} fk? tag(s); {n_empty} empty and "
        f"{n_const} const column(s) across {len(profiles)} table(s)")
    if skipped:
        say(f"  ⏭  not profilable (unsupported type): {', '.join(skipped[:8])}"
            + (" …" if len(skipped) > 8 else ""), "warning")
    if data_maturity != "production":
        say(
            "  ⚠ data_maturity is not 'production' — empty/const tags are "
            "ADVISORY; consumers must not exclude columns on this profile.",
            "warning",
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{system}.profile.yaml"
    with out.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(
            {
                "schema_version": PROFILE_SCHEMA_VERSION,
                "system": system,
                "basis": "import-extract(full)",
                "data_maturity": data_maturity,
                "not_profiled": sorted(skipped),
                "tables": profiles,
            },
            fh,
            sort_keys=True,
            allow_unicode=True,
        )
    return out


def load_profile(sources_dir: Path, system: str) -> dict[str, Any] | None:
    """Load a system's profile artifact, or ``None`` when absent/unreadable."""
    path = sources_dir / system / f"{system}.profile.yaml"
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError:
        return None
    return doc if isinstance(doc, dict) and doc.get("tables") else None


def load_fk_evidence(
    sources_dir: Path,
) -> dict[tuple[str, str], dict[str, set[tuple[str, str]]]]:
    """DD-189 ``fk?->table.col`` tags as join evidence for relationship proposal.

    Keyed ``(system_lower, table)`` → ``{column: {(target_table, target_column)}}``.
    This is the tier-2 join matcher's input: measured value containment where
    exact name equality has nothing to say (``goods.consignment_id ⊆
    consignments.consignment_id`` was known here while the name matcher
    returned a sentinel). Empty when no profiles exist — purely additive.
    """
    evidence: dict[tuple[str, str], dict[str, set[tuple[str, str]]]] = {}
    directory = Path(sources_dir)
    if not directory.is_dir():
        return evidence
    for sysdir in sorted(p for p in directory.iterdir() if p.is_dir()):
        profile = load_profile(directory, sysdir.name)
        if not profile:
            continue
        system = sysdir.name.lower()
        for table, prof in (profile.get("tables") or {}).items():
            columns: dict[str, set[tuple[str, str]]] = {}
            for col, meta in (prof.get("columns") or {}).items():
                targets = {
                    (parts[0], parts[1])
                    for tag in (meta.get("tags") or [])
                    if isinstance(tag, str) and tag.startswith("fk?->")
                    for parts in [tag[len("fk?->"):].split(".", 1)]
                    if len(parts) == 2
                }
                if targets:
                    columns[col] = targets
            if columns:
                evidence[(system, table)] = columns
    return evidence


PROFILE_LEGEND = """
Column annotations in [brackets] are DETERMINISTIC data-profile facts computed from the
import extracts — trust them over name impressions:
- unique: distinct == non-null count (proven key candidate)
- const: single value (config/tenant discriminator — NEVER a grain or key member)
- low-card(n): n distinct values; id-like/code-like/date-like/measure-like/free-text/json: value shape
- fk?->table.col: sampled values are contained in that table's unique column (join evidence)
- Table tag versioned?: rows may accumulate versions — grain uniqueness in the extract may not hold over time
- Always-empty columns are omitted where noted: they carry no signal and must not influence any decision.
"""


def annotate_outline(
    outline: list[tuple[str, str, list[str]]],
    sources_dir: Path,
    *,
    report: Reporter | None = None,
) -> tuple[list[tuple[str, str, list[str]]], bool]:
    """Annotate an anchoring outline with profile tags where profiles exist.

    Returns ``(annotated outline, any_profile_found)``. Column entries become
    ``name[tag,…]`` strings; always-empty columns are dropped **only** when the
    profile was computed under declared ``production`` maturity (the §4.3
    gate), and every drop is echoed, never silent. Tables/systems without a
    profile pass through untouched — this is additive evidence, not a new
    requirement.
    """
    say = report or _noop_report
    cache: dict[str, dict[str, Any] | None] = {}
    result: list[tuple[str, str, list[str]]] = []
    found = False
    for system, table, cols in outline:
        if system not in cache:
            cache[system] = load_profile(sources_dir, system)
        profile = cache[system]
        table_prof = (profile or {}).get("tables", {}).get(table)
        if not table_prof:
            result.append((system, table, cols))
            continue
        found = True
        exclude_empty = (profile or {}).get("data_maturity") == "production"
        annotated: list[str] = []
        omitted = 0
        col_meta = table_prof.get("columns", {})
        for col in cols:
            meta = col_meta.get(col)
            if meta is None:
                annotated.append(col)
                continue
            tags = meta.get("tags") or []
            if "empty" in tags and exclude_empty:
                omitted += 1
                continue
            annotated.append(col + (f"[{','.join(tags)}]" if tags else ""))
        if omitted:
            say(f"  📊 {system}.{table}: {omitted} always-empty column(s) "
                "omitted from the anchoring outline (production profile)")
        result.append((system, table, annotated))
    return result, found
