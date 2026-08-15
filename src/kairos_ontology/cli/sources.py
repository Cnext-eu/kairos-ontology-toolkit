# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused sources CLI commands."""

import json
import click
from pathlib import Path
from typing import Any

# Importing the design-time MDM package registers the additive ``mdm-profile``
# projection target with the core projector (registry pattern, MDM-DD-002).
# The CLI is the layer that legitimately depends on both core and mdm.
from .. import mdm as _mdm  # noqa: F401  (import for side-effect: target registration)

from ..core.import_flatfile import DEFAULT_MAX_ROWS, DEFAULT_SAMPLE_SIZE
from .shared import (
    _FORMAT_OPTION,
    _REFMODELS_OPTION,
    _emit,
    _resolve_conformance_root,
    _resolve_import_dir,
    resolve_refmodels_dir,
)


@click.command(name="import-tmdl")
@click.argument("source", type=click.Path(exists=True))
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output directory (default: <hub root>/integration/discovery/bi/). "
    "An explicit path is used verbatim, relative to the current directory.",
)
def import_tmdl(source, output):
    """Import and inventory TMDL/PBIP files for ontology modeling.

    SOURCE is a path to a PBIP ZIP archive, a SemanticModel folder, or a
    standalone .tmdl file. The command parses TMDL content and generates:

    \b
    - An Engineering Pack (markdown) with table/column/measure inventory
    - A Concept Mapping template (YAML) for reference model alignment

    Power BI/TMDL is downstream **demand evidence**, not a canonical input
    source, so output lands under ``integration/discovery/bi/`` (alongside the
    other demand/discovery artifacts) — never under ``integration/sources/``.

    \b
    That path is resolved against the **hub root**, not the current directory,
    so running this from the repository root (where raw exports usually live)
    still writes inside ``ontology-hub/``. Only the two generated artifacts are
    written: a PBIP archive is expanded in a temporary directory, never into the
    hub. Pass --output to write somewhere else; an explicit path is used as
    given.
    """
    from ..core.hub_utils import resolve_hub_output_dir
    from ..core.import_tmdl import _BI_DISCOVERY_RELPATH, run_import_tmdl

    source_path = Path(source)

    # Resolve here as well as in core, so the destination is ANNOUNCED before
    # anything is written. This defect was invisible precisely because the
    # command only ever reported paths after the fact (issue #296): core's
    # logger.warning serves library callers, this echo serves CLI users.
    if output:
        output_path = Path(output)
    else:
        output_path, hub_root = resolve_hub_output_dir(_BI_DISCOVERY_RELPATH)
        if hub_root is None:
            click.echo(
                "⚠️  No ontology-hub root detected from the current directory.\n"
                f"   Writing to the relative path: {output_path}\n"
                "   Run from the hub (or its repository root), or pass --output.",
                err=True,
            )

    click.echo(f"📦 Importing TMDL from: {source_path}")
    click.echo(f"📂 Writing to: {output_path}")
    generated = run_import_tmdl(source_path, output_path)

    if generated:
        click.echo(f"\n✅ Generated {len(generated)} file(s):")
        for f in generated:
            click.echo(f"   {f}")
    else:
        click.echo("\n⚠️  No TMDL content found. Check input path.", err=True)
        raise SystemExit(1)


@click.command(name="show-source-schema")
@click.option("--system", required=True)
@click.option("--sources", type=click.Path(exists=True, file_okay=False), default=None)
def show_source_schema_cmd(system, sources):
    """Print the parsed source vocabulary for one source system as JSON."""
    from ..core.analyse_sources import parse_source_vocabulary
    from ..core.hub_utils import find_hub_root

    hub = find_hub_root(Path.cwd(), require_model=True)
    source_root = (
        Path(sources)
        if sources
        else hub / "integration" / "sources"
        if hub
        else Path("integration") / "sources"
    )
    system_dir = source_root / system
    if not system_dir.is_dir():
        raise click.ClickException(f"Source system directory not found: {system_dir}")
    tables: dict = {}
    files = []
    for ttl in sorted(system_dir.glob("*.ttl")):
        files.append(str(ttl))
        for table, columns in parse_source_vocabulary(ttl).items():
            tables.setdefault(table, []).extend(columns)
    click.echo(
        json.dumps(
            {
                "schema_version": 1,
                "system": system,
                "source_files": files,
                "table_count": len(tables),
                "tables": tables,
            },
            indent=2,
            sort_keys=True,
        )
    )


@click.command(name="import-source")
@click.option(
    "--from",
    "from_path",
    type=click.Path(exists=True),
    required=True,
    help="Path to source-schema YAML file or extracted/<system>/ directory.",
)
@click.option(
    "--system", "system_name", default=None, help="Override the system name (default: from YAML)."
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output directory (default: integration/sources/{system}/).",
)
@click.option("--dry-run", is_flag=True, help="Show changes without writing files.")
@click.option(
    "--enrich/--no-enrich",
    default=True,
    help="Run inference enrichment (enum/format/FK detection). Default: enabled.",
)
@click.option(
    "--enum-threshold",
    type=int,
    default=25,
    help="Max distinct values to suggest as enumeration (default: 25).",
)
@click.option(
    "--split-tables",
    is_flag=True,
    default=False,
    help="ONLY generate per-table files (skip monolithic). By default both are written.",
)
def import_source(from_path, system_name, output, dry_run, enrich, enum_threshold, split_tables):
    """Import source schema YAML and generate/refresh bronze vocabulary TTL.

    Reads a standardized source-schema YAML file (produced by the
    extract_source_schema dbt macro or manually) and generates or updates
    the corresponding kairos-bronze vocabulary TTL.

    Accepts either a single YAML file (v1.0) or a directory with
    _manifest.yaml + per-table YAML files (v1.1 from extract-schema).

    With --enrich (default), runs inference passes that add:
    - Enum suggestions for low-cardinality columns
    - Format hints (email, date, UUID, phone, URL)
    - FK relationship suggestions from naming patterns

    \b
    Examples:
      kairos-ontology import-source --from extracted/adminpulse-schema.yaml
      kairos-ontology import-source --from extracted/adminpulse/
      kairos-ontology import-source --from schema.yaml --system myapp --dry-run
      kairos-ontology import-source --from extracted/nms/ --no-enrich
      kairos-ontology import-source --from extracted/nms/ --split-tables
    """
    from ..core.import_source import run_import_source, parse_source_schema_dir

    source_path = Path(from_path)
    output_dir = Path(output) if output else None

    # CWD guard: warn if running from a dataplatform repo
    cwd = Path.cwd()
    if (cwd / "dbt_project.yml").exists() and not (cwd / "model").is_dir():
        click.echo(
            "⚠️  You appear to be in a dataplatform repo (dbt_project.yml found, "
            "no model/ directory). import-source writes to CWD-relative paths by "
            "default. Consider running from your ontology-hub repo or using "
            "--output to specify the hub path.",
            err=True,
        )

    # Support directory input (v1.1 per-table format)
    tmp_cleanup = None
    if source_path.is_dir():
        click.echo(f"📋 Importing source schema from directory: {source_path}")
        try:
            data = parse_source_schema_dir(source_path)
        except ValueError as e:
            click.echo(f"\n❌ {e}", err=True)
            raise SystemExit(1)

        # Issue #298: a table with zero sampled columns produces a vocabulary with no
        # signal anyone is told about. Surface it as an aggregate warning up front so it
        # isn't silently buried in _merge_samples_from_file's per-table logger.warning
        # calls (which the CLI does not echo).
        tables_without_samples = [
            tbl.get("name", "?")
            for tbl in data.get("tables", [])
            if not any(col.get("samples") for col in tbl.get("columns", []))
        ]
        if tables_without_samples:
            click.echo(
                f"⚠️  {len(tables_without_samples)} of {len(data.get('tables', []))} "
                "table(s) have no sample evidence:",
                err=True,
            )
            for name in tables_without_samples:
                click.echo(f"   - {name}", err=True)

        # Write a temporary combined YAML for run_import_source
        import tempfile
        import yaml as _yaml

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as tmp:
            _yaml.dump(data, tmp, default_flow_style=False, sort_keys=False)
            yaml_path = Path(tmp.name)
            tmp_cleanup = yaml_path
    else:
        yaml_path = source_path
        click.echo(f"📋 Importing source schema from: {yaml_path}")

    try:
        result_path, report = run_import_source(
            yaml_path=yaml_path,
            system_name=system_name,
            output_dir=output_dir,
            dry_run=dry_run,
            enrich=enrich,
            enum_threshold=enum_threshold,
            split_tables=split_tables,
        )
    except ValueError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)

    if report and report.has_changes:
        click.echo(f"\n📊 Changes detected: {report.summary()}")
        if report.added_tables:
            click.echo(f"   ✅ New tables: {', '.join(report.added_tables)}")
        if report.removed_tables:
            click.echo(f"   ⚠️  Deprecated tables: {', '.join(report.removed_tables)}")
        if report.added_columns:
            for c in report.added_columns[:10]:
                click.echo(f"   + {c.table}.{c.column}")
            if len(report.added_columns) > 10:
                click.echo(f"   ... and {len(report.added_columns) - 10} more")
        if report.removed_columns:
            for c in report.removed_columns[:10]:
                click.echo(f"   - {c.table}.{c.column}")
            if len(report.removed_columns) > 10:
                click.echo(f"   ... and {len(report.removed_columns) - 10} more")
        if report.type_changes:
            for c in report.type_changes[:10]:
                click.echo(f"   ~ {c.table}.{c.column}: {c.old_value} → {c.new_value}")
    elif report is None:
        click.echo("\n🆕 Fresh vocabulary generated (no existing file to merge with)")
    else:
        click.echo("\n✅ No changes — vocabulary is already in sync")

    if dry_run:
        click.echo("\n🔍 Dry-run mode — no files written")
    elif result_path:
        if split_tables:
            # split-tables-only mode: result_path is the vocabulary/ directory
            n_files = len(list(result_path.glob("*.vocabulary.ttl")))
            click.echo(f"\n✅ Written {n_files} per-table vocabulary files to: {result_path}")
        else:
            # Default mode: monolithic + per-table
            click.echo(f"\n✅ Written: {result_path}")
            vocab_dir = result_path.parent / "vocabulary"
            if vocab_dir.is_dir():
                n_files = len(list(vocab_dir.glob("*.vocabulary.ttl")))
                click.echo(f"   📂 Also written {n_files} per-table files to: {vocab_dir}")

        # Persist privacy-safe row-context files from directory inputs.
        if source_path.is_dir() and result_path:
            import yaml as _yaml

            from ..core.source_privacy import sanitize_samples_document

            dest_dir = result_path.parent if not split_tables else result_path.parent
            samples_copied = 0
            for samples_file in source_path.glob("*.samples.yaml"):
                dest_file = dest_dir / samples_file.name
                document = _yaml.safe_load(samples_file.read_text(encoding="utf-8"))
                table = (
                    str(document.get("table"))
                    if isinstance(document, dict) and document.get("table")
                    else samples_file.name.removesuffix(".samples.yaml")
                )
                table_file = source_path / f"{table}.yaml"
                table_data = (
                    _yaml.safe_load(table_file.read_text(encoding="utf-8"))
                    if table_file.is_file()
                    else {}
                ) or {}
                column_types = {
                    str(column.get("name", "")): str(column.get("data_type", "unknown"))
                    for column in table_data.get("columns", [])
                }
                safe_document, _ = sanitize_samples_document(
                    document,
                    table=table,
                    column_types=column_types,
                )
                dest_file.write_text(
                    _yaml.safe_dump(
                        safe_document,
                        allow_unicode=True,
                        sort_keys=False,
                    ),
                    encoding="utf-8",
                )
                samples_copied += 1
            if samples_copied:
                click.echo(
                    f"   📋 Persisted {samples_copied} privacy-safe "
                    ".samples.yaml file(s) for row-level context"
                )

    # Clean up temp file if we created one
    if tmp_cleanup and tmp_cleanup.exists():
        tmp_cleanup.unlink()


