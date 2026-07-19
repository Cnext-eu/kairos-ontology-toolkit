# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for offline dbt parse, compile, and manifest validation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kairos_ontology.core.dbt_validation import (
    DbtValidationError,
    validate_dbt_project,
    validate_manifest,
)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "dbt"
    (project / "target").mkdir(parents=True)
    (project / "dbt_project.yml").write_text(
        "name: test_project\nprofile: test_project\nversion: '1.0.0'\n",
        encoding="utf-8",
    )
    return project


def _manifest(
    project: Path,
    *,
    include_wrapper: bool = True,
    include_test: bool = True,
    unit_test: bool = False,
) -> None:
    custom_id = "model.test_project.int_shipment_conformed"
    nodes: dict[str, object] = {
        custom_id: {
            "name": "int_shipment_conformed",
            "resource_type": "model",
            "original_file_path": "models/intermediate/int_shipment_conformed.sql",
            "meta": {
                "kairos": {
                    "decisions": [
                        {
                            "id": "route-fallback",
                            "verified_by": ["unit_test_route_fallback"],
                        }
                    ]
                }
            },
            "depends_on": {"nodes": []},
        }
    }
    if include_wrapper:
        nodes["model.test_project.shipment"] = {
            "name": "shipment",
            "resource_type": "model",
            "original_file_path": "models/silver/logistics/shipment.sql",
            "depends_on": {"nodes": [custom_id]},
        }
    unit_tests = {}
    if include_test:
        test = {
            "name": "unit_test_route_fallback",
            "resource_type": "unit_test" if unit_test else "test",
            "depends_on": {"nodes": [custom_id]},
        }
        if unit_test:
            unit_tests["unit_test.test_project.unit_test_route_fallback"] = test
        else:
            nodes["test.test_project.unit_test_route_fallback"] = test
    (project / "target" / "manifest.json").write_text(
        json.dumps({"nodes": nodes, "unit_tests": unit_tests}),
        encoding="utf-8",
    )


def _result(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_validate_dbt_project_runs_required_sequence(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _manifest(project)
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(list(args))
        assert kwargs["cwd"] == project.resolve()
        return _result()

    result = validate_dbt_project(project, "fabric", runner=runner)

    assert [call[1] for call in calls] == ["deps", "parse", "compile"]
    assert result.compile_status == "passed"
    assert result.manifest_path == project / "target" / "manifest.json"


def test_compile_connection_failure_is_environment_blocked(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _manifest(project)

    def runner(args, **kwargs):
        if args[1] == "compile":
            return _result(1, stderr="Authentication failed: could not connect")
        return _result()

    result = validate_dbt_project(project, "databricks", runner=runner)

    assert result.compile_status == "environment_blocked"
    assert "Authentication failed" in (result.compile_message or "")


def test_parse_and_sql_compile_failures_are_blocking(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _manifest(project)

    def parse_failure(args, **kwargs):
        return _result(1, stderr="Parsing Error") if args[1] == "parse" else _result()

    with pytest.raises(DbtValidationError, match="dbt parse failed"):
        validate_dbt_project(project, "fabric", runner=parse_failure)

    def compile_failure(args, **kwargs):
        if args[1] == "compile":
            return _result(1, stderr="Compilation Error in model shipment")
        return _result()

    with pytest.raises(DbtValidationError, match="dbt compile failed"):
        validate_dbt_project(project, "fabric", runner=compile_failure)


@pytest.mark.parametrize(
    ("include_wrapper", "include_test", "match"),
    [
        (False, True, "no generated Silver dependent"),
        (True, False, "references missing test"),
    ],
)
def test_manifest_requires_wrapper_and_decision_test_edges(
    tmp_path: Path,
    include_wrapper: bool,
    include_test: bool,
    match: str,
) -> None:
    project = _project(tmp_path)
    _manifest(project, include_wrapper=include_wrapper, include_test=include_test)

    with pytest.raises(DbtValidationError, match=match):
        validate_manifest(project / "target" / "manifest.json")


def test_manifest_accepts_dbt_unit_test_section(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _manifest(project, unit_test=True)

    validate_manifest(project / "target" / "manifest.json")


def test_cursor_compile_failure_is_environment_blocked(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _manifest(project)

    def runner(args, **kwargs):
        if args[1] == "compile":
            return _result(1, stderr="'NoneType' object has no attribute 'cursor'")
        return _result()

    result = validate_dbt_project(project, "fabric", runner=runner)

    assert result.compile_status == "environment_blocked"


def test_compile_timeout_is_environment_blocked(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _manifest(project)

    def runner(args, **kwargs):
        if args[1] == "compile":
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        return _result()

    result = validate_dbt_project(project, "databricks", runner=runner)

    assert result.compile_status == "environment_blocked"
    assert "exceeded 120 seconds" in (result.compile_message or "")


def test_rejects_invalid_platform_and_project(tmp_path: Path) -> None:
    project = _project(tmp_path)

    with pytest.raises(DbtValidationError, match="unsupported platform"):
        validate_dbt_project(project, "snowflake", runner=lambda *args, **kwargs: _result())

    with pytest.raises(DbtValidationError, match="no dbt_project.yml"):
        validate_dbt_project(
            tmp_path / "missing",
            "fabric",
            runner=lambda *args, **kwargs: _result(),
        )


def test_explicit_profiles_directory_must_contain_profile(tmp_path: Path) -> None:
    project = _project(tmp_path)
    profiles = tmp_path / "profiles"
    profiles.mkdir()

    with pytest.raises(DbtValidationError, match="no profiles.yml"):
        validate_dbt_project(
            project,
            "fabric",
            profiles_dir=profiles,
            runner=lambda *args, **kwargs: _result(),
        )
