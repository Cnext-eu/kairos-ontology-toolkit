# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused setup CLI commands."""

import click
import re
import shutil
import subprocess
from pathlib import Path


from .. import __version__ as _toolkit_version
from ..core._provenance import provenance_comment
from ..core.catalog_utils import sync_domain_catalog_entry
from ..core.decision_records import build_index_markdown
from ..core.hub_utils import publish_root

# Importing the design-time MDM package registers the additive ``mdm-profile``
# projection target with the core projector (registry pattern, MDM-DD-002).
# The CLI is the layer that legitimately depends on both core and mdm.
from .. import mdm as _mdm  # noqa: F401  (import for side-effect: target registration)

from .shared import (
    _DATAPLATFORM_SCAFFOLD,
    _DATAPLATFORM_SKILLS,
    _MIGRATE_DIR_MAP,
    _MIGRATE_OUTPUT_MAP,
    _SCAFFOLD_DIR,
    _V5_HUB_DIRECTORIES,
    _V5_OUTPUT_DIRECTORIES,
    _check_not_inside_git_repo,
    _configure_branch_protection,
    _copy_managed,
    _create_github_repo,
    _detect_hub_context,
    _is_old_layout,
    _resolve_channel,
    _run_reference_models_update,
    _slugify,
    _tag_to_version,
)


