# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Main CLI entry point for kairos-ontology toolkit."""

import re
import click
import shutil
import subprocess
from pathlib import Path
from ..validator import run_validation, run_gdpr_validation
from ..projector import run_projections
from ..catalog_test import test_catalog_resolution
from .. import __version__ as _toolkit_version

# Resolve scaffold data directory bundled with the package
_SCAFFOLD_DIR = Path(__file__).resolve().parent.parent / "scaffold"

# Reference models repository
_REF_MODELS_REPO = (
    "https://github.com/Cnext-eu/kairos-ontology-referencemodels.git"
)
_REF_MODELS_PATH = "ontology-reference-models"

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
@click.option('--target', type=click.Choice(['all', 'dbt', 'neo4j', 'azure-search', 'a2ui', 'prompt', 'silver', 'report']),
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
        hub / "output" / "medallion" / "gold",
        hub / "output" / "medallion" / "dbt",
        hub / "output" / "neo4j",
        hub / "output" / "azure-search",
        hub / "output" / "a2ui",
        hub / "output" / "prompt",
        hub / "output" / "report",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    # Place .gitkeep in empty output subdirs so git tracks them
    for target in [
        "medallion/gold", "medallion/dbt",
        "neo4j", "azure-search", "a2ui", "prompt", "report",
    ]:
        gitkeep = hub / "output" / target / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()
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

    # 4c. Copy update-referencemodels.ps1
    refscript_src = _SCAFFOLD_DIR / "update-referencemodels.ps1"
    refscript_dst = cwd / "update-referencemodels.ps1"
    if refscript_src.is_file():
        if refscript_dst.exists() and not force:
            print("  ⏭  update-referencemodels.ps1 already exists (use --force to overwrite)")
        else:
            shutil.copy2(refscript_src, refscript_dst)
            print("  ✓ Installed update-referencemodels.ps1")

    # 4d. Copy .gitignore
    gitignore_src = _SCAFFOLD_DIR / "gitignore.template"
    gitignore_dst = cwd / ".gitignore"
    if gitignore_src.is_file():
        if gitignore_dst.exists() and not force:
            print("  ⏭  .gitignore already exists (use --force to overwrite)")
        else:
            shutil.copy2(gitignore_src, gitignore_dst)
            print("  ✓ Installed .gitignore")

    # 5. Add reference models as git submodule
    _add_reference_models(cwd)

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

@cli.command()
@click.option("--check", is_flag=True,
              help="Report outdated files without modifying anything (exit 1 on drift).")
def update(check):
    """Update toolkit-managed files to the installed toolkit version.

    Scans .github/ for files stamped by kairos-ontology-toolkit and refreshes
    them from the currently installed package.  Use --check to preview what
    would change without writing anything.

    \b
    Exit codes (with --check):
      0  All managed files are up to date
      1  One or more files are outdated or missing

    \b
    Managed files (do not edit manually):
      .github/copilot-instructions.md
      .github/skills/*/SKILL.md
    """
    managed_map = _managed_scaffold_map()
    repo_root = Path.cwd()

    updated: list[tuple[str, str]] = []
    outdated: list[tuple[str, str]] = []
    missing: list[str] = []
    current: list[str] = []

    for rel_path, scaffold_src in managed_map.items():
        local_file = repo_root / rel_path
        if not local_file.is_file():
            missing.append(rel_path)
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
        if not outdated and not missing:
            print(f"✅ All managed files are up to date (v{_toolkit_version})")
        else:
            raise SystemExit(1)
    else:
        if updated:
            print(f"✅ Updated {len(updated)} file(s) to v{_toolkit_version}:")
            for path, ver in updated:
                print(f"   {path}  ({ver} → {_toolkit_version})")
        if missing:
            print(f"⚠  {len(missing)} managed file(s) missing "
                  f"(run new-repo or init to create them):")
            for p in missing:
                print(f"   {p}")
        if not updated and not missing:
            print(f"✅ All managed files are up to date (v{_toolkit_version})")

    # --- Migrate .gitignore: remove legacy output/ ignore line ---------------
    if not check:
        gitignore_path = repo_root / ".gitignore"
        if gitignore_path.is_file():
            content = gitignore_path.read_text(encoding="utf-8")
            legacy_line = "ontology-hub/output/"
            lines = content.splitlines(keepends=True)
            filtered = [
                l for l in lines
                if l.strip() != legacy_line and l.strip() != f"# Generated projection outputs"
            ]
            # Also drop a blank line that may have been left behind after the block
            cleaned = "".join(filtered).lstrip("\n")
            if cleaned != content:
                gitignore_path.write_text(cleaned, encoding="utf-8")
                print(f"  ✓ Removed legacy 'ontology-hub/output/' from .gitignore "
                      f"(projection outputs are now tracked in git)")

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
        hub / "output" / "medallion" / "gold",
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
            print(f"  DELETE  application-models/  (ERDs now in output/medallion/dbt/docs/diagrams/)")
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
              help="Git ref (tag/branch) for the reference-models submodule (default: latest).")
