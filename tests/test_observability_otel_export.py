# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""With OTEL_EXPORTER_OTLP_ENDPOINT set, one run is one trace (#1011, DD-242).

The DD-151 bridge installed a ``LoggingHandler`` with no provider, so nothing was
exported, and there were no spans at all. The export now builds real providers; these
tests swap the OTLP exporters for in-memory ones.
"""

from __future__ import annotations

import json
import logging
import shutil
import warnings
from pathlib import Path

import pytest
from click.testing import CliRunner

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from kairos_ontology.cli.main import cli  # noqa: E402
from kairos_ontology.core.observability import configure_logging, otel, spans  # noqa: E402

_PRODUCT_HUB = Path(__file__).parent / "scenarios" / "v5-product-hub"
_BILLING_CODE = "relationship.external-reference-key-unverified"
_OPERATION = "0123456789abcdef0123456789abcdef"


def _log_exporter():
    from opentelemetry.sdk._logs import export

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        # InMemoryLogRecordExporter is 1.44-only; the old name works back to 1.28.
        return export.InMemoryLogExporter()


def _record(item):
    """The SDK log record, whether the exporter hands back a wrapper or not."""
    return getattr(item, "log_record", item)


@pytest.fixture
def exporters(monkeypatch):
    span_exporter, log_exporter = InMemorySpanExporter(), _log_exporter()
    shutdowns: list[str] = []
    span_shutdown, log_shutdown = span_exporter.shutdown, log_exporter.shutdown

    def record_span_shutdown():
        shutdowns.append("spans")
        span_shutdown()

    def record_log_shutdown():
        shutdowns.append("logs")
        log_shutdown()

    span_exporter.shutdown = record_span_shutdown
    log_exporter.shutdown = record_log_shutdown
    monkeypatch.setattr(
        otel,
        "_processors",
        lambda: (SimpleSpanProcessor(span_exporter), SimpleLogRecordProcessor(log_exporter)),
    )
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.invalid:4318")
    spans.reset_spans()
    yield span_exporter, log_exporter, shutdowns
    spans.reset_spans()


@pytest.fixture
def hub(tmp_path, monkeypatch):
    root = tmp_path / "hub"
    shutil.copytree(_PRODUCT_HUB, root)
    monkeypatch.chdir(root)
    monkeypatch.delenv("KAIROS_RUN_LOG", raising=False)
    return root


class TestCommandTrace:
    def _run(self, tmp_path):
        log = tmp_path / "run.jsonl"
        result = CliRunner().invoke(
            cli,
            ["--log-file", str(log), "--log-format", "json", "compile", "billing", "--check"],
            env={"KAIROS_SKILL_CONTEXT": "1"},
        )
        assert result.exit_code == 0, result.output
        records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        return records

    def test_one_trace_whose_id_is_the_operation_id(self, hub, tmp_path, exporters):
        span_exporter, _logs, _shutdowns = exporters
        records = self._run(tmp_path)
        operation = records[0]["kairos.operation.id"]
        finished = span_exporter.get_finished_spans()
        assert finished
        assert {format(span.context.trace_id, "032x") for span in finished} == {operation}

    def test_spans_nest_run_domain_gate(self, hub, tmp_path, exporters):
        span_exporter, _logs, _shutdowns = exporters
        self._run(tmp_path)
        finished = span_exporter.get_finished_spans()
        by_key = {(span.name, span.attributes["kairos.span.name"]): span for span in finished}
        run = by_key[("kairos.run", "compile")]
        domain = by_key[("kairos.domain", "billing")]
        gate = by_key[("kairos.gate", "compile")]
        assert run.parent is None
        assert domain.parent.span_id == run.context.span_id
        assert gate.parent.span_id == domain.context.span_id
        assert gate.attributes["kairos.diagnostics.info"] == 1

    def test_diagnostics_are_span_events(self, hub, tmp_path, exporters):
        span_exporter, _logs, _shutdowns = exporters
        self._run(tmp_path)
        (gate,) = [
            span
            for span in span_exporter.get_finished_spans()
            if span.attributes.get("kairos.span.name") == "compile" and span.name == "kairos.gate"
        ]
        (event,) = [event for event in gate.events if event.name == "kairos.diagnostic"]
        assert event.attributes["diagnostic.code"] == _BILLING_CODE
        assert event.attributes["diagnostic.severity"] == "info"

    def test_log_span_ids_match_the_trace(self, hub, tmp_path, exporters):
        span_exporter, _logs, _shutdowns = exporters
        records = self._run(tmp_path)
        exported = {
            format(span.context.span_id, "016x") for span in span_exporter.get_finished_spans()
        }
        logged = {r["span.id"] for r in records if r.get("event") == spans.SPAN_COMPLETED}
        assert logged == exported

    def test_log_records_carry_the_trace_context(self, hub, tmp_path, exporters):
        span_exporter, log_exporter, _shutdowns = exporters
        records = self._run(tmp_path)
        operation = int(records[0]["kairos.operation.id"], 16)
        exported = [_record(item) for item in log_exporter.get_finished_logs()]
        (diagnostic,) = [
            record
            for record in exported
            if (record.attributes or {}).get("event") == "kairos.diagnostic.reported"
        ]
        assert diagnostic.trace_id == operation
        gate = next(
            span
            for span in span_exporter.get_finished_spans()
            if span.name == "kairos.gate" and span.attributes["kairos.span.name"] == "compile"
        )
        assert diagnostic.span_id == gate.context.span_id
        (summary,) = [
            record
            for record in exported
            if (record.attributes or {}).get("event") == "kairos.run.summary"
        ]
        assert isinstance(summary.attributes["kairos.summary"], str)
        assert json.loads(summary.attributes["kairos.summary"])["billing"]["code"] == {
            _BILLING_CODE: 1
        }

    def test_the_run_log_keeps_the_structured_summary(self, hub, tmp_path, exporters):
        """Flattening for OTel happens on a copy: the file after it still gets the dict."""
        records = self._run(tmp_path)
        (summary,) = [r for r in records if r.get("event") == "kairos.run.summary"]
        assert isinstance(summary["kairos.summary"], dict)

    def test_the_providers_are_shut_down(self, hub, tmp_path, exporters):
        _spans, _logs, shutdowns = exporters
        self._run(tmp_path)
        assert sorted(shutdowns) == ["logs", "spans"]


class TestSession:
    def test_exported_records_are_redacted(self, exporters):
        _spans, log_exporter, _shutdowns = exporters
        configure_logging()
        session = otel.configure_otel(operation_id=_OPERATION, command="compile")
        assert session is not None
        logging.getLogger("kairos_ontology.test").info(
            "connecting with password=hunter2", extra={"api_key": "s3cret"}
        )
        otel.flush_otel(session)
        (record,) = [_record(item) for item in log_exporter.get_finished_logs()]
        assert "hunter2" not in str(record.body)
        assert record.attributes["api_key"] != "s3cret"

    def test_info_records_reach_the_collector_on_a_warning_console(self, exporters):
        _spans, log_exporter, _shutdowns = exporters
        configure_logging()  # console at WARNING
        session = otel.configure_otel(operation_id=_OPERATION)
        logging.getLogger("kairos_ontology.test").info("an info diagnostic")
        otel.flush_otel(session)
        assert [str(_record(item).body) for item in log_exporter.get_finished_logs()] == [
            "an info diagnostic"
        ]

    def test_a_malformed_operation_id_falls_back_to_a_random_trace(self, exporters):
        span_exporter, _logs, _shutdowns = exporters
        session = otel.configure_otel(operation_id="not-hex")
        spans.set_tracer(session.tracer)
        with spans.task_span("stage", "emit"):
            pass
        otel.flush_otel(session)
        (span,) = span_exporter.get_finished_spans()
        assert span.context.trace_id != 0


class TestOptIn:
    def test_without_the_endpoint_nothing_is_imported(self, monkeypatch):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

        def must_not_import():
            raise AssertionError("OpenTelemetry imported without the endpoint set")

        monkeypatch.setattr(otel, "_import_opentelemetry", must_not_import)
        assert otel.configure_otel(operation_id=_OPERATION) is None
        assert otel.is_otel_enabled() is False

    def test_flush_accepts_none(self):
        otel.flush_otel(None)
