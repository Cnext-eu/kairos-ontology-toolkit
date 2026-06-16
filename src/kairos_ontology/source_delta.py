# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Change management for new/changed source systems (Slice 6, DD-EL-8).

Deterministic, AI-free classification of *candidate deltas* introduced by a new
or changed source system, plus a silver/gold contract version-bump suggestion.

Core invariant (methodology §13):

> New evidence may expand silver, but must not silently mutate existing silver.

A source system's bronze vocabulary is compared against the approved Claim
Registry + SKOS mappings (+ optional affinity hints + optional baseline
vocabulary for change detection).  Each table / column is classified into a
methodology §13.2 delta type, every delta carries an *impact* (mapping-only /
additive / breaking), and the worst impact drives a SemVer bump suggestion
(§13.5) with backward-compatibility tactics (§13.6).

This module never edits the registry or projections — it only *reports*.  The
contract version it reads/suggests lives in the registry ``contract:`` block
(:class:`~kairos_ontology.claim_registry.ContractMeta`).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from rdflib import RDF, Graph, Namespace
from rdflib.namespace import SKOS

from .claim_registry import ContractMeta, load_registry

logger = logging.getLogger(__name__)

KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")

#: SKOS predicates that establish a source→domain mapping (shared with
#: ``source_coverage`` / DD-061).
_MATCH_PREDICATES = (
    SKOS.exactMatch,
    SKOS.closeMatch,
    SKOS.narrowMatch,
    SKOS.broadMatch,
    SKOS.relatedMatch,
)

# --- Delta taxonomy (methodology §13.2) ------------------------------------
MAPS_TO_EXISTING_CLASS = "maps-to-existing-class"
NEW_CLAIM_CANDIDATE = "new-claim-candidate"
NEW_COLUMN_TO_PROPERTY = "new-column-to-property"
PASSTHROUGH_CANDIDATE = "passthrough-candidate"
NEW_REFERENCE_LIST = "new-reference-list"
NEW_RELATIONSHIP = "new-relationship"
SEMANTIC_CONFLICT = "semantic-conflict"
CHANGED_TYPE = "changed-type"
CHANGED_KEY = "changed-key"
CHANGED_GRAIN = "changed-grain"
REMOVED_COLUMN = "removed-column"

# --- Impact levels (methodology §13.3) -------------------------------------
MAPPING_ONLY = "mapping-only"
ADDITIVE = "additive"
BREAKING = "breaking"

#: Default impact for each delta type (``changed-type`` is downgraded to
#: ``additive`` when the change is a backward-compatible widening).
DELTA_IMPACT: dict[str, str] = {
    MAPS_TO_EXISTING_CLASS: MAPPING_ONLY,
    NEW_COLUMN_TO_PROPERTY: MAPPING_ONLY,
    NEW_CLAIM_CANDIDATE: ADDITIVE,
    PASSTHROUGH_CANDIDATE: ADDITIVE,
    NEW_REFERENCE_LIST: ADDITIVE,
    NEW_RELATIONSHIP: ADDITIVE,
    CHANGED_TYPE: BREAKING,
    SEMANTIC_CONFLICT: BREAKING,
    CHANGED_KEY: BREAKING,
    CHANGED_GRAIN: BREAKING,
    REMOVED_COLUMN: BREAKING,
}

#: Impact → SemVer bump level (methodology §13.5).
IMPACT_TO_BUMP: dict[str, str] = {
    MAPPING_ONLY: "patch",
    ADDITIVE: "minor",
    BREAKING: "major",
}

_BUMP_RANK = {"none": 0, "patch": 1, "minor": 2, "major": 3}

#: Identifier-shaped column names that suggest a foreign key / relationship.
_FK_SUFFIXES = ("id", "code", "key", "ref", "fk", "no", "nr")

#: Table-name tokens that suggest a reference / code list.
_REFERENCE_TOKENS = ("type", "code", "status", "category", "kind", "ref", "lookup", "list")

