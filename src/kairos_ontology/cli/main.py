# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Root Click group and command registration for the Kairos toolkit."""

import logging
import sys
import traceback
from pathlib import Path

import click

from .. import __version__ as _toolkit_version
from .. import mdm as _mdm  # noqa: F401
from ..core.observability import (
    OperationContext,
    configure_logging,
    new_operation_id,
    reset_logging,
)
from ..core.observability.context import (
    reset_operation_context,
    set_operation_context,
)
from ..core.observability.otel import configure_otel, flush_otel
from ..core.observability import spans as _spans
from ..core.observability import events as _events
from . import run_log as _run_log
from ..core.gates import EnforcementMode as _EnforcementMode
from ..core.gates import reset_enforcement_state as _reset_enforcement_state
from ..core.gates import set_active_mode as _set_active_mode
from . import compile as _compile
from . import inspection as _inspection
from . import operations as _operations
from . import projections as _projections
from . import setup as _setup
from . import shared as _shared
from . import sources as _sources
from . import validation as _validation
from .compile import compile_cmd
from .emit_gold import apply_gold_connection_cmd, emit_gold_cmd, harvest_gold_cmd
from .package_powerbi_release import package_powerbi_release_cmd
from .decisions import decision
from .feedback import feedback
from .gates import gates_cmd
from .hook import hook_group
from .logs import logs_group
from .mcp_server import mcp_group
from .promote_transform import promote_transform_cmd
from .validation import (
    validate_dbt_cmd,
    validate_dbt_contracts_cmd,
    validate_source_bindings_cmd,
    validate,
    mdm_validate,
    catalog_test_cmd,
    validate_mapping_cmd,
    validate_silver_ext_cmd,
    suggest_shapes_cmd,
)
from .projections import (
    project,
    scaffold_mapping_cmd,
    scaffold_silver_ext_cmd,
)
from .scaffold_binding import scaffold_binding_cmd
from .scaffold_contract import scaffold_contract_cmd
from .scaffold_extensions import scaffold_extensions_cmd
from .scaffold_staging import scaffold_staging_cmd
from .scaffold_system import scaffold_system_cmd
from .setup import (
    init,
    migrate,
    new_repo,
    init_dataplatform,
    scaffold_domain,
)
from .sources import (
    import_tmdl,
    show_source_schema_cmd,
    import_source,
    source_privacy_cmd,
    import_flatfile,
    analyse_sources_cmd,
    profile_sources_cmd,
    generate_bindings_cmd,
    anchor_tables_cmd,
    draft_gap_decisions_cmd,
    audit_silver_samples_cmd,
    audit_column_coverage_cmd,
    propose_alignment_cmd,
    discovery_status_cmd,
    discovery_conformance,
    register_concept_cmd,
    source_disposition_group,
    build_glossary_cmd,
    read_document_cmd,
    list_patterns_cmd,
)
from .class_disposition import class_disposition_group
from .inspection import (
    resolve_ontology_cmd,
    show_class_inventory_cmd,
    list_class_properties_cmd,
    fit_report_cmd,
    inverse_scan_cmd,
    propose_relationships_cmd,
    plan_sources_cmd,
    explain_term_cmd,
    coverage_report_cmd,
    field_mapping_report_cmd,
    domain_coverage_cmd,
    draft_model_report_cmd,
    next_action_cmd,
    design_landscape_cmd,
    guard_scope_cmd,
    check_ai_config_cmd,
    alignment_report_cmd,
    suggest_anchor_cmd,
    suggest_type_cmd,
)
from .operations import (
    bump_hub,
    update,
    update_refmodels,
)
from .shared import (
    _ensure_utf8_stdio as _shared_ensure_utf8_stdio,
    _warn_if_no_skill_context,
    _warn_if_outside_venv,
    _warn_if_version_mismatch,
    extract_schema,
)


def __getattr__(name: str):
    """Preserve imports of implementation helpers from the historical module."""
    for module in (
        _shared,
        _compile,
        _inspection,
        _operations,
        _projections,
        _setup,
        _sources,
        _validation,
    ):
        try:
            return getattr(module, name)
        except AttributeError:
            continue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None


