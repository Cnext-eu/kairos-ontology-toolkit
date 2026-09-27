# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Column-coverage gate: source columns with real, populated data that no EntityBinding
references anywhere, and source tables with no binding at all (issue #353).

v4 had a real mechanism for this -- a "Claim Registry" that reconciled every source
column against a persisted coverage table (DD-077, DD-127, DD-128) so a column could
never silently vanish unaccounted for. It was deleted in the v5.0.0 clean-break rewrite
and never replaced: v5 is fully stateless (DD-133), so nothing recomputes this on demand.
This module recomputes it fresh on every run instead of persisting anything, which is the
right shape for a stateless v5 hub, not a compromise.

A column is "referenced" by a binding if it appears in ``fields:``, ``technicalFields:``,
``identity.sourceKey``/``businessKey``, ``grain.columns``, a ``relationships[].join[].local``,
a ``quality[].columns`` entry, or anywhere in ``load.incremental`` (``mergeIdentity``,
``canonicalHashInputs``, ``cdcOperation.column``, ``sourceUpdatedAt``, ``businessEffectiveAt``,
``ingestedAt``, ``totalOrder``) -- the last group is easy to miss and was originally omitted
from this module's own first draft: ``source_updated_at`` is frequently exactly one of the
audit-trail timestamp columns this same check would otherwise flag as an orphan.

An adversarial pre-implementation review found that a naive "has real sample variation"
threshold is unreliable in both directions on real client data: audit-trail
``*SystemLastEditTimeUtc`` columns often show LOW distinct/row-count ratios (batched edits
cluster timestamps), while genuine business timestamps (e.g. an ETA/ETD) often show HIGH
ratios -- so a cardinality-ratio cutoff both lets real audit noise through and suppresses
exactly the real signal this check exists to surface. Filtering audit/technical columns by
name (reusing and extending the existing, precedented `core.propose_alignment` pattern
lists, DD-077) instead of by statistical shape is the approach this module uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ._samples import redact_sample_value
from .bound_columns import EMPTY_BOUND_COLUMNS, binding_referenced_columns, load_bound_columns
from .compiler import CompileError, load_entity_binding
from .domain_coverage import load_source_affinity_by_table
from .propose_alignment import _is_operational_column
from .silver_sample_audit import SourceColumnSample, load_source_samples

#: Bumped when the machine-readable report contract changes.
#: v1 (issue #494/#489, DD-160): unbound tables carry DD-156 row evidence, cross-domain
#: column candidates are reported, and the whole report is JSON-serializable.
#: v2 (#1065): every finding carries ``system``, orphans carry ``read_by_models``, and
#: ``lineage_unconfirmed`` lists tables a ``select *`` dbtModel chain reads.
SCHEMA_VERSION = 2

TableKey = tuple[str, str]


@dataclass
class OrphanColumnFinding:
    """One source column with real, populated data that no binding references."""

    table: str
    column: str
    data_type: str
    distinct_count: int | None
    row_count: int | None
    sample_value: str
    binding_names: tuple[str, ...]
    system: str = ""
    #: dbtModel chain models that read this column's table (DD-250). A table bound only
    #: through a chain has no ``binding_names``; these say who reads it instead.
    read_by_models: tuple[str, ...] = ()


@dataclass
class LineageUnconfirmedFinding:
    """A table a dbtModel chain reads with ``select *``, whose leftover columns are unproven.

    A star read passes every column on, so a column no model names may still reach Silver.
    Reporting those columns as orphans would be wrong, and so would calling them bound
    (DD-250: a chain is evidence, not a decision). They are counted here instead.
    """

    system: str
    table: str
    models: tuple[str, ...]
    column_count: int


@dataclass
class UnboundTableFinding:
    """One source table with zero EntityBindings referencing it at all.

    Carries DD-156 profiling evidence so a consumer can prioritise by data volume. All
    three counts are honestly nullable: ``row_count is None`` means the true cardinality is
    unknown (a capped flatfile read), NOT zero. Without these the autopilot's own
    "unbound tables over 1000 rows" reporting rule was literally unevaluable (#494).
    """

    table: str
    column_count: int
    row_count: int | None = None
    rows_sampled: int | None = None
    distinct_scope: str | None = None
    system: str = ""

    def volume_label(self) -> str:
        """Human-readable row volume that never presents a window size as a table count."""
        if self.row_count is not None:
            return str(self.row_count)
        if self.rows_sampled is not None:
            return f"{self.rows_sampled}+ (sampled; true count unknown)"
        return "?"


@dataclass
class CrossDomainColumnFinding:
    """A bound table whose source data also belongs to a domain nothing binds it to (#489).

    One source relation may be bound by several EntityBindings -- nothing in the schema
    constrains ``source.relation`` to one binding, ``safety.artifact-collision`` keys on
    binding *name* and artifact path only, and each binding carries its own
    grain/identity/load. A wide operational table (the CLdN ``Qargo.orders`` has 123
    columns) routinely spans booking, party, consignment and equipment concepts, but a hub
    that authors only the first binding silently drops the rest.

    The evidence is the affinity pass's own ``secondary_domains`` -- the analysis already
    recorded that a table spans several domains, and nothing ever compared that against
    what was actually bound. Name-matching the leftover columns was considered and
    rejected: the measured candidate ladder in ``scaffold_binding`` matches **zero**
    columns on its exact-equality rung, so a name-based cross-domain scan would report
    nothing while looking authoritative.
    """

    table: str
    bound_domains: tuple[str, ...]
    candidate_domain: str
    unmapped_column_count: int
    likely_entity: str
    system: str = ""


@dataclass
class ColumnCoverageReport:
    """Structured output of the column-coverage audit."""

    generated_at: str
    sources_dir: str
    bindings_dir: str
    orphan_columns: list[OrphanColumnFinding] = field(default_factory=list)
    unbound_tables: list[UnboundTableFinding] = field(default_factory=list)
    cross_domain_columns: list[CrossDomainColumnFinding] = field(default_factory=list)
    lineage_unconfirmed: list[LineageUnconfirmedFinding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON payload (#494). ``schema_version`` is bumped on any contract change."""
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": self.generated_at,
            "sources_dir": self.sources_dir,
            "bindings_dir": self.bindings_dir,
            "orphan_columns": [
                {
                    "system": item.system,
                    "table": item.table,
                    "column": item.column,
                    "data_type": item.data_type,
                    "distinct_count": item.distinct_count,
                    "row_count": item.row_count,
                    "sample_value": item.sample_value,
                    "binding_names": list(item.binding_names),
                    "read_by_models": list(item.read_by_models),
                }
                for item in self.orphan_columns
            ],
            "unbound_tables": [
                {
                    "system": item.system,
                    "table": item.table,
                    "column_count": item.column_count,
                    "row_count": item.row_count,
                    "rows_sampled": item.rows_sampled,
                    "distinct_scope": item.distinct_scope,
                }
                for item in self.unbound_tables
            ],
            "cross_domain_columns": [
                {
                    "system": item.system,
                    "table": item.table,
                    "bound_domains": list(item.bound_domains),
                    "candidate_domain": item.candidate_domain,
                    "unmapped_column_count": item.unmapped_column_count,
                    "likely_entity": item.likely_entity,
                }
                for item in self.cross_domain_columns
            ],
            "lineage_unconfirmed": [
                {
                    "system": item.system,
                    "table": item.table,
                    "models": list(item.models),
                    "column_count": item.column_count,
                }
                for item in self.lineage_unconfirmed
            ],
            "notes": list(self.notes),
        }


#: The one definition of "a binding references this column" lives in ``bound_columns``
#: (DD-250), where the DD-169 gate reads it too; kept under its old name here.
_binding_referenced_columns = binding_referenced_columns


def _table_from_relation(relation: str) -> str:
    """Return the bronze-vocabulary table name a binding's ``source.relation`` refers to.

    ``relation`` is ``"<system>.<table>"`` (e.g. ``"tms.Shipment.sample"``); the
    bronze vocabulary's own ``kairos-bronze:tableName``/``SourceColumnSample.table_name``
    keeps the ``.sample``-style suffix intact, so only the leading system segment is
    stripped -- split once, not on every dot.
    """
    _, _, rest = relation.partition(".")
    return rest or relation


def _key_from_relation(relation: str) -> TableKey:
    """``(system, table)`` for a binding's ``source.relation``, split once like
    :func:`_table_from_relation`."""
    system, _, rest = relation.partition(".")
    return (system.strip(), rest.strip()) if rest else ("", relation.strip())


def _sample_key(column: SourceColumnSample) -> TableKey:
    """The hub-wide key of a sample's table: its source directory, else its label."""
    return (column.system_dir or column.system, column.table_name)


def run_column_coverage_audit(
    *,
    sources_dir: Path,
    bindings_dir: Path,
    analysis_dir: Path | None = None,
    hub_root: Path | None = None,
) -> ColumnCoverageReport:
    """Build a column-coverage report across every EntityBinding in *bindings_dir*.

    Advisory and best-effort, matching ``audit-silver-samples``: a hub with no bindings
    or source vocabulary yields an empty report rather than raising.

    Tables are keyed by ``(system, table)`` throughout (#1065), so two systems' tables of
    the same name are two tables. A ``source.relation`` binding names its columns
    outright. A ``source.dbtModel`` binding is read through
    :func:`bound_columns.load_bound_columns` (DD-250): a table its chain reads is bound,
    a column the chain names is referenced, and a table read with ``select *`` goes to
    ``lineage_unconfirmed`` instead of having its other columns reported as orphans.
    *hub_root* resolves the chain's model SQL; it defaults to two levels above
    *bindings_dir* (``<hub>/integration/bindings``).

    ``analysis_dir`` points at ``integration/sources/_analysis/`` and enables the
    cross-domain scan (#489). Omitting it keeps the orphan-column and unbound-table
    findings unchanged.
    """
    report = ColumnCoverageReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        sources_dir=str(sources_dir),
        bindings_dir=str(bindings_dir),
    )

    if not bindings_dir.is_dir():
        report.notes.append(f"'{bindings_dir}' does not exist -- nothing to audit.")
        return report

    referenced_by_table: dict[TableKey, set[str]] = {}
    binding_names_by_table: dict[TableKey, set[str]] = {}
    domains_by_table: dict[TableKey, set[str]] = {}
    affinity_by_table = (
        load_source_affinity_by_table(analysis_dir) if analysis_dir is not None else {}
    )

    for path in sorted(bindings_dir.glob("*.binding.yaml")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            report.notes.append(f"binding '{path.name}' could not be read: {exc}")
            continue
        try:
            binding = load_entity_binding(text, path=str(path))
        except CompileError as exc:
            messages = "; ".join(d.message for d in exc.diagnostics)
            report.notes.append(f"binding '{path.name}' could not be parsed: {messages}")
            continue
        if not binding.source.relation:
            continue  # a dbtModel binding: its chain is read below
        key = _key_from_relation(binding.source.relation)
        referenced_by_table.setdefault(key, set()).update(_binding_referenced_columns(binding))
        binding_names_by_table.setdefault(key, set()).add(binding.name)
        domains_by_table.setdefault(key, set()).add(binding.domain)

    root = hub_root if hub_root is not None else bindings_dir.parent.parent
    try:
        chains = load_bound_columns(bindings_dir, root)
    except Exception as exc:  # noqa: BLE001 - advisory; the chain is compile's to report
        report.notes.append(f"dbtModel chains could not be read: {exc}")
        chains = EMPTY_BOUND_COLUMNS
    chain_readers: dict[TableKey, set[str]] = {}
    for key, columns_read in chains.read_by.items():
        referenced_by_table.setdefault(key, set()).update(columns_read)
        for models in columns_read.values():
            chain_readers.setdefault(key, set()).update(models)
    for key, models in chains.unconfirmed.items():
        chain_readers.setdefault(key, set()).update(models)
    bound_tables = set(binding_names_by_table) | set(chain_readers)

    source_columns = load_source_samples(sources_dir)
    columns_by_table: dict[TableKey, list[SourceColumnSample]] = {}
    for column in source_columns.values():
        columns_by_table.setdefault(_sample_key(column), []).append(column)

    if not columns_by_table:
        report.notes.append(f"'{sources_dir}' has no source vocabulary -- nothing to audit.")
        return report

    chain_only_unchecked = 0
    for key, columns in sorted(columns_by_table.items()):
        system, table = key
        if key not in bound_tables:
            evidence = columns[0] if columns else None
            report.unbound_tables.append(
                UnboundTableFinding(
                    table=table,
                    column_count=len(columns),
                    row_count=evidence.row_count if evidence else None,
                    rows_sampled=evidence.rows_sampled if evidence else None,
                    distinct_scope=evidence.distinct_scope if evidence else None,
                    system=system,
                )
            )
            continue

        referenced = referenced_by_table.get(key, set())
        binding_names = tuple(sorted(binding_names_by_table.get(key, ())))
        readers = tuple(sorted(chain_readers.get(key, ())))
        star_readers = tuple(sorted(chains.unconfirmed.get(key, ())))
        unmapped: list[SourceColumnSample] = []
        unconfirmed_count = 0
        for column in sorted(columns, key=lambda c: c.name):
            if column.name.lower() in referenced:
                continue
            if _is_operational_column(column.name):
                continue
            unmapped.append(column)
            if star_readers and not binding_names:
                # A star read may pass the column on: unproven, not orphaned (DD-250).
                unconfirmed_count += 1
                continue
            if column.distinct_count is None or column.distinct_count <= 1:
                continue
            # Always redact here, whatever the import policy was (issue #692). This value is
            # printed to stdout and included in `--format json`, so it lands in terminals,
            # agent transcripts and CI logs -- destinations no hub controls. Redacting
            # per-value rather than blanking keeps the evidence this finding exists to give:
            # the #302 exemptions mean money, dates and identifiers survive intact, and only
            # a genuine detection becomes an opaque token.
            raw_sample = column.samples[0] if column.samples else ""
            sample_value = ""
            if raw_sample:
                sample_value, _ = redact_sample_value(
                    raw_sample,
                    table=table,
                    column=column.name,
                    data_type=column.data_type,
                )
            report.orphan_columns.append(
                OrphanColumnFinding(
                    table=table,
                    column=column.name,
                    data_type=column.data_type,
                    distinct_count=column.distinct_count,
                    row_count=column.row_count,
                    sample_value=sample_value,
                    binding_names=binding_names,
                    system=system,
                    read_by_models=readers,
                )
            )
        if unconfirmed_count:
            report.lineage_unconfirmed.append(
                LineageUnconfirmedFinding(
                    system=system, table=table, models=star_readers,
                    column_count=unconfirmed_count,
                )
            )
        affinity = affinity_by_table.get(key)
        # A table with nothing left unmapped has no second entity hiding in it, whatever
        # the affinity pass thought -- reporting it would be pure noise.
        if affinity and unmapped:
            if not binding_names:
                # Bound only through a chain: which domain binds it is not known here, so
                # every secondary domain would look unbound. Say so rather than guess.
                chain_only_unchecked += 1
                continue
            bound_domains = domains_by_table.get(key, set())
            for candidate in affinity.get("secondary", ()):
                if candidate and candidate not in bound_domains:
                    report.cross_domain_columns.append(
                        CrossDomainColumnFinding(
                            table=table,
                            bound_domains=tuple(sorted(bound_domains)),
                            candidate_domain=candidate,
                            unmapped_column_count=len(unmapped),
                            likely_entity=str(affinity.get("likely_entity", "")),
                            system=system,
                        )
                    )
    if chain_only_unchecked:
        report.notes.append(
            f"{chain_only_unchecked} table(s) bound only through a dbtModel chain were not "
            "checked for cross-domain candidates: the chain does not say which domain binds "
            "each table it reads."
        )

    return report