def _echo_privacy_coverage(report) -> None:
    """Report a clean privacy result *and what it covered* (#415).

    The old message — "privacy-safe for supported patterns" — read as an unqualified
    all-clear while naming no patterns, so a reader could not tell that coordinate columns
    were not among them (they are since #423; abbreviated lat/lon/geo names and WKT still
    are not). A latitude/longitude pair left beside a redacted address in the same row
    re-identifies it by reverse-geocoding, and the command reported success. The kinds
    come from the detectors themselves so this can never overstate coverage.
    """
    kinds = ", ".join(report.checked_kinds)
    click.echo(f"✅ No unredacted PII found in {report.files_scanned} artifact(s).")
    click.echo(f"   Patterns checked: {kinds}.")
    click.echo(
        "   Coordinates checked: latitude/longitude/lng/coordinate columns with "
        'in-range fractional values, including single-column "lat,lon" pairs (#423). '
        "Still not checked: lat/lon/geo-abbreviated column names and WKT geometries."
    )


@click.command(name="source-privacy")
@click.option(
    "--sources",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="Source directory to inspect (default: integration/sources).",
)
@click.option(
    "--fix",
    is_flag=True,
    help="Rewrite affected source YAML and vocabulary TTL with opaque redaction tokens.",
)
def source_privacy_cmd(sources, fix):
    """Check or sanitize persisted source sample artifacts without exposing values."""
    from collections import Counter

    from ..core.hub_utils import find_hub_root
    from ..core.source_privacy import run_source_privacy

    if sources:
        source_dir = Path(sources)
    else:
        hub_root = find_hub_root(Path.cwd(), require_model=False)
        if hub_root is None:
            click.echo(
                "❌ Could not locate ontology-hub; pass --sources explicitly.",
                err=True,
            )
            raise SystemExit(2)
        source_dir = hub_root / "integration" / "sources"

    try:
        report = run_source_privacy(source_dir, fix=fix)
    except (ValueError, OSError) as exc:
        click.echo(f"❌ Source privacy check failed: {exc}", err=True)
        raise SystemExit(2) from exc

    click.echo(f"🔒 Source privacy: scanned {report.files_scanned} artifact(s)")
    summary = Counter(
        (
            str(path.relative_to(source_dir)),
            finding.table,
            finding.column,
            finding.kind,
        )
        for path, finding in report.findings
    )
    for (path, table, column, kind), count in sorted(summary.items()):
        click.echo(f"   ⚠ {path}: {table}.{column} [{kind}] × {count}")

    if fix:
        click.echo(f"   ✓ Rewritten {len(report.changed_files)} affected artifact(s)")
        remaining = run_source_privacy(source_dir)
        if remaining.findings:
            click.echo(
                f"❌ {len(remaining.findings)} unresolved privacy finding(s) remain.",
                err=True,
            )
            raise SystemExit(1)
        _echo_privacy_coverage(remaining)
        return

    if report.findings:
        click.echo(
            f"❌ {len(report.findings)} privacy finding(s); rerun with --fix.",
            err=True,
        )
        raise SystemExit(1)
    _echo_privacy_coverage(report)


@click.command(name="import-flatfile")
@click.option(
    "--from",
    "from_path",
    type=click.Path(exists=True),
    required=True,
    help="Path to CSV file, .xlsx file, Parquet file, or directory of flat files "
    "(non-recursive — top-level files only; pass --recursive for nested export trees).",
)
@click.option(
    "--system",
    "system_name",
    default=None,
    help="System name (default: derived from filename/directory).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output directory (default: integration/sources/{system}/).",
)
@click.option(
    "--sample-size",
    type=int,
    default=DEFAULT_SAMPLE_SIZE,
    help=f"Number of sample rows to store per table (default: {DEFAULT_SAMPLE_SIZE}).",
)
@click.option(
    "--max-rows",
    type=int,
    default=DEFAULT_MAX_ROWS,
    help=f"Maximum rows to read for type inference (default: {DEFAULT_MAX_ROWS}).",
)
@click.option(
    "--exclude-columns",
    default=None,
    help="Comma-separated list of column names to exclude from output.",
)
@click.option(
    "--keep-technical",
    is_flag=True,
    default=False,
    help="Keep auto-detected technical/metadata columns (volume, subfolder, etc.).",
)
@click.option(
    "--recursive",
    is_flag=True,
    default=False,
    help="Directory mode only: walk the full subtree instead of just the top level. "
    "Table names are then derived from each file's path relative to --from "
    "(lowercased, separators collapsed) so same-basename files in different "
    "subdirectories don't collide.",
)
def import_flatfile(
    from_path,
    system_name,
    output,
    sample_size,
    max_rows,
    exclude_columns,
    keep_technical,
    recursive,
):
    """Import CSV/.xlsx/Parquet flat files as source schema documentation.

    Reads flat files and produces the standard source schema format
    (_manifest.yaml + per-table YAML + samples). Use import-source afterwards
    to generate the bronze vocabulary TTL.

    \b
    Supported inputs:
      - Single .csv file → 1 table
      - Single .xlsx file → 1 table per worksheet
      - Single .parquet file → 1 table
      - Directory of .csv/.xlsx/.parquet files → 1 table per file/sheet
        (non-recursive by default; pass --recursive for nested export trees)

    \b
    Directory mode tolerates unreadable files: each one is skipped with a
    warning and the rest are imported (exit 0). If no file in the directory
    can be read, nothing is written and the exit code is 1. A single file
    given directly always fails fast. Legacy .xls files are recognized but
    never readable — convert to .xlsx first.

    \b
    Examples:
      kairos-ontology import-flatfile --from exports/customers.csv --system erp
      kairos-ontology import-flatfile --from data/report.xlsx --system finance
      kairos-ontology import-flatfile --from exports/orders.parquet --system wms
      kairos-ontology import-flatfile --from data-exports/ --system legacy-erp
      kairos-ontology import-flatfile --from nested-exports/ --recursive --system legacy-erp
      kairos-ontology import-flatfile --from .input/data --system erp \\
        --exclude-columns "volume,subfolder,table"

    \b
    Next step after import-flatfile:
      kairos-ontology import-source --from integration/sources/{system}/
    """
    from ..core.import_flatfile import (
        SUPPORTED_FLATFILE_SUFFIXES,
        list_flatfile_candidates,
        missing_flatfile_extras,
        run_import_flatfile,
    )

    source_path = Path(from_path)
    output_dir = Path(output) if output else None

    # Parse comma-separated exclusion list
    exclude_set: set[str] | None = None
    if exclude_columns:
        exclude_set = {c.strip() for c in exclude_columns.split(",") if c.strip()}

    click.echo(f"📋 Importing flat files from: {source_path}")

    # Candidate count for the partial-failure report, taken from the same helper
    # the import loop uses so "M of K" cannot disagree with what was attempted.
    candidates = (
        list_flatfile_candidates(source_path, recursive=recursive)
        if source_path.is_dir()
        else [source_path]
    )
    candidate_count = len(candidates)

    # Ergonomics fix (issue #407 item 2): directory mode is non-recursive by
    # default, so a nested export tree reports "No CSV, Excel, or Parquet files
    # found" — indistinguishable from "wrong path". When --recursive was NOT
    # passed and nothing was found at the top level, check one level further
    # (one extra rglob) so a genuinely nested tree gets a message pointing at
    # --recursive instead of the generic not-found error. This does not change
    # core defaults or touch the write path — nothing has been written yet.
    if source_path.is_dir() and not recursive and candidate_count == 0:
        nested = [
            f
            for f in source_path.rglob("*")
            if f.is_file() and f.suffix.lower() in SUPPORTED_FLATFILE_SUFFIXES
        ]
        if nested:
            click.echo(
                f"\n❌ found {len(nested)} candidate file(s) in subdirectories — "
                "directory mode is non-recursive (use --recursive)",
                err=True,
            )
            raise SystemExit(1)

    # Preflight (issue #407 item 1): a directory of files needing a missing
    # optional extra (e.g. openpyxl for .xlsx, pyarrow for .parquet) would
    # otherwise produce one near-identical warning per file plus a single huge
    # aggregate ValueError from run_import_flatfile. Fail once, up front, with
    # the install command — before anything is written.
    missing_extras = missing_flatfile_extras(candidates)
    if missing_extras:
        click.echo("\n❌ Missing optional dependency for this input:", err=True)
        for extra, install_cmd in sorted(missing_extras.items()):
            click.echo(f"   - install with: {install_cmd}", err=True)
        raise SystemExit(1)

    try:
        result_dir, table_count, samples_count, failures = run_import_flatfile(
            source_path=source_path,
            system_name=system_name,
            output_dir=output_dir,
            max_rows=max_rows,
            sample_size=sample_size,
            exclude_columns=exclude_set,
            keep_technical=keep_technical,
            return_count=True,
            recursive=recursive,
        )
    except (ValueError, ImportError) as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)

    click.echo(f"\n✅ Written to: {result_dir}")
    click.echo(f"   📊 {table_count} table(s) documented")
    if samples_count:
        click.echo(f"   📋 {samples_count} sample file(s) created")
    if failures:
        # Partial success: the readable files were imported and written, so this
        # is a warning and the exit code stays 0. Total failure raises ValueError
        # above and exits 1 without writing anything.
        click.echo(
            f"\n⚠ {len(failures)} of {candidate_count} file(s) could not be read — skipped:",
            err=True,
        )
        for name, reason in failures:
            click.echo(f"   - {name}: {reason}", err=True)
    click.echo(f"\n💡 Next step: kairos-ontology import-source --from {result_dir}")


