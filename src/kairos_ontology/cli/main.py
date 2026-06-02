# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Main CLI entry point for kairos-ontology toolkit."""

import json
import re
import sys
import click
import shutil
import subprocess
from pathlib import Path
from ..validator import run_validation, run_gdpr_validation
from ..projector import run_projections
from ..catalog_test import test_catalog_resolution
from .. import __version__ as _toolkit_version


def _ensure_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 on Windows.

    The toolkit prints Unicode characters (✓, ✅, 🚀, etc.) which cannot be
    encoded by the default Windows console code pages (cp1252/cp437).  Calling
    this early in the process avoids ``UnicodeEncodeError`` at print time.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


_ensure_utf8_stdio()

# Resolve scaffold data directory bundled with the package
_SCAFFOLD_DIR = Path(__file__).resolve().parent.parent / "scaffold"

# Reference models folder name (at hub root)
_REF_MODELS_PATH = "ontology-reference-models"

# Toolkit GitHub repo for channel resolution
_TOOLKIT_REPO = "Cnext-eu/kairos-ontology-toolkit"


def _resolve_channel(channel: str) -> str | None:
    """Resolve a channel name to a git ref (tag) using GitHub releases.

    Returns the tag name (e.g. 'v2.17.0') or None if resolution fails.
    Channels:
      - "stable"  → latest non-prerelease tag
      - "preview" → latest tag (including pre-releases)
      - anything else → treated as an explicit ref (returned as-is)
    """
    if channel not in ("stable", "preview"):
        return channel  # explicit ref like "v2.16.0" or "main"

    try:
        result = subprocess.run(
            ["gh", "api", f"/repos/{_TOOLKIT_REPO}/releases",
             "--jq", ".[].tag_name"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return None
        tags = [t.strip() for t in result.stdout.strip().splitlines() if t.strip()]
        if not tags:
            return None
        if channel == "preview":
            return tags[0]  # most recent release (may be pre-release)
        # stable: skip pre-release tags
        for tag in tags:
            if not any(label in tag for label in ("-rc.", "-beta.", "-alpha.")):
                return tag
        return tags[0]  # fallback if all are pre-releases
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _tag_to_version(tag: str) -> str:
    """Convert a git tag (e.g. ``v3.9.0-rc.1``) to PEP 440 (``3.9.0rc1``)."""
    import re

    v = tag.lstrip("v")
    # -rc.N → rcN, -beta.N → bN, -alpha.N → aN
    v = re.sub(r"-rc\.?(\d+)", r"rc\1", v)
    v = re.sub(r"-beta\.?(\d+)", r"b\1", v)
    v = re.sub(r"-alpha\.?(\d+)", r"a\1", v)
    return v


def _whl_url(tag: str) -> str:
    """Build the GitHub Releases download URL for the .whl artifact."""
    version = _tag_to_version(tag)
    filename = f"kairos_ontology_toolkit-{version}-py3-none-any.whl"
    return (
        f"https://github.com/{_TOOLKIT_REPO}/releases/download/"
        f"{tag}/{filename}"
    )


def _read_hub_channel() -> str:
    """Read the [tool.kairos] channel from the current directory's pyproject.toml."""
    pyproject = Path.cwd() / "pyproject.toml"
    if not pyproject.is_file():
        return "stable"
    content = pyproject.read_text(encoding="utf-8")
    # Simple TOML parsing for channel value (avoid tomllib dependency)
    match = re.search(r'\[tool\.kairos\].*?channel\s*=\s*"([^"]+)"', content, re.DOTALL)
    return match.group(1) if match else "stable"

# ---------------------------------------------------------------------------
# Managed-file stamping — toolkit-owned files carry a version marker so
# ``kairos-ontology update`` can refresh them without manual diffing.
# ---------------------------------------------------------------------------
_MANAGED_MARKER_RE = re.compile(
    r"<!-- kairos-ontology-toolkit:managed v([\d]+(?:\.[\d]+)*\S*) -->")
_MANAGED_MARKER_TEMPLATE = (
    "<!-- kairos-ontology-toolkit:managed v{version} -->"
)


def _stamp_managed(content: str, version: str) -> str:
    """Insert (or replace) a managed-file version marker.

    For files with YAML front-matter (``---`` … ``---``), the marker is placed
    right after the closing ``---``.  Otherwise it goes on the first line.
    """
    marker_line = _MANAGED_MARKER_TEMPLATE.format(version=version)

    # Replace an existing marker
    if _MANAGED_MARKER_RE.search(content):
        return _MANAGED_MARKER_RE.sub(marker_line, content, count=1)

    # Insert after YAML front-matter if present
    if content.startswith("---"):
        close_idx = content.index("---", 3)
        end_of_line = content.index("\n", close_idx) + 1
        return content[:end_of_line] + marker_line + "\n" + content[end_of_line:]

    return marker_line + "\n" + content


def _get_managed_version(content: str) -> str | None:
    """Extract the toolkit version from a managed-file marker, or *None*."""
    m = _MANAGED_MARKER_RE.search(content)
    return m.group(1) if m else None


def _managed_scaffold_map() -> dict[str, Path]:
    """Return ``{repo_relative_path: scaffold_source_path}`` for managed files."""
    result: dict[str, Path] = {}

    ci = _SCAFFOLD_DIR / "copilot-instructions.md"
    if ci.is_file():
        result[".github/copilot-instructions.md"] = ci

    skills = _SCAFFOLD_DIR / "skills"
    if skills.is_dir():
        for skill_dir in sorted(skills.iterdir()):
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.is_file():
                    result[f".github/skills/{skill_dir.name}/SKILL.md"] = skill_file

    return result


def _copy_managed(src: Path, dst: Path) -> None:
    """Copy a scaffold file to *dst*, stamping the managed-file marker."""
    content = src.read_text(encoding="utf-8")
    content = _stamp_managed(content, _toolkit_version)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(content, encoding="utf-8")


def _check_not_inside_git_repo(parent: Path, name: str) -> None:
    """Raise ClickException if *parent* is deeply inside an existing git repo.

    We allow creating a new repo directly inside a git root (e.g.,
    ``G:\\Git\\new-hub`` when ``G:\\Git`` is a repo) because ``git init``
    in the subdirectory creates an independent nested repo.  We only block
    when *parent* is a subdirectory **below** the git root (e.g., inside
    ``some-repo/src/``), which almost certainly means the user is inside
    another project.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=parent, capture_output=True, text=True,
        )
        if result.returncode == 0:
            git_root = Path(result.stdout.strip()).resolve()
            resolved_parent = parent.resolve()
            # Allow if parent IS the git root (top-level directory)
            if resolved_parent == git_root:
                return
            if resolved_parent.is_relative_to(git_root):
                safe_path = git_root.parent
                raise click.ClickException(
                    f"Cannot create a new repo inside an existing git "
                    f"repository.\n\n"
                    f"  You are in:  {resolved_parent}\n"
                    f"  Git root:    {git_root}\n\n"
                    f"  Fix: cd to the directory that contains your repos,\n"
                    f"  then run the command again.  For example:\n\n"
                    f"    cd {safe_path}\n"
                    f"    kairos-ontology new-repo {name}\n\n"
                    f"  Or use --path to specify the parent directory:\n\n"
                    f"    kairos-ontology new-repo {name} --path {safe_path}"
                )
    except FileNotFoundError:
        pass  # git not installed yet — will fail later with a clearer message


@click.group()
@click.version_option(version=_toolkit_version, package_name="kairos-ontology-toolkit")
def cli():
    """Kairos Ontology Toolkit - Validation and projection tools for OWL/Turtle ontologies."""
    pass


_LIFECYCLE_TABLE = """\
┌─────────────────────────────────────────────────────────────────────────┐
│                         ONTOLOGY HUB LIFECYCLE                          │
├──────────┬──────────────────────────────────────────────────────────────┤
│  PHASE   │  SKILLS                                                      │
├──────────┼──────────────────────────────────────────────────────────────┤
│ Orient   │  kairos-help                                                  │
├──────────┼──────────────────────────────────────────────────────────────┤
│ Setup    │  kairos-setup-init        (create new hub repo)               │
│          │  kairos-setup-config      (folder structure + config)         │
│          │  kairos-setup-migrate     (flat → grouped layout)            │
├──────────┼──────────────────────────────────────────────────────────────┤
│ Design   │  kairos-design-source     (bronze vocabulary)                 │
│          │  kairos-design-domain     (OWL ontology)                      │
│          │  kairos-design-mapping    (SKOS source→domain)               │
│          │  kairos-design-silver     (silver annotations)                │
│          │  kairos-design-gold       (gold annotations)                  │
├──────────┼──────────────────────────────────────────────────────────────┤
│ Execute  │  kairos-execute-project   (generate all projection targets)   │
│          │  kairos-execute-validate  (syntax + SHACL check)              │
│          │  kairos-execute-report    (HTML mapping reports)              │
├──────────┼──────────────────────────────────────────────────────────────┤
│ Diagnose │  kairos-diagnose-status   (completeness check)                │
├──────────┼──────────────────────────────────────────────────────────────┤
│ Package  │  kairos-package-dataplatform (dbt package in downstream repo) │
├──────────┼──────────────────────────────────────────────────────────────┤
│ Toolkit  │  kairos-toolkit-dev       (modify the toolkit)                │
│ (dev)    │  kairos-toolkit-ops       (release, upgrade, versioning)      │
├──────────┼──────────────────────────────────────────────────────────────┤
│ Workflow │  SC-feature-branch        (create branch)                     │
│ (git)    │  SC-merge-pr              (PR + merge)                        │
│          │  SC-document              (Outline wiki)                       │
└──────────┴──────────────────────────────────────────────────────────────┘"""


@cli.command()
def lifecycle():
    """Display the ontology hub lifecycle phases and available Copilot skills."""
    print()
    print(f"  Kairos Ontology Toolkit v{_toolkit_version}")
    print()
    print(_LIFECYCLE_TABLE)
    print()
    print("  Tip: Invoke any skill by name in GitHub Copilot Chat.")
    print("  Run 'kairos-ontology --help' for available CLI commands.")
    print()


# Catalog search order: hub-local catalog first, then shared reference-models.
_CATALOG_CANDIDATES = [
    Path("ontology-hub/catalog-v001.xml"),
    Path("ontology-reference-models/catalog-v001.xml"),
]


def _resolve_catalog(explicit: str | None) -> Path | None:
    """Return the catalog path to use.

    If *explicit* is given (user passed ``--catalog``), use it directly.
    Otherwise, search ``_CATALOG_CANDIDATES`` in order and return the
    first one that exists, or ``None`` if no catalog is found.
    """
    if explicit:
        return Path(explicit)
    for candidate in _CATALOG_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


@cli.command()
@click.option('--ontologies', type=click.Path(exists=True),
              default='ontology-hub/model/ontologies',
              help='Path to ontologies directory')
@click.option('--shapes', type=click.Path(exists=True),
              default='ontology-hub/model/shapes',
              help='Path to SHACL shapes directory')
@click.option('--catalog', type=click.Path(exists=True),
              default=None,
              help='Path to catalog file for resolving imports '
                   '(default: ontology-hub/catalog-v001.xml or '
                   'ontology-reference-models/catalog-v001.xml)')
@click.option('--all', 'validate_all', is_flag=True,
              help='Validate all: syntax + SHACL + consistency')
@click.option('--syntax', is_flag=True, help='Validate syntax only')
@click.option('--shacl', is_flag=True, help='Validate SHACL only')
@click.option('--consistency', is_flag=True, help='Validate consistency only')
@click.option('--gdpr', is_flag=True, help='Scan for PII properties without GDPR satellite protection')
def validate(ontologies, shapes, catalog, validate_all, syntax, shacl, consistency, gdpr):
    """Validate ontologies (syntax, SHACL, consistency, GDPR PII scan)."""
    ontologies_path = Path(ontologies)
    shapes_path = Path(shapes)
    catalog_path = _resolve_catalog(catalog)
    
    # Default to all if nothing specified
    if not any([validate_all, syntax, shacl, consistency, gdpr]):
        validate_all = True
    
    if gdpr or validate_all:
        run_gdpr_validation(
            ontologies_path=ontologies_path,
            catalog_path=catalog_path,
        )
        if gdpr and not any([validate_all, syntax, shacl, consistency]):
            return  # GDPR-only mode

    run_validation(
        ontologies_path=ontologies_path,
        shapes_path=shapes_path,
        catalog_path=catalog_path,
        do_syntax=validate_all or syntax,
        do_shacl=validate_all or shacl,
        do_consistency=validate_all or consistency
    )


@cli.command()
@click.option('--ontologies', type=click.Path(exists=True),
              default='ontology-hub/model/ontologies',
              help='Path to ontologies directory')
@click.option('--catalog', type=click.Path(exists=True),
              default=None,
              help='Path to catalog file for resolving imports '
                   '(default: ontology-hub/catalog-v001.xml or '
                   'ontology-reference-models/catalog-v001.xml)')
@click.option('--output', type=click.Path(),
              default='ontology-hub/output',
              help='Output directory for projections')
@click.option('--target', type=click.Choice(['all', 'dbt', 'neo4j', 'azure-search', 'a2ui', 'prompt', 'silver', 'powerbi', 'report']),
              default='all', help='Projection target')
@click.option('--namespace', type=str, default=None,
              help='Base namespace to project (e.g., http://example.org/ont/). Auto-detects if not provided.')
def project(ontologies, catalog, output, target, namespace):
    """Generate projections from ontologies."""
    ontologies_path = Path(ontologies)
    catalog_path = _resolve_catalog(catalog)
    output_path = Path(output)
    
    run_projections(
        ontologies_path=ontologies_path,
        catalog_path=catalog_path,
        output_path=output_path,
        target=target,
        namespace=namespace
    )


@cli.command(name='catalog-test')
@click.option('--catalog', type=click.Path(exists=True), required=True,
              help='Path to catalog file to test')
@click.option('--ontology', type=click.Path(exists=True),
              help='Optional: test with specific ontology file')
def catalog_test_cmd(catalog, ontology):
    """Test catalog resolution for imports."""
    catalog_path = Path(catalog)
    ontology_path = Path(ontology) if ontology else None
    
    test_catalog_resolution(catalog_path, ontology_path)


@cli.command()
@click.option('--domain', type=str, default=None,
              help='Name of the first domain (e.g., "customer"). Creates a starter .ttl file.')
@click.option('--company-domain', 'company_domain', type=str, required=True,
              help='Company internet domain (e.g., "contoso.com"). '
                   'Used as the namespace base: https://<domain>/ont/')
@click.option('--force', is_flag=True, help='Overwrite existing files')
def init(domain, company_domain, force):
    """Initialize a Kairos ontology hub in the current directory.

    Creates the standard folder structure, installs Copilot skills, and
    optionally scaffolds a starter ontology domain.
    """
    cwd = Path.cwd()
    company_name = company_domain.split(".")[0].replace("-", " ").title()
    print("🚀 Initializing Kairos ontology hub")
    print(f"   Directory: {cwd}")
    print(f"   Company:   {company_name} ({company_domain})\n")

    hub = cwd / "ontology-hub"

    # 1. Create directory structure
    for d in [
        hub / "model" / "ontologies",
        hub / "model" / "shapes",
        hub / "model" / "extensions",
        hub / "model" / "mappings",
        hub / "integration" / "sources",
        hub / "output" / "medallion" / "powerbi",
        hub / "output" / "medallion" / "dbt",
        hub / "output" / "neo4j",
        hub / "output" / "azure-search",
        hub / "output" / "a2ui",
        hub / "output" / "prompt",
        hub / "output" / "report",
        hub / ".sessions-projection",
        hub / ".sessions-design",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    # Place .gitkeep in empty output subdirs so git tracks them
    for target in [
        "medallion/powerbi", "medallion/dbt",
        "neo4j", "azure-search", "a2ui", "prompt", "report",
    ]:
        gitkeep = hub / "output" / target / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()

    # Place .gitkeep in session folders so git tracks them
    for session_folder in [
        ".sessions-projection",
        ".sessions-design",
    ]:
        sk = hub / session_folder / ".gitkeep"
        if not sk.exists():
            sk.touch()

    # 2. Copy README files for each directory
    readme_map = {
        "model/ontologies": "model/ontologies",
        "model/shapes": "model/shapes",
        "model/mappings": "model/mappings",
        "integration/sources": "integration/sources",
    }
    for scaffold_subdir, hub_subdir in readme_map.items():
        readme_src = _SCAFFOLD_DIR / "ontology-hub" / scaffold_subdir / "README.md"
        readme_dst = hub / hub_subdir / "README.md"
        if readme_src.is_file() and (not readme_dst.exists() or force):
            shutil.copy2(readme_src, readme_dst)

    # 2b. Copy source-system-template into integration/sources/
    src_template_src = _SCAFFOLD_DIR / "ontology-hub" / "integration" / "sources" / "source-system-template"
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
                    print(f"  ⏭  .github/ISSUE_TEMPLATE/{tpl_file.name} already exists (use --force)")
                else:
                    shutil.copy2(tpl_file, dst_file)
                    print(f"  ✓ Installed .github/ISSUE_TEMPLATE/{tpl_file.name}")

    # 4c. Copy update-referencemodels.ps1
    refscript_src = _SCAFFOLD_DIR / "update-referencemodels.ps1"
    refscript_dst = cwd / "update-referencemodels.ps1"
    if refscript_src.is_file():
        if refscript_dst.exists() and not force:
            print("  ⏭  update-referencemodels.ps1 already exists (use --force to overwrite)")
        else:
            shutil.copy2(refscript_src, refscript_dst)
            print("  ✓ Installed update-referencemodels.ps1")

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

    # 4e. Generate pyproject.toml (needed for uv sync)
    pyproject_src = _SCAFFOLD_DIR / "pyproject.toml.template"
    pyproject_dst = cwd / "pyproject.toml"
    if pyproject_src.is_file():
        if pyproject_dst.exists() and not force:
            print("  ⏭  pyproject.toml already exists (use --force to overwrite)")
        else:
            ref = _resolve_channel("stable") or "v3.8.0"
            version = _tag_to_version(ref)
            repo_name = cwd.name
            content = pyproject_src.read_text(encoding="utf-8")
            content = (content
                       .replace("{repo_name}", repo_name)
                       .replace("{description}", repo_name)
                       .replace("{toolkit_ref}", ref)
                       .replace("{toolkit_version}", version))
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
            content = (content
                       .replace("{company_name}", company_name)
                       .replace("{company_domain}", company_domain))
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
            content = (content
                       .replace("{company_name}", company_name)
                       .replace("{company_domain}", company_domain))
            master_dst.write_text(content, encoding="utf-8")
            print("  ✓ Created ontology-hub/model/ontologies/_master.ttl")

    # 7b. Generate local catalog (URI → local file mapping)
    catalog_src = _SCAFFOLD_DIR / "ontology-hub" / "catalog-v001.xml.template"
    catalog_dst = hub / "catalog-v001.xml"
    if catalog_src.is_file():
        if catalog_dst.exists() and not force:
            print("  ⏭  ontology-hub/catalog-v001.xml already exists (use --force)")
        else:
            content = catalog_src.read_text(encoding="utf-8")
            content = (content
                       .replace("{company_name}", company_name)
                       .replace("{company_domain}", company_domain))
            catalog_dst.write_text(content, encoding="utf-8")
            print("  ✓ Created ontology-hub/catalog-v001.xml")

    # 8. Scaffold a starter domain ontology
    if domain:
        template_src = _SCAFFOLD_DIR / "ontology-hub" / "model" / "ontologies" / "starter.ttl.template"
        ontology_dst = hub / "model" / "ontologies" / f"{domain}.ttl"
        if ontology_dst.exists() and not force:
            print(f"  ⏭  ontology-hub/model/ontologies/{domain}.ttl already exists (use --force to overwrite)")
        elif template_src.is_file():
            label = domain.replace("-", " ").replace("_", " ").title()
            content = template_src.read_text(encoding="utf-8")
            content = (content
                       .replace("{domain}", domain)
                       .replace("{label}", label)
                       .replace("{company_domain}", company_domain))
            ontology_dst.write_text(content, encoding="utf-8")
            print(f"  ✓ Created ontology-hub/model/ontologies/{domain}.ttl")

    # 9. Run smartcoding update if the script exists
    _run_smartcoding_update(cwd)

    print("\n✅ Ontology hub initialized!")
    print("\nNext steps:")
    print("  1. Edit ontology-hub/model/ontologies/*.ttl to define your domain classes and properties")
    print("  2. Run: kairos-ontology validate")
    print("  3. Run: kairos-ontology project --target prompt")


# ---------------------------------------------------------------------------
# update — refresh toolkit-managed files to the installed version
# ---------------------------------------------------------------------------

@cli.command(name='import-tmdl')
@click.argument('source', type=click.Path(exists=True))
@click.option('--output', '-o', type=click.Path(), default='integration/sources/powerbi',
              help='Output directory (default: integration/sources/powerbi/)')
def import_tmdl(source, output):
    """Import and inventory TMDL/PBIP files for ontology modeling.

    SOURCE is a path to a PBIP ZIP archive, a SemanticModel folder, or a
    standalone .tmdl file. The command parses TMDL content and generates:

    \b
    - An Engineering Pack (markdown) with table/column/measure inventory
    - A Concept Mapping template (YAML) for reference model alignment
    """
    from ..import_tmdl import run_import_tmdl

    source_path = Path(source)
    output_path = Path(output)

    click.echo(f"📦 Importing TMDL from: {source_path}")
    generated = run_import_tmdl(source_path, output_path)

    if generated:
        click.echo(f"\n✅ Generated {len(generated)} file(s):")
        for f in generated:
            click.echo(f"   {f}")
    else:
        click.echo("\n⚠️  No TMDL content found. Check input path.", err=True)
        raise SystemExit(1)


@cli.command(name='import-source')
@click.option('--from', 'from_path', type=click.Path(exists=True), required=True,
              help='Path to source-schema YAML file.')
@click.option('--system', 'system_name', default=None,
              help='Override the system name (default: from YAML).')
@click.option('--output', '-o', type=click.Path(), default=None,
              help='Output directory (default: integration/sources/{system}/).')
@click.option('--dry-run', is_flag=True,
              help='Show changes without writing files.')
def import_source(from_path, system_name, output, dry_run):
    """Import source schema YAML and generate/refresh bronze vocabulary TTL.

    Reads a standardized source-schema YAML file (produced by the
    extract_source_schema dbt macro or manually) and generates or updates
    the corresponding kairos-bronze vocabulary TTL.

    \b
    Examples:
      kairos-ontology import-source --from extracted/adminpulse-schema.yaml
      kairos-ontology import-source --from schema.yaml --system myapp --dry-run
    """
    from ..import_source import run_import_source, ChangeReport

    yaml_path = Path(from_path)
    output_dir = Path(output) if output else None

    click.echo(f"📋 Importing source schema from: {yaml_path}")

    try:
        result_path, report = run_import_source(
            yaml_path=yaml_path,
            system_name=system_name,
            output_dir=output_dir,
            dry_run=dry_run,
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
        click.echo(f"\n✅ Written: {result_path}")


@cli.command()
@click.option("--check", is_flag=True,
              help="Report outdated files without modifying anything (exit 1 on drift).")
@click.option("--upgrade", is_flag=True,
              help="Upgrade the toolkit dependency to the channel's latest version.")
def update(check, upgrade):
    """Update toolkit-managed files to the installed toolkit version.

    Scans .github/ for files stamped by kairos-ontology-toolkit and refreshes
    them from the currently installed package.  Missing managed files (e.g.,
    newly added skills) are created automatically.  Skills that have the
    managed marker but are no longer in the current scaffold (renamed or
    removed) are deleted.  Use --check to preview what would change without
    writing anything.

    Use --upgrade to upgrade the toolkit dependency based on the channel
    configured in [tool.kairos] of pyproject.toml (stable or preview).

    \b
    Exit codes (with --check):
      0  All managed files are up to date
      1  One or more files are outdated, missing, or stale

    \b
    Managed files (do not edit manually):
      .github/copilot-instructions.md
      .github/skills/*/SKILL.md
    """
    # --- Upgrade toolkit dependency via uv ------------------------------------
    if upgrade:
        channel = _read_hub_channel()
        ref = _resolve_channel(channel)
        if ref is None:
            print(f"⚠  Could not resolve channel '{channel}' — is 'gh' installed and "
                  f"authenticated?")
            raise SystemExit(1)
        print(f"📦 Channel: {channel} → {ref}")

        # Update the pyproject.toml dependency pin first
        pyproject = Path.cwd() / "pyproject.toml"
        version = _tag_to_version(ref)
        if not pyproject.is_file():
            # Auto-generate pyproject.toml from scaffold template for legacy hubs
            template = _SCAFFOLD_DIR / "pyproject.toml.template"
            if template.is_file():
                repo_name = Path.cwd().name
                content = template.read_text(encoding="utf-8")
                content = content.replace("{repo_name}", repo_name)
                content = content.replace("{description}", repo_name)
                content = content.replace("{toolkit_ref}", ref)
                content = content.replace("{toolkit_version}", version)
                pyproject.write_text(content, encoding="utf-8")
                print(f"   ✓ Created pyproject.toml (was missing)")
            else:
                print("❌ pyproject.toml not found and cannot generate it")
                raise SystemExit(1)
        if pyproject.is_file():
            content = pyproject.read_text(encoding="utf-8")
            new_dep = (
                f"kairos-ontology-toolkit @ {_whl_url(ref)}"
            )
            # Match both old git+https format and new .whl URL format
            new_content = re.sub(
                r'kairos-ontology-toolkit\s*@\s*(?:'
                r'git\+https://github\.com/Cnext-eu/kairos-ontology-toolkit\.git@[^\s"]*'
                r'|https://github\.com/Cnext-eu/kairos-ontology-toolkit/releases/download/[^\s"]*'
                r')',
                new_dep,
                content,
            )
            if new_content != content:
                pyproject.write_text(new_content, encoding="utf-8")
                print(f"   ✓ Updated pyproject.toml pin to {ref} (.whl)")

        # Lock and sync with uv
        print(f"   Syncing environment with uv ...")
        result = subprocess.run(["uv", "lock"], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ uv lock failed:\n{result.stderr}")
            raise SystemExit(1)
        result = subprocess.run(["uv", "sync"], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ uv sync failed:\n{result.stderr}")
            raise SystemExit(1)
        print(f"   ✓ Upgraded to {ref}")
        return
    managed_map = _managed_scaffold_map()
    repo_root = Path.cwd()

    updated: list[tuple[str, str]] = []
    outdated: list[tuple[str, str]] = []
    missing: list[str] = []
    created: list[str] = []
    current: list[str] = []

    for rel_path, scaffold_src in managed_map.items():
        local_file = repo_root / rel_path
        if not local_file.is_file():
            if check:
                missing.append(rel_path)
            else:
                _copy_managed(scaffold_src, local_file)
                created.append(rel_path)
            continue

        local_content = local_file.read_text(encoding="utf-8")
        local_ver = _get_managed_version(local_content)

        if local_ver == _toolkit_version:
            current.append(rel_path)
            continue

        scaffold_content = scaffold_src.read_text(encoding="utf-8")
        new_content = _stamp_managed(scaffold_content, _toolkit_version)

        if check:
            outdated.append((rel_path, local_ver or "unmanaged"))
        else:
            local_file.write_text(new_content, encoding="utf-8")
            updated.append((rel_path, local_ver or "unmanaged"))

    # --- Stale managed-skill cleanup ----------------------------------------
    stale: list[str] = []
    removed: list[str] = []
    skills_dir = repo_root / ".github" / "skills"
    scaffold_skills_dir = _SCAFFOLD_DIR / "skills"
    if skills_dir.is_dir() and scaffold_skills_dir.is_dir():
        scaffold_skill_names = {
            d.name for d in scaffold_skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").is_file()
        }
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.is_file():
                continue
            if skill_dir.name in scaffold_skill_names:
                continue
            content = skill_file.read_text(encoding="utf-8")
            if not _MANAGED_MARKER_RE.search(content):
                continue
            if check:
                stale.append(skill_dir.name)
            else:
                shutil.rmtree(skill_dir)
                removed.append(skill_dir.name)

    # --- Report -------------------------------------------------------------
    if check:
        if outdated:
            print(f"⚠  {len(outdated)} file(s) need updating:")
            for path, ver in outdated:
                print(f"   {path}  ({ver} → {_toolkit_version})")
        if missing:
            print(f"⚠  {len(missing)} managed file(s) missing:")
            for p in missing:
                print(f"   {p}")
        if stale:
            print(f"⚠  {len(stale)} stale managed skill(s) to remove:")
            for name in stale:
                print(f"   .github/skills/{name}/")
        if not outdated and not missing and not stale:
            print(f"✅ All managed files are up to date (v{_toolkit_version})")
        else:
            raise SystemExit(1)
    else:
        if created:
            print(f"✅ Created {len(created)} new file(s) (v{_toolkit_version}):")
            for path in created:
                print(f"   {path}")
        if updated:
            print(f"✅ Updated {len(updated)} file(s) to v{_toolkit_version}:")
            for path, ver in updated:
                print(f"   {path}  ({ver} → {_toolkit_version})")
        if removed:
            print(f"🗑️  Removed {len(removed)} stale managed skill(s):")
            for name in removed:
                print(f"   .github/skills/{name}/")
        if not updated and not created and not removed:
            print(f"✅ All managed files are up to date (v{_toolkit_version})")

    # --- Ensure package.json exists (Mermaid CLI for SVG export) -------------
    if not check:
        pkg_json = repo_root / "package.json"
        pkg_src = _SCAFFOLD_DIR / "ontology-hub" / "package.json.template"
        if not pkg_json.is_file() and pkg_src.is_file():
            shutil.copy2(pkg_src, pkg_json)
            print("  ✓ Created package.json (run 'npm install' for Mermaid CLI SVG export)")

    # --- Ensure .devcontainer exists (VS Code Dev Container) -----------------
    if not check:
        devcontainer_dst = repo_root / ".devcontainer"
        devcontainer_src = _SCAFFOLD_DIR / ".devcontainer"
        if not devcontainer_dst.exists() and devcontainer_src.is_dir():
            shutil.copytree(devcontainer_src, devcontainer_dst)
            print("  ✓ Created .devcontainer/ (VS Code Dev Container with Node.js)")


# ---------------------------------------------------------------------------
# migrate — move files from old flat layout to model/integration/output
# ---------------------------------------------------------------------------

# Old (flat) → new (grouped) directory mapping for migration.
_MIGRATE_DIR_MAP = {
    # model
    "ontologies": "model/ontologies",
    "shapes": "model/shapes",
    # integration
    "sources": "integration/sources",
    "mappings": "model/mappings",
    "bronze": "integration/sources",
}

# Old output subdirs that move under output/medallion/
_MIGRATE_OUTPUT_MAP = {
    "silver": "medallion/dbt",
    "dbt": "medallion/dbt",
}


def _is_old_layout(hub: Path) -> bool:
    """Return True if *hub* still has the old flat directory layout."""
    return (hub / "ontologies").is_dir() and not (hub / "model").is_dir()


@cli.command()
@click.option("--check", is_flag=True,
              help="Preview what would change without modifying anything.")
@click.option("--hub", "hub_path", type=click.Path(exists=True),
              default="ontology-hub",
              help="Path to the ontology-hub directory (default: ontology-hub).")
def migrate(check, hub_path):
    """Migrate an existing ontology hub from the flat layout to the grouped layout.

    Moves files into the new model/ + integration/ + output/medallion/ structure
    and cleans up empty old directories.

    \b
    After migrating, run:
      kairos-ontology update      # refresh managed files (skills, instructions)
      kairos-ontology validate    # verify ontologies still parse correctly
      kairos-ontology project     # regenerate projections with new paths
    """
    hub = Path(hub_path)

    if not hub.is_dir():
        raise click.ClickException(f"Hub directory not found: {hub}")

    # Guard: already migrated?
    if (hub / "model").is_dir() and not (hub / "ontologies").is_dir():
        print("✅ Hub is already using the new layout — nothing to migrate.")
        return

    if not _is_old_layout(hub):
        raise click.ClickException(
            f"Cannot detect old flat layout in {hub}. "
            f"Expected ontology-hub/ontologies/ to exist."
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
        hub / "integration" / "sources",
        hub / "output" / "medallion" / "powerbi",
        hub / "output" / "medallion" / "dbt",
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
                    if (
                        check
                        and old_name == "ontologies"
                        and item.name.endswith("-silver-ext.ttl")
                    ):
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

    # --- 4. Move old output/silver/ and output/dbt/ to output/medallion/ -----
    output_dir = hub / "output"
    if output_dir.is_dir():
        for old_target, new_rel in _MIGRATE_OUTPUT_MAP.items():
            old_target_dir = output_dir / old_target
            new_target_dir = output_dir / new_rel
            if old_target_dir.is_dir():
                items = list(old_target_dir.iterdir())
                if items:
                    for item in items:
                        dst = new_target_dir / item.name
                        if check:
                            print(f"  MOVE  output/{old_target}/{item.name}  →  output/{new_rel}/{item.name}")
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
            print("  DELETE  application-models/  (ERDs now in output/medallion/dbt/docs/diagrams/)")
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
                print(f"  ⚠  {old_name}/ still has files — not removed: "
                      f"{[f.name for f in remaining]}")

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
        print("  3. kairos-ontology project    # regenerate projections")
        print("  4. git add -A && git commit -m 'refactor: migrate hub to new layout'")



# ---------------------------------------------------------------------------
# Repo naming helper
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    """Turn a human name into a GitHub-friendly repo slug.

    Convention:  <client>-ontology-hub
    Examples:    contoso-ontology-hub, acme-logistics-ontology-hub
    """
    import re
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    if not slug.endswith("-ontology-hub"):
        slug = f"{slug}-ontology-hub"
    return slug


@cli.command(name="new-repo")
@click.argument("name")
@click.option("--description", "desc", type=str, default=None,
              help="Short repo description for README / pyproject.")
@click.option("--path", "dest", type=click.Path(), default=None,
              help="Parent directory to create the repo in (default: current dir).")
@click.option("--org", type=str, default="Cnext-eu",
              help="GitHub organisation for the remote repo (default: Cnext-eu).")
@click.option("--private/--public", "is_private", default=True,
              help="Create a private (default) or public GitHub repo.")
@click.option("--ref-models-version", "ref_models_version", type=str, default=None,
              help="Git ref (tag/branch) for reference models (default: latest).")
@click.option("--template", "template", type=str, default="kairos-app-template",
              help="GitHub repo template to use (default: kairos-app-template). "
                   "Pass empty string to skip.")
@click.option("--company-domain", "company_domain", type=str, default=None,
              help="Company internet domain (e.g., \"contoso.com\"). "
                   "Defaults to <name>.com if not provided.")
@click.option("--skip-protection", "skip_protection", is_flag=True, default=False,
              help="Skip configuring branch protection on main (useful if no admin rights).")
def new_repo(name, desc, dest, org, is_private, ref_models_version, template,
             company_domain, skip_protection):
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
      kairos-ontology init --domain customer
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
                base = base[:-len(suffix)]
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

    # When using a template, create the remote first and clone it.
    # Otherwise, create the local directory from scratch.
    use_template = bool(template)
    if use_template:
        _create_repo_from_template(repo_dir, repo_slug, org, template,
                                   description, is_private)
    else:
        repo_dir.mkdir(parents=True)

    # --- Scaffold the hub structure (reuse init logic) -----------------------
    hub = repo_dir / "ontology-hub"

    for d in [
        hub / "model" / "ontologies",
        hub / "model" / "shapes",
        hub / "model" / "extensions",
        hub / "model" / "mappings",
        hub / "integration" / "sources",
        hub / "output" / "medallion" / "powerbi",
        hub / "output" / "medallion" / "dbt",
        hub / "output" / "neo4j",
        hub / "output" / "azure-search",
        hub / "output" / "a2ui",
        hub / "output" / "prompt",
        hub / "output" / "report",
        hub / ".sessions-projection",
        hub / ".sessions-design",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    # Place .gitkeep in output subdirs so git tracks them
    for target in [
        "medallion/powerbi", "medallion/dbt",
        "neo4j", "azure-search", "a2ui", "prompt", "report",
    ]:
        gitkeep = hub / "output" / target / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()

    # Place .gitkeep in session folders so git tracks them
    for session_folder in [
        ".sessions-projection",
        ".sessions-design",
    ]:
        sk = hub / session_folder / ".gitkeep"
        if not sk.exists():
            sk.touch()

    # README files
    readme_map = {
        "model/ontologies": "model/ontologies",
        "model/shapes": "model/shapes",
        "model/mappings": "model/mappings",
        "integration/sources": "integration/sources",
    }
    for scaffold_subdir, hub_subdir in readme_map.items():
        src = _SCAFFOLD_DIR / "ontology-hub" / scaffold_subdir / "README.md"
        dst = hub / hub_subdir / "README.md"
        if src.is_file():
            shutil.copy2(src, dst)

    # Source-system-template into integration/sources/
    src_template_src = _SCAFFOLD_DIR / "ontology-hub" / "integration" / "sources" / "source-system-template"
    src_template_dst = hub / "integration" / "sources" / "source-system-template"
    if src_template_src.is_dir() and not src_template_dst.exists():
        shutil.copytree(src_template_src, src_template_dst)

    # Hub-level README with company context
    hub_readme_src = _SCAFFOLD_DIR / "ontology-hub" / "README.md.template"
    if hub_readme_src.is_file():
        content = hub_readme_src.read_text(encoding="utf-8")
        content = (content
                   .replace("{company_name}", company_name)
                   .replace("{company_domain}", company_domain_val))
        (hub / "README.md").write_text(content, encoding="utf-8")
        print("  ✓ ontology-hub/README.md (company context)")

    # Master ontology (imports all domains)
    master_src = _SCAFFOLD_DIR / "ontology-hub" / "model" / "ontologies" / "master.ttl.template"
    if master_src.is_file():
        content = master_src.read_text(encoding="utf-8")
        content = (content
                   .replace("{company_name}", company_name)
                   .replace("{company_domain}", company_domain_val))
        (hub / "model" / "ontologies" / "_master.ttl").write_text(content, encoding="utf-8")
        print("  ✓ ontology-hub/model/ontologies/_master.ttl")

    # Local catalog (URI → local file mapping)
    catalog_src = _SCAFFOLD_DIR / "ontology-hub" / "catalog-v001.xml.template"
    if catalog_src.is_file():
        content = catalog_src.read_text(encoding="utf-8")
        content = (content
                   .replace("{company_name}", company_name)
                   .replace("{company_domain}", company_domain_val))
        (hub / "catalog-v001.xml").write_text(content, encoding="utf-8")
        print("  ✓ ontology-hub/catalog-v001.xml")

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
        content = (content
                   .replace("{repo_name}", repo_slug)
                   .replace("{description}", description)
                   .replace("{toolkit_version}", _toolkit_version)
                   .replace("{toolkit_ref}", f"v{_toolkit_version}"))
        (repo_dir / "pyproject.toml").write_text(content, encoding="utf-8")
        print("  ✓ pyproject.toml")

    # .gitignore
    gitignore_src = _SCAFFOLD_DIR / "gitignore.template"
    if gitignore_src.is_file():
        shutil.copy2(gitignore_src, repo_dir / ".gitignore")
        print("  ✓ .gitignore")

    # README.md
    readme_src = _SCAFFOLD_DIR / "README.md.template"
    if readme_src.is_file():
        content = readme_src.read_text(encoding="utf-8")
        content = content.replace("{repo_name}", repo_slug).replace("{description}", description)
        (repo_dir / "README.md").write_text(content, encoding="utf-8")
        print("  ✓ README.md")

    # update-referencemodels.ps1
    refscript_src = _SCAFFOLD_DIR / "update-referencemodels.ps1"
    if refscript_src.is_file():
        shutil.copy2(refscript_src, repo_dir / "update-referencemodels.ps1")
        print("  ✓ update-referencemodels.ps1")

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
        if not use_template:
            subprocess.run(
                ["git", "init", "-b", "main"],
                cwd=repo_dir, capture_output=True, check=True,
            )
        subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial ontology hub scaffold"],
            cwd=repo_dir, capture_output=True, check=True,
        )
        print("  ✓ git repo initialised with initial commit")
        if use_template:
            subprocess.run(
                ["git", "push"],
                cwd=repo_dir, capture_output=True, check=True,
            )
            print("  ✓ Pushed scaffold to remote")
    except FileNotFoundError:
        raise click.ClickException(
            "git not found — install git before using new-repo"
        )
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(
            f"git command failed: {exc.stderr.decode().strip()}"
        )

    # --- GitHub repo creation (non-template flow) ----------------------------
    if not use_template:
        _create_github_repo(repo_dir, repo_slug, org, description, is_private)

    # --- Run smartcoding update if template provided the script ---------------
    _run_smartcoding_update(repo_dir)

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
    print("  kairos-ontology init --domain <your-domain>")


def _create_repo_from_template(
    repo_dir: Path, repo_slug: str, org: str,
    template: str, description: str, is_private: bool,
):
    """Create a GitHub repo from a template, then clone it to *repo_dir*."""
    visibility = "--private" if is_private else "--public"
    full_name = f"{org}/{repo_slug}"
    template_ref = template if "/" in template else f"{org}/{template}"

    try:
        subprocess.run(["gh", "--version"], capture_output=True, check=True)
    except FileNotFoundError:
        raise click.ClickException(
            "gh CLI is required for --template. "
            "Install from https://cli.github.com"
        )

    # --clone tells gh to clone the new repo into the current directory
    # after creating it on GitHub from the template.
    try:
        subprocess.run(
            ["gh", "repo", "create", full_name,
             "--template", template_ref,
             visibility,
             "--description", description,
             "--clone"],
            cwd=repo_dir.parent, capture_output=True, check=True,
        )
        print(f"  ✓ GitHub repo created from template {template_ref}")
        print(f"  ✓ Cloned {full_name} to {repo_dir.name}")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode().strip() if exc.stderr else str(exc)
        raise click.ClickException(
            f"Failed to create repo from template: {stderr}"
        )


_SMARTCODING_SCRIPT = "update-smartcoding-latest.ps1"


def _run_smartcoding_update(repo_dir: Path):
    """Run update-smartcoding-latest.ps1 if it exists in *repo_dir*."""
    script = repo_dir / _SMARTCODING_SCRIPT
    if not script.is_file():
        return

    print(f"  ▶ Running {_SMARTCODING_SCRIPT} …")
    try:
        subprocess.run(
            ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(script), "-SkipSelfUpdateCheck"],
            cwd=repo_dir, check=True,
        )
        print("  ✓ SmartCoding updated to latest")
    except FileNotFoundError:
        print(f"  ⚠  pwsh not found — run {_SMARTCODING_SCRIPT} manually")
    except subprocess.CalledProcessError:
        print(f"  ⚠  {_SMARTCODING_SCRIPT} failed — run it manually")


# ---------------------------------------------------------------------------
# update-refmodels — fetch reference models from upstream repo
# ---------------------------------------------------------------------------

_REFMODELS_REMOTE = "https://github.com/Cnext-eu/kairos-ontology-referencemodels.git"
_REFMODELS_REMOTE_DIR = "ontology-reference-models"


def _detect_refmodels_dest() -> Path:
    """Auto-detect the reference-models destination directory.

    Walks up from CWD looking for a hub structure with ontology-reference-models/.
    Falls back to ontology-reference-models/ relative to CWD.
    """
    cwd = Path.cwd()

    # Check if we're inside an ontology-hub directory structure
    for parent in [cwd, *cwd.parents]:
        candidate = parent / "ontology-reference-models"
        if candidate.exists():
            return candidate
        # Also check ontology-hub subdirectory
        candidate2 = parent / "ontology-hub" / "ontology-reference-models"
        if candidate2.exists():
            return candidate2

    # Default: assume we're at hub root
    default = cwd / "ontology-reference-models"
    return default


@cli.command(name="update-refmodels")
@click.option("--ref", "git_ref", type=str, default="main",
              help="Branch, tag, or SHA to fetch (default: main).")
@click.option("--dest", "dest_path", type=click.Path(), default=None,
              help="Destination path for reference models "
                   "(default: auto-detect ontology-reference-models/).")
def update_refmodels(git_ref, dest_path):
    """Fetch reference models from the upstream repository.

    Performs a sparse shallow clone of the kairos-ontology-referencemodels repo,
    extracts the ontology-reference-models/ subfolder, and replaces the local
    reference-models directory.

    \b
    Examples:
        kairos-ontology update-refmodels
        kairos-ontology update-refmodels --ref v1.2.1
        kairos-ontology update-refmodels --dest path/to/reference-models
    """
    import tempfile

    dest = Path(dest_path) if dest_path else _detect_refmodels_dest()

    # Verify git is available
    try:
        subprocess.run(
            ["git", "--version"], capture_output=True, check=True,
        )
    except FileNotFoundError:
        raise click.ClickException(
            "git is not installed or not on PATH. "
            "Install git and try again."
        )

    click.echo(f"  ▶ Fetching ref '{git_ref}' from upstream reference models…")

    tmp_dir = Path(tempfile.mkdtemp(prefix="kairos-refmodels-"))

    try:
        # Sparse shallow clone
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none",
             "--sparse", "--branch", git_ref,
             _REFMODELS_REMOTE, str(tmp_dir)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise click.ClickException(
                f"git clone failed (ref '{git_ref}'):\n{result.stderr.strip()}"
            )

        # Set sparse-checkout to only the reference models folder
        result = subprocess.run(
            ["git", "-C", str(tmp_dir), "sparse-checkout", "set", _REFMODELS_REMOTE_DIR],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise click.ClickException(
                f"git sparse-checkout failed:\n{result.stderr.strip()}"
            )

        src = tmp_dir / _REFMODELS_REMOTE_DIR
        if not src.exists():
            raise click.ClickException(
                f"Expected folder '{_REFMODELS_REMOTE_DIR}' not found in cloned repo. "
                f"Check that the ref '{git_ref}' contains this folder."
            )

        # Get commit SHA for reporting
        sha_result = subprocess.run(
            ["git", "-C", str(tmp_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        )
        sha = sha_result.stdout.strip() if sha_result.returncode == 0 else "unknown"

        # Replace destination with fetched content
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)

        # Report results
        click.echo(f"  ✓ Reference models updated: {dest}")
        click.echo(f"    Ref    : {git_ref}")
        click.echo(f"    Commit : {sha[:12]}")

        # Check for VERSION file
        version_file = dest / "VERSION"
        if version_file.exists():
            version = version_file.read_text().strip()
            click.echo(f"    Version: {version}")

    finally:
        # Clean up temp directory
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

def _run_reference_models_update(repo_dir: Path, version: str | None = None):
    """Populate ontology-reference-models/ via sparse clone (no submodule).

    Performs the same sparse-clone + copy logic as the update-refmodels CLI
    command, then commits the result.
    """
    import tempfile

    git_ref = version or "main"
    dest = repo_dir / _REF_MODELS_PATH

    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
    except FileNotFoundError:
        print("  ⚠  git not found — skipping reference models update")
        return

    print(f"  ▶ Fetching reference models (ref '{git_ref}')…")
    tmp_dir = Path(tempfile.mkdtemp(prefix="kairos-refmodels-"))

    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none",
             "--sparse", "--branch", git_ref,
             _REFMODELS_REMOTE, str(tmp_dir)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  ⚠  git clone failed: {result.stderr.strip()}")
            return

        subprocess.run(
            ["git", "-C", str(tmp_dir), "sparse-checkout", "set", _REFMODELS_REMOTE_DIR],
            capture_output=True, text=True, check=True,
        )

        src = tmp_dir / _REFMODELS_REMOTE_DIR
        if not src.exists():
            print(f"  ⚠  Folder '{_REFMODELS_REMOTE_DIR}' not found in ref '{git_ref}'")
            return

        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)

        # Commit the populated reference-models content
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir, capture_output=True, text=True,
        )
        if result.stdout.strip():
            subprocess.run(["git", "add", _REF_MODELS_PATH], cwd=repo_dir,
                           capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "chore: populate ontology-reference-models"],
                cwd=repo_dir, capture_output=True, check=True,
            )
            subprocess.run(["git", "push"], cwd=repo_dir, capture_output=True, check=True)
            print("  ✓ Reference models populated and committed")
        else:
            print("  ✓ Reference models already up to date")
    except subprocess.CalledProcessError as exc:
        print("  ⚠  Reference models update failed — run 'kairos-ontology update-refmodels' manually")
        if hasattr(exc, "stderr") and exc.stderr:
            print(f"       {exc.stderr.decode().strip() if isinstance(exc.stderr, bytes) else exc.stderr}")
    finally:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)



def _configure_branch_protection(repo_dir: Path, full_name: str):
    """Configure branch protection on main after GitHub repo creation.

    Uses ``gh api`` to:
    1. Enable delete_branch_on_merge (auto-cleanup after PR merge).
    2. Create branch protection on main with PR requirements.
    3. Verify protection is active.

    Non-fatal: prints warnings if protection cannot be applied (e.g., free plan).
    """
    owner, repo = full_name.split("/", 1)

    # 1. Enable delete_branch_on_merge
    try:
        subprocess.run(
            ["gh", "api", "--method", "PATCH", f"/repos/{full_name}",
             "-f", "delete_branch_on_merge=true"],
            cwd=repo_dir, capture_output=True, check=True,
        )
        print("  ✓ Enabled delete_branch_on_merge")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode().strip() if exc.stderr else str(exc)
        print(f"  ⚠ Could not enable delete_branch_on_merge: {stderr}")

    # 2. Create branch protection on main
    protection_payload = json.dumps({
        "required_status_checks": {
            "strict": True,
            "contexts": [],
        },
        "enforce_admins": False,
        "required_pull_request_reviews": {
            "required_approving_review_count": 1,
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": False,
        },
        "restrictions": None,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "required_linear_history": False,
        "required_conversation_resolution": False,
    })

    try:
        subprocess.run(
            ["gh", "api", "--method", "PUT",
             f"/repos/{full_name}/branches/main/protection",
             "--input", "-"],
            input=protection_payload.encode(),
            cwd=repo_dir, capture_output=True, check=True,
        )
        print("  ✓ Branch protection enabled on main:")
        print("      • Require PR with 1 reviewer")
        print("      • Dismiss stale reviews on new commits")
        print("      • Require branch up-to-date before merge")
        print("      • Block force push & branch deletion")
        print("      • Admin bypass allowed for emergencies")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode().strip() if exc.stderr else str(exc)
        print(f"  ⚠ Could not set branch protection on main: {stderr}")
        print("    (This may require a GitHub Pro/Team/Enterprise plan)")
        return

    # 3. Verify protection is active
    try:
        result = subprocess.run(
            ["gh", "api", f"/repos/{full_name}/branches/main/protection"],
            cwd=repo_dir, capture_output=True, check=True,
        )
        raw = result.stdout
        text = raw.decode() if isinstance(raw, bytes) else str(raw)
        protection = json.loads(text)
        if protection.get("required_pull_request_reviews"):
            print("  ✓ Protection verified: main branch is protected")
        else:
            print("  ⚠ Protection set but could not verify PR requirement")
    except (subprocess.CalledProcessError, json.JSONDecodeError, TypeError,
            UnicodeDecodeError, AttributeError):
        print("  ⚠ Could not verify branch protection (may still be active)")


def _create_github_repo(repo_dir: Path, repo_slug: str, org: str,
                         description: str, is_private: bool):
    """Create a GitHub remote repo via `gh` CLI and push the initial commit."""
    visibility = "--private" if is_private else "--public"
    full_name = f"{org}/{repo_slug}"

    # Check gh is available — hard-fail, repos must be on GitHub
    try:
        subprocess.run(["gh", "--version"], capture_output=True, check=True)
    except FileNotFoundError:
        raise click.ClickException(
            "gh CLI is required to create the GitHub repository. "
            "Install from https://cli.github.com and run `gh auth login`."
        )

    # Create the remote repo — hard-fail so repos are never local-only
    try:
        subprocess.run(
            ["gh", "repo", "create", full_name,
             visibility,
             "--description", description,
             "--source", ".",
             "--push"],
            cwd=repo_dir, capture_output=True, check=True,
        )
        print(f"  ✓ GitHub repo created: {full_name}")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode().strip()
        raise click.ClickException(
            f"Failed to create GitHub repo {full_name}: {stderr}\n"
            f"  Fix the issue and retry, or create manually:\n"
            f"    cd {repo_dir}\n"
            f"    gh repo create {full_name} {visibility} --source . --push"
        )


if __name__ == '__main__':
    cli()


# --------------------------------------------------------------------------- #
# init-dataplatform — scaffold a downstream dataplatform repo from a hub
# --------------------------------------------------------------------------- #

_DATAPLATFORM_SCAFFOLD = _SCAFFOLD_DIR / "dataplatform"


def _detect_hub_context() -> dict:
    """Detect ontology-hub context from the current working directory.

    Returns a dict with hub_root, repo_url, org, repo_name, version,
    and source_systems (list of system names found under integration/sources/).
    """
    cwd = Path.cwd()
    hub_root = None
    for candidate in [cwd / "ontology-hub", cwd]:
        if (candidate / "model" / "ontologies").is_dir():
            hub_root = candidate
            break

    if not hub_root:
        raise click.ClickException(
            "Could not detect an ontology-hub in the current directory.\n"
            "Run this command from the root of a hub repository (containing "
            "ontology-hub/model/ontologies/)."
        )

    # Detect git remote URL
    repo_url = ""
    org = ""
    repo_name = ""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10,
            cwd=hub_root.parent if hub_root.name == "ontology-hub" else hub_root,
        )
        if result.returncode == 0:
            repo_url = result.stdout.strip()
            # Parse org/repo from URL (https or ssh)
            import re as _re
            m = _re.search(r'[/:]([^/]+)/([^/]+?)(?:\.git)?$', repo_url)
            if m:
                org = m.group(1)
                repo_name = m.group(2)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Detect version from VERSION.json
    version = "v0.1.0"
    version_file = (hub_root.parent if hub_root.name == "ontology-hub" else hub_root)
    version_json = version_file / "VERSION.json"
    if version_json.exists():
        try:
            v = json.loads(version_json.read_text(encoding="utf-8"))
            version = f"v{v.get('version', '0.1.0')}"
        except (json.JSONDecodeError, KeyError):
            pass

    # Detect source systems
    sources_dir = hub_root / "integration" / "sources"
    source_systems = []
    if sources_dir.is_dir():
        for d in sorted(sources_dir.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                source_systems.append(d.name)

    return {
        "hub_root": hub_root,
        "repo_url": repo_url,
        "org": org,
        "repo_name": repo_name,
        "version": version,
        "source_systems": source_systems,
    }


@cli.command(name="init-dataplatform")
@click.argument("name", required=False, default=None)
@click.option("--path", "dest", type=click.Path(), default=None,
              help="Parent directory to create the dataplatform repo in (default: sibling of hub).")
@click.option("--platform", type=click.Choice(
    ["fabric-lakehouse", "fabric-warehouse", "databricks"]),
    default="fabric-lakehouse",
    help="Target platform for dbt adapter configuration.")
@click.option("--org", "org_override", type=str, default=None,
              help="GitHub organisation (default: same as hub repo).")
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
        hub_git_root = ctx["hub_root"].parent if ctx["hub_root"].name == "ontology-hub" else ctx["hub_root"]
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
    (repo_dir / "tests").mkdir(parents=True)
    (repo_dir / "seeds").mkdir(parents=True)
    (repo_dir / "snapshots").mkdir(parents=True)
    (repo_dir / "analyses").mkdir(parents=True)

    # Template substitutions
    subs = {
        "{PROJECT_NAME}": project_name,
        "{ORG}": hub_org,
        "{HUB_REPO}": hub_repo,
        "{HUB_VERSION}": hub_version,
        "{DATABASE}": "your_bronze_database",
        "{SCHEMA}": "your_bronze_schema",
    }

    # Copy and template scaffold files
    template_files = {
        "dbt_project.yml.template": "dbt_project.yml",
        "packages.yml.template": "packages.yml",
        "profiles.yml.example": "profiles.yml.example",
        "pyproject.toml.template": "pyproject.toml",
        "README.md.template": "README.md",
    }

    for src_name, dst_name in template_files.items():
        src = _DATAPLATFORM_SCAFFOLD / src_name
        if src.exists():
            content = src.read_text(encoding="utf-8")
            for placeholder, value in subs.items():
                content = content.replace(placeholder, value)
            (repo_dir / dst_name).write_text(content, encoding="utf-8")
            click.echo(f"  ✓ {dst_name}")

    # Copy macros
    macro_src = _DATAPLATFORM_SCAFFOLD / "macros" / "extract_source_schema.sql"
    if macro_src.exists():
        shutil.copy2(macro_src, repo_dir / "macros" / "extract_source_schema.sql")
        click.echo("  ✓ macros/extract_source_schema.sql")

    # Generate _sources.yml from detected source systems
    if ctx["source_systems"]:
        sources_content = "# Physical Source Bindings\n"
        sources_content += "# Update database/schema per environment.\n\n"
        sources_content += "version: 2\n\nsources:\n"
        for sys_name in ctx["source_systems"]:
            sources_content += f"  - name: {sys_name}\n"
            sources_content += f'    description: "Bronze source: {sys_name}"\n'
            sources_content += f'    database: "your_bronze_database"\n'
            sources_content += f'    schema: "raw_{sys_name}"\n'
            sources_content += "    tables:\n"

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
                for tbl_name in sorted(table_names):
                    sources_content += f"      - name: {tbl_name}\n"
            else:
                sources_content += "      # Add tables matching the hub vocabulary\n"
                sources_content += "      # - name: tblExample\n"
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
        ".env\nprofiles.yml\n"
    )
    (repo_dir / ".gitignore").write_text(gitignore, encoding="utf-8")
    click.echo("  ✓ .gitignore")

    # Create .python-version
    (repo_dir / ".python-version").write_text("3.12\n", encoding="utf-8")
    click.echo("  ✓ .python-version")

    # Create minimal Python package so hatchling can build the project
    pkg_name = project_name.replace("-", "_")
    pkg_dir = repo_dir / pkg_name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    click.echo(f"  ✓ {pkg_name}/__init__.py")

    # Initialize git repo
    try:
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=repo_dir,
            capture_output=True, check=True, timeout=10,
        )
        subprocess.run(
            ["git", "add", "."], cwd=repo_dir,
            capture_output=True, check=True, timeout=10,
        )
        subprocess.run(
            ["git", "commit", "-m",
             f"chore: scaffold dataplatform from {hub_org}/{hub_repo}\n\n"
             f"Hub version: {hub_version}\n"
             f"Platform: {platform}\n\n"
             "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"],
            cwd=repo_dir, capture_output=True, check=True, timeout=10,
        )
        click.echo("  ✓ git init + initial commit")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        click.echo(f"  ⚠️  git init skipped: {e}")

    click.echo(f"\n✅ Dataplatform project created at: {repo_dir}")
    click.echo(f"\n📋 Next steps:")
    click.echo(f"   cd {name}")
    click.echo(f"   uv sync")
    click.echo(f"   # Edit profiles.yml.example → ~/.dbt/profiles.yml")
    click.echo(f"   # Edit models/_sources.yml with actual database/schema")
    click.echo(f"   dbt deps")
    click.echo(f"   dbt build")
