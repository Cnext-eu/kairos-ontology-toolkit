# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused validation CLI commands."""

import json
import click
from pathlib import Path


from ..core.validator import run_validation, run_gdpr_validation
from ..core.catalog_test import test_catalog_resolution
from ..core.conformance_artifact import check_discovery_gate

# Importing the design-time MDM package registers the additive ``mdm-profile``
# projection target with the core projector (registry pattern, MDM-DD-002).
# The CLI is the layer that legitimately depends on both core and mdm.
from .. import mdm as _mdm  # noqa: F401  (import for side-effect: target registration)

from .shared import (
    _ontology_domain_hints,
    _resolve_catalog,
    _resolve_ref_models_dir,
)


@click.command(name="validate-dbt")
@click.option(
    "--platform",
    type=click.Choice(["fabric", "databricks"]),
    default=None,
    help="Adapter used to parse and compile the generated project. Required "
    "unless --structural-only is set (the structural scan needs no adapter).",
)
@click.option(
    "--project-dir",
    type=click.Path(path_type=Path),
    help="dbt project directory (default: <repo>/ontology-hub-publish/medallion/dbt).",
)
@click.option(
    "--profiles-dir",
    type=click.Path(path_type=Path),
    help="Optional directory containing a non-committed profiles.yml.",
)
@click.option(
    "--structural-only",
    is_flag=True,
    help="Run only the offline ref()-vs-model scan; skip dbt deps/parse/compile "
    "entirely. Needs no dbt install — for CI gates that want #342-shaped dangling "
    "cross-domain refs caught without paying for a real dbt adapter.",
)
def validate_dbt_cmd(platform, project_dir, profiles_dir, structural_only):
    """Run structural, dependency, parse, graph, and compile validation for dbt.

    The structural dangling-``ref()`` scan runs first and needs no dbt install;
    the remaining phases still require `dbt` itself, unless --structural-only.
    """
    from ..core.dbt_validation import DbtValidationError, validate_dbt_project
    from ..core.hub_utils import find_hub_root, publish_root

    if platform is None:
        if not structural_only:
            raise click.UsageError("--platform is required unless --structural-only is set")
        platform = "fabric"  # inert placeholder; structural-only never invokes an adapter

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=False) or cwd

    def resolve(value, default):
        path = Path(value) if value is not None else default
        return path if path.is_absolute() else hub_root / path

    project = resolve(project_dir, publish_root(hub_root) / "medallion" / "dbt")
    profiles = resolve(profiles_dir, None) if profiles_dir is not None else None
    try:
        result = validate_dbt_project(
            project,
            platform,
            profiles_dir=profiles,
            structural_only=structural_only,
        )
    except DbtValidationError as exc:
        # This conversion to ClickException is what keeps one dbt-phase failure
        # to a single structured-log record: events.py's timed_phase() already
        # ERROR-logs DBT_PHASE_FAILED (core/dbt_validation.py:312,324,339) and
        # re-raises; ClickException is exempted from the DD-151 unhandled-
        # exception boundary in cli/main.py's _KairosGroup, so it is never
        # logged a second time. If this conversion is ever removed, the
        # boundary would log the same failure again as `exception.*`.
        raise click.ClickException(str(exc)) from exc

    click.echo("✓ structural ref() scan passed (no dangling cross-domain refs)")
    if result.compile_status == "skipped":
        return
    click.echo(f"✓ dbt deps and parse passed for {platform}")
    click.echo(f"✓ manifest graph validated: {result.manifest_path}")
    if result.compile_status == "passed":
        click.echo("✓ dbt compile passed")
    else:
        click.echo(f"⚠ dbt compile environment-blocked: {result.compile_message}")


