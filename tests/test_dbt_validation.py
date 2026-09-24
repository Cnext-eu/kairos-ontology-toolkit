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
    _offline_profile,
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


def test_fabric_offline_profile_fails_connection_fast() -> None:
    output = _offline_profile("fabric-warehouse")["outputs"]["offline"]

    # A pre-supplied token (#825): a service-principal profile makes dbt-fabric emit
    # `Authority Id`, which mssql-python (dbt-fabric >= 1.10.1) rejects at parse, and
    # "sql" is not an accepted authentication value at all. Verified against dbt-fabric
    # 1.10.0 and 1.10.1: both reach the connect attempt and fail there.
    assert output["authentication"] == "ActiveDirectoryAccessToken"
    assert output["access_token"]
    assert not {"tenant_id", "client_id", "client_secret"} & set(output)
    assert output["retries"] == 0
    assert output["login_timeout"] == 1
    assert output["query_timeout"] == 1


def test_databricks_offline_profile_fails_connection_fast() -> None:
    """#922: the connector retried name resolution 30 times, so compile never finished."""
    output = _offline_profile("databricks")["outputs"]["offline"]

    assert output["host"] == "offline.invalid", "the adapter adds the scheme itself"
    assert output["connect_retries"] == 0
    assert output["connection_parameters"]["_retry_stop_after_attempts_count"] == 1


@pytest.mark.parametrize(
    "message",
    [
        # dbt-fabric 1.10.1 (mssql-python) with the offline profile.
        "Database Error\n  Driver Error: Client unable to establish connection; DDBC Error: "
        "[Microsoft]Named Pipes Provider: Could not open a connection to SQL Server [53].",
        # dbt-databricks with the fail-fast offline profile.
        "HTTPSConnectionPool(host='offline.invalid', port=443): Max retries exceeded with url: "
        "/sql/1.0/warehouses/offline (Caused by NameResolutionError(\"HTTPSConnection(host="
        "'offline.invalid', port=443): Failed to resolve 'offline.invalid' ([Errno 11001] "
        "getaddrinfo failed)\"))",
    ],
)
def test_the_offline_profiles_connect_failures_read_as_environment_blocked(message) -> None:
    from kairos_ontology.core.dbt_validation import _is_environment_blocked

    assert _is_environment_blocked(message)


def test_a_real_sql_error_is_not_environment_blocked() -> None:
    from kairos_ontology.core.dbt_validation import _is_environment_blocked

    assert not _is_environment_blocked("Compilation Error in model m: 'foo' is undefined")


