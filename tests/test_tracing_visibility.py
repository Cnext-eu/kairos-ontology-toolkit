# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Langfuse tracing must never fail silently (issue #694).

Degrading rather than failing is right -- observability must not break a run. The defect
was the *silence*: setting credentials is an explicit request for tracing, and having it
dropped is indistinguishable from Langfuse being broken. DD-195's own context named this
failure mode and fixed only the availability half.
"""

from __future__ import annotations

import builtins
import logging

import pytest

from kairos_ontology.cli.inspection import tracing_status
from kairos_ontology.core import tracing

_ENV = {
    "LANGFUSE_PUBLIC_KEY": "pk-test",
    "LANGFUSE_SECRET_KEY": "sk-test",
    "LANGFUSE_HOST": "https://langfuse.example",
}


@pytest.fixture
def configured(monkeypatch):
    for name, value in _ENV.items():
        monkeypatch.setenv(name, value)
    tracing.reset_tracing_client()
    yield
    tracing.reset_tracing_client()


@pytest.fixture
def unconfigured(monkeypatch):
    for name in (*_ENV, "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    tracing.reset_tracing_client()
    yield
    tracing.reset_tracing_client()


@pytest.fixture
def langfuse_missing(monkeypatch):
    """Make `import langfuse` fail, whether or not it is installed in this env."""
    real_import = builtins.__import__

    def _fake(name, *args, **kwargs):
        if name == "langfuse" or name.startswith("langfuse."):
            raise ImportError("No module named 'langfuse'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake)


class TestRuntimeReporting:
    def test_a_missing_package_warns_when_credentials_are_set(
        self, configured, langfuse_missing, caplog
    ):
        with caplog.at_level(logging.WARNING, logger=tracing.__name__):
            assert tracing.get_tracing_client() is None
        assert any(record.levelno == logging.WARNING for record in caplog.records)
        message = caplog.text
        assert "not installed" in message
        # uv-native remediation (DD-198): a bare `uv pip install` is undone by the next
        # sync, and the hub declares the extra (DD-195).
        assert "uv sync --extra langfuse" in message
        assert "uv pip install" not in message

    def test_an_unconfigured_hub_stays_silent(self, unconfigured, langfuse_missing, caplog):
        """The other half of the contract: no nagging where nothing was asked for."""
        with caplog.at_level(logging.INFO, logger=tracing.__name__):
            assert tracing.get_tracing_client() is None
        assert caplog.records == []


class TestCheckAiConfigReporting:
    """Surfaced before a long run, not only during one."""

    def test_reports_missing_dependency_when_configured(self, configured, langfuse_missing):
        status, detail = tracing_status()
        assert status == "missing_dependency"
        assert "uv sync --extra langfuse" in detail

    def test_reports_off_when_unconfigured(self, unconfigured):
        assert tracing_status()[0] == "off"

    def test_reports_ok_when_configured_and_installed(self, configured):
        pytest.importorskip("langfuse")
        assert tracing_status()[0] == "ok"
