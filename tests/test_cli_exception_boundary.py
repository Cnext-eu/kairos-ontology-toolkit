# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the DD-151 unhandled-exception boundary on the root CLI group (#295).

Before the boundary existed, an exception that escaped a command body produced
*zero* structured records: Click rendered a traceback to stderr and exited, and
the observability layer never saw the failure. These tests pin the record shape,
the exemption list, the teardown, and the exit codes.

Every test invokes the **root ``cli`` group**. ``CliRunner().invoke(subcommand)``
would bypass ``Group.invoke`` — where the boundary lives — entirely, and so would
assert nothing at all.
"""

from __future__ import annotations

import json
import logging

import click
import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.observability import reset_logging
from kairos_ontology.core.observability.context import (
    clear_operation_context,
    current_operation_id,
)

_BOOM_MESSAGE = "synthetic boundary failure"


@pytest.fixture(autouse=True)
def _clean_logging():
    reset_logging()
    clear_operation_context()
    yield
    reset_logging()
    clear_operation_context()


@pytest.fixture
def raising_command():
    """Temporarily register commands on the real root group.

    Registering on the real ``cli`` is the point: the boundary is a property of
    that group's ``invoke``, so a stand-in group would test a copy of the code
    rather than the shipped object.
    """
    added: list[str] = []

    def _register(name: str, callback):
        command = click.command(name=name)(callback)
        cli.add_command(command)
        added.append(name)
        return command

    yield _register

    for name in added:
        cli.commands.pop(name, None)


def _boom():
    raise RuntimeError(_BOOM_MESSAGE)


def _records(log_file) -> list[dict]:
    """Parse the NDJSON written by --log-file --log-format json."""
    if not log_file.exists():
        return []
    return [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line]


def _failure_records(log_file) -> list[dict]:
    return [r for r in _records(log_file) if r.get("event") == "kairos.cli.command.failed"]


def _invoke(args, log_file):
    return CliRunner().invoke(cli, ["--log-format", "json", "--log-file", str(log_file), *args])


# --------------------------------------------------------------------------- #
# The record itself
# --------------------------------------------------------------------------- #


def test_unhandled_exception_produces_exactly_one_structured_record(tmp_path, raising_command):
    raising_command("boom-once", _boom)
    log_file = tmp_path / "kairos.ndjson"

    result = _invoke(["boom-once"], log_file)

    assert result.exit_code == 1
    failures = _failure_records(log_file)
    assert len(failures) == 1, _records(log_file)


def test_record_carries_type_message_and_stacktrace(tmp_path, raising_command):
    raising_command("boom-fields", _boom)
    log_file = tmp_path / "kairos.ndjson"

    _invoke(["boom-fields"], log_file)

    record = _failure_records(log_file)[0]
    assert record["level"] == "ERROR"
    assert record["logger"] == "kairos_ontology.cli"
    assert record["exception.type"] == "RuntimeError"
    assert record["exception.message"] == _BOOM_MESSAGE
    assert "Traceback (most recent call last)" in record["exception.stacktrace"]
    assert "RuntimeError" in record["exception.stacktrace"]
    assert record["message"] == "unhandled exception: RuntimeError"


def test_record_shares_the_run_operation_id(tmp_path, raising_command):
    raising_command("boom-opid", _boom)
    log_file = tmp_path / "kairos.ndjson"

    _invoke(["boom-opid"], log_file)

    record = _failure_records(log_file)[0]
    assert record["kairos.operation.id"]


def test_stacktrace_is_redacted_like_any_other_field(tmp_path, raising_command):
    """The stacktrace must be an ``extra``, never ``exc_info=``.

    ``RedactionFilter`` skips ``exc_info``/``exc_text``, so an ``exc_info``-bound
    traceback would reach the file handler with secrets intact.
    """

    def _leaky():
        password = "hunter2-should-not-persist"  # noqa: F841 — must appear in the frame
        raise RuntimeError(f"connect failed: password={password}")

    raising_command("boom-secret", _leaky)
    log_file = tmp_path / "kairos.ndjson"

    _invoke(["boom-secret"], log_file)

    raw = log_file.read_text(encoding="utf-8")
    assert "hunter2-should-not-persist" not in raw
    assert "[REDACTED]" in raw


def test_exception_is_reraised_so_click_still_owns_the_exit_code(tmp_path, raising_command):
    raising_command("boom-exit", _boom)
    log_file = tmp_path / "kairos.ndjson"

    result = _invoke(["boom-exit"], log_file)

    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
    assert str(result.exception) == _BOOM_MESSAGE


# --------------------------------------------------------------------------- #
# The exemption list
# --------------------------------------------------------------------------- #


def test_subcommand_help_is_not_logged_as_a_failure(tmp_path, raising_command):
    """``--help`` raises ``click.exceptions.Exit``, whose MRO includes RuntimeError.

    A bare ``except Exception`` at the boundary would therefore log every single
    ``--help`` as a command failure. This is the regression that exemption guards.
    """
    raising_command("boom-help", _boom)
    log_file = tmp_path / "kairos.ndjson"

    result = _invoke(["boom-help", "--help"], log_file)

    assert result.exit_code == 0
    assert _failure_records(log_file) == []


def test_click_exit_mro_includes_runtimeerror():
    """Pins the reason the exemption exists, so a click upgrade that changes it is visible."""
    assert issubclass(click.exceptions.Exit, RuntimeError)


def test_click_exception_is_not_logged_as_unhandled(tmp_path, raising_command):
    """ClickException is the deliberate user-error channel — already reported once."""

    def _user_error():
        raise click.ClickException("bad input from the user")

    raising_command("boom-click", _user_error)
    log_file = tmp_path / "kairos.ndjson"

    result = _invoke(["boom-click"], log_file)

    assert result.exit_code == 1
    assert _failure_records(log_file) == []


def test_usage_error_is_not_logged_as_unhandled(tmp_path, raising_command):
    def _usage():
        raise click.UsageError("wrong usage")

    raising_command("boom-usage", _usage)
    log_file = tmp_path / "kairos.ndjson"

    result = _invoke(["boom-usage"], log_file)

    assert result.exit_code == 2
    assert _failure_records(log_file) == []


def test_systemexit_is_not_logged_as_unhandled(tmp_path, raising_command):
    """``raise SystemExit(1)`` is the toolkit's deliberate non-zero-exit channel.

    Commands using it have already echoed their own error message, so logging it
    here would double-report every ordinary validation failure.
    """

    def _exiting():
        raise SystemExit(1)

    raising_command("boom-sysexit", _exiting)
    log_file = tmp_path / "kairos.ndjson"

    result = _invoke(["boom-sysexit"], log_file)

    assert result.exit_code == 1
    assert _failure_records(log_file) == []


def test_abort_is_not_logged_as_unhandled(tmp_path, raising_command):
    def _aborting():
        raise click.Abort()

    raising_command("boom-abort", _aborting)
    log_file = tmp_path / "kairos.ndjson"

    result = _invoke(["boom-abort"], log_file)

    assert result.exit_code == 1
    assert _failure_records(log_file) == []


def test_keyboard_interrupt_is_not_logged_as_unhandled(tmp_path, raising_command):
    def _interrupted():
        raise KeyboardInterrupt()

    raising_command("boom-sigint", _interrupted)
    log_file = tmp_path / "kairos.ndjson"

    result = _invoke(["boom-sigint"], log_file)

    assert result.exit_code == 1
    assert _failure_records(log_file) == []


def test_successful_command_logs_no_failure_record(tmp_path, raising_command):
    raising_command("boom-not", lambda: click.echo("fine"))
    log_file = tmp_path / "kairos.ndjson"

    result = _invoke(["boom-not"], log_file)

    assert result.exit_code == 0
    assert _failure_records(log_file) == []


# --------------------------------------------------------------------------- #
# Teardown on the failure path
# --------------------------------------------------------------------------- #


def test_failure_path_resets_the_operation_context(tmp_path, raising_command):
    """Click runs ``@result_callback`` only on success, so the boundary must tear down."""
    raising_command("boom-teardown", _boom)
    log_file = tmp_path / "kairos.ndjson"

    _invoke(["boom-teardown"], log_file)

    assert current_operation_id() is None


def test_failure_path_resets_logging_handlers(tmp_path, raising_command):
    """Without reset_logging, propagate=False leaks into later tests' caplog."""
    raising_command("boom-handlers", _boom)
    log_file = tmp_path / "kairos.ndjson"

    _invoke(["boom-handlers"], log_file)

    logger = logging.getLogger("kairos_ontology")
    owned = [h for h in logger.handlers if getattr(h, "_kairos_observability", False)]
    assert owned == []
    assert logger.propagate is True


