# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Offline dbt dependency, parse, compile, and manifest validation."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import yaml

SUPPORTED_PLATFORMS = ("fabric", "databricks")

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
    if platform == "fabric":
        output = {
            "type": "fabric",
            "driver": "ODBC Driver 18 for SQL Server",
            "server": "offline.invalid",
            "database": "offline",
            "schema": "dbo",
            "authentication": "ServicePrincipal",
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
            "type": "databricks",
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


def _node_name(node: dict[str, object]) -> str:
    return str(node.get("name") or "")


def _dependency_ids(node: dict[str, object]) -> set[str]:
    depends_on = node.get("depends_on")
    if not isinstance(depends_on, dict):
        return set()
    values = depends_on.get("nodes")
    return {str(value) for value in values} if isinstance(values, list) else set()


def validate_manifest(manifest_path: Path) -> None:
    """Validate custom-model wrapper and decision-test edges in a dbt manifest."""
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
    test_nodes = {
        node_id: node
        for node_id, node in nodes.items()
        if isinstance(node, dict) and node.get("resource_type") == "test"
    }
    unit_tests = manifest.get("unit_tests", {})
    if isinstance(unit_tests, dict):
        test_nodes.update(
            {
                node_id: node
                for node_id, node in unit_tests.items()
                if isinstance(node, dict) and node.get("resource_type") == "unit_test"
            }
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

        decisions = kairos.get("decisions", [])
        if not isinstance(decisions, list):
            continue
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            for test_name in decision.get("verified_by", []) or []:
                matches = [
                    test for test in test_nodes.values() if _node_name(test) == str(test_name)
                ]
                if not matches:
                    raise DbtValidationError(
                        "manifest",
                        f"decision '{decision.get('id')}' references missing test '{test_name}'",
                    )
                if not any(model_id in _dependency_ids(test) for test in matches):
                    raise DbtValidationError(
                        "manifest",
                        f"test '{test_name}' does not depend on contracted model "
                        f"'{_node_name(model)}'",
                    )


def validate_dbt_project(
    project_dir: Path,
    platform: str,
    *,
    profiles_dir: Path | None = None,
    executable: str = "dbt",
    runner: RunCommand = subprocess.run,
) -> DbtValidationResult:
    """Run offline dbt validation for one generated adapter-specific project."""
    project_dir = Path(project_dir).resolve()
    if platform not in SUPPORTED_PLATFORMS:
        raise DbtValidationError(
            "preflight",
            f"unsupported platform '{platform}'; choose {', '.join(SUPPORTED_PLATFORMS)}",
        )
    if not (project_dir / "dbt_project.yml").is_file():
        raise DbtValidationError("preflight", f"no dbt_project.yml under {project_dir}")
    if runner is subprocess.run and shutil.which(executable) is None:
        extra = f"dbt-validate-{platform}"
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
    try:
        try:
            deps = _run((executable, "deps", *common), project_dir=project_dir, runner=runner)
        except subprocess.TimeoutExpired as exc:
            raise DbtValidationError("deps", "command exceeded 300 seconds") from exc
        if deps.returncode:
            raise DbtValidationError("deps", _failure_text(deps))

        try:
            parse = _run((executable, "parse", *common), project_dir=project_dir, runner=runner)
        except subprocess.TimeoutExpired as exc:
            raise DbtValidationError("parse", "command exceeded 300 seconds") from exc
        if parse.returncode:
            raise DbtValidationError("parse", _failure_text(parse))

        manifest_path = project_dir / "target" / "manifest.json"
        validate_manifest(manifest_path)

        try:
            compile_result = _run(
                (executable, "compile", *common),
                project_dir=project_dir,
                runner=runner,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
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
        if compile_result.returncode:
            message = _failure_text(compile_result)
            if _is_environment_blocked(message):
                return DbtValidationResult(
                    platform=platform,
                    project_dir=project_dir,
                    manifest_path=manifest_path,
                    compile_status="environment_blocked",
                    compile_message=message,
                )
            raise DbtValidationError("compile", message)

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