@click.command()
@click.option(
    "--ontologies",
    type=click.Path(exists=True),
    default=None,
    help="Path to ontologies directory (default: auto-detect from hub).",
)
@click.option(
    "--shapes",
    type=click.Path(),
    default=None,
    help="Path to SHACL shapes directory (default: auto-detect from hub; "
    "optional — SHACL is skipped if it does not exist).",
)
@click.option(
    "--catalog",
    type=click.Path(exists=True),
    default=None,
    help="Path to catalog file for resolving imports "
    "(default: <hub>/catalog-v001.xml or "
    "ontology-reference-models/catalog-v001.xml)",
)
@click.option(
    "--ref-models",
    type=click.Path(),
    default=None,
    help="Reference-model repository containing accelerator module profiles.",
)
@click.option(
    "--accelerator",
    default=None,
    help="Accelerator pack used for managed-import completeness checks.",
)
@click.option(
    "--all", "validate_all", is_flag=True, help="Validate all: syntax + SHACL + consistency"
)
@click.option(
    "--domain",
    default=None,
    help="Data domain to resolve the accelerator against (parity with compile). "
    "When omitted, domains are inferred from the ontology file stems.",
)
@click.option(
    "--syntax",
    is_flag=True,
    help="Validate syntax and naming; also verifies managed import completeness "
    "whenever reference models are present (DD-155).",
)
@click.option("--shacl", is_flag=True, help="Validate SHACL only")
@click.option("--consistency", is_flag=True, help="Validate consistency only")
@click.option(
    "--gdpr", is_flag=True, help="Scan for PII properties without GDPR satellite protection"
)
@click.option(
    "--ddd",
    "ddd",
    is_flag=True,
    help="Validate DDD design overlays (*-ddd-ext.ttl) via the dedicated DDD path",
)
@click.option(
    "--degraded",
    is_flag=True,
    default=False,
    help="Explicitly allow incomplete ontology imports for semantic validation; "
    "results are marked import_complete=false.",
)
@click.option(
    "--report-format",
    "--format",
    type=click.Choice(["json", "markdown", "both", "none"]),
    default="json",
    show_default=True,
    help="Validation report format(s) to write. Additive: the default preserves "
    "the pre-existing JSON-only report contract at "
    "<repo>/ontology-hub-publish/validation-report.json unchanged. Pass 'none' "
    "to run validation without writing any report file at all.",
)
@click.option(
    "--report-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Explicit report output path. Only valid with a single --report-format "
    "(json or markdown) — --report-format both always writes the default "
    "validation-report.json and validation-report.md under "
    "<repo>/ontology-hub-publish/, and --report-format none writes no report "
    "at all, so --report-path is rejected with either.",
)
def validate(
    ontologies,
    shapes,
    catalog,
    ref_models,
    accelerator,
    validate_all,
    syntax,
    domain,
    shacl,
    consistency,
    gdpr,
    ddd,
    degraded,
    report_format,
    report_path,
):
    """Validate ontologies (syntax, SHACL, consistency, GDPR PII scan, DDD overlays)."""
    from ..core.hub_utils import find_hub_root, publish_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=False)

    if ontologies is not None:
        ontologies_path = Path(ontologies)
    elif hub_root is not None:
        ontologies_path = hub_root / "model" / "ontologies"
    else:
        ontologies_path = cwd / "ontology-hub" / "model" / "ontologies"

    if not ontologies_path.is_dir():
        click.echo(
            f"❌ Cannot find ontologies directory at {ontologies_path}. "
            "Run from the hub root (or inside ontology-hub/), or pass --ontologies.",
            err=True,
        )
        raise SystemExit(1)

    effective_hub_root = hub_root if hub_root is not None else cwd / "ontology-hub"
    # Domain-scoped (issue #389/#390): an unresolved DD-148 judgment tagged to a domain
    # other than the one being validated no longer blocks this narrower check. Deliberately
    # NOT falling back to `_ontology_domain_hints(ontologies_path)` when --domain is omitted
    # (unlike the accelerator-resolution call below) — that helper only returns domain stems
    # already modeled in the hub, which would silently weaken whole-hub validation for any
    # judgment tagged to a domain with no TTL yet (the common case). Passing domains=None
    # here when --domain is omitted preserves today's whole-hub gating exactly.
    discovery_errors = check_discovery_gate(
        effective_hub_root, domains=[domain] if domain else None
    )
    if discovery_errors:
        for error in discovery_errors:
            click.echo(f"❌ {error}", err=True)
        raise SystemExit(1)

    if shapes is not None:
        shapes_path = Path(shapes)
    elif hub_root is not None:
        shapes_path = hub_root / "model" / "shapes"
    else:
        shapes_path = cwd / "ontology-hub" / "model" / "shapes"

    ref_models_path = Path(ref_models) if ref_models else _resolve_ref_models_dir(cwd, hub_root)
    catalog_path = _resolve_catalog(catalog, hub_root, cwd, ref_models_path)
    from ..core.reference_modules import resolve_hub_accelerator_detailed

    try:
        accelerator_resolution = resolve_hub_accelerator_detailed(
            explicit=accelerator,
            hub_root=hub_root,
            ref_models_dir=ref_models_path,
            domain_hint=[domain] if domain else _ontology_domain_hints(ontologies_path),
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    accelerator = accelerator_resolution.accelerator
    if ref_models_path is not None:
        click.echo(
            f"   Accelerator:  {accelerator or '(none)'} (source: {accelerator_resolution.source})"
        )
        if accelerator_resolution.data_domains_path is not None:
            click.echo(f"   Data domains: {accelerator_resolution.data_domains_path}")

    if report_path is not None and report_format in ("both", "none"):
        raise click.ClickException(
            "--report-path requires --report-format json or markdown (not 'both' or "
            "'none'); 'both' always writes validation-report.json and "
            "validation-report.md under <repo>/ontology-hub-publish/, and 'none' "
            "writes no report at all."
        )

    # Report destination: always the publish root (repo-root sibling), never the
    # process CWD (mirrors the `project` command's output_path resolution below).
    output_dir = (
        publish_root(hub_root) if hub_root is not None else publish_root(cwd / "ontology-hub")
    )
    decisions_path = (
        hub_root / "decisions" if hub_root is not None else cwd / "ontology-hub" / "decisions"
    )
    json_report_path = None
    markdown_report_path = None
    if report_format in ("json", "both"):
        json_report_path = (
            Path(report_path)
            if (report_path is not None and report_format == "json")
            else output_dir / "validation-report.json"
        )
    if report_format in ("markdown", "both"):
        markdown_report_path = (
            Path(report_path)
            if (report_path is not None and report_format == "markdown")
            else output_dir / "validation-report.md"
        )
    if report_format == "none":
        click.echo("   Report: skipped (--report-format none)")

    # Default to all if nothing specified
    if not any([validate_all, syntax, shacl, consistency, gdpr, ddd]):
        validate_all = True

    gdpr_warning_count = 0
    if gdpr or validate_all:
        gdpr_warning_count = (
            run_gdpr_validation(
                ontologies_path=ontologies_path,
                catalog_path=catalog_path,
                hub_root=effective_hub_root,
            )
            or 0
        )
        if gdpr and not any([validate_all, syntax, shacl, consistency, ddd]):
            return  # GDPR-only mode

    # DDD overlay validation (DD-091) — dedicated path (merged domain + overlay).
    ddd_failures = 0
    if ddd or validate_all:
        from ..core.ddd import run_ddd_validation

        extensions_path = ontologies_path.parent / "extensions"
        ddd_failures = run_ddd_validation(
            extensions_dir=extensions_path,
            ontologies_dir=ontologies_path,
            catalog_path=catalog_path,
        )
        if ddd and not any([validate_all, syntax, shacl, consistency]):
            if ddd_failures:
                raise SystemExit(1)
            return  # DDD-only mode

    run_validation(
        ontologies_path=ontologies_path,
        shapes_path=shapes_path,
        catalog_path=catalog_path,
        do_syntax=validate_all or syntax,
        do_shacl=validate_all or shacl,
        do_consistency=validate_all or consistency,
        report_path=json_report_path,
        degraded=degraded,
        ref_models_dir=ref_models_path,
        accelerator=accelerator,
        markdown_report_path=markdown_report_path,
        decisions_path=decisions_path,
        gdpr_warnings=gdpr_warning_count,
    )

    # run_validation() exits non-zero on its own failures; if it fell through
    # (its checks passed) but DDD overlays failed, still fail the overall run.
    if ddd_failures:
        raise SystemExit(1)


@click.command(name="mdm-validate")
@click.option(
    "--ontologies",
    type=click.Path(exists=True),
    default=None,
    help="Path to ontologies directory (default: auto-detect from hub).",
)
@click.option(
    "--catalog",
    type=click.Path(exists=True),
    default=None,
    help="Path to catalog file for resolving imports.",
)
def mdm_validate(ontologies, catalog):
    """Validate MDM extension policy (``*-mdm-ext.ttl``) for each domain.

    Structural design-time gate: checks controlled enumerations, thresholds, match
    rules, DQ dimensions and the probabilistic-artifact reference before the
    ``mdm-profile`` projection is trusted. Prefer the **kairos-design-mdm** skill,
    which wraps this with interactive authoring guidance.
    """
    from ..core.hub_utils import find_hub_root
    from ..core.ontology_loader import SemanticProfile, load_ontology
    from ..core.projections.shared import merge_ext_graph
    from ..mdm.vocabulary import discover_mdm_extension
    from ..mdm.validation import validate_mdm_extension

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=False)

    if ontologies is not None:
        ontologies_path = Path(ontologies)
    elif hub_root is not None:
        ontologies_path = hub_root / "model" / "ontologies"
    else:
        ontologies_path = cwd / "ontology-hub" / "model" / "ontologies"

    if not ontologies_path.is_dir():
        click.echo(
            f"❌ Cannot find ontologies directory at {ontologies_path}. "
            "Run from the hub root (or inside ontology-hub/), or pass --ontologies.",
            err=True,
        )
        raise SystemExit(1)

    extensions_dir = ontologies_path.parent / "extensions"
    catalog_path = _resolve_catalog(catalog, hub_root, cwd)

    onto_files = sorted(
        p
        for p in ontologies_path.glob("*.ttl")
        if not p.stem.endswith("-ext") and not p.stem.startswith("_")
    )
    if not onto_files:
        click.echo(f"No ontology files found in {ontologies_path}.")
        return

    total_errors = 0
    checked = 0
    for onto_file in onto_files:
        onto_name = onto_file.stem
        ext_path = discover_mdm_extension(onto_name, onto_file, extensions_dir)
        if ext_path is None:
            continue  # no MDM policy for this domain — nothing to validate
        checked += 1
        result = load_ontology(
            onto_file,
            catalog_path=catalog_path,
            profile=SemanticProfile.KAIROS_DESIGN,
        )
        base_graph = result.graph
        merged = merge_ext_graph(base_graph, ext_path)

        report = validate_mdm_extension(merged)
        icon = "✅" if report["passed"] else "❌"
        click.echo(f"{icon} {onto_name} ({ext_path.name})")
        for err in report["errors"]:
            click.echo(f"    ✗ {err}", err=True)
            total_errors += 1
        for warn in report["warnings"]:
            click.echo(f"    ⚠ {warn}")

    if checked == 0:
        click.echo("No *-mdm-ext.ttl extensions found — nothing to validate.")
        return

    if total_errors:
        click.echo(f"\n❌ MDM validation failed with {total_errors} error(s).", err=True)
        raise SystemExit(1)
    click.echo(f"\n✅ MDM validation passed for {checked} domain(s).")