@click.command()
@click.option(
    "--domain",
    type=str,
    default=None,
    help='Name of the first domain (e.g., "customer"). Creates a starter .ttl file.',
)
@click.option(
    "--company-domain",
    "company_domain",
    type=str,
    required=True,
    help='Company internet domain (e.g., "contoso.com"). '
    "Used as the namespace base: https://<domain>/ont/",
)
@click.option("--force", is_flag=True, help="Overwrite existing files")
def init(domain, company_domain, force):
    """Initialize a Kairos ontology hub in the current directory.

    Creates the standard folder structure, installs Copilot skills, and
    optionally scaffolds a starter ontology domain.
    """
    cwd = Path.cwd()

    # --- Refuse to scaffold a nested hub (DD-062) ----------------------------
    # `init` writes the repo-root scaffold (pyproject.toml pin, managed .github/,
    # .gitignore, setup-env.*) plus ontology-hub/.  Run from a *content*
    # subdirectory of an existing hub it would fabricate an entire second,
    # nested hub with a divergent toolkit pin.  Unlike `update` — which only
    # touches the pin and managed files and can safely re-root — `init` creates
    # ~15 paths and honours --force, so silently re-rooting could overwrite the
    # real hub.  Refuse instead and point at the right command.
    from ..core.hub_utils import find_managed_root

    managed_root = find_managed_root(cwd)
    if managed_root is not None and managed_root != cwd.resolve():
        raise click.ClickException(
            f"An existing Kairos hub was detected at {managed_root}\n"
            f"   (you ran `init` from {cwd}, a subdirectory of it).\n\n"
            "   `init` scaffolds a NEW hub root and would create a nested second hub\n"
            "   here with its own divergent toolkit pin. Refusing.\n\n"
            "   Did you mean, from the hub root:\n"
            f"     cd {managed_root}\n"
            "     kairos-ontology update                 # refresh managed files / toolkit pin\n"
            "     kairos-ontology init --domain <name> --company-domain <domain>\n"
            "                                            # backfill scaffold / add a domain"
        )

    company_name = company_domain.split(".")[0].replace("-", " ").title()
    print("🚀 Initializing Kairos ontology hub")
    print(f"   Directory: {cwd}")
    print(f"   Company:   {company_name} ({company_domain})\n")

    hub = cwd / "ontology-hub"

    # 1. Create directory structure
    for relative in _V5_HUB_DIRECTORIES:
        (hub / relative).mkdir(parents=True, exist_ok=True)

    # Business-discovery imports live at the REPO ROOT (like ontology-reference-models),
    # not under ontology-hub/. Created on init so it's ready to receive artifacts.
    imports_bd = cwd / ".import" / "businessdiscovery"
    imports_bd.mkdir(parents=True, exist_ok=True)
    imports_readme_src = _SCAFFOLD_DIR / "import" / "businessdiscovery" / "README.md"
    if imports_readme_src.is_file() and (not (imports_bd / "README.md").exists() or force):
        shutil.copy2(imports_readme_src, imports_bd / "README.md")

    # Place .gitkeep in empty publish subdirs (sibling <repo>/ontology-hub-publish/)
    # so git tracks the derived-output slots.
    for target in _V5_OUTPUT_DIRECTORIES:
        gitkeep = publish_root(hub) / target / ".gitkeep"
        gitkeep.parent.mkdir(parents=True, exist_ok=True)
        if not gitkeep.exists():
            gitkeep.touch()

    # 2. Copy README files for each directory
    readme_map = {
        "model/ontologies": "model/ontologies",
        "model/shapes": "model/shapes",
        "businessdiscovery": "businessdiscovery",
        "businessdiscovery/_extractions": "businessdiscovery/_extractions",
        "integration/bindings": "integration/bindings",
        "integration/discovery/bi": "integration/discovery/bi",
        "integration/sources": "integration/sources",
        "integration/transforms/dbt": "integration/transforms/dbt",
    }
    for scaffold_subdir, hub_subdir in readme_map.items():
        readme_src = _SCAFFOLD_DIR / "ontology-hub" / scaffold_subdir / "README.md"
        readme_dst = hub / hub_subdir / "README.md"
        if readme_src.is_file() and (not readme_dst.exists() or force):
            shutil.copy2(readme_src, readme_dst)

    # 2a. Install the OKF decision-log bundle.
    decisions_src = _SCAFFOLD_DIR / "ontology-hub" / "decisions"
    decisions_dst = hub / "decisions"
    decisions_dst.mkdir(parents=True, exist_ok=True)
    for filename in ("README.md", "HUB-DD-template.md.template"):
        src = decisions_src / filename
        dst = decisions_dst / filename
        if src.is_file() and (not dst.exists() or force):
            _copy_managed(src, dst)
    index_dst = decisions_dst / "index.md"
    if not index_dst.exists() or force:
        index_dst.write_text(build_index_markdown([]), encoding="utf-8")
        print("  ✓ Created ontology-hub/decisions/index.md")

    # 2b. Copy the business glossary template into businessdiscovery/
    glossary_tpl_src = (
        _SCAFFOLD_DIR / "ontology-hub" / "businessdiscovery" / "glossary-template.ttl"
    )
    glossary_tpl_dst = hub / "businessdiscovery" / "glossary-template.ttl"
    if glossary_tpl_src.is_file() and (not glossary_tpl_dst.exists() or force):
        shutil.copy2(glossary_tpl_src, glossary_tpl_dst)

    # 2c. Copy source-system-template into integration/sources/
    src_template_src = (
        _SCAFFOLD_DIR / "ontology-hub" / "integration" / "sources" / "source-system-template"
    )
    src_template_dst = hub / "integration" / "sources" / "source-system-template"
    if src_template_src.is_dir() and (not src_template_dst.exists() or force):
        if src_template_dst.exists():
            shutil.rmtree(src_template_dst)
        shutil.copytree(src_template_src, src_template_dst)
        print("  ✓ Installed integration/sources/source-system-template/")

    # 3. Copy Copilot skills into .github/skills/
    skills_src = _SCAFFOLD_DIR / "skills"
    skills_dst = cwd / ".github" / "skills"
    if skills_src.is_dir():
        for skill_dir in skills_src.iterdir():
            if skill_dir.is_dir():
                dst = skills_dst / skill_dir.name
                if dst.exists() and not force:
                    print(f"  ⏭  Skill {skill_dir.name}/ already exists (use --force to overwrite)")
                else:
                    if dst.exists():
                        shutil.rmtree(dst)
                    dst.mkdir(parents=True, exist_ok=True)
                    for src_file in skill_dir.iterdir():
                        if src_file.is_file() and src_file.suffix == ".md":
                            _copy_managed(src_file, dst / src_file.name)
                        elif src_file.is_file():
                            shutil.copy2(src_file, dst / src_file.name)
                    print(f"  ✓ Installed skill: {skill_dir.name}/")

    # 4. Copy copilot-instructions.md
    instructions_src = _SCAFFOLD_DIR / "copilot-instructions.md"
    instructions_dst = cwd / ".github" / "copilot-instructions.md"
    if instructions_src.is_file():
        if instructions_dst.exists() and not force:
            print("  ⏭  copilot-instructions.md already exists (use --force to overwrite)")
        else:
            _copy_managed(instructions_src, instructions_dst)
            print("  ✓ Installed copilot-instructions.md")

    # 4b. Copy CI workflow for managed-file checks
    workflow_src = _SCAFFOLD_DIR / "github-workflows" / "managed-check.yml"
    workflow_dst = cwd / ".github" / "workflows" / "managed-check.yml"
    if workflow_src.is_file():
        if workflow_dst.exists() and not force:
            print("  ⏭  .github/workflows/managed-check.yml already exists (use --force)")
        else:
            workflow_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(workflow_src, workflow_dst)
            print("  ✓ Installed .github/workflows/managed-check.yml")

    # 4b-ii. Copy release-projections workflow
    release_wf_src = _SCAFFOLD_DIR / "github-workflows" / "release-projections.yml"
    release_wf_dst = cwd / ".github" / "workflows" / "release-projections.yml"
    if release_wf_src.is_file():
        if release_wf_dst.exists() and not force:
            print("  ⏭  .github/workflows/release-projections.yml already exists (use --force)")
        else:
            release_wf_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(release_wf_src, release_wf_dst)
            print("  ✓ Installed .github/workflows/release-projections.yml")

    # 4b-iii. Copy assign-copilot workflow
    copilot_wf_src = _SCAFFOLD_DIR / "github-workflows" / "assign-copilot.yml"
    copilot_wf_dst = cwd / ".github" / "workflows" / "assign-copilot.yml"
    if copilot_wf_src.is_file():
        if copilot_wf_dst.exists() and not force:
            print("  ⏭  .github/workflows/assign-copilot.yml already exists (use --force)")
        else:
            copilot_wf_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(copilot_wf_src, copilot_wf_dst)
            print("  ✓ Installed .github/workflows/assign-copilot.yml")

    # 4b-v. Copy copilot-setup-steps workflow
    setup_wf_src = _SCAFFOLD_DIR / "github-workflows" / "copilot-setup-steps.yml"
    setup_wf_dst = cwd / ".github" / "workflows" / "copilot-setup-steps.yml"
    if setup_wf_src.is_file():
        if setup_wf_dst.exists() and not force:
            print("  ⏭  .github/workflows/copilot-setup-steps.yml already exists (use --force)")
        else:
            setup_wf_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(setup_wf_src, setup_wf_dst)
            print("  ✓ Installed .github/workflows/copilot-setup-steps.yml")

    # 4b-vi. Copy issue templates
    issue_tpl_src = _SCAFFOLD_DIR / "github-issue-templates"
    issue_tpl_dst = cwd / ".github" / "ISSUE_TEMPLATE"
    if issue_tpl_src.is_dir():
        issue_tpl_dst.mkdir(parents=True, exist_ok=True)
        for tpl_file in issue_tpl_src.iterdir():
            if tpl_file.is_file():
                dst_file = issue_tpl_dst / tpl_file.name
                if dst_file.exists() and not force:
                    print(
                        f"  ⏭  .github/ISSUE_TEMPLATE/{tpl_file.name} already exists (use --force)"
                    )
                else:
                    shutil.copy2(tpl_file, dst_file)
                    print(f"  ✓ Installed .github/ISSUE_TEMPLATE/{tpl_file.name}")

    # update-referencemodels.ps1 is no longer installed; reference models are
    # populated by the `kairos-ontology update-refmodels` command instead.

    # 4c-ii. Copy setup-env scripts (uv-based environment bootstrap)
    for script_name in ("setup-env.ps1", "setup-env.sh"):
        script_src = _SCAFFOLD_DIR / script_name
        script_dst = cwd / script_name
        if script_src.is_file():
            if script_dst.exists() and not force:
                print(f"  ⏭  {script_name} already exists (use --force to overwrite)")
            else:
                shutil.copy2(script_src, script_dst)
                print(f"  ✓ Installed {script_name}")

    # 4d. Copy .gitignore
    gitignore_src = _SCAFFOLD_DIR / "gitignore.template"
    gitignore_dst = cwd / ".gitignore"
    if gitignore_src.is_file():
        if gitignore_dst.exists() and not force:
            print("  ⏭  .gitignore already exists (use --force to overwrite)")
        else:
            shutil.copy2(gitignore_src, gitignore_dst)
            print("  ✓ Installed .gitignore")

    # 4d-ii. Copy .claude/settings.json (denies raw TTL Read/Grep — DD-103)
    claude_settings_src = _SCAFFOLD_DIR / "claude-settings.json"
    claude_settings_dst = cwd / ".claude" / "settings.json"
    if claude_settings_src.is_file():
        if claude_settings_dst.exists() and not force:
            print("  ⏭  .claude/settings.json already exists (use --force to overwrite)")
        else:
            claude_settings_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(claude_settings_src, claude_settings_dst)
            print("  ✓ Installed .claude/settings.json (TTL access boundary)")

    # 4e-bis. Copy .env.example into repo root
    env_example_src = _SCAFFOLD_DIR / ".env.example"
    env_example_dst = cwd / ".env.example"
    if env_example_src.is_file():
        if env_example_dst.exists() and not force:
            print("  ⏭  .env.example already exists (use --force to overwrite)")
        else:
            shutil.copy2(env_example_src, env_example_dst)
            print("  ✓ Installed .env.example")

    # 4e. Generate pyproject.toml (needed for uv sync)
    pyproject_src = _SCAFFOLD_DIR / "pyproject.toml.template"
    pyproject_dst = cwd / "pyproject.toml"
    if pyproject_src.is_file():
        if pyproject_dst.exists() and not force:
            print("  ⏭  pyproject.toml already exists (use --force to overwrite)")
        else:
            ref = _resolve_channel("stable") or f"v{_toolkit_version}"
            version = _tag_to_version(ref)
            repo_name = cwd.name
            content = pyproject_src.read_text(encoding="utf-8")
            content = (
                content.replace("{repo_name}", repo_name)
                .replace("{description}", repo_name)
                .replace("{toolkit_ref}", ref)
                .replace("{toolkit_version}", version)
            )
            pyproject_dst.write_text(content, encoding="utf-8")
            print("  ✓ Created pyproject.toml")

    # 5. Reference models are populated later by _run_reference_models_update()
    # (no submodule — files committed directly)

    # 6. Generate hub README with company context
    hub_readme_src = _SCAFFOLD_DIR / "ontology-hub" / "README.md.template"
    hub_readme_dst = hub / "README.md"
    if hub_readme_src.is_file():
        if hub_readme_dst.exists() and not force:
            print("  ⏭  ontology-hub/README.md already exists (use --force to overwrite)")
        else:
            content = hub_readme_src.read_text(encoding="utf-8")
            content = content.replace("{company_name}", company_name).replace(
                "{company_domain}", company_domain
            )
            hub_readme_dst.write_text(content, encoding="utf-8")
            print("  ✓ Created ontology-hub/README.md (company context)")

    # 7. Generate master ontology (imports all domains)
    master_src = _SCAFFOLD_DIR / "ontology-hub" / "model" / "ontologies" / "master.ttl.template"
    master_dst = hub / "model" / "ontologies" / "_master.ttl"
    if master_src.is_file():
        if master_dst.exists() and not force:
            print("  ⏭  ontology-hub/model/ontologies/_master.ttl already exists (use --force)")
        else:
            content = master_src.read_text(encoding="utf-8")
            content = content.replace("{company_name}", company_name).replace(
                "{company_domain}", company_domain
            )
            content = provenance_comment("init", editable=True) + "\n" + content
            master_dst.write_text(content, encoding="utf-8")
            print("  ✓ Created ontology-hub/model/ontologies/_master.ttl")

    # 7a-ii. Generate foundation ontology (shared base for thin domain ontologies)
    foundation_src = (
        _SCAFFOLD_DIR / "ontology-hub" / "model" / "ontologies" / "foundation.ttl.template"
    )
    foundation_dst = hub / "model" / "ontologies" / "_foundation.ttl"
    if foundation_src.is_file():
        if foundation_dst.exists() and not force:
            print("  ⏭  ontology-hub/model/ontologies/_foundation.ttl already exists (use --force)")
        else:
            content = foundation_src.read_text(encoding="utf-8")
            content = content.replace("{company_name}", company_name).replace(
                "{company_domain}", company_domain
            )
            content = provenance_comment("init", editable=True) + "\n" + content
            foundation_dst.write_text(content, encoding="utf-8")
            print("  ✓ Created ontology-hub/model/ontologies/_foundation.ttl")

    # 7b. Generate local catalog (URI → local file mapping)
    catalog_src = _SCAFFOLD_DIR / "ontology-hub" / "catalog-v001.xml.template"
    catalog_dst = hub / "catalog-v001.xml"
    if catalog_src.is_file():
        if catalog_dst.exists() and not force:
            print("  ⏭  ontology-hub/catalog-v001.xml already exists (use --force)")
        else:
            content = catalog_src.read_text(encoding="utf-8")
            content = content.replace("{company_name}", company_name).replace(
                "{company_domain}", company_domain
            )
            catalog_dst.write_text(content, encoding="utf-8")
            print("  ✓ Created ontology-hub/catalog-v001.xml")

    config_src = _SCAFFOLD_DIR / "ontology-hub" / "kairos.yaml.template"
    config_dst = hub / "kairos.yaml"
    if config_src.is_file() and (not config_dst.exists() or force):
        content = config_src.read_text(encoding="utf-8").replace("{repo_name}", cwd.name)
        if domain:
            content += f"default_domain: {domain}\n"
        config_dst.write_text(content, encoding="utf-8")
        print("  ✓ Created ontology-hub/kairos.yaml")

    # 8. Scaffold a starter domain ontology
    if domain:
        template_src = (
            _SCAFFOLD_DIR / "ontology-hub" / "model" / "ontologies" / "starter.ttl.template"
        )
        ontology_dst = hub / "model" / "ontologies" / f"{domain}.ttl"
        if ontology_dst.exists() and not force:
            print(
                f"  ⏭  ontology-hub/model/ontologies/{domain}.ttl already exists "
                "(use --force to overwrite)"
            )
        elif template_src.is_file():
            label = domain.replace("-", " ").replace("_", " ").title()
            content = template_src.read_text(encoding="utf-8")
            content = (
                content.replace("{domain}", domain)
                .replace("{label}", label)
                .replace("{company_domain}", company_domain)
            )
            content = provenance_comment("init", editable=True) + "\n" + content
            ontology_dst.write_text(content, encoding="utf-8")
            print(f"  ✓ Created ontology-hub/model/ontologies/{domain}.ttl")
        if ontology_dst.exists() and catalog_dst.exists():
            ontology_iri = sync_domain_catalog_entry(
                catalog_dst,
                ontology_dst,
                company_domain=company_domain,
            )
            print(f"  ✓ Registered {ontology_iri} in ontology-hub/catalog-v001.xml")

    print("\n✅ Ontology hub initialized!")
    print("\nNext steps:")
    print(
        "  1. Edit ontology-hub/model/ontologies/*.ttl to define your domain classes and properties"
    )
    print("  2. Run: kairos-ontology validate")
    print("  3. Run: kairos-ontology project --target prompt")


