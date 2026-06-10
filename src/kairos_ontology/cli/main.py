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

# Skills subset for dataplatform repos (used by init-dataplatform and update)
_DATAPLATFORM_SKILLS = [
    "kairos-develop-dataplatform",
    "kairos-package-dataplatform",
    "kairos-help",
    "kairos-diagnose-status",
    "kairos-toolkit-ops",
    "SC-feature-branch",
    "SC-merge-pr",
    "SC-document",
]

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

        # Sort tags by PEP 440 version (numeric comparison, not lexicographic)
        from packaging.version import Version, InvalidVersion

        def _parse_version(tag: str) -> Version:
            try:
                return Version(_tag_to_version(tag))
            except InvalidVersion:
                return Version("0.0.0")

        sorted_tags = sorted(tags, key=_parse_version, reverse=True)

        if channel == "preview":
            return sorted_tags[0]  # highest version (may be pre-release)
        # stable: skip pre-release tags
        for tag in sorted_tags:
            try:
                v = Version(_tag_to_version(tag))
                if not v.is_prerelease:
                    return tag
            except InvalidVersion:
                continue
        return sorted_tags[0]  # fallback if all are pre-releases
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


def _managed_dataplatform_map() -> dict[str, Path]:
    """Return managed-file map for dataplatform repos (skill subset)."""
    result: dict[str, Path] = {}

    ci = _SCAFFOLD_DIR / "dataplatform-copilot-instructions.md"
    if ci.is_file():
        result[".github/copilot-instructions.md"] = ci

    skills = _SCAFFOLD_DIR / "skills"
    for skill_name in _DATAPLATFORM_SKILLS:
        skill_file = skills / skill_name / "SKILL.md"
        if skill_file.is_file():
            result[f".github/skills/{skill_name}/SKILL.md"] = skill_file

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
              help='Path to source-schema YAML file or extracted/<system>/ directory.')
@click.option('--system', 'system_name', default=None,
              help='Override the system name (default: from YAML).')
@click.option('--output', '-o', type=click.Path(), default=None,
              help='Output directory (default: integration/sources/{system}/).')
@click.option('--dry-run', is_flag=True,
              help='Show changes without writing files.')
@click.option('--enrich/--no-enrich', default=True,
              help='Run inference enrichment (enum/format/FK detection). Default: enabled.')
@click.option('--enum-threshold', type=int, default=25,
              help='Max distinct values to suggest as enumeration (default: 25).')
@click.option('--split-tables', is_flag=True, default=False,
              help='ONLY generate per-table files (skip monolithic). By default both are written.')
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
    from ..import_source import run_import_source, parse_source_schema_dir

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

        # Copy .samples.yaml files from source directory to output directory
        if source_path.is_dir() and result_path:
            import shutil as _shutil
            dest_dir = result_path.parent if not split_tables else result_path.parent
            samples_copied = 0
            for samples_file in source_path.glob("*.samples.yaml"):
                dest_file = dest_dir / samples_file.name
                if samples_file.resolve() == dest_file.resolve():
                    continue
                _shutil.copy2(samples_file, dest_file)
                samples_copied += 1
            if samples_copied:
                click.echo(
                    f"   📋 Copied {samples_copied} .samples.yaml file(s) for row-level context"
                )

    # Clean up temp file if we created one
    if tmp_cleanup and tmp_cleanup.exists():
        tmp_cleanup.unlink()


@cli.command(name='import-flatfile')
@click.option('--from', 'from_path', type=click.Path(exists=True), required=True,
              help='Path to CSV file, Excel file, or directory containing flat files.')
@click.option('--system', 'system_name', default=None,
              help='System name (default: derived from filename/directory).')
@click.option('--output', '-o', type=click.Path(), default=None,
              help='Output directory (default: integration/sources/{system}/).')
@click.option('--sample-size', type=int, default=5,
              help='Number of sample rows to store per table (default: 5).')
@click.option('--max-rows', type=int, default=1000,
              help='Maximum rows to read for type inference (default: 1000).')