@click.command(name="catalog-test")
@click.option(
    "--catalog", type=click.Path(exists=True), required=True, help="Path to catalog file to test"
)
@click.option(
    "--ontology", type=click.Path(exists=True), help="Optional: test with specific ontology file"
)
def catalog_test_cmd(catalog, ontology):
    """Test catalog resolution for imports."""
    catalog_path = Path(catalog)
    ontology_path = Path(ontology) if ontology else None

    passed = test_catalog_resolution(catalog_path, ontology_path)
    if not passed:
        raise SystemExit(1)


@click.command(name="validate-mapping")
@click.option("--domain", required=True)
@click.option(
    "--mapping",
    "mappings",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False),
)
@click.option("--catalog", type=click.Path(exists=True, dir_okay=False), default=None)
def validate_mapping_cmd(domain, mappings, catalog):
    """Validate one domain's named mapping contracts and IRI resolution."""
    from ..core.design_validation import validate_mapping_design
    from ..core.hub_utils import find_hub_root

    hub = find_hub_root(Path.cwd(), require_model=True)
    if hub is None:
        raise click.ClickException("Cannot locate an ontology hub.")
    if mappings:
        paths = tuple(Path(item) for item in mappings)
    else:
        mapping_dir = hub / "model" / "mappings"
        paths = tuple(sorted(mapping_dir.glob(f"*{domain}*.ttl")))
    if not paths:
        raise click.ClickException(
            f"No scoped mapping files found for domain {domain!r}; pass --mapping explicitly."
        )
    result = validate_mapping_design(
        mapping_paths=paths,
        source_root=hub / "integration" / "sources",
        ontology_path=hub / "model" / "ontologies" / f"{domain}.ttl",
        catalog_path=Path(catalog) if catalog else None,
    )
    click.echo(json.dumps(result, indent=2, sort_keys=True))
    if not result["passed"]:
        raise click.exceptions.Exit(1)


