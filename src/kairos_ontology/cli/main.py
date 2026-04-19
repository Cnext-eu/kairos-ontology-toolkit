"""Main CLI entry point for kairos-ontology toolkit."""

import re
import click
import shutil
import subprocess
from pathlib import Path
from ..validator import run_validation
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
    """Raise ClickException if *parent* is inside an existing git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=parent, capture_output=True, text=True,
        )
        if result.returncode == 0:
            git_root = Path(result.stdout.strip()).resolve()
            if parent.resolve().is_relative_to(git_root):
                raise click.ClickException(
                    f"Current directory is inside an existing git repo "
                    f"({git_root.name}/).\n"
                    f"  Use --path to create the new repo elsewhere, e.g.:\n"
                    f"    kairos-ontology new-repo {name} --path {git_root.parent}"
                )
    except FileNotFoundError:
        pass  # git not installed yet — will fail later with a clearer message


@click.group()
@click.version_option(version=_toolkit_version, package_name="kairos-ontology-toolkit")
def cli():
    """Kairos Ontology Toolkit - Validation and projection tools for OWL/Turtle ontologies."""
    pass


@cli.command()
@click.option('--ontologies', type=click.Path(exists=True),
              default='ontology-hub/ontologies',
              help='Path to ontologies directory')
@click.option('--shapes', type=click.Path(exists=True),
              default='ontology-hub/shapes',
              help='Path to SHACL shapes directory')
@click.option('--catalog', type=click.Path(exists=True),
              default='ontology-reference-models/catalog-v001.xml',
              help='Path to catalog file for resolving imports')
@click.option('--all', 'validate_all', is_flag=True,
              help='Validate all: syntax + SHACL + consistency')
@click.option('--syntax', is_flag=True, help='Validate syntax only')
@click.option('--shacl', is_flag=True, help='Validate SHACL only')
@click.option('--consistency', is_flag=True, help='Validate consistency only')
def validate(ontologies, shapes, catalog, validate_all, syntax, shacl, consistency):
    """Validate ontologies (syntax, SHACL, consistency)."""
    ontologies_path = Path(ontologies)
    shapes_path = Path(shapes)
    catalog_path = Path(catalog) if catalog else None
    
    # Default to all if nothing specified
    if not any([validate_all, syntax, shacl, consistency]):
        validate_all = True
    
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
              default='ontology-hub/ontologies',
              help='Path to ontologies directory')
@click.option('--catalog', type=click.Path(exists=True),
              default='ontology-reference-models/catalog-v001.xml',
              help='Path to catalog file for resolving imports')
@click.option('--output', type=click.Path(),
              default='ontology-hub/output',
              help='Output directory for projections')
@click.option('--target', type=click.Choice(['all', 'dbt', 'neo4j', 'azure-search', 'a2ui', 'prompt']),
              default='all', help='Projection target')
@click.option('--namespace', type=str, default=None,
              help='Base namespace to project (e.g., http://example.org/ont/). Auto-detects if not provided.')
def project(ontologies, catalog, output, target, namespace):
    """Generate projections from ontologies."""
    ontologies_path = Path(ontologies)
    catalog_path = Path(catalog) if catalog else None
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
        hub / "ontologies",
        hub / "shapes",
        hub / "mappings",
        hub / "output" / "dbt",
        hub / "output" / "neo4j",
        hub / "output" / "azure-search",
        hub / "output" / "a2ui",
        hub / "output" / "prompt",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    # 2. Copy README files for each directory
    for subdir in ["ontologies", "shapes", "mappings"]:
        readme_src = _SCAFFOLD_DIR / "ontology-hub" / subdir / "README.md"
        readme_dst = hub / subdir / "README.md"
        if readme_src.is_file() and (not readme_dst.exists() or force):
            shutil.copy2(readme_src, readme_dst)

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
    master_src = _SCAFFOLD_DIR / "ontology-hub" / "ontologies" / "master.ttl.template"
    master_dst = hub / "ontologies" / "_master.ttl"
    if master_src.is_file():
        if master_dst.exists() and not force:
            print("  ⏭  ontology-hub/ontologies/_master.ttl already exists (use --force)")
        else:
            content = master_src.read_text(encoding="utf-8")
            content = (content
                       .replace("{company_name}", company_name)
                       .replace("{company_domain}", company_domain))
            master_dst.write_text(content, encoding="utf-8")
            print("  ✓ Created ontology-hub/ontologies/_master.ttl")

    # 8. Scaffold a starter domain ontology
    if domain:
        template_src = _SCAFFOLD_DIR / "ontology-hub" / "ontologies" / "starter.ttl.template"
        ontology_dst = hub / "ontologies" / f"{domain}.ttl"
        if ontology_dst.exists() and not force:
            print(f"  ⏭  ontology-hub/ontologies/{domain}.ttl already exists (use --force to overwrite)")
        elif template_src.is_file():
            label = domain.replace("-", " ").replace("_", " ").title()
            content = template_src.read_text(encoding="utf-8")
            content = (content
                       .replace("{domain}", domain)
                       .replace("{label}", label)
                       .replace("{company_domain}", company_domain))
            ontology_dst.write_text(content, encoding="utf-8")
            print(f"  ✓ Created ontology-hub/ontologies/{domain}.ttl")

    # 9. Run smartcoding update if the script exists
    _run_smartcoding_update(cwd)

    print("\n✅ Ontology hub initialized!")
    print("\nNext steps:")
    print("  1. Edit ontology-hub/ontologies/*.ttl to define your domain classes and properties")
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
        hub / "ontologies",
        hub / "shapes",
        hub / "mappings",
        hub / "output" / "dbt",
        hub / "output" / "neo4j",
        hub / "output" / "azure-search",
        hub / "output" / "a2ui",
        hub / "output" / "prompt",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    # README files
    for subdir in ["ontologies", "shapes", "mappings"]:
        src = _SCAFFOLD_DIR / "ontology-hub" / subdir / "README.md"
        dst = hub / subdir / "README.md"
        if src.is_file():
            shutil.copy2(src, dst)

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
    master_src = _SCAFFOLD_DIR / "ontology-hub" / "ontologies" / "master.ttl.template"
    if master_src.is_file():
        content = master_src.read_text(encoding="utf-8")
        content = (content
                   .replace("{company_name}", company_name)
                   .replace("{company_domain}", company_domain_val))
        (hub / "ontologies" / "_master.ttl").write_text(content, encoding="utf-8")
        print("  ✓ ontology-hub/ontologies/_master.ttl")

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

    # --- Git + submodule + commit -------------------------------------------
    try:
        if not use_template:
            subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
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

    # Check gh is available
    try:
        subprocess.run(["gh", "--version"], capture_output=True, check=True)
    except FileNotFoundError:
        print("  ⚠  gh CLI not found — install from https://cli.github.com")
        print("     Then run manually:")
        print(f"       gh repo create {full_name} {visibility} --source . --push")
        return

    # Create the remote repo
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
        print(f"  ⚠  gh repo create failed: {stderr}")
        print("     You can create it manually:")
        print(f"       cd {repo_slug}")
        print(f"       gh repo create {full_name} {visibility} --source . --push")


if __name__ == '__main__':
    cli()
