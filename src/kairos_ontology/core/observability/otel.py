# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Optional OpenTelemetry export of a run's spans and log records (DD-151, DD-242).

This module is **opt-in and off by default**. It imports the OpenTelemetry
packages only when the operator has opted in via ``OTEL_EXPORTER_OTLP_ENDPOINT``
*and* the ``[otel]`` extra is installed. When either condition is false,
:func:`configure_otel` is a safe no-op and nothing from OpenTelemetry is imported.

Activation contract
--------------------

- ``OTEL_EXPORTER_OTLP_ENDPOINT`` signals opt-in. Without it, nothing is installed,
  even if the extra packages are present. The exporters read it (and the other
  standard ``OTEL_EXPORTER_OTLP_*`` variables) themselves.
- ``OTEL_EXPORTER_OTLP_PROTOCOL`` picks ``http/protobuf`` (default) or ``grpc``.
- ``OTEL_SERVICE_NAME`` (optional) overrides ``service.name``; defaults to
  ``"kairos-ontology"``.
- One run is one trace, and its trace id **is** the run's operation id: the
  ``kairos.operation.id`` of every log record finds the trace with no extra join.
- Spans come from :mod:`.spans`; log records reach the collector through an OTel
  ``LoggingHandler`` with the same redaction filter as every other handler.
- Any failure here is caught and logged; it never raises into CLI code and never
  changes an exit code.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import warnings
from dataclasses import dataclass
from typing import Any, Optional

from ._redaction import RedactionFilter
from .logging_config import _HANDLER_MARK, _LOGGER_PREFIX

_OTEL_ENABLED_ATTR = "_kairos_otel_handler"
ENV_ENDPOINT = "OTEL_EXPORTER_OTLP_ENDPOINT"
ENV_PROTOCOL = "OTEL_EXPORTER_OTLP_PROTOCOL"

logger = logging.getLogger("kairos_ontology.observability.otel")


@dataclass(slots=True)
class OtelSession:
    """The providers and handler of one run, torn down by :func:`flush_otel`."""

    tracer_provider: Any
    logger_provider: Any
    handler: logging.Handler
    tracer: Any


def is_otel_enabled() -> bool:
    """Return True when the operator has opted into OTel export.

    Opt-in is explicit: ``OTEL_EXPORTER_OTLP_ENDPOINT`` must be set *and* the
    OpenTelemetry extra must be importable. The variable is read first, so a run
    without it never imports OpenTelemetry.
    """
    return bool(os.environ.get(ENV_ENDPOINT)) and _import_opentelemetry() is not None


def _import_opentelemetry():
    """Return the OTel SDK modules if importable, else None."""
    try:
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.id_generator import RandomIdGenerator
    except Exception:  # pragma: no cover - exercised by absence tests
        return None
    return {
        "LoggerProvider": LoggerProvider,
        "LoggingHandler": LoggingHandler,
        "BatchLogRecordProcessor": BatchLogRecordProcessor,
        "Resource": Resource,
        "TracerProvider": TracerProvider,
        "BatchSpanProcessor": BatchSpanProcessor,
        "RandomIdGenerator": RandomIdGenerator,
    }


def _processors() -> tuple[Any, Any]:
    """The span and log-record processors: batched OTLP exporters.

    One function, so a test can replace it with in-memory exporters.
    """
    mods = _import_opentelemetry()
    if os.environ.get(ENV_PROTOCOL, "").strip().lower() == "grpc":
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    else:
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    return (
        mods["BatchSpanProcessor"](OTLPSpanExporter()),
        mods["BatchLogRecordProcessor"](OTLPLogExporter()),
    )