@click.command(name="validate-silver-ext")
@click.option("--domain", required=True)
@click.option(
    "--catalog",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
)
@click.option(
    "--shapes",
    "shapes_override",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help=(
        "Override the Silver-ext SHACL shape file. Defaults to the hub-local "
        "managed shape, then the packaged canonical shape."
    ),
)
def validate_silver_ext_cmd(domain, catalog, shapes_override):
    """Check one legacy Silver extension without granting v5 authority."""
    from ..core.design_validation import (
        resolve_silver_ext_shapes,
        validate_silver_extension,
    )
    from ..core.hub_utils import find_hub_root

    cwd = Path.cwd()
    hub = find_hub_root(cwd, require_model=True)
    if hub is None:
        raise click.ClickException("Cannot locate an ontology hub.")
    catalog_path = _resolve_catalog(
        catalog,
        hub_root=hub,
        cwd=cwd,
        ref_models_dir=_resolve_ref_models_dir(cwd, hub),
    )
    if shapes_override is not None:
        shapes_path: Path = shapes_override
        shape_source = "override"
    else:
        shapes_path, shape_source = resolve_silver_ext_shapes(hub)
        if shapes_path is None:
            raise click.ClickException(
                "No Silver-ext SHACL shape found: hub-local "
                "model/shapes/kairos-ext-shapes.shacl.ttl is absent and no packaged "
                "canonical shape is available. Run 'kairos-ontology update' or pass "
                "--shapes."
            )
    click.echo(
        f"Using Silver-ext shapes: {shapes_path} (source: {shape_source})",
        err=True,
    )
    result = validate_silver_extension(
        extension_path=hub / "model" / "extensions" / f"{domain}-silver-ext.ttl",
        ontology_path=hub / "model" / "ontologies" / f"{domain}.ttl",
        shapes_path=shapes_path,
        catalog_path=catalog_path,
    )
    click.echo(json.dumps(result, indent=2, sort_keys=True))
    if not result["passed"]:
        raise click.exceptions.Exit(1)