@click.option("--template", "template", type=str, default="kairos-app-template",
              help="GitHub repo template to use (default: kairos-app-template). "
                   "Pass empty string to skip.")
@click.option("--company-domain", "company_domain", type=str, default=None,
              help="Company internet domain (e.g., \"contoso.com\"). "
                   "Defaults to <name>.com if not provided.")
def new_repo(name, desc, dest, org, is_private, ref_models_version, template, company_domain):
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
      pip install -e .
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
        hub / "output" / "medallion" / "gold",
        hub / "output" / "medallion" / "dbt",
        hub / "output" / "neo4j",
        hub / "output" / "azure-search",
        hub / "output" / "a2ui",
        hub / "output" / "prompt",
        hub / "output" / "report",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    # Place .gitkeep in output subdirs so git tracks them
    for target in [
        "medallion/gold", "medallion/dbt",
        "neo4j", "azure-search", "a2ui", "prompt", "report",
    ]:
        gitkeep = hub / "output" / target / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()

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

    # --- Repo-level files ---------------------------------------------------
    # pyproject.toml
    pyproject_src = _SCAFFOLD_DIR / "pyproject.toml.template"
    if pyproject_src.is_file():
        content = pyproject_src.read_text(encoding="utf-8")
        content = (content
                   .replace("{repo_name}", repo_slug)
                   .replace("{description}", description)
                   .replace("{toolkit_version}", _toolkit_version))
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

    # --- Git + submodule + commit -------------------------------------------
    try:
        if not use_template:
            subprocess.run(
                ["git", "init", "-b", "main"],
                cwd=repo_dir, capture_output=True, check=True,
            )
        # Add reference models as git submodule
        _add_reference_models(repo_dir, ref_models_version)
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

    print(f"\n✅ Repository created: {repo_slug}")
    print(f"   GitHub: https://github.com/{org}/{repo_slug}")
    print("\nNext steps:")
    print(f"  cd {repo_dir}")
    print("  pip install -e .")
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
_REF_MODELS_SCRIPT = "update-referencemodels.ps1"


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


def _run_reference_models_update(repo_dir: Path, version: str | None = None):
    """Run update-referencemodels.ps1 to populate ontology-reference-models/.

    The script performs a sparse clone and copies the reference model files
    into the repo.  After running it, any new/changed files are committed.
    """
    script = repo_dir / _REF_MODELS_SCRIPT
    if not script.is_file():
        print(f"  ⚠  {_REF_MODELS_SCRIPT} not found — skipping reference models update")
        return

    print(f"  ▶ Running {_REF_MODELS_SCRIPT} …")
    cmd = ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    if version:
        cmd += ["-Ref", version]
    try:
        subprocess.run(cmd, cwd=repo_dir, check=True)
        # Commit the populated reference-models content
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir, capture_output=True, text=True,
        )
        if result.stdout.strip():
            subprocess.run(["git", "add", "ontology-reference-models"], cwd=repo_dir,
                           capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "chore: populate ontology-reference-models"],
                cwd=repo_dir, capture_output=True, check=True,
            )
            subprocess.run(["git", "push"], cwd=repo_dir, capture_output=True, check=True)
            print("  ✓ Reference models populated and committed")
        else:
            print("  ✓ Reference models already up to date")
    except FileNotFoundError:
        print(f"  ⚠  pwsh not found — run {_REF_MODELS_SCRIPT} manually to populate reference models")
    except subprocess.CalledProcessError as exc:
        print(f"  ⚠  {_REF_MODELS_SCRIPT} failed — run it manually")
        if hasattr(exc, "stderr") and exc.stderr:
            print(f"       {exc.stderr.decode().strip()}")


def _add_reference_models(repo_dir: Path, version: str | None = None):
    """Add kairos-ontology-referencemodels as a git submodule.

    If *version* is given it should be a git ref (tag or branch).  The
    submodule is checked out at that ref after being added.
    """
    target = repo_dir / _REF_MODELS_PATH
    if target.exists() and any(target.iterdir()):
        print(f"  ⏭  {_REF_MODELS_PATH}/ already exists — skipping submodule")
        return

    try:
        # Enable long paths to avoid Windows filename length issues
        subprocess.run(
            ["git", "config", "core.longpaths", "true"],
            cwd=repo_dir, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "submodule", "add", _REF_MODELS_REPO, _REF_MODELS_PATH],
            cwd=repo_dir, capture_output=True, check=True,
        )
        if version:
            subprocess.run(
                ["git", "checkout", version],
                cwd=target, capture_output=True, check=True,
            )
            subprocess.run(
                ["git", "add", _REF_MODELS_PATH],
                cwd=repo_dir, capture_output=True, check=True,
            )
        print(f"  ✓ Reference models submodule ({version or 'latest'})")
    except FileNotFoundError:
        print("  ⚠  git not found — skipping reference models submodule")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode().strip() if exc.stderr else str(exc)
        print(f"  ⚠  Failed to add reference models submodule: {stderr}")
        print("     You can add it manually:")
        print(f"       cd {repo_dir.name}")
        print(f"       git submodule add {_REF_MODELS_REPO} {_REF_MODELS_PATH}")


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