@click.command(name="analyse-sources")
@click.option(
    "--sources",
    type=click.Path(exists=True),
    default=None,
    help="Path to integration/sources/ directory (default: auto-detect from hub).",
)
@click.option(
    "--ref-models",
    type=click.Path(exists=True),
    default=None,
    help="Path to ontology-reference-models/ directory (default: auto-detect).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output directory (default: integration/sources/_analysis/).",
)
@click.option(
    "--threshold",
    type=float,
    default=0.3,
    help="Deprecated; ignored in table-centric (schema_version 2) analysis.",
)
@click.option(
    "--model",
    "llm_model",
    default="gpt-5.4-mini",
    help="LLM model for semantic matching (default: gpt-5.4-mini).",
)
@click.option(
    "--max-domains",
    type=int,
    default=None,
    help="Maximum reference domains to analyse (rate limit protection).",
)
@click.option(
    "--domains",
    "domains_filter",
    default=None,
    help="Comma-separated domain names — OUTPUT filter only (issue #189): "
    "tables are always classified against the full domain set, then "
    "only matching primary domains are written (case-insensitive "
    "substring match).",
)
@click.option(
    "--materialize",
    "materialize_dir",
    type=click.Path(),
    default=None,
    help="Write the resolved analysis context (manifest + per-domain YAML) "
    "to this directory for inspection.",
)
@click.option(
    "--exclude",
    "exclude_patterns",
    multiple=True,
    default=("archive/**",),
    help="Glob patterns to exclude from reference models (default: archive/**).",
)
@click.option(
    "--accelerator",
    default=None,
    help="Accelerator pack name (e.g. logistics) — classify against its "
    "data domains (party, commercial, ...) instead of raw reference models.",
)
@click.option(
    "--shallow",
    is_flag=True,
    default=False,
    help="Skip owl:imports resolution in the reference-model fallback (faster).",
)
@click.option(
    "--max-workers",
    type=int,
    default=8,
    help="Max concurrent per-table LLM calls (default: 8; use 1 for serial).",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Bypass the per-table cache and re-classify every table.",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Show per-table classification lines."
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    default=False,
    help="Suppress progress output (errors still shown).",
)
def analyse_sources_cmd(
    sources,
    ref_models,
    output,
    threshold,
    llm_model,
    max_domains,
    domains_filter,
    materialize_dir,
    exclude_patterns,
    accelerator,
    shallow,
    max_workers,
    force,
    verbose,
    quiet,
):
    """Analyse source vocabularies against reference model domains (LLM-powered).

    Classifies each source table by domain affinity. Two strategies:

    \b
    - Data-domain-first (recommended): pass --accelerator <name> to classify
      tables toward the accelerator's data domains (party, commercial, booking,
      ...), each carrying its model URIs. Fast — no owl:imports resolution.
    - Reference-model (default): resolves and groups reference model TTLs.

    Produces per-source affinity reports that the modeling skill uses to scope
    context and seed evidence tables.

    --domains is an OUTPUT focus, not a candidate restriction: every table is
    always classified against the full domain set (so it gets its true primary
    domain), then only tables whose primary domain matches --domains are written
    (issue #189). This avoids forcing unrelated tables into the requested domain.

    Requires AI provider configuration (GITHUB_TOKEN or AZURE_AI_ENDPOINT).

    \b
    Examples:
      kairos-ontology analyse-sources --accelerator logistics
      kairos-ontology analyse-sources --accelerator logistics --domains "party,booking"
      kairos-ontology analyse-sources --materialize .resolved/ --verbose
      kairos-ontology analyse-sources --sources path/to/sources/ --ref-models path/to/refs/
    """
    from ..core.analyse_sources import (
        run_analyse_sources,
        resolve_reference_models,
        build_data_domain_targets,
        load_data_domains,
        list_accelerator_packs,
        make_reporter,
        AffinityTotalFailureError,
    )
    from ..core.ai_provider import DEFAULT_MODEL, ROLE_AFFINITY, resolve_role_model
    from ..core.hub_utils import find_hub_root

    # Issue #182: a per-role model override (KAIROS_AI_AFFINITY_MODEL) acts as the
    # default for this step unless the operator pinned --model explicitly.
    if llm_model == DEFAULT_MODEL:
        llm_model = resolve_role_model(ROLE_AFFINITY, DEFAULT_MODEL)

    # Auto-detect hub paths
    cwd = Path.cwd()
    hub_root = find_hub_root(cwd)

    if sources is None:
        if hub_root:
            sources_path = hub_root / "integration" / "sources"
        else:
            sources_path = Path("integration/sources")
    else:
        sources_path = Path(sources)

    if ref_models is None:
        ref_models_path = resolve_refmodels_dir(cwd, hub_root)
        if ref_models_path is None:
            click.echo(
                "❌ Cannot find ontology-reference-models/ directory. Use --ref-models to specify.",
                err=True,
            )
            raise SystemExit(1)
    else:
        ref_models_path = Path(ref_models)

    if output is None:
        output_path = sources_path / "_analysis"
    else:
        output_path = Path(output)

    if not sources_path.is_dir():
        click.echo(f"❌ Sources directory not found: {sources_path}", err=True)
        raise SystemExit(1)

    if not quiet:
        click.echo(f"🔍 Analysing sources in: {sources_path}")
        click.echo(f"   Reference models: {ref_models_path}")
        click.echo(f"   Model: {llm_model}")
        if accelerator:
            click.echo(f"   Accelerator: {accelerator} (data-domain-first)")
        if domains_filter:
            click.echo(
                f"   Domain filter: {domains_filter} (output focus only — full set is classified)"
            )
        click.echo()

    # Detect catalog for owl:imports resolution
    catalog_file = None
    if hub_root:
        candidate_cat = hub_root / "catalog-v001.xml"
        if candidate_cat.exists():
            catalog_file = candidate_cat

    # Convert exclude_patterns tuple to list
    excl_list = list(exclude_patterns) if exclude_patterns else None

    # Pre-flight: show resolved domains (skipped in quiet mode)
    if not quiet:
        if accelerator:
            data_domains = load_data_domains(ref_models_path, accelerator=accelerator)
            if not data_domains:
                available = list_accelerator_packs(ref_models_path)
                click.echo(
                    f"❌ No data-domains.yaml for accelerator '{accelerator}'. "
                    f"Available: {available or '(none)'}",
                    err=True,
                )
                raise SystemExit(1)
            targets = build_data_domain_targets(data_domains)
            click.echo(f"📊 {len(targets)} data domain(s) from '{accelerator}':")
            for d in targets:
                uris = ", ".join(d.get("uris", [])) or "(no URIs)"
                click.echo(f"   • {d['domain_name']} [{d.get('group', '')}] → {uris}")
            click.echo()
        else:
            ref_domains = resolve_reference_models(
                ref_models_path,
                catalog_path=(None if shallow else catalog_file),
                exclude_patterns=excl_list,
            )
            if ref_domains:
                total_cls = sum(len(d.get("classes", [])) for d in ref_domains)
                total_props = sum(
                    sum(len(c.get("properties", [])) for c in d.get("classes", []))
                    for d in ref_domains
                )
                click.echo(
                    f"📊 Resolved {len(ref_domains)} domain(s) "
                    f"({total_cls} classes, {total_props} properties):"
                )
                for d in ref_domains:
                    n_cls = len(d.get("classes", []))
                    n_props = sum(len(c.get("properties", [])) for c in d.get("classes", []))
                    click.echo(f"   • {d['domain_name']} ({n_cls} classes, {n_props} properties)")
                click.echo()

    # Parse domains filter
    filter_list = None
    if domains_filter:
        filter_list = [d.strip() for d in domains_filter.split(",") if d.strip()]

    # Parse materialize dir
    mat_dir = Path(materialize_dir) if materialize_dir else None

    try:
        reporter = make_reporter(verbose=verbose, quiet=quiet)
        output_files = run_analyse_sources(
            sources_dir=sources_path,
            ref_models_dir=ref_models_path,
            output_dir=output_path,
            model=llm_model,
            threshold=threshold,
            max_domains=max_domains,
            domains_filter=filter_list,
            materialize_dir=mat_dir,
            catalog_path=catalog_file,
            exclude_patterns=excl_list,
            accelerator=accelerator,
            shallow=shallow,
            report=reporter,
            max_workers=max_workers,
            force=force,
            cost_warning=not quiet,
        )
        if not quiet:
            click.echo(
                f"\n✅ Analysis complete! Written {len(output_files)} file(s) to: {output_path}"
            )
            for f in output_files:
                click.echo(f"   📄 {f.name}")
    except EnvironmentError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)
    except ValueError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)
    except AffinityTotalFailureError as e:
        click.echo(f"\n⛔ {e}", err=True)
        raise SystemExit(1)


@click.command(name="audit-silver-samples")
@click.option(
    "--sources",
    type=click.Path(exists=True),
    default=None,
    help="Path to integration/sources/ directory (default: auto-detect).",
)
@click.option(
    "--mappings",
    type=click.Path(exists=True),
    default=None,
    help="Path to model/mappings/ directory of v4 SKOS mappings (default: auto-detect).",
)
@click.option(
    "--bindings",
    type=click.Path(exists=True),
    default=None,
    help="Path to integration/bindings/ directory of v5 EntityBindings (default: auto-detect).",
)
@click.option(
    "--dbt-output",
    type=click.Path(exists=True),
    default=None,
    help="Path to generated dbt output directory "
    "(default: <repo>/ontology-hub-publish/medallion/dbt).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Report output directory "
    "(default: <repo>/ontology-hub-publish/reports/silver-sample-audit).",
)
@click.option(
    "--fail-on",
    type=click.Choice(["none", "warning", "error"]),
    default="none",
    help="Exit non-zero when findings at this severity exist (default: none).",
)
def audit_silver_samples_cmd(sources, mappings, bindings, dbt_output, output, fail_on):
    """Offline advisory audit of generated silver dbt mappings using source samples.

    This command reads source vocabularies, mapped columns (v4 SKOS mappings and/or v5
    EntityBindings), and generated dbt SQL only. It does not require a dbt profile,
    warehouse credentials, or live bronze data. Findings are advisory by default.
    """
    from ..core.hub_utils import find_hub_root, publish_root
    from ..core.silver_sample_audit import run_silver_sample_audit

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd)
    base = hub_root or cwd
    pub = publish_root(hub_root or cwd / "ontology-hub")

    sources_path = Path(sources) if sources else base / "integration" / "sources"
    mappings_path = Path(mappings) if mappings else base / "model" / "mappings"
    bindings_path = Path(bindings) if bindings else base / "integration" / "bindings"
    dbt_output_path = Path(dbt_output) if dbt_output else pub / "medallion" / "dbt"
    output_path = Path(output) if output else pub / "reports" / "silver-sample-audit"

    click.echo("🔎 Running offline silver sample audit")
    click.echo(f"   Sources:    {sources_path}")
    click.echo(f"   Mappings:   {mappings_path} (v4)")
    click.echo(f"   Bindings:   {bindings_path} (v5)")
    click.echo(f"   dbt output: {dbt_output_path}")
    click.echo(f"   Report:     {output_path}")
    click.echo()

    report = run_silver_sample_audit(
        sources_dir=sources_path,
        mappings_dir=mappings_path,
        dbt_output_dir=dbt_output_path,
        output_dir=output_path,
        bindings_dir=bindings_path,
        hub_root=base,
    )

    counts = report.counts
    if report.mapped_columns == 0:
        click.echo(
            "⚠ No mapped columns found on either authoring surface — nothing was audited. "
            f"Searched {mappings_path} (v4) and {bindings_path} (v5)."
        )
    else:
        click.echo(
            f"✅ Audit complete: {report.mapped_columns} mapped column(s), "
            f"{report.sampled_mapped_columns} with samples "
            f"({report.sample_coverage_ratio:.0%} coverage)"
        )
    click.echo(
        f"   Findings: {counts['error']} error(s), "
        f"{counts['warning']} warning(s), {counts['info']} info"
    )
    click.echo(f"   📄 {output_path / 'silver-sample-audit.yaml'}")
    click.echo(f"   📄 {output_path / 'silver-sample-audit.md'}")

    should_fail = (fail_on == "error" and counts["error"] > 0) or (
        fail_on == "warning" and (counts["error"] > 0 or counts["warning"] > 0)
    )
    if should_fail:
        raise SystemExit(1)


