# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Privacy-safe preparation of source samples before artifact persistence."""

from __future__ import annotations

import copy
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDFS

from ._samples import (
    SAMPLE_PRIVACY_POLICY,
    SAMPLE_PRIVACY_VERSION,
    SamplePrivacyError,
    SamplePrivacyFinding,
    detect_sample_pii_kind,
    is_redaction_token,
    redact_sample_value,
    redact_sample_rows,
)

KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")


@dataclass
class SourcePrivacyReport:
    """Value-free result of checking or fixing source artifacts."""

    root: Path
    files_scanned: int = 0
    findings: list[tuple[Path, SamplePrivacyFinding]] = field(default_factory=list)
    changed_files: list[Path] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.findings


def sanitize_samples_document(
    document: Any,
    *,
    table: str,
    column_types: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[SamplePrivacyFinding]]:
    """Return a standard samples document with detected PII redacted."""
    if isinstance(document, dict):
        rows = document.get("rows", [])
        safe_document = copy.deepcopy(document)
    elif isinstance(document, list):
        rows = document
        safe_document = {"table": table, "schema": "", "rows": []}
    else:
        raise ValueError(f"Invalid samples document for table '{table}'")

    safe_rows, findings = redact_sample_rows(
        rows,
        table=table,
        column_types=column_types,
    )
    safe_document["rows"] = safe_rows
    safe_document["sample_privacy"] = {
        "policy": SAMPLE_PRIVACY_POLICY,
        "version": SAMPLE_PRIVACY_VERSION,
    }
    residual: list[SamplePrivacyFinding] = []
    for row in safe_rows:
        for column, value in row.items():
            if is_redaction_token(value):
                continue
            kind = detect_sample_pii_kind(str(column), value)
            if kind:
                residual.append(
                    SamplePrivacyFinding(table=table, column=str(column), kind=kind)
                )
    if residual:
        raise SamplePrivacyError(residual)
    return safe_document, findings


def find_samples_document_privacy_issues(
    document: Any,
    *,
    table: str,
) -> list[SamplePrivacyFinding]:
    """Find supported PII in a samples document without returning values."""
    rows = document.get("rows", []) if isinstance(document, dict) else document
    findings: list[SamplePrivacyFinding] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for column, value in row.items():
            if is_redaction_token(value):
                continue
            kind = detect_sample_pii_kind(str(column), value)
            if kind:
                findings.append(
                    SamplePrivacyFinding(table=table, column=str(column), kind=kind)
                )
    return findings


def _sanitize_values(
    values: list[Any] | None,
    *,
    table: str,
    column: str,
    data_type: str,
) -> tuple[list[Any], list[SamplePrivacyFinding]]:
    safe_values: list[Any] = []
    findings: list[SamplePrivacyFinding] = []
    for value in values or []:
        safe_value, finding = redact_sample_value(
            value,
            table=table,
            column=column,
            data_type=data_type,
        )
        safe_values.append(safe_value)
        if finding:
            findings.append(finding)
    return safe_values, findings


def sanitize_source_data(
    data: dict[str, Any],
) -> tuple[dict[str, Any], list[SamplePrivacyFinding]]:
    """Return a deep-copied source schema with detected PII redacted.

    This handles inline samples, sample-derived enum values, and JSON-structure
    examples. Raw input remains available in memory to enrichment callers, but the
    returned structure is safe for generated YAML and Turtle artifacts.
    """
    safe_data = copy.deepcopy(data)
    findings: list[SamplePrivacyFinding] = []

    for table in safe_data.get("tables", []):
        table_name = str(table.get("name", "unknown-table"))
        for column in table.get("columns", []):
            column_name = str(column.get("name", "unknown-column"))
            data_type = str(column.get("data_type", "unknown"))

            for sample_field in ("samples", "enum_values"):
                if sample_field not in column:
                    continue
                safe_values, field_findings = _sanitize_values(
                    column.get(sample_field),
                    table=table_name,
                    column=column_name,
                    data_type=data_type,
                )
                column[sample_field] = safe_values
                findings.extend(field_findings)

            for structure in column.get("json_structure", []) or []:
                if structure.get("sample") is None:
                    continue
                key = str(structure.get("key", "unknown-key"))
                safe_value, finding = redact_sample_value(
                    structure["sample"],
                    table=table_name,
                    column=f"{column_name}.{key}",
                    data_type=str(structure.get("type", "unknown")),
                )
                structure["sample"] = safe_value
                if finding:
                    findings.append(finding)

    safe_data["sample_privacy"] = {
        "policy": SAMPLE_PRIVACY_POLICY,
        "version": SAMPLE_PRIVACY_VERSION,
    }
    assert_source_data_private(safe_data)
    return safe_data, findings


