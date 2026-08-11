# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Root Click group and command registration for the Kairos toolkit."""

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
from .decisions import decision
from .validation import (
    validate_dbt_cmd,
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
from .scaffold_system import scaffold_system_cmd
from .setup import (
    init,
    migrate,
    new_repo,
    init_dataplatform,
)
from .sources import (
    import_tmdl,
    show_source_schema_cmd,
    import_source,
    source_privacy_cmd,
    import_flatfile,
    analyse_sources_cmd,
    audit_silver_samples_cmd,
    propose_alignment_cmd,
    discovery_status_cmd,
    discovery_conformance,
    build_glossary_cmd,
    list_patterns_cmd,
)
from .inspection import (
    resolve_ontology_cmd,
    show_class_inventory_cmd,
    list_class_properties_cmd,
    fit_report_cmd,
    explain_term_cmd,
    coverage_report_cmd,
    generate_inventory_cmd,
    check_inventory_cmd,
    draft_model_report_cmd,
    next_action_cmd,
    design_landscape_cmd,
    guard_scope_cmd,
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


@click.group()
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


@cli.result_callback()
@click.pass_context
def _reset_operation_context(ctx, _result, **_kwargs):  # noqa: ANN001
    """Reset the per-invocation operation context and flush OTel bridge after the command."""
    token = (ctx.obj or {}).get("operation_context_token") if ctx.obj else None
    otel_handler = (ctx.obj or {}).get("otel_handler") if ctx.obj else None
    if token is not None:
        reset_operation_context(token)
    flush_otel(otel_handler)
    # Restore logging defaults so a CLI-invoking test does not leave
    # propagate=False set and starve later tests' caplog of records.
    reset_logging()


def register_commands(group: click.Group) -> None:
    """Register the retained v5 command surface on *group*."""
    group.add_command(compile_cmd)
    group.add_command(decision)
    group.add_command(validate_dbt_cmd)
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
    group.add_command(scaffold_system_cmd)
    group.add_command(init)
    group.add_command(migrate)
    group.add_command(new_repo)
    group.add_command(init_dataplatform)
    group.add_command(import_tmdl)
    group.add_command(show_source_schema_cmd)
    group.add_command(extract_schema)
    group.add_command(import_source)
    group.add_command(source_privacy_cmd)
    group.add_command(import_flatfile)
    group.add_command(analyse_sources_cmd)
    group.add_command(audit_silver_samples_cmd)
    group.add_command(propose_alignment_cmd)
    group.add_command(discovery_status_cmd)
    group.add_command(discovery_conformance)
    group.add_command(build_glossary_cmd)
    group.add_command(list_patterns_cmd)
    group.add_command(resolve_ontology_cmd)
    group.add_command(show_class_inventory_cmd)
    group.add_command(list_class_properties_cmd)
    group.add_command(fit_report_cmd)
    group.add_command(explain_term_cmd)
    group.add_command(coverage_report_cmd)
    group.add_command(generate_inventory_cmd)
    group.add_command(check_inventory_cmd)
    group.add_command(draft_model_report_cmd)
    group.add_command(next_action_cmd)
    group.add_command(design_landscape_cmd)
    group.add_command(guard_scope_cmd)
    group.add_command(update)
    group.add_command(update_refmodels)


register_commands(cli)
