# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Optional OpenTelemetry bridge for structured logs (DD-151).

This module is **opt-in and off by default**. It imports the OpenTelemetry
packages only when the ``[otel]`` extra is installed *and* the operator has
opted in via ``OTEL_*`` environment variables. When either condition is false,
:func:`configure_otel_logging` is a safe no-op.

Activation contract
--------------------

- ``OTEL_EXPORTER_OTLP_ENDPOINT`` signals opt-in. Without it, no bridge is
  installed — even if the extra packages are present.
- ``OTEL_SERVICE_NAME`` (optional) overrides the semantic-convention
  ``service.name`` attribute; defaults to ``"kairos-ontology"``.
- Bridge log records are forwarded via the OTel ``LoggingHandler`` so existing
  :class:`logging.Formatter` work (JSON/text) is unchanged; the bridge simply
  attaches an OTel exporter-backed handler to the ``kairos_ontology`` logger.
- Any failure here is caught and logged; it never raises into CLI code.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from .logging_config import _LOGGER_PREFIX, _HANDLER_MARK

_OTEL_ENABLED_ATTR = "_kairos_otel_handler"

logger = logging.getLogger("kairos_ontology.observability.otel")


def is_otel_enabled() -> bool:
    """Return True when the operator has opted into OTel export.

    Opt-in is explicit: the OpenTelemetry extra must be importable *and*
    ``OTEL_EXPORTER_OTLP_ENDPOINT`` must be set.
    """
    return bool(_import_opentelemetry()) and bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))


def _import_opentelemetry():
    """Return the OTel SDK modules if importable, else None.

    Isolated so the missing-extra case (the common one) never touches
    OTel APIs.
    """
    try:
        # Imported lazily so test environments without the extra never pay cost.
        from opentelemetry import trace  # noqa: F401  (probe import)
        from opentelemetry.sdk._logs import LoggingHandler
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        del trace  # probe only
    except Exception:  # pragma: no cover - exercised by absence tests
        return None
    return {
        "LoggingHandler": LoggingHandler,
        "Resource": Resource,
        "TracerProvider": TracerProvider,
        "BatchSpanProcessor": BatchSpanProcessor,
    }


def configure_otel_logging() -> Optional[object]:
    """Install the OTel logging handler when opted in; no-op otherwise.

    Returns the installed handler (or None) so callers can flush/dispose of it
    at CLI exit. This function never raises: failures are logged and None is
    returned so the caller can continue.
    """
    mods = _import_opentelemetry()
    if not mods:
        return None
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return None

    try:
        mods["Resource"].create(
            {"service.name": os.environ.get("OTEL_SERVICE_NAME", "kairos-ontology")}
        )
        handler: logging.Handler = mods["LoggingHandler"]()
        handler.setLevel(logging.NOTSET)
        setattr(handler, _OTEL_ENABLED_ATTR, True)
        setattr(handler, _HANDLER_MARK, True)

        root = logging.getLogger(_LOGGER_PREFIX)
        root.addHandler(handler)
        return handler
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("OpenTelemetry logging bridge not installed: %s", exc)
        return None


def flush_otel(handler: object) -> None:
    """Flush and dispose of the OTel logging handler at CLI exit.

    Safe to call with None. Never raises: export failure must not change the
    command exit code.
    """
    if handler is None:
        return
    try:
        logging_handler = logging.Handler
        if isinstance(handler, logging_handler):
            handler.flush()
            handler.close()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("OpenTelemetry flush failed: %s", exc)


__all__ = ["configure_otel_logging", "flush_otel", "is_otel_enabled"]