def find_source_data_privacy_issues(
    data: dict[str, Any],
) -> list[SamplePrivacyFinding]:
    """Return supported unredacted PII findings without exposing values."""
    findings: list[SamplePrivacyFinding] = []
    for table in data.get("tables", []):
        table_name = str(table.get("name", "unknown-table"))
        for column in table.get("columns", []):
            column_name = str(column.get("name", "unknown-column"))
            for sample_field in ("samples", "enum_values"):
                for value in column.get(sample_field, []) or []:
                    if is_redaction_token(value):
                        continue
                    kind = detect_sample_pii_kind(column_name, value)
                    if kind:
                        findings.append(
                            SamplePrivacyFinding(
                                table=table_name,
                                column=column_name,
                                kind=kind,
                            )
                        )
            for structure in column.get("json_structure", []) or []:
                value = structure.get("sample")
                if value is None or is_redaction_token(value):
                    continue
                key = str(structure.get("key", "unknown-key"))
                source_column = f"{column_name}.{key}"
                kind = detect_sample_pii_kind(source_column, value)
                if kind:
                    findings.append(
                        SamplePrivacyFinding(
                            table=table_name,
                            column=source_column,
                            kind=kind,
                        )
                    )
    return findings


def assert_source_data_private(data: dict[str, Any]) -> None:
    """Block artifact generation while supported raw PII remains."""
    findings = find_source_data_privacy_issues(data)
    if findings:
        raise SamplePrivacyError(findings)


def _graph_source_context(graph: Graph, subject: URIRef) -> tuple[str, str, str]:
    column = str(
        graph.value(subject, KAIROS_BRONZE.columnName)
        or graph.value(subject, RDFS.label)
        or str(subject).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        or "unknown-column"
    )
    table_subject = graph.value(subject, KAIROS_BRONZE.sourceTable)
    if table_subject is None:
        parent = graph.value(subject, KAIROS_BRONZE.derivedFromJson)
        if parent is not None:
            table_subject = graph.value(parent, KAIROS_BRONZE.sourceTable)
    table = str(
        graph.value(table_subject, KAIROS_BRONZE.tableName)
        if table_subject is not None
        else "unknown-table"
    )
    data_type = str(graph.value(subject, KAIROS_BRONZE.dataType) or "unknown")
    return table, column, data_type


def find_vocabulary_privacy_issues(
    graph: Graph,
) -> list[SamplePrivacyFinding]:
    """Find supported raw PII in managed vocabulary sample predicates."""
    findings: list[SamplePrivacyFinding] = []
    for predicate in (KAIROS_BRONZE.sampleValues, KAIROS_BRONZE.enumValues):
        for subject, value in graph.subject_objects(predicate):
            if is_redaction_token(value):
                continue
            table, column, _ = _graph_source_context(graph, subject)
            kind = detect_sample_pii_kind(column, str(value))
            if kind:
                findings.append(
                    SamplePrivacyFinding(table=table, column=column, kind=kind)
                )
    return findings


def sanitize_vocabulary_graph(
    graph: Graph,
) -> list[SamplePrivacyFinding]:
    """Redact managed sample literals in an RDF graph in place."""
    findings: list[SamplePrivacyFinding] = []
    for predicate in (KAIROS_BRONZE.sampleValues, KAIROS_BRONZE.enumValues):
        for subject, value in list(graph.subject_objects(predicate)):
            table, column, data_type = _graph_source_context(graph, subject)
            safe_value, finding = redact_sample_value(
                str(value),
                table=table,
                column=column,
                data_type=data_type,
            )
            if finding:
                graph.remove((subject, predicate, value))
                graph.add((subject, predicate, Literal(str(safe_value))))
                findings.append(finding)

    unresolved = find_vocabulary_privacy_issues(graph)
    if unresolved:
        raise SamplePrivacyError(unresolved)
    return findings


def _table_types(table_path: Path) -> dict[str, str]:
    if not table_path.is_file():
        return {}
    data = yaml.safe_load(table_path.read_text(encoding="utf-8")) or {}
    return {
        str(column.get("name", "")): str(column.get("data_type", "unknown"))
        for column in data.get("columns", [])
    }