@click.option('--exclude-columns', default=None,
              help='Comma-separated list of column names to exclude from output.')
@click.option('--keep-technical', is_flag=True, default=False,
              help='Keep auto-detected technical/metadata columns (volume, subfolder, etc.).')
def import_flatfile(
    from_path, system_name, output, sample_size, max_rows, exclude_columns, keep_technical,
):
    """Import CSV/Excel flat files as source schema documentation.

    Reads flat files and produces the standard source schema format
    (_manifest.yaml + per-table YAML + samples). Use import-source afterwards
    to generate the bronze vocabulary TTL.

    \b
    Supported inputs:
      - Single .csv file → 1 table
      - Single .xlsx file → 1 table per worksheet
      - Directory of .csv/.xlsx files → 1 table per file/sheet

    \b
    Examples:
      kairos-ontology import-flatfile --from exports/customers.csv --system erp
      kairos-ontology import-flatfile --from data/report.xlsx --system finance
      kairos-ontology import-flatfile --from data-exports/ --system legacy-erp
      kairos-ontology import-flatfile --from .input/data --system erp \\
        --exclude-columns "volume,subfolder,table"

    \b
    Next step after import-flatfile:
      kairos-ontology import-source --from integration/sources/{system}/
    """
    from ..import_flatfile import run_import_flatfile

    source_path = Path(from_path)
    output_dir = Path(output) if output else None

    # Parse comma-separated exclusion list
    exclude_set: set[str] | None = None
    if exclude_columns:
        exclude_set = {c.strip() for c in exclude_columns.split(",") if c.strip()}

    click.echo(f"📋 Importing flat files from: {source_path}")

    try:
        result_dir = run_import_flatfile(
            source_path=source_path,
            system_name=system_name,
            output_dir=output_dir,
            max_rows=max_rows,
            sample_size=sample_size,
            exclude_columns=exclude_set,
            keep_technical=keep_technical,
        )
    except (ValueError, ImportError) as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)

    # Count outputs
    yaml_count = len(list(result_dir.glob("*.yaml"))) - 1  # exclude _manifest.yaml
    samples_count = len(list(result_dir.glob("*.samples.yaml")))

    click.echo(f"\n✅ Written to: {result_dir}")
    click.echo(f"   📊 {yaml_count} table(s) documented")
    if samples_count:
        click.echo(f"   📋 {samples_count} sample file(s) created")
    click.echo(
        f"\n💡 Next step: kairos-ontology import-source --from {result_dir}"
    )



@click.option('--profile', 'profile_name', required=True,
              help='dbt profile name (from profiles.yml).')
@click.option('--target', default='dev',
              help='dbt target name (default: dev).')
@click.option('--schema', 'schema_name', required=True,
              help='Database schema to introspect.')
@click.option('--system', 'system_name', required=True,
              help='Logical source system name (used for output directory).')
@click.option('--output', '-o', type=click.Path(), default='extracted',
              help='Output base directory (default: extracted/).')
@click.option('--profiles-dir', 'profiles_dir', type=click.Path(exists=True),
              default='.dbt',
              help='Directory containing profiles.yml (default: .dbt/).')
@click.option('--tables', 'table_list', default=None,
              help='Comma-separated list of tables to introspect (default: all).')
@click.option('--sample-size', default=5, type=int,
              help='Number of sample rows per table (default: 5).')
