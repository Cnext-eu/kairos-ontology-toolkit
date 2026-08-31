# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Click surface for ``kairos-ontology promote-transform`` (issue #634)."""

from __future__ import annotations

from pathlib import Path

import click


@click.command(name="promote-transform")
@click.argument(
    "sql_path", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option(
    "--domain", required=True, help="Hub domain to promote the model into."
)
@click.option(
    "--properties",
    "properties_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Explicit properties YAML file holding this model's entry. Default: "
    "auto-discover next to sql_path (and its parent directories); fails closed "
    "if the model's name is found in more than one candidate file.",
)
@click.option(
    "--force", is_flag=True, default=False, help="Overwrite existing destination files."
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be written (and that validation would run) without "
    "writing any file.",
)
@click.option(
    "--hub-root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Explicit ontology-hub root. Default: auto-discover from the current "
    "directory (find_hub_root), the same resolution 'validate-dbt-contracts' uses.",
)
def promote_transform_cmd(sql_path, domain, properties_path, force, dry_run, hub_root):
    """Promote a dataplatform-authored contracted dbt model into the hub (issue #634).

    Run this from within a dataplatform repo, after developing and testing SQL_PATH as an
    ordinary local dbt model (``dbt build``/``dbt test`` against seed data) -- the same
    ``int_merged__<entity>``/``int_<source>__<entity>`` shape
    kairos-develop-dbt-transformation documents, with ``contract: {enforced: true}`` and a
    ``meta.kairos`` block, just authored outside the hub.

    Copies (never moves -- SQL_PATH and its properties YAML are never touched) the model's
    SQL and just its own properties-YAML entry into
    ``<hub>/integration/transforms/dbt/models/intermediate/<domain>/``, then runs the same
    offline contract validator ``validate-dbt-contracts`` runs. A validation failure deletes
    both just-written files (rollback) so an invalid model is never left in the hub tree.

    Does **not** wire the EntityBinding's ``source.dbtModel`` or record a Decision Log entry
    -- both remain manual follow-up steps for the binding author.

    \b
    Examples:
      kairos-ontology promote-transform models/int_merged__party.sql --domain party
      kairos-ontology promote-transform models/int_merged__party.sql --domain party \\
          --properties models/_party__models.yml
      kairos-ontology promote-transform models/int_merged__party.sql --domain party \\
          --dry-run
    """
    from ..core.hub_utils import find_hub_root
    from ..core.promote_transform import (
        PromoteTransformError,
        PromoteTransformValidationError,
        run_promote_transform,
    )
    from .shared import _resolve_catalog, resolve_refmodels_dir
    from .validation import _hub_class_resolver

    cwd = Path.cwd()
    resolved_hub_root = Path(hub_root) if hub_root is not None else find_hub_root(
        cwd, require_model=False
    )
    if resolved_hub_root is None:
        raise click.ClickException(
            "Cannot locate an ontology hub. Run from a dataplatform repo whose hub is "
            "discoverable, or pass --hub-root explicitly."
        )

    resolver = None
    if not dry_run:
        catalog_path = _resolve_catalog(
            None,
            resolved_hub_root,
            cwd,
            resolve_refmodels_dir(cwd, resolved_hub_root),
        )
        resolver = _hub_class_resolver(
            resolved_hub_root,
            catalog_path,
            on_warning=lambda message: click.echo(f"⚠ {message}", err=True),
        )

    try:
        result = run_promote_transform(
            resolved_hub_root,
            sql_path,
            domain=domain,
            properties_path=properties_path,
            force=force,
            dry_run=dry_run,
            resolve_target_class=resolver,
        )
    except PromoteTransformValidationError as exc:
        click.echo(
            f"❌ '{exc.model_name}' failed contract validation after promotion; rolled "
            "back -- nothing was left in the hub tree.",
            err=True,
        )
        for finding in exc.report.errors:
            model = f" [{finding.model}]" if finding.model else ""
            click.echo(f"❌ {finding.path}{model}: {finding.message}", err=True)
        raise click.exceptions.Exit(1)
    except PromoteTransformError as exc:
        raise click.ClickException(str(exc)) from exc

    if dry_run:
        click.echo(
            f"🔍 Dry-run: would promote '{result.model_name}' into domain {domain!r}:"
        )
        click.echo(f"   - SQL:        {result.sql_dest_path}")
        click.echo(f"   - Properties: {result.properties_dest_path}")
        click.echo(
            "   ⚠ No files were written. Contract validation (validate-dbt-contracts) "
            "would run against the hub after copying."
        )
        return

    click.echo(
        f"✅ Promoted '{result.model_name}' into {resolved_hub_root} (domain {domain!r}):"
    )
    click.echo(f"   - SQL:        {result.sql_dest_path}")
    click.echo(f"   - Properties: {result.properties_dest_path}")
    report = result.validation_report
    click.echo(
        f"✅ Contract validated ({len(report.contracted_models)} model(s), "
        f"{len(report.warnings)} warning(s))."
    )
    click.echo(
        "\nNext steps (this command does NOT do either of these):\n"
        "   1. Wire source.dbtModel.{name, sqlPath, contractPath} in an EntityBinding via "
        "the kairos-design-mapping skill.\n"
    )
    if result.model_name.startswith("int_merged__"):
        click.echo(
            "   2. Persist a Decision Log entry with `kairos-ontology decision new`, not ad "
            "hoc markdown, capturing the grain, the natural key, which reconciliation "
            "strategy was chosen and why, and any sample-evidence/row-count reconciliation "
            "performed (kairos-develop-dbt-transformation step 7)."
        )
    click.echo(
        f"\n⚠ {result.sql_source_path} is still your dataplatform repo's own copy. Once "
        f"the hub compiles and emits with this model wired in and this dataplatform repo "
        f"reinstalls the package (`dbt deps`), that installed copy and this local file "
        f"resolve to the same database object -- `dbt parse` will fail with 'two resources "
        f"with identical database representations'. Remove or exclude "
        f"{result.sql_source_path.name} from this project once the promotion has reached a "
        "hub release and been reinstalled."
    )