def _flatten_for_otel(record: logging.LogRecord) -> logging.LogRecord:
    """A copy of *record* whose dict/list extras are JSON strings.

    An OTel attribute is a primitive or a list of them, so a nested extra such as
    ``kairos.summary`` would be dropped. Returning a copy keeps the change local to this
    handler: the run log after it still receives the structured value.
    """
    nested = {
        key: value
        for key, value in vars(record).items()
        if isinstance(value, (dict, list, tuple)) and key not in {"args"}
    }
    if not nested:
        return record
    flat = copy.copy(record)
    for key, value in nested.items():
        setattr(flat, key, json.dumps(value, sort_keys=True, default=str))
    return flat


def configure_otel(*, operation_id: str | None = None, command: str = "") -> Optional[OtelSession]:
    """Install the OTel tracer and log handler when opted in; None otherwise.

    The trace id of every span is *operation_id*. Never raises: a failure is logged
    at DEBUG and the run continues without export.
    """
    if not os.environ.get(ENV_ENDPOINT):
        return None
    mods = _import_opentelemetry()
    if not mods:
        return None
    try:
        from ... import __version__

        resource = mods["Resource"].create(
            {
                "service.name": os.environ.get("OTEL_SERVICE_NAME", "kairos-ontology"),
                "service.version": __version__,
                **({"kairos.command": command} if command else {}),
            }
        )

        class _OperationIdGenerator(mods["RandomIdGenerator"]):
            def generate_trace_id(self) -> int:
                try:
                    value = int(operation_id or "", 16)
                except ValueError:
                    value = 0
                return value if 0 < value < 2**128 else super().generate_trace_id()

        span_processor, log_processor = _processors()
        tracer_provider = mods["TracerProvider"](
            resource=resource, id_generator=_OperationIdGenerator(), shutdown_on_exit=False
        )
        tracer_provider.add_span_processor(span_processor)
        logger_provider = mods["LoggerProvider"](resource=resource, shutdown_on_exit=False)
        logger_provider.add_log_record_processor(log_processor)
        with warnings.catch_warnings():
            # 1.4x deprecates the SDK handler in favour of an instrumentation package we
            # do not depend on; it still works, and the warning is noise to a user.
            warnings.simplefilter("ignore", DeprecationWarning)
            handler: logging.Handler = mods["LoggingHandler"](
                level=logging.INFO, logger_provider=logger_provider
            )
        # Redact before anything leaves the machine, then flatten for OTel only.
        handler.addFilter(RedactionFilter())
        handler.addFilter(_flatten_for_otel)
        setattr(handler, _OTEL_ENABLED_ATTR, True)
        setattr(handler, _HANDLER_MARK, True)

        root = logging.getLogger(_LOGGER_PREFIX)
        root.addHandler(handler)
        # INFO diagnostics must reach the collector even on a WARNING console; the
        # console handler keeps its own level.
        root.setLevel(min(root.level or logging.WARNING, logging.INFO))
        return OtelSession(
            tracer_provider=tracer_provider,
            logger_provider=logger_provider,
            handler=handler,
            tracer=tracer_provider.get_tracer("kairos_ontology"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("OpenTelemetry export not installed: %s", exc)
        return None


def configure_otel_logging() -> Optional[OtelSession]:
    """Backwards-compatible name for :func:`configure_otel`."""
    from .context import current_operation_id

    return configure_otel(operation_id=current_operation_id())


def flush_otel(session: object) -> None:
    """Export what is buffered and shut the providers down at CLI exit.

    Safe to call with None. Never raises: export failure must not change the
    command exit code.
    """
    if session is None:
        return
    try:
        if isinstance(session, OtelSession):
            session.tracer_provider.force_flush()
            session.tracer_provider.shutdown()
            session.logger_provider.force_flush()
            session.logger_provider.shutdown()
            logging.getLogger(_LOGGER_PREFIX).removeHandler(session.handler)
        elif isinstance(session, logging.Handler):
            session.flush()
            session.close()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("OpenTelemetry flush failed: %s", exc)


__all__ = [
    "OtelSession",
    "configure_otel",
    "configure_otel_logging",
    "flush_otel",
    "is_otel_enabled",
]