def extract_schema(profile_name, target, schema_name, system_name, output,
                   profiles_dir, table_list, sample_size):
    """Introspect live warehouse/lakehouse schema and produce per-table YAML.

    Connects to the database using dbt profile credentials and extracts:
    column metadata, row counts, sample values, and JSON structure detection.

    \b
    Output structure:
      extracted/<system>/
        _manifest.yaml       (system metadata)
        <table1>.yaml        (columns + samples + JSON)
        <table2>.yaml

    \b
    Examples:
      kairos-ontology extract-schema --profile myproject --schema bronze --system adminpulse
      kairos-ontology extract-schema --profile myproject --schema dbo --system nms \\
          --tables "tblClient,tblInvoice" --sample-size 10
    """
    from ..extract_schema import run_extract_schema

    tables = [t.strip() for t in table_list.split(",")] if table_list else None
    output_path = Path(output)
    profiles_path = Path(profiles_dir)

    click.echo(f"🔍 Extracting schema: {schema_name}")
    click.echo(f"   Profile: {profile_name} (target: {target})")
    click.echo(f"   System: {system_name}")
    click.echo(f"   Profiles dir: {profiles_path}")
    if tables:
        click.echo(f"   Tables: {', '.join(tables)}")
    else:
        click.echo("   Tables: all in schema")
    click.echo(f"   Sample size: {sample_size}")
    click.echo()

    try:
        result_dir = run_extract_schema(
            profiles_dir=profiles_path,
            profile_name=profile_name,
            target=target,
            schema=schema_name,
            system_name=system_name,
            output_dir=output_path,
            tables=tables,
            sample_size=sample_size,
        )
    except ImportError as e:
        click.echo(f"\n❌ Missing dependency: {e}", err=True)
        raise SystemExit(1)
    except FileNotFoundError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)
    except (ValueError, RuntimeError, NotImplementedError) as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)

    # Report results
    yaml_files = sorted(result_dir.glob("*.yaml"))
    table_files = [f for f in yaml_files if f.name != "_manifest.yaml"]
    click.echo(f"✅ Extracted {len(table_files)} tables to: {result_dir}")
    for f in table_files:
        click.echo(f"   📄 {f.name}")


@cli.command(name='generate-staging')
@click.option('--from', 'from_dir', type=click.Path(exists=True), required=True,
              help='Path to extracted/<system>/ directory (from extract-schema).')
@click.option('--output', '-o', type=click.Path(), default='models/staging',
              help='Output directory for staging models (default: models/staging/).')
@click.option('--source', 'source_name', default=None,
              help='dbt source name for {{ source() }} refs (default: from manifest).')
def generate_staging(from_dir, output, source_name):
    """Generate bronze_expanded staging models from JSON metadata.

    Reads extract-schema output (per-table YAML with json_structure) and
    generates dbt SQL models that flatten JSON columns into typed columns.

    \b
    Generated model patterns:
      - Flat JSON → view with JSON_VALUE extractions
      - Array of objects → table with CROSS APPLY OPENJSON

    \b
    Examples:
      kairos-ontology generate-staging --from extracted/adminpulse/
      kairos-ontology generate-staging --from extracted/nms/ --output models/staging/nms
    """
    from ..generate_staging import generate_staging_models

    schema_dir = Path(from_dir)
    output_path = Path(output)

    click.echo(f"🏗️  Generating staging models from: {schema_dir}")
    click.echo(f"   Output: {output_path}")
    click.echo()

    try:
        generated = generate_staging_models(
            schema_dir=schema_dir,
            output_dir=output_path,
            source_name=source_name,
        )
    except FileNotFoundError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)

    if generated:
        click.echo(f"✅ Generated {len(generated)} staging models:")
        for p in generated:
            click.echo(f"   📄 {p.name}")
    else:
        click.echo("ℹ️  No JSON columns detected — no staging models needed.")


@cli.command(name='analyse-sources')
@click.option('--sources', type=click.Path(exists=True), default=None,
              help='Path to integration/sources/ directory (default: auto-detect from hub).')
@click.option('--ref-models', type=click.Path(exists=True), default=None,
              help='Path to ontology-reference-models/ directory (default: auto-detect).')
@click.option('--output', '-o', type=click.Path(), default=None,
              help='Output directory (default: integration/sources/_analysis/).')
@click.option('--threshold', type=float, default=0.3,
              help='Deprecated; ignored in table-centric (schema_version 2) analysis.')
@click.option('--model', 'llm_model', default='gpt-5.4-mini',
              help='LLM model for semantic matching (default: gpt-5.4-mini).')
@click.option('--max-domains', type=int, default=None,
              help='Maximum reference domains to analyse (rate limit protection).')