@click.command()
@click.option("--check", is_flag=True, help="Preview what would change without modifying anything.")
@click.option("--dry-run", "dry_run", is_flag=True, help="Alias for --check.")
@click.option(
    "--hub",
    "hub_path",
    type=click.Path(exists=True),
    default="ontology-hub",
    help="Path to the ontology-hub directory (default: ontology-hub).",
)
def migrate(check, dry_run, hub_path):
    """Move an existing ontology hub from the flat layout to the grouped layout.

    Moves files into the new model/ + integration/ structure (derived output is
    emitted to the sibling ontology-hub-publish/ publish root) and cleans up empty
    old directories. This layout utility does not convert legacy authoring
    contracts to v5; rebuild those hubs in a fresh repository.

    \b
    After migrating, run:
      kairos-ontology update      # refresh managed files (skills, instructions)
      kairos-ontology validate    # verify ontologies still parse correctly
    """
    check = check or dry_run
    hub = Path(hub_path)

    if not hub.is_dir():
        raise click.ClickException(f"Hub directory not found: {hub}")

    if (hub / "model").is_dir() and not (hub / "ontologies").is_dir():
        print("✅ Hub is already using the new layout — nothing to migrate.")
        return

    if not _is_old_layout(hub):
        raise click.ClickException(
            f"Cannot detect old flat layout in {hub}. Expected ontology-hub/ontologies/ to exist."
        )

    if check:
        print("🔍 Migration preview (no files will be moved):\n")
    else:
        print("🚀 Migrating ontology hub to new layout\n")

    moved_count = 0

    # --- 1. Create new directory structure -----------------------------------
    new_dirs = [
        hub / "model" / "ontologies",
        hub / "model" / "shapes",
        hub / "model" / "extensions",
        hub / "model" / "mappings",
        hub / "model" / "planning",
        hub / "integration" / "sources",
        hub / "integration" / "discovery",
        publish_root(hub) / "medallion" / "powerbi",
        publish_root(hub) / "medallion" / "dbt",
    ]
    if not check:
        for d in new_dirs:
            d.mkdir(parents=True, exist_ok=True)

    # --- 2. Move top-level hub dirs ------------------------------------------
    for old_name, new_rel in _MIGRATE_DIR_MAP.items():
        old_dir = hub / old_name
        new_dir = hub / new_rel
        if old_dir.is_dir():
            items = list(old_dir.iterdir())
            if items:
                for item in items:
                    # In check mode, skip silver-ext files from ontologies/
                    # — they'll be shown in step 3 with correct final destination.
                    if check and old_name == "ontologies" and item.name.endswith("-silver-ext.ttl"):
                        continue
                    dst = new_dir / item.name
                    if check:
                        print(f"  MOVE  {old_name}/{item.name}  →  {new_rel}/{item.name}")
                    else:
                        if dst.exists():
                            if dst.is_dir():
                                shutil.rmtree(dst)
                            else:
                                dst.unlink()
                        shutil.move(str(item), str(dst))
                    moved_count += 1

    # --- 3. Move *-silver-ext.ttl from model/ontologies/ to model/extensions/ -
    # In --check mode files haven't moved yet, so scan the original location.
    onto_dir = hub / "model" / "ontologies"
    ext_scan_dir = (hub / "ontologies") if check and not onto_dir.is_dir() else onto_dir
    ext_dir = hub / "model" / "extensions"
    if ext_scan_dir.is_dir():
        for ext_file in list(ext_scan_dir.glob("*-silver-ext.ttl")):
            dst = ext_dir / ext_file.name
            if check:
                print(f"  MOVE  {ext_file.name}  →  model/extensions/{ext_file.name}")
            else:
                if dst.exists():
                    dst.unlink()
                shutil.move(str(ext_file), str(dst))
            moved_count += 1

    # --- 4. Move old output/silver/ and output/dbt/ to the publish root ------
    output_dir = hub / "output"
    publish_dir = publish_root(hub)
    if output_dir.is_dir():
        for old_target, new_rel in _MIGRATE_OUTPUT_MAP.items():
            old_target_dir = output_dir / old_target
            new_target_dir = publish_dir / new_rel
            if old_target_dir.is_dir():
                items = list(old_target_dir.iterdir())
                if items:
                    new_target_dir.mkdir(parents=True, exist_ok=True)
                    for item in items:
                        dst = new_target_dir / item.name
                        if check:
                            print(
                                f"  MOVE  output/{old_target}/{item.name}  →  "
                                f"ontology-hub-publish/{new_rel}/{item.name}"
                            )
                        else:
                            if dst.exists():
                                if dst.is_dir():
                                    shutil.rmtree(dst)
                                else:
                                    dst.unlink()
                            shutil.move(str(item), str(dst))
                        moved_count += 1

    # --- 5. Remove application-models/ ---------------------------------------
    app_models = hub.parent / "application-models"
    if app_models.is_dir():
        if check:
            print(
                "  DELETE  application-models/  "
                "(ERDs now in ontology-hub-publish/medallion/dbt/docs/diagrams/)"
            )
        else:
            shutil.rmtree(app_models)
            print("  ✓ Removed application-models/")

    # --- 6. Clean up old empty directories -----------------------------------
    old_dirs = ["ontologies", "shapes", "mappings", "sources", "bronze"]
    for old_name in old_dirs:
        old_dir = hub / old_name
        if old_dir.is_dir():
            remaining = list(old_dir.iterdir())
            if not remaining:
                if check:
                    print(f"  RMDIR  {old_name}/")
                else:
                    old_dir.rmdir()
            else:
                print(
                    f"  ⚠  {old_name}/ still has files — not removed: {[f.name for f in remaining]}"
                )

    # Clean up old output subdirs
    for old_target in _MIGRATE_OUTPUT_MAP:
        old_target_dir = output_dir / old_target
        if old_target_dir.is_dir():
            remaining = list(old_target_dir.iterdir())
            if not remaining:
                if check:
                    print(f"  RMDIR  output/{old_target}/")
                else:
                    old_target_dir.rmdir()

    # --- Summary -------------------------------------------------------------
    if check:
        print(f"\n📋 {moved_count} item(s) would be moved.")
        print("   Run without --check to apply.")
    else:
        print(f"\n✅ Migration complete — {moved_count} item(s) moved.")
        print("\nNext steps:")
        print("  1. kairos-ontology update     # refresh managed files")
        print("  2. kairos-ontology validate   # verify ontologies parse")
        print("  3. git add -A && git commit -m 'refactor: migrate hub to new layout'")


