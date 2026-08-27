# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused setup CLI commands."""

import click
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


from ..core._provenance import provenance_comment
from ..core.analyse_sources import load_data_domains
from ..core.catalog_utils import sync_domain_catalog_entry
from ..core.decision_records import build_index_markdown
from ..core.feedback_records import build_index_markdown as build_feedback_index_markdown
from ..core.hub_utils import publish_root
from ..core.master_ontology import MasterOntologySyncError, sync_master_ontology_import

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
    _format_refmodels_fetch_provenance,
    _is_old_layout,
    _resolve_scaffold_refmodels_pin,
    _resolve_scaffold_toolkit_pin,
    _slugify,
    _tag_to_version,
    resolve_refmodels_dir,
)


def _registration_import_gate(
    *,
    domain: str,
    ontology_path: Path,
    hub: Path,
    refmodels_root: Path,
    catalog_path: Path | None,
    degraded: bool,
    modes_served: list[str] | None = None,
) -> None:
    """Refuse to register a pre-existing, import-incomplete domain (issue #426, DD-155).

    Raises ``SystemExit(1)`` — before the catalog write and the ``_master.ttl``
    sync — when the domain's Managed Import Completeness diagnostics contain
    hard errors, or degradable ``missing_managed_import`` errors without
    ``--degraded``.

    Scope caveat (DD-155): this builds a *single-domain* module context, which is
    a LOWER BOUND on what ``validate --all`` checks — the scoped context can pass
    where the full run fails (never the reverse of practical concern), so the
    skill's pre-registration ``validate --all --domain <domain>`` run remains
    necessary, not belt-and-braces.

    Failure ownership: toolkit-owned infrastructure exceptions (context build
    crash, unreadable TTL) warn and proceed — they must never block a user's
    registration. An *ambiguous* accelerator also warns and skips the gate,
    pointing at ``validate --all --accelerator <pack>``. DD-088 fleet mode: the
    gate blocks identically in fleet mode; an explicit ``--degraded`` is the
    only bypass.
    """
    from rdflib import Graph
    from rdflib.namespace import OWL

    from ..core.reference_modules import (
        build_reference_module_context,
        resolve_hub_accelerator_detailed,
    )
    from ..core.validator import validate_managed_imports

    try:
        resolution = resolve_hub_accelerator_detailed(
            explicit=None,
            hub_root=hub,
            ref_models_dir=refmodels_root,
            domain_hint=[domain],
        )
    except ValueError as exc:
        print(
            f"  ⚠ Managed-import registration gate skipped — {exc}\n"
            "      Check import completeness with "
            f"`kairos-ontology validate --all --accelerator <pack> --domain {domain}`."
        )
        return

    try:
        graph = Graph()
        graph.parse(ontology_path)
        imported_iris = {str(item) for item in graph.objects(predicate=OWL.imports)}
        module_context = build_reference_module_context(
            refmodels_root,
            catalog_path=catalog_path,
            accelerator=resolution.accelerator,
            requested_domains=[domain],
            imported_ontology_iris=imported_iris,
        )
        if module_context is None:
            return  # no accelerator module config resolvable — nothing to gate on
        diagnostics = validate_managed_imports(
            ontology_path,
            domain=domain,
            module_context=module_context,
            modes_served=modes_served,
        )
    except Exception as exc:  # noqa: BLE001 — toolkit-owned failures must not block
        print(
            f"  ⚠ Managed-import registration gate skipped for {domain} "
            f"({type(exc).__name__}: {exc}); run "
            f"`kairos-ontology validate --all --domain {domain}` to check imports."
        )
        return

    # Mirror run_validation's Managed Import Completeness semantics (DD-155):
    # hard errors always block; missing_managed_import blocks unless --degraded.
    errors = [item for item in diagnostics if item.level == "error"]
    warnings = [item for item in diagnostics if item.level != "error"]
    hard_errors = [item for item in errors if item.code != "missing_managed_import"]
    degradable_errors = [item for item in errors if item.code == "missing_managed_import"]
    for item in warnings:
        print(f"  ⚠ {item.message}")
    if hard_errors or (degradable_errors and not degraded):
        for item in errors:
            print(f"  ❌ {item.message}")
        print(
            f"  ❌ {domain} failed the managed-import completeness check above — "
            "registration refused — fix the imports or rerun with --degraded."
        )
        raise SystemExit(1)
    if degradable_errors:
        for item in degradable_errors:
            print(f"  ⚠ {item.message}")
        print(
            f"  ⚠ --degraded accepted {len(degradable_errors)} missing managed "
            f"import(s) for {domain}; registration proceeds."
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
@click.option(
    "--skip-refmodels",
    "skip_refmodels",
    is_flag=True,
    default=False,
    help="Skip adding the kairos-ontology-referencemodels dependency (install it later).",
)
@click.option(
    "--ref-models-version",
    "ref_models_version",
    type=str,
    default=None,
    help="Pin a specific kairos-ontology-referencemodels release (e.g. v1.33.1). "
    "Default: the latest published stable release.",
)
@click.option(
    "--degraded",
    is_flag=True,
    default=False,
    help="Explicitly allow incomplete ontology imports for semantic validation; "
    "results are marked import_complete=false.",
)
@click.option(
    "--channel",
    "channel",
    type=click.Choice(["stable", "preview"]),
    default=None,
    help="Toolkit release channel to pin: 'stable' (latest GA) or 'preview' (latest rc/beta). "
    "Defaults to auto-detection from the running toolkit version.",
)
def init(domain, company_domain, force, skip_refmodels, ref_models_version, degraded, channel):
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
    hub_already_existed = hub.exists()

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

    # Modeling — toolkit-managed, git-tracked OKF-style records (distinct from raw
    # client evidence in .import/businessdiscovery/, which stays gitignored).
    imports_modeling = cwd / ".import" / "modeling"
    imports_modeling.mkdir(parents=True, exist_ok=True)
    modeling_readme_src = _SCAFFOLD_DIR / "import" / "modeling" / "README.md"
    if modeling_readme_src.is_file() and (not (imports_modeling / "README.md").exists() or force):
        shutil.copy2(modeling_readme_src, imports_modeling / "README.md")

    # Modeling-feedback bundle (OKF-style, lighter-weight sibling of the decision log).
    feedback_src = _SCAFFOLD_DIR / "import" / "modeling" / "feedback"
    feedback_dst = imports_modeling / "feedback"
    feedback_dst.mkdir(parents=True, exist_ok=True)
    for filename in ("README.md", "FEEDBACK-template.md.template"):
        src = feedback_src / filename
        dst = feedback_dst / filename
        if src.is_file() and (not dst.exists() or force):
            _copy_managed(src, dst)
    feedback_index_dst = feedback_dst / "index.md"
    if not feedback_index_dst.exists() or force:
        feedback_index_dst.write_text(build_feedback_index_markdown([]), encoding="utf-8")
        print("  ✓ Created .import/modeling/feedback/index.md")

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

    # 3. Copy skills into .claude/skills/ (read directly by both Claude Code and
    # GitHub Copilot's Agent Skills support)
    skills_src = _SCAFFOLD_DIR / "skills"
    skills_dst = cwd / ".claude" / "skills"
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
            ref, tk_channel = _resolve_scaffold_toolkit_pin(channel=channel)
            version = _tag_to_version(ref)
            rm_ref, rm_version = _resolve_scaffold_refmodels_pin(version_tag=ref_models_version)
            repo_name = cwd.name
            content = pyproject_src.read_text(encoding="utf-8")
            content = (
                content.replace("{repo_name}", repo_name)
                .replace("{description}", repo_name)
                .replace("{toolkit_ref}", ref)
                .replace("{toolkit_version}", version)
                .replace("{toolkit_channel}", tk_channel)
                .replace("{refmodels_ref}", rm_ref)
                .replace("{refmodels_version}", rm_version)
            )
            pyproject_dst.write_text(content, encoding="utf-8")
            print("  ✓ Created pyproject.toml")
            print(f"    toolkit {ref} (channel '{tk_channel}'), reference models {rm_ref}")

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
    from ..core.archetype_loader import _looks_like_refmodels_root

    refmodels_dest = resolve_refmodels_dir(cwd, hub)
    if domain:
        template_src = (
            _SCAFFOLD_DIR / "ontology-hub" / "model" / "ontologies" / "starter.ttl.template"
        )
        ontology_dst = hub / "model" / "ontologies" / f"{domain}.ttl"
        # A pre-existing (and kept) TTL is authored content that must pass the
        # managed-import registration gate below (issue #426, DD-155); a TTL this
        # run scaffolds (fresh, or overwritten via --force) is the toolkit's own
        # starter with no owl:imports and is never gated.
        ontology_preexisted = ontology_dst.exists() and not force
        if ontology_preexisted:
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
            # Managed-import registration gate (issue #426, DD-155): refuse to
            # register a PRE-EXISTING, import-incomplete domain — before the
            # catalog write and the _master.ttl sync below, so a refused run
            # leaves both untouched. Freshly scaffolded starters are never gated
            # (they carry no owl:imports by design); they get an advisory instead.
            refmodels_available = (
                refmodels_dest is not None
                and refmodels_dest.is_dir()
                and _looks_like_refmodels_root(refmodels_dest)
            )
            if ontology_preexisted and refmodels_available:
                from ..core.hub_inspection import configured_modes_served

                _registration_import_gate(
                    domain=domain,
                    ontology_path=ontology_dst,
                    hub=hub,
                    refmodels_root=refmodels_dest,
                    catalog_path=catalog_dst if catalog_dst.is_file() else None,
                    degraded=degraded,
                    modes_served=configured_modes_served(hub),
                )
            elif refmodels_available:
                print(
                    f"  ℹ Freshly scaffolded {domain}.ttl registered without the "
                    "managed-import gate (the starter template has no owl:imports yet). "
                    f"After authoring, run `kairos-ontology validate --all --domain {domain}`."
                )
            ontology_iri = sync_domain_catalog_entry(
                catalog_dst,
                ontology_dst,
                company_domain=company_domain,
            )
            print(f"  ✓ Registered {ontology_iri} in ontology-hub/catalog-v001.xml")

            # Issue #393: a domain can be authored, cataloged, bound, and validated
            # yet never imported by _master.ttl -- silently unreachable from the
            # hub's single ontology entry point. Sync it automatically here so that
            # gap can no longer occur by default. Best-effort/secondary: never
            # crashes `init` -- a missing or unreadable _master.ttl only warns.
            if master_dst.exists():
                try:
                    inserted = sync_master_ontology_import(master_dst, ontology_iri)
                except MasterOntologySyncError as exc:
                    print(
                        f"  ⚠ Could not sync _master.ttl automatically: {exc}\n"
                        f'      Add "owl:imports <{ontology_iri}>" to '
                        "ontology-hub/model/ontologies/_master.ttl manually."
                    )
                else:
                    if inserted:
                        print(
                            f"  ✓ Synced owl:imports <{ontology_iri}> into "
                            "ontology-hub/model/ontologies/_master.ttl"
                        )
                    else:
                        print(
                            f"  ⏭  ontology-hub/model/ontologies/_master.ttl already imports "
                            f"{ontology_iri}"
                        )
            else:
                print(
                    "  ⚠ ontology-hub/model/ontologies/_master.ttl not found; "
                    "skipping owl:imports sync."
                )

    # 9. Reference models are now resolved from an installed Python package.
    #
    # `uv sync` (step 10) installs the kairos-ontology-referencemodels package
    # listed in the scaffolded pyproject.toml dependencies. No sparse clone,
    # no committed copy, and no init-time inventory pre-generation —
    # inventories are generated on-demand by `compile` / `check-inventory`.
    if skip_refmodels:
        print(
            "  ⏭  Skipped reference models package "
            "(install manually: `uv pip install kairos-ontology-referencemodels`)"
        )
    else:
        provenance = _format_refmodels_fetch_provenance(None)
        if provenance:
            print(f"  ✓ Reference models package available: {provenance}")
        else:
            print(
                "  ℹ  Reference models package will be installed by `uv sync` "
                "(run `kairos-ontology update-refmodels` to upgrade later)"
            )

    if hub_already_existed:
        if domain:
            print(f"\n✅ Domain '{domain}' added to existing ontology hub!")
        else:
            print("\n✅ Existing ontology hub scaffold refreshed!")
    else:
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
    help="Pin a specific kairos-ontology-referencemodels release (e.g. v1.33.1). "
    "Default: the latest published stable release.",
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
@click.option(
    "--channel",
    "channel",
    type=click.Choice(["stable", "preview"]),
    default=None,
    help="Toolkit release channel to pin: 'stable' (latest GA) or 'preview' (latest rc/beta). "
    "Defaults to auto-detection from the running toolkit version.",
)
@click.option(
    "--local-only",
    "local_only",
    is_flag=True,
    default=False,
    help="Scaffold and git-init on disk without creating or pushing a GitHub remote. "
    "For throwaway hubs used to exercise the toolkit; a client hub belongs on GitHub.",
)
def new_repo(
    name, desc, dest, org, is_private, ref_models_version, company_domain, skip_protection,
    channel, local_only,
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

    # Modeling — toolkit-managed, git-tracked OKF-style records (distinct from raw
    # client evidence in .import/businessdiscovery/, which stays gitignored).
    imports_modeling = repo_dir / ".import" / "modeling"
    imports_modeling.mkdir(parents=True, exist_ok=True)
    modeling_readme_src = _SCAFFOLD_DIR / "import" / "modeling" / "README.md"
    if modeling_readme_src.is_file():
        shutil.copy2(modeling_readme_src, imports_modeling / "README.md")

    feedback_src = _SCAFFOLD_DIR / "import" / "modeling" / "feedback"
    feedback_dst = imports_modeling / "feedback"
    feedback_dst.mkdir(parents=True, exist_ok=True)
    for filename in ("README.md", "FEEDBACK-template.md.template"):
        src = feedback_src / filename
        dst = feedback_dst / filename
        if src.is_file():
            _copy_managed(src, dst)
    (feedback_dst / "index.md").write_text(build_feedback_index_markdown([]), encoding="utf-8")
    print("  ✓ .import/modeling/feedback/ (modeling feedback)")

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

    # Skills — installed into .claude/skills/, read directly by both Claude Code
    # and GitHub Copilot's Agent Skills support
    skills_src = _SCAFFOLD_DIR / "skills"
    skills_dst = repo_dir / ".claude" / "skills"
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
        # Same pin policy as `init` — never the running (possibly unpublished) version.
        ref, tk_channel = _resolve_scaffold_toolkit_pin(channel=channel)
        rm_ref, rm_version = _resolve_scaffold_refmodels_pin(version_tag=ref_models_version)
        content = pyproject_src.read_text(encoding="utf-8")
        content = (
            content.replace("{repo_name}", repo_slug)
            .replace("{description}", description)
            .replace("{toolkit_version}", _tag_to_version(ref))
            .replace("{toolkit_ref}", ref)
            .replace("{toolkit_channel}", tk_channel)
            .replace("{refmodels_ref}", rm_ref)
            .replace("{refmodels_version}", rm_version)
        )
        (repo_dir / "pyproject.toml").write_text(content, encoding="utf-8")
        print("  ✓ pyproject.toml")
        print(f"    toolkit {ref} (channel '{tk_channel}'), reference models {rm_ref}")

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

    # --- .env.example ---------------------------------------------------------
    # `init` and `update` both install this, but a hub scaffolded with --local-only may
    # sit for a while before `init` runs, and the AI provider config is the first thing
    # someone looks for. Emitted here, before git init, so it lands in the first commit.
    env_example_src = _SCAFFOLD_DIR / ".env.example"
    env_example_dst = repo_dir / ".env.example"
    if env_example_src.is_file() and not env_example_dst.exists():
        shutil.copy2(env_example_src, env_example_dst)
        print("  ✓ .env.example (AI provider configuration template)")

    # setup-env.ps1 (uv environment bootstrap)
    setup_env_src = _SCAFFOLD_DIR / "setup-env.ps1"
    if setup_env_src.is_file():
        shutil.copy2(setup_env_src, repo_dir / "setup-env.ps1")
        print("  ✓ setup-env.ps1 (uv environment bootstrap)")

    # setup-env.sh (bash equivalent for Linux/CI)
    setup_env_sh_src = _SCAFFOLD_DIR / "setup-env.sh"
    if setup_env_sh_src.is_file():
        shutil.copy2(setup_env_sh_src, repo_dir / "setup-env.sh")
        print("  ✓ setup-env.sh (uv environment bootstrap - bash)")

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
    # _create_github_repo hard-fails by design ("repos must be never local-only"), which
    # is right for a client hub and wrong for a hub whose only purpose is to exercise the
    # toolkit end-to-end. --local-only relaxes that deliberately and says so on the way out.
    if local_only:
        print("\n⏭  Skipping GitHub repo creation (--local-only)")
        print("   This hub has no remote. Publish it later with:")
        print(f"     cd {repo_dir}")
        print(
            f"     gh repo create {org}/{repo_slug} "
            f"{'--private' if is_private else '--public'} --source . --push"
        )
    else:
        _create_github_repo(repo_dir, repo_slug, org, description, is_private)

    # --- Reference models are installed via pyproject.toml + uv sync ----------
    # No separate fetch step — the scaffolded pyproject.toml already pins
    # kairos-ontology-referencemodels, and `uv sync` (run by the user after
    # new-repo) installs it.

    # --- Configure branch protection on main ---------------------------------
    if not skip_protection and not local_only:
        full_name = f"{org}/{repo_slug}"
        print("\n🔒 Configuring branch protection on main...")
        _configure_branch_protection(repo_dir, full_name)

    print(f"\n✅ Repository created: {repo_slug}")
    if local_only:
        # Printing a github.com URL here would advertise a repo that does not exist.
        print(f"   Local only (no remote): {repo_dir}")
    else:
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
    # Upper-bounded below dbt Core 2.0 (the former "Fusion" engine, now in beta as of
    # 2026-08 -- see dbt-labs/dbt-core's 2026-06-announcing-v2.md roadmap doc): it ships a
    # stricter codified language spec than v1.x, and neither adapter has a 2.0-compatible
    # release yet, so an unbounded floor-only pin would silently let a future `uv sync`
    # resolve into it. Revisit this ceiling once the adapters publish 2.0-line releases and
    # the generated dbt project has been validated against the new spec.
    adapter_map = {
        "fabric-lakehouse": "dbt-fabric>=1.9.0,<2.0.0",
        "fabric-warehouse": "dbt-fabric>=1.9.0,<2.0.0",
        "databricks": "dbt-databricks>=1.9.0,<2.0.0",
    }
    subs = {
        "{PROJECT_NAME}": project_name,
        "{ORG}": hub_org,
        "{HUB_REPO}": hub_repo,
        "{HUB_VERSION}": hub_version,
        "{DATABASE}": "your_bronze_database",
        "{SCHEMA}": "your_bronze_schema",
        "{DBT_ADAPTER}": adapter_map.get(platform, "dbt-fabric>=1.9.0,<2.0.0"),
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
    claude_dir = repo_dir / ".claude"
    for skill_name in _DATAPLATFORM_SKILLS:
        skill_file = skills_src / skill_name / "SKILL.md"
        if skill_file.is_file():
            _copy_managed(skill_file, claude_dir / "skills" / skill_name / "SKILL.md")
            click.echo(f"  ✓ .claude/skills/{skill_name}/SKILL.md")

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


# ---------------------------------------------------------------------------
# scaffold-domain  (issue #469, todo E5-scaffold-domain)
# ---------------------------------------------------------------------------

_DOMAIN_NAME_PATTERN = re.compile(r"https://([^/]+)/ont/")


def _extract_company_domain(hub: Path) -> str | None:
    """Extract the ``company_domain`` from an existing hub's ontology files.

    Scans ``_master.ttl`` then every other ``.ttl`` under ``model/ontologies/``
    for the ``https://<company_domain>/ont/`` pattern. Falls back to
    ``catalog-v001.xml`` if no ontology file yields a match.

    Returns ``None`` when no company domain can be recovered.
    """
    ont_dir = hub / "model" / "ontologies"

    # 1. Try _master.ttl first (always present in a well-formed hub).
    master = ont_dir / "_master.ttl"
    candidates: list[Path] = []
    if master.is_file():
        candidates.append(master)

    # 2. Then every remaining .ttl in the ontologies directory.
    if ont_dir.is_dir():
        for ttl in sorted(ont_dir.glob("*.ttl")):
            if ttl not in candidates:
                candidates.append(ttl)

    for ttl in candidates:
        try:
            text = ttl.read_text(encoding="utf-8")
        except OSError:
            continue
        m = _DOMAIN_NAME_PATTERN.search(text)
        if m:
            return m.group(1)

    # 3. Fall back to the XML catalog.
    catalog = hub / "catalog-v001.xml"
    if catalog.is_file():
        try:
            text = catalog.read_text(encoding="utf-8")
        except OSError:
            return None
        m = _DOMAIN_NAME_PATTERN.search(text)
        if m:
            return m.group(1)

    return None


def _load_cross_domain_relationships(
    refmodels_dir: Path | None, accelerator: str | None
) -> list[dict[str, Any]]:
    """Return the accelerator blueprint's declared ``cross_domain_relationships``.

    The logistics pack ships 24 of these — ``booking-to-consignment``,
    ``consignment-to-invoice``, and so on — each naming a property IRI plus its domain and
    range classes. Nothing in the toolkit read them, so an author who needed to reach
    another domain had no declared route and minted a local class instead.

    Best-effort: an unreadable or absent blueprint yields ``[]`` rather than failing a
    scaffold, since this enriches a header and gates nothing.

    Delegates to the core loader (DD-181), which alignment also uses for its anchor
    pool — one reader, so a scaffold header and the anchor pool can never disagree
    about what the blueprint authorises.
    """
    if refmodels_dir is None or not accelerator:
        return []
    from ..core.analyse_sources import load_cross_domain_bridges

    return load_cross_domain_bridges(Path(refmodels_dir), accelerator)


def _wrap_comment(text: str, *, prefix: str = "#   ", width: int = 88) -> list[str]:
    """Wrap *text* into ``#``-prefixed comment lines."""
    import textwrap

    return [f"{prefix}{line}" for line in textwrap.wrap(text, width=width - len(prefix))] or []


def _build_boundary_header(
    *,
    domain: str,
    label: str,
    blueprint: dict[str, Any] | None,
    cross_domain: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Render the blueprint's ownership boundary as the file's own header (DD-163).

    ``scaffold-domain --from-blueprint`` previously copied only ``imports[].uri``, so the
    one artifact an author actually edits never stated what the domain owns. The
    boundaries existed — as a contract field feeding the source-affinity classifier — but
    were invisible at the moment they were being crossed, and a full run produced eight
    domains declaring ``Booking``.

    Writing them here also makes them *enforceable*: ``integrity.class-violates-declared-
    exclusion`` reads exactly this ``Deliberate exclusions`` block, so a scaffold-generated
    domain arrives with a boundary a validator can check rather than an empty header a
    later pass has to remember to write (the same header every file in that run kept
    verbatim).
    """
    lines = [
        "# " + "=" * 76,
        f"# Domain: {domain}",
        f"# {label}",
        "#",
    ]
    if blueprint:
        owns = str(blueprint.get("owns") or "").strip()
        excluded = str(blueprint.get("does_not_own") or "").strip()
        if owns:
            lines.append("# OWNS (accelerator blueprint):")
            lines.extend(_wrap_comment(owns))
            lines.append("#")
        if excluded:
            # Parsed by core/ontology_integrity.py -- keep the heading text stable, and
            # seed the bullet form its parser recognises ("- <Concept>: owned by the <x>
            # domain"). An author extending this block then produces enforceable entries
            # by default instead of prose the checker cannot read.
            lines.append("# Deliberate exclusions (with reasons):")
            lines.extend(
                _wrap_comment(f"Blueprint DOES NOT OWN: {excluded}", prefix="#   ")
            )
            lines.append("#   Record each concept you leave out as its own bullet, in this")
            lines.append("#   form, so 'kairos-ontology validate' can enforce it:")
            lines.append("#     - <Concept>: owned by the <other> domain; <why>")
            lines.append("#")
    if cross_domain:
        lines.append("# Declared cross-domain relationships (use these, do not re-mint a class):")
        for bridge in cross_domain:
            prop = str(bridge.get("property_uri") or "")
            target = str(bridge.get("target_domain") or "")
            desc = str(bridge.get("description") or "").strip()
            lines.append(f"#   -> {target}: <{prop}>")
            if desc:
                lines.extend(_wrap_comment(desc, prefix="#      "))
        lines.append("#")
    lines.extend(
        [
            "# Author classes and properties with kairos-design-domain. A concept another",
            "# domain owns is referenced across the boundary (externalReference, DD-133 §7),",
            "# never re-declared here -- 'kairos-ontology validate' fails a redeclaration.",
            "# " + "=" * 76,
            "",
        ]
    )
    return lines


def _build_domain_ttl(
    *,
    domain: str,
    label: str,
    company_domain: str,
    imports: list[dict[str, str]],
    blueprint: dict[str, Any] | None = None,
    cross_domain: list[dict[str, Any]] | None = None,
) -> str:
    """Generate starter TTL content for a domain ontology (text template, not rdflib).

    Mirrors the ``starter.ttl.template`` convention but injects mandated
    ``owl:imports`` lines from the accelerator blueprint when available, plus the
    blueprint's ownership boundary as a header block (see :func:`_build_boundary_header`).
    """
    lines: list[str] = _build_boundary_header(
        domain=domain, label=label, blueprint=blueprint, cross_domain=cross_domain
    )
    lines += [
        f"@prefix : <https://{company_domain}/ont/{domain}#> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
        f"<https://{company_domain}/ont/{domain}> a owl:Ontology ;",
        f'    rdfs:label "{label}"@en ;',
        f'    rdfs:comment "Ontology for the {label} domain"@en ;',
        '    owl:versionInfo "0.1.0" .',
    ]

    if imports:
        iri_to_uri = {}
        for imp in imports:
            uri = imp.get("uri")
            if not uri:
                continue
            iri_to_uri[uri] = uri

        if iri_to_uri:
            lines.append("")
            lines.append(
                "## -- Mandated imports from accelerator blueprint data-domains.yaml."
            )
            lines.append("## -- Add matching catalog-v001.xml <uri> entries for offline resolution.")
            ontology_iri = f"<https://{company_domain}/ont/{domain}>"
            for iri in iri_to_uri:
                lines.append(f"{ontology_iri} owl:imports <{iri}> .")

    lines.append("")
    lines.append("## -- Domain classes below.")
    lines.append("## -- To share base conventions, import the foundation ontology:")
    lines.append(f"##   owl:imports <https://{company_domain}/ont/_foundation> ;")
    lines.append("## -- (add a matching catalog-v001.xml <uri> entry so it resolves offline).")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# --ai flag helpers (issue #470, todo E6-ai-flag)
# ---------------------------------------------------------------------------


def _gather_ai_context(hub: Path, domain_slug: str) -> str:
    """Gather conformance evidence and source-vocabulary context as prompt text.

    Reads the conformance artifact from ``integration/discovery/`` and every source
    system vocabulary TTL under ``integration/sources/``. Returns a compact human-
    readable string suitable for inclusion in an LLM prompt. Missing directories or
    files are gracefully omitted — the caller always produces a valid prompt.
    """
    parts: list[str] = []

    # 1. Conformance evidence.
    conformance_path = hub / "integration" / "discovery" / "core-concepts-conformance.yaml"
    if conformance_path.is_file():
        try:
            from kairos_ontology.core.conformance_artifact import read_artifact

            artifact = read_artifact(conformance_path)
            concepts = artifact.get("concepts", [])
            if isinstance(concepts, list) and concepts:
                lines: list[str] = ["## Confirmed core concepts (from discovery conformance):"]
                for concept in concepts:
                    if not isinstance(concept, dict):
                        continue
                    likely_domains = concept.get("likely_domains") or []
                    if likely_domains and domain_slug not in {d.lower() for d in likely_domains if isinstance(d, str)}:
                        continue
                    name = concept.get("name") or concept.get("term") or "(unnamed)"
                    predicate = concept.get("predicate", "")
                    outcome = concept.get("outcome", "")
                    rationale = concept.get("rationale", "")
                    line = f"- {name}"
                    if predicate:
                        line += f" ({predicate})"
                    if outcome:
                        line += f" — outcome: {outcome}"
                    if rationale:
                        line += f" — {rationale}"
                    lines.append(line)
                if len(lines) > 1:
                    parts.append("\n".join(lines))
        except Exception:
            pass

    # 2. Source schemas.
    sources_dir = hub / "integration" / "sources"
    if sources_dir.is_dir():
        vocab_files = sorted(sources_dir.rglob("*.vocabulary.ttl"))
        if vocab_files:
            schema_parts: list[str] = ["## Source system schemas (from integration/sources/):"]
            for vf in vocab_files[:10]:
                try:
                    text = vf.read_text(encoding="utf-8")
                except OSError:
                    continue
                rel = vf.relative_to(hub)
                # Extract a compact table/column summary from the raw TTL.
                schema_parts.append(f"### {rel}")
                # Include the raw TTL but truncated to keep the prompt bounded.
                snippet = text[:2000]
                schema_parts.append(f"```turtle\n{snippet}\n```")
            if len(schema_parts) > 1:
                parts.append("\n".join(schema_parts))

    return "\n\n".join(parts) if parts else ""


def _build_ai_domain_prompt(
    *,
    domain: str,
    label: str,
    company_domain: str,
    imports: list[dict[str, str]],
    context: str,
) -> str:
    """Build the prompt sent to the AI provider for domain TTL generation."""
    import_uris = [imp.get("uri", "") for imp in imports if imp.get("uri")]

    prompt_lines = [
        f"Generate a complete OWL/Turtle domain ontology for the '{domain}' domain ({label}).",
        "",
        "## Ontology conventions (MUST follow):",
        "- Every ontology declares owl:Ontology, rdfs:label, and owl:versionInfo.",
        "- Use HTTP(S) namespaces. Classes are PascalCase; properties are camelCase.",
        "- Every class has a label and comment. Every property has domain, range, and label.",
        f"- Use the prefix ': <https://{company_domain}/ont/{domain}#> .'",
        f"- The ontology IRI must be <https://{company_domain}/ont/{domain}>.",
        "",
        "## Required prefixes:",
        f"@prefix : <https://{company_domain}/ont/{domain}#> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
    ]
    if import_uris:
        prompt_lines.append("## Mandated owl:imports (include these IRIs):")
        for iri in import_uris:
            prompt_lines.append(f"  <{iri}>")
        prompt_lines.append("")

    prompt_lines.append("## Instructions:")
    prompt_lines.append("Generate OWL/Turtle ONLY — no markdown fences, no commentary.")
    prompt_lines.append("Start with @prefix lines, then the owl:Ontology declaration.")
    prompt_lines.append("Include at least 2-3 class stubs and 3-5 property stubs derived from")
    prompt_lines.append("the conformance evidence and source schemas below.")
    prompt_lines.append("")

    if context:
        prompt_lines.append(context)
    else:
        prompt_lines.append("## Context: No conformance evidence or source schemas found.")
        prompt_lines.append(f"Generate reasonable class and property stubs for the '{label}' domain.")

    return "\n".join(prompt_lines)


def _generate_domain_ttl_with_ai(
    *,
    domain: str,
    label: str,
    company_domain: str,
    imports: list[dict[str, str]],
    hub: Path,
) -> str | None:
    """Call the AI provider to generate domain TTL content.

    Returns the generated TTL text (without provenance comment), or ``None`` when
    the AI call fails or the generated content is not valid Turtle. The caller is
    responsible for prepending the provenance comment and writing the file.
    """
    from kairos_ontology.core.ai_preflight import require_ai_provider
    from kairos_ontology.core.ai_provider import get_ai_client
    from kairos_ontology.core._concurrency import call_with_backoff

    # Fail fast if AI is not configured — re-raise so the command can decide.
    provider_config = require_ai_provider(None, probe=False)
    model_name = provider_config.model

    context = _gather_ai_context(hub, domain)
    prompt = _build_ai_domain_prompt(
        domain=domain,
        label=label,
        company_domain=company_domain,
        imports=imports,
        context=context,
    )

    client = get_ai_client()

    try:
        response = call_with_backoff(
            lambda: client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert ontologist. You generate valid OWL/Turtle "
                            "domain ontologies following best practices: classes with labels "
                            "and comments, properties with domain, range, and labels. You "
                            "respond with raw Turtle text only — no markdown fences, no JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
        )
        raw_content = response.choices[0].message.content
    except Exception as e:
        print(f"  ⚠ AI provider call failed: {e}")
        return None

    if not raw_content or not raw_content.strip():
        print("  ⚠ AI provider returned empty content.")
        return None

    # Strip markdown fences if present.
    text = raw_content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)

    # Validate that it parses as Turtle.
    try:
        from rdflib import Graph

        g = Graph()
        g.parse(data=text, format="turtle")
    except Exception as e:
        print(f"  ⚠ AI-generated TTL failed Turtle parsing: {e}")
        return None

    return text


@click.command(name="scaffold-domain")
@click.option(
    "--domain",
    "domain",
    required=True,
    type=str,
    help='Domain name (e.g. "customer" — becomes the .ttl file stem).',
)
@click.option(
    "--from-blueprint",
    "accelerator",
    default=None,
    type=str,
    help="Read mandated imports from data-domains.yaml in the named accelerator pack. "
    "When omitted, a bare starter with no imports is generated.",
)
@click.option(
    "--label",
    "label",
    default=None,
    type=str,
    help='Human-readable domain label (default: title-cased domain name).',
)
@click.option("--force", is_flag=True, help="Overwrite existing .ttl file.")
@click.option(
    "--refmodels-root",
    "refmodels_root",
    default=None,
    type=click.Path(exists=True, file_okay=False),
    help="Override reference-models root (default: auto-detected from installed package).",
)
@click.option(
    "--ai",
    "use_ai",
    is_flag=True,
    default=False,
    help="Use the configured AI provider to generate domain class/property stubs "
    "from conformance evidence and source schemas.",
)
def scaffold_domain(domain, accelerator, label, force, refmodels_root, use_ai):
    """Scaffold a new domain ontology in an existing hub (issue #469)."""
    # 1. Detect hub root from CWD (same logic as _detect_hub_context).
    cwd = Path.cwd()
    hub: Path | None = None
    for candidate in [cwd / "ontology-hub", cwd]:
        if (candidate / "model" / "ontologies").is_dir():
            hub = candidate
            break

    if hub is None:
        raise click.ClickException(
            "Could not detect an ontology-hub in the current directory.\n"
            "Run this command from the root of a hub repository (containing "
            "ontology-hub/model/ontologies/)."
        )

    # 2. Extract company_domain from existing hub files.
    company_domain = _extract_company_domain(hub)
    if not company_domain:
        raise click.ClickException(
            "Could not determine the company domain from existing hub files.\n"
            "Ensure ontology-hub/model/ontologies/_master.ttl or catalog-v001.xml "
            "contains a 'https://<company_domain>/ont/' URI."
        )

    # 3. Slugify the domain name for the file stem.
    domain_slug = re.sub(r"[^a-z0-9-]", "-", domain.lower().strip()).strip("-")
    if not domain_slug:
        raise click.ClickException(
            f"Invalid domain name: {domain!r} — must contain at least one "
            "alphanumeric character."
        )

    # 4. Determine the label.
    resolved_label = label if label else domain_slug.replace("-", " ").replace("_", " ").title()

    ont_dir = hub / "model" / "ontologies"
    ontology_dst = ont_dir / f"{domain_slug}.ttl"

    # 5. Refuse to overwrite an existing file without --force.
    if ontology_dst.exists() and not force:
        raise click.ClickException(
            f"ontology-hub/model/ontologies/{domain_slug}.ttl already exists.\n"
            "Use --force to overwrite."
        )

    print("🚀 Scaffolding domain ontology")
    print(f"   Hub:           {hub}")
    print(f"   Domain:        {domain_slug}")
    print(f"   Company domain: {company_domain}")
    if accelerator:
        print(f"   Accelerator:   {accelerator}")
    print()

    # 6. Resolve mandated imports from the blueprint if --from-blueprint is given.
    imports: list[dict[str, str]] = []
    blueprint_domain: dict[str, Any] | None = None
    cross_domain_bridges: list[dict[str, Any]] = []
    if accelerator:
        if refmodels_root is not None:
            refmodels_dir: Path | None = Path(refmodels_root)
        else:
            refmodels_dir = resolve_refmodels_dir(cwd, hub)
        if refmodels_dir is None or not refmodels_dir.is_dir():
            raise click.ClickException(
                f"Could not resolve reference-models directory for accelerator "
                f"'{accelerator}'.\n"
                "Pass --refmodels-root <path> pointing at a directory containing "
                "accelerator-packs/<name>/client-hub-blueprint/data-domains.yaml."
            )
        data_domains = load_data_domains(refmodels_dir, accelerator)
        if not data_domains:
            raise click.ClickException(
                f"No data-domains.yaml found for accelerator '{accelerator}' "
                f"under {refmodels_dir}."
            )
        if domain_slug not in data_domains:
            available = ", ".join(sorted(data_domains.keys())) or "(none)"
            raise click.ClickException(
                f"Domain '{domain_slug}' not found in data-domains.yaml for "
                f"accelerator '{accelerator}'.\n"
                f"Available domains: {available}"
            )
        imports = data_domains[domain_slug].get("imports", [])
        if imports:
            print(f"  ✓ Loaded {len(imports)} mandated import(s) from blueprint")
        blueprint_domain = data_domains[domain_slug]
        # The blueprint's own declared bridges out of this domain. Naming them in the
        # header is what makes "reference it, do not re-mint it" actionable rather than
        # an instruction with no target.
        cross_domain_bridges = [
            bridge
            for bridge in _load_cross_domain_relationships(refmodels_dir, accelerator)
            if bridge.get("source_domain") == domain_slug
        ]
        if blueprint_domain.get("does_not_own"):
            print("  ✓ Wrote blueprint ownership boundary into the domain header")
        if cross_domain_bridges:
            print(f"  ✓ Listed {len(cross_domain_bridges)} declared cross-domain bridge(s)")

    # 7. Generate the TTL content.
    content: str
    if use_ai:
        print("🤖 Generating domain content via AI provider …")
        try:
            ai_content = _generate_domain_ttl_with_ai(
                domain=domain_slug,
                label=resolved_label,
                company_domain=company_domain,
                imports=imports,
                hub=hub,
            )
        except Exception as e:
            print(f"❌ AI provider is not available: {e}")
            raise click.ClickException(
                "AI provider is not configured or not reachable.\n"
                "Run 'kairos-ontology check-ai-config' to verify configuration, "
                "or re-run without --ai for a bare starter template."
            )
        if ai_content is not None:
            content = ai_content
            print("  ✓ AI-generated domain content validated as valid Turtle.")
        else:
            print("  ⚠ Falling back to bare starter template.")
            content = _build_domain_ttl(
                domain=domain_slug,
                label=resolved_label,
                company_domain=company_domain,
                imports=imports,
                blueprint=blueprint_domain,
                cross_domain=cross_domain_bridges,
            )
    else:
        content = _build_domain_ttl(
            domain=domain_slug,
            label=resolved_label,
            company_domain=company_domain,
            imports=imports,
            blueprint=blueprint_domain,
            cross_domain=cross_domain_bridges,
        )
    content = provenance_comment("scaffold-domain", editable=True) + "\n" + content
    ontology_dst.write_text(content, encoding="utf-8")
    print(f"  ✓ Created ontology-hub/model/ontologies/{domain_slug}.ttl")

    # 8. Register in catalog-v001.xml.
    catalog_dst = hub / "catalog-v001.xml"
    if catalog_dst.is_file():
        ontology_iri = sync_domain_catalog_entry(
            catalog_dst,
            ontology_dst,
            company_domain=company_domain,
        )
        print(f"  ✓ Registered {ontology_iri} in ontology-hub/catalog-v001.xml")
    else:
        ontology_iri = f"https://{company_domain.rstrip('/')}/ont/{domain_slug}"
        print(
            "  ⚠ ontology-hub/catalog-v001.xml not found; skipping catalog registration."
        )

    # 9. Sync owl:imports into _master.ttl.
    master_dst = hub / "model" / "ontologies" / "_master.ttl"
    if master_dst.exists():
        try:
            inserted = sync_master_ontology_import(master_dst, ontology_iri)
        except MasterOntologySyncError as exc:
            print(
                f"  ⚠ Could not sync _master.ttl automatically: {exc}\n"
                f'      Add "owl:imports <{ontology_iri}>" to '
                "ontology-hub/model/ontologies/_master.ttl manually."
            )
        else:
            if inserted:
                print(
                    f"  ✓ Synced owl:imports <{ontology_iri}> into "
                    "ontology-hub/model/ontologies/_master.ttl"
                )
            else:
                print(
                    f"  ⏭  ontology-hub/model/ontologies/_master.ttl already imports "
                    f"{ontology_iri}"
                )
    else:
        print(
            "  ⚠ ontology-hub/model/ontologies/_master.ttl not found; "
            "skipping owl:imports sync."
        )

    print(f"\n✅ Domain '{domain_slug}' scaffolded!")
    print("\nNext steps:")
    print(f"  1. Edit ontology-hub/model/ontologies/{domain_slug}.ttl to define classes and properties")
    print("  2. Run: kairos-ontology validate")
    print("  3. Run: kairos-ontology compile <domain> --check")