@click.command(name="audit-column-coverage")
@click.option(
    "--sources",
    type=click.Path(exists=True),
    default=None,
    help="Path to integration/sources/ directory (default: auto-detect).",
)
@click.option(
    "--bindings",
    type=click.Path(exists=True),
    default=None,
    help="Path to integration/bindings/ directory of v5 EntityBindings (default: auto-detect).",
)
@click.option(
    "--fail-on",
    type=click.Choice(["none", "any"]),
    default="none",
    help="Exit non-zero when any orphan column or unbound table is found (default: none).",
)
def audit_column_coverage_cmd(sources, bindings, fail_on):
    """Advisory gate: source columns with real data that no binding references (issue #353).

    For every bound source table, flags a column with real, populated sample variation
    that isn't referenced anywhere in that table's binding(s) -- not in fields:, not in
    technicalFields:, not in identity/grain/relationships/quality/load.incremental --
    and separately lists source tables with zero bindings at all. Audit-trail/operational
    columns (created/updated/system timestamps, GUIDs, hashes) are excluded by name, reusing
    the same pattern list `propose-alignment` already uses (DD-077), not a bespoke one.

    This is the closest v5 equivalent to v4's deleted Claim Registry column-omission gate --
    recomputed fresh each run (v5 is stateless, DD-133), not persisted. Advisory by default:
    a flagged column is a candidate for authoring, not proof that it should be mapped --
    check the binding's own documented exclusions first.
    """
    from ..core.hub_utils import find_hub_root
    from ..core.column_coverage_audit import run_column_coverage_audit

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd)
    base = hub_root or cwd

    sources_path = Path(sources) if sources else base / "integration" / "sources"
    bindings_path = Path(bindings) if bindings else base / "integration" / "bindings"

    click.echo("🔎 Running column-coverage audit")
    click.echo(f"   Sources:  {sources_path}")
    click.echo(f"   Bindings: {bindings_path}")
    click.echo()

    report = run_column_coverage_audit(sources_dir=sources_path, bindings_dir=bindings_path)

    if report.unbound_tables:
        click.echo(f"⚠️  {len(report.unbound_tables)} source table(s) with zero bindings:")
        for finding in report.unbound_tables:
            click.echo(f"   {finding.table} ({finding.column_count} columns)")
        click.echo()

    if report.orphan_columns:
        click.echo(f"⚠️  {len(report.orphan_columns)} unmapped column(s) with real data:")
        for finding in report.orphan_columns:
            bindings_note = ", ".join(finding.binding_names)
            # row_count may be absent (#422: capped flatfile reads omit it).
            row_total = "?" if finding.row_count is None else finding.row_count
            click.echo(
                f"   {finding.table}.{finding.column} "
                f"(distinct={finding.distinct_count}/{row_total}, "
                f"type={finding.data_type}) sample={finding.sample_value!r} "
                f"[bound by: {bindings_note}]"
            )
    else:
        click.echo("✅ No unmapped columns with real data found.")

    for note in report.notes:
        click.echo(f"   ⚠ {note}")

    if fail_on == "any" and (report.orphan_columns or report.unbound_tables):
        raise SystemExit(1)


@click.command(name="propose-alignment")
@click.option(
    "--analysis",
    type=click.Path(exists=True),
    default=None,
    help="Path to _analysis/ directory with affinity reports (default: auto-detect).",
)
@click.option(
    "--sources",
    type=click.Path(exists=True),
    default=None,
    help="Path to integration/sources/ directory (default: auto-detect).",
)
@click.option(
    "--catalog",
    type=click.Path(exists=True),
    default=None,
    help="Path to catalog-v001.xml (default: auto-detect from hub).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Advisory alignment output directory (default: source _analysis/ directory).",
)
@click.option(
    "--model",
    "llm_model",
    default="gpt-5.4-mini",
    help="LLM model for semantic alignment (default: gpt-5.4-mini).",
)
@click.option(
    "--domains",
    "domains_filter",
    default=None,
    help="Comma-separated domain names to include (case-insensitive substring match).",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Show per-table alignment details."
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    default=False,
    help="Suppress progress output (errors still shown).",
)
@click.option(
    "--include-mapping-hints",
    is_flag=True,
    default=False,
    help="DD-045: add deterministic transform + structural mapping hints "
    "(advisory, human-confirmed). Default output is unchanged.",
)
@click.option(
    "--no-sample-values",
    "no_sample_values",
    is_flag=True,
    default=False,
    help="DD-075: suppress masked sample example_values in the output "
    "(values are included by default; PII is always masked).",
)
@click.option(
    "--max-prompt-classes",
    type=int,
    default=12,
    help="Max reference classes in first-pass table prompt (default: 12).",
)
@click.option(
    "--retry-min-confidence",
    type=click.FloatRange(0.0, 1.0),
    default=0.6,
    help="Retry with full reference inventory when ref_class confidence is below this "
    "threshold (default: 0.6).",
)
@click.option(
    "--retry-min-mapped-ratio",
    type=click.FloatRange(0.0, 1.0),
    default=0.4,
    help="Retry with full reference inventory when non-custom mapped column ratio is "
    "below this threshold (default: 0.4).",
)
@click.option(
    "--max-workers",
    type=int,
    default=8,
    help="Max concurrent per-table LLM calls (default: 8; use 1 for serial).",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Bypass caches (domain affinity skip + per-table cache) and re-align all.",
)
@click.option(
    "--cross-module",
    "cross_module",
    is_flag=True,
    default=False,
    help="DD-070 (issue #166): widen the property candidate pool to the whole "
    "accelerator so columns can match sibling/shared-module properties "
    "(e.g. a shared Address class). Requires --accelerator. Default output "
    "is unchanged.",
)
@click.option(
    "--accelerator",
    default=None,
    help="Accelerator pack name whose data-domains.yaml defines the cross-module "
    "property pool (required with --cross-module).",
)
@click.option(
    "--custom-confidence-floor",
    type=click.FloatRange(0.0, 1.0),
    default=0.5,
    help="Issue #182: below this confidence an unmatched column emits no "
    "suggested property (null) instead of a confident-but-wrong guess "
    "(default: 0.5).",
)
@click.option(
    "--high-accuracy",
    "high_accuracy",
    is_flag=True,
    default=False,
    help="Issue #182: use the preferred non-reasoning accuracy tier "
    "(gpt-5.4) for this accuracy-sensitive alignment step "
    "(overrides the default model unless --model was set "
    "explicitly). Costs more per run than the mini default.",
)
@click.option(
    "--allow-fallback-output",
    "allow_fallback_output",
    is_flag=True,
    default=False,
    help="Write a domain alignment even when "
    "every one of its tables is fallback-only (no reference model "
    "to align against — the LLM was never called). Without this "
    "flag such a domain is skipped as incomplete so a placeholder "
    "never masquerades as a real proposal.",
)
def propose_alignment_cmd(
    analysis,
    sources,
    catalog,
    output,
    llm_model,
    domains_filter,
    verbose,
    quiet,
    include_mapping_hints,
    no_sample_values,
    max_prompt_classes,
    retry_min_confidence,
    retry_min_mapped_ratio,
    max_workers,
    force,
    cross_module,
    accelerator,
    custom_confidence_floor,
    high_accuracy,
    allow_fallback_output,
):
    """Propose source-column → reference-model-property alignment (LLM-powered).

    Pre-modeling step that analyses how source columns map to reference model
    classes and properties. Requires affinity reports from analyse-sources.

    \b
    Produces per-domain alignment YAML files that the modeling skill uses
    to pre-populate the Source Evidence Table with reference model matches.

    \b
    Examples:
      kairos-ontology propose-alignment
      kairos-ontology propose-alignment --domains "commercial,party" --verbose
      kairos-ontology propose-alignment --analysis path/to/_analysis/
    """
    from ..core.propose_alignment import (
        HIGH_ACCURACY_MODEL,
        AlignmentTotalFailureError,
        run_propose_alignment,
    )
    from ..core.ai_provider import DEFAULT_MODEL, ROLE_ALIGNMENT, resolve_role_model
    from ..core.conformance_artifact import ARTIFACT_RELPATH
    from ..core.hub_utils import find_hub_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd)

    # Issue #182: the opt-in high-accuracy preset bumps the model tier for this
    # accuracy-sensitive step, unless the operator pinned a model explicitly. When
    # neither is given, a per-role model override (KAIROS_AI_ALIGNMENT_MODEL) acts
    # as the default so it stays consistent with KAIROS_AI_ALIGNMENT_ENDPOINT.
    if high_accuracy and llm_model == DEFAULT_MODEL:
        llm_model = HIGH_ACCURACY_MODEL
    elif llm_model == DEFAULT_MODEL:
        llm_model = resolve_role_model(ROLE_ALIGNMENT, DEFAULT_MODEL)

    # Auto-detect analysis directory
    if analysis is None:
        for candidate in [
            (hub_root / "integration" / "sources" / "_analysis") if hub_root else None,
            cwd / "integration" / "sources" / "_analysis",
            cwd / "_analysis",
        ]:
            if candidate and candidate.is_dir():
                analysis_path = candidate
                break
        else:
            click.echo(
                "❌ Cannot find _analysis/ directory with affinity reports. "
                "Run 'kairos-ontology analyse-sources' first, or use --analysis.",
                err=True,
            )
            raise SystemExit(1)
    else:
        analysis_path = Path(analysis)

    # Auto-detect sources directory
    if sources is None:
        if hub_root:
            sources_path = hub_root / "integration" / "sources"
        else:
            sources_path = cwd / "integration" / "sources"
    else:
        sources_path = Path(sources)

    # Auto-detect catalog
    if catalog is None:
        catalog_path = None
        if hub_root:
            candidate_cat = hub_root / "catalog-v001.xml"
            if candidate_cat.exists():
                catalog_path = candidate_cat
    else:
        catalog_path = Path(catalog)

    output_path = Path(output) if output else analysis_path

    # DD-070: resolve the reference-models dir + validate cross-module prerequisites.
    ref_models_dir = None
    if cross_module:
        ref_models_dir = resolve_refmodels_dir(cwd, hub_root)
        if not accelerator:
            click.echo(
                "❌ --cross-module requires --accelerator <name> (the accelerator "
                "pack whose data-domains.yaml defines the cross-module pool).",
                err=True,
            )
            raise SystemExit(1)
        if ref_models_dir is None:
            click.echo(
                "❌ --cross-module needs a reference-models directory "
                "(ontology-reference-models/). None found. Run "
                "'kairos-ontology update-refmodels' first.",
                err=True,
            )
            raise SystemExit(1)

    # uri-anchor-contract: auto-detect the confirmed discovery conformance
    # artifact (DD-090) so a table's affinity-derived likely_entity that was
    # explicitly confirmed (``conforms``/``conforms-with-rename``, including a
    # human rename via ``rename_to``) resolves straight to its canonical
    # inventory URI, ahead of any name-similarity/LLM class guess. A missing
    # artifact is not an error — output stays exactly as before this feature.
    conformance_artifact_path = (
        (hub_root / ARTIFACT_RELPATH) if hub_root else (cwd / ARTIFACT_RELPATH)
    )
    if not conformance_artifact_path.is_file():
        conformance_artifact_path = None

    if not quiet:
        click.echo("📐 Proposing column→property alignment")
        click.echo(f"   Analysis: {analysis_path}")
        click.echo(f"   Sources: {sources_path}")
        click.echo(f"   Catalog: {catalog_path or '(none)'}")
        click.echo(f"   Model: {llm_model}")
        if domains_filter:
            click.echo(f"   Domain filter: {domains_filter}")
        if include_mapping_hints:
            click.echo("   Mapping hints: enabled (DD-045)")
        if cross_module:
            click.echo(f"   Cross-module: enabled (accelerator: {accelerator}) [DD-070]")
        if conformance_artifact_path:
            click.echo(f"   Confirmed anchors: {conformance_artifact_path}")
        click.echo()

    filter_list = None
    if domains_filter:
        filter_list = [d.strip() for d in domains_filter.split(",") if d.strip()]

    def reporter(msg, level="normal"):
        if quiet:
            return
        if level == "verbose" and not verbose:
            return
        click.echo(msg)

    try:
        generation_stats: dict[str, int] = {}
        output_files = run_propose_alignment(
            analysis_dir=analysis_path,
            sources_dir=sources_path,
            catalog_path=catalog_path,
            output_dir=output_path,
            model=llm_model,
            domains_filter=filter_list,
            report=reporter,
            include_mapping_hints=include_mapping_hints,
            include_sample_values=not no_sample_values,
            max_prompt_classes=max_prompt_classes,
            retry_min_confidence=retry_min_confidence,
            retry_min_mapped_ratio=retry_min_mapped_ratio,
            max_workers=max_workers,
            force=force,
            cost_warning=not quiet,
            cross_module=cross_module,
            accelerator=accelerator,
            ref_models_dir=ref_models_dir,
            custom_confidence_floor=custom_confidence_floor,
            allow_fallback_output=allow_fallback_output,
            generation_stats=generation_stats,
            conformance_artifact_path=conformance_artifact_path,
        )
        if not quiet:
            click.echo(
                f"\n✅ Proposal complete! Wrote {len(output_files)} alignment "
                f"file(s) to: {output_path}"
            )
            for f in output_files:
                click.echo(f"   📄 {f.name}")
            if generation_stats.get("provider_failure"):
                click.echo(
                    f"   ⚠ {generation_stats['provider_failure']} of "
                    f"{generation_stats.get('attempted', 0)} attempted table(s) "
                    "had a semantic generation failure — see per-table warnings above."
                )
    except AlignmentTotalFailureError as e:
        # Alignment-reliability: total failure must never print success and must
        # exit non-zero. Nothing was written by the pipeline in this case.
        click.echo(f"\n⛔ {e}", err=True)
        raise SystemExit(1)
    except EnvironmentError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)
    except ValueError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)