@click.option('--domains', 'domains_filter', default=None,
              help='Comma-separated domain names to include (case-insensitive substring match).')
@click.option('--materialize', 'materialize_dir', type=click.Path(), default=None,
              help='Write the resolved analysis context (manifest + per-domain YAML) '
                   'to this directory for inspection.')
@click.option('--exclude', 'exclude_patterns', multiple=True, default=('archive/**',),
              help='Glob patterns to exclude from reference models (default: archive/**).')
@click.option('--accelerator', default=None,
              help='Accelerator pack name (e.g. logistics) — classify against its '
                   'data domains (party, commercial, ...) instead of raw reference models.')
@click.option('--shallow', is_flag=True, default=False,
              help='Skip owl:imports resolution in the reference-model fallback (faster).')
@click.option('--verbose', '-v', is_flag=True, default=False,
              help='Show per-table classification lines.')
@click.option('--quiet', '-q', is_flag=True, default=False,
              help='Suppress progress output (errors still shown).')
def analyse_sources_cmd(sources, ref_models, output, threshold, llm_model, max_domains,
                        domains_filter, materialize_dir, exclude_patterns,
                        accelerator, shallow, verbose, quiet):
    """Analyse source vocabularies against reference model domains (LLM-powered).

    Classifies each source table by domain affinity. Two strategies:

    \b
    - Data-domain-first (recommended): pass --accelerator <name> to classify
      tables toward the accelerator's data domains (party, commercial, booking,
      ...), each carrying its model URIs. Fast — no owl:imports resolution.
    - Reference-model (default): resolves and groups reference model TTLs.

    Produces per-source affinity reports that the modeling skill uses to scope
    context and seed evidence tables.

    Requires AI provider configuration (GITHUB_TOKEN or AZURE_AI_ENDPOINT).

    \b
    Examples:
      kairos-ontology analyse-sources --accelerator logistics
      kairos-ontology analyse-sources --accelerator logistics --domains "party,booking"
      kairos-ontology analyse-sources --materialize .resolved/ --verbose
      kairos-ontology analyse-sources --sources path/to/sources/ --ref-models path/to/refs/
    """
    from ..analyse_sources import (
        run_analyse_sources, resolve_reference_models,
        build_data_domain_targets, load_data_domains, list_accelerator_packs,
        make_reporter,
    )
    from ..hub_utils import find_hub_root

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
        # Check common locations
        for candidate_rm in [
            cwd / "ontology-reference-models",
            (hub_root / "ontology-reference-models") if hub_root else None,
            cwd / "ontology-hub" / "ontology-reference-models",
        ]:
            if candidate_rm and candidate_rm.is_dir():
                ref_models_path = candidate_rm
                break
        else:
            click.echo("❌ Cannot find ontology-reference-models/ directory. "
                       "Use --ref-models to specify.", err=True)
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
            click.echo(f"   Domain filter: {domains_filter}")
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
                    f"Available: {available or '(none)'}", err=True,
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
                click.echo(f"📊 Resolved {len(ref_domains)} domain(s) "
                           f"({total_cls} classes, {total_props} properties):")
                for d in ref_domains:
                    n_cls = len(d.get("classes", []))
                    n_props = sum(len(c.get("properties", [])) for c in d.get("classes", []))
                    click.echo(
                        f"   • {d['domain_name']} ({n_cls} classes, {n_props} properties)"
                    )
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
        )
        if not quiet:
            click.echo(
                f"\n✅ Analysis complete! Written {len(output_files)} file(s) "
                f"to: {output_path}"
            )
            for f in output_files:
                click.echo(f"   📄 {f.name}")
    except EnvironmentError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)
    except ValueError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)


@cli.command(name='propose-alignment')
@click.option('--analysis', type=click.Path(exists=True), default=None,
              help='Path to _analysis/ directory with affinity reports (default: auto-detect).')
@click.option('--sources', type=click.Path(exists=True), default=None,
              help='Path to integration/sources/ directory (default: auto-detect).')
