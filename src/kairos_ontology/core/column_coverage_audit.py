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
threshold is unreliable in both directions on real CargoWise data: audit-trail
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

from .compiler import CompileError, load_entity_binding
from .compiler.adapter import _expression_columns
from .compiler.bindings import EntityBinding
from .propose_alignment import _is_operational_column
from .silver_sample_audit import SourceColumnSample, load_source_samples


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


@dataclass
class UnboundTableFinding:
    """One source table with zero EntityBindings referencing it at all."""

    table: str
    column_count: int


@dataclass
class ColumnCoverageReport:
    """Structured output of the column-coverage audit."""

    generated_at: str
    sources_dir: str
    bindings_dir: str
    orphan_columns: list[OrphanColumnFinding] = field(default_factory=list)
    unbound_tables: list[UnboundTableFinding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _binding_referenced_columns(binding: EntityBinding) -> set[str]:
    """Every source column *binding* references anywhere, lower-cased.

    Lower-cased because the table's column list (from the bronze vocabulary TTL) and a
    binding's authored expressions are two independently-authored surfaces with no shared
    casing contract -- comparing case-insensitively avoids manufacturing a false orphan
    from pure casing drift between them.
    """
    refs: set[str] = set()
    for f in binding.fields:
        refs.update(_expression_columns(f.expression))
    for tf in binding.technical_fields:
        refs.update(_expression_columns(tf.expression))
    refs.update(binding.identity.source_key)
    refs.update(binding.identity.business_key)
    refs.update(binding.grain.columns)
    for rel in binding.relationships:
        for join in rel.on:
            refs.add(join.local)
    for q in binding.quality:
        refs.update(q.columns)
    incremental = binding.load.incremental
    if incremental is not None:
        refs.update(incremental.merge_identity)
        refs.update(incremental.canonical_hash_inputs)
        refs.add(incremental.cdc_operation.column)
        for col in (
            incremental.source_updated_at,
            incremental.business_effective_at,
            incremental.ingested_at,
        ):
            if col:
                refs.add(col)
        refs.update(incremental.total_order)
    return {c.lower() for c in refs if c}


def _table_from_relation(relation: str) -> str:
    """Return the bronze-vocabulary table name a binding's ``source.relation`` refers to.

    ``relation`` is ``"<system>.<table>"`` (e.g. ``"cargowise.JobShipment.sample"``); the
    bronze vocabulary's own ``kairos-bronze:tableName``/``SourceColumnSample.table_name``
    keeps the ``.sample``-style suffix intact, so only the leading system segment is
    stripped -- split once, not on every dot.
    """
    _, _, rest = relation.partition(".")
    return rest or relation


def run_column_coverage_audit(
    *, sources_dir: Path, bindings_dir: Path
) -> ColumnCoverageReport:
    """Build a column-coverage report across every EntityBinding in *bindings_dir*.

    Advisory and best-effort, matching ``audit-silver-samples``: a hub with no bindings
    or source vocabulary yields an empty report rather than raising.
    """
    report = ColumnCoverageReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        sources_dir=str(sources_dir),
        bindings_dir=str(bindings_dir),
    )

    if not bindings_dir.is_dir():
        report.notes.append(f"'{bindings_dir}' does not exist -- nothing to audit.")
        return report

    referenced_by_table: dict[str, set[str]] = {}
    binding_names_by_table: dict[str, set[str]] = {}
    bound_tables: set[str] = set()

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

        table = _table_from_relation(binding.source.relation)
        bound_tables.add(table)
        referenced_by_table.setdefault(table, set()).update(_binding_referenced_columns(binding))
        binding_names_by_table.setdefault(table, set()).add(binding.name)

    source_columns = load_source_samples(sources_dir)
    columns_by_table: dict[str, list[SourceColumnSample]] = {}
    for column in source_columns.values():
        columns_by_table.setdefault(column.table_name, []).append(column)

    if not columns_by_table:
        report.notes.append(f"'{sources_dir}' has no source vocabulary -- nothing to audit.")
        return report

    for table, columns in sorted(columns_by_table.items()):
        if table not in bound_tables:
            report.unbound_tables.append(
                UnboundTableFinding(table=table, column_count=len(columns))
            )
            continue

        referenced = referenced_by_table.get(table, set())
        binding_names = tuple(sorted(binding_names_by_table.get(table, ())))
        for column in sorted(columns, key=lambda c: c.name):
            if column.name.lower() in referenced:
                continue
            if _is_operational_column(column.name):
                continue
            if column.distinct_count is None or column.distinct_count <= 1:
                continue
            sample_value = column.samples[0] if column.samples else ""
            report.orphan_columns.append(
                OrphanColumnFinding(
                    table=table,
                    column=column.name,
                    data_type=column.data_type,
                    distinct_count=column.distinct_count,
                    row_count=column.row_count,
                    sample_value=sample_value,
                    binding_names=binding_names,
                )
            )

    return report
