# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Offline advisory audit for silver/dbt mappings using source sample values."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from rdflib import Graph, Namespace, RDF, RDFS

from .compiler import CompileError, adapt_binding, load_entity_binding, resolve_scope
from .compiler.dbt_lineage import resolve_dbt_model_contributing_sources
from .compiler.kernel import _binding_dbt_paths, _binding_domain, _binding_source_ref
from .projections.dbt.mapping_bind import mapping_context
from .projections.dbt.mapping_specs import ColumnMappingFact, SourceMappings
from .projections.medallion_dbt_projector import _parse_skos_mappings
from .projections.uri_utils import camel_to_snake, extract_local_name

KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"
SEVERITIES = (SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO)


@dataclass
class SourceColumnSample:
    """Source vocabulary column metadata plus captured sample values."""

    uri: str
    name: str
    table_uri: str
    table_name: str
    system: str
    data_type: str
    samples: list[str] = field(default_factory=list)
    distinct_count: int | None = None
    nullable: bool | None = None
    row_count: int | None = None


@dataclass
class AuditFinding:
    """One advisory audit finding."""

    severity: str
    code: str
    message: str
    source: str | None = None
    table: str | None = None
    column: str | None = None
    target: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class SilverSampleAuditReport:
    """Structured output of the offline sample audit."""

    generated_at: str
    sources_dir: str
    mappings_dir: str
    dbt_output_dir: str
    mapped_columns: int
    sampled_mapped_columns: int
    findings: list[AuditFinding] = field(default_factory=list)
    bindings_dir: str = ""

    @property
    def counts(self) -> dict[str, int]:
        return {sev: sum(1 for f in self.findings if f.severity == sev) for sev in SEVERITIES}

    @property
    def sample_coverage_ratio(self) -> float | None:
        """Return the mapped-column sample coverage ratio, or ``None`` if nothing was mapped.

        ``0 of 0`` is arithmetically ``1.0`` but operationally meaningless: a command that
        checked no columns must not report the same "100% coverage" a command that checked
        columns and found every one sampled would report (issue #348).
        """
        if self.mapped_columns == 0:
            return None
        return round(self.sampled_mapped_columns / self.mapped_columns, 4)


def _split_samples(value: Any) -> list[str]:
    if value is None:
        return []
    return [part.strip() for part in str(value).split(" | ") if part.strip()]


def load_source_samples(sources_dir: Path) -> dict[str, SourceColumnSample]:
    """Load source-column samples keyed by bronze column URI."""
    if not sources_dir or not sources_dir.is_dir():
        return {}

    graph = Graph()
    for ttl in sorted(sources_dir.rglob("*.ttl")):
        graph.parse(ttl, format="turtle")

    table_names: dict[str, str] = {}
    table_systems: dict[str, str] = {}
    table_row_counts: dict[str, int] = {}
    for tbl_uri in graph.subjects(RDF.type, KAIROS_BRONZE.SourceTable):
        tbl_key = str(tbl_uri)
        table_names[tbl_key] = str(
            graph.value(tbl_uri, KAIROS_BRONZE.tableName)
            or graph.value(tbl_uri, RDFS.label)
            or extract_local_name(tbl_key)
        )
        system_uri = graph.value(tbl_uri, KAIROS_BRONZE.sourceSystem) or graph.value(
            tbl_uri, KAIROS_BRONZE.belongsToSystem
        )
        if system_uri:
            table_systems[tbl_key] = str(
                graph.value(system_uri, RDFS.label) or extract_local_name(str(system_uri))
            )
        row_count_lit = graph.value(tbl_uri, KAIROS_BRONZE.rowCount)
        if row_count_lit is not None:
            try:
                table_row_counts[tbl_key] = int(row_count_lit)
            except (TypeError, ValueError):
                pass

    columns: dict[str, SourceColumnSample] = {}
    for col_uri in graph.subjects(RDF.type, KAIROS_BRONZE.SourceColumn):
        table_uri = graph.value(col_uri, KAIROS_BRONZE.sourceTable) or graph.value(
            col_uri, KAIROS_BRONZE.belongsToTable
        )
        if table_uri is None:
            continue
        col_key = str(col_uri)
        table_key = str(table_uri)
        samples = _split_samples(graph.value(col_uri, KAIROS_BRONZE.sampleValues))
        distinct_count_lit = graph.value(col_uri, KAIROS_BRONZE.distinctCount)
        distinct_count = None
        if distinct_count_lit is not None:
            try:
                distinct_count = int(distinct_count_lit)
            except (TypeError, ValueError):
                distinct_count = None
        nullable_lit = graph.value(col_uri, KAIROS_BRONZE.nullable)
        nullable = bool(nullable_lit) if nullable_lit is not None else None
        columns[col_key] = SourceColumnSample(
            uri=col_key,
            name=str(graph.value(col_uri, KAIROS_BRONZE.columnName) or extract_local_name(col_key)),
            table_uri=table_key,
            table_name=table_names.get(table_key, extract_local_name(table_key)),
            system=table_systems.get(table_key, ""),
            data_type=str(graph.value(col_uri, KAIROS_BRONZE.dataType) or "unknown"),
            samples=samples,
            distinct_count=distinct_count,
            nullable=nullable,
            row_count=table_row_counts.get(table_key),
        )
    return columns