@click.command(name="new-repo")
@click.argument("name")
@click.option(
    "--description",
    "desc",
    type=str,
    default=None,
    help="Short repo description for README / pyproject.",
)
@click.option(
    "--path",
    "dest",
    type=click.Path(),
    default=None,
    help="Parent directory to create the repo in (default: current dir).",
)
@click.option(
    "--org",
    type=str,
    default="Cnext-eu",
    help="GitHub organisation for the remote repo (default: Cnext-eu).",
)
@click.option(
    "--private/--public",
    "is_private",
    default=True,
    help="Create a private (default) or public GitHub repo.",
)
@click.option(
    "--ref-models-version",
    "ref_models_version",
    type=str,
    default=None,
    help="Git ref (tag/branch) for reference models (default: latest).",
)
@click.option(
    "--company-domain",
    "company_domain",
    type=str,
    default=None,
    help='Company internet domain (e.g., "contoso.com"). Defaults to <name>.com if not provided.',
)
@click.option(
    "--skip-protection",
    "skip_protection",
    is_flag=True,
    default=False,
    help="Skip configuring branch protection on main (useful if no admin rights).",
)
def new_repo(
    name, desc, dest, org, is_private, ref_models_version, company_domain, skip_protection
):
    """Create a new ontology hub GitHub repository.

    NAME is the client or project identifier (e.g., "contoso" or
    "acme-logistics").  The repo will be named <NAME>-ontology-hub
    following the Kairos naming convention.

    \b
    Naming convention
    ─────────────────
      contoso           → contoso-ontology-hub
      acme-logistics    → acme-logistics-ontology-hub

    This command:
      1. Creates the repo directory with the standard hub structure.
      2. Generates pyproject.toml with kairos-ontology-toolkit as a dependency.
      3. Adds .gitignore, README.md, Copilot skills & instructions.
      4. Initialises a git repo with an initial commit.
      5. Creates the GitHub repo under --org and pushes (requires gh CLI).

    \b
    Examples:
      kairos-ontology new-repo contoso
      kairos-ontology new-repo contoso --org Acme-Corp
      kairos-ontology new-repo contoso --public

    After running this, `cd` into the new repo and add domains with:

    \b
      uv sync
      kairos-ontology init --company-domain <domain>
    """
    repo_slug = _slugify(name)
    description = desc or f"{name.replace('-', ' ').title()} domain ontologies"
    parent = Path(dest) if dest else Path.cwd()
    repo_dir = parent / repo_slug

    # Derive company domain from name if not provided
    if not company_domain:
        # "contoso-ontology-hub" -> "contoso", "acme-logistics" -> "acme-logistics"
        base = name.lower().strip()
        for suffix in ["-ontology-hub", "-ontology"]:
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        company_domain_val = f"{base}.com"
    else:
        company_domain_val = company_domain
    company_name = company_domain_val.split(".")[0].replace("-", " ").title()

    if repo_dir.exists():
        raise click.ClickException(f"Directory already exists: {repo_dir}")

    # Guard: don't create a new repo inside an existing git repository
    _check_not_inside_git_repo(parent, name)

    print(f"🚀 Creating ontology hub repository: {repo_slug}")
    print(f"   Location: {repo_dir}\n")

    # Create the local directory from scratch (no GitHub template).
    repo_dir.mkdir(parents=True)

    # --- Scaffold the hub structure (reuse init logic) -----------------------
    hub = repo_dir / "ontology-hub"

    for relative in _V5_HUB_DIRECTORIES:
        (hub / relative).mkdir(parents=True, exist_ok=True)

    # Business-discovery imports live at the REPO ROOT (like ontology-reference-models),
    # not under ontology-hub/. Created on new-repo so it's ready to receive artifacts.
    imports_bd = repo_dir / ".import" / "businessdiscovery"
    imports_bd.mkdir(parents=True, exist_ok=True)
    imports_readme_src = _SCAFFOLD_DIR / "import" / "businessdiscovery" / "README.md"
    if imports_readme_src.is_file():
        shutil.copy2(imports_readme_src, imports_bd / "README.md")

    # Place .gitkeep in publish subdirs (sibling <repo>/ontology-hub-publish/)
    # so git tracks the derived-output slots.
    for target in _V5_OUTPUT_DIRECTORIES:
        gitkeep = publish_root(hub) / target / ".gitkeep"
        gitkeep.parent.mkdir(parents=True, exist_ok=True)
        if not gitkeep.exists():
            gitkeep.touch()

    # README files
    readme_map = {
        "model/ontologies": "model/ontologies",
        "model/shapes": "model/shapes",
        "businessdiscovery": "businessdiscovery",
        "businessdiscovery/_extractions": "businessdiscovery/_extractions",
        "integration/bindings": "integration/bindings",
        "integration/discovery/bi": "integration/discovery/bi",
        "integration/sources": "integration/sources",
        "integration/transforms/dbt": "integration/transforms/dbt",
    }
    for scaffold_subdir, hub_subdir in readme_map.items():
        src = _SCAFFOLD_DIR / "ontology-hub" / scaffold_subdir / "README.md"
        dst = hub / hub_subdir / "README.md"
        if src.is_file():
            shutil.copy2(src, dst)

    # Decision-log bundle.
    decisions_src = _SCAFFOLD_DIR / "ontology-hub" / "decisions"
    decisions_dst = hub / "decisions"
    decisions_dst.mkdir(parents=True, exist_ok=True)
    for filename in ("README.md", "HUB-DD-template.md.template"):
        src = decisions_src / filename
        dst = decisions_dst / filename
        if src.is_file():
            _copy_managed(src, dst)
    (decisions_dst / "index.md").write_text(build_index_markdown([]), encoding="utf-8")
    print("  ✓ ontology-hub/decisions/ (decision log)")

    # Business glossary template into businessdiscovery/
    glossary_tpl_src = (
        _SCAFFOLD_DIR / "ontology-hub" / "businessdiscovery" / "glossary-template.ttl"
    )
    if glossary_tpl_src.is_file():
        shutil.copy2(glossary_tpl_src, hub / "businessdiscovery" / "glossary-template.ttl")

    # Source-system-template into integration/sources/
    src_template_src = (
        _SCAFFOLD_DIR / "ontology-hub" / "integration" / "sources" / "source-system-template"
    )
    src_template_dst = hub / "integration" / "sources" / "source-system-template"
    if src_template_src.is_dir() and not src_template_dst.exists():
        shutil.copytree(src_template_src, src_template_dst)

    # Hub-level README with company context
    hub_readme_src = _SCAFFOLD_DIR / "ontology-hub" / "README.md.template"
    if hub_readme_src.is_file():
        content = hub_readme_src.read_text(encoding="utf-8")
        content = content.replace("{company_name}", company_name).replace(
            "{company_domain}", company_domain_val
        )
        (hub / "README.md").write_text(content, encoding="utf-8")
        print("  ✓ ontology-hub/README.md (company context)")

    # Master ontology (imports all domains)
    master_src = _SCAFFOLD_DIR / "ontology-hub" / "model" / "ontologies" / "master.ttl.template"
    if master_src.is_file():
        content = master_src.read_text(encoding="utf-8")
        content = content.replace("{company_name}", company_name).replace(
            "{company_domain}", company_domain_val
        )
        content = provenance_comment("new-repo", editable=True) + "\n" + content
        (hub / "model" / "ontologies" / "_master.ttl").write_text(content, encoding="utf-8")
        print("  ✓ ontology-hub/model/ontologies/_master.ttl")

    # Foundation ontology (shared base for thin domain ontologies)
    foundation_src = (
        _SCAFFOLD_DIR / "ontology-hub" / "model" / "ontologies" / "foundation.ttl.template"
    )
    if foundation_src.is_file():
        content = foundation_src.read_text(encoding="utf-8")
        content = content.replace("{company_name}", company_name).replace(
            "{company_domain}", company_domain_val
        )
        content = provenance_comment("new-repo", editable=True) + "\n" + content
        (hub / "model" / "ontologies" / "_foundation.ttl").write_text(content, encoding="utf-8")
        print("  ✓ ontology-hub/model/ontologies/_foundation.ttl")

    # Local catalog (URI → local file mapping)
    catalog_src = _SCAFFOLD_DIR / "ontology-hub" / "catalog-v001.xml.template"
    if catalog_src.is_file():
        content = catalog_src.read_text(encoding="utf-8")
        content = content.replace("{company_name}", company_name).replace(
            "{company_domain}", company_domain_val
        )
        (hub / "catalog-v001.xml").write_text(content, encoding="utf-8")
        print("  ✓ ontology-hub/catalog-v001.xml")

    config_src = _SCAFFOLD_DIR / "ontology-hub" / "kairos.yaml.template"
    if config_src.is_file():
        content = config_src.read_text(encoding="utf-8").replace("{repo_name}", repo_slug)
        (hub / "kairos.yaml").write_text(content, encoding="utf-8")
        print("  ✓ ontology-hub/kairos.yaml")

    # Copilot skills
    skills_src = _SCAFFOLD_DIR / "skills"
    skills_dst = repo_dir / ".github" / "skills"
    if skills_src.is_dir():
        for skill_dir in skills_src.iterdir():
            if skill_dir.is_dir():
                dst = skills_dst / skill_dir.name
                dst.mkdir(parents=True, exist_ok=True)
                for src_file in skill_dir.iterdir():
                    if src_file.is_file() and src_file.suffix == ".md":
                        _copy_managed(src_file, dst / src_file.name)
                    elif src_file.is_file():
                        shutil.copy2(src_file, dst / src_file.name)
                print(f"  ✓ Skill: {skill_dir.name}/")

    # Copilot instructions
    instructions_src = _SCAFFOLD_DIR / "copilot-instructions.md"
    instructions_dst = repo_dir / ".github" / "copilot-instructions.md"
    if instructions_src.is_file():
        _copy_managed(instructions_src, instructions_dst)
        print("  ✓ copilot-instructions.md")

    # CI workflow for managed-file checks
    workflow_src = _SCAFFOLD_DIR / "github-workflows" / "managed-check.yml"
    workflow_dst = repo_dir / ".github" / "workflows" / "managed-check.yml"
    if workflow_src.is_file():
        workflow_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(workflow_src, workflow_dst)
        print("  ✓ .github/workflows/managed-check.yml")

    # Release-projections workflow
    release_wf_src = _SCAFFOLD_DIR / "github-workflows" / "release-projections.yml"
    release_wf_dst = repo_dir / ".github" / "workflows" / "release-projections.yml"
    if release_wf_src.is_file():
        shutil.copy2(release_wf_src, release_wf_dst)
        print("  ✓ .github/workflows/release-projections.yml")

    # Assign-copilot workflow
    copilot_wf_src = _SCAFFOLD_DIR / "github-workflows" / "assign-copilot.yml"
    copilot_wf_dst = repo_dir / ".github" / "workflows" / "assign-copilot.yml"
    if copilot_wf_src.is_file():
        shutil.copy2(copilot_wf_src, copilot_wf_dst)
        print("  ✓ .github/workflows/assign-copilot.yml")

    # Copilot setup-steps workflow (agent environment)
    setup_wf_src = _SCAFFOLD_DIR / "github-workflows" / "copilot-setup-steps.yml"
    setup_wf_dst = repo_dir / ".github" / "workflows" / "copilot-setup-steps.yml"
    if setup_wf_src.is_file():
        shutil.copy2(setup_wf_src, setup_wf_dst)
        print("  ✓ .github/workflows/copilot-setup-steps.yml")

    # Issue templates
    issue_tpl_src = _SCAFFOLD_DIR / "github-issue-templates"
    issue_tpl_dst = repo_dir / ".github" / "ISSUE_TEMPLATE"
    if issue_tpl_src.is_dir():
        issue_tpl_dst.mkdir(parents=True, exist_ok=True)
        for tpl_file in issue_tpl_src.iterdir():
            if tpl_file.is_file():
                shutil.copy2(tpl_file, issue_tpl_dst / tpl_file.name)
                print(f"  ✓ .github/ISSUE_TEMPLATE/{tpl_file.name}")

    # --- Repo-level files ---------------------------------------------------
    # pyproject.toml
    pyproject_src = _SCAFFOLD_DIR / "pyproject.toml.template"
    if pyproject_src.is_file():
        content = pyproject_src.read_text(encoding="utf-8")
        content = (
            content.replace("{repo_name}", repo_slug)
            .replace("{description}", description)
            .replace("{toolkit_version}", _toolkit_version)
            .replace("{toolkit_ref}", f"v{_toolkit_version}")
        )
        (repo_dir / "pyproject.toml").write_text(content, encoding="utf-8")
        print("  ✓ pyproject.toml")

    # .gitignore
    gitignore_src = _SCAFFOLD_DIR / "gitignore.template"
    if gitignore_src.is_file():
        shutil.copy2(gitignore_src, repo_dir / ".gitignore")
        print("  ✓ .gitignore")

    # .claude/settings.json (denies raw TTL Read/Grep — DD-103)
    claude_settings_src = _SCAFFOLD_DIR / "claude-settings.json"
    if claude_settings_src.is_file():
        claude_settings_dst = repo_dir / ".claude" / "settings.json"
        claude_settings_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(claude_settings_src, claude_settings_dst)
        print("  ✓ .claude/settings.json (TTL access boundary)")

    # README.md
    readme_src = _SCAFFOLD_DIR / "README.md.template"
    if readme_src.is_file():
        content = readme_src.read_text(encoding="utf-8")
        content = content.replace("{repo_name}", repo_slug).replace("{description}", description)
        (repo_dir / "README.md").write_text(content, encoding="utf-8")
        print("  ✓ README.md")

    # update-referencemodels.ps1 is no longer installed; reference models are
    # populated by the `kairos-ontology update-refmodels` command instead.

    # setup-env.ps1 (venv bootstrap)
    setup_env_src = _SCAFFOLD_DIR / "setup-env.ps1"
    if setup_env_src.is_file():
        shutil.copy2(setup_env_src, repo_dir / "setup-env.ps1")
        print("  ✓ setup-env.ps1 (venv bootstrap)")

    # setup-env.sh (bash equivalent for Linux/CI)
    setup_env_sh_src = _SCAFFOLD_DIR / "setup-env.sh"
    if setup_env_sh_src.is_file():
        shutil.copy2(setup_env_sh_src, repo_dir / "setup-env.sh")
        print("  ✓ setup-env.sh (venv bootstrap - bash)")

    # package.json (Mermaid CLI for SVG rendering)
    pkg_src = _SCAFFOLD_DIR / "ontology-hub" / "package.json.template"
    if pkg_src.is_file() and not (repo_dir / "package.json").exists():
        shutil.copy2(pkg_src, repo_dir / "package.json")
        print("  ✓ package.json (mermaid-cli for SVG export)")

    # .devcontainer (VS Code Dev Container with Node.js + Python)
    devcontainer_src = _SCAFFOLD_DIR / ".devcontainer"
    devcontainer_dst = repo_dir / ".devcontainer"
    if devcontainer_src.is_dir() and not devcontainer_dst.exists():
        shutil.copytree(devcontainer_src, devcontainer_dst)
        print("  ✓ .devcontainer/ (VS Code Dev Container)")

    # --- Git + commit -------------------------------------------
    try:
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=repo_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial ontology hub scaffold"],
            cwd=repo_dir,
            capture_output=True,
            check=True,
        )
        print("  ✓ git repo initialised with initial commit")
    except FileNotFoundError:
        raise click.ClickException("git not found — install git before using new-repo")
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(f"git command failed: {exc.stderr.decode().strip()}")

    # --- GitHub repo creation ------------------------------------------------
    _create_github_repo(repo_dir, repo_slug, org, description, is_private)

    # --- Populate reference models -------------------------------------------
    _run_reference_models_update(repo_dir, ref_models_version)

    # --- Configure branch protection on main ---------------------------------
    if not skip_protection:
        full_name = f"{org}/{repo_slug}"
        print("\n🔒 Configuring branch protection on main...")
        _configure_branch_protection(repo_dir, full_name)

    print(f"\n✅ Repository created: {repo_slug}")
    print(f"   GitHub: https://github.com/{org}/{repo_slug}")
    print("\nNext steps:")
    print(f"  cd {repo_dir}")
    print("  uv sync")


