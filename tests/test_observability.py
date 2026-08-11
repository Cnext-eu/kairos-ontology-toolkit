# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the structured logging + redaction foundation (DD-151).

Covers: idempotent configuration, JSON/text formatter shape, redaction of
sensitive keys and embedded secret substrings, operation-id propagation
through the context var, and that telemetry never escapes the
``kairos_ontology`` logger namespace (third-party loggers stay quiet).
"""

from __future__ import annotations

import io
import json
import logging

import pytest

from kairos_ontology.core.observability import (
    OperationContext,
    configure_logging,
    current_operation_id,
    new_operation_id,
    reset_logging,
)
from kairos_ontology.core.observability.context import (
    reset_operation_context,
    set_operation_context,
)
from kairos_ontology.core.observability.formatters import JsonFormatter, TextFormatter
from kairos_ontology.core.observability._redaction import RedactionFilter, redact_text
from kairos_ontology.core.observability.context import clear_operation_context


@pytest.fixture(autouse=True)
def _clean_logging():
    reset_logging()
    clear_operation_context()
    yield
    reset_logging()
    clear_operation_context()


def _emit(logger: logging.Logger, level: int, msg: str, **extra) -> str:
    handler = logging.StreamHandler(io.StringIO())
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())
    logger.addHandler(handler)
    logger.log(level, msg, extra=extra)
    return handler.stream.getvalue().strip()


def test_configure_logging_installs_console_handler_on_kairos_logger():
    logger = configure_logging(verbose=True)
    assert logger.name == "kairos_ontology"
    assert logger.handlers, "expected at least one owned handler"
    assert all(getattr(h, "_kairos_observability", False) for h in logger.handlers)
    assert logger.level == logging.INFO


def test_configure_logging_is_idempotent_single_handler():
    configure_logging(verbose=True)
    configure_logging(verbose=True)
    logger = logging.getLogger("kairos_ontology")
    owned = [h for h in logger.handlers if getattr(h, "_kairos_observability", False)]
    assert len(owned) == 1, f"expected exactly one owned handler, got {len(owned)}"


def test_configure_logging_debug_overrides_verbose():
    logger = configure_logging(verbose=True, debug=True)
    assert logger.level == logging.DEBUG


def test_configure_logging_rejects_unknown_format():
    with pytest.raises(ValueError):
        configure_logging(log_format="yaml")


def test_json_formatter_emits_stable_field_set():
    logger = logging.getLogger("kairos_ontology.subsystem")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    line = _emit(logger, logging.INFO, "dbt parse completed", event="kairos.dbt.parse.completed")
    payload = json.loads(line)
    for key in ("timestamp", "level", "logger", "message", "event"):
        assert key in payload, f"missing stable field {key!r}: {payload}"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "kairos_ontology.subsystem"
    assert payload["event"] == "kairos.dbt.parse.completed"


def test_json_formatter_includes_operation_id_from_context():
    token = set_operation_context(OperationContext(operation_id="op-123"))
    try:
        logger = logging.getLogger("kairos_ontology.x")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        line = _emit(logger, logging.INFO, "hello")
    finally:
        reset_operation_context(token)
    payload = json.loads(line)
    assert payload["kairos.operation.id"] == "op-123"


def test_text_formatter_is_human_readable_single_line():
    record = logging.LogRecord(
        name="kairos_ontology.x",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="model failed",
        args=None,
        exc_info=None,
    )
    record.event = "kairos.dbt.model.failed"
    out = TextFormatter().format(record)
    assert "WARNING" in out and "kairos_ontology.x" in out and "model failed" in out
    assert "event=kairos.dbt.model.failed" in out
    assert out.count("\n") == 0


def test_redaction_masks_sensitive_extra_keys():
    logger = logging.getLogger("kairos_ontology.secret")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    line = _emit(
        logger,
        logging.INFO,
        "profile loaded",
        token="super-secret-value",
        client_secret="abc",
        database_name="prod",
    )
    payload = json.loads(line)
    assert payload["token"] == "[REDACTED]"
    assert payload["client_secret"] == "[REDACTED]"
    assert payload["database_name"] == "prod"


def test_redaction_scrubs_secret_substrings_in_free_text():
    masked = redact_text("password=hunter2 token=abc123 Bearer xyz")
    assert "hunter2" not in masked
    assert "abc123" not in masked
    assert "Bearer" not in masked or "[REDACTED]" in masked


def test_redaction_never_drops_records():
    filt = RedactionFilter()
    record = logging.LogRecord(
        name="x", level=logging.INFO, pathname=__file__, lineno=1,
        msg="ok", args=None, exc_info=None,
    )
    record.token = "secret"
    assert filt.filter(record) is True
    assert record.token == "[REDACTED]"


def test_third_party_loggers_stay_quiet_by_default():
    # The toolkit root is left untouched; rdflib/jinja2 must not inherit handlers.
    configure_logging(verbose=True)
    foreign = logging.getLogger("rdflib")
    assert not foreign.handlers


def test_new_operation_id_is_unique_hex():
    a = new_operation_id()
    b = new_operation_id()
    assert a != b and len(a) == 32


def test_current_operation_id_none_outside_context():
    reset_logging()
    assert current_operation_id() is None


# --- Optional OpenTelemetry bridge (DD-151) -------------------------------


def test_otel_bridge_is_noop_without_env(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    from kairos_ontology.core.observability.otel import (
        configure_otel_logging,
        is_otel_enabled,
    )

    assert is_otel_enabled() is False
    handler = configure_otel_logging()
    assert handler is None


def test_otel_bridge_flush_is_safe_with_none():
    from kairos_ontology.core.observability.otel import flush_otel

    flush_otel(None)  # must not raise