@click.option('--catalog', type=click.Path(exists=True), default=None,
              help='Path to catalog-v001.xml (default: auto-detect from hub).')
@click.option('--output', '-o', type=click.Path(), default=None,
              help='Output directory (default: same as --analysis).')
@click.option('--model', 'llm_model', default='gpt-5.4-mini',
              help='LLM model for semantic alignment (default: gpt-5.4-mini).')
@click.option('--domains', 'domains_filter', default=None,
              help='Comma-separated domain names to include (case-insensitive substring match).')
@click.option('--verbose', '-v', is_flag=True, default=False,
              help='Show per-table alignment details.')
@click.option('--quiet', '-q', is_flag=True, default=False,
              help='Suppress progress output (errors still shown).')
def propose_alignment_cmd(analysis, sources, catalog, output, llm_model,
                          domains_filter, verbose, quiet):
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
    from ..propose_alignment import run_propose_alignment
    from ..hub_utils import find_hub_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd)

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

    # Output defaults to same dir as analysis
    if output is None:
        output_path = analysis_path
    else:
        output_path = Path(output)

    if not quiet:
        click.echo("📐 Proposing column→property alignment")
        click.echo(f"   Analysis: {analysis_path}")
        click.echo(f"   Sources: {sources_path}")
        click.echo(f"   Catalog: {catalog_path or '(none)'}")
        click.echo(f"   Model: {llm_model}")
        if domains_filter:
            click.echo(f"   Domain filter: {domains_filter}")
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
        output_files = run_propose_alignment(
            analysis_dir=analysis_path,
            sources_dir=sources_path,
            catalog_path=catalog_path,
            output_dir=output_path,
            model=llm_model,
            domains_filter=filter_list,
            report=reporter,
        )
        if not quiet:
            click.echo(
                f"\n✅ Alignment complete! Written {len(output_files)} file(s) "
                f"to: {output_path}"
            )
            for f in output_files:
                click.echo(f"   📄 {f.name}")
    except EnvironmentError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)
    except ValueError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)


@cli.command('coverage-report')
@click.option('--ontology', type=click.Path(exists=True), default=None,
              help='Path to model/ontologies/ directory (default: auto-detect from hub).')
@click.option('--ref-models', type=click.Path(exists=True), default=None,
              help='Path to ontology-reference-models/ directory (default: auto-detect).')
@click.option('--sources', type=click.Path(exists=True), default=None,
              help='Path to integration/sources/ (for evidence tracing).')
@click.option('--output', '-o', type=click.Path(), default=None,
              help='Output directory (default: output/reports/).')
@click.option('--format', 'out_format', type=click.Choice(['yaml', 'markdown', 'both']),
              default='both', help='Output format (default: both).')
@click.option('--model', 'llm_model', default='gpt-5.4-mini',
              help='LLM model for semantic matching (default: gpt-5.4-mini).')