def test_failure_path_flushes_the_log_file_to_disk(tmp_path, raising_command):
    """The file handler is closed by reset_logging — that is what flushes it."""
    raising_command("boom-flush", _boom)
    log_file = tmp_path / "kairos.ndjson"

    _invoke(["boom-flush"], log_file)

    assert log_file.exists()
    assert log_file.read_text(encoding="utf-8").strip()


# --------------------------------------------------------------------------- #
# OntologyLoadError rendering (#587)
# --------------------------------------------------------------------------- #


_MISSING_PARTY = "Missing required import: https://kairos.eu/ref/party"
_MISSING_ASSET = "Missing required import: https://kairos.eu/ref/asset"
_UNRELATED_WARNING = "Import already loaded: https://kairos.eu/ref/base"


def _make_ontology_load_error():
    """Build a synthetic OntologyLoadError with diagnostics attached."""
    from rdflib import Graph

    from kairos_ontology.core.ontology_loader import (
        OntologyDiagnostic,
        OntologyLoadError,
        OntologyLoadResult,
        SemanticProfile,
    )

    result = OntologyLoadResult(
        graph=Graph(),
        manifest=(),
        diagnostics=(
            # The warning first: rendering must reorder missing_import to the top.
            OntologyDiagnostic(level="warning", code="duplicate_import", message=_UNRELATED_WARNING),
            OntologyDiagnostic(
                level="error",
                code="missing_import",
                message=_MISSING_PARTY,
                import_uri="https://kairos.eu/ref/party",
            ),
            OntologyDiagnostic(
                level="error",
                code="missing_import",
                message=_MISSING_ASSET,
                import_uri="https://kairos.eu/ref/asset",
            ),
        ),
        complete=False,
        closure_hash="0" * 64,
        profile=SemanticProfile.KAIROS_DESIGN,
    )
    return OntologyLoadError(
        "Ontology closure is incomplete; rerun with degraded=True only when partial "
        "semantics are explicitly acceptable.",
        result,
    )