#: Backward-compatibility tactics per breaking delta type (methodology §13.6).
_TACTICS: dict[str, tuple[str, ...]] = {
    CHANGED_TYPE: (
        "keep a backward-compatible cast or compatibility view",
        "add a new column instead of changing the existing one",
        "require downstream sign-off",
    ),
    CHANGED_KEY: (
        "introduce a compatibility view preserving the old natural key",
        "version the silver table",
        "require downstream sign-off",
    ),
    CHANGED_GRAIN: (
        "introduce a compatibility view preserving the old grain",
        "version the silver table",
        "require downstream sign-off",
    ),
    REMOVED_COLUMN: (
        "preserve the old column with deprecation metadata",
        "keep an alias for the renamed business term",
        "deprecate the claim before removal",
        "require downstream sign-off",
    ),
    SEMANTIC_CONFLICT: (
        "model the new meaning separately (do not silently merge)",
        "mark the affected claim deprecated before change",
        "require downstream sign-off",
    ),
}


# ---------------------------------------------------------------------------
# Source model
# ---------------------------------------------------------------------------


@dataclass
class SourceColumn:
    """A bronze source column with the attributes needed for delta detection."""

    name: str
    data_type: str | None = None
    nullable: bool | None = None
    uri: str | None = None


@dataclass
class SourceTable:
    """A bronze source table (its columns, primary key, and bronze URIs)."""

    system: str
    name: str
    uri: str | None = None
    primary_key: list[str] = field(default_factory=list)
    columns: list[SourceColumn] = field(default_factory=list)

    def column(self, name: str) -> SourceColumn | None:
        for col in self.columns:
            if col.name == name:
                return col
        return None