def _publish_candidates(candidates: dict[Path, str]) -> None:
    """Publish staged rewrites and restore every original if publication fails."""
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    published: list[Path] = []
    try:
        for path, content in candidates.items():
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.privacy-",
                delete=False,
            ) as handle:
                handle.write(content)
                staged[path] = Path(handle.name)
            shutil.copymode(path, staged[path])

        for path in candidates:
            with tempfile.NamedTemporaryFile(
                dir=path.parent,
                prefix=f".{path.name}.backup-",
                delete=False,
            ) as handle:
                backups[path] = Path(handle.name)
            shutil.copy2(path, backups[path])

        try:
            for path in candidates:
                os.replace(staged[path], path)
                published.append(path)
                staged.pop(path)
        except Exception:
            restore_failures: list[str] = []
            for path in reversed(published):
                try:
                    os.replace(backups[path], path)
                    backups.pop(path)
                except OSError as exc:
                    restore_failures.append(f"{path}: {exc}")
            if restore_failures:
                raise RuntimeError(
                    "Source privacy publication failed and rollback was incomplete: "
                    + "; ".join(restore_failures)
                )
            raise
    finally:
        for temporary in [*staged.values(), *backups.values()]:
            temporary.unlink(missing_ok=True)


def run_source_privacy(
    source_dir: Path,
    *,
    fix: bool = False,
) -> SourcePrivacyReport:
    """Check or sanitize existing source YAML and vocabulary artifacts.

    Every candidate is parsed and sanitized before any file is rewritten. Reports
    contain paths and source locations only; raw values never leave this function.
    """
    root = Path(source_dir)
    if not root.is_dir():
        raise ValueError(f"Source directory does not exist: {root}")

    report = SourcePrivacyReport(root=root)
    candidates: dict[Path, str] = {}

    for samples_path in sorted(root.rglob("*.samples.yaml")):
        report.files_scanned += 1
        document = yaml.safe_load(samples_path.read_text(encoding="utf-8"))
        table = (
            str(document.get("table"))
            if isinstance(document, dict) and document.get("table")
            else samples_path.name.removesuffix(".samples.yaml")
        )
        findings = find_samples_document_privacy_issues(document, table=table)
        report.findings.extend((samples_path, finding) for finding in findings)
        if fix and findings:
            safe_document, _ = sanitize_samples_document(
                document,
                table=table,
                column_types=_table_types(samples_path.with_name(f"{table}.yaml")),
            )
            candidates[samples_path] = yaml.safe_dump(
                safe_document,
                allow_unicode=True,
                sort_keys=False,
            )

    table_paths = {
        path
        for pattern in ("*.yaml", "*.yml")
        for path in root.rglob(pattern)
        if not path.name.startswith("_")
        and not path.name.endswith(".samples.yaml")
        and "_analysis" not in path.parts
    }
    for table_path in sorted(table_paths):
        table_data = yaml.safe_load(table_path.read_text(encoding="utf-8")) or {}
        if not (
            isinstance(table_data, dict)
            and isinstance(table_data.get("columns"), list)
            and table_data.get("name")
        ):
            continue
        report.files_scanned += 1
        wrapped = {"tables": [table_data]}
        findings = find_source_data_privacy_issues(wrapped)
        report.findings.extend((table_path, finding) for finding in findings)
        if fix and findings:
            safe_data, _ = sanitize_source_data(wrapped)
            candidates[table_path] = yaml.safe_dump(
                safe_data["tables"][0],
                allow_unicode=True,
                sort_keys=False,
            )

    for ttl_path in sorted(root.rglob("*.vocabulary.ttl")):
        report.files_scanned += 1
        graph = Graph()
        graph.parse(ttl_path, format="turtle")
        findings = find_vocabulary_privacy_issues(graph)
        report.findings.extend((ttl_path, finding) for finding in findings)
        if fix and findings:
            sanitize_vocabulary_graph(graph)
            candidates[ttl_path] = graph.serialize(format="turtle")

    if fix:
        # Validate every candidate before publishing any rewrite.
        for path, content in candidates.items():
            if path.suffix == ".ttl":
                graph = Graph()
                graph.parse(data=content, format="turtle")
                unresolved = find_vocabulary_privacy_issues(graph)
            else:
                document = yaml.safe_load(content)
                if path.name.endswith(".samples.yaml"):
                    table = (
                        str(document.get("table"))
                        if isinstance(document, dict) and document.get("table")
                        else path.name.removesuffix(".samples.yaml")
                    )
                    unresolved = find_samples_document_privacy_issues(
                        document,
                        table=table,
                    )
                else:
                    unresolved = find_source_data_privacy_issues(
                        {"tables": [document]}
                    )
            if unresolved:
                raise SamplePrivacyError(unresolved)

        _publish_candidates(candidates)
        report.changed_files.extend(candidates)

    return report
