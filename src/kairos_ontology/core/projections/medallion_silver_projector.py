# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Thin DD-110 renderer for shared Silver logical and physical plans."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

import yaml

from .dbt.silver_contract import (
    canonical_data,
    canonical_type_label,
    silver_column_marker,
    silver_model_fingerprint,
    silver_parity_fields,
)
from .dbt.specs import (
    SilverConstraintPhysicalPlan,
    SilverModelKind,
    SilverModelSpec,
    SilverPhysicalPlan,
)

logger = logging.getLogger(__name__)


class SilverParityError(ValueError):
    """Rendered representations drift from the shared Silver authority."""

    def __init__(self, errors: tuple[str, ...]) -> None:
        self.errors = errors
        self.blocking_rules = tuple(("DD-110-parity", error) for error in errors)
        super().__init__("Silver parity blocked: " + "; ".join(errors))


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _sql_comment(value: str) -> str:
    return " ".join(value.replace("--", "—").split())


def _column_fragment(column) -> str:
    nullability = "NULL" if column.nullable else "NOT NULL"
    default = (
        f" DEFAULT {column.default_expression}"
        if column.default_expression
        else ""
    )
    comment = f" -- {_sql_comment(column.comment)}" if column.comment else ""
    return (
        f"    {column.name} {column.physical_type}{default} "
        f"{nullability}{comment}"
    )


def _constraint_comment(constraint: SilverConstraintPhysicalPlan) -> str:
    target = ""
    if constraint.referenced_model:
        target_name = ".".join(
            value
            for value in (
                constraint.referenced_schema,
                constraint.referenced_model,
            )
            if value
        )
        target = (
            f" REFERENCES {target_name}"
            f" ({', '.join(constraint.referenced_columns)})"
        )
    temporal = (
        f"; temporal={constraint.temporal_mode}"
        f"{f'; as_of={constraint.as_of_column}' if constraint.as_of_column else ''}"
        if constraint.temporal_mode
        else ""
    )
    return (
        f"-- UNENFORCED {constraint.kind.upper()} {constraint.name}: "
        f"({', '.join(constraint.columns)}){target}{temporal}; "
        f"capability={constraint.capability_disposition}"
        f"{f'; deviation={constraint.deviation_ref}' if constraint.deviation_ref else ''}"
    )


def _render_ddl(plan: SilverPhysicalPlan, models: tuple[SilverModelSpec, ...]) -> str:
    specs = {model.identity.model_name: model for model in models}
    schemas = sorted({model.schema_name for model in plan.models})
    lines = [
        "-- DD-110 Silver physical DDL",
        f"-- Adapter: {plan.adapter}/{plan.adapter_version}",
        "-- Constraints and indexes are metadata-only unless explicitly marked enforced.",
        "",
    ]
    for schema in schemas:
        if plan.adapter == "fabric":
            lines.extend(
                (
                    f"IF SCHEMA_ID('{schema}') IS NULL",
                    f"    EXEC('CREATE SCHEMA {schema}');",
                )
            )
        else:
            lines.append(f"CREATE SCHEMA IF NOT EXISTS {schema};")
    if schemas:
        lines.append("")

    for physical in plan.models:
        spec = specs[physical.model_name]
        lines.extend(
            (
                f"-- DD-110-MODEL: {physical.model_name}",
                f"-- DD-110-SILVER-SPEC-SHA256: {silver_model_fingerprint(spec)}",
                f"-- DD-110-COLUMNS: {silver_column_marker(spec)}",
                (
                    f"-- Materialization: {physical.materialization}; "
                    f"dbt SQL: {physical.sql_artifact_path}"
                ),
            )
        )
        if physical.materialization == "view":
            lines.append(
                "-- VIEW definition is owned by the referenced dbt SQL; "
                "its exact physical columns follow."
            )
            lines.extend(
                f"-- COLUMN {_column_fragment(column).strip()}"
                for column in physical.columns
            )
        else:
            create = (
                f"CREATE TABLE {physical.schema_name}.{physical.model_name} ("
                if plan.adapter == "fabric"
                else (
                    f"CREATE TABLE IF NOT EXISTS "
                    f"{physical.schema_name}.{physical.model_name} ("
                )
            )
            lines.append(create)
            lines.append(",\n".join(_column_fragment(column) for column in physical.columns))
            lines.append(")" + (" USING DELTA" if plan.adapter == "databricks" else "") + ";")
        if physical.constraints:
            lines.extend(_constraint_comment(item) for item in physical.constraints)
        for index in physical.indexes:
            lines.append(
                f"-- INDEX METADATA {index.name}: ({', '.join(index.columns)}); "
                f"purpose={index.purpose}; applied=false"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _constraint_data(plan: SilverPhysicalPlan) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "authority": "SilverModelSpec",
        "adapter": {
            "name": plan.adapter,
            "version": plan.adapter_version,
        },
        "enforcement_note": (
            "enforced=false means metadata/documentation only; generated output "
            "does not claim runtime enforcement"
        ),
        "capabilities": [canonical_data(item) for item in plan.capability_results],
        "models": [
            {
                "model_name": model.model_name,
                "schema_name": model.schema_name,
                "materialization": model.materialization,
                "columns": [
                    {
                        "ordinal": column.ordinal,
                        "name": column.name,
                        "canonical_type": canonical_type_label(column.canonical_type),
                        "physical_type": column.physical_type,
                        "nullable": column.nullable,
                        "default": column.default_expression or None,
                        "role": column.role,
                        "runtime_generated": column.runtime_generated,
                        "comment": column.comment,
                        "provenance": list(column.provenance),
                    }
                    for column in model.columns
                ],
                "constraints": [canonical_data(item) for item in model.constraints],
                "indexes": [canonical_data(item) for item in model.indexes],
                "relation_links": [canonical_data(item) for item in model.relation_links],
                "provenance": list(model.provenance),
            }
            for model in plan.models
        ],
    }