def _ensure_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 on Windows."""
    _shared_ensure_utf8_stdio()


_ensure_utf8_stdio()


class _KairosGroup(click.Group):
    """Root group with the DD-151 unhandled-exception boundary.

    Sits inside Group.invoke so `configure_logging` (the group callback) has
    already run, and outside the command body so Click's standalone_mode still
    owns every exit code and all stderr rendering. Covers both
    `kairos-ontology ...` and `python -m kairos_ontology` because both call
    this same object.
    """

    def invoke(self, ctx):
        # Every way out tears observability down once (DD-242): a refused or failing
        # command is the run whose summary matters most, and Click's own exits used to
        # skip it. The success path already tore down in the result callback.
        exit_code, early_exit = 1, False
        try:
            result = super().invoke(ctx)
            exit_code = 0
            return result
        except click.exceptions.Exit as exc:
            exit_code = exc.exit_code
            early_exit = exit_code == 0
            raise
        except click.ClickException as exc:
            exit_code = exc.exit_code
            raise
        except click.Abort:
            raise
        except KeyboardInterrupt:
            exit_code = 130
            raise
        except SystemExit as exc:
            exit_code = _system_exit_code(exc)
            raise
        except Exception as exc:
            _log_unhandled_exception(exc)
            _teardown_observability(ctx, exit_code=1)
            # OntologyLoadError carries structured diagnostics (missing_import et
            # al.) that explain the failure far better than its generic message;
            # render them instead of letting Click print a raw traceback (#587).
            # The sys.modules lookup keeps core.ontology_loader (rdflib) off this
            # path for unrelated failures: if the module was never imported, the
            # exception cannot be an OntologyLoadError.
            loader = sys.modules.get("kairos_ontology.core.ontology_loader")
            if loader is not None and isinstance(exc, loader.OntologyLoadError):
                _shared.render_ontology_load_failure(exc)
                # The DD-151 record is already written above — Exit alone would
                # skip it, which is why the conversion happens after the logging.
                raise click.exceptions.Exit(1)
            raise
        finally:
            _teardown_observability(ctx, exit_code=exit_code, early_exit=early_exit)

    def main(self, *args, **kwargs):
        # Issue #398: Click's Windows default expands an unquoted-by-the-time-it-
        # reaches-argv glob (e.g. --allow "*binding.yaml") against the filesystem
        # before our own option parsing ever sees it, turning one glob argument into
        # dozens of literal positional arguments. Every documented invocation in this
        # toolkit's skills passes globs as literal filter strings, never as file
        # arguments meant for shell-style expansion, so this expansion is never wanted.
        kwargs.setdefault("windows_expand_args", False)
        return super().main(*args, **kwargs)


@click.group(cls=_KairosGroup)
@click.version_option(version=_toolkit_version, package_name="kairos-ontology-toolkit")
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Emit INFO-level log output."
)
@click.option(
    "--debug", is_flag=True, default=False, help="Emit DEBUG-level log output."
)
@click.option(
    "--log-file", "log_file", default=None, help="Also write logs to this file."
)
@click.option(
    "--log-format",
    "log_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Structured log format for console and --log-file.",
)
@click.option(
    "--mode",
    "mode",
    type=click.Choice([m.value for m in _EnforcementMode], case_sensitive=False),
    default=None,
    help="Enforcement mode for this run (DD-234). 'interactive' (default) lets a human "
    "pass escape flags deliberately; 'autopilot' and 'ci' refuse the escapes that "
    "downgrade a result, because nobody is reading the warning. Also settable via "
    "KAIROS_MODE. Run 'kairos-ontology gates' to see what each mode allows.",
)
@click.pass_context
def cli(ctx, verbose, debug, log_file, log_format, mode):
    """Kairos Ontology Toolkit - Validation and projection tools for OWL/Turtle ontologies."""
    configure_logging(
        verbose=verbose, debug=debug, log_file=log_file, log_format=log_format
    )
    _events.reset_run_diagnostics()
    _run_log.reset(explicit_log_file=log_file is not None)
    # Before any subcommand parses its options, so an escape flag's parse-time callback
    # sees the resolved mode. Click invokes a group's callback ahead of building the
    # subcommand context, which is what makes that ordering hold.
    #
    # The reset matters as much as the assignment: the escape ledger is process-global
    # (see core.gates) and one invocation's escapes must not appear in the enforcement
    # block of an artifact a later invocation writes. One process is normally one
    # invocation; it is not when a test or an embedder drives the CLI in-process, which
    # is precisely where a stale ledger would be hardest to notice.
    _reset_enforcement_state()
    _set_active_mode(mode)
    operation_id = new_operation_id()
    token = set_operation_context(OperationContext(operation_id=operation_id))
    command = ctx.invoked_subcommand or ""
    otel_session = configure_otel(operation_id=operation_id, command=command)
    _spans.reset_spans()
    _spans.set_tracer(otel_session.tracer if otel_session is not None else None)
    _spans.open_run_span(command, **{"kairos.command": command})
    ctx.obj = {
        "operation_context_token": token,
        "otel_handler": otel_session,
        "command": command,
        "log_format": log_format,
    }
    _warn_if_outside_venv()
    _warn_if_version_mismatch()
    _warn_if_no_skill_context(ctx.invoked_subcommand)


def _log_unhandled_exception(exc: BaseException) -> None:
    """Log the single DD-151 record for an exception that escaped every command body.

    Deliberately does not pass ``exc_info=``: :class:`RedactionFilter` skips
    ``exc_info``/``exc_text`` (they are standard ``LogRecord`` attributes), so
    an ``exc_info``-bound traceback would reach both formatters unredacted.
    Building the stacktrace string ourselves and carrying it as a normal
    ``extra`` routes it through :func:`redact_text` like any other field, and
    keeps ``TextFormatter`` from rendering a second, unredacted traceback
    block (it only does that when ``record.exc_info`` is set).
    """
    logging.getLogger("kairos_ontology.cli").error(
        "unhandled exception: %s",
        type(exc).__name__,
        extra={
            "event": "kairos.cli.command.failed",
            "exception.type": type(exc).__name__,
            "exception.message": str(exc),
            "exception.stacktrace": "".join(traceback.format_exception(exc)),
        },
    )


def _system_exit_code(exc: SystemExit) -> int:
    """The process exit code a ``SystemExit`` stands for."""
    if exc.code is None:
        return 0
    return exc.code if isinstance(exc.code, int) else 1


def _teardown_observability(  # noqa: ANN001
    ctx, *, exit_code: int = 0, early_exit: bool = False
) -> None:
    """Write the run summary, end the run span, flush OTel, and reset logging.

    Shared by the success path (``@cli.result_callback()``, invoked only when
    the command returns normally) and every failure path (``_KairosGroup.invoke``,
    which Click's result callback never sees) so the two cannot drift. Runs once
    per invocation; a second call is a no-op. Tolerates ``ctx.obj is None`` (root
    option parsing can fail before the group callback runs).

    *early_exit* is a clean ``Exit(0)`` such as ``--help``: it ends the span but writes
    no summary unless the command had already reported something.
    """
    obj = ctx.obj
    if obj is None:
        reset_logging()
        return
    if obj.get("torn_down"):
        return
    obj["torn_down"] = True
    token = obj.get("operation_context_token")
    otel_session = obj.get("otel_handler")
    if obj.get("command") and not (early_exit and not _events.run_summary()):
        _events.log_run_summary(obj["command"], exit_code=exit_code)
    _spans.close_run_span(exit_code=exit_code)
    _spans.reset_spans()
    if token is not None:
        reset_operation_context(token)
    flush_otel(otel_session)
    # Restore logging defaults so a CLI-invoking test does not leave
    # propagate=False set and starve later tests' caplog of records. This also
    # closes the file handler (see reset_logging -> _strip_owned_handlers),
    # which is what flushes --log-file to disk; no separate flush loop needed.
    reset_logging()
    _announce_run_log(obj)


def _announce_run_log(obj: dict) -> None:
    """Name the run log a writing command just kept, as its last line (#1011).

    The log holds every diagnostic, grouped under the domain, product and gate that
    reported it, but nobody reads a file they do not know exists. On stderr, after the
    command's own output, so ``--format json`` keeps stdout a single document; not under
    ``--log-format json``, where stderr is a JSON-lines stream.
    """
    path = _run_log.started_path()
    if path is None or obj.get("log_format") == "json":
        return
    try:
        shown = path.relative_to(Path.cwd())
    except ValueError:
        shown = path
    click.echo(f"Run log: {shown}  (kairos-ontology logs show)", err=True)


@cli.result_callback()
@click.pass_context
def _reset_operation_context(ctx, _result, **_kwargs):  # noqa: ANN001
    """Reset the per-invocation operation context and flush OTel bridge after the command."""
    _teardown_observability(ctx)


def register_commands(group: click.Group) -> None:
    """Register the retained v5 command surface on *group*."""
    group.add_command(compile_cmd)
    group.add_command(emit_gold_cmd)
    group.add_command(apply_gold_connection_cmd)
    group.add_command(harvest_gold_cmd)
    group.add_command(package_powerbi_release_cmd)
    group.add_command(decision)
    group.add_command(gates_cmd)
    group.add_command(logs_group)
    group.add_command(mcp_group)
    group.add_command(hook_group)
    group.add_command(feedback)
    group.add_command(validate_dbt_cmd)
    group.add_command(validate_dbt_contracts_cmd)
    group.add_command(validate_source_bindings_cmd)
    group.add_command(validate)
    group.add_command(mdm_validate)
    group.add_command(catalog_test_cmd)
    group.add_command(validate_mapping_cmd)
    group.add_command(validate_silver_ext_cmd)
    group.add_command(suggest_shapes_cmd)
    group.add_command(project)
    group.add_command(scaffold_mapping_cmd)
    group.add_command(scaffold_silver_ext_cmd)
    group.add_command(scaffold_binding_cmd)
    group.add_command(scaffold_contract_cmd)
    group.add_command(scaffold_extensions_cmd)
    group.add_command(scaffold_staging_cmd)
    group.add_command(scaffold_system_cmd)
    group.add_command(promote_transform_cmd)
    group.add_command(init)
    group.add_command(migrate)
    group.add_command(new_repo)
    group.add_command(init_dataplatform)
    group.add_command(scaffold_domain)
    group.add_command(import_tmdl)
    group.add_command(show_source_schema_cmd)
    group.add_command(extract_schema)
    group.add_command(import_source)
    group.add_command(source_privacy_cmd)
    group.add_command(import_flatfile)
    group.add_command(analyse_sources_cmd)
    group.add_command(profile_sources_cmd)
    group.add_command(generate_bindings_cmd)
    group.add_command(anchor_tables_cmd)
    group.add_command(draft_gap_decisions_cmd)
    group.add_command(audit_silver_samples_cmd)
    group.add_command(audit_column_coverage_cmd)
    group.add_command(propose_alignment_cmd)
    group.add_command(discovery_status_cmd)
    group.add_command(discovery_conformance)
    group.add_command(register_concept_cmd)
    group.add_command(source_disposition_group)
    group.add_command(class_disposition_group)
    group.add_command(build_glossary_cmd)
    group.add_command(read_document_cmd)
    group.add_command(list_patterns_cmd)
    group.add_command(resolve_ontology_cmd)
    group.add_command(show_class_inventory_cmd)
    group.add_command(list_class_properties_cmd)
    group.add_command(fit_report_cmd)
    group.add_command(inverse_scan_cmd)
    group.add_command(propose_relationships_cmd)
    group.add_command(plan_sources_cmd)
    group.add_command(explain_term_cmd)
    group.add_command(coverage_report_cmd)
    group.add_command(field_mapping_report_cmd)
    group.add_command(domain_coverage_cmd)
    group.add_command(draft_model_report_cmd)
    group.add_command(next_action_cmd)
    group.add_command(design_landscape_cmd)
    group.add_command(guard_scope_cmd)
    group.add_command(check_ai_config_cmd)
    group.add_command(alignment_report_cmd)
    group.add_command(suggest_anchor_cmd)
    group.add_command(suggest_type_cmd)
    group.add_command(update)
    group.add_command(update_refmodels)
    group.add_command(bump_hub)


register_commands(cli)
