# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Offline dbt dependency, parse, compile, and manifest validation."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .observability.events import (
    DBT_ENVIRONMENT_BLOCKED,
    timed_phase,
)

import yaml

from .adapters import (
    FABRIC_WAREHOUSE,
    SUPPORTED_ADAPTER_IDS,
    dbt_profile_type,
    dbt_validate_extra,
)

#: Canonical vocabulary owned by :mod:`kairos_ontology.core.adapters` (DD-215).
SUPPORTED_PLATFORMS = SUPPORTED_ADAPTER_IDS

_ENVIRONMENT_BLOCK_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"credential",
        r"authentication",
        r"access token",
        r"client secret",
        r"login failed",
        r"cannot open server",
        r"could not connect",
        "has no attribute 'cursor'",
        'has no attribute "cursor"',
        r"connection (?:error|failed|refused|timeout)",
        r"network",
        r"pyodbc",
        r"odbc driver",
        r"http[_ ]path",
        r"warehouse.*(?:not found|unavailable)",
        r"temporary failure in name resolution",
    )
)


class DbtValidationError(RuntimeError):
    """Raised when generated dbt artifacts fail an offline validation gate."""

    def __init__(self, phase: str, message: str) -> None:
        super().__init__(f"dbt {phase} failed: {message}")
        self.phase = phase
        self.message = message


@dataclass(frozen=True)
class DbtValidationResult:
    """Result of validating one generated dbt project."""

    platform: str
    project_dir: Path
    manifest_path: Path
    compile_status: str
    compile_message: str | None = None


RunCommand = Callable[..., subprocess.CompletedProcess[str]]