def _all_dbt_sql(dbt_output_dir: Path) -> dict[str, str]:
    if not dbt_output_dir or not dbt_output_dir.is_dir():
        return {}
    return {
        str(path.relative_to(dbt_output_dir)): path.read_text(encoding="utf-8")
        for path in sorted(dbt_output_dir.rglob("*.sql"))
    }


def _prefixed_iri(uri: str) -> str:
    """Derive the dbt projector's fallback compact IRI form for a URI."""
    local = extract_local_name(uri)
    if "#" in uri:
        namespace = uri.rsplit("#", 1)[0]
    elif "/" in uri:
        namespace = uri.rsplit("/", 1)[0]
    else:
        return local
    prefix = namespace.rsplit("/", 1)[-1] if "/" in namespace else namespace
    return f"{prefix}:{local}"


def _target_sql_tokens(target_uri: str, mapping_ns: dict[str, str] | None = None) -> set[str]:
    """Return accepted SQL lineage/alias tokens for a mapped target URI."""
    if not target_uri:
        return set()
    tokens = {
        camel_to_snake(extract_local_name(target_uri)),
        target_uri,
        _prefixed_iri(target_uri),
    }
    for prefix, namespace in (mapping_ns or {}).items():
        if target_uri.startswith(namespace):
            local = target_uri[len(namespace) :]
            if local:
                tokens.add(f"{prefix}:{local}")
    return {token for token in tokens if token}


def _is_identifier_token(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token))


def _sql_contains_token(sql: str, token: str) -> bool:
    if not token:
        return False
    if _is_identifier_token(token):
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])"
        return re.search(pattern, sql, flags=re.IGNORECASE) is not None
    return token.lower() in sql.lower()


def _sql_contains_any_token(sql_artifacts: dict[str, str], tokens: set[str]) -> bool:
    return any(
        _sql_contains_token(sql, token) for sql in sql_artifacts.values() for token in tokens
    )


def _samples_parse_as(sql_type: str, samples: list[str]) -> tuple[int, int]:
    type_text = sql_type.lower()
    total = len(samples)
    if not samples:
        return 0, 0
    ok = 0
    for sample in samples:
        text = str(sample).strip()
        if "int" in type_text or "decimal" in type_text or "numeric" in type_text:
            try:
                float(text.replace(",", "."))
                ok += 1
            except ValueError:
                pass
        elif "date" in type_text or "time" in type_text:
            if re.match(r"^\d{4}-\d{2}-\d{2}", text) or re.match(
                r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", text
            ):
                ok += 1
        elif "bool" in type_text or "bit" in type_text:
            if text.lower() in {"0", "1", "true", "false", "yes", "no", "y", "n"}:
                ok += 1
        else:
            ok += 1
    return ok, total


def _sample_shape(value: str) -> str:
    text = str(value).strip()
    if not text:
        return "blank"
    if re.match(r"^-?\d+([,.]\d+)?$", text):
        return "numeric"
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return "date"
    if text.lower() in {"0", "1", "true", "false", "yes", "no", "y", "n"}:
        return "boolean"
    if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", text):
        return "email"
    if re.match(r"^[A-Z0-9_-]{2,20}$", text, re.IGNORECASE):
        return "code"
    return "text"


