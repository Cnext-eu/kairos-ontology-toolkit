# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Central logging configuration for the Kairos CLI.

:func:`configure_logging` is called once per CLI invocation from the root Click
group. It installs a single console handler on the ``kairos_ontology`` logger
plus an optional file handler, attaches the redaction filter, and sets the
level. Library code never calls this.

Re-entrancy: calling :func:`configure_logging` again replaces the handlers it
previously installed (identified by a marker attribute) so a CLI invoked twice
in the same process — or tests that reconfigure logging — does not duplicate
handlers. Data the CLI emits via :func:`logging` is telemetry only; it must
never affect compiler/projection artifacts or command exit codes.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Final

from ._redaction import RedactionFilter
from .formatters import JsonFormatter, TextFormatter

#: Logger name prefix that owns the handlers. The root is left untouched so
#: third-party loggers (rdflib, jinja2, requests) stay quiet by default.
_LOGGER_PREFIX: Final[str] = "kairos_ontology"

#: Attribute stamped on handlers this module owns so reconfiguration can find
#: and remove them without touching foreign handlers (e.g. pytest's).
_HANDLER_MARK: Final[str] = "_kairos_observability"

_VALID_FORMATS: Final[frozenset[str]] = frozenset({"text", "json"})


def _resolve_level(verbose: bool, debug: bool) -> int:
    if debug:
        return logging.DEBUG
    if verbose:
        return logging.INFO
    return logging.WARNING


def _make_formatter(log_format: str) -> logging.Formatter:
    if log_format == "json":
        return JsonFormatter()
    return TextFormatter()


def _strip_owned_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            logger.removeHandler(handler)
            handler.close()


def configure_logging(
    *,
    verbose: bool = False,
    debug: bool = False,
    log_file: str | Path | None = None,
    log_format: str = "text",
) -> logging.Logger:
    """Install console (and optional file) handlers on the ``kairos_ontology`` logger.

    Parameters are the CLI options. ``log_format`` is ``"text"`` (default) or
    ``"json"``. Returns the configured logger so callers can attach tests or
    extra handlers if needed.
    """
    if log_format not in _VALID_FORMATS:
        raise ValueError(f"unsupported log_format {log_format!r}; choose text or json")

    level = _resolve_level(verbose=verbose, debug=debug)
    formatter = _make_formatter(log_format)
    redaction = RedactionFilter()

    logger = logging.getLogger(_LOGGER_PREFIX)
    _strip_owned_handlers(logger)
    logger.setLevel(level)
    logger.propagate = False

    console = logging.StreamHandler(stream=sys.stderr)
    console.setLevel(level)
    console.setFormatter(formatter)
    console.addFilter(redaction)
    setattr(console, _HANDLER_MARK, True)
    logger.addHandler(console)

    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redaction)
        setattr(file_handler, _HANDLER_MARK, True)
        logger.addHandler(file_handler)

    return logger


def reset_logging() -> None:
    """Remove all handlers installed by :func:`configure_logging` and restore
    the ``kairos_ontology`` logger to its library default (propagation on, no
    owned handlers). Intended for tests that want a clean slate between cases
    so a CLI-invoking test cannot leave ``propagate = False`` set, which would
    starve ``pytest``'s ``caplog`` (root-based) of records from later tests.
    """
    logger = logging.getLogger(_LOGGER_PREFIX)
    _strip_owned_handlers(logger)
    logger.propagate = True


__all__ = ["configure_logging", "reset_logging"]