_PLATFORM_MARKER_RE = re.compile(r"^\s*# --- PLATFORM: (\S+) ---\s*$")
_PLATFORM_END_MARKER_RE = re.compile(r"^\s*# --- END PLATFORM ---\s*$")
_CONFIG_START_RE = re.compile(r"^(\s*)# @config\s*$")
_CONFIG_END_RE = re.compile(r"^\s*# @endconfig\s*$")
_COMMENTED_LINE_RE = re.compile(r"^(\s*)#\s?(.*)$")


def _toggle_config_line(line: str, *, active: bool, base_indent: str) -> str:
    """Uncomment (active) or comment (inactive) one profile config line.

    ``base_indent`` is the indentation of the enclosing ``# @config`` marker; it is
    the fixed comment column used for every line in that config region, so
    re-commenting an active block reproduces the template's original alignment
    (marker at the block's base column, child indentation preserved after it).
    Blank lines are returned unchanged either way; a config line is only ever
    commented or uncommented, never duplicated.
    """
    match = _COMMENTED_LINE_RE.match(line)
    if match:
        indent, rest = match.group(1), match.group(2)
        return f"{indent}{rest}" if active else line
    if active or not line.strip():
        return line
    rest = line[len(base_indent) :] if line.startswith(base_indent) else line.lstrip()
    return f"{base_indent}# {rest}"