@click.command(name="discovery-status")
@click.option(
    "--import-dir",
    type=click.Path(),
    default=None,
    help="Path to .import/businessdiscovery/ (default: auto-detect from hub).",
)
@click.option(
    "--extraction-dir",
    type=click.Path(),
    default=None,
    help="Path to businessdiscovery/_extractions/ (default: auto-detect from hub).",
)
@click.option(
    "--strict",
    is_flag=True,
    default=False,
    help="Exit non-zero when documents are new (unprocessed) or changed.",
)
@click.option(
    "--warn-only",
    is_flag=True,
    default=False,
    help="Report status but always exit 0 (never block).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format (default: text -- human-readable). Use ``--format json`` for "
    "machine-readable output.   Conformance/BI/archetype status is available in JSON via "
    "``kairos-ontology next --format json``.",
)
def discovery_status_cmd(import_dir, extraction_dir, strict, warn_only, output_format):
    """Report which business-discovery documents are unprocessed or changed (DD-060).

    Deterministic, AI-free helper for the ``design-discovery`` skill: scans the raw
    artifacts in ``.import/businessdiscovery/`` and compares each against its
    per-document extraction file under ``businessdiscovery/_extractions/`` using the
    stored ``source_sha256``.  The skill uses this to process only **new** or
    **changed** documents on a rerun instead of re-reading everything.

    Informational by default (exit 0).  Pass ``--strict`` to exit non-zero when
    there is work to do (new or changed documents) or when a matched extraction
    record still looks like an unedited placeholder (TODO/empty summary,
    strategy, or ``extracted_terms``). Byte-identical duplicate documents and
    the ``processed``/``partial``/``skipped`` status breakdown are always
    reported but never block, even under ``--strict``.

    ``--format`` defaults to ``text`` (human-readable). The CLI has two output families:
    conformance helpers (``discovery-conformance``) use ``_FORMAT_OPTION`` which defaults
    to ``json`` — those are machine-first; status/advisory commands like this one are
    human-first and default to ``text``. Use ``--format json`` for machine consumption of
    the ``DiscoveryStatusReport`` dataclass, the three booleans (``has_work``,
    ``has_warnings``, ``has_content_warnings``), and the two resolved paths. Conformance,
    BI, and archetype status are available in JSON via ``kairos-ontology next --format
    json`` — this command does not duplicate that.

    \\b
    Examples:
      kairos-ontology discovery-status
      kairos-ontology discovery-status --strict
      kairos-ontology discovery-status --format json
    """
    from ..core.discovery_extraction import check_discovery_docs
    from ..core.hub_utils import find_hub_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=False)

    if import_dir:
        imp_path = Path(import_dir)
    else:
        imp_path = _resolve_import_dir(cwd, hub_root)

    if extraction_dir:
        ext_path = Path(extraction_dir)
    elif hub_root:
        ext_path = hub_root / "businessdiscovery" / "_extractions"
    else:
        ext_path = cwd / "businessdiscovery" / "_extractions"

    report = check_discovery_docs(import_dir=imp_path, extraction_dir=ext_path)

    if output_format == "json":
        import dataclasses

        payload = {
            "report": dataclasses.asdict(report),
            "has_work": report.has_work,
            "has_warnings": report.has_warnings,
            "has_content_warnings": report.has_content_warnings,
            "import_dir": str(imp_path),
            "extraction_dir": str(ext_path),
        }
        # Exit codes mirror the text path: --strict + has_work/has_content_warnings -> 1.
        if strict and not warn_only and (report.has_work or report.has_content_warnings):
            payload["blocked"] = True
            payload["block_reason"] = (
                "new/changed documents" if report.has_work else "placeholder-shaped content"
            )
            click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
            raise SystemExit(1)
        payload["blocked"] = False
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    click.echo("🔎 Checking business-discovery documents")
    click.echo(f"   Import dir:     {imp_path}")
    click.echo(f"   Extraction dir: {ext_path}")

    if not imp_path.is_dir():
        click.echo("   ⚠ No .import/businessdiscovery/ directory found — nothing to process.")
        return

    for name in report.ok:
        click.echo(f"   ✓ {name}: up to date")
    for name in report.unprocessed:
        click.echo(f"   ➕ {name}: NEW (not yet processed)")
    for name in report.changed:
        click.echo(f"   ♻ {name}: CHANGED since last extraction")
    for name in report.unverifiable:
        click.echo(f"   ⚠ {name}: cannot verify freshness (no stored hash — reprocess)")
    for name in report.conflict:
        click.echo(f"   ⚠ {name}: conflicting provenance (claimed by >1 extraction)")
    for name in report.orphan:
        click.echo(f"   ⚠ {name}: orphan extraction (no matching source document)")
    # C1/#417: byte-identical documents are additive information, never subtracted
    # from the work count below — a duplicate with no extraction record still
    # needs processing.
    for group in report.duplicate:
        click.echo(f"   ⧉ duplicate content ({len(group)} documents): {', '.join(group)}")
    # D3/#416a: placeholder-shaped extraction content (TODO/empty summary,
    # strategy, extracted_terms). Always advisory; see has_content_warnings.
    for entry in report.content_warnings:
        click.echo(f"   ⚠ placeholder content — {entry}")

    if report.status_counts:
        # C2/#416b: `status: processed | partial | skipped` is documented but was
        # read nowhere in src/ — surface the breakdown instead of a single green line.
        parts = [
            f"{count} {status}" for status, count in sorted(report.status_counts.items()) if count
        ]
        click.echo(f"   Σ extraction status: {', '.join(parts)}")

    # C3: `--strict` fails on `has_work` (unchanged) and, newly, on
    # `has_content_warnings` — but the two are OR'd together only under
    # `--strict`, mirroring `cli/inspection.py`'s
    # `blocking = report.is_blocking or (strict and report.unverifiable)` shape.
    # `has_content_warnings` is deliberately NOT folded into `has_work` itself:
    # doing so would make `--strict` unconvergeable on a hub with
    # legitimately-`partial` records (the #405 pathology this plan also fixes)
    # and would make the "N document(s) need processing" count below name
    # already-processed documents as needing processing.
    if strict and not warn_only and (report.has_work or report.has_content_warnings):
        reason = (
            "new/changed documents" if report.has_work else "placeholder-shaped extraction content"
        )
        click.echo(
            f"\n❌ Discovery documents need processing ({reason}). Run the "
            "kairos-design-discovery skill to extract new/changed documents.",
            err=True,
        )
        raise SystemExit(1)

    nothing_found = not any(
        [
            report.ok,
            report.unprocessed,
            report.changed,
            report.unverifiable,
            report.orphan,
            report.conflict,
        ]
    )

    if report.has_work:
        n = len(report.unprocessed) + len(report.changed)
        click.echo(f"\n⚠ {n} document(s) need processing (run kairos-design-discovery).")
    elif report.has_warnings:
        click.echo("\n⚠ Discovery documents checked with warnings (not blocking).")
    elif nothing_found:
        click.echo(
            "\n   (no discovery documents found under .import/businessdiscovery/ — "
            "nothing to check)"
        )
    else:
        click.echo("\n✅ All discovery documents are processed and up to date.")


@click.group(name="discovery-conformance")
def discovery_conformance():
    """Core Concepts Conformance helpers for the design-discovery skill (DD-090).

    Deterministic, machine-output helpers that load the archetype + discovery contract
    from a reference-models checkout (>= v1.11.0), derive relationship topology, and
    validate the conformance artifact.  The interactive interview itself is driven by the
    **kairos-design-discovery** skill — these subcommands give it clean JSON/YAML to work
    from.  All human-readable progress goes to **stderr**; stdout is machine output only.
    """


@discovery_conformance.command(name="list-archetypes")
@_REFMODELS_OPTION
@_FORMAT_OPTION
def conformance_list(refmodels_root, output_format):
    """List archetype ids available in the reference-models checkout."""
    from ..core.archetype_loader import list_archetypes, load_outcome_codes

    root = _resolve_conformance_root(refmodels_root)
    click.echo(f"🔎 Reference-models root: {root}", err=True)
    _emit(
        {
            "refmodels_root": str(root),
            "archetypes": list_archetypes(root),
            "outcome_codes": load_outcome_codes(root),
        },
        output_format,
    )