def coverage_report_cmd(ontology, ref_models, sources, output, out_format, llm_model):
    """Generate ontology-to-reference-model coverage report (LLM-powered).

    Measures how well the domain ontology aligns with industry reference models,
    traces source evidence, and suggests improvements.

    Requires AI provider configuration (GITHUB_TOKEN or AZURE_AI_ENDPOINT).

    \b
    Examples:
      kairos-ontology coverage-report
      kairos-ontology coverage-report --format markdown
      kairos-ontology coverage-report --ontology path/to/ontologies/ --ref-models path/to/refs/
    """
    from ..coverage_report import (
        run_coverage_report,
        write_coverage_yaml,
        write_coverage_markdown,
    )

    # Auto-detect hub paths
    from ..hub_utils import find_hub_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=True)

    if ontology is None:
        if hub_root:
            ont_path = hub_root / "model" / "ontologies"
        else:
            click.echo("❌ Cannot find model/ontologies/ directory. "
                       "Use --ontology to specify.", err=True)
            raise SystemExit(1)
    else:
        ont_path = Path(ontology)

    if ref_models is None:
        for candidate_rm in [
            cwd / "ontology-reference-models",
            (hub_root / "ontology-reference-models") if hub_root else None,
            cwd / "ontology-hub" / "ontology-reference-models",
        ]:
            if candidate_rm and candidate_rm.is_dir():
                ref_models_path = candidate_rm
                break
        else:
            click.echo("❌ Cannot find ontology-reference-models/ directory. "
                       "Use --ref-models to specify.", err=True)
            raise SystemExit(1)
    else:
        ref_models_path = Path(ref_models)

    sources_path = None
    if sources:
        sources_path = Path(sources)
    elif hub_root and (hub_root / "integration" / "sources").is_dir():
        sources_path = hub_root / "integration" / "sources"

    if output is None:
        if hub_root:
            output_path = hub_root.parent / "output" / "reports"
        else:
            output_path = Path("output/reports")
    else:
        output_path = Path(output)

    click.echo("📊 Generating coverage report")
    click.echo(f"   Ontology: {ont_path}")
    click.echo(f"   Reference models: {ref_models_path}")
    click.echo(f"   Model: {llm_model}")
    click.echo()

    try:
        report = run_coverage_report(
            ontology_dir=ont_path,
            ref_models_dir=ref_models_path,
            sources_dir=sources_path,
            model=llm_model,
        )

        output_files = []
        if out_format in ("yaml", "both"):
            yaml_path = write_coverage_yaml(report, output_path)
            output_files.append(yaml_path)
        if out_format in ("markdown", "both"):
            md_path = write_coverage_markdown(report, output_path)
            output_files.append(md_path)

        click.echo("\n✅ Coverage report generated!")
        click.echo(f"   Classes: {report.aligned_classes}/{report.total_classes} "
                   f"({report.class_coverage_pct}%)")
        click.echo(f"   Properties: {report.aligned_properties}/{report.total_properties} "
                   f"({report.property_coverage_pct}%)")
        click.echo()
        for f in output_files:
            click.echo(f"   📄 {f}")

    except EnvironmentError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)
    except ValueError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)


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
                print("   ✓ Created pyproject.toml (was missing)")
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
        print("   Syncing environment with uv ...")
        result = subprocess.run(["uv", "lock"], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ uv lock failed:\n{result.stderr}")
            raise SystemExit(1)
        if sys.platform == "win32":
            # On Windows the running .exe is locked and uv sync cannot replace it.
            # uv run auto-syncs when the lock file is newer, so the new version
            # activates on the next invocation without manual intervention.
            print(f"   ✓ Upgraded to {ref} (will activate on next uv run)")
        else:
            result = subprocess.run(["uv", "sync"], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"❌ uv sync failed:\n{result.stderr}")
                raise SystemExit(1)
            print(f"   ✓ Upgraded to {ref}")

    # Detect repo type: dataplatform (has dbt_project.yml) vs ontology-hub
    repo_root = Path.cwd()
    if (repo_root / "dbt_project.yml").is_file():
        managed_map = _managed_dataplatform_map()
    else:
        managed_map = _managed_scaffold_map()

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

    # --- Ensure .env.example exists (AI provider config) ---------------------
    if not check:
        env_example_src = _SCAFFOLD_DIR / ".env.example"
        env_example_dst = repo_root / ".env.example"
        if not env_example_dst.is_file() and env_example_src.is_file():
            shutil.copy2(env_example_src, env_example_dst)
            print("  ✓ Created .env.example (AI provider configuration template)")

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
    _skip_dirs = {"source-system-template", "reference-data"}
    if sources_dir.is_dir():
        for d in sorted(sources_dir.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and d.name not in _skip_dirs:
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
    click.echo("\n📋 Next steps:")
    click.echo(f"   cd {name}")
    click.echo("   uv sync")
    click.echo("   # Edit profiles.yml.example → ~/.dbt/profiles.yml")
    click.echo("   # Edit models/_sources.yml with actual database/schema")
    click.echo("   dbt deps")
    click.echo("   dbt build")