@click.command("suggest-shapes")
@click.option(
    "--source",
    type=click.Path(exists=True),
    default=None,
    help="Path to a bronze source vocabulary TTL (e.g. "
    "<system>.vocabulary.ttl). Default: auto-detect single vocabulary.",
)
@click.option(
    "--mappings",
    type=click.Path(exists=True),
    default=None,
    help="Optional SKOS mappings TTL (reserved for domain-targeted shapes).",
)
@click.option(
    "--out",
    "-o",
    type=click.Path(),
    default=None,
    help="Output draft TTL path (default: <repo>/ontology-hub-publish/shapes-draft/<name>.ttl).",
)
@click.option(
    "--enum-distinct-max",
    type=int,
    default=12,
    help="Max distinct values to emit an sh:in enum (default: 12).",
)
@click.option(
    "--no-sample-values",
    "no_sample_values",
    is_flag=True,
    default=False,
    help="Suppress masked example values in shape comments (PII is always masked).",
)
@click.option(
    "--force", is_flag=True, default=False, help="Overwrite an existing draft shapes file."
)
def suggest_shapes_cmd(source, mappings, out, enum_distinct_max, no_sample_values, force):
    """DD-076: generate a DRAFT SHACL file from bronze source profiling metadata.

    Produces advisory PropertyShapes (datatype always; format pattern, nullability
    minCount, and distinctCount-backed enums when reliable evidence exists) that a
    human reviews and promotes into model/shapes/. PII values are never enumerated
    and are always masked. Output is written outside the loaded shapes directory so
    the validator does not pick it up automatically.

    \b
    Examples:
      kairos-ontology suggest-shapes
      kairos-ontology suggest-shapes --source integration/sources/crm/crm.vocabulary.ttl
    """
    from ..core.suggest_shapes import suggest_shapes
    from ..core.hub_utils import find_hub_root, publish_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd)
    base = hub_root or cwd

    # Auto-detect the source vocabulary when not provided.
    if source is None:
        sources_dir = base / "integration" / "sources"
        candidates = sorted(sources_dir.glob("**/*.vocabulary.ttl")) if sources_dir.is_dir() else []
        if not candidates:
            click.echo(
                "❌ No source vocabulary found under integration/sources/. "
                "Run 'kairos-ontology import-source' first, or pass --source.",
                err=True,
            )
            raise SystemExit(1)
        if len(candidates) > 1:
            click.echo(
                "❌ Multiple source vocabularies found; specify one with --source:",
                err=True,
            )
            for c in candidates:
                click.echo(f"   - {c}", err=True)
            raise SystemExit(1)
        source_path = candidates[0]
    else:
        source_path = Path(source)

    # Default output: <repo>/ontology-hub-publish/shapes-draft/<name>.ttl (outside model/shapes).
    if out is None:
        name = source_path.name.replace(".vocabulary.ttl", "").replace(".ttl", "")
        pub = publish_root(hub_root or cwd / "ontology-hub")
        out_path = pub / "shapes-draft" / f"{name}.ttl"
    else:
        out_path = Path(out)

    click.echo("🔶 Suggesting draft SHACL shapes from source profiling")
    click.echo(f"   Source: {source_path}")
    click.echo(f"   Output: {out_path}")
    click.echo()

    try:
        written = suggest_shapes(
            source_path,
            out_path,
            enum_distinct_max=enum_distinct_max,
            include_sample_values=not no_sample_values,
            force=force,
        )
    except FileExistsError as e:
        click.echo(f"❌ {e}", err=True)
        raise SystemExit(1)

    click.echo(f"✅ Draft shapes written: {written}")
    click.echo(
        "⚠ DRAFT — review and edit before moving into model/shapes/. "
        "These are advisory and require human confirmation."
    )