def _dominant_shape(samples: list[str]) -> str:
    counts: dict[str, int] = {}
    for sample in samples:
        shape = _sample_shape(sample)
        counts[shape] = counts.get(shape, 0) + 1
    return max(counts.items(), key=lambda item: item[1])[0] if counts else "unknown"


def _to_dict(report: SilverSampleAuditReport) -> dict[str, Any]:
    return {
        "generated_at": report.generated_at,
        "sources_dir": report.sources_dir,
        "mappings_dir": report.mappings_dir,
        "bindings_dir": report.bindings_dir,
        "dbt_output_dir": report.dbt_output_dir,
        "summary": {
            "mapped_columns": report.mapped_columns,
            "sampled_mapped_columns": report.sampled_mapped_columns,
            "sample_coverage_ratio": report.sample_coverage_ratio,
            "findings": report.counts,
        },
        "findings": [
            {
                "severity": f.severity,
                "code": f.code,
                "message": f.message,
                **({"source": f.source} if f.source else {}),
                **({"table": f.table} if f.table else {}),
                **({"column": f.column} if f.column else {}),
                **({"target": f.target} if f.target else {}),
                **({"evidence": f.evidence} if f.evidence else {}),
            }
            for f in report.findings
        ],
    }


def _coverage_text(ratio: float | None) -> str:
    return f"{ratio:.0%}" if ratio is not None else "N/A (0 mapped columns)"


def render_markdown(report: SilverSampleAuditReport) -> str:
    """Render a human-readable markdown audit report."""
    lines = [
        "# Silver sample audit",
        "",
        f"Generated at: `{report.generated_at}`",
        "",
        "## Summary",
        "",
        f"- Mapped columns: {report.mapped_columns}",
        f"- Mapped columns with samples: {report.sampled_mapped_columns}",
        f"- Sample coverage: {_coverage_text(report.sample_coverage_ratio)}",
        f"- Errors: {report.counts[SEVERITY_ERROR]}",
        f"- Warnings: {report.counts[SEVERITY_WARNING]}",
        f"- Info: {report.counts[SEVERITY_INFO]}",
        "",
        "## Findings",
        "",
    ]
    if not report.findings:
        lines.append("No findings.")
    for finding in report.findings:
        scope = " / ".join(
            part for part in [finding.source, finding.table, finding.column, finding.target] if part
        )
        suffix = f" — {scope}" if scope else ""
        lines.append(f"- **{finding.severity.upper()} {finding.code}**{suffix}: {finding.message}")
    lines.append("")
    return "\n".join(lines)


def _resolve_source_column(
    key: str,
    source_columns: dict[str, SourceColumnSample],
    by_table_and_name: dict[tuple[str, str], SourceColumnSample],
) -> SourceColumnSample | None:
    """Resolve one mapping's source-column key against the loaded samples.

    v4 SKOS mappings key by the real bronze ``kairos-bronze:SourceColumn`` RDF subject URI,
    which is a direct hit against ``source_columns``. v5 EntityBindings resolve through the
    compiler's ``ResolvedRelation.column_uri()`` (``core/compiler/adapter.py``), which
    synthesizes ``f"{table_uri}/{column_name}"`` rather than reproducing the real bronze
    subject URI -- the compiler has no reason to know it, since it only needs a stable
    per-relation symbol. Fall back to splitting that synthesized form and joining on the real
    ``(table_uri, column_name)`` pair the sample loader already carries, instead of
    re-deriving bronze URI conventions.
    """
    column = source_columns.get(key)
    if column is not None:
        return column
    table_uri, sep, name = key.rpartition("/")
    if not sep:
        return None
    return by_table_and_name.get((table_uri, name))


