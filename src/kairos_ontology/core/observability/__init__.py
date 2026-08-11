# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Structured, OpenTelemetry-ready observability for the Kairos toolkit.

This subpackage owns the *configuration* boundary for logging and the optional
OpenTelemetry bridge. Library code elsewhere in ``kairos_ontology`` keeps using
``logging.getLogger(__name__)``; it must never install its own handlers. The
CLI entrypoint calls :func:`configure_logging` once per invocation.

Design notes:
- Core must never import MDM; observability is core, so it stays import-light
  and free of any toolkit-external hard dependency.
- OpenTelemetry is an opt-in ``[otel]`` extra. The bridge module imports it
  lazily and degrades to a no-op when the package is absent.
- Telemetry (logs/traces/metrics) must never change command exit codes or
  compiler/projection output bytes.
"""

from __future__ import annotations

from .context import OperationContext, current_operation_id, new_operation_id
from .logging_config import configure_logging, reset_logging

__all__ = [
    "OperationContext",
    "configure_logging",
    "current_operation_id",
    "new_operation_id",
    "reset_logging",
]