def test_validate_dbt_project_runs_required_sequence(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _manifest(project)
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(list(args))
        assert kwargs["cwd"] == project.resolve()
        return _result()

    result = validate_dbt_project(project, "fabric-warehouse", runner=runner)

    assert [call[1] for call in calls] == ["deps", "parse", "compile"]
    assert result.compile_status == "passed"
    assert result.manifest_path == project / "target" / "manifest.json"


def test_structural_check_catches_dangling_ref(tmp_path: Path) -> None:
    project = _project(tmp_path)
    models = project / "models" / "silver" / "consignment"
    models.mkdir(parents=True)
    (models / "consoltransportleg.sql").write_text(
        "select * from {{ ref('carrierreservation') }}", encoding="utf-8"
    )

    def runner(args, **kwargs):
        raise AssertionError("dbt must not run once the structural scan fails")

    with pytest.raises(DbtValidationError, match="dbt structural failed"):
        validate_dbt_project(project, "fabric-warehouse", runner=runner)


def test_structural_check_passes_with_resolvable_refs(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _manifest(project)
    models = project / "models" / "silver" / "consignment"
    models.mkdir(parents=True)
    (models / "consoltransportleg.sql").write_text(
        "select * from {{ ref('transportbooking') }}", encoding="utf-8"
    )
    (project / "models" / "silver" / "booking").mkdir(parents=True)
    (project / "models" / "silver" / "booking" / "transportbooking.sql").write_text(
        "select 1", encoding="utf-8"
    )

    result = validate_dbt_project(project, "fabric-warehouse", runner=lambda *a, **k: _result())

    assert result.compile_status == "passed"


def test_structural_check_catches_a_duplicate_model_name(tmp_path: Path) -> None:
    """#786: the one defect class that makes an emitted package unparseable.

    dbt resolves ref() in a single resource namespace, so no --select works around this
    and no dataplatform can consume the package. #777 and #779 were both this shape and
    both passed `--structural-only`, which ran exactly one check: the dangling-ref scan.
    """
    project = _project(tmp_path)
    for domain in ("consignment", "booking"):
        models = project / "models" / "silver" / domain
        models.mkdir(parents=True)
        (models / "transportleg.sql").write_text("select 1", encoding="utf-8")

    def runner(args, **kwargs):
        raise AssertionError("dbt must not run once the structural scan fails")

    with pytest.raises(DbtValidationError, match="two dbt resources claim one name"):
        validate_dbt_project(project, "fabric-warehouse", runner=runner)


def test_structural_check_catches_a_model_and_seed_sharing_a_name(tmp_path: Path) -> None:
    """Seeds share the ref() namespace, which is why they are checked together."""
    project = _project(tmp_path)
    models = project / "models" / "silver" / "reference"
    models.mkdir(parents=True)
    (models / "country.sql").write_text("select 1", encoding="utf-8")
    seeds = project / "seeds"
    seeds.mkdir(parents=True)
    (seeds / "country.csv").write_text("code\nBE\n", encoding="utf-8")

    with pytest.raises(DbtValidationError, match="two dbt resources claim one name"):
        validate_dbt_project(project, "fabric-warehouse", runner=lambda *a, **k: _result())


def test_structural_check_catches_a_repeated_generic_test(tmp_path: Path) -> None:
    """The #777/#779 shape: dbt derives one name from test name plus arguments."""
    project = _project(tmp_path)
    models = project / "models" / "silver" / "cargo"
    models.mkdir(parents=True)
    (models / "cargounit.sql").write_text("select 1", encoding="utf-8")
    (models / "cargounit.yml").write_text(
        "version: 2\n"
        "models:\n"
        "  - name: cargounit\n"
        "    columns:\n"
        "      - name: parent_source_id\n"
        "        data_tests:\n"
        "          - kairos_temporal_fk_cardinality:\n"
        "              arguments:\n"
        "                cardinality: zero-or-one\n"
        "          - kairos_temporal_fk_cardinality:\n"
        "              arguments:\n"
        "                cardinality: zero-or-one\n",
        encoding="utf-8",
    )

    with pytest.raises(DbtValidationError, match="declared twice with identical arguments"):
        validate_dbt_project(project, "fabric-warehouse", runner=lambda *a, **k: _result())


def test_structural_check_allows_distinct_tests_on_one_column(tmp_path: Path) -> None:
    """Two tests differing in their arguments render to distinct names and are fine."""
    project = _project(tmp_path)
    _manifest(project)
    models = project / "models" / "silver" / "cargo"
    models.mkdir(parents=True)
    (models / "cargounit.sql").write_text("select 1", encoding="utf-8")
    (models / "cargounit.yml").write_text(
        "version: 2\n"
        "models:\n"
        "  - name: cargounit\n"
        "    columns:\n"
        "      - name: parent_source_id\n"
        "        data_tests:\n"
        "          - not_null\n"
        "          - unique\n"
        "          - kairos_temporal_fk_cardinality:\n"
        "              arguments:\n"
        "                cardinality: zero-or-one\n"
        "          - kairos_temporal_fk_cardinality:\n"
        "              arguments:\n"
        "                cardinality: exactly-one\n",
        encoding="utf-8",
    )

    result = validate_dbt_project(project, "fabric-warehouse", runner=lambda *a, **k: _result())

    assert result.compile_status == "passed"


def test_structural_only_never_invokes_dbt(tmp_path: Path) -> None:
    project = _project(tmp_path)
    models = project / "models" / "silver" / "party"
    models.mkdir(parents=True)
    (models / "organisation.sql").write_text("select 1", encoding="utf-8")

    def runner(args, **kwargs):
        raise AssertionError("structural_only must never shell out to dbt")

    result = validate_dbt_project(project, "fabric-warehouse", runner=runner, structural_only=True)

    assert result.compile_status == "skipped"


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
        validate_dbt_project(project, "fabric-warehouse", runner=parse_failure)

    def compile_failure(args, **kwargs):
        if args[1] == "compile":
            return _result(1, stderr="Compilation Error in model shipment")
        return _result()

    with pytest.raises(DbtValidationError, match="dbt compile failed"):
        validate_dbt_project(project, "fabric-warehouse", runner=compile_failure)


@pytest.mark.parametrize(
    ("include_wrapper", "include_test", "match"),
    [
        (False, True, "no generated Silver dependent"),
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

    result = validate_dbt_project(project, "fabric-warehouse", runner=runner)

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
            "fabric-warehouse",
            runner=lambda *args, **kwargs: _result(),
        )


def test_explicit_profiles_directory_must_contain_profile(tmp_path: Path) -> None:
    project = _project(tmp_path)
    profiles = tmp_path / "profiles"
    profiles.mkdir()

    with pytest.raises(DbtValidationError, match="no profiles.yml"):
        validate_dbt_project(
            project,
            "fabric-warehouse",
            profiles_dir=profiles,
            runner=lambda *args, **kwargs: _result(),
        )


def _silver_manifest(
    project: Path,
    *,
    marker: str | None,
    columns: list[str] | None,
) -> None:
    node: dict[str, object] = {
        "name": "shipment",
        "resource_type": "model",
        "original_file_path": "models/silver/logistics/shipment.sql",
        "depends_on": {"nodes": []},
    }
    if marker is not None:
        node["raw_code"] = f"-- DD-110-COLUMNS: {marker}\nselect 1 as one\n"
    if columns is not None:
        node["columns"] = {name: {"name": name} for name in columns}
    (project / "target" / "manifest.json").write_text(
        json.dumps({"nodes": {"model.test_project.shipment": node}, "unit_tests": {}}),
        encoding="utf-8",
    )


def test_manifest_parity_accepts_matching_marker_and_columns(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _silver_manifest(project, marker='["a","b","c"]', columns=["a", "b", "c"])

    validate_manifest(project / "target" / "manifest.json")


def test_manifest_parity_rejects_column_drift(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _silver_manifest(project, marker='["a","b","c"]', columns=["a", "c", "b"])

    with pytest.raises(DbtValidationError, match="DD-110 Silver output parity"):
        validate_manifest(project / "target" / "manifest.json")


def test_manifest_parity_skips_models_without_contract_columns(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _silver_manifest(project, marker='["a","b"]', columns=None)

    validate_manifest(project / "target" / "manifest.json")


def test_manifest_parity_skips_models_without_marker(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _silver_manifest(project, marker=None, columns=["a", "b"])

    validate_manifest(project / "target" / "manifest.json")


def test_manifest_parity_rejects_malformed_marker(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _silver_manifest(project, marker="[not json", columns=["a"])

    with pytest.raises(DbtValidationError, match="malformed DD-110-COLUMNS marker"):
        validate_manifest(project / "target" / "manifest.json")