@discovery_conformance.command(name="load")
@click.option("--archetype", "archetype_id", required=True, help="Archetype id to load.")
@_REFMODELS_OPTION
@_FORMAT_OPTION
def conformance_load(archetype_id, refmodels_root, output_format):
    """Load an archetype: emit catalog, derived topology, and discovery-doc path.

    The skill uses this payload to drive the conformance interview. Concept coverage,
    relationship edges (with declared cardinality), and version-drift warnings are all
    included; warnings are also echoed to stderr.
    """
    from ..core.archetype_loader import (
        ArchetypeError,
        check_version_drift,
        load_archetype,
        locate_discovery_doc,
        _refmodels_version,
    )
    from ..core.archetype_topology import (
        UNKNOWN_ONTOLOGY_TIER,
        derive_archetype_topology,
        unpinned_blueprint_modules,
    )

    root = _resolve_conformance_root(refmodels_root)
    try:
        archetype = load_archetype(root, archetype_id)
    except ArchetypeError as exc:
        click.echo(f"❌ {exc}", err=True)
        raise SystemExit(2) from exc

    try:
        discovery_doc = locate_discovery_doc(root, archetype_id)
    except ArchetypeError as exc:
        click.echo(f"❌ {exc}", err=True)
        raise SystemExit(2) from exc

    discovery_doc_rel = None
    if discovery_doc is not None:
        try:
            discovery_doc_rel = discovery_doc.relative_to(root).as_posix()
        except ValueError:
            # Defensive: shouldn't happen since locate_discovery_doc globs under root,
            # but never let an unrelativizable path leak out absolute (#313).
            discovery_doc_rel = discovery_doc.name

    topology = derive_archetype_topology(root, archetype)
    drift = check_version_drift(archetype, root)
    # Machine-only: actionable in reference-models, not by the hub designer reading this
    # console, and it would otherwise print on every load of an affected archetype.
    blueprint_warnings = unpinned_blueprint_modules(archetype, topology.module_tiers)

    for w in drift + topology.warnings():
        click.echo(f"⚠ {w}", err=True)
    if discovery_doc is None:
        click.echo(
            f"⚠ No discovery doc paired with '{archetype_id}'; "
            "the skill will run a generic per-concept flow.",
            err=True,
        )

    payload = {
        "archetype": {
            "id": archetype.id,
            "label": archetype.label,
            "description": archetype.description,
            "source": archetype.source_path.name,
            "catalog_hash": archetype.catalog_hash,
            "concept_set_hash": archetype.concept_set_hash(),
            "compatible_with": archetype.compatible_with,
        },
        "refmodels_version": _refmodels_version(root),
        "discovery_doc": discovery_doc_rel,
        # 'tier' is the archetype's *conformance* tier (required/recommended/optional);
        # 'ontology_tier' is which reference-models tier the module lives in
        # (blueprint/derived/authoritative). Two unrelated meanings — never merge the keys.
        "ref_model_modules": [
            {
                "iri": m.iri,
                "tier": m.tier,
                "ontology_tier": topology.module_tiers.get(m.iri, UNKNOWN_ONTOLOGY_TIER),
            }
            for m in archetype.ref_model_modules
        ],
        "core_concepts": [
            {"uri": c.uri, "label": c.label, "tier": c.tier} for c in archetype.core_concepts
        ],
        "topology": {
            "present_concepts": topology.present_concepts,
            "missing_concepts": topology.missing_concepts,
            "loaded_modules": topology.loaded_modules,
            "edges": [
                {
                    "property": e.property_uri,
                    "label": e.property_label,
                    "domain": e.domain_uri,
                    "range": e.range_uri,
                    "min_cardinality": e.min_cardinality,
                    "max_cardinality": e.max_cardinality,
                    "exact_cardinality": e.exact_cardinality,
                    "functional": e.functional,
                    "cardinality_declared": e.cardinality_declared,
                    "mandatory": e.mandatory,
                }
                for e in topology.edges
            ],
        },
        "warnings": drift + topology.warnings() + blueprint_warnings,
    }
    _emit(payload, output_format)


@discovery_conformance.command(name="validate")
@click.option(
    "--file",
    "artifact_file",
    type=click.Path(),
    default=None,
    help="Conformance artifact (default: <hub>/integration/discovery/"
    "core-concepts-conformance.yaml).",
)
@click.option(
    "--archetype",
    "archetype_id",
    default=None,
    help="Archetype id to validate identity/coverage/staleness against (DD-090, "
    "issue #308). Default: the artifact's own 'archetype.id' field.",
)
@click.option(
    "--allow-unresolved",
    is_flag=True,
    default=False,
    help="Do not fail when the artifact has unresolved AI-decided concept judgments "
    "(DD-148). Off by default — unresolved is unsafe everywhere, including CI.",
)
@click.option(
    "--domain",
    "domains",
    multiple=True,
    help="Restrict the unresolved-judgment check (DD-148) to concept(s) tagged to one or "
    "more domains, plus any cross-cutting concept (no 'likely_domains'). Repeatable. "
    "Omit to check the whole artifact, matching prior behavior (issue #389/#390).",
)
@_REFMODELS_OPTION
def conformance_validate(artifact_file, archetype_id, allow_unresolved, domains, refmodels_root):
    """Validate a conformance artifact against the shared outcome-codes enum."""
    from ..core.archetype_loader import (
        ArchetypeError,
        load_archetype,
        load_outcome_codes,
        load_valid_tiers,
    )
    from ..core.conformance_artifact import (
        ARTIFACT_RELPATH,
        ConformanceArtifactError,
        open_questions,
        read_artifact,
        validate_artifact,
    )
    from ..core.hub_utils import find_hub_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=False)
    if artifact_file:
        path = Path(artifact_file)
    elif hub_root:
        path = hub_root / ARTIFACT_RELPATH
    else:
        path = cwd / ARTIFACT_RELPATH

    root = _resolve_conformance_root(refmodels_root)
    try:
        artifact = read_artifact(path)
    except ConformanceArtifactError as exc:
        click.echo(f"❌ {exc}", err=True)
        raise SystemExit(2) from exc

    # #308 hole 1/2: resolve the archetype the artifact claims to conform to (explicit
    # --archetype, or falling back to the artifact's own 'archetype.id') so validate_artifact
    # can actually check identity/coverage/staleness instead of only shape/enum validity.
    resolved_archetype_id = archetype_id or (
        (artifact.get("archetype") or {}).get("id") if isinstance(artifact, dict) else None
    )
    archetype = None
    if isinstance(resolved_archetype_id, str) and resolved_archetype_id.strip():
        try:
            archetype = load_archetype(root, resolved_archetype_id)
        except ArchetypeError as exc:
            click.echo(f"❌ {exc}", err=True)
            raise SystemExit(2) from exc

    errors = validate_artifact(
        artifact, load_outcome_codes(root), load_valid_tiers(root), archetype=archetype
    )
    if errors:
        click.echo(f"❌ Conformance artifact invalid ({len(errors)} error(s)):", err=True)
        for e in errors:
            click.echo(f"   • {e}", err=True)
        raise SystemExit(1)

    if not allow_unresolved:
        questions = open_questions(artifact, domains=list(domains) or None)
        if questions:
            click.echo(
                f"❌ Conformance artifact has {len(questions)} unresolved AI-decided "
                "item(s) (DD-148) — a human must confirm these via kairos-design-discovery:",
                err=True,
            )
            for q in questions:
                tag = q.get("domains") or "cross-cutting"
                click.echo(
                    f"   • {q.get('label') or q.get('uri')} ({q['reason']}) [{tag}]", err=True
                )
            raise SystemExit(1)

    click.echo(f"✅ Conformance artifact valid: {path}", err=True)