def _discover_binding_domains(bindings_dir: Path) -> tuple[str, ...]:
    """Return the distinct ``metadata.domain`` values declared under ``bindings_dir``."""
    domains: set[str] = set()
    for path in sorted(bindings_dir.glob("*.binding.yaml")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        domain = _binding_domain(text)
        if domain:
            domains.add(domain)
    return tuple(sorted(domains))


def _diagnostics_message(exc: CompileError) -> str:
    return "; ".join(diagnostic.message for diagnostic in exc.diagnostics)


def _binding_matches_system(
    text: str, source_system: str, *, hub_root: Path | None = None
) -> bool:
    """True when *text*'s declared source belongs to *source_system*.

    A ``source.relation`` binding matches on the relation's first dot-segment (e.g.
    ``"cargowise"`` in ``"cargowise.GlbStaff.sample"``) -- always present on a resolvable
    binding, unlike a matching bronze ``SourceColumn``/sample entry, which issue #298
    documents may not exist for every declared column.

    A ``source.dbtModel`` binding has no direct relation to sniff. Previously this always
    returned ``False`` for it under every ``source_system`` -- a dbt-model binding whose
    contracted model is itself fed by real source systems (via ``source()``/``ref()``) was
    unconditionally excluded, not merely misattributed (issue #400). When *hub_root* is
    given, it matches when *source_system* is one of the model's transitively resolved
    contributing sources, traced from the model's own declared ``sqlPath``.
    """
    relation = _binding_source_ref(text)
    if relation:
        system = relation.split(".", 1)[0]
        return system.lower() == source_system.lower()
    if hub_root is None:
        return False
    sql_path, _contract_path = _binding_dbt_paths(text)
    if not sql_path:
        return False
    sources, _fully_traceable = resolve_dbt_model_contributing_sources(hub_root, sql_path)
    return source_system.lower() in {system.lower() for system in sources}


def resolve_v5_column_facts(
    hub_root: Path, bindings_dir: Path, *, source_system: str | None = None
) -> tuple[list[ColumnMappingFact], list[AuditFinding]]:
    """Resolve every v5 EntityBinding's column mappings via the compiler's own resolution.

    Reuses the compiler's own binding resolution (``resolve_scope`` + ``adapt_binding``)
    rather than re-deriving source-relation, property, or expression resolution; the only
    bespoke code here is domain enumeration, a small YAML peek mirroring
    ``core.compiler.kernel._binding_domain`` (issue #348).

    ``source_system``, if given, restricts resolution to bindings whose ``source.relation``
    belongs to that system (see `_binding_matches_system`) -- filtered before
    ``adapt_binding`` runs, so an out-of-scope binding costs nothing beyond the read.

    Shared by ``load_binding_mappings`` (silver-sample audit) and
    ``core.field_mapping_report`` (field-mapping report) -- both need the identical
    resolve_scope/adapt_binding walk over every domain's bindings; only what each does with
    the resulting facts differs.
    """
    findings: list[AuditFinding] = []
    if not bindings_dir.is_dir() or not any(bindings_dir.glob("*.binding.yaml")):
        return [], findings

    columns: list[ColumnMappingFact] = []
    for domain in _discover_binding_domains(bindings_dir):
        try:
            scope, context = resolve_scope(hub_root, domain)
        except CompileError as exc:
            findings.append(
                AuditFinding(
                    severity=SEVERITY_INFO,
                    code="binding_domain_unresolved",
                    message=(
                        f"v5 domain '{domain}' could not be resolved for audit: "
                        f"{_diagnostics_message(exc)}"
                    ),
                    source=domain,
                )
            )
            continue
        for path_str in scope.binding_paths:
            path = Path(path_str)
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                findings.append(
                    AuditFinding(
                        severity=SEVERITY_INFO,
                        code="binding_unreadable",
                        message=f"binding '{path.name}' could not be read for audit: {exc}",
                        source=domain,
                    )
                )
                continue
            if source_system is not None and not _binding_matches_system(
                text, source_system, hub_root=hub_root
            ):
                continue
            try:
                binding = load_entity_binding(text, path=str(path))
            except CompileError as exc:
                findings.append(
                    AuditFinding(
                        severity=SEVERITY_INFO,
                        code="binding_unreadable",
                        message=(
                            f"binding '{path.name}' could not be parsed for audit: "
                            f"{_diagnostics_message(exc)}"
                        ),
                        source=domain,
                    )
                )
                continue
            if binding.domain != domain:
                # Mirrors the kernel's own selection guard: an undomained/foreign binding
                # surfaced by resolve_scope for this domain is audited under its own domain
                # pass instead, so it is not double-counted here.
                continue
            try:
                bound = adapt_binding(binding, context)
            except CompileError as exc:
                findings.append(
                    AuditFinding(
                        severity=SEVERITY_INFO,
                        code="binding_unresolved",
                        message=(
                            f"binding '{binding.name}' could not be resolved for audit: "
                            f"{_diagnostics_message(exc)}"
                        ),
                        source=domain,
                        target=binding.name,
                    )
                )
                continue
            columns.extend(bound.mappings.columns)

    return columns, findings


def load_binding_mappings(
    hub_root: Path, bindings_dir: Path
) -> tuple[dict[str, Any], dict[str, str], list[AuditFinding]]:
    """Resolve v5 EntityBindings to the same ``column_maps`` facade v4 SKOS mappings use."""
    empty: dict[str, Any] = {"table_maps": {}, "column_maps": {}}
    if not bindings_dir.is_dir() or not any(bindings_dir.glob("*.binding.yaml")):
        return empty, {}, []

    columns, findings = resolve_v5_column_facts(hub_root, bindings_dir)
    mappings, namespaces = mapping_context(SourceMappings(tables=(), columns=tuple(columns)))
    return mappings, namespaces, findings


def _no_mapping_surface_finding(mappings_dir: Path, bindings_dir: Path | None) -> AuditFinding:
    """Build the finding that replaces a false 100%-coverage result (issue #348)."""
    parts = [
        (
            f"'{mappings_dir}' exists but declares no SKOS column mappings (v4)"
            if mappings_dir.is_dir()
            else f"'{mappings_dir}' does not exist (v4)"
        )
    ]
    if bindings_dir is None:
        parts.append("no v5 bindings directory was given")
    elif bindings_dir.is_dir():
        parts.append(f"'{bindings_dir}' exists but resolved no field mappings (v5)")
    else:
        parts.append(f"'{bindings_dir}' does not exist (v5)")
    return AuditFinding(
        severity=SEVERITY_WARNING,
        code="no_mapping_surface_found",
        message=(
            "No mapped columns were found on any authoring surface, so nothing was audited: "
            + "; ".join(parts)
        ),
    )


def run_silver_sample_audit(
    *,
    sources_dir: Path,
    mappings_dir: Path,
    dbt_output_dir: Path,
    output_dir: Path | None = None,
    bindings_dir: Path | None = None,
    hub_root: Path | None = None,
) -> SilverSampleAuditReport:
    """Run an offline advisory audit over generated dbt silver artifacts.

    Reads mapped columns from both authoring surfaces a hub may use: the v4 SKOS
    ``model/mappings/`` directory and, if ``bindings_dir`` is given, the v5
    ``integration/bindings/*.binding.yaml`` EntityBindings (issue #348).
    """
    source_columns = load_source_samples(sources_dir)
    by_table_and_name: dict[tuple[str, str], SourceColumnSample] = {
        (column.table_uri, column.name): column for column in source_columns.values()
    }
    sql_artifacts = _all_dbt_sql(dbt_output_dir)

    v4_mappings, mapping_ns = _parse_skos_mappings(mappings_dir)
    v5_findings: list[AuditFinding] = []
    v5_mappings: dict[str, Any] = {"table_maps": {}, "column_maps": {}}
    v5_ns: dict[str, str] = {}
    if bindings_dir is not None:
        v5_mappings, v5_ns, v5_findings = load_binding_mappings(
            hub_root or bindings_dir.parent.parent, bindings_dir
        )
    mapping_ns = {**mapping_ns, **v5_ns}

    column_maps: dict[str, list[dict]] = {}
    for surface_mappings in (v4_mappings, v5_mappings):
        for key, entries in surface_mappings.get("column_maps", {}).items():
            column_maps.setdefault(key, []).extend(entries)

    findings: list[AuditFinding] = list(v5_findings)
    grouped_shapes: dict[str, list[tuple[SourceColumnSample, str]]] = {}
    mapped_columns = 0
    sampled_mapped_columns = 0
    seen_mapping_triples: set[tuple[str, str, str]] = set()
    duplicate_mappings = 0

    for col_uri, col_maps in column_maps.items():
        column = _resolve_source_column(col_uri, source_columns, by_table_and_name)
        for col_map in col_maps:
            target = col_map.get("target_uri", "")
            if column is not None:
                # The same physical source column can legitimately be declared under both
                # authoring surfaces during a v4-to-v5 migration; count it once per distinct
                # target rather than inflating mapped_columns/sample_coverage_ratio.
                triple = (column.table_uri, column.name, target)
                if triple in seen_mapping_triples:
                    duplicate_mappings += 1
                    continue
                seen_mapping_triples.add(triple)
            mapped_columns += 1
            if column is None:
                findings.append(
                    AuditFinding(
                        severity=SEVERITY_ERROR,
                        code="missing_source_column",
                        message="Mapping references a source column that is not present in source vocabularies.",
                        target=target,
                        evidence={"source_column_uri": col_uri},
                    )
                )
                continue

            if column.samples:
                sampled_mapped_columns += 1
                grouped_shapes.setdefault(target, []).append(
                    (column, _dominant_shape(column.samples))
                )
            else:
                findings.append(
                    AuditFinding(
                        severity=SEVERITY_WARNING,
                        code="missing_mapped_samples",
                        message="Mapped column has no sample values; semantic and expression checks are limited.",
                        source=column.system,
                        table=column.table_name,
                        column=column.name,
                        target=target,
                    )
                )

            for referenced_uri in col_map.get("referenced_column_uris") or ():
                referenced = _resolve_source_column(
                    referenced_uri, source_columns, by_table_and_name
                )
                if referenced is None or referenced.table_uri != column.table_uri:
                    findings.append(
                        AuditFinding(
                            severity=SEVERITY_ERROR,
                            code="invalid_expression_source_column",
                            message=(
                                f"Expression references source column IRI {referenced_uri!r} "
                                "that is not on the mapped table."
                            ),
                            source=column.system,
                            table=column.table_name,
                            column=column.name,
                            target=target,
                            evidence={"mapping_resource_uri": col_map.get("mapping_resource_uri")},
                        )
                    )

            target_tokens = _target_sql_tokens(target, mapping_ns)
            if sql_artifacts and not _sql_contains_any_token(sql_artifacts, target_tokens):
                findings.append(
                    AuditFinding(
                        severity=SEVERITY_WARNING,
                        code="target_alias_not_found_in_sql",
                        message=(
                            "Expected mapped target alias or lineage token was not found "
                            "in generated dbt SQL."
                        ),
                        source=column.system,
                        table=column.table_name,
                        column=column.name,
                        target=target,
                        evidence={"expected_tokens": sorted(target_tokens)},
                    )
                )

    for target, entries in grouped_shapes.items():
        shapes = {shape for _, shape in entries}
        systems = {col.system or col.table_name for col, _ in entries}
        if len(entries) > 1 and len(shapes) > 1:
            findings.append(
                AuditFinding(
                    severity=SEVERITY_WARNING,
                    code="cross_source_sample_shape_mismatch",
                    message="Multiple sources mapped to the same target property have different sample shapes.",
                    target=target,
                    evidence={
                        "shapes": sorted(shapes),
                        "sources": sorted(systems),
                    },
                )
            )

    if duplicate_mappings:
        findings.append(
            AuditFinding(
                severity=SEVERITY_INFO,
                code="duplicate_mapping_across_surfaces",
                message=(
                    f"{duplicate_mappings} column mapping(s) targeting the same property were "
                    "declared on both the v4 model/mappings/ and v5 integration/bindings/ "
                    "authoring surfaces for the same physical source column; counted once."
                ),
            )
        )

    if mapped_columns == 0:
        findings.append(_no_mapping_surface_finding(mappings_dir, bindings_dir))

    report = SilverSampleAuditReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        sources_dir=str(sources_dir),
        mappings_dir=str(mappings_dir),
        bindings_dir=str(bindings_dir) if bindings_dir is not None else "",
        dbt_output_dir=str(dbt_output_dir),
        mapped_columns=mapped_columns,
        sampled_mapped_columns=sampled_mapped_columns,
        findings=findings,
    )
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "silver-sample-audit.yaml").write_text(
            yaml.safe_dump(_to_dict(report), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        (output_dir / "silver-sample-audit.md").write_text(
            render_markdown(report),
            encoding="utf-8",
        )
    return report


def report_to_dict(report: SilverSampleAuditReport) -> dict[str, Any]:
    """Public wrapper for serialising an audit report."""
    return _to_dict(report)
