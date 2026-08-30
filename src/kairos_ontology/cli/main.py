# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Root Click group and command registration for the Kairos toolkit."""

import logging
import sys
import traceback

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
from ..core.observability.otel import configure_otel_logging, flush_otel
from . import compile as _compile
from . import inspection as _inspection
from . import operations as _operations
from . import projections as _projections
from . import setup as _setup
from . import shared as _shared
from . import sources as _sources
from . import validation as _validation
from .compile import compile_cmd
from .emit_gold import emit_gold_cmd
from .package_powerbi_release import package_powerbi_release_cmd
from .decisions import decision
from .feedback import feedback
from .validation import (
    validate_dbt_cmd,
    validate_dbt_contracts_cmd,
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
    list_patterns_cmd,
)
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
        try:
            return super().invoke(ctx)
        except (
            click.exceptions.Exit,
            click.Abort,
            click.ClickException,
            KeyboardInterrupt,
            SystemExit,
        ):
            raise
        except Exception as exc:
            _log_unhandled_exception(exc)
            _teardown_observability(ctx)
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
@click.pass_context
def cli(ctx, verbose, debug, log_file, log_format):
    """Kairos Ontology Toolkit - Validation and projection tools for OWL/Turtle ontologies."""
    configure_logging(
        verbose=verbose, debug=debug, log_file=log_file, log_format=log_format
    )
    token = set_operation_context(OperationContext(operation_id=new_operation_id()))
    otel_handler = configure_otel_logging()
    ctx.obj = {"operation_context_token": token, "otel_handler": otel_handler}
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


def _teardown_observability(ctx) -> None:  # noqa: ANN001
    """Reset the operation context, flush the OTel bridge, and reset logging.

    Shared by the success path (``@cli.result_callback()``, invoked only when
    the command returns normally) and the failure path (``_KairosGroup.invoke``,
    which Click's result callback never sees) so the two cannot drift.
    Tolerates ``ctx.obj is None`` (root option parsing can fail before the
    group callback runs).
    """
    obj = ctx.obj or {}
    token = obj.get("operation_context_token")
    otel_handler = obj.get("otel_handler")
    if token is not None:
        reset_operation_context(token)
    flush_otel(otel_handler)
    # Restore logging defaults so a CLI-invoking test does not leave
    # propagate=False set and starve later tests' caplog of records. This also
    # closes the file handler (see reset_logging -> _strip_owned_handlers),
    # which is what flushes --log-file to disk; no separate flush loop needed.
    reset_logging()


@cli.result_callback()
@click.pass_context
def _reset_operation_context(ctx, _result, **_kwargs):  # noqa: ANN001
    """Reset the per-invocation operation context and flush OTel bridge after the command."""
    _teardown_observability(ctx)


def register_commands(group: click.Group) -> None:
    """Register the retained v5 command surface on *group*."""
    group.add_command(compile_cmd)
    group.add_command(emit_gold_cmd)
    group.add_command(package_powerbi_release_cmd)
    group.add_command(decision)
    group.add_command(feedback)
    group.add_command(validate_dbt_cmd)
    group.add_command(validate_dbt_contracts_cmd)
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
    group.add_command(scaffold_staging_cmd)
    group.add_command(scaffold_system_cmd)
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
    group.add_command(build_glossary_cmd)
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


register_commands(cli)