def _activate_profile_platform(content: str, platform: str) -> str:
    """Activate one platform's dbt profile block, keeping the others as reference.

    The template marks each platform's YAML with ``# --- PLATFORM: <id> ---`` /
    ``# --- END PLATFORM ---`` and its toggleable lines with ``# @config`` /
    ``# @endconfig``. This uncomments the block matching ``platform`` and ensures
    the other platforms stay commented out; all marker lines are stripped from
    the output since they exist only to drive this selection. Lines inside a
    platform's region but outside its ``# @config``/``# @endconfig`` markers
    (e.g. alternative-auth notes) are left untouched regardless of activation.
    """
    current_platform: str | None = None
    in_config = False
    base_indent = ""
    output: list[str] = []
    for line in content.splitlines():
        if _PLATFORM_MARKER_RE.match(line):
            current_platform = _PLATFORM_MARKER_RE.match(line).group(1)
            continue
        if _PLATFORM_END_MARKER_RE.match(line):
            current_platform = None
            continue
        config_start_match = _CONFIG_START_RE.match(line)
        if config_start_match:
            in_config = True
            base_indent = config_start_match.group(1)
            continue
        if _CONFIG_END_RE.match(line):
            in_config = False
            continue
        if in_config and current_platform is not None:
            output.append(
                _toggle_config_line(
                    line, active=current_platform == platform, base_indent=base_indent
                )
            )
        else:
            output.append(line)
    return "\n".join(output) + "\n"