def _raise_load_error():
    raise _make_ontology_load_error()


def test_ontology_load_error_renders_diagnostics_not_a_traceback(tmp_path, raising_command):
    raising_command("boom-closure", _raise_load_error)
    log_file = tmp_path / "kairos.ndjson"

    result = _invoke(["boom-closure"], log_file)

    assert result.exit_code == 1
    # The boundary converts to Exit, so the exception never escapes to become a
    # raw interpreter traceback (CliRunner records what would have escaped).
    # The DD-151 record on stderr still carries its redacted stacktrace *field*
    # by design, which is why this asserts on the exception, not on the text.
    assert isinstance(result.exception, SystemExit)
    assert "✗ Ontology closure is incomplete" in result.stderr
    assert _MISSING_PARTY in result.stderr
    assert _MISSING_ASSET in result.stderr
    assert _UNRELATED_WARNING in result.stderr
    # missing_import diagnostics render before the unrelated warning
    assert result.stderr.index(_MISSING_PARTY) < result.stderr.index(_UNRELATED_WARNING)
    assert result.stderr.index(_MISSING_ASSET) < result.stderr.index(_UNRELATED_WARNING)


def test_ontology_load_error_still_writes_the_dd151_record(tmp_path, raising_command):
    """Converting to Exit must not lose the failure record — Exit alone writes none."""
    raising_command("boom-closure-record", _raise_load_error)
    log_file = tmp_path / "kairos.ndjson"

    result = _invoke(["boom-closure-record"], log_file)

    assert result.exit_code == 1
    failures = _failure_records(log_file)
    assert len(failures) == 1, _records(log_file)
    assert failures[0]["exception.type"] == "OntologyLoadError"


def test_ontology_load_error_hints_at_missing_refmodels_package(
    tmp_path, raising_command, monkeypatch
):
    from kairos_ontology.cli import shared as cli_shared

    monkeypatch.setattr(cli_shared, "_read_refmodels_provenance", lambda: None)
    raising_command("boom-closure-hint", _raise_load_error)
    log_file = tmp_path / "kairos.ndjson"

    result = _invoke(["boom-closure-hint"], log_file)

    assert result.exit_code == 1
    assert (
        "2 required imports could not be resolved because kairos-ontology-referencemodels "
        "is not installed in this Python environment." in result.stderr
    )
    assert "try 'uv run kairos-ontology ...' instead" in result.stderr


def test_ontology_load_error_hint_absent_when_refmodels_installed(
    tmp_path, raising_command, monkeypatch
):
    from kairos_ontology.cli import shared as cli_shared

    monkeypatch.setattr(
        cli_shared,
        "_read_refmodels_provenance",
        lambda: {"ref": "1.2.3", "version": "1.2.3", "source": "pip"},
    )
    raising_command("boom-closure-nohint", _raise_load_error)
    log_file = tmp_path / "kairos.ndjson"

    result = _invoke(["boom-closure-nohint"], log_file)

    assert result.exit_code == 1
    assert _MISSING_PARTY in result.stderr
    assert "is not installed in this Python environment" not in result.stderr


def test_ontology_load_error_resets_the_operation_context(tmp_path, raising_command):
    """The new arm runs the same teardown as the generic one."""
    raising_command("boom-closure-teardown", _raise_load_error)
    log_file = tmp_path / "kairos.ndjson"

    _invoke(["boom-closure-teardown"], log_file)

    assert current_operation_id() is None


# --------------------------------------------------------------------------- #
# Text format
# --------------------------------------------------------------------------- #


def test_text_format_renders_the_stacktrace(tmp_path, raising_command):
    """TextFormatter only renders ``exc_info`` tracebacks, so it needs the extra."""
    raising_command("boom-text", _boom)
    log_file = tmp_path / "kairos.log"

    CliRunner().invoke(cli, ["--log-format", "text", "--log-file", str(log_file), "boom-text"])

    contents = log_file.read_text(encoding="utf-8")
    assert "unhandled exception: RuntimeError" in contents
    assert "Traceback (most recent call last)" in contents