@discovery_conformance.command(name="build")
@click.option("--archetype", "archetype_id", required=True, help="Archetype id to build against.")
@click.option(
    "--judgments-file",
    "judgments_file",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="YAML or JSON file with mode, core_concepts outcomes, and optional "
    "topology_confirmations/cardinality_answers. Scaffold one with "
    "`discovery-conformance judgments-template --archetype <id>` rather than "
    "hand-writing it. Per core_concepts entry: 'uri' and 'outcome' (one of the codes "
    "from `list-archetypes`' outcome_codes, e.g. conforms/conforms-with-rename/partial/"
    "deviates/not-applicable) are required; 'label'/'tier' are optional and derived from "
    "the archetype catalog when absent (a present-but-wrong value still fails validation); "
    "'confidence' must be a float between 0.0 and 1.0 (not 'high'/'medium'/'low' — that "
    "scale belongs to a different, unrelated field in _extractions/*.yaml) or omitted "
    "entirely.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(),
    default=None,
    help="Where to write the artifact (default: <hub>/integration/discovery/"
    "core-concepts-conformance.yaml).",
)
@click.option(
    "--validate/--no-validate",
    "run_validate",
    default=True,
    help="Run the same checks as `discovery-conformance validate` immediately after "
    "writing (default: on).",
)
@click.option(
    "--allow-unresolved",
    is_flag=True,
    default=False,
    help="Passed through to the post-build validation pass (DD-148); same meaning as "
    "`validate --allow-unresolved`.",
)
@click.option(
    "--domain",
    "domains",
    multiple=True,
    help="Passed through to the post-build validation pass (DD-148); same meaning as "
    "`validate --domain`. Repeatable.",
)
@_REFMODELS_OPTION
def conformance_build(
    archetype_id,
    judgments_file,
    output_path,
    run_validate,
    allow_unresolved,
    domains,
    refmodels_root,
):
    """Assemble, write, and (by default) validate a conformance artifact in one step.

    This is the CLI equivalent of calling ``build_artifact()``/``write_artifact()`` directly
    (issue #311): the judgments file's shape mirrors ``build_artifact()``'s own parameters
    (``mode``, ``core_concepts`` outcome dicts, optional ``topology_confirmations`` /
    ``cardinality_answers`` / ``discovery_doc`` / ``archetype_confirmed_by``) rather than
    inventing a new envelope, so a human or the kairos-design-discovery skill only ever
    has to write plain YAML/JSON, never a one-off Python script. Use
    ``discovery-conformance judgments-template --archetype <id>`` to scaffold that file
    instead of hand-writing or hand-scripting it (issue #410) — it pre-fills ``uri``/
    ``label``/``tier`` per concept from the archetype catalog, leaving only the business
    judgment fields (``outcome``, ``confidence``, ``rationale``, ...) to fill in.

    Each ``core_concepts`` entry needs a ``uri`` and an ``outcome`` (one of the codes
    published by ``list-archetypes``' ``outcome_codes`` — never hardcode ``high``/
    ``medium``/``low``, that is a different field's scale, e.g. visual-evidence
    ``confidence`` in ``_extractions/*.yaml``). ``label``/``tier`` are optional — when
    absent they are derived from the archetype's own catalog for that ``uri``; when
    present they must exactly match the catalog (a wrong value still fails validation,
    it is never silently accepted or silently corrected). ``confidence`` is optional and,
    when present, must be a float between ``0.0`` and ``1.0``.

    By default this also runs the same checks ``discovery-conformance validate`` runs, so
    a caller ends up with either a validated artifact or a clear failure — pass
    ``--no-validate`` to only write (a separate ``validate`` call, or a subsequent ``build``,
    can check it later).
    """
    import yaml

    from ..core.archetype_loader import (
        ArchetypeError,
        load_archetype,
        load_outcome_codes,
        load_valid_tiers,
        locate_discovery_doc,
        _refmodels_version,
    )
    from ..core.conformance_artifact import (
        build_artifact,
        derive_missing_identity,
        open_questions,
        validate_artifact,
        write_artifact,
    )
    from ..core.hub_utils import find_hub_root

    root = _resolve_conformance_root(refmodels_root)
    try:
        archetype = load_archetype(root, archetype_id)
    except ArchetypeError as exc:
        click.echo(f"❌ {exc}", err=True)
        raise SystemExit(2) from exc

    judgments_path = Path(judgments_file)
    try:
        judgments = yaml.safe_load(judgments_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        click.echo(f"❌ Could not parse judgments file {judgments_path}: {exc}", err=True)
        raise SystemExit(2) from exc

    if not isinstance(judgments, dict):
        click.echo(
            f"❌ Judgments file {judgments_path} must contain a mapping with at least "
            "'mode' and 'core_concepts' keys.",
            err=True,
        )
        raise SystemExit(2)

    core_concepts = judgments.get("core_concepts")
    if not isinstance(core_concepts, list):
        click.echo(
            f"❌ Judgments file {judgments_path} is missing a 'core_concepts' list "
            "(one outcome dict per archetype concept, e.g. {uri, outcome, tier, ...}).",
            err=True,
        )
        raise SystemExit(2)

    # #410: 'label'/'tier' are optional in the judgments file — derive them from the
    # already-resolved archetype's own catalog when a concept's entry omits them, so an
    # author only ever has to hand-write the actual business judgment. A present-but-wrong
    # value is left untouched (validate_artifact still catches it below).
    core_concepts = derive_missing_identity(core_concepts, archetype)

    discovery_doc = judgments.get("discovery_doc")
    if not discovery_doc:
        try:
            resolved_doc = locate_discovery_doc(root, archetype_id)
        except ArchetypeError as exc:
            click.echo(f"❌ {exc}", err=True)
            raise SystemExit(2) from exc
        discovery_doc = None
        if resolved_doc is not None:
            # Relative to the reference-models root, matching `conformance_load`'s own
            # fix (#313) and the real committed fixture convention -- an absolute,
            # machine-local path here would fail this same command's own default
            # post-write validation (#308/#313's validate_artifact absolute-path check).
            try:
                discovery_doc = resolved_doc.relative_to(root).as_posix()
            except ValueError:
                discovery_doc = resolved_doc.name

    refmodels_version = _refmodels_version(root)
    valid_tiers = load_valid_tiers(root)

    artifact = build_artifact(
        archetype=archetype,
        refmodels_version=refmodels_version,
        outcomes=core_concepts,
        mode=judgments.get("mode"),
        archetype_confirmed_by=judgments.get("archetype_confirmed_by", "human"),
        topology_confirmations=judgments.get("topology_confirmations"),
        cardinality_answers=judgments.get("cardinality_answers"),
        discovery_doc=discovery_doc,
        valid_tiers=valid_tiers,
    )

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=False)
    if output_path:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            yaml.safe_dump(artifact, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    else:
        out_path = write_artifact(hub_root or cwd, artifact)

    click.echo(f"✅ Wrote conformance artifact: {out_path}", err=True)

    if run_validate:
        errors = validate_artifact(
            artifact, load_outcome_codes(root), valid_tiers, archetype=archetype
        )
        if errors:
            click.echo(f"❌ Conformance artifact invalid ({len(errors)} error(s)):", err=True)
            for e in errors:
                click.echo(f"   • {e}", err=True)
            raise SystemExit(1)

        if not allow_unresolved:
            questions = open_questions(artifact, domains=list(domains) or None)
            if questions:
                click.echo(
                    f"❌ Conformance artifact has {len(questions)} unresolved AI-decided "
                    "item(s) (DD-148) — a human must confirm these via "
                    "kairos-design-discovery:",
                    err=True,
                )
                for q in questions:
                    tag = q.get("domains") or "cross-cutting"
                    click.echo(
                        f"   • {q.get('label') or q.get('uri')} ({q['reason']}) [{tag}]", err=True
                    )
                raise SystemExit(1)

        click.echo(f"✅ Conformance artifact valid: {out_path}", err=True)


@discovery_conformance.command(name="judgments-template")
@click.option(
    "--archetype", "archetype_id", required=True, help="Archetype id to scaffold a template for."
)
@click.option(
    "--mode",
    "session_mode",
    # Mirrors conformance_artifact.VALID_MODES (DD-088); kept as a literal here rather than
    # imported at module scope so this module's other commands can keep their established
    # lazy-import-inside-the-function convention.
    type=click.Choice(["interactive", "fleet"]),
    default="interactive",
    show_default=True,
    help="Session mode (DD-088) to pre-fill; edit if the actual session differs.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False),
    default=None,
    help="Where to write the template (default: echo to stdout).",
)
@click.option(
    "--overwrite", is_flag=True, default=False, help="Explicitly replace an existing file."
)
@_REFMODELS_OPTION
@_FORMAT_OPTION
@click.pass_context
def conformance_judgments_template(
    ctx, archetype_id, session_mode, output_path, overwrite, refmodels_root, output_format
):
    """Scaffold a ``build --judgments-file`` template, one entry per archetype concept.

    Phase 2.5 of ``kairos-design-discovery`` forbids hand-transcribing or hand-scripting the
    concept list (DD-090); before this command, the only way to learn the judgments-file
    contract was a failed ``build`` — three separate requirements (``label`` required,
    ``label`` must exactly equal the catalog label, ``confidence`` is a float 0.0-1.0, not
    ``high``/``medium``/``low``) were each discoverable only that way (issue #410). This
    projects ``load``'s own ``core_concepts`` (``uri``/``label``/``tier``, straight from the
    archetype catalog) into ``build``'s input envelope, leaving only the business-judgment
    fields for a human or the skill's interview to fill in.

    Fields an author must actually fill in (``outcome``, ``rationale``) carry an
    ``<CONFIRM_...>`` sentinel — the same family ``scaffold-binding``/``scaffold-staging``
    already use — so an unedited template is mechanically detectable via
    ``core.hub_utils.is_scaffold_placeholder_text``, not just documented convention.
    ``label``/``tier`` are pre-filled from the catalog and should not be edited; ``build``
    also derives them itself when a concept's entry omits them (issue #410), so they may be
    deleted from an entry instead of copied by hand.

    Per-outcome conditional fields (issue #461): the template pre-stubs
    ``deviation_reason`` and ``rename_to`` as null so they are discoverable before
    ``build`` fails. Set ``deviation_reason`` to a non-empty string when ``outcome``
    is ``deviates``. Set ``rename_to`` to a non-empty string when ``outcome`` is
    ``conforms-with-rename``. Both fields are only valid on their respective outcomes
    — a stray ``rename_to`` on ``conforms`` or a stray ``deviation_reason`` on
    ``conforms`` will fail validation.
    """
    from ..core.archetype_loader import ArchetypeError, load_archetype, load_outcome_codes
    from ..core.authoring_scaffolds import AuthoringScaffoldError, write_text
    from ..core.hub_utils import find_hub_root, strip_doubled_hub_segment

    root = _resolve_conformance_root(refmodels_root)
    try:
        archetype = load_archetype(root, archetype_id)
    except ArchetypeError as exc:
        click.echo(f"❌ {exc}", err=True)
        raise SystemExit(2) from exc

    outcome_codes = load_outcome_codes(root)
    outcome_sentinel = f"<CONFIRM_OUTCOME:{'|'.join(outcome_codes)}>"

    core_concepts = [
        {
            "uri": concept.uri,
            "label": concept.label,
            "tier": concept.tier,
            "outcome": outcome_sentinel,
            "confidence": None,
            "rationale": "<CONFIRM_RATIONALE>",
            "references": [],
            "needs_confirmation": False,
            "decided_by": "ai",
            "likely_domains": [],
            # Pre-stub the per-outcome conditional fields (issue #461) so authors
            # discover them before `build` fails: set deviation_reason when outcome is
            # "deviates"; set rename_to when outcome is "conforms-with-rename". Both
            # are null here — present-but-null makes the field discoverable without
            # triggering the "present-but-wrong" validation in build/validate.
            "deviation_reason": None,
            "rename_to": None,
        }
        for concept in archetype.core_concepts
    ]
    payload = {"mode": session_mode, "core_concepts": core_concepts}

    if output_path is None:
        _emit(payload, output_format)
        return

    effective_format = output_format
    fmt_source = ctx.get_parameter_source("output_format")
    if fmt_source == click.core.ParameterSource.DEFAULT:
        suffix = Path(output_path).suffix.lower()
        if suffix in (".yaml", ".yml"):
            effective_format = "yaml"
        elif suffix == ".json":
            effective_format = "json"
    elif output_path:
        suffix = Path(output_path).suffix.lower()
        ext_format = None
        if suffix in (".yaml", ".yml"):
            ext_format = "yaml"
        elif suffix == ".json":
            ext_format = "json"
        if ext_format is not None and ext_format != effective_format:
            click.echo(
                f"⚠️  --format {effective_format} does not match --output suffix "
                f"'{suffix}'; writing {effective_format}.",
                err=True,
            )

    if effective_format == "yaml":
        import yaml

        content = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    else:
        content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=False)
    out = Path(output_path)
    if hub_root and not out.is_absolute():
        out = strip_doubled_hub_segment(out, hub_root)
    destination = out if out.is_absolute() else ((hub_root / out) if hub_root else out)
    try:
        write_text(destination, content, overwrite=overwrite)
    except AuthoringScaffoldError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"✓ Wrote judgments-file template ({len(core_concepts)} concept(s)): {destination}",
        err=True,
    )


