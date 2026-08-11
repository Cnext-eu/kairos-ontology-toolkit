# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for projection-step structured events (DD-151)."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from kairos_ontology.core.observability.events import (
    PROJECTION_STEP_COMPLETED,
    PROJECTION_STEP_FAILED,
    PROJECTION_STEP_STARTED,
)
from kairos_ontology.core.observability.logging_config import reset_logging


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


@pytest.fixture(autouse=True)
def _clean():
    reset_logging()
    yield
    reset_logging()


def _event_records(cap: _Capture, event: str) -> list[logging.LogRecord]:
    return [r for r in cap.records if r.__dict__.get("event") == event]


def test_mermaid_render_emits_skipped_when_no_mmdc(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "kairos_ontology.core.projections.medallion_silver_projector.shutil.which",
        lambda _name: None,
    )
    from kairos_ontology.core.projections.medallion_silver_projector import render_mermaid_svg

    mmd = tmp_path / "diagram.mmd"
    mmd.write_text("graph TD\n  A --> B", encoding="utf-8")
    result = render_mermaid_svg(mmd)
    assert result is None


def test_mermaid_render_emits_completed_on_success(tmp_path: Path, monkeypatch, _capture):
    def _fake_run(*args, **kwargs):
        class _R:
            returncode = 0
            stdout = b""
            stderr = b""

        return _R()

    monkeypatch.setattr(
        "kairos_ontology.core.projections.medallion_silver_projector.shutil.which",
        lambda _name: "/fake/mmdc",
    )
    monkeypatch.setattr(
        "kairos_ontology.core.projections.medallion_silver_projector.subprocess.run",
        _fake_run,
    )
    from kairos_ontology.core.projections.medallion_silver_projector import render_mermaid_svg

    mmd = tmp_path / "diagram.mmd"
    mmd.write_text("graph TD\n  A --> B", encoding="utf-8")
    result = render_mermaid_svg(mmd)
    assert result == mmd.with_suffix(".svg")
    completed = _event_records(_capture, PROJECTION_STEP_COMPLETED)
    assert completed, "expected PROJECTION_STEP_COMPLETED event"
    rec = completed[0].__dict__
    assert rec.get("kairos.projection.step") == "mermaid_render"
    assert rec.get("duration_ms") is not None
    assert _event_records(_capture, PROJECTION_STEP_STARTED), "expected PROJECTION_STEP_STARTED event"


def test_mermaid_render_emits_failed_and_returns_none(tmp_path: Path, monkeypatch, _capture):
    def _boom(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["mmdc"], stderr=b"boom")

    monkeypatch.setattr(
        "kairos_ontology.core.projections.medallion_silver_projector.shutil.which",
        lambda _name: "/fake/mmdc",
    )
    monkeypatch.setattr(
        "kairos_ontology.core.projections.medallion_silver_projector.subprocess.run",
        _boom,
    )
    from kairos_ontology.core.projections.medallion_silver_projector import render_mermaid_svg

    mmd = tmp_path / "diagram.mmd"
    mmd.write_text("graph TD\n  A --> B", encoding="utf-8")
    result = render_mermaid_svg(mmd)
    assert result is None, "failed render must remain non-fatal"
    failed = _event_records(_capture, PROJECTION_STEP_FAILED)
    assert failed, "expected PROJECTION_STEP_FAILED event"
    rec = failed[0].__dict__
    assert rec.get("kairos.projection.step") == "mermaid_render"
    assert rec.get("error_type") == "CalledProcessError"
