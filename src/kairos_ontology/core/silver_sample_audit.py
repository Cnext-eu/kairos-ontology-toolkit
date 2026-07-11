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

    @property
    def counts(self) -> dict[str, int]:
        return {sev: sum(1 for f in self.findings if f.severity == sev) for sev in SEVERITIES}

    @property
    def sample_coverage_ratio(self) -> float:
        if self.mapped_columns == 0:
            return 1.0
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
        columns[col_key] = SourceColumnSample(
            uri=col_key,
            name=str(
                graph.value(col_uri, KAIROS_BRONZE.columnName) or extract_local_name(col_key)
            ),
            table_uri=table_key,
            table_name=table_names.get(table_key, extract_local_name(table_key)),
            system=table_systems.get(table_key, ""),
            data_type=str(graph.value(col_uri, KAIROS_BRONZE.dataType) or "unknown"),
            samples=samples,
        )
    return columns


def _source_column_tokens(transform: str | None, source_columns: list[str] | None) -> set[str]:
    tokens = set(source_columns or [])
    if transform:
        tokens.update(re.findall(r"source\.([A-Za-z0-9_]+)", transform))
    return tokens


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
            local = target_uri[len(namespace):]
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
        _sql_contains_token(sql, token)
        for sql in sql_artifacts.values()
        for token in tokens
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
            if re.match(r"^\d{4}-\d{2}-\d{2}", text) or re.match(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", text):
                ok += 1
        elif "bool" in type_text or "bit" in type_text:
            if text.lower() in {"0", "1", "true", "false", "yes", "no", "y", "n"}:
                ok += 1
        else:
            ok += 1
    return ok, total


def _cast_target(transform: str | None) -> str | None:
    if not transform:
        return None
    match = re.search(r"\bCAST\s*\(.+?\s+AS\s+([A-Za-z0-9_(),]+)", transform, re.IGNORECASE)
    return match.group(1) if match else None


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
        f"- Sample coverage: {report.sample_coverage_ratio:.0%}",
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


def run_silver_sample_audit(
    *,
    sources_dir: Path,
    mappings_dir: Path,
    dbt_output_dir: Path,
    output_dir: Path | None = None,
) -> SilverSampleAuditReport:
    """Run an offline advisory audit over generated dbt silver artifacts."""
    source_columns = load_source_samples(sources_dir)
    mappings, mapping_ns = _parse_skos_mappings(mappings_dir)
    sql_artifacts = _all_dbt_sql(dbt_output_dir)

    findings: list[AuditFinding] = []
    grouped_shapes: dict[str, list[tuple[SourceColumnSample, str]]] = {}
    mapped_columns = 0
    sampled_mapped_columns = 0

    for col_uri, col_maps in mappings.get("column_maps", {}).items():
        column = source_columns.get(col_uri)
        for col_map in col_maps:
            mapped_columns += 1
            target = col_map.get("target_uri", "")
            if column is None:
                findings.append(AuditFinding(
                    severity=SEVERITY_ERROR,
                    code="missing_source_column",
                    message="Mapping references a source column that is not present in source vocabularies.",
                    target=target,
                    evidence={"source_column_uri": col_uri},
                ))
                continue

            if column.samples:
                sampled_mapped_columns += 1
                grouped_shapes.setdefault(target, []).append((column, _dominant_shape(column.samples)))
            else:
                findings.append(AuditFinding(
                    severity=SEVERITY_WARNING,
                    code="missing_mapped_samples",
                    message="Mapped column has no sample values; semantic and transform checks are limited.",
                    source=column.system,
                    table=column.table_name,
                    column=column.name,
                    target=target,
                ))

            table_col_names = {
                c.name for c in source_columns.values() if c.table_uri == column.table_uri
            }
            for token in _source_column_tokens(col_map.get("transform"), col_map.get("source_columns")):
                if token not in table_col_names:
                    findings.append(AuditFinding(
                        severity=SEVERITY_ERROR,
                        code="missing_transform_source_column",
                        message=f"Transform references source column '{token}' that is not on the mapped table.",
                        source=column.system,
                        table=column.table_name,
                        column=column.name,
                        target=target,
                        evidence={"transform": col_map.get("transform")},
                    ))

            cast_type = _cast_target(col_map.get("transform"))
            if cast_type and column.samples:
                ok, total = _samples_parse_as(cast_type, column.samples)
                if ok < total:
                    findings.append(AuditFinding(
                        severity=SEVERITY_WARNING,
                        code="cast_sample_incompatibility",
                        message=f"{total - ok}/{total} sample value(s) may not cast cleanly to {cast_type}.",
                        source=column.system,
                        table=column.table_name,
                        column=column.name,
                        target=target,
                        evidence={"samples_checked": total, "cast_type": cast_type},
                    ))

            target_tokens = _target_sql_tokens(target, mapping_ns)
            if sql_artifacts and not _sql_contains_any_token(sql_artifacts, target_tokens):
                findings.append(AuditFinding(
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
                ))

    for target, entries in grouped_shapes.items():
        shapes = {shape for _, shape in entries}
        systems = {col.system or col.table_name for col, _ in entries}
        if len(entries) > 1 and len(shapes) > 1:
            findings.append(AuditFinding(
                severity=SEVERITY_WARNING,
                code="cross_source_sample_shape_mismatch",
                message="Multiple sources mapped to the same target property have different sample shapes.",
                target=target,
                evidence={
                    "shapes": sorted(shapes),
                    "sources": sorted(systems),
                },
            ))

    report = SilverSampleAuditReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        sources_dir=str(sources_dir),
        mappings_dir=str(mappings_dir),
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