def _mermaid_type(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


def _render_erd(plan: SilverPhysicalPlan) -> str:
    emitted = {model.model_name for model in plan.models}
    lines = [
        "erDiagram",
        (
            f"    %% Silver ERD: {plan.domain_name}; "
            f"adapter={plan.adapter}/{plan.adapter_version}"
        ),
        "    %% Relationships come only from emitted SilverForeignKeySpec values.",
        "",
    ]
    for model in plan.models:
        lines.append(f"    {model.model_name.upper()} {{")
        primary_columns = {
            column
            for constraint in model.constraints
            if constraint.kind == "primary-key"
            for column in constraint.columns
        }
        foreign_columns = {
            column
            for constraint in model.constraints
            if constraint.kind == "foreign-key"
            for column in constraint.columns
        }
        for column in model.columns:
            marker = (
                " PK"
                if column.name in primary_columns
                else " FK"
                if column.name in foreign_columns
                else ""
            )
            lines.append(
                f"        {_mermaid_type(column.physical_type)} "
                f"{column.name}{marker}"
            )
        lines.extend(("    }", ""))
    for model in plan.models:
        for constraint in model.constraints:
            if (
                constraint.kind != "foreign-key"
                or constraint.referenced_model not in emitted
            ):
                continue
            temporal = constraint.temporal_mode or "none"
            annotation = f"temporal={temporal}"
            if constraint.as_of_column:
                annotation += f";as-of={constraint.as_of_column}"
            lines.append(
                f'    {constraint.referenced_model.upper()} ||--o{{ '
                f'{model.model_name.upper()} : "{constraint.property_uri} '
                f'[{annotation}]"'
            )
    return "\n".join(lines).rstrip() + "\n"


def _schema_columns(content: str, model_name: str) -> tuple[str, ...] | None:
    loaded = yaml.safe_load(content)
    if not isinstance(loaded, dict):
        return None
    models = loaded.get("models", [])
    if not isinstance(models, list):
        return None
    model = next(
        (
            item
            for item in models
            if isinstance(item, dict) and item.get("name") == model_name
        ),
        None,
    )
    if model is None or not isinstance(model.get("columns"), list):
        return None
    return tuple(
        str(item.get("name"))
        for item in model["columns"]
        if isinstance(item, dict)
    )


def _representation(
    path: str | None,
    artifacts: dict[str, str],
    *,
    required: bool,
) -> dict[str, object]:
    if path is None:
        return {"status": "not-applicable"}
    content = artifacts.get(path)
    if content is None:
        return {
            "status": "missing" if required else "not-applicable",
            "path": path,
        }
    return {"status": "present", "path": path, "sha256": _sha256(content)}


def _build_parity_manifest(
    models: tuple[SilverModelSpec, ...],
    plan: SilverPhysicalPlan,
    artifacts: dict[str, str],
    schema_paths: dict[str, str],
) -> tuple[str, dict[str, object]]:
    errors: list[str] = []
    physical = {model.model_name: model for model in plan.models}
    model_entries: list[dict[str, object]] = []
    for model in models:
        if model.identity.artifact_path is None:
            continue
        expected_columns = tuple(column.name for column in model.columns)
        physical_model = physical.get(model.identity.model_name)
        if physical_model is None:
            errors.append(f"{model.identity.model_name}: physical plan is missing")
            continue
        actual_physical = tuple(column.name for column in physical_model.columns)
        if actual_physical != expected_columns:
            errors.append(
                f"{model.identity.model_name}: physical column order differs from spec"
            )
        sql_path = model.identity.artifact_path
        sql = artifacts.get(sql_path, "")
        marker = f"-- DD-110-COLUMNS: {silver_column_marker(model)}"
        if marker not in sql:
            errors.append(
                f"{model.identity.model_name}: dbt SQL column marker is missing or stale"
            )
        schema_path = schema_paths.get(model.identity.model_name)
        schema_required = model.kind in {
            SilverModelKind.ENTITY,
            SilverModelKind.UNION,
        }
        if schema_required:
            schema_content = artifacts.get(schema_path or "", "")
            if not schema_path or _schema_columns(
                schema_content,
                model.identity.model_name,
            ) != expected_columns:
                errors.append(
                    f"{model.identity.model_name}: schema YAML columns differ from spec"
                )
        ddl = artifacts.get(plan.ddl_artifact_path, "")
        if marker not in ddl:
            errors.append(
                f"{model.identity.model_name}: DDL column marker is missing or stale"
            )

        representations = {
            "dbt_sql": _representation(sql_path, artifacts, required=True),
            "schema_yaml": _representation(
                schema_path,
                artifacts,
                required=schema_required,
            ),
            "ddl": _representation(
                plan.ddl_artifact_path,
                artifacts,
                required=True,
            ),
            "constraint_metadata": _representation(
                plan.constraint_artifact_path,
                artifacts,
                required=True,
            ),
            "erd": _representation(
                plan.erd_artifact_path,
                artifacts,
                required=True,
            ),
        }
        fields = [
            {
                "field": path,
                "value_sha256": value_hash,
                "output_set": "model_representations",
            }
            for path, value_hash in silver_parity_fields(model)
        ]
        model_entries.append(
            {
                "model_name": model.identity.model_name,
                "spec_sha256": silver_model_fingerprint(model),
                "columns": list(expected_columns),
                "fields": fields,
                "representations": representations,
            }
        )

    referenced_paths = sorted(
        {
            value["path"]
            for model in model_entries
            for value in model["representations"].values()
            if value.get("status") == "present"
        }
    )
    manifest = {
        "schema_version": "1.0",
        "authority": "SilverModelSpec",
        "adapter": {
            "name": plan.adapter,
            "version": plan.adapter_version,
        },
        "status": "blocking" if errors else "pass",
        "errors": sorted(errors),
        "artifact_hashes": {
            path: _sha256(artifacts[path]) for path in referenced_paths
        },
        "models": model_entries,
    }
    content = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    status = {
        "status": manifest["status"],
        "manifest_path": plan.parity_artifact_path,
        "manifest_sha256": _sha256(content),
        "artifact_hashes": manifest["artifact_hashes"],
        "errors": manifest["errors"],
    }
    return content, status


def validate_parity_manifest(
    manifest_content: str,
    artifacts: dict[str, str],
) -> None:
    """Fail when a persisted parity manifest is missing, stale, or blocking."""
    loaded = json.loads(manifest_content)
    errors = list(loaded.get("errors", ()))
    if loaded.get("status") != "pass":
        errors.append("manifest status is not pass")
    hashes = loaded.get("artifact_hashes", {})
    if not isinstance(hashes, dict):
        errors.append("artifact_hashes is not an object")
    else:
        for path, expected in sorted(hashes.items()):
            content = artifacts.get(path)
            if content is None:
                errors.append(f"{path}: parity artifact is missing")
            elif _sha256(content) != expected:
                errors.append(f"{path}: parity artifact hash drift")
    if errors:
        raise SilverParityError(tuple(sorted(set(errors))))


def generate_silver_artifacts(
    *,
    models: tuple[SilverModelSpec, ...],
    physical_plan: SilverPhysicalPlan,
    rendered_artifacts: dict[str, str],
    schema_paths: dict[str, str],
) -> tuple[dict[str, str], dict[str, object]]:
    """Render DDL, constraint metadata, ERD, and parity from shared plans only."""
    artifacts = {
        physical_plan.ddl_artifact_path: _render_ddl(physical_plan, models),
        physical_plan.constraint_artifact_path: (
            json.dumps(_constraint_data(physical_plan), indent=2, sort_keys=True)
            + "\n"
        ),
        physical_plan.erd_artifact_path: _render_erd(physical_plan),
    }
    combined = {**rendered_artifacts, **artifacts}
    manifest, status = _build_parity_manifest(
        models,
        physical_plan,
        combined,
        schema_paths,
    )
    artifacts[physical_plan.parity_artifact_path] = manifest
    validate_parity_manifest(manifest, {**combined, physical_plan.parity_artifact_path: manifest})
    return artifacts, status


def generate_master_erd(
    dbt_output_path: Path,
    hub_name: str = "master",
) -> str | None:
    """Merge deterministic per-domain ERDs without changing their relationships."""
    diagrams_dir = dbt_output_path / "docs" / "diagrams"
    if not diagrams_dir.exists():
        return None
    domain_erds: list[tuple[str, str]] = []
    for mmd_file in sorted(diagrams_dir.rglob("*-erd.mmd")):
        if mmd_file.name == "master-erd.mmd":
            continue
        body = "\n".join(
            line
            for line in mmd_file.read_text(encoding="utf-8").splitlines()
            if line.strip() != "erDiagram"
            and not line.strip().startswith("%% Silver ERD:")
        ).strip()
        if body:
            domain_erds.append((mmd_file.parent.name, body))
    if not domain_erds:
        return None
    emitted: set[str] = set()
    relationships: set[str] = set()
    metadata_dir = dbt_output_path / "metadata"
    metadata_documents: list[dict] = []
    if metadata_dir.exists():
        for path in sorted(metadata_dir.glob("*-silver-constraints.json")):
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                metadata_documents.append(loaded)
                emitted.update(
                    str(model.get("model_name", ""))
                    for model in loaded.get("models", ())
                    if isinstance(model, dict)
                )
    for document in metadata_documents:
        for model in document.get("models", ()):
            if not isinstance(model, dict):
                continue
            source = str(model.get("model_name", ""))
            for constraint in model.get("constraints", ()):
                if (
                    not isinstance(constraint, dict)
                    or constraint.get("kind") != "foreign-key"
                ):
                    continue
                target = str(constraint.get("referenced_model", ""))
                if source not in emitted or target not in emitted:
                    continue
                temporal = str(constraint.get("temporal_mode") or "none")
                as_of = str(constraint.get("as_of_column") or "")
                annotation = f"temporal={temporal}"
                if as_of:
                    annotation += f";as-of={as_of}"
                relationships.add(
                    f'    {target.upper()} ||--o{{ {source.upper()} : "'
                    f'{constraint.get("property_uri", "")} [{annotation}]"'
                )
    lines = [
        "erDiagram",
        f"    %% Master ERD — {hub_name} (all domains)",
        "",
    ]
    for domain, body in domain_erds:
        lines.extend((f"    %% --- Domain: {domain} ---", body, ""))
    existing = "\n".join(body for _, body in domain_erds)
    cross_domain = [
        relationship
        for relationship in sorted(relationships)
        if relationship.strip() not in existing
    ]
    if cross_domain:
        lines.extend(("    %% --- Cross-domain relationships ---", *cross_domain, ""))
    return "\n".join(lines)


def render_mermaid_svg(mmd_path: Path) -> Path | None:
    """Render Mermaid through an installed CLI; absence remains non-fatal."""
    mmdc = None
    search_dir = mmd_path.parent
    while search_dir != search_dir.parent:
        for name in ("mmdc.cmd", "mmdc"):
            candidate = search_dir / "node_modules" / ".bin" / name
            if candidate.exists():
                mmdc = str(candidate)
                break
        if mmdc:
            break
        search_dir = search_dir.parent
    mmdc = mmdc or shutil.which("mmdc")
    if not mmdc:
        return None
    svg_path = mmd_path.with_suffix(".svg")
    try:
        subprocess.run(
            [mmdc, "-i", str(mmd_path), "-o", str(svg_path), "-q"],
            check=True,
            capture_output=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.warning("Mermaid render failed for %s: %s", mmd_path.name, exc)
        return None
    return svg_path