@dataclass
class Delta:
    """A single candidate change introduced by the source system."""

    system: str
    table: str
    delta_type: str
    impact: str
    column: str | None = None
    target: str | None = None
    detail: str = ""
    tactics: tuple[str, ...] = ()

    @property
    def bump(self) -> str:
        return IMPACT_TO_BUMP[self.impact]


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _local(uri: str) -> str:
    """Return the local name of a URI (last ``#`` or ``/`` segment)."""
    return str(uri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def load_source_tables(sources_dir: Path, system: str | None = None) -> dict[str, SourceTable]:
    """Load bronze tables (with columns, types, nullability, PK) from vocabularies.

    Returns a mapping of *table name* → :class:`SourceTable`.  ``system`` is the
    vocabulary file stem (matching how affinity reports name systems); when
    given, only that system's vocabularies are loaded.
    """
    tables: dict[str, SourceTable] = {}
    if not sources_dir or not Path(sources_dir).is_dir():
        return tables

    for vocab_file in sorted(Path(sources_dir).rglob("*.vocabulary.ttl")):
        stem = vocab_file.stem.replace(".vocabulary", "")
        if system is not None and stem != system:
            continue
        g = Graph()
        try:
            g.parse(vocab_file, format="turtle")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not parse vocabulary %s: %s", vocab_file.name, exc)
            continue

        for tbl_uri in g.subjects(RDF.type, KAIROS_BRONZE.SourceTable):
            tbl_name = str(
                g.value(tbl_uri, KAIROS_BRONZE.tableName)
                or _local(str(tbl_uri))
            )
            pk_raw = g.value(tbl_uri, KAIROS_BRONZE.primaryKeyColumns)
            primary_key = _split_columns(str(pk_raw)) if pk_raw is not None else []

            col_uris = set(g.subjects(KAIROS_BRONZE.belongsToTable, tbl_uri))
            col_uris.update(g.subjects(KAIROS_BRONZE.sourceTable, tbl_uri))
            columns: list[SourceColumn] = []
            for col_uri in col_uris:
                col_name = g.value(col_uri, KAIROS_BRONZE.columnName)
                if col_name is None:
                    continue
                dtype = g.value(col_uri, KAIROS_BRONZE.dataType)
                nullable = g.value(col_uri, KAIROS_BRONZE.nullable)
                columns.append(
                    SourceColumn(
                        name=str(col_name),
                        data_type=str(dtype) if dtype is not None else None,
                        nullable=(bool(nullable.toPython()) if nullable is not None else None),
                        uri=str(col_uri),
                    )
                )
            columns.sort(key=lambda c: c.name)
            tables[tbl_name] = SourceTable(
                system=stem,
                name=tbl_name,
                uri=str(tbl_uri),
                primary_key=primary_key,
                columns=columns,
            )

    return tables


def _split_columns(raw: str) -> list[str]:
    """Split a primary-key declaration (``"A, B"`` or ``"A"``) into names."""
    return [p.strip() for p in re.split(r"[,;]", raw) if p.strip()]


def load_mapping_targets(mappings_dir: Path) -> dict[str, set[str]]:
    """Map each mapped bronze subject URI → the set of its target local names."""
    targets: dict[str, set[str]] = {}
    if not mappings_dir or not Path(mappings_dir).is_dir():
        return targets

    g = Graph()
    for ttl in sorted(Path(mappings_dir).rglob("*.ttl")):
        try:
            g.parse(ttl, format="turtle")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not parse mapping file %s: %s", ttl.name, exc)

    for predicate in _MATCH_PREDICATES:
        for subj, obj in g.subject_objects(predicate):
            targets.setdefault(str(subj), set()).add(_local(str(obj)))
    return targets


def load_approved_targets(
    claims_dir: Path, domains: list[str] | None = None
) -> tuple[set[str], set[str], dict[str, ContractMeta]]:
    """Return ``(approved_classes, approved_props, contracts_by_domain)``.

    Approved *class* local names come from ``class``/``reference_data``/``measure``
    claims with ``status == approved``; approved *property* local names come from
    ``property``/``relationship`` claims.  ``contracts_by_domain`` maps each
    domain to its registry ``contract:`` block.
    """
    approved_classes: set[str] = set()
    approved_props: set[str] = set()
    contracts: dict[str, ContractMeta] = {}
    if not claims_dir or not Path(claims_dir).is_dir():
        return approved_classes, approved_props, contracts

    for claims_file in sorted(Path(claims_dir).glob("*-claims.yaml")):
        domain = claims_file.stem.replace("-claims", "")
        if domains and domain not in domains:
            continue
        try:
            registry = load_registry(claims_file)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not load claims file %s: %s", claims_file.name, exc)
            continue
        contracts[registry.domain or domain] = registry.contract
        for claim in registry.claims:
            if claim.status != "approved":
                continue
            if claim.type in ("class", "reference_data", "measure") and claim.class_uri:
                approved_classes.add(_local(claim.class_uri))
            if claim.type in ("property", "relationship") and claim.property_uri:
                approved_props.add(_local(claim.property_uri))
    return approved_classes, approved_props, contracts


def load_affinity_tables(analysis_dir: Path | None) -> set[str]:
    """Return the set of table names assigned to *any* domain by affinity."""
    if not analysis_dir:
        return set()
    try:
        from .alignment_coverage import load_affinity_domain_tables
    except Exception:  # pragma: no cover - defensive
        return set()
    domain_tables = load_affinity_domain_tables(Path(analysis_dir))
    return {table for pairs in domain_tables.values() for (_system, table) in pairs}


# ---------------------------------------------------------------------------
# Type-widening detection (methodology §13.5: "changed type major unless a
# backward-compatible cast remains")
# ---------------------------------------------------------------------------

_INT_RANK = {"tinyint": 1, "smallint": 2, "int": 3, "integer": 3, "bigint": 4}
_VARCHAR_RE = re.compile(r"^(n?(?:var)?char)\s*\(\s*(\d+|max)\s*\)$", re.IGNORECASE)


def _is_widening(old: str | None, new: str | None) -> bool:
    """True when ``old`` → ``new`` is a backward-compatible widening cast."""
    if not old or not new:
        return False
    o, n = old.strip().lower(), new.strip().lower()
    if o == n:
        return True
    if o in _INT_RANK and n in _INT_RANK:
        return _INT_RANK[n] >= _INT_RANK[o]
    mo, mn = _VARCHAR_RE.match(o), _VARCHAR_RE.match(n)
    if mo and mn and mo.group(1) == mn.group(1):
        if mn.group(2) == "max":
            return True
        if mo.group(2) == "max":
            return False
        return int(mn.group(2)) >= int(mo.group(2))
    return False


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _is_fk_shaped(column: str, primary_key: list[str]) -> bool:
    name = column.lower().rstrip("_")
    if column in primary_key:
        return False
    return any(name.endswith(suffix) for suffix in _FK_SUFFIXES)


def _is_reference_table(table: SourceTable) -> bool:
    name = table.name.lower()
    if any(tok in name for tok in _REFERENCE_TOKENS):
        return True
    # A narrow code+label table (single-column PK + at most one other column).
    return len(table.primary_key) == 1 and len(table.columns) <= 2


def _classify_columns(
    table: SourceTable,
    column_names: list[str],
    mapped: set[str],
    approved_props: set[str],
) -> list[Delta]:
    """Classify a set of (new) columns of ``table`` into column-level deltas."""
    deltas: list[Delta] = []
    for col_name in column_names:
        col = table.column(col_name)
        if col is None:
            continue
        if col.uri and col.uri in mapped:
            deltas.append(
                Delta(
                    system=table.system,
                    table=table.name,
                    column=col_name,
                    delta_type=NEW_COLUMN_TO_PROPERTY,
                    impact=DELTA_IMPACT[NEW_COLUMN_TO_PROPERTY],
                    detail="column maps to an existing property; mapping expands, no schema change",
                )
            )
        elif _is_fk_shaped(col_name, table.primary_key):
            deltas.append(
                Delta(
                    system=table.system,
                    table=table.name,
                    column=col_name,
                    delta_type=NEW_RELATIONSHIP,
                    impact=DELTA_IMPACT[NEW_RELATIONSHIP],
                    detail="identifier-shaped column; candidate foreign key / relationship",
                )
            )
        else:
            deltas.append(
                Delta(
                    system=table.system,
                    table=table.name,
                    column=col_name,
                    delta_type=PASSTHROUGH_CANDIDATE,
                    impact=DELTA_IMPACT[PASSTHROUGH_CANDIDATE],
                    detail="column has no property; passthrough / skip / specialize decision",
                )
            )
    return deltas


def _classify_changed_table(
    table: SourceTable,
    baseline: SourceTable,
    mapped: set[str],
    approved_props: set[str],
) -> list[Delta]:
    """Diff a table against its baseline → changed/removed deltas + new columns."""
    deltas: list[Delta] = []

    if set(table.primary_key) != set(baseline.primary_key):
        deltas.append(
            Delta(
                system=table.system,
                table=table.name,
                delta_type=CHANGED_KEY,
                impact=BREAKING,
                detail=(
                    f"primary key changed: {baseline.primary_key or '∅'} → "
                    f"{table.primary_key or '∅'}"
                ),
                tactics=_TACTICS[CHANGED_KEY],
            )
        )
        if len(table.primary_key) != len(baseline.primary_key):
            deltas.append(
                Delta(
                    system=table.system,
                    table=table.name,
                    delta_type=CHANGED_GRAIN,
                    impact=BREAKING,
                    detail="primary-key cardinality changed; table grain may differ",
                    tactics=_TACTICS[CHANGED_GRAIN],
                )
            )

    new_names = {c.name for c in table.columns}
    base_names = {c.name for c in baseline.columns}

    for removed in sorted(base_names - new_names):
        base_col = baseline.column(removed)
        was_mapped = bool(base_col and base_col.uri and base_col.uri in mapped)
        if was_mapped:
            deltas.append(
                Delta(
                    system=table.system,
                    table=table.name,
                    column=removed,
                    delta_type=SEMANTIC_CONFLICT,
                    impact=BREAKING,
                    detail="a mapped column was removed/renamed; the modeled concept lost its source",
                    tactics=_TACTICS[SEMANTIC_CONFLICT],
                )
            )
        else:
            deltas.append(
                Delta(
                    system=table.system,
                    table=table.name,
                    column=removed,
                    delta_type=REMOVED_COLUMN,
                    impact=BREAKING,
                    detail="existing column removed",
                    tactics=_TACTICS[REMOVED_COLUMN],
                )
            )

    for name in sorted(new_names & base_names):
        new_col = table.column(name)
        base_col = baseline.column(name)
        if not new_col or not base_col:
            continue
        if (new_col.data_type or "") != (base_col.data_type or ""):
            if _is_widening(base_col.data_type, new_col.data_type):
                deltas.append(
                    Delta(
                        system=table.system,
                        table=table.name,
                        column=name,
                        delta_type=CHANGED_TYPE,
                        impact=ADDITIVE,
                        detail=(
                            f"type widened: {base_col.data_type} → {new_col.data_type} "
                            "(backward-compatible)"
                        ),
                    )
                )
            else:
                deltas.append(
                    Delta(
                        system=table.system,
                        table=table.name,
                        column=name,
                        delta_type=CHANGED_TYPE,
                        impact=BREAKING,
                        detail=f"type changed: {base_col.data_type} → {new_col.data_type}",
                        tactics=_TACTICS[CHANGED_TYPE],
                    )
                )

    deltas.extend(
        _classify_columns(table, sorted(new_names - base_names), mapped, approved_props)
    )
    return deltas


def classify_deltas(
    tables: dict[str, SourceTable],
    mapping_targets: dict[str, set[str]],
    approved_classes: set[str],
    approved_props: set[str],
    affinity_tables: set[str],
    baseline: dict[str, SourceTable] | None = None,
) -> list[Delta]:
    """Classify every table/column of a source system into candidate deltas."""
    baseline = baseline or {}
    mapped = set(mapping_targets.keys())
    deltas: list[Delta] = []

    for name in sorted(tables):
        table = tables[name]
        prior = baseline.get(name)
        if prior is not None:
            deltas.extend(_classify_changed_table(table, prior, mapped, approved_props))
            continue

        table_targets = mapping_targets.get(table.uri or "", set())
        if table_targets:
            if table_targets & approved_classes:
                deltas.append(
                    Delta(
                        system=table.system,
                        table=table.name,
                        delta_type=MAPS_TO_EXISTING_CLASS,
                        impact=DELTA_IMPACT[MAPS_TO_EXISTING_CLASS],
                        target=", ".join(sorted(table_targets & approved_classes)),
                        detail="source coverage expands; maps to an approved class",
                    )
                )
                deltas.extend(
                    _classify_columns(
                        table,
                        [c.name for c in table.columns],
                        mapped,
                        approved_props,
                    )
                )
            else:
                deltas.append(
                    Delta(
                        system=table.system,
                        table=table.name,
                        delta_type=NEW_CLAIM_CANDIDATE,
                        impact=DELTA_IMPACT[NEW_CLAIM_CANDIDATE],
                        target=", ".join(sorted(table_targets)),
                        detail="maps to an unclaimed class; candidate new claim / silver table",
                    )
                )
        elif _is_reference_table(table):
            deltas.append(
                Delta(
                    system=table.system,
                    table=table.name,
                    delta_type=NEW_REFERENCE_LIST,
                    impact=DELTA_IMPACT[NEW_REFERENCE_LIST],
                    detail="reference/code-list shape; candidate MDM/reference-data claim",
                )
            )
        else:
            deltas.append(
                Delta(
                    system=table.system,
                    table=table.name,
                    delta_type=NEW_CLAIM_CANDIDATE,
                    impact=DELTA_IMPACT[NEW_CLAIM_CANDIDATE],
                    detail=(
                        "affinity-assigned, unmapped table; candidate new claim / silver table"
                        if table.name in affinity_tables
                        else "unmapped table; candidate new claim / silver table"
                    ),
                )
            )

    return deltas


# ---------------------------------------------------------------------------
# Version policy (methodology §13.5)
# ---------------------------------------------------------------------------


def suggest_version_bump(deltas: list[Delta]) -> str:
    """Return ``major`` / ``minor`` / ``patch`` / ``none`` for a set of deltas."""
    best = "none"
    for delta in deltas:
        level = delta.bump
        if _BUMP_RANK[level] > _BUMP_RANK[best]:
            best = level
    return best


def bump_semver(current: str | None, level: str) -> str | None:
    """Apply a SemVer ``level`` bump to ``current`` (e.g. ``1.2.3`` + minor)."""
    if level == "none":
        return current
    base = current or "0.0.0"
    parts = base.split(".")
    while len(parts) < 3:
        parts.append("0")
    try:
        major, minor, patch = (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return current
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    if level == "patch":
        return f"{major}.{minor}.{patch + 1}"
    return current


# ---------------------------------------------------------------------------
# Impact report
# ---------------------------------------------------------------------------


@dataclass
class ImpactReport:
    """The result of a source-delta analysis (methodology §13.4)."""

    system: str
    deltas: list[Delta]
    silver_version: str | None = None
    gold_version: str | None = None

    def by_impact(self, impact: str) -> list[Delta]:
        return [d for d in self.deltas if d.impact == impact]

    def by_type(self, *types: str) -> list[Delta]:
        wanted = set(types)
        return [d for d in self.deltas if d.delta_type in wanted]

    @property
    def has_breaking(self) -> bool:
        return any(d.impact == BREAKING for d in self.deltas)

    @property
    def suggested_bump(self) -> str:
        return suggest_version_bump(self.deltas)

    @property
    def suggested_silver_version(self) -> str | None:
        return bump_semver(self.silver_version, self.suggested_bump)

    def render_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"# Source delta impact report — `{self.system}`")
        lines.append("")
        lines.append(
            "> New evidence may expand silver, but must not silently mutate existing "
            "silver."
        )
        lines.append("")

        counts: dict[str, int] = {}
        for d in self.deltas:
            counts[d.impact] = counts.get(d.impact, 0) + 1
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Total candidate deltas: **{len(self.deltas)}**")
        lines.append(f"- Breaking: **{counts.get(BREAKING, 0)}**")
        lines.append(f"- Additive: **{counts.get(ADDITIVE, 0)}**")
        lines.append(f"- Mapping-only: **{counts.get(MAPPING_ONLY, 0)}**")
        lines.append(f"- Suggested contract version bump: **{self.suggested_bump}**")
        lines.append("")

        lines.append("## Candidate deltas")
        lines.append("")
        if self.deltas:
            lines.append("| Table | Column | Delta type | Impact | Detail |")
            lines.append("|---|---|---|---|---|")
            for d in self.deltas:
                lines.append(
                    f"| `{d.table}` | {('`' + d.column + '`') if d.column else '—'} "
                    f"| {d.delta_type} | {d.impact} | {d.detail} |"
                )
        else:
            lines.append("_No candidate deltas detected._")
        lines.append("")

        silver_tables = self.by_type(NEW_CLAIM_CANDIDATE, NEW_REFERENCE_LIST)
        lines.append("## Expected silver table additions")
        lines.append("")
        if silver_tables:
            for d in silver_tables:
                lines.append(f"- `{d.table}` ({d.delta_type})")
        else:
            lines.append("_None._")
        lines.append("")

        silver_columns = self.by_type(PASSTHROUGH_CANDIDATE, NEW_RELATIONSHIP)
        lines.append("## Expected silver column / FK additions")
        lines.append("")
        if silver_columns:
            for d in silver_columns:
                lines.append(f"- `{d.table}`.`{d.column}` ({d.delta_type})")
        else:
            lines.append("_None._")
        lines.append("")

        breaking = self.by_impact(BREAKING)
        lines.append("## Breaking changes")
        lines.append("")
        if breaking:
            for d in breaking:
                loc = f"`{d.table}`" + (f".`{d.column}`" if d.column else "")
                lines.append(f"- {loc} — **{d.delta_type}**: {d.detail}")
                for tactic in d.tactics:
                    lines.append(f"  - tactic: {tactic}")
        else:
            lines.append("_None — all deltas are additive or mapping-only._")
        lines.append("")

        approvals = [d for d in self.deltas if d.impact in (ADDITIVE, BREAKING)]
        lines.append("## Required approvals")
        lines.append("")
        if approvals:
            lines.append(
                "The following deltas change the silver/gold contract and require "
                "claim/mapping review + approval before projection:"
            )
            for d in approvals:
                loc = f"`{d.table}`" + (f".`{d.column}`" if d.column else "")
                lines.append(f"- {loc} — {d.delta_type} ({d.impact})")
        else:
            lines.append("_None — mapping-only changes do not alter the contract._")
        lines.append("")

        lines.append("## Suggested contract version")
        lines.append("")
        cur = self.silver_version or "unset"
        lines.append(
            f"- Silver: `{cur}` → **`{self.suggested_silver_version or 'unset'}`** "
            f"({self.suggested_bump})"
        )
        if self.gold_version is not None:
            lines.append(f"- Gold (current): `{self.gold_version}`")
        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_source_delta(
    system: str,
    sources_dir: Path,
    mappings_dir: Path,
    claims_dir: Path,
    analysis_dir: Path | None = None,
    baseline: Path | None = None,
    domains: list[str] | None = None,
) -> ImpactReport:
    """Build an :class:`ImpactReport` for ``system`` (deterministic, AI-free)."""
    tables = load_source_tables(Path(sources_dir), system=system)
    mapping_targets = load_mapping_targets(Path(mappings_dir))
    approved_classes, approved_props, contracts = load_approved_targets(
        Path(claims_dir), domains=domains
    )
    affinity_tables = load_affinity_tables(analysis_dir)

    baseline_tables: dict[str, SourceTable] = {}
    if baseline is not None:
        baseline_tables = _load_baseline(Path(baseline), system)

    deltas = classify_deltas(
        tables,
        mapping_targets,
        approved_classes,
        approved_props,
        affinity_tables,
        baseline=baseline_tables,
    )

    silver_version, gold_version = _resolve_contract(contracts, domains)
    return ImpactReport(
        system=system,
        deltas=deltas,
        silver_version=silver_version,
        gold_version=gold_version,
    )


def _load_baseline(baseline: Path, system: str) -> dict[str, SourceTable]:
    """Load baseline tables from a vocabulary file or a directory of them."""
    if baseline.is_dir():
        return load_source_tables(baseline, system=system)
    if baseline.is_file():
        return load_source_tables(baseline.parent, system=baseline.stem.replace(".vocabulary", ""))
    return {}


def _resolve_contract(
    contracts: dict[str, ContractMeta], domains: list[str] | None
) -> tuple[str | None, str | None]:
    """Pick the contract versions to report (highest silver across in-scope domains)."""
    scoped = [
        meta
        for dom, meta in contracts.items()
        if (not domains or dom in domains) and not meta.is_empty()
    ]
    silver = _max_semver([m.silver_version for m in scoped if m.silver_version])
    gold = _max_semver([m.gold_version for m in scoped if m.gold_version])
    return silver, gold


def _max_semver(versions: list[str]) -> str | None:
    """Return the highest dotted-numeric version (or the last one if unparsable)."""
    if not versions:
        return None

    def key(v: str) -> tuple[int, ...]:
        try:
            return tuple(int(p) for p in v.split("."))
        except ValueError:
            return (0,)

    return max(versions, key=key)