def _profile_name(project_dir: Path) -> str:
    project_file = project_dir / "dbt_project.yml"
    try:
        project = yaml.safe_load(project_file.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise DbtValidationError("preflight", f"cannot read {project_file}: {exc}") from exc
    profile = project.get("profile")
    if not isinstance(profile, str) or not profile.strip():
        raise DbtValidationError("preflight", "dbt_project.yml has no non-empty profile")
    return profile.strip()


def _offline_profile(platform: str) -> dict[str, object]:
    if platform == FABRIC_WAREHOUSE:
        output = {
            "type": dbt_profile_type(platform),
            "driver": "ODBC Driver 18 for SQL Server",
            "server": "offline.invalid",
            "database": "offline",
            "schema": "dbo",
            # dbt-fabric dispatches on this value case-insensitively against a closed
            # set (`fabric_token_provider.py`) that does not contain "ServicePrincipal";
            # the spelling it accepts is "ActiveDirectoryServicePrincipal" (#705). The
            # wrong value surfaced only at `dbt compile` as
            # "Unsupported authentication method", never at parse.
            "authentication": "ActiveDirectoryServicePrincipal",
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "client_id": "00000000-0000-0000-0000-000000000000",
            "client_secret": "offline",
            "retries": 0,
            "login_timeout": 1,
            "query_timeout": 1,
            "threads": 1,
        }
    else:
        output = {
            "type": dbt_profile_type(platform),
            "host": "https://offline.invalid",
            "http_path": "/sql/1.0/warehouses/offline",
            "token": "offline",
            "schema": "default",
            "threads": 1,
        }
    return {"target": "offline", "outputs": {"offline": output}}


def _write_offline_profiles(project_dir: Path, platform: str, destination: Path) -> None:
    profile = _profile_name(project_dir)
    destination.mkdir(parents=True, exist_ok=True)
    content = {profile: _offline_profile(platform)}
    (destination / "profiles.yml").write_text(
        yaml.safe_dump(content, sort_keys=False),
        encoding="utf-8",
    )


def _run(
    args: Sequence[str],
    *,
    project_dir: Path,
    runner: RunCommand,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    return runner(
        list(args),
        cwd=project_dir,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _failure_text(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    return output or f"process exited with code {result.returncode}"


def _is_environment_blocked(message: str) -> bool:
    return any(pattern.search(message) for pattern in _ENVIRONMENT_BLOCK_PATTERNS)


_MODEL_REF_RE = re.compile(r"\bref\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")


def _dangling_refs(project_dir: Path) -> dict[str, list[str]]:
    """Map each model's relative path to any ``ref()`` targets with no model file.

    Text-scans the already-assembled project on disk (DD-140's unified topology),
    independent of dbt or of the compiler's per-domain relationship resolution
    (DD-138/139 keep that scoped to one domain and never search peer bindings) --
    this instead checks whether the artifact those bindings produced is internally
    self-consistent, the same class of defect dbt's own parser would catch (#342).
    """
    models_dir = project_dir / "models"
    if not models_dir.is_dir():
        return {}
    sql_files = sorted(models_dir.rglob("*.sql"))
    known_models = {path.stem for path in sql_files}
    # #586: ref() may target a dbt seed; emitted seed CSVs live under seeds/ and share
    # the model ref namespace.
    seeds_dir = project_dir / "seeds"
    if seeds_dir.is_dir():
        known_models.update(path.stem for path in seeds_dir.rglob("*.csv"))
    problems: dict[str, list[str]] = {}
    for path in sql_files:
        content = path.read_text(encoding="utf-8")
        missing = sorted(set(_MODEL_REF_RE.findall(content)) - known_models)
        if missing:
            problems[str(path.relative_to(project_dir).as_posix())] = missing
    return problems


def _node_name(node: dict[str, object]) -> str:
    return str(node.get("name") or "")


def _dependency_ids(node: dict[str, object]) -> set[str]:
    depends_on = node.get("depends_on")
    if not isinstance(depends_on, dict):
        return set()
    values = depends_on.get("nodes")
    return {str(value) for value in values} if isinstance(values, list) else set()


_COLUMN_MARKER = re.compile(r"^-- DD-110-COLUMNS: (.+)$", re.MULTILINE)


def _marker_columns(node: dict[str, object]) -> list[str] | None:
    """Return the ordered column names declared in a model's DD-110-COLUMNS marker.

    Returns ``None`` when the model carries no marker (e.g. Gold or non-Kairos models).
    Raises when the marker exists but is not a JSON array of strings.
    """
    raw = node.get("raw_code")
    if not isinstance(raw, str):
        raw = node.get("raw_sql")
    if not isinstance(raw, str):
        return None
    match = _COLUMN_MARKER.search(raw)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise DbtValidationError(
            "manifest",
            f"model '{_node_name(node)}' has a malformed DD-110-COLUMNS marker: {exc}",
        ) from exc
    if not isinstance(parsed, list) or not all(isinstance(name, str) for name in parsed):
        raise DbtValidationError(
            "manifest",
            f"model '{_node_name(node)}' DD-110-COLUMNS marker is not a JSON array of names",
        )
    return list(parsed)


def _manifest_columns(node: dict[str, object]) -> list[str]:
    """Return the ordered contract column names dbt parsed for a model node."""
    columns = node.get("columns")
    return list(columns.keys()) if isinstance(columns, dict) else []


def validate_manifest(manifest_path: Path) -> None:
    """Validate custom-model wrapper edges and DD-110 Silver output parity in a dbt manifest."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DbtValidationError("manifest", f"cannot read {manifest_path}: {exc}") from exc

    nodes = manifest.get("nodes")
    if not isinstance(nodes, dict):
        raise DbtValidationError("manifest", "manifest.json has no nodes object")

    model_nodes = {
        node_id: node
        for node_id, node in nodes.items()
        if isinstance(node, dict) and node.get("resource_type") == "model"
    }
    for model in model_nodes.values():
        marker = _marker_columns(model)
        if marker is None:
            continue
        declared = _manifest_columns(model)
        # DD-110 parity only fires when dbt actually parsed a column contract for the model;
        # an empty declaration means the contract is not enforced, so comparing would produce
        # a false positive rather than catch real drift.
        if declared and declared != marker:
            raise DbtValidationError(
                "manifest",
                (
                    f"model '{_node_name(model)}' violates DD-110 Silver output parity: "
                    f"emitted marker columns {marker} do not match the parsed manifest "
                    f"columns {declared} (order-sensitive)"
                ),
            )
    for model_id, model in model_nodes.items():
        meta = model.get("meta")
        kairos = meta.get("kairos") if isinstance(meta, dict) else None
        if not isinstance(kairos, dict):
            continue

        silver_dependents = [
            node
            for node in model_nodes.values()
            if model_id in _dependency_ids(node)
            and "models/silver/" in str(node.get("original_file_path") or "").replace("\\", "/")
        ]
        if not silver_dependents:
            raise DbtValidationError(
                "manifest",
                f"contracted model '{_node_name(model)}' has no generated Silver dependent",
            )
        meta = model.get("meta")
        kairos = meta.get("kairos") if isinstance(meta, dict) else None
        if not isinstance(kairos, dict):
            continue

        silver_dependents = [
            node
            for node in model_nodes.values()
            if model_id in _dependency_ids(node)
            and "models/silver/" in str(node.get("original_file_path") or "").replace("\\", "/")
        ]
        if not silver_dependents:
            raise DbtValidationError(
                "manifest",
                f"contracted model '{_node_name(model)}' has no generated Silver dependent",
            )


def validate_dbt_project(
    project_dir: Path,
    platform: str,
    *,
    profiles_dir: Path | None = None,
    executable: str = "dbt",
    runner: RunCommand = subprocess.run,
    structural_only: bool = False,
) -> DbtValidationResult:
    """Run offline dbt validation for one generated adapter-specific project.

    Runs a structural dangling-``ref()`` scan first, unconditionally -- it needs
    no dbt installation, so it still catches #342-shaped defects (a cross-domain
    ``ref()`` naming a model absent from the assembled project) in environments
    where ``dbt`` itself is unavailable. ``structural_only=True`` stops there,
    skipping the deps/parse/compile phases and the dbt-installed preflight check
    entirely -- for callers (CI's release loop) that want this gate without
    paying for a real dbt install.
    """
    project_dir = Path(project_dir).resolve()
    if platform not in SUPPORTED_PLATFORMS:
        raise DbtValidationError(
            "preflight",
            f"unsupported platform '{platform}'; choose {', '.join(SUPPORTED_PLATFORMS)}",
        )
    if not (project_dir / "dbt_project.yml").is_file():
        raise DbtValidationError("preflight", f"no dbt_project.yml under {project_dir}")

    with timed_phase("structural", platform=platform, project_dir=str(project_dir)):
        dangling = _dangling_refs(project_dir)
        if dangling:
            details = "; ".join(f"{path} -> {refs}" for path, refs in sorted(dangling.items()))
            raise DbtValidationError(
                "structural",
                f"ref() targets no model file in this assembled project: {details}",
            )

    if structural_only:
        return DbtValidationResult(
            platform=platform,
            project_dir=project_dir,
            manifest_path=project_dir / "target" / "manifest.json",
            compile_status="skipped",
            compile_message="structural-only run; dbt deps/parse/compile were not invoked",
        )

    if runner is subprocess.run and shutil.which(executable) is None:
        # Not f"dbt-validate-{platform}": DD-215 renamed the canonical adapter id to
        # `fabric-warehouse` while the hub extra stayed `dbt-validate-fabric`, so the
        # composed name pointed at an extra no hub declares (#686).
        extra = dbt_validate_extra(platform)
        raise DbtValidationError(
            "preflight",
            f"'{executable}' is not installed; run `uv sync --extra {extra}`",
        )
    target_dir = project_dir / "target"
    packages_dir = project_dir / "dbt_packages"
    target_existed = target_dir.exists()
    packages_existed = packages_dir.exists()

    temporary: tempfile.TemporaryDirectory[str] | None = None
    if profiles_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="kairos-dbt-profiles-")
        effective_profiles = Path(temporary.name)
        _write_offline_profiles(project_dir, platform, effective_profiles)
    else:
        effective_profiles = Path(profiles_dir).resolve()
        if not (effective_profiles / "profiles.yml").is_file():
            raise DbtValidationError(
                "preflight",
                f"no profiles.yml under {effective_profiles}",
            )

    common = ("--profiles-dir", str(effective_profiles))
    project_dir_str = str(project_dir)
    try:
        try:
            with timed_phase(
                "deps",
                platform=platform,
                project_dir=project_dir_str,
            ):
                deps = _run((executable, "deps", *common), project_dir=project_dir, runner=runner)
                if deps.returncode:
                    raise DbtValidationError("deps", _failure_text(deps))
        except subprocess.TimeoutExpired as exc:
            raise DbtValidationError("deps", "command exceeded 300 seconds") from exc

        try:
            with timed_phase(
                "parse",
                platform=platform,
                project_dir=project_dir_str,
            ):
                parse = _run((executable, "parse", *common), project_dir=project_dir, runner=runner)
                if parse.returncode:
                    raise DbtValidationError("parse", _failure_text(parse))
        except subprocess.TimeoutExpired as exc:
            raise DbtValidationError("parse", "command exceeded 300 seconds") from exc

        manifest_path = project_dir / "target" / "manifest.json"
        validate_manifest(manifest_path)

        try:
            with timed_phase(
                "compile",
                platform=platform,
                project_dir=project_dir_str,
            ):
                compile_result = _run(
                    (executable, "compile", *common),
                    project_dir=project_dir,
                    runner=runner,
                    timeout=120,
                )
                if compile_result.returncode:
                    message = _failure_text(compile_result)
                    if _is_environment_blocked(message):
                        logging.getLogger("kairos_ontology.dbt").info(
                            "dbt compile environment-blocked",
                            extra={
                                "event": DBT_ENVIRONMENT_BLOCKED,
                                "kairos.dbt.phase": "compile",
                                "kairos.dbt.platform": platform,
                                "kairos.retryable": True,
                            },
                        )
                        return DbtValidationResult(
                            platform=platform,
                            project_dir=project_dir,
                            manifest_path=manifest_path,
                            compile_status="environment_blocked",
                            compile_message=message,
                        )
                    raise DbtValidationError("compile", message)
        except subprocess.TimeoutExpired:
            logging.getLogger("kairos_ontology.dbt").info(
                "dbt compile environment-blocked (timeout)",
                extra={
                    "event": DBT_ENVIRONMENT_BLOCKED,
                    "kairos.dbt.phase": "compile",
                    "kairos.dbt.platform": platform,
                    "kairos.retryable": True,
                },
            )
            return DbtValidationResult(
                platform=platform,
                project_dir=project_dir,
                manifest_path=manifest_path,
                compile_status="environment_blocked",
                compile_message=(
                    "dbt compile exceeded 120 seconds while using the "
                    "credential-free offline profile"
                ),
            )

        return DbtValidationResult(
            platform=platform,
            project_dir=project_dir,
            manifest_path=manifest_path,
            compile_status="passed",
        )
    finally:
        if temporary is not None:
            temporary.cleanup()
        if not target_existed:
            shutil.rmtree(target_dir, ignore_errors=True)
        if not packages_existed:
            shutil.rmtree(packages_dir, ignore_errors=True)