@click.command(name="init-dataplatform")
@click.argument("name", required=False, default=None)
@click.option(
    "--path",
    "dest",
    type=click.Path(),
    default=None,
    help="Parent directory to create the dataplatform repo in (default: sibling of hub).",
)
@click.option(
    "--platform",
    type=click.Choice(["fabric-lakehouse", "fabric-warehouse", "databricks"]),
    default="fabric-lakehouse",
    help="Target platform for dbt adapter configuration.",
)
@click.option(
    "--org",
    "org_override",
    type=str,
    default=None,
    help="GitHub organisation (default: same as hub repo).",
)
def init_dataplatform(name, dest, platform, org_override):
    """Scaffold a dataplatform dbt project linked to this ontology hub.

    Run this command from within an ontology-hub repository. It creates a
    sibling directory with a dbt project pre-configured to consume the
    hub's projections via dbt deps.

    \b
    NAME is the project name (default: derived from hub name, e.g.,
    "contoso-ontology-hub" → "contoso-dataplatform").

    \b
    What it creates:
      - dbt_project.yml with correct package reference
      - packages.yml pinned to the hub's current version
      - profiles.yml.example for your platform
      - macros/extract_source_schema.sql for bronze introspection
      - _sources.yml template with physical binding placeholders
      - pyproject.toml with uv + toolkit dependency
      - .github/workflows/deploy-powerbi-semantic-model.yml (fabric-cicd)
      - .github/fabric/deployment-settings.json.example
      - README.md with setup instructions

    \b
    Examples:
      kairos-ontology init-dataplatform
      kairos-ontology init-dataplatform contoso-data --platform databricks
    """
    # Detect hub context
    ctx = _detect_hub_context()
    hub_org = org_override or ctx["org"] or "your-org"
    hub_repo = ctx["repo_name"] or "your-ontology-hub"
    hub_version = ctx["version"]

    # Derive name
    if not name:
        base = hub_repo.replace("-ontology-hub", "").replace("-ontology", "")
        name = f"{base}-dataplatform"

    project_name = name.replace("-", "_")

    # Determine output directory
    if dest:
        parent = Path(dest)
    else:
        # Place sibling to the hub repo
        hub_git_root = (
            ctx["hub_root"].parent if ctx["hub_root"].name == "ontology-hub" else ctx["hub_root"]
        )
        parent = hub_git_root.parent

    repo_dir = parent / name

    if repo_dir.exists():
        raise click.ClickException(f"Directory already exists: {repo_dir}")

    click.echo(f"🚀 Creating dataplatform project: {name}")
    click.echo(f"   Location: {repo_dir}")
    click.echo(f"   Hub: {hub_org}/{hub_repo} @ {hub_version}")
    click.echo(f"   Platform: {platform}")
    if ctx["source_systems"]:
        click.echo(f"   Source systems: {', '.join(ctx['source_systems'])}")
    click.echo()

    # Create directory structure
    repo_dir.mkdir(parents=True)
    (repo_dir / "models" / "custom").mkdir(parents=True)
    (repo_dir / "macros").mkdir(parents=True)
    (repo_dir / "scripts").mkdir(parents=True)
    (repo_dir / "tests").mkdir(parents=True)
    (repo_dir / "seeds").mkdir(parents=True)
    (repo_dir / "snapshots").mkdir(parents=True)
    (repo_dir / "analyses").mkdir(parents=True)
    (repo_dir / ".dbt").mkdir(parents=True)

    # Template substitutions
    adapter_map = {
        "fabric-lakehouse": "dbt-fabric>=1.9.0",
        "fabric-warehouse": "dbt-fabric>=1.9.0",
        "databricks": "dbt-databricks>=1.9.0",
    }
    subs = {
        "{PROJECT_NAME}": project_name,
        "{ORG}": hub_org,
        "{HUB_REPO}": hub_repo,
        "{HUB_VERSION}": hub_version,
        "{DATABASE}": "your_bronze_database",
        "{SCHEMA}": "your_bronze_schema",
        "{DBT_ADAPTER}": adapter_map.get(platform, "dbt-fabric>=1.9.0"),
    }

    # Copy and template scaffold files
    template_files = {
        "dbt_project.yml.template": "dbt_project.yml",
        "packages.yml.template": "packages.yml",
        "profiles.yml.example": ".dbt/profiles.yml.example",
        "pyproject.toml.template": "pyproject.toml",
        "README.md.template": "README.md",
    }

    for src_name, dst_name in template_files.items():
        src = _DATAPLATFORM_SCAFFOLD / src_name
        if src.exists():
            content = src.read_text(encoding="utf-8")
            if src_name == "profiles.yml.example":
                content = _activate_profile_platform(content, platform)
            for placeholder, value in subs.items():
                content = content.replace(placeholder, value)
            (repo_dir / dst_name).write_text(content, encoding="utf-8")
            click.echo(f"  ✓ {dst_name}")

    # Copy macros
    for macro_name in ("extract_source_schema.sql", "print_query.sql"):
        macro_src = _DATAPLATFORM_SCAFFOLD / "macros" / macro_name
        if macro_src.exists():
            shutil.copy2(macro_src, repo_dir / "macros" / macro_name)
            click.echo(f"  ✓ macros/{macro_name}")

    # Copy helper scripts
    for script_name in ("package_fabric_semantic_model.py",):
        script_src = _DATAPLATFORM_SCAFFOLD / "scripts" / script_name
        if script_src.exists():
            shutil.copy2(script_src, repo_dir / "scripts" / script_name)
            click.echo(f"  ✓ scripts/{script_name}")

    # Generate _sources.yml from detected source systems
    if ctx["source_systems"]:
        sources_content = "# Physical Source Bindings\n"
        sources_content += "# Update database/schema per environment.\n\n"
        sources_content += "version: 2\n\nsources:\n"
        for sys_name in ctx["source_systems"]:
            sources_content += f"  - name: {sys_name}\n"
            sources_content += f'    description: "Bronze source: {sys_name}"\n'
            sources_content += '    database: "your_bronze_database"\n'
            sources_content += f'    schema: "raw_{sys_name}"\n'

            # Scan for table names in vocabulary TTL
            vocab_dir = ctx["hub_root"] / "integration" / "sources" / sys_name
            if vocab_dir.is_dir():
                from rdflib import Graph as RdfGraph, Namespace as RdfNamespace
                from rdflib.namespace import RDF as RDF_NS

                bronze_ns = RdfNamespace("https://kairos.cnext.eu/bronze#")
                g = RdfGraph()
                for ttl in vocab_dir.glob("*.ttl"):
                    try:
                        g.parse(ttl, format="turtle")
                    except Exception:
                        continue
                table_names = []
                for tbl_uri in g.subjects(RDF_NS.type, bronze_ns.SourceTable):
                    tbl_name = str(g.value(tbl_uri, bronze_ns.tableName) or "")
                    if tbl_name:
                        table_names.append(tbl_name)
                if table_names:
                    sources_content += "    tables:\n"
                    for tbl_name in sorted(table_names):
                        sources_content += f"      - name: {tbl_name}\n"
                else:
                    sources_content += "    # tables: (run schema discovery to populate)\n"
            else:
                sources_content += "    # tables: (run schema discovery to populate)\n"
            sources_content += "\n"

        (repo_dir / "models" / "_sources.yml").write_text(sources_content, encoding="utf-8")
        click.echo("  ✓ models/_sources.yml (pre-populated from hub vocabulary)")
    else:
        # Copy template
        src = _DATAPLATFORM_SCAFFOLD / "models" / "_sources.yml.template"
        if src.exists():
            content = src.read_text(encoding="utf-8")
            for placeholder, value in subs.items():
                content = content.replace(placeholder, value)
            (repo_dir / "models" / "_sources.yml").write_text(content, encoding="utf-8")
            click.echo("  ✓ models/_sources.yml (template)")

    # Create .gitignore
    gitignore = (
        "target/\ndbt_packages/\nlogs/\n.venv/\n__pycache__/\n*.pyc\n"
        ".env\nprofiles.yml\n.dbt/profiles.yml\n"
    )
    (repo_dir / ".gitignore").write_text(gitignore, encoding="utf-8")
    click.echo("  ✓ .gitignore")

    # Create .python-version
    (repo_dir / ".python-version").write_text("3.12\n", encoding="utf-8")
    click.echo("  ✓ .python-version")

    # Copy Copilot instructions and skills (managed files)
    github_dir = repo_dir / ".github"
    github_dir.mkdir(parents=True, exist_ok=True)

    dp_instructions = _SCAFFOLD_DIR / "dataplatform-copilot-instructions.md"
    if dp_instructions.is_file():
        _copy_managed(dp_instructions, github_dir / "copilot-instructions.md")
        click.echo("  ✓ .github/copilot-instructions.md")

    # Scaffold Fabric semantic-model deployment workflow (Phase 1: fabric-cicd)
    deploy_wf_src = (
        _DATAPLATFORM_SCAFFOLD
        / ".github"
        / "workflows"
        / "deploy-powerbi-semantic-model.yml.template"
    )
    deploy_wf_dst = github_dir / "workflows" / "deploy-powerbi-semantic-model.yml"
    if deploy_wf_src.is_file():
        wf_content = deploy_wf_src.read_text(encoding="utf-8")
        for placeholder, value in subs.items():
            wf_content = wf_content.replace(placeholder, value)
        deploy_wf_dst.parent.mkdir(parents=True, exist_ok=True)
        deploy_wf_dst.write_text(wf_content, encoding="utf-8")
        click.echo("  ✓ .github/workflows/deploy-powerbi-semantic-model.yml")

    deploy_cfg_src = (
        _DATAPLATFORM_SCAFFOLD / ".github" / "fabric" / "deployment-settings.json.example.template"
    )
    deploy_cfg_dst = github_dir / "fabric" / "deployment-settings.json.example"
    if deploy_cfg_src.is_file():
        cfg_content = deploy_cfg_src.read_text(encoding="utf-8")
        for placeholder, value in subs.items():
            cfg_content = cfg_content.replace(placeholder, value)
        deploy_cfg_dst.parent.mkdir(parents=True, exist_ok=True)
        deploy_cfg_dst.write_text(cfg_content, encoding="utf-8")
        click.echo("  ✓ .github/fabric/deployment-settings.json.example")

    skills_src = _SCAFFOLD_DIR / "skills"
    for skill_name in _DATAPLATFORM_SKILLS:
        skill_file = skills_src / skill_name / "SKILL.md"
        if skill_file.is_file():
            _copy_managed(skill_file, github_dir / "skills" / skill_name / "SKILL.md")
            click.echo(f"  ✓ .github/skills/{skill_name}/SKILL.md")

    # Create minimal Python package so hatchling can build the project
    pkg_name = project_name.replace("-", "_")
    pkg_dir = repo_dir / pkg_name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    click.echo(f"  ✓ {pkg_name}/__init__.py")

    # Initialize git repo
    try:
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=repo_dir,
            capture_output=True,
            check=True,
            timeout=10,
        )
        subprocess.run(
            ["git", "add", "."],
            cwd=repo_dir,
            capture_output=True,
            check=True,
            timeout=10,
        )
        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                f"chore: scaffold dataplatform from {hub_org}/{hub_repo}\n\n"
                f"Hub version: {hub_version}\n"
                f"Platform: {platform}\n\n"
                "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>",
            ],
            cwd=repo_dir,
            capture_output=True,
            check=True,
            timeout=10,
        )
        click.echo("  ✓ git init + initial commit")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        click.echo(f"  ⚠️  git init skipped: {e}")

    click.echo(f"\n✅ Dataplatform project created at: {repo_dir}")
    click.echo("\n📋 Next steps:")
    click.echo(f"   cd {name}")
    click.echo("   uv sync")
    click.echo("   # Edit profiles.yml.example → ~/.dbt/profiles.yml")
    click.echo("   # Edit models/_sources.yml with actual database/schema")
    click.echo("   dbt deps")
    click.echo("   dbt build")
    click.echo(
        "   # Configure Fabric secrets and run .github/workflows/deploy-powerbi-semantic-model.yml"
    )