@discovery_conformance.command(name="summarize")
@click.option(
    "--file",
    "artifact_file",
    type=click.Path(),
    default=None,
    help="Conformance artifact (default: <hub>/integration/discovery/"
    "core-concepts-conformance.yaml).",
)
@click.option(
    "--judgments-file",
    "judgments_file",
    type=click.Path(),
    default=None,
    help="Optional judgments file whose core_concepts should be scored instead of the "
    "artifact's own. Tolerates <CONFIRM_OUTCOME:...> sentinels and absent label/tier "
    "fields — those entries are reported in an 'unfilled' bucket, never treated as errors.",
)
@click.option(
    "--outcome",
    "outcomes_filter",
    multiple=True,
    help="Restrict the scorecard to entries with the given outcome(s). Repeatable, e.g. "
    "--outcome accepted --outcome rejected.",
)
@_FORMAT_OPTION
def conformance_summarize(artifact_file, judgments_file, outcomes_filter, output_format):
    """Summarize conformance outcomes: scorecard, average confidence, open questions (DD-090).

    Loads a conformance artifact (or an optional ``--judgments-file``) and emits a
    machine-readable summary with:

    \\b
    - ``scorecard``: outcome counts (overall and by tier) from ``compute_scorecard``
    - ``average_confidence``: mean of per-concept ``confidence`` values (0.0-1.0)
    - ``needs_confirmation_count``: how many concepts have ``needs_confirmation: true``
    - ``open_questions``: unresolved AI-decided judgments from ``open_questions``
    - ``unfilled``: entries still carrying ``<CONFIRM_OUTCOME:...>`` sentinels or no outcome

    When ``--judgments-file`` is passed, the summary is computed on that file's
    ``core_concepts`` rather than the artifact's own — useful for previewing a
    template before ``build``. Unfilled entries are bucketed separately; they are
    first-class information, not an error.

    \\b
    Examples:
      kairos-ontology discovery-conformance summarize
      kairos-ontology discovery-conformance summarize --format yaml
      kairos-ontology discovery-conformance summarize --judgments-file template.yaml
    """
    from ..core.conformance_artifact import (
        ARTIFACT_RELPATH,
        ConformanceArtifactError,
        compute_scorecard,
        open_questions,
        read_artifact,
    )
    from ..core.hub_utils import find_hub_root, is_scaffold_placeholder_text

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=False)
    if artifact_file:
        artifact_path = Path(artifact_file)
    elif hub_root:
        artifact_path = hub_root / ARTIFACT_RELPATH
    else:
        artifact_path = cwd / ARTIFACT_RELPATH

    if judgments_file:
        import yaml

        judgments_path = Path(judgments_file)
        try:
            judgments = yaml.safe_load(judgments_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            click.echo(f"❌ Could not parse judgments file {judgments_path}: {exc}", err=True)
            raise SystemExit(2) from exc
        if not isinstance(judgments, dict):
            click.echo(
                f"❌ Judgments file {judgments_path} must contain a mapping.", err=True
            )
            raise SystemExit(2)
        concepts = judgments.get("core_concepts") or []
        artifact_data = None
    else:
        try:
            artifact_data = read_artifact(artifact_path)
        except ConformanceArtifactError as exc:
            click.echo(f"❌ {exc}", err=True)
            raise SystemExit(2) from exc
        concepts = artifact_data.get("core_concepts") or []

    concepts = [c for c in concepts if isinstance(c, dict)]

    # Separate unfilled entries from scored outcomes. An entry is "unfilled" when its
    # outcome is missing, a <CONFIRM_OUTCOME:...> sentinel, or otherwise a placeholder.
    unfilled: list[dict[str, Any]] = []
    scored: list[dict[str, Any]] = []
    for concept in concepts:
        outcome = concept.get("outcome")
        if outcome is None or (isinstance(outcome, str) and is_scaffold_placeholder_text(outcome)):
            unfilled.append(concept)
        else:
            scored.append(concept)

    if outcomes_filter:
        wanted = set(outcomes_filter)
        filtered = [c for c in scored if c.get("outcome", "unknown") in wanted]
    else:
        filtered = scored

    scorecard = compute_scorecard(filtered)

    confidences = [
        c["confidence"]
        for c in filtered
        if isinstance(c.get("confidence"), (int, float))
    ]
    average_confidence = sum(confidences) / len(confidences) if confidences else None

    needs_confirmation_count = sum(1 for c in filtered if c.get("needs_confirmation"))

    if artifact_data is not None:
        questions = open_questions(artifact_data)
    else:
        # A judgments file does not have an artifact envelope; reconstruct a minimal one
        # so open_questions can operate on it (it only reads core_concepts + decided_by).
        questions = open_questions({"core_concepts": scored})

    payload = {
        "scorecard": scorecard,
        "average_confidence": average_confidence,
        "needs_confirmation_count": needs_confirmation_count,
        "open_questions": questions,
        "unfilled": [
            {
                "uri": c.get("uri"),
                "label": c.get("label"),
                "tier": c.get("tier"),
                "outcome": c.get("outcome"),
            }
            for c in unfilled
        ],
        "unfilled_count": len(unfilled),
    }
    _emit(payload, output_format)


@click.command(name="build-glossary")
@click.option(
    "--extraction-dir",
    type=click.Path(),
    default=None,
    help="Path to businessdiscovery/_extractions/ (default: auto-detect from hub).",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(),
    default=None,
    help="Output glossary TTL path (default: businessdiscovery/{company}-glossary.ttl).",
)
@click.option(
    "--company-domain",
    "company_domain",
    type=str,
    default=None,
    help="Company domain (e.g. acme.com). Default: auto-detect from hub README.",
)
@click.option(
    "--company-name",
    "company_name",
    type=str,
    default=None,
    help="Company display name for the scheme label. Default: auto-detect from hub README.",
)
@click.option(
    "--glossary-namespace",
    "glossary_namespace",
    type=str,
    default=None,
    help="Glossary namespace IRI. Default: https://{company-domain}/glossary#.",
)
@click.option(
    "--company-specific-only",
    is_flag=True,
    default=False,
    help="Only include terms flagged company_specific in the extractions.",
)
def build_glossary_cmd(
    extraction_dir,
    output_path,
    company_domain,
    company_name,
    glossary_namespace,
    company_specific_only,
):
    """Build the SKOS company glossary TTL from confirmed extractions (DD-062).

    Deterministic, AI-free serializer for the ``kairos-design-discovery`` skill:
    reads the per-document extraction files under ``businessdiscovery/_extractions/``
    and aggregates their ``extracted_terms`` into a SKOS ``ConceptScheme`` glossary
    overlay.  Terms are grouped by their resolved ``linked_iri`` (or ``prefLabel``),
    ``altLabel`` values are deduplicated, and ``linked_iri`` becomes ``rdfs:seeAlso``
    (or ``skos:relatedMatch`` when the term sets ``link_relation: relatedMatch``).

    The domain ontology is never touched — this writes only the glossary overlay.

    \\b
    Examples:
      kairos-ontology build-glossary
      kairos-ontology build-glossary --company-specific-only
      kairos-ontology build-glossary --company-domain acme.com --output glossary.ttl
    """
    from ..core.glossary_builder import build_glossary, derive_glossary_namespace, read_company_info
    from ..core.hub_utils import find_hub_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=False)

    if extraction_dir:
        ext_path = Path(extraction_dir)
    elif hub_root:
        ext_path = hub_root / "businessdiscovery" / "_extractions"
    else:
        ext_path = cwd / "businessdiscovery" / "_extractions"

    # Resolve company name + domain (CLI flags win, else parse the hub README).
    readme_name, readme_domain = (None, None)
    if hub_root and (not company_name or not company_domain):
        readme_name, readme_domain = read_company_info(hub_root)
    company_name = company_name or readme_name
    company_domain = company_domain or readme_domain

    if not glossary_namespace:
        if not company_domain:
            click.echo(
                "❌ Could not determine the company domain. Pass --company-domain "
                "or --glossary-namespace (no hub README value found).",
                err=True,
            )
            raise SystemExit(1)
        glossary_namespace = derive_glossary_namespace(company_domain)

    scheme_label = f"{company_name} Business Glossary" if company_name else "Business Glossary"
    scheme_description = (
        "Company-specific terminology overlay for source-to-domain mapping. "
        "Does not modify the domain ontology."
    )

    if output_path:
        out_path = Path(output_path)
    else:
        slug = (company_domain.split(".")[0] if company_domain else "company").lower()
        base = hub_root / "businessdiscovery" if hub_root else cwd / "businessdiscovery"
        out_path = base / f"{slug}-glossary.ttl"

    click.echo("🛠  Building business glossary")
    click.echo(f"   Extraction dir: {ext_path}")
    click.echo(f"   Namespace:      {glossary_namespace}")
    click.echo(f"   Output:         {out_path}")

    if not ext_path.is_dir():
        click.echo(
            "   ⚠ No _extractions/ directory found — run the kairos-design-discovery "
            "skill first to extract terminology.",
            err=True,
        )
        raise SystemExit(1)

    result = build_glossary(
        extraction_dir=ext_path,
        output_path=out_path,
        glossary_namespace=glossary_namespace,
        scheme_label=scheme_label,
        scheme_description=scheme_description,
        company_specific_only=company_specific_only,
    )

    click.echo(
        f"   ✓ Wrote {len(result.concepts)} concept(s) from "
        f"{len(result.sources)} extraction file(s)."
    )
    if result.excluded_sources:
        # C4/#417/#416b: `status: skipped` extraction files are excluded — the
        # document was never actually read, so its `extracted_terms` (if any)
        # would be stale/hypothetical rather than confirmed evidence.
        click.echo(
            f"   ⏭ Excluded {len(result.excluded_sources)} extraction file(s) with status: skipped."
        )
    if result.skipped_terms:
        click.echo(f"   ⏭ Skipped {result.skipped_terms} term(s) (no prefLabel or filtered).")
    click.echo("\n✅ Glossary built.")


@click.command(name="list-patterns")
@click.option(
    "--pattern",
    "pattern_id",
    default=None,
    help="Load a single pattern by id instead of the whole library.",
)
@click.option(
    "--coverage",
    "coverage",
    is_flag=True,
    default=False,
    help="Print the toolkit's enforcement-coverage ledger instead of the pattern bodies.",
)
@_REFMODELS_OPTION
@_FORMAT_OPTION
def list_patterns_cmd(pattern_id, coverage, refmodels_root, output_format):
    """Surface the reference-models pattern library for the design-domain skill (#262 §3).

    Emits sector-neutral modelling craft — normative naming conventions and anti-patterns
    for recurring shapes (temporal quartets, qualified roles, governed code lists,
    deferred relationships) — so ``kairos-design-domain`` prefers the shared vocabulary
    when naming properties instead of inventing synonyms.  This is advisory,
    authoring-time guidance, deliberately separate from the ``discovery-conformance``
    concept flow.  Human progress goes to stderr; stdout is machine output only.

    ``--coverage`` prints the toolkit-owned ledger instead: every normative unit the library
    publishes, mapped to ``enforced_by`` a diagnostic, ``not_enforceable`` with a stated
    reason, or ``unrecognized_shape``.  It is a record, not a gate — it enforces nothing and
    never changes the exit code.

    \\b
    Examples:
      kairos-ontology list-patterns
      kairos-ontology list-patterns --pattern temporal-quartet
      kairos-ontology list-patterns --coverage
    """
    from ..core.pattern_loader import (
        PatternError,
        load_pattern,
        load_patterns,
        pattern_quality_warnings,
    )
    from ..core.pattern_rules import build_ledger

    root = _resolve_conformance_root(refmodels_root)
    click.echo(f"🔎 Reference-models root: {root}", err=True)

    if pattern_id:
        try:
            pattern = load_pattern(root, pattern_id)
        except PatternError as exc:
            click.echo(f"❌ {exc}", err=True)
            raise SystemExit(2) from exc
        quality = pattern_quality_warnings(pattern)
        for w in quality:
            click.echo(f"⚠ {w}", err=True)
        if coverage:
            _emit_pattern_coverage(root, build_ledger([pattern], quality), output_format)
            return
        _emit(
            {
                "refmodels_root": str(root),
                "pattern": pattern.to_payload(),
                "warnings": quality,
            },
            output_format,
        )
        return

    patterns, warnings = load_patterns(root)
    for w in warnings:
        click.echo(f"⚠ {w}", err=True)
    if not patterns:
        click.echo(
            "⚠ No patterns found — this reference-models checkout has no "
            "'blueprints/patterns/' library.",
            err=True,
        )
    if coverage:
        _emit_pattern_coverage(root, build_ledger(patterns, warnings), output_format)
        return
    _emit(
        {
            "refmodels_root": str(root),
            "patterns": [p.to_payload() for p in patterns],
            "warnings": warnings,
        },
        output_format,
    )


def _emit_pattern_coverage(root, ledger, output_format):
    """Write the coverage ledger: a stderr summary for humans, the ledger on stdout.

    Gates nothing.  An empty ``enforced_by`` column, an ``unrecognized_shape`` unit and a
    skipped pattern are all *reported*, never fatal — the point of the ledger is that the
    toolkit's reach is written down, not that it is large.
    """
    totals = ledger.totals
    click.echo(
        f"📒 Pattern coverage: {totals['units']} normative unit(s) across "
        f"{len(ledger.patterns_seen)} pattern(s) — "
        f"{totals['enforced_by']} enforced_by, "
        f"{totals['not_enforceable']} not_enforceable, "
        f"{totals['unrecognized_shape']} unrecognized_shape.",
        err=True,
    )
    for entry in ledger.entries:
        if entry.classification == "enforced_by":
            click.echo(
                f"   ✓ {entry.pattern}/{entry.unit} → {entry.diagnostic_code} (home: {entry.home})",
                err=True,
            )
    for entry in ledger.entries:
        if entry.classification == "unrecognized_shape":
            click.echo(
                f"   ? {entry.pattern}/{entry.key}/{entry.unit} — no registered "
                "classification (new or reshaped upstream)",
                err=True,
            )
    for stale in ledger.stale_registry_entries:
        click.echo(f"   ⚠ registry entry '{stale}' matches no published unit", err=True)
    payload = {"refmodels_root": str(root)}
    payload.update(ledger.to_payload())
    _emit(payload, output_format)
