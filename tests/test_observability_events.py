# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for stable structured dbt-validation event emission (DD-151)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from kairos_ontology.core.dbt_validation import (
    DbtValidationError,
    validate_dbt_project,
)
from kairos_ontology.core.observability.events import (
    DBT_ENVIRONMENT_BLOCKED,
    DBT_PHASE_COMPLETED,
    DBT_PHASE_FAILED,
    DBT_PHASE_STARTED,
)
from kairos_ontology.core.observability.logging_config import reset_logging
from kairos_ontology.core.observability.context import clear_operation_context


@pytest.fixture(autouse=True)
def _clean_observability():
    reset_logging()
    clear_operation_context()
    yield
    reset_logging()
    clear_operation_context()


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "dbt"
    (project / "target").mkdir(parents=True)
    (project / "dbt_project.yml").write_text(
        "name: test_project\nprofile: test_project\nversion: '1.0.0'\n",
        encoding="utf-8",
    )
    manifest = project / "target" / "manifest.json"
    manifest.write_text(
        '{"metadata": {"dbt_schema_version": "v2"}, "nodes": {}, "sources": {}}',
        encoding="utf-8",
    )
    return project


def _result(returncode: int = 0, stdout: str = "", stderr: str = ""):
    class _R:
        pass

    r = _R()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


class _Capture:
    def __init__(self) -> None:
        self.records: list[logging.LogRecord] = []

    def filter(self, record: logging.LogRecord) -> bool:
        self.records.append(record)
        return True


@pytest.fixture()
def _capture(monkeypatch):
    cap = _Capture()
    root = logging.getLogger("kairos_ontology.dbt")
    root.addFilter(cap)
    root.setLevel(logging.DEBUG)
    yield cap
    root.removeFilter(cap)


def _events(cap: _Capture) -> list[str]:
    return [r.__dict__.get("event") for r in cap.records if r.__dict__.get("event")]


def test_happy_path_emits_phase_completed_for_each_phase(tmp_path, monkeypatch, _capture):
    project = _project(tmp_path)
    result = validate_dbt_project(project, "fabric", runner=lambda *a, **k: _result())
    assert result.compile_status == "passed"
    events = _events(_capture)
    assert DBT_PHASE_STARTED in events
    assert events.count(DBT_PHASE_COMPLETED) == 3  # deps, parse, compile


def test_parse_failure_emits_phase_failed_not_retryable(tmp_path, monkeypatch, _capture):
    project = _project(tmp_path)

    def runner(args, **kwargs):
        if args[1] == "parse":
            return _result(1, stderr="Parsing Error")
        return _result()

    with pytest.raises(DbtValidationError, match="dbt parse failed"):
        validate_dbt_project(project, "fabric", runner=runner)
    events = _events(_capture)
    assert DBT_PHASE_FAILED in events
    failed = [r for r in _capture.records if r.__dict__.get("event") == DBT_PHASE_FAILED]
    assert failed
    assert failed[0].__dict__.get("kairos.retryable") in (False, None)


def test_compile_environment_blocked_emits_environment_blocked_event(tmp_path, monkeypatch, _capture):
    project = _project(tmp_path)

    def runner(args, **kwargs):
        if args[1] == "compile":
            return _result(1, stderr="Authentication failed: could not connect")
        return _result()

    result = validate_dbt_project(project, "databricks", runner=runner)
    assert result.compile_status == "environment_blocked"
    events = _events(_capture)
    assert DBT_ENVIRONMENT_BLOCKED in events


def test_retryable_classification_is_not_set_for_genuine_artifact_failure(tmp_path, monkeypatch, _capture):
    """A genuine artifact failure must never be marked retryable."""
    project = _project(tmp_path)

    def runner(args, **kwargs):
        if args[1] == "compile":
            return _result(1, stderr="Compilation Error in model shipment")
        return _result()

    with pytest.raises(DbtValidationError, match="dbt compile failed"):
        validate_dbt_project(project, "fabric", runner=runner)
    failed = [r for r in _capture.records if r.__dict__.get("event") == DBT_PHASE_FAILED]
    assert failed
    # genuine artifact failure is NOT retryable
    assert failed[0].__dict__.get("kairos.retryable") in (False, None)


def test_phase_events_carry_phase_and_operation_attributes(tmp_path, monkeypatch, _capture):
    project = _project(tmp_path)
    from kairos_ontology.core.observability.context import (
        set_operation_context,
        OperationContext,
        reset_operation_context,
    )
    token = set_operation_context(OperationContext(operation_id="op-test"))
    try:
        validate_dbt_project(project, "fabric", runner=lambda *a, **k: _result())
    finally:
        reset_operation_context(token)
    completed = [r for r in _capture.records if r.__dict__.get("event") == DBT_PHASE_COMPLETED]
    assert completed
    rec = completed[0].__dict__
    assert rec.get("kairos.dbt.phase") in {"deps", "parse", "compile"}
