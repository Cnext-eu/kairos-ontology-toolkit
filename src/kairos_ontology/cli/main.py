# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Main CLI entry point for kairos-ontology toolkit."""

import json
import os
import re
import sys
import click
import shutil
import subprocess
from pathlib import Path
from ..core.validator import run_validation, run_gdpr_validation
from ..core.projector import ProjectionRunError, run_projections
from ..core.catalog_test import test_catalog_resolution
from .. import __version__ as _toolkit_version
from ..core._provenance import provenance_comment
# Importing the design-time MDM package registers the additive ``mdm-profile``
# projection target with the core projector (registry pattern, MDM-DD-002).
# The CLI is the layer that legitimately depends on both core and mdm.
from .. import mdm as _mdm  # noqa: F401  (import for side-effect: target registration)


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


def _warn_if_outside_venv() -> None:
    """Emit a warning if running outside the project's .venv.

    Detects when the user invokes ``python -m kairos_ontology`` using a system
    Python while a local ``.venv`` exists (created by ``uv``).  This avoids
    silently running a stale toolkit version installed globally.
    """
    if sys.prefix != sys.base_prefix:
        return  # already inside a venv — nothing to warn about

    cwd = Path.cwd()
    candidates = [cwd / ".venv", cwd.parent / ".venv"]
    if not any(p.is_dir() for p in candidates):
        return  # no local venv found — probably intentional

    click.echo(
        "⚠️  Running outside the project .venv — you may be using a different\n"
        "   toolkit version than the one pinned in this hub.\n"
        "   Fix: activate the venv or use `uv run kairos-ontology`.\n",
        err=True,
    )


# Resolve scaffold data directory bundled with the package
_SCAFFOLD_DIR = Path(__file__).resolve().parent.parent / "scaffold"

# ---------------------------------------------------------------------------
# Skill-first soft gate
#
# These commands are *skill-managed*: each is wrapped by a Copilot skill that
# runs pre-flight checks and interactive validation gates the raw CLI skips.
# When invoked directly (outside a skill context) we emit a loud warning that
# redirects to the skill, but still run the command (soft gate).  Skills set the
# ``KAIROS_SKILL_CONTEXT`` env var so the skill path stays silent and only the
# raw path nags.  See DD-053 in docs/design/toolkit-design-decisions.md.
# ---------------------------------------------------------------------------
_SKILL_COVERED_COMMANDS = {
    "validate": "kairos-execute-validate",
    "project": "kairos-execute-project",
    "init": "kairos-setup-config",
    "new-repo": "kairos-setup-init",
    "migrate": "kairos-setup-migrate",
    "update": "kairos-toolkit-ops",
    "update-refmodels": "kairos-toolkit-ops",
    "import-source": "kairos-design-source",
    "import-flatfile": "kairos-design-source",
    "source-privacy": "kairos-design-source",
    "generate-staging": "kairos-design-source",
    "analyse-sources": "kairos-design-source",
    "derive-claims": "kairos-design-source",
    "draft-model-report": "kairos-design-domain",
    "decide-claims": "kairos-design-domain",
    "discovery-conformance": "kairos-design-discovery",
    "init-dataplatform": "kairos-setup-dataplatform",
    "suggest-shapes": "kairos-execute-validate",
    "mdm-validate": "kairos-design-mdm",
    "sync-dbt-contracts": "kairos-develop-dbt-transformation",
    "validate-dbt": "kairos-execute-validate",
}
# Env vars that signal the command was launched from within a skill context.
_SKILL_CONTEXT_ENV_VARS = ("KAIROS_SKILL_CONTEXT", "KAIROS_VIA_SKILL")


def _in_skill_context() -> bool:
    """Return True if a skill-context sentinel env var is set (truthy)."""
    return any(os.environ.get(var) for var in _SKILL_CONTEXT_ENV_VARS)


def _warn_if_no_skill_context(subcommand: str | None) -> None:
    """Emit a soft skill-gate warning for skill-managed commands.

    If *subcommand* is covered by a Copilot skill and the process is not running
    inside a skill context (no sentinel env var), print a loud warning to stderr
    that redirects the operator to the skill.  The command still runs afterwards
    — this is a soft gate, not a hard block.
    """
    if not subcommand:
        return
    skill = _SKILL_COVERED_COMMANDS.get(subcommand)
    if skill is None:
        return  # not a skill-managed command (e.g. import-tmdl, coverage-report)
    if _in_skill_context():
        return  # launched from within a skill — stay quiet

    click.echo(
        f"⚠️  `{subcommand}` is skill-managed.\n"
        f"   Prefer the **{skill}** skill in GitHub Copilot Chat — it runs\n"
        f"   pre-flight checks and validation gates this raw command skips.\n"
        f"   Continuing anyway… (set KAIROS_SKILL_CONTEXT=1 to silence)\n",
        err=True,
    )


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


def _resolve_ref_models_dir(cwd: Path, hub_root: Path | None) -> Path | None:
    """Locate the reference-models directory.

    Reference models live at the **repository root** in
    ``ontology-reference-models/`` (a sibling of ``model/``), not under
    ``model/reference-models/``.  Returns the first existing candidate, or
    ``None`` if none are found.  The legacy ``model/reference-models/`` location
    is kept as a last-resort fallback for backward compatibility.
    """
    candidates = [
        cwd / _REF_MODELS_PATH,
        (hub_root / _REF_MODELS_PATH) if hub_root else None,
        (hub_root.parent / _REF_MODELS_PATH) if hub_root else None,
        cwd / "ontology-hub" / _REF_MODELS_PATH,
        (hub_root / "model" / "reference-models") if hub_root else None,
    ]
    for candidate in candidates:
        if candidate and candidate.is_dir():
            return candidate
    return None


def _resolve_import_dir(cwd: Path, hub_root: Path | None) -> Path:
    """Locate the business-discovery import directory.

    Raw discovery artifacts live at the **repository root** in
    ``.import/businessdiscovery/`` (a sibling of ``ontology-hub/`` and
    ``ontology-reference-models/``), not under ``ontology-hub/``.  Like
    :func:`_resolve_ref_models_dir`, this resolves the dual layout so the command
    works both from the repo root and from inside ``ontology-hub/`` (DD-064).

    Returns the first existing candidate, or ``cwd/.import/businessdiscovery`` as
    a stable fallback when none exist (so the caller's "nothing to process"
    message still reports a sensible path).
    """
    rel = Path(".import") / "businessdiscovery"
    candidates = [
        cwd / rel,
        (hub_root.parent / rel) if hub_root else None,
        (hub_root / rel) if hub_root else None,
    ]
    for candidate in candidates:
        if candidate and candidate.is_dir():
            return candidate
    return cwd / rel


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


def _read_pinned_toolkit_version() -> str | None:
    """Return the toolkit version pinned in the cwd ``pyproject.toml`` (or None).

    Parses the ``kairos-ontology-toolkit @ …`` dependency, supporting both the
    ``.whl`` release URL and the legacy ``git+https://…@<tag>`` form, and returns
    the PEP 440 version derived from the tag.  Returns ``None`` when there is no
    pyproject, no toolkit pin, or the tag cannot be parsed.
    """
    pyproject = Path.cwd() / "pyproject.toml"
    if not pyproject.is_file():
        return None
    content = pyproject.read_text(encoding="utf-8")
    # .whl release URL: .../releases/download/<tag>/kairos_ontology_toolkit-...
    m = re.search(
        r"kairos-ontology-toolkit\s*@\s*https://github\.com/[^/]+/[^/]+/"
        r"releases/download/([^/]+)/",
        content,
    )
    if not m:
        # Legacy git pin: kairos-ontology-toolkit @ git+https://…@<tag>
        m = re.search(
            r"kairos-ontology-toolkit\s*@\s*git\+https://[^\s\"@]+@([^\s\"]+)",
            content,
        )
    if not m:
        return None
    return _tag_to_version(m.group(1))


def _warn_if_version_mismatch() -> None:
    """Warn when the running toolkit version differs from the hub's pin.

    Catches the case where a user runs a globally-installed (often older)
    ``kairos-ontology`` / ``python -m kairos_ontology`` instead of
    ``uv run kairos-ontology``, silently using a different version than the one
    pinned in this hub's ``pyproject.toml``.  Non-blocking (stderr warning only).
    """
    pinned = _read_pinned_toolkit_version()
    if not pinned or pinned == _toolkit_version:
        return

    relation = "different from"
    try:
        from packaging.version import parse as _parse_version

        if _parse_version(_toolkit_version) < _parse_version(pinned):
            relation = "OLDER than"
    except Exception:  # pragma: no cover - packaging always present via deps
        pass

    click.echo(
        f"⚠️  Running kairos-ontology v{_toolkit_version}, which is {relation} the\n"
        f"   version pinned in this hub (v{pinned}).\n"
        f"   You may be using a globally-installed toolkit.\n"
        f"   Fix: run `uv run kairos-ontology …` (or `uv sync`) to use the pin.\n",
        err=True,
    )

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


def _schedule_windows_refresh(check: bool) -> bool:
    """Schedule a detached managed-file refresh that runs after THIS process exits.

    On Windows the currently-running ``kairos-ontology.exe`` holds a lock on its own
    executable, so an in-process (or synchronously re-exec'd) ``uv sync`` cannot replace
    it with the newly-pinned version — the refresh would fail with a file-lock error.

    To work around this we spawn a fully detached PowerShell process that:

    1. Waits for the current parent PID to terminate (releasing the ``.exe`` lock),
    2. Runs ``uv sync`` to install the new version, then
    3. Runs ``uv run kairos-ontology update`` (with ``--check`` if requested) to refresh
       the managed files under the new version.

    Output is mirrored to a transcript log so the result is durable after the spawned
    console window closes.  Returns ``True`` if the helper was scheduled, ``False`` on
    failure (callers fall back to printing manual guidance).
    """
    pid = os.getpid()
    update_cmd = "uv run kairos-ontology update"
    if check:
        update_cmd += " --check"

    log_dir = Path.cwd() / ".kairos"
    log_path = log_dir / "upgrade-refresh.log"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    ps_script = (
        f"Wait-Process -Id {pid} -ErrorAction SilentlyContinue; "
        f"Start-Sleep -Milliseconds 750; "
        f"try {{ Start-Transcript -Path '{log_path}' -Force | Out-Null }} catch {{}} ; "
        f"Write-Host 'Refreshing managed files under the upgraded toolkit...'; "
        f"uv sync; "
        f"{update_cmd}; "
        f"try {{ Stop-Transcript | Out-Null }} catch {{}}"
    )

    # DETACHED_PROCESS=0x8, CREATE_NEW_CONSOLE=0x10, CREATE_NEW_PROCESS_GROUP=0x200.
    # A visible console lets the user watch progress; the transcript keeps a record.
    creationflags = 0x00000010 | 0x00000200
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            creationflags=creationflags,
            close_fds=True,
        )
    except (OSError, ValueError):
        return False
    return True


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
@click.pass_context
def cli(ctx):
    """Kairos Ontology Toolkit - Validation and projection tools for OWL/Turtle ontologies."""
    _warn_if_outside_venv()
    _warn_if_version_mismatch()
    _warn_if_no_skill_context(ctx.invoked_subcommand)


_LIFECYCLE_TABLE = """\
┌─────────────────────────────────────────────────────────────────────────┐
│                         ONTOLOGY HUB LIFECYCLE                          │
├──────────┬──────────────────────────────────────────────────────────────┤
│  PHASE   │  SKILLS                                                      │
├──────────┼──────────────────────────────────────────────────────────────┤
│ Orient   │  kairos-help                                                  │
├──────────┼──────────────────────────────────────────────────────────────┤
│ Start    │  kairos-flow              (status + start/continue)           │
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
│          │  kairos-design-mdm        (MDM policy → mdm-profile)          │
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


@cli.command(name="sync-dbt-contracts")
@click.option(
    "--transforms",
    type=click.Path(path_type=Path),
    help="Custom dbt transforms directory (default: integration/transforms/dbt).",
)
@click.option(
    "--sources",
    type=click.Path(path_type=Path),
    help="Generated vocabulary directory (default: integration/sources/custom-transformations).",
)
@click.option(
    "--bronze-sources",
    type=click.Path(path_type=Path),
    help="Bronze input vocabulary root used to validate replacements "
    "(default: integration/sources).",
)
@click.option("--check", is_flag=True, help="Report drift without writing files.")
def sync_dbt_contracts_cmd(transforms, sources, bronze_sources, check):
    """Synchronize custom dbt contracts to Bronze-compatible RDF vocabularies."""
    from ..core.dbt_contract_sync import sync_dbt_contracts
    from ..core.hub_utils import find_hub_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd) or cwd

    def resolve_override(value):
        if value is None:
            return None
        path = Path(value)
        return path if path.is_absolute() else hub_root / path

    try:
        report = sync_dbt_contracts(
            hub_root,
            transforms_dir=resolve_override(transforms),
            sources_dir=resolve_override(sources),
            bronze_sources_dir=resolve_override(bronze_sources),
            check=check,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if not report.items:
        click.echo("No custom dbt contracts found; nothing to synchronize.")
        return
    for item in report.items:
        click.echo(f"{item.action}: {item.model} -> {item.output_path}")
    if check and report.has_drift:
        raise click.exceptions.Exit(1)
    click.echo(
        f"dbt contract sync complete: {report.written_count} written, "
        f"{report.unchanged_count} unchanged."
    )


@cli.command(name="validate-dbt")
@click.option(
    "--platform",
    type=click.Choice(["fabric", "databricks"]),
    required=True,
    help="Adapter used to parse and compile the generated project.",
)
@click.option(
    "--project-dir",
    type=click.Path(path_type=Path),
    help="dbt project directory (default: output/medallion/dbt).",
)
@click.option(
    "--profiles-dir",
    type=click.Path(path_type=Path),
    help="Optional directory containing a non-committed profiles.yml.",
)
def validate_dbt_cmd(platform, project_dir, profiles_dir):
    """Run offline dependency, parse, graph, and compile validation for dbt."""
    from ..core.dbt_validation import DbtValidationError, validate_dbt_project
    from ..core.hub_utils import find_hub_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=False) or cwd

    def resolve(value, default):
        path = Path(value) if value is not None else default
        return path if path.is_absolute() else hub_root / path

    project = resolve(project_dir, hub_root / "output" / "medallion" / "dbt")
    profiles = resolve(profiles_dir, None) if profiles_dir is not None else None
    try:
        result = validate_dbt_project(
            project,
            platform,
            profiles_dir=profiles,
        )
    except DbtValidationError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"✓ dbt deps and parse passed for {platform}")
    click.echo(f"✓ manifest graph validated: {result.manifest_path}")
    if result.compile_status == "passed":
        click.echo("✓ dbt compile passed")
    else:
        click.echo(f"⚠ dbt compile environment-blocked: {result.compile_message}")


# Catalog filename used by hubs and the shared reference-models repo.
_CATALOG_FILENAME = "catalog-v001.xml"

# Legacy cwd-relative search order (repo-root invocation), kept as a fallback.
_CATALOG_CANDIDATES = [
    Path("ontology-hub/catalog-v001.xml"),
    Path("ontology-reference-models/catalog-v001.xml"),
]


def _resolve_catalog(
    explicit: str | None,
    hub_root: Path | None = None,
    cwd: Path | None = None,
) -> Path | None:
    """Return the catalog path to use.

    If *explicit* is given (user passed ``--catalog``), use it directly.
    Otherwise search, in order:

    1. ``hub_root/catalog-v001.xml`` (the hub-local catalog),
    2. the reference-models catalog (``_resolve_ref_models_dir``),
    3. the legacy cwd-relative ``_CATALOG_CANDIDATES`` (repo-root invocation).

    Resolving from *hub_root* makes catalog auto-detection work whether the command
    is run from the repo root or from inside ``ontology-hub/`` (DD-064).  Returns
    the first existing candidate, or ``None`` if no catalog is found.
    """
    if explicit:
        return Path(explicit)

    if cwd is None:
        cwd = Path.cwd()

    candidates: list[Path] = []
    if hub_root is not None:
        candidates.append(hub_root / _CATALOG_FILENAME)
    ref_models_dir = _resolve_ref_models_dir(cwd, hub_root)
    if ref_models_dir is not None:
        candidates.append(ref_models_dir / _CATALOG_FILENAME)
    candidates.extend(_CATALOG_CANDIDATES)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


@cli.command()
@click.option('--ontologies', type=click.Path(exists=True), default=None,
              help='Path to ontologies directory (default: auto-detect from hub).')
@click.option('--shapes', type=click.Path(), default=None,
              help='Path to SHACL shapes directory (default: auto-detect from hub; '
                   'optional — SHACL is skipped if it does not exist).')
@click.option('--catalog', type=click.Path(exists=True),
              default=None,
              help='Path to catalog file for resolving imports '
                   '(default: <hub>/catalog-v001.xml or '
                   'ontology-reference-models/catalog-v001.xml)')
@click.option('--all', 'validate_all', is_flag=True,
              help='Validate all: syntax + SHACL + consistency')
@click.option('--syntax', is_flag=True, help='Validate syntax only')
@click.option('--shacl', is_flag=True, help='Validate SHACL only')
@click.option('--consistency', is_flag=True, help='Validate consistency only')
@click.option('--gdpr', is_flag=True, help='Scan for PII properties without GDPR satellite protection')
@click.option('--ddd', 'ddd', is_flag=True,
              help='Validate DDD design overlays (*-ddd-ext.ttl) via the dedicated DDD path')
def validate(ontologies, shapes, catalog, validate_all, syntax, shacl, consistency, gdpr, ddd):
    """Validate ontologies (syntax, SHACL, consistency, GDPR PII scan, DDD overlays)."""
    from ..core.hub_utils import find_hub_root

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

    if shapes is not None:
        shapes_path = Path(shapes)
    elif hub_root is not None:
        shapes_path = hub_root / "model" / "shapes"
    else:
        shapes_path = cwd / "ontology-hub" / "model" / "shapes"

    catalog_path = _resolve_catalog(catalog, hub_root, cwd)

    # Default to all if nothing specified
    if not any([validate_all, syntax, shacl, consistency, gdpr, ddd]):
        validate_all = True

    if gdpr or validate_all:
        run_gdpr_validation(
            ontologies_path=ontologies_path,
            catalog_path=catalog_path,
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
        do_consistency=validate_all or consistency
    )

    # run_validation() exits non-zero on its own failures; if it fell through
    # (its checks passed) but DDD overlays failed, still fail the overall run.
    if ddd_failures:
        raise SystemExit(1)


@cli.command()
@click.option('--ontologies', type=click.Path(exists=True), default=None,
              help='Path to ontologies directory (default: auto-detect from hub).')
@click.option('--ontology', type=click.Path(exists=True, dir_okay=False), default=None,
              help='Path to a single ontology file to project.')
@click.option('--catalog', type=click.Path(exists=True),
              default=None,
              help='Path to catalog file for resolving imports '
                   '(default: <hub>/catalog-v001.xml or '
                   'ontology-reference-models/catalog-v001.xml)')
@click.option('--output', type=click.Path(), default=None,
              help='Output directory for projections (default: <hub>/output).')
@click.option('--target', type=click.Choice(['all', 'dbt', 'neo4j', 'azure-search', 'a2ui', 'prompt', 'silver', 'powerbi', 'report', 'ddd', 'mdm-profile']),
              default='all', help='Projection target')
@click.option(
    '--platform',
    type=click.Choice(['fabric', 'databricks']),
    default='fabric',
    show_default=True,
    help='SQL platform for dbt projection.',
)
@click.option('--namespace', type=str, default=None,
              help='Base namespace to project (e.g., http://example.org/ont/). Auto-detects if not provided.')
def project(ontologies, ontology, catalog, output, target, platform, namespace):
    """Generate projections from ontologies."""
    from ..core.hub_utils import find_hub_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=False)
    if platform != 'fabric' and target not in {'dbt', 'all'}:
        raise click.UsageError("--platform applies only to --target dbt or --target all")

    if ontology is not None and ontologies is not None:
        raise click.UsageError("Use either --ontology for one file or --ontologies for a directory, not both.")

    if ontology is not None:
        ontologies_path = Path(ontology)
    elif ontologies is not None:
        ontologies_path = Path(ontologies)
    elif hub_root is not None:
        ontologies_path = hub_root / "model" / "ontologies"
    else:
        ontologies_path = cwd / "ontology-hub" / "model" / "ontologies"

    if not ontologies_path.is_dir() and not ontologies_path.is_file():
        click.echo(
            f"❌ Cannot find ontology input at {ontologies_path}. "
            "Run from the hub root (or inside ontology-hub/), pass --ontologies "
            "for a directory, or pass --ontology for one file.",
            err=True,
        )
        raise SystemExit(1)

    catalog_path = _resolve_catalog(catalog, hub_root, cwd)

    if output is not None:
        output_path = Path(output)
    elif hub_root is not None:
        output_path = hub_root / "output"
    else:
        output_path = cwd / "ontology-hub" / "output"

    try:
        run_projections(
            ontologies_path=ontologies_path,
            catalog_path=catalog_path,
            output_path=output_path,
            target=target,
            namespace=namespace,
            platform=platform,
        )
    except ProjectionRunError as exc:
        raise click.ClickException(str(exc)) from exc


@cli.command(name='mdm-validate')
@click.option('--ontologies', type=click.Path(exists=True), default=None,
              help='Path to ontologies directory (default: auto-detect from hub).')
@click.option('--catalog', type=click.Path(exists=True), default=None,
              help='Path to catalog file for resolving imports.')
def mdm_validate(ontologies, catalog):
    """Validate MDM extension policy (``*-mdm-ext.ttl``) for each domain.

    Structural design-time gate: checks controlled enumerations, thresholds, match
    rules, DQ dimensions and the probabilistic-artifact reference before the
    ``mdm-profile`` projection is trusted. Prefer the **kairos-design-mdm** skill,
    which wraps this with interactive authoring guidance.
    """
    from ..core.hub_utils import find_hub_root
    from ..core.catalog_utils import load_graph_with_catalog
    from ..core.projections.shared import merge_ext_graph
    from ..mdm.vocabulary import discover_mdm_extension
    from ..mdm.validation import validate_mdm_extension
    from rdflib import Graph

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
        p for p in ontologies_path.glob("*.ttl")
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
        if catalog_path is not None:
            result = load_graph_with_catalog(onto_file, catalog_path)
            base_graph = result.graph
        else:
            base_graph = Graph()
            base_graph.parse(str(onto_file), format="turtle")
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
        hub / "model" / "planning",
        hub / "referencemodels-unpacked",
        hub / "businessdiscovery",
        hub / "businessdiscovery" / "_extractions",
        hub / "integration" / "sources",
        hub / "integration" / "sources" / "custom-transformations",
        hub / "integration" / "transforms" / "dbt" / "models" / "intermediate",
        hub / "integration" / "transforms" / "dbt" / "macros",
        hub / "integration" / "transforms" / "dbt" / "tests",
        hub / "integration" / "discovery",
        hub / "model" / "mappings" / "custom-transformations",
        hub / "output" / "medallion" / "powerbi",
        hub / "output" / "medallion" / "dbt",
        hub / "output" / "neo4j",
        hub / "output" / "azure-search",
        hub / "output" / "a2ui",
        hub / "output" / "prompt",
        hub / "output" / "report",
        hub / ".sessions-projection",
        hub / ".sessions-design-import",
        hub / ".kairos-state",
        hub / ".kairos-state" / "_archive",
        hub / ".kairos-state" / "phases",
        hub / ".kairos-state" / "phases" / "source",
        hub / ".kairos-state" / "phases" / "domain",
        hub / ".kairos-state" / "phases" / "mapping",
        hub / ".kairos-state" / "phases" / "dbt-transformation",
        hub / ".kairos-state" / "phases" / "silver",
        hub / ".kairos-state" / "phases" / "gold",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    # Business-discovery imports live at the REPO ROOT (like ontology-reference-models),
    # not under ontology-hub/. Created on init so it's ready to receive artifacts.
    imports_bd = cwd / ".import" / "businessdiscovery"
    imports_bd.mkdir(parents=True, exist_ok=True)
    imports_readme_src = _SCAFFOLD_DIR / "import" / "businessdiscovery" / "README.md"
    if imports_readme_src.is_file() and (not (imports_bd / "README.md").exists() or force):
        shutil.copy2(imports_readme_src, imports_bd / "README.md")

    # Place .gitkeep in empty output subdirs so git tracks them
    for target in [
        "medallion/powerbi", "medallion/dbt",
        "neo4j", "azure-search", "a2ui", "prompt", "report",
    ]:
        gitkeep = hub / "output" / target / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()

    # Place .gitkeep in audit session folders so git tracks them
    for session_folder in [
        ".sessions-projection",
        ".sessions-design-import",
    ]:
        sk = hub / session_folder / ".gitkeep"
        if not sk.exists():
            sk.touch()

    # Place .gitkeep in OKF state folders so git tracks the lifecycle memory skeleton
    for state_folder in [
        ".kairos-state",
        ".kairos-state/_archive",
        ".kairos-state/phases",
        ".kairos-state/phases/source",
        ".kairos-state/phases/domain",
        ".kairos-state/phases/mapping",
        ".kairos-state/phases/dbt-transformation",
        ".kairos-state/phases/silver",
        ".kairos-state/phases/gold",
    ]:
        sk = hub / state_folder / ".gitkeep"
        if not sk.exists():
            sk.touch()

    # 2. Copy README files for each directory
    readme_map = {
        "model/ontologies": "model/ontologies",
        "model/shapes": "model/shapes",
        "model/mappings": "model/mappings",
        "model/mappings/custom-transformations": "model/mappings/custom-transformations",
        "businessdiscovery": "businessdiscovery",
        "businessdiscovery/_extractions": "businessdiscovery/_extractions",
        "integration/sources": "integration/sources",
        "integration/sources/custom-transformations":
            "integration/sources/custom-transformations",
        "integration/transforms/dbt": "integration/transforms/dbt",
    }
    for scaffold_subdir, hub_subdir in readme_map.items():
        readme_src = _SCAFFOLD_DIR / "ontology-hub" / scaffold_subdir / "README.md"
        readme_dst = hub / hub_subdir / "README.md"
        if readme_src.is_file() and (not readme_dst.exists() or force):
            shutil.copy2(readme_src, readme_dst)

    # 2a. Copy the business glossary template into businessdiscovery/
    glossary_tpl_src = _SCAFFOLD_DIR / "ontology-hub" / "businessdiscovery" / "glossary-template.ttl"
    glossary_tpl_dst = hub / "businessdiscovery" / "glossary-template.ttl"
    if glossary_tpl_src.is_file() and (not glossary_tpl_dst.exists() or force):
        shutil.copy2(glossary_tpl_src, glossary_tpl_dst)

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
            content = provenance_comment("init", editable=True) + "\n" + content
            master_dst.write_text(content, encoding="utf-8")
            print("  ✓ Created ontology-hub/model/ontologies/_master.ttl")

    # 7a-ii. Generate foundation ontology (shared base for thin domain ontologies)
    foundation_src = _SCAFFOLD_DIR / "ontology-hub" / "model" / "ontologies" / "foundation.ttl.template"
    foundation_dst = hub / "model" / "ontologies" / "_foundation.ttl"
    if foundation_src.is_file():
        if foundation_dst.exists() and not force:
            print("  ⏭  ontology-hub/model/ontologies/_foundation.ttl already exists (use --force)")
        else:
            content = foundation_src.read_text(encoding="utf-8")
            content = (content
                       .replace("{company_name}", company_name)
                       .replace("{company_domain}", company_domain))
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
            content = provenance_comment("init", editable=True) + "\n" + content
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
    from ..core.import_tmdl import run_import_tmdl

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


@cli.command(name="source-privacy")
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
        click.echo("✅ Source sample artifacts are privacy-safe for supported patterns.")
        return

    if report.findings:
        click.echo(
            f"❌ {len(report.findings)} privacy finding(s); rerun with --fix.",
            err=True,
        )
        raise SystemExit(1)
    click.echo("✅ Source sample artifacts are privacy-safe for supported patterns.")


@cli.command(name="import-flatfile")
@click.option(
    "--from",
    "from_path",
    type=click.Path(exists=True),
    required=True,
    help="Path to CSV file, Excel file, Parquet file, or directory of flat files.",
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
    default=5,
    help="Number of sample rows to store per table (default: 5).",
)
@click.option(
    "--max-rows",
    type=int,
    default=1000,
    help="Maximum rows to read for type inference (default: 1000).",
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
def import_flatfile(
    from_path, system_name, output, sample_size, max_rows, exclude_columns, keep_technical,
):
    """Import CSV/Excel/Parquet flat files as source schema documentation.

    Reads flat files and produces the standard source schema format
    (_manifest.yaml + per-table YAML + samples). Use import-source afterwards
    to generate the bronze vocabulary TTL.

    \b
    Supported inputs:
      - Single .csv file → 1 table
      - Single .xlsx file → 1 table per worksheet
      - Single .parquet file → 1 table
      - Directory of .csv/.xlsx/.parquet files → 1 table per file/sheet

    \b
    Examples:
      kairos-ontology import-flatfile --from exports/customers.csv --system erp
      kairos-ontology import-flatfile --from data/report.xlsx --system finance
      kairos-ontology import-flatfile --from exports/orders.parquet --system wms
      kairos-ontology import-flatfile --from data-exports/ --system legacy-erp
      kairos-ontology import-flatfile --from .input/data --system erp \\
        --exclude-columns "volume,subfolder,table"

    \b
    Next step after import-flatfile:
      kairos-ontology import-source --from integration/sources/{system}/
    """
    from ..core.import_flatfile import run_import_flatfile

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
    from ..core.extract_schema import run_extract_schema

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
    from ..core.generate_staging import generate_staging_models

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
              help='Comma-separated domain names — OUTPUT filter only (issue #189): '
                   'tables are always classified against the full domain set, then '
                   'only matching primary domains are written (case-insensitive '
                   'substring match).')
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
@click.option('--max-workers', type=int, default=8,
              help='Max concurrent per-table LLM calls (default: 8; use 1 for serial).')
@click.option('--force', is_flag=True, default=False,
              help='Bypass the per-table cache and re-classify every table.')
@click.option('--verbose', '-v', is_flag=True, default=False,
              help='Show per-table classification lines.')
@click.option('--quiet', '-q', is_flag=True, default=False,
              help='Suppress progress output (errors still shown).')
def analyse_sources_cmd(sources, ref_models, output, threshold, llm_model, max_domains,
                        domains_filter, materialize_dir, exclude_patterns,
                        accelerator, shallow, max_workers, force, verbose, quiet):
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
        run_analyse_sources, resolve_reference_models,
        build_data_domain_targets, load_data_domains, list_accelerator_packs,
        make_reporter,
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
        ref_models_path = _resolve_ref_models_dir(cwd, hub_root)
        if ref_models_path is None:
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
            click.echo(f"   Domain filter: {domains_filter} "
                       f"(output focus only — full set is classified)")
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
            max_workers=max_workers,
            force=force,
            cost_warning=not quiet,
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


@cli.command(name='audit-silver-samples')
@click.option('--sources', type=click.Path(exists=True), default=None,
              help='Path to integration/sources/ directory (default: auto-detect).')
@click.option('--mappings', type=click.Path(exists=True), default=None,
              help='Path to model/mappings/ directory (default: auto-detect).')
@click.option('--dbt-output', type=click.Path(exists=True), default=None,
              help='Path to generated dbt output directory (default: output/medallion/dbt).')
@click.option('--output', '-o', type=click.Path(), default=None,
              help='Report output directory (default: output/reports/silver-sample-audit).')
@click.option('--fail-on', type=click.Choice(['none', 'warning', 'error']), default='none',
              help='Exit non-zero when findings at this severity exist (default: none).')
def audit_silver_samples_cmd(sources, mappings, dbt_output, output, fail_on):
    """Offline advisory audit of generated silver dbt mappings using source samples.

    This command reads source vocabularies, SKOS mappings, and generated dbt SQL
    only. It does not require a dbt profile, warehouse credentials, or live bronze
    data. Findings are advisory by default.
    """
    from ..core.hub_utils import find_hub_root
    from ..core.silver_sample_audit import run_silver_sample_audit

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd)
    base = hub_root or cwd

    sources_path = Path(sources) if sources else base / "integration" / "sources"
    mappings_path = Path(mappings) if mappings else base / "model" / "mappings"
    dbt_output_path = Path(dbt_output) if dbt_output else base / "output" / "medallion" / "dbt"
    output_path = Path(output) if output else base / "output" / "reports" / "silver-sample-audit"

    click.echo("🔎 Running offline silver sample audit")
    click.echo(f"   Sources:    {sources_path}")
    click.echo(f"   Mappings:   {mappings_path}")
    click.echo(f"   dbt output: {dbt_output_path}")
    click.echo(f"   Report:     {output_path}")
    click.echo()

    report = run_silver_sample_audit(
        sources_dir=sources_path,
        mappings_dir=mappings_path,
        dbt_output_dir=dbt_output_path,
        output_dir=output_path,
    )

    counts = report.counts
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

    should_fail = (
        (fail_on == 'error' and counts['error'] > 0)
        or (fail_on == 'warning' and (counts['error'] > 0 or counts['warning'] > 0))
    )
    if should_fail:
        raise SystemExit(1)


@cli.command(name='propose-alignment')
@click.option('--analysis', type=click.Path(exists=True), default=None,
              help='Path to _analysis/ directory with affinity reports (default: auto-detect).')
@click.option('--sources', type=click.Path(exists=True), default=None,
              help='Path to integration/sources/ directory (default: auto-detect).')
@click.option('--catalog', type=click.Path(exists=True), default=None,
              help='Path to catalog-v001.xml (default: auto-detect from hub).')
@click.option('--output', '-o', type=click.Path(), default=None,
              help='Claim registry output directory (default: hub model/claims/).')
@click.option('--model', 'llm_model', default='gpt-5.4-mini',
              help='LLM model for semantic alignment (default: gpt-5.4-mini).')
@click.option('--domains', 'domains_filter', default=None,
              help='Comma-separated domain names to include (case-insensitive substring match).')
@click.option('--verbose', '-v', is_flag=True, default=False,
              help='Show per-table alignment details.')
@click.option('--quiet', '-q', is_flag=True, default=False,
              help='Suppress progress output (errors still shown).')
@click.option('--include-mapping-hints', is_flag=True, default=False,
              help='DD-045: add deterministic transform + structural mapping hints '
                   '(advisory, human-confirmed). Default output is unchanged.')
@click.option('--no-sample-values', 'no_sample_values', is_flag=True, default=False,
              help='DD-075: suppress masked sample example_values in the output '
                   '(values are included by default; PII is always masked).')
@click.option('--max-prompt-classes', type=int, default=12,
              help='Max reference classes in first-pass table prompt (default: 12).')
@click.option('--retry-min-confidence', type=click.FloatRange(0.0, 1.0), default=0.6,
              help='Retry with full reference inventory when ref_class confidence is below this '
                   'threshold (default: 0.6).')
@click.option('--retry-min-mapped-ratio', type=click.FloatRange(0.0, 1.0), default=0.4,
              help='Retry with full reference inventory when non-custom mapped column ratio is '
                   'below this threshold (default: 0.4).')
@click.option('--max-workers', type=int, default=8,
              help='Max concurrent per-table LLM calls (default: 8; use 1 for serial).')
@click.option('--force', is_flag=True, default=False,
              help='Bypass caches (domain affinity skip + per-table cache) and re-align all.')
@click.option('--cross-module', 'cross_module', is_flag=True, default=False,
              help='DD-070 (issue #166): widen the property candidate pool to the whole '
                   'accelerator so columns can match sibling/shared-module properties '
                   '(e.g. a shared Address class). Requires --accelerator. Default output '
                   'is unchanged.')
@click.option('--accelerator', default=None,
              help='Accelerator pack name whose data-domains.yaml defines the cross-module '
                   'property pool (required with --cross-module).')
@click.option('--custom-confidence-floor', type=click.FloatRange(0.0, 1.0), default=0.5,
              help='Issue #182: below this confidence an unmatched column emits no '
                   'suggested property (null) instead of a confident-but-wrong guess '
                   '(default: 0.5).')
@click.option('--high-accuracy', 'high_accuracy', is_flag=True, default=False,
              help='Issue #182: use the preferred non-reasoning accuracy tier '
                   '(gpt-5.4) for this accuracy-sensitive alignment step '
                   '(overrides the default model unless --model was set '
                   'explicitly). Costs more per run than the mini default.')
def propose_alignment_cmd(analysis, sources, catalog, output, llm_model,
                          domains_filter, verbose, quiet, include_mapping_hints,
                          no_sample_values,
                          max_prompt_classes, retry_min_confidence, retry_min_mapped_ratio,
                          max_workers, force, cross_module, accelerator,
                          custom_confidence_floor, high_accuracy):
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
    from ..core.propose_alignment import HIGH_ACCURACY_MODEL, run_propose_alignment
    from ..core.ai_provider import DEFAULT_MODEL, ROLE_ALIGNMENT, resolve_role_model
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

    # Output defaults to the hub's claim registry directory (model/claims/).
    # DD-EL-1: propose-alignment now emits candidate (proposed) claims into the
    # Claim Registry instead of the retired {domain}-alignment.yaml.
    if output is None:
        output_path = _resolve_claims_dir(cwd, hub_root)
    else:
        output_path = Path(output)

    # DD-070: resolve the reference-models dir + validate cross-module prerequisites.
    ref_models_dir = None
    if cross_module:
        ref_models_dir = _resolve_ref_models_dir(cwd, hub_root)
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
        )
        if not quiet:
            click.echo(
                f"\n✅ Proposal complete! Wrote {len(output_files)} claim "
                f"registry file(s) to: {output_path}"
            )
            for f in output_files:
                click.echo(f"   📄 {f.name}")
    except EnvironmentError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)
    except ValueError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)


@cli.command('suggest-shapes')
@click.option('--source', type=click.Path(exists=True), default=None,
              help='Path to a bronze source vocabulary TTL (e.g. '
                   '<system>.vocabulary.ttl). Default: auto-detect single vocabulary.')
@click.option('--mappings', type=click.Path(exists=True), default=None,
              help='Optional SKOS mappings TTL (reserved for domain-targeted shapes).')
@click.option('--out', '-o', type=click.Path(), default=None,
              help='Output draft TTL path (default: output/shapes-draft/<name>.ttl).')
@click.option('--enum-distinct-max', type=int, default=12,
              help='Max distinct values to emit an sh:in enum (default: 12).')
@click.option('--no-sample-values', 'no_sample_values', is_flag=True, default=False,
              help='Suppress masked example values in shape comments (PII is always masked).')
@click.option('--force', is_flag=True, default=False,
              help='Overwrite an existing draft shapes file.')
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
    from ..core.hub_utils import find_hub_root

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

    # Default output: output/shapes-draft/<name>.ttl (outside model/shapes).
    if out is None:
        name = source_path.name.replace(".vocabulary.ttl", "").replace(".ttl", "")
        out_path = base / "output" / "shapes-draft" / f"{name}.ttl"
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
def coverage_report_cmd(ontology, ref_models, sources, output, out_format):
    """Generate ontology-to-reference-model coverage report.

    Measures how well the domain ontology aligns with industry reference models
    using deterministic matching (rdfs:seeAlso, owl:imports, name matching).
    No LLM or API keys required.

    \b
    Examples:
      kairos-ontology coverage-report
      kairos-ontology coverage-report --format markdown
      kairos-ontology coverage-report --ontology path/to/ontologies/ --ref-models path/to/refs/
    """
    from ..core.coverage_report import (
        run_coverage_report,
        write_coverage_yaml,
        write_coverage_markdown,
    )

    # Auto-detect hub paths
    from ..core.hub_utils import find_hub_root

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
        ref_models_path = _resolve_ref_models_dir(cwd, hub_root)
        if ref_models_path is None:
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
    click.echo()

    try:
        report = run_coverage_report(
            ontology_dir=ont_path,
            ref_models_dir=ref_models_path,
            sources_dir=sources_path,
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


@cli.command(name='generate-inventory')
@click.option('--ontology-dir', type=click.Path(exists=True), default=None,
              help='Path to model/ontologies/ directory (default: auto-detect from hub).')
@click.option('--ref-models-dir', type=click.Path(exists=True), default=None,
              help='Path to ontology-reference-models/ directory (default: auto-detect).')
@click.option('--output-dir', '-o', type=click.Path(), default=None,
              help='Output directory (default: referencemodels-unpacked/).')
@click.option('--prune/--no-prune', default=True,
              help='Remove orphaned inventory files no longer produced by any '
                   'source (default: prune). Self-heals legacy stem-named files.')
def generate_inventory_cmd(ontology_dir, ref_models_dir, output_dir, prune):
    """Generate materialized YAML inventories for ontologies and reference models.

    Produces one YAML file per domain/reference model containing classes, properties,
    and specialization trees (DD-044).  Inventories are consumed by analyse-sources,
    propose-alignment, and coverage-report as a cached alternative to re-parsing TTL.

    Reference-model modules are namespaced by their owning model (DD-054), e.g.
    ``bsp-party-inventory.yaml``, so same-named modules from different models no
    longer overwrite each other.

    Files are written to referencemodels-unpacked/ and should be committed to git.

    \\b
    Examples:
      kairos-ontology generate-inventory
      kairos-ontology generate-inventory --output-dir referencemodels-unpacked/
      kairos-ontology generate-inventory --ref-models-dir path/to/refs/
    """
    from ..core.inventory import (
        generate_inventory,
        inventory_filename,
        iter_reference_inventory_sources,
        write_inventory,
    )
    from ..core.hub_utils import find_hub_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=True)

    # Resolve ontology directory
    if ontology_dir:
        ont_path = Path(ontology_dir)
    elif hub_root:
        ont_path = hub_root / "model" / "ontologies"
    else:
        ont_path = None

    # Resolve reference models directory
    if ref_models_dir:
        ref_path = Path(ref_models_dir)
    else:
        ref_path = _resolve_ref_models_dir(cwd, hub_root)

    if not ont_path and not ref_path:
        click.echo("❌ No ontology or reference model directories found. "
                    "Use --ontology-dir or --ref-models-dir.", err=True)
        raise SystemExit(1)

    # Resolve output directory
    if output_dir:
        out_path = Path(output_dir)
    elif hub_root:
        out_path = hub_root / "referencemodels-unpacked"
    else:
        out_path = Path("referencemodels-unpacked")

    click.echo("📦 Generating materialized inventories")
    written: list[Path] = []

    # Process reference models
    produced_by: dict[str, Path] = {}
    if ref_path and ref_path.is_dir():
        click.echo(f"   Reference models: {ref_path}")
        ref_ttls = iter_reference_inventory_sources(ref_path)
        for ttl_file in ref_ttls:
            try:
                inv = generate_inventory(ttl_file)
                if not inv["classes"]:
                    continue
                stem = ttl_file.stem
                fname = inventory_filename(ttl_file, ref_models_dir=ref_path)
                if fname in produced_by and produced_by[fname] != ttl_file:
                    click.echo(
                        f"   ❌ Inventory name collision: {fname} already written "
                        f"from {produced_by[fname]}; skipping {ttl_file}. "
                        "Report this (DD-054 disambiguation gap).",
                        err=True,
                    )
                    continue
                produced_by[fname] = ttl_file
                yaml_path = out_path / fname
                write_inventory(inv, yaml_path)
                written.append(yaml_path)
                n_classes = len(inv["classes"])
                n_specs = sum(
                    len(c.get("specializations", []))
                    for c in inv["classes"]
                )
                click.echo(
                    f"   ✅ {stem}: {n_classes} classes, {n_specs} specializations"
                )
            except Exception as e:
                click.echo(f"   ⚠ Failed to process {ttl_file.name}: {e}", err=True)

    # Process domain ontologies
    if ont_path and ont_path.is_dir():
        click.echo(f"   Ontologies: {ont_path}")
        ont_ttls = sorted(ont_path.glob("**/*.ttl"))
        for ttl_file in ont_ttls:
            try:
                inv = generate_inventory(ttl_file, include_specializations=False)
                if not inv["classes"]:
                    continue
                stem = ttl_file.stem
                yaml_path = out_path / inventory_filename(ttl_file)
                write_inventory(inv, yaml_path)
                written.append(yaml_path)
                click.echo(f"   ✅ {stem}: {len(inv['classes'])} classes")
            except Exception as e:
                click.echo(f"   ⚠ Failed to process {ttl_file.name}: {e}", err=True)

    if prune and out_path.is_dir():
        produced = {p.name for p in written}
        for existing in sorted(out_path.glob("*-inventory.yaml")):
            if existing.name not in produced:
                existing.unlink()
                click.echo(f"   🧹 Pruned orphaned inventory: {existing.name}")

    click.echo(f"\n✅ Generated {len(written)} inventory file(s) in {out_path}")


@cli.command(name='check-inventory')
@click.option('--ontology-dir', type=click.Path(exists=True), default=None,
              help='Path to model/ontologies/ directory (default: auto-detect from hub).')
@click.option('--ref-models-dir', type=click.Path(exists=True), default=None,
              help='Path to ontology-reference-models/ directory (default: auto-detect).')
@click.option('--inventory-dir', type=click.Path(), default=None,
              help='Path to referencemodels-unpacked/ directory (default: auto-detect).')
@click.option('--strict', is_flag=True, default=False,
              help='Also fail when an inventory cannot be verified (no stored hash).')
@click.option('--warn-only', is_flag=True, default=False,
              help='Report problems but always exit 0 (never block).')
def check_inventory_cmd(ontology_dir, ref_models_dir, inventory_dir, strict, warn_only):
    """Verify that materialized inventories exist and are up to date (DD-047).

    Deterministic pre-flight gate for ``design-domain``: confirms that every source
    TTL has a matching ``referencemodels-unpacked/*-inventory.yaml`` and that the stored
    ``source_sha256`` matches the current file content.  Exits non-zero (blocking)
    when an inventory is **missing** or **stale**, so a modeler never works against
    an out-of-date view of the reference model's specialization tree.

    \\b
    Examples:
      kairos-ontology check-inventory
      kairos-ontology check-inventory --strict
      kairos-ontology check-inventory --warn-only
    """
    from ..core.inventory import check_inventories
    from ..core.hub_utils import find_hub_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=True)

    if ontology_dir:
        ont_path: Path | None = Path(ontology_dir)
    elif hub_root:
        ont_path = hub_root / "model" / "ontologies"
    else:
        ont_path = None

    if ref_models_dir:
        ref_path: Path | None = Path(ref_models_dir)
    else:
        ref_path = _resolve_ref_models_dir(cwd, hub_root)

    if inventory_dir:
        inv_path = Path(inventory_dir)
    elif hub_root:
        inv_path = hub_root / "referencemodels-unpacked"
    else:
        inv_path = Path("referencemodels-unpacked")

    if not ont_path and not ref_path:
        click.echo("❌ No ontology or reference model directories found. "
                   "Use --ontology-dir or --ref-models-dir.", err=True)
        raise SystemExit(1)

    report = check_inventories(
        ontology_dir=ont_path, ref_models_dir=ref_path, inventory_dir=inv_path,
    )

    click.echo("🔎 Checking materialized inventories")
    click.echo(f"   Inventory dir: {inv_path}")
    for stem in report.ok:
        click.echo(f"   ✓ {stem}: up to date")
    for stem in report.missing:
        click.echo(f"   ❌ {stem}: MISSING inventory", err=True)
    for stem in report.stale:
        click.echo(f"   ❌ {stem}: STALE (source changed since generation)", err=True)
    for stem in report.unverifiable:
        click.echo(f"   ⚠ {stem}: cannot verify freshness (no stored hash — regenerate)")
    for name in report.orphan:
        click.echo(f"   ⚠ {name}: orphan inventory (no matching source TTL)")

    blocking = report.is_blocking or (strict and report.unverifiable)

    if blocking and not warn_only:
        click.echo(
            "\n❌ Inventory check failed. Run "
            "`kairos-ontology generate-inventory` and commit the result "
            "before modeling.",
            err=True,
        )
        raise SystemExit(1)

    if report.is_blocking or report.has_warnings:
        click.echo("\n⚠ Inventory check completed with warnings (not blocking).")
    else:
        click.echo("\n✅ Inventories are present and up to date.")


def _autodetect_analysis_dir(cwd: Path, hub_root: Path | None) -> Path | None:
    """Locate the ``_analysis/`` directory holding affinity/alignment reports."""
    for candidate in [
        (hub_root / "integration" / "sources" / "_analysis") if hub_root else None,
        cwd / "integration" / "sources" / "_analysis",
        cwd / "_analysis",
    ]:
        if candidate and candidate.is_dir():
            return candidate
    return None


def _resolve_claims_dir(cwd: Path, hub_root: Path | None) -> Path:
    """Resolve the ``model/claims/`` directory (created on demand by callers)."""
    base = hub_root if hub_root else cwd
    return base / "model" / "claims"


def _resolve_model_path(
    cwd: Path, hub_root: Path | None, *, subdir: str, claims_path: Path | None = None
) -> Path:
    """Resolve a model subdirectory with claims-dir sibling fallback."""
    if hub_root:
        return hub_root / "model" / subdir
    if claims_path and claims_path.parent.name == "model":
        return claims_path.parent / subdir
    return cwd / "model" / subdir


@cli.command(name='migrate-claims')
@click.option('--analysis-dir', type=click.Path(exists=True), default=None,
              help='Directory holding the legacy {domain}-alignment.yaml files '
                   '(default: auto-detect _analysis/).')
@click.option('--domain', 'domain_filter', default=None,
              help='Migrate only this domain (default: every *-alignment.yaml found).')
@click.option('--output', '-o', type=click.Path(), default=None,
              help='Output directory for {domain}-claims.yaml (default: model/claims/).')
@click.option('--inventory-dir', type=click.Path(), default=None,
              help='Path to referencemodels-unpacked/ for URI back-fill '
                   '(default: auto-detect).')
@click.option('--no-resolve-uris', is_flag=True, default=False,
              help='Do not back-fill class_uri/property_uri from the inventory.')
@click.option('--force', is_flag=True, default=False,
              help='Overwrite an existing {domain}-claims.yaml.')
def migrate_claims_cmd(analysis_dir, domain_filter, output, inventory_dir, no_resolve_uris, force):
    """One-way migrate legacy alignment YAML → Claim Registry (DD-EL-1).

    Deterministic, AI-free conversion of each ``{domain}-alignment.yaml`` into a
    ``model/claims/{domain}-claims.yaml`` of ``proposed`` claims, so no prior
    analysis is lost.  The alignment YAML is **not** modified, but is retired:
    downstream commands reject it (run this once and switch to claims).

    Unless ``--no-resolve-uris`` is passed, ``class_uri`` / ``property_uri`` are
    back-filled from the materialized reference-model inventories
    (``referencemodels-unpacked/``) for unambiguously resolvable reference names,
    so anchored claims are approvable without manual URI entry (issue #190).

    \\b
    Examples:
      kairos-ontology migrate-claims
      kairos-ontology migrate-claims --domain party
      kairos-ontology migrate-claims --output model/claims --force
    """
    from ..core.claim_registry import (
        registry_path,
        validate_registry,
        validation_errors,
        write_registry,
    )
    from ..core.hub_utils import find_hub_root
    from ..core.migrate_claims import find_legacy_alignment_files, migrate_alignment_file

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd)

    src_dir = Path(analysis_dir) if analysis_dir else _autodetect_analysis_dir(cwd, hub_root)
    if not src_dir:
        click.echo(
            "❌ Cannot find an _analysis/ directory with alignment files. "
            "Use --analysis-dir.",
            err=True,
        )
        raise SystemExit(1)

    out_dir = Path(output) if output else _resolve_claims_dir(cwd, hub_root)

    inv_dir: Path | None = None
    if not no_resolve_uris:
        if inventory_dir:
            inv_dir = Path(inventory_dir)
        elif hub_root:
            inv_dir = hub_root / "referencemodels-unpacked"
        else:
            candidate = cwd / "referencemodels-unpacked"
            inv_dir = candidate if candidate.is_dir() else None
        if inv_dir and not inv_dir.is_dir():
            inv_dir = None

    legacy = find_legacy_alignment_files(src_dir)
    if domain_filter:
        legacy = [p for p in legacy if p.name == f"{domain_filter}-alignment.yaml"]
    if not legacy:
        click.echo(f"❌ No matching *-alignment.yaml found in {src_dir}", err=True)
        raise SystemExit(1)

    click.echo("🔄 Migrating alignment → Claim Registry")
    click.echo(f"   Source: {src_dir}")
    click.echo(f"   Output: {out_dir}")
    if no_resolve_uris:
        click.echo("   URI back-fill: disabled (--no-resolve-uris)")
    elif inv_dir:
        click.echo(f"   URI back-fill: {inv_dir}")
    else:
        click.echo("   URI back-fill: no inventory found (URIs stay null)")

    exit_code = 0
    for align_file in legacy:
        domain = align_file.name.replace("-alignment.yaml", "")
        target = registry_path(out_dir, domain)
        if target.exists() and not force:
            click.echo(f"   ⚠ {domain}: {target.name} exists; use --force to overwrite "
                       "(skipped)", err=True)
            exit_code = 1
            continue
        try:
            registry = migrate_alignment_file(align_file, inventory_dir=inv_dir)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"   ❌ {domain}: migration failed: {exc}", err=True)
            exit_code = 1
            continue
        errors = validation_errors(validate_registry(registry))
        if errors:
            click.echo(f"   ❌ {domain}: produced an invalid registry:", err=True)
            for issue in errors:
                click.echo(f"      - {issue.message}", err=True)
            exit_code = 1
            continue
        write_registry(registry, target)
        anchored = [c for c in registry.claims if c.disposition in ("claim", "specialize")
                    and c.type in ("class", "property", "reference_data", "measure")]
        resolved = sum(1 for c in anchored if c.identifying_uri())
        uri_note = (
            f" ({resolved}/{len(anchored)} anchored URIs resolved)" if anchored else ""
        )
        click.echo(f"   ✓ {domain}: {len(registry.claims)} claim(s) → {target.name}{uri_note}")

    raise SystemExit(exit_code)


@cli.command(name='decide-claims')
@click.option('--claims-dir', type=click.Path(), default=None,
              help='Path to model/claims/ directory (default: auto-detect).')
@click.option('--domains', 'domains', default=None,
              help='Comma-separated domains to curate (default: every *-claims.yaml).')
@click.option('--status', 'status_filter', default=None,
              help='Only select claims with this status (repeatable via comma).')
@click.option('--disposition', 'disposition_filter', default=None,
              help='Only select claims with this disposition (comma-separated).')
@click.option('--type', 'type_filter', default=None,
              help='Only select claims of this type (comma-separated).')
@click.option('--origin', 'origin_filter', default=None,
              help='Only select claims with this origin (comma-separated).')
@click.option('--id', 'id_globs', multiple=True,
              help='Select claims whose id matches this glob (repeatable).')
@click.option('--column', 'column_globs', multiple=True,
              help='Select claims with an evidence source column matching this glob '
                   '(case-insensitive, repeatable).')
@click.option('--set-status', 'set_status', default=None,
              help='Set every selected claim to this status.')
@click.option('--by-disposition', 'by_disposition', default=None,
              help='Map dispositions to statuses, e.g. '
                   '"claim=approved,passthrough=approved,skip=rejected".')
@click.option('--list', 'list_only', is_flag=True, default=False,
              help='List the selected claims without changing anything.')
@click.option('--dry-run', is_flag=True, default=False,
              help='Show what would change without writing the registry.')
def decide_claims_cmd(claims_dir, domains, status_filter, disposition_filter, type_filter,
                      origin_filter, id_globs, column_globs, set_status, by_disposition,
                      list_only, dry_run):
    """Query and bulk-curate claim ``status`` decisions (issue #190).

    The Claim Registry stays the single git-tracked source of truth — this command
    is the missing **query + bulk-update API** over it. Selected claims are filtered
    by any combination of ``--status`` / ``--disposition`` / ``--type`` / ``--origin``
    plus ``--id`` / ``--column`` globs; ``--list`` just prints matches. To decide,
    pass exactly one of ``--set-status`` or ``--by-disposition``. Only the ``status``
    field changes (along allowed transitions); the registry is written back via the
    canonical serializer, so diffs stay minimal.

    \\b
    Examples:
      kairos-ontology decide-claims --domains party --list --status proposed
      kairos-ontology decide-claims --domains party \\
          --by-disposition claim=approved,passthrough=approved,skip=rejected
      kairos-ontology decide-claims --domains party --disposition claim \\
          --column "*_id" --set-status rejected --dry-run
    """
    from ..core.claim_registry import load_registry, registry_path, write_registry
    from ..core.decide_claims import (
        ClaimSelector,
        apply_decisions,
        parse_by_disposition,
        select_claims,
        validate_filter_values,
    )
    from ..core.hub_utils import find_hub_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd)
    claims_path = Path(claims_dir) if claims_dir else _resolve_claims_dir(cwd, hub_root)

    def _split(value):
        return [v.strip() for v in value.split(",") if v.strip()] if value else None

    status_list = _split(status_filter)
    disposition_list = _split(disposition_filter)
    type_list = _split(type_filter)
    origin_list = _split(origin_filter)

    try:
        validate_filter_values(
            status=status_list,
            disposition=disposition_list,
            type_=type_list,
            origin=origin_list,
        )
        disposition_map = parse_by_disposition(by_disposition) if by_disposition else None
    except ValueError as exc:
        click.echo(f"❌ {exc}", err=True)
        raise SystemExit(2) from exc

    deciding = bool(set_status) or bool(disposition_map)
    if not list_only and not deciding:
        click.echo(
            "❌ Nothing to do: pass --list, or one of --set-status / --by-disposition.",
            err=True,
        )
        raise SystemExit(2)
    if set_status and disposition_map:
        click.echo("❌ Use only one of --set-status or --by-disposition.", err=True)
        raise SystemExit(2)

    domain_names = _split(domains)
    if domain_names:
        registry_files = [registry_path(claims_path, d) for d in domain_names]
        missing = [p for p in registry_files if not p.exists()]
        if missing:
            for path in missing:
                click.echo(f"❌ No claims file: {path}", err=True)
            raise SystemExit(1)
    else:
        registry_files = sorted(claims_path.glob("*-claims.yaml")) if claims_path.is_dir() else []
    if not registry_files:
        click.echo(f"❌ No *-claims.yaml found in {claims_path}", err=True)
        raise SystemExit(1)

    selector = ClaimSelector(
        status=status_list,
        disposition=disposition_list,
        type=type_list,
        origin=origin_list,
        id_globs=list(id_globs),
        column_globs=list(column_globs),
    )

    verb = "Listing" if list_only else ("Previewing (dry-run)" if dry_run else "Deciding")
    click.echo(f"🗳️  {verb} claim decisions")
    click.echo(f"   Registry dir: {claims_path}")

    def _print_summary(domain, summary):
        applied = summary.applied
        skipped = summary.skipped
        blocked = summary.blocked
        block_note = f", {len(blocked)} blocker(s)" if blocked else ""
        click.echo(
            f"   • {domain}: {len(applied)} change(s), {len(skipped)} skipped{block_note}"
        )
        for result in applied:
            click.echo(f"      ✓ {result.claim_id}: {result.from_status} → {result.to_status}")
        for result in skipped:
            marker = "❌" if result.blocking else "⤫"
            click.echo(f"      {marker} {result.claim_id}: {result.reason}")

    loaded = [
        (reg_file.name.replace("-claims.yaml", ""), reg_file, load_registry(reg_file))
        for reg_file in registry_files
    ]

    if list_only:
        for domain, _reg_file, registry in loaded:
            matches = select_claims(registry, selector)
            click.echo(f"   • {domain}: {len(matches)} match(es)")
            for claim in matches:
                click.echo(
                    f"      - {claim.id}  [{claim.type}/{claim.disposition}]  {claim.status}"
                )
        return

    previews = []
    for domain, reg_file, registry in loaded:
        summary = apply_decisions(
            registry,
            selector=selector,
            set_status=set_status or None,
            by_disposition=disposition_map,
            dry_run=True,
        )
        previews.append((domain, reg_file, registry, summary))
        _print_summary(domain, summary)

    if any(summary.blocked for _domain, _reg_file, _registry, summary in previews):
        if dry_run:
            click.echo("ℹ️  Dry run — no files written.")
            return
        click.echo("\n❌ Approval blocked; no files written.")
        raise SystemExit(1)

    total_changed = 0
    if not dry_run:
        for domain, reg_file, registry in loaded:
            # Re-run after the command-wide preflight so only this pass mutates.
            summary = apply_decisions(
                registry,
                selector=selector,
                set_status=set_status or None,
                by_disposition=disposition_map,
                dry_run=False,
            )
            if summary.changed:
                write_registry(registry, reg_file)
                total_changed += len(summary.applied)

    if dry_run:
        click.echo("ℹ️  Dry run — no files written.")
    elif total_changed:
        click.echo(f"✅ Wrote {total_changed} decision(s).")
    else:
        click.echo("ℹ️  No changes applied.")


@cli.command(name='check-claims')
@click.option('--claims-dir', type=click.Path(), default=None,
              help='Path to model/claims/ directory (default: auto-detect).')
@click.option('--analysis-dir', type=click.Path(exists=True), default=None,
              help='Path to _analysis/ directory with affinity reports '
                   '(default: auto-detect).')
@click.option('--sources', type=click.Path(), default=None,
              help='Path to integration/sources/ directory (default: auto-detect).')
@click.option('--mappings', type=click.Path(), default=None,
              help='Path to model/mappings/ directory (default: auto-detect).')
@click.option('--accelerator', default=None,
              help='Accelerator pack whose data-domains.yaml defines domain '
                   'ownership (default: first pack found).')
@click.option('--domains', 'domains_filter', default=None,
              help='Comma-separated domain names to include (case-insensitive substring match).')
@click.option('--no-source-coverage', is_flag=True, default=False,
              help='Skip the pre-silver mapping-coverage check (registry checks only).')
@click.option('--no-extension-sync', is_flag=True, default=False,
              help='Skip Claim Registry ↔ ontology/extension sync checks.')
@click.option('--no-mdm-anchor', is_flag=True, default=False,
              help='Skip the MDM-anchor gate (broad claims need known reference anchors).')
@click.option('--no-ownership', is_flag=True, default=False,
              help='Skip the data-domains.yaml ownership-boundary check.')
@click.option('--strict', is_flag=True, default=False,
              help='Also block when any registry still carries an undecided '
                   '(proposed) claim — i.e. require a fully curated registry.')
@click.option('--warn-only', is_flag=True, default=False,
              help='Report problems but always exit 0 (never block).')
def check_claims_cmd(claims_dir, analysis_dir, sources, mappings, accelerator,
                     domains_filter, no_source_coverage, no_extension_sync,
                     no_mdm_anchor, no_ownership, strict, warn_only):
    """Verify every domain's Claim Registry is valid, complete, and fresh (DD-EL-1).

    The single governance gate (replaces the retired ``check-alignment`` and
    ``check-source-coverage``).  Deterministic and AI-free: it reads the committed
    Claim Registries, affinity reports, source vocabularies, and mapping files.

    For each domain the affinity reports enumerate, it confirms that a
    ``model/claims/{domain}-claims.yaml`` exists, is structurally valid, covers
    **all** of the domain's affinity tables, and is still fresh (its stored
    ``freshness.affinity_sha256`` matches the current affinity table set).  It
    also blocks on cross-file duplicate ``approved`` claims, and — unless
    ``--no-source-coverage`` — on any affinity table not yet mapped (the
    pre-silver check).

    \\b
    Flag precedence:
      (default)             missing/invalid/incomplete/stale/duplicate/unmapped block
      --strict              the above, plus undecided (proposed) claims block
      --no-source-coverage  skip the mapping-coverage portion
      --warn-only           report everything but always exit 0 (overrides --strict)

    \\b
    Examples:
      kairos-ontology check-claims
      kairos-ontology check-claims --domains party,commercial
      kairos-ontology check-claims --strict
      kairos-ontology check-claims --warn-only
    """
    from ..core.analyse_sources import load_data_domains
    from ..core.claim_coverage import check_claims_coverage
    from ..core.hub_utils import find_hub_root
    from ..core.migrate_claims import find_legacy_alignment_files, legacy_alignment_error
    from ..core.source_coverage import check_source_coverage

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd)

    if analysis_dir:
        analysis_path: Path | None = Path(analysis_dir)
    else:
        analysis_path = _autodetect_analysis_dir(cwd, hub_root)

    if not analysis_path:
        click.echo(
            "❌ Cannot find _analysis/ directory with affinity reports. "
            "Run 'kairos-ontology analyse-sources' first, or use --analysis-dir.",
            err=True,
        )
        raise SystemExit(1)

    # No dual path (DD-EL-1): a hub that still carries legacy alignment YAML must
    # migrate first. This is a hard error even under --warn-only.
    legacy = find_legacy_alignment_files(analysis_path)
    if legacy:
        click.echo(
            "❌ Legacy alignment files found — the alignment YAML is retired "
            "(DD-EL-1). Migrate before checking claims:",
            err=True,
        )
        for path in legacy:
            click.echo(f"   • {legacy_alignment_error(path)}", err=True)
        raise SystemExit(1)

    claims_path = Path(claims_dir) if claims_dir else _resolve_claims_dir(cwd, hub_root)

    if sources:
        sources_path = Path(sources)
    elif hub_root:
        sources_path = hub_root / "integration" / "sources"
    else:
        sources_path = cwd / "integration" / "sources"

    if mappings:
        mappings_path = Path(mappings)
    else:
        mappings_path = _resolve_model_path(
            cwd, hub_root, subdir="mappings", claims_path=claims_path
        )

    ontologies_path = _resolve_model_path(
        cwd, hub_root, subdir="ontologies", claims_path=claims_path
    )
    extensions_path = _resolve_model_path(
        cwd, hub_root, subdir="extensions", claims_path=claims_path
    )

    filter_list = None
    if domains_filter:
        filter_list = [d.strip() for d in domains_filter.split(",") if d.strip()]

    # Domain ownership baseline (data-domains.yaml). Best-effort: when no
    # reference models are resolvable, ownership is simply not checked.
    data_domains: dict[str, object] | None = None
    ref_models_dir = _resolve_ref_models_dir(cwd, hub_root)
    if ref_models_dir:
        loaded = load_data_domains(ref_models_dir, accelerator=accelerator)
        if loaded:
            data_domains = dict(loaded)

    report = check_claims_coverage(
        claims_dir=claims_path,
        analysis_dir=analysis_path,
        data_domains=data_domains,
        domains_filter=filter_list,
        check_mdm_anchor=not no_mdm_anchor,
        check_ownership=not no_ownership,
    )

    click.echo("🔎 Checking Claim Registry coverage")
    click.echo(f"   Claims dir:   {claims_path}")
    click.echo(f"   Analysis dir: {analysis_path}")
    for domain in report.ok:
        click.echo(f"   ✓ {domain}: valid, complete, and up to date")
    for domain in report.missing:
        gaps = report.uncovered_tables.get(domain, [])
        click.echo(f"   ❌ {domain}: MISSING claims ({len(gaps)} table(s) "
                   "unclaimed)", err=True)
    for domain in sorted(report.invalid):
        click.echo(f"   ❌ {domain}: INVALID registry:", err=True)
        for msg in report.invalid[domain][:10]:
            click.echo(f"        - {msg}", err=True)
        if len(report.invalid[domain]) > 10:
            click.echo(f"        … and {len(report.invalid[domain]) - 10} more", err=True)
    for domain in report.incomplete:
        gaps = report.uncovered_tables.get(domain, [])
        click.echo(f"   ❌ {domain}: INCOMPLETE — {len(gaps)} affinity table(s) "
                   "not in coverage", err=True)
        for tbl in gaps[:10]:
            click.echo(f"        • {tbl}", err=True)
        if len(gaps) > 10:
            click.echo(f"        … and {len(gaps) - 10} more", err=True)
    for domain in report.stale:
        click.echo(f"   ❌ {domain}: STALE (affinity tables changed since the "
                   "registry was generated)", err=True)
    for domain in report.unverifiable:
        click.echo(f"   ⚠ {domain}: cannot verify freshness (no stored hash — "
                   "regenerate with propose-alignment)")
    for name in report.orphan:
        click.echo(f"   ⚠ {name}: orphan registry (no matching affinity domain)")
    for name in report.unowned:
        click.echo(f"   ⚠ {name}: registry domain not found in data-domains.yaml "
                   "(ownership unverified)")

    if report.duplicate_approved:
        click.echo(
            f"\n⛔ Duplicate approved claims ({len(report.duplicate_approved)}):",
            err=True,
        )
        for dup in report.duplicate_approved[:15]:
            click.echo(
                f"   • {dup.uri}: {dup.first} and {dup.second}", err=True
            )
        click.echo(
            "   → Two domains approved the same URI. Deduplicate before modeling.",
            err=True,
        )

    if report.anchor_pending:
        click.echo(
            f"\n⛔ MDM anchors undecided ({len(report.anchor_pending)} domain(s)):",
            err=True,
        )
        for domain in sorted(report.anchor_pending):
            ids = report.anchor_pending[domain]
            click.echo(
                f"   • {domain}: {len(ids)} anchor(s) still proposed "
                f"while broad claims are approved", err=True,
            )
            for cid in ids[:10]:
                click.echo(f"        - {cid}", err=True)
        click.echo(
            "   → Decide (approve/defer) the domain's MDM/reference anchors "
            "before approving broad claims (§5.4).",
            err=True,
        )

    if report.deviation_missing:
        click.echo(
            f"\n⛔ Deviation log incomplete ({len(report.deviation_missing)} "
            "domain(s)):", err=True,
        )
        for domain in sorted(report.deviation_missing):
            ids = report.deviation_missing[domain]
            click.echo(
                f"   • {domain}: {len(ids)} approved gap (client-native) claim(s) "
                "lack a deviation record", err=True,
            )
            for cid in ids[:10]:
                click.echo(f"        - {cid}", err=True)
        click.echo(
            "   → Add a deviation (owner + reason) to every client-native gap "
            "claim (§12).", err=True,
        )

    if report.ownership_conflicts:
        click.echo(
            f"\n⛔ Ownership conflicts ({len(report.ownership_conflicts)}):",
            err=True,
        )
        for conf in report.ownership_conflicts[:15]:
            click.echo(
                f"   • {conf.domain}:{conf.claim_id} approves {conf.uri} "
                f"owned by {', '.join(conf.owners)}", err=True,
            )
        click.echo(
            "   → Move the claim to its owning domain, or add an "
            "ownership_override (owner + rationale) to document the exception.",
            err=True,
        )

    if report.anchor_missing:
        click.echo(
            f"\n⚠ MDM anchors not declared ({len(report.anchor_missing)} domain(s)):"
        )
        for domain in sorted(report.anchor_missing):
            click.echo(
                f"   • {domain}: broad class claims approved but no mdm_anchor "
                "reference-data claim declared"
            )
        click.echo(
            "   → Identify the domain's major reference anchors "
            "(conformed dimensions / code lists / natural keys)."
        )
        click.echo(
            "   → Declare each as a reference_data claim with mdm_anchor: true, e.g.\n"
            "        - id: <domain>-<anchor>\n"
            "          type: reference_data\n"
            "          disposition: claim\n"
            "          mdm_anchor: true\n"
            "          class_uri: <reference class URI>\n"
            "          reference_data: {authority_system: <MDM>, key: <natural key>}\n"
            "     then approve it. See the kairos-design-domain skill (MDM anchors) "
            "or pass --no-mdm-anchor to skip this gate."
        )

    if report.shared_dimensions:
        click.echo(
            f"\n⚠ Shared conformed dimensions ({len(report.shared_dimensions)}) — "
            "approved in multiple domains with a documented override:"
        )
        for dup in report.shared_dimensions[:15]:
            click.echo(f"   • {dup.uri}: {dup.first} and {dup.second}")

    if report.passthrough_review:
        total = sum(len(v) for v in report.passthrough_review.values())
        click.echo(
            f"\n⚠ Passthrough fields awaiting promotion review ({total}):"
        )
        for domain in sorted(report.passthrough_review):
            ids = report.passthrough_review[domain]
            click.echo(f"   • {domain}: {len(ids)} high-use passthrough claim(s)")
            for cid in ids[:10]:
                click.echo(f"        - {cid}")
        click.echo(
            "   → Review for promotion to a modeled property, or mark "
            "passthrough_reviewed: true (§11.2)."
        )

    if report.proposed_counts:
        click.echo(
            f"\n🧩 Undecided claims ({report.total_proposed}) — awaiting human "
            "decision:"
        )
        for domain in sorted(report.proposed_counts):
            click.echo(f"   • {domain}: {report.proposed_counts[domain]} proposed claim(s)")
        click.echo(
            "   → Approve / reject / defer each in the registry "
            "(pass --strict to block until curated)."
        )

    # Pre-silver mapping coverage (former check-source-coverage). Reuses the same
    # backend; no double path.
    source_blocking = False
    if not no_source_coverage:
        src_report = check_source_coverage(
            analysis_dir=analysis_path,
            sources_dir=sources_path,
            mappings_dir=mappings_path,
            domains_filter=filter_list,
            claims_dir=claims_path,
            extensions_dir=extensions_path,
            hub_root=hub_root or cwd,
            transforms_dir=(hub_root or cwd) / "integration" / "transforms" / "dbt",
        )
        click.echo("\n🔎 Checking source-to-domain mapping coverage")
        click.echo(f"   Sources:  {sources_path}")
        click.echo(f"   Mappings: {mappings_path}")
        for domain in sorted(src_report.domain_counts):
            covered, total = src_report.domain_counts[domain]
            gaps = src_report.uncovered.get(domain, [])
            if not gaps:
                replacements = src_report.replacement_counts.get(domain, 0)
                if replacements:
                    direct = src_report.direct_counts.get(domain, 0)
                    click.echo(
                        f"   ✓ {domain}: {covered}/{total} tables mapped "
                        f"({direct} direct, {replacements} governed replacement)"
                    )
                else:
                    click.echo(
                        f"   ✓ {domain}: {covered}/{total} tables mapped "
                        f"({src_report.coverage_pct(domain):.0f}%)"
                    )
            else:
                click.echo(f"   ❌ {domain}: {covered}/{total} tables mapped "
                           f"({src_report.coverage_pct(domain):.0f}%) — "
                           f"{len(gaps)} unmapped", err=True)
                for tbl in gaps[:10]:
                    click.echo(f"        • {tbl}", err=True)
                if len(gaps) > 10:
                    click.echo(f"        … and {len(gaps) - 10} more", err=True)
            for diagnostic in src_report.diagnostics.get(domain, []):
                click.echo(f"        ⛔ {diagnostic}", err=True)
        source_blocking = src_report.is_blocking
        if source_blocking and not warn_only:
            click.echo(
                f"\n❌ Source-coverage check failed: {src_report.total_uncovered} "
                "affinity table(s) are uncovered or have conflicting source authority. "
                "Complete mappings and governed replacement evidence before running silver.",
                err=True,
            )

    sync_blocking = False
    if not no_extension_sync and ontologies_path.is_dir():
        from ..core.claim_projection_sync import evaluate_projection_sync

        sync_report = evaluate_projection_sync(
            claims_dir=claims_path,
            ontologies_dir=ontologies_path,
            extensions_dir=extensions_path,
            domains_filter=filter_list,
        )
        click.echo("\n🔎 Checking claim↔projection sync")
        click.echo(f"   Ontologies: {ontologies_path}")
        click.echo(f"   Extensions: {extensions_path}")
        for domain_sync in sync_report.domains:
            if domain_sync.in_sync:
                click.echo(f"   ✓ {domain_sync.domain}: claims/imports/includes in sync")
                continue
            click.echo(f"   ❌ {domain_sync.domain}: sync drift detected", err=True)
            if domain_sync.error:
                click.echo(f"      - {domain_sync.error}", err=True)
            for iri in domain_sync.missing_imports[:10]:
                click.echo(f"      - missing owl:imports: {iri}", err=True)
            for iri in domain_sync.extra_imports[:10]:
                click.echo(f"      - extra owl:imports: {iri}", err=True)
            for iri in domain_sync.missing_includes[:10]:
                click.echo(f"      - missing silverInclude: {iri}", err=True)
            for iri in domain_sync.extra_includes[:10]:
                click.echo(f"      - extra silverInclude: {iri}", err=True)
            if domain_sync.has_bulk_include_imports:
                click.echo("      - silverIncludeImports bulk flag must be removed", err=True)
        sync_blocking = sync_report.is_blocking
        if sync_blocking and not warn_only:
            click.echo(
                "\n❌ Claim/projection sync check failed. Run "
                "`kairos-ontology claims-to-silver-ext` and commit the generated "
                "ontology/extension changes before projecting.",
                err=True,
            )

    strict_block = strict and report.has_undecided_claims()
    should_block = (
        report.is_blocking or source_blocking or sync_blocking or strict_block
    ) and not warn_only

    if report.is_blocking and not warn_only:
        click.echo(
            "\n❌ Claim check failed. Run "
            "`kairos-ontology propose-alignment` (no domain filter), curate the "
            "registry, and commit it before modeling.",
            err=True,
        )
    if strict_block and not warn_only:
        click.echo(
            "\n❌ Strict check failed: undecided (proposed) claims remain. Approve, "
            "reject, or defer every claim before completing the domain.",
            err=True,
        )
    if should_block:
        raise SystemExit(1)

    if report.is_blocking or report.has_warnings or source_blocking or sync_blocking:
        click.echo("\n⚠ Claim check completed with warnings (not blocking).")
    else:
        click.echo("\n✅ Claims are valid, complete, and up to date.")


@cli.command(name='claims-to-silver-ext')
@click.option('--claims-dir', type=click.Path(), default=None,
              help='Path to model/claims/ directory (default: auto-detect).')
@click.option('--ontologies', type=click.Path(), default=None,
              help='Path to model/ontologies/ directory (default: auto-detect).')
@click.option('--extensions', type=click.Path(), default=None,
              help='Path to model/extensions/ directory (default: auto-detect).')
@click.option('--domains', 'domains_filter', default=None,
              help='Comma-separated domain names to include (case-insensitive substring match).')
@click.option('--check-only', is_flag=True, default=False,
              help='Report drift only (exit 1 when out of sync, no writes).')
@click.option('--no-scaffold', is_flag=True, default=False,
              help='Do not bootstrap missing {domain}.ttl / *-silver-ext.ttl skeletons.')
def claims_to_silver_ext_cmd(claims_dir, ontologies, extensions, domains_filter, check_only,
                             no_scaffold):
    """Generate projection-facing imports/includes from approved claims (Slice 2).

    A1 authority: approved imported class claims deterministically drive:
    1) domain ontology ``owl:imports``, and 2) per-class
    ``kairos-ext:silverInclude`` in ``*-silver-ext.ttl``.

    Unless ``--check-only`` or ``--no-scaffold`` is passed, a minimal valid skeleton
    is created for any domain whose ``{domain}.ttl`` / ``{domain}-silver-ext.ttl`` is
    missing, so a fresh domain bootstraps instead of silently writing nothing
    (issue #190).
    """
    from ..core.claim_projection_sync import (
        apply_projection_sync,
        evaluate_projection_sync,
        scaffold_missing_surfaces,
    )
    from ..core.hub_utils import find_hub_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd)
    claims_path = Path(claims_dir) if claims_dir else _resolve_claims_dir(cwd, hub_root)
    ontologies_path = (
        Path(ontologies)
        if ontologies
        else _resolve_model_path(cwd, hub_root, subdir="ontologies", claims_path=claims_path)
    )
    extensions_path = (
        Path(extensions)
        if extensions
        else _resolve_model_path(cwd, hub_root, subdir="extensions", claims_path=claims_path)
    )

    filter_list = None
    if domains_filter:
        filter_list = [d.strip() for d in domains_filter.split(",") if d.strip()]

    click.echo("🔄 Claim-driven projection sync")
    click.echo(f"   Claims:     {claims_path}")
    click.echo(f"   Ontologies: {ontologies_path}")
    click.echo(f"   Extensions: {extensions_path}")

    if check_only:
        report = evaluate_projection_sync(
            claims_dir=claims_path,
            ontologies_dir=ontologies_path,
            extensions_dir=extensions_path,
            domains_filter=filter_list,
        )
    else:
        if not no_scaffold:
            created = scaffold_missing_surfaces(
                claims_dir=claims_path,
                ontologies_dir=ontologies_path,
                extensions_dir=extensions_path,
                domains_filter=filter_list,
            )
            for path in created:
                click.echo(f"   🆕 scaffolded skeleton: {path.name}")
        report = apply_projection_sync(
            claims_dir=claims_path,
            ontologies_dir=ontologies_path,
            extensions_dir=extensions_path,
            domains_filter=filter_list,
            scaffold_missing=False,
        )

    if not report.domains:
        click.echo("   ⏭ No claims registries found in scope.")
        raise SystemExit(0)

    for domain_sync in report.domains:
        if domain_sync.in_sync:
            click.echo(f"   ✓ {domain_sync.domain}: in sync")
            continue
        click.echo(f"   ❌ {domain_sync.domain}: drift remains", err=True)
        if domain_sync.error:
            click.echo(f"      - {domain_sync.error}", err=True)
        for iri in domain_sync.missing_imports[:10]:
            click.echo(f"      - missing owl:imports: {iri}", err=True)
        for iri in domain_sync.extra_imports[:10]:
            click.echo(f"      - extra owl:imports: {iri}", err=True)
        for iri in domain_sync.missing_includes[:10]:
            click.echo(f"      - missing silverInclude: {iri}", err=True)
        for iri in domain_sync.extra_includes[:10]:
            click.echo(f"      - extra silverInclude: {iri}", err=True)
        if domain_sync.has_bulk_include_imports:
            click.echo("      - silverIncludeImports bulk flag must be removed", err=True)

    if report.is_blocking:
        raise SystemExit(1)
    click.echo("✅ Claim-driven projection surfaces are in sync.")


@cli.command(name='derive-claims')
@click.option('--claims-dir', type=click.Path(), default=None,
              help='Path to model/claims/ directory (default: auto-detect).')
@click.option('--analysis-dir', type=click.Path(), default=None,
              help='Path to _analysis/ directory with affinity reports (default: auto-detect).')
@click.option('--mappings', type=click.Path(), default=None,
              help='Path to model/mappings/ directory with SKOS mappings (default: auto-detect).')
@click.option('--tmdl-dir', type=click.Path(), default=None,
              help='Path to import-tmdl concept-mapping output '
                   '(default: integration/sources/powerbi/).')
@click.option('--domains', 'domains_filter', default=None,
              help='Comma-separated domain names to include (case-insensitive substring match).')
@click.option('--max-workers', type=int, default=8,
              help='Max concurrent per-domain aggregations (default: 8; use 1 for serial).')
@click.option('--force', is_flag=True, default=False,
              help='Bypass the sidecar cache and re-aggregate every domain.')
@click.option('--quiet', '-q', is_flag=True, default=False,
              help='Suppress per-domain progress output (errors still shown).')
def derive_claims_cmd(claims_dir, analysis_dir, mappings, tmdl_dir, domains_filter,
                      max_workers, force, quiet):
    """Aggregate multi-source evidence into candidate claims (DD-EL-5).

    Deterministic and **AI-free**: the semantic LLM work already happened upstream
    in ``analyse-sources`` (affinity) and ``propose-alignment`` (column→property,
    which already writes ``{domain}-claims.yaml``).  This command is the
    deterministic merge/enrich layer that joins those outputs with affinity, TMDL
    concept-mapping, SKOS mapping, and sample-shape evidence — attaching **multiple
    ``evidence_sources`` per claim** so each candidate is traceable.

    \\b
    Every derived/new claim is ``proposed`` — never auto-``approved`` (the C4
    guard).  Human decisions survive re-runs (decided claims keep their curated
    fields; their evidence is refreshed).  Run it after ``propose-alignment`` and
    before human curation / approval.

    \\b
    Examples:
      kairos-ontology derive-claims
      kairos-ontology derive-claims --domains "client,invoice"
      kairos-ontology derive-claims --max-workers 1 --force
    """
    from ..core.derive_claims import run_derive_claims
    from ..core.hub_utils import find_hub_root

    _warn_if_no_skill_context("derive-claims")

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd)

    claims_path = Path(claims_dir) if claims_dir else _resolve_claims_dir(cwd, hub_root)
    if not claims_path.is_dir():
        click.echo(
            f"❌ No claims directory at {claims_path}. Run propose-alignment "
            "(or migrate-claims) first.",
            err=True,
        )
        raise SystemExit(1)

    analysis_path = (
        Path(analysis_dir) if analysis_dir else _autodetect_analysis_dir(cwd, hub_root)
    )
    mappings_path = (
        Path(mappings) if mappings
        else _resolve_model_path(cwd, hub_root, subdir="mappings", claims_path=claims_path)
    )
    if tmdl_dir:
        tmdl_path = Path(tmdl_dir)
    else:
        base = hub_root if hub_root else cwd
        tmdl_path = base / "integration" / "sources" / "powerbi"

    filters = [f for f in (domains_filter.split(",") if domains_filter else []) if f.strip()]

    if not quiet:
        click.echo("🧩 Deriving candidate claims (deterministic, AI-free)")
        click.echo(f"   Claims:   {claims_path}")
        click.echo(f"   Affinity: {analysis_path if analysis_path else '(none)'}")
        click.echo(f"   Mappings: {mappings_path if mappings_path.is_dir() else '(none)'}")
        click.echo(f"   TMDL:     {tmdl_path if tmdl_path.is_dir() else '(none)'}")

    # The per-domain aggregation is CPU-light and the file readers are shared, so
    # the bounded pool mostly future-proofs large hubs; correctness is identical
    # for any --max-workers (deterministic, input-ordered).
    report = run_derive_claims(
        claims_path,
        analysis_dir=analysis_path,
        mappings_dir=mappings_path,
        tmdl_dir=tmdl_path,
        domains_filter=filters,
        max_workers=max_workers,
        force=force,
        write=True,
    )

    if not report.domain_stats:
        click.echo("⚠ No matching {domain}-claims.yaml found to enrich.", err=True)
        raise SystemExit(1)

    for stats in report.domain_stats:
        if not quiet:
            click.echo(
                f"   ✓ {stats.domain}: +{stats.evidence_added} evidence, "
                f"+{stats.new_claims} new candidate(s) "
                f"({stats.total_claims} claim(s) total"
                + (f", {stats.conflicts} conflict(s)" if stats.conflicts else "")
                + (f", {stats.unrouted_tmdl} unrouted TMDL" if stats.unrouted_tmdl else "")
                + ")"
            )
    click.echo(
        f"✅ Derived claims for {len(report.domain_stats)} domain(s): "
        f"+{report.total_evidence_added} evidence, +{report.total_new_claims} new candidate(s). "
        "All candidates are 'proposed' — review and approve before projecting."
    )


@cli.command(name='draft-model-report')
@click.option('--claims-dir', type=click.Path(), default=None,
              help='Path to model/claims/ directory (default: auto-detect when present).')
@click.option('--analysis-dir', type=click.Path(), default=None,
              help='Path to _analysis/ directory with affinity reports (default: auto-detect).')
@click.option('--mappings', type=click.Path(), default=None,
              help='Path to model/mappings/ directory with SKOS mappings (default: auto-detect).')
@click.option('--tmdl-dir', type=click.Path(), default=None,
              help='Path to import-tmdl output (default: integration/sources/powerbi/).')
@click.option('--glossary-dir', type=click.Path(), default=None,
              help='Path to business-discovery glossary TTL directory (default: businessdiscovery/).')
@click.option('--output', '-o', type=click.Path(), default=None,
              help='Output directory (default: model/planning/draft-model/).')
@click.option('--domains', 'domains_filter', default=None,
              help='Comma-separated domain names to include (case-insensitive substring match).')
@click.option('--contract', type=click.Path(), default=None,
              help='Planning-only data-product contract YAML to scope the report.')
@click.option('--data-product', default=None,
              help='Data product name; loads model/planning/data-products/<name>/contract.yaml.')
def draft_model_report_cmd(
    claims_dir,
    analysis_dir,
    mappings,
    tmdl_dir,
    glossary_dir,
    output,
    domains_filter,
    contract,
    data_product,
):
    """Create advisory draft domain-model evidence packs and a cross-domain ERD.

    The report extends the claim-extraction evidence workflow with richer
    TMDL/reporting context, but it is read-only: it never approves claims, writes
    ontology TTL, or acts as projection authority.
    """
    from ..core.draft_model_report import build_draft_model_report, write_draft_model_report
    from ..core.hub_utils import find_hub_root

    _warn_if_no_skill_context("draft-model-report")

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd)
    base = hub_root if hub_root else cwd

    claims_path = Path(claims_dir) if claims_dir else _resolve_claims_dir(cwd, hub_root)
    analysis_path = (
        Path(analysis_dir) if analysis_dir else _autodetect_analysis_dir(cwd, hub_root)
    )
    mappings_path = (
        Path(mappings)
        if mappings
        else _resolve_model_path(cwd, hub_root, subdir="mappings", claims_path=claims_path)
    )
    tmdl_path = Path(tmdl_dir) if tmdl_dir else base / "integration" / "sources" / "powerbi"
    glossary_path = Path(glossary_dir) if glossary_dir else base / "businessdiscovery"
    contract_path = Path(contract) if contract else None
    if data_product and not contract_path:
        contract_path = (
            base / "model" / "planning" / "data-products" / data_product / "contract.yaml"
        )
    if contract_path and not contract_path.exists():
        raise click.ClickException(f"Data-product contract not found: {contract_path}")
    if output:
        output_path = Path(output)
    elif contract_path:
        output_path = contract_path.parent
    else:
        output_path = base / "model" / "planning" / "draft-model"
    filters = [f for f in (domains_filter.split(",") if domains_filter else []) if f.strip()]

    click.echo("🧭 Building advisory draft model report")
    click.echo(f"   Claims:   {claims_path if claims_path.is_dir() else '(none)'}")
    click.echo(f"   Affinity: {analysis_path if analysis_path else '(none)'}")
    click.echo(f"   Mappings: {mappings_path if mappings_path.is_dir() else '(none)'}")
    click.echo(f"   TMDL:     {tmdl_path if tmdl_path.is_dir() else '(none)'}")
    click.echo(f"   Glossary: {glossary_path if glossary_path.exists() else '(none)'}")
    if contract_path:
        click.echo(f"   Product:  {contract_path}")

    try:
        report = build_draft_model_report(
            claims_dir=claims_path if claims_path.is_dir() else None,
            analysis_dir=analysis_path,
            mappings_dir=mappings_path if mappings_path.is_dir() else None,
            tmdl_dir=tmdl_path if tmdl_path.is_dir() else None,
            glossary_dir=glossary_path if glossary_path.exists() else None,
            domains_filter=filters,
            data_product_contract_path=contract_path,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    artifacts = write_draft_model_report(report, output_path)

    click.echo(f"   ✓ summary: {artifacts.summary_yaml}")
    click.echo(f"   ✓ report:  {artifacts.markdown}")
    click.echo(f"   ✓ ERD:     {artifacts.mermaid}")
    if report.get("artifact") == "data-product-draft-model-report":
        click.echo(
            "✅ Data-product vertical-slice plan for "
            f"{report['product']} across {report['summary']['domains']} domain(s)."
        )
    else:
        click.echo(f"✅ Draft model evidence packs for {report['summary']['domains']} domain(s).")


@cli.command(name='discovery-status')
@click.option('--import-dir', type=click.Path(), default=None,
              help='Path to .import/businessdiscovery/ (default: auto-detect from hub).')
@click.option('--extraction-dir', type=click.Path(), default=None,
              help='Path to businessdiscovery/_extractions/ (default: auto-detect from hub).')
@click.option('--strict', is_flag=True, default=False,
              help='Exit non-zero when documents are new (unprocessed) or changed.')
@click.option('--warn-only', is_flag=True, default=False,
              help='Report status but always exit 0 (never block).')
def discovery_status_cmd(import_dir, extraction_dir, strict, warn_only):
    """Report which business-discovery documents are unprocessed or changed (DD-060).

    Deterministic, AI-free helper for the ``design-discovery`` skill: scans the raw
    artifacts in ``.import/businessdiscovery/`` and compares each against its
    per-document extraction file under ``businessdiscovery/_extractions/`` using the
    stored ``source_sha256``.  The skill uses this to process only **new** or
    **changed** documents on a rerun instead of re-reading everything.

    Informational by default (exit 0).  Pass ``--strict`` to exit non-zero when
    there is work to do (new or changed documents).

    \\b
    Examples:
      kairos-ontology discovery-status
      kairos-ontology discovery-status --strict
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

    click.echo("🔎 Checking business-discovery documents")
    click.echo(f"   Import dir:     {imp_path}")
    click.echo(f"   Extraction dir: {ext_path}")

    if not imp_path.is_dir():
        click.echo(
            "   ⚠ No .import/businessdiscovery/ directory found — nothing to process.")
        return

    for name in report.ok:
        click.echo(f"   ✓ {name}: up to date")
    for name in report.unprocessed:
        click.echo(f"   ➕ {name}: NEW (not yet processed)")
    for name in report.changed:
        click.echo(f"   ♻ {name}: CHANGED since last extraction")
    for name in report.unverifiable:
        click.echo(f"   ⚠ {name}: cannot verify freshness (no stored hash — reprocess)")
    for name in report.orphan:
        click.echo(f"   ⚠ {name}: orphan extraction (no matching source document)")

    if report.has_work and strict and not warn_only:
        click.echo(
            "\n❌ Discovery documents need processing. Run the "
            "kairos-design-discovery skill to extract new/changed documents.",
            err=True,
        )
        raise SystemExit(1)

    if report.has_work:
        n = len(report.unprocessed) + len(report.changed)
        click.echo(f"\n⚠ {n} document(s) need processing (run kairos-design-discovery).")
    elif report.has_warnings:
        click.echo("\n⚠ Discovery documents checked with warnings (not blocking).")
    else:
        click.echo("\n✅ All discovery documents are processed and up to date.")


@cli.group(name='discovery-conformance')
def discovery_conformance():
    """Core Concepts Conformance helpers for the design-discovery skill (DD-090).

    Deterministic, machine-output helpers that load the archetype + discovery contract
    from a reference-models checkout (>= v1.11.0), derive relationship topology, and
    validate the conformance artifact.  The interactive interview itself is driven by the
    **kairos-design-discovery** skill — these subcommands give it clean JSON/YAML to work
    from.  All human-readable progress goes to **stderr**; stdout is machine output only.
    """


def _resolve_conformance_root(refmodels_root):
    """Resolve the reference-models root for conformance commands, exiting on failure."""
    from ..core.archetype_loader import ArchetypeError, resolve_refmodels_root
    from ..core.hub_utils import find_hub_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=False)
    try:
        return resolve_refmodels_root(explicit=refmodels_root, cwd=cwd, hub_root=hub_root)
    except ArchetypeError as exc:
        click.echo(f"❌ {exc}", err=True)
        raise SystemExit(2) from exc


def _emit(payload, output_format):
    """Write *payload* to stdout as clean JSON or YAML (no diagnostics mixed in)."""
    if output_format == "yaml":
        import yaml

        click.echo(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), nl=False)
    else:
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False))


_FORMAT_OPTION = click.option(
    '--format', 'output_format', type=click.Choice(['json', 'yaml']), default='json',
    help='Machine-output format on stdout (default: json).')
_REFMODELS_OPTION = click.option(
    '--refmodels-root', 'refmodels_root', type=click.Path(), default=None,
    help='Reference-models checkout (default: $KAIROS_REFMODELS_ROOT or sibling scan).')


@discovery_conformance.command(name='list-archetypes')
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


@discovery_conformance.command(name='load')
@click.option('--archetype', 'archetype_id', required=True, help='Archetype id to load.')
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
    from ..core.archetype_topology import derive_archetype_topology

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

    topology = derive_archetype_topology(root, archetype)
    drift = check_version_drift(archetype, root)

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
        "discovery_doc": str(discovery_doc) if discovery_doc else None,
        "ref_model_modules": [
            {"iri": m.iri, "tier": m.tier} for m in archetype.ref_model_modules
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
        "warnings": drift + topology.warnings(),
    }
    _emit(payload, output_format)


@discovery_conformance.command(name='validate')
@click.option('--file', 'artifact_file', type=click.Path(), default=None,
              help='Conformance artifact (default: <hub>/integration/discovery/'
                   'core-concepts-conformance.yaml).')
@_REFMODELS_OPTION
def conformance_validate(artifact_file, refmodels_root):
    """Validate a conformance artifact against the shared outcome-codes enum."""
    from ..core.archetype_loader import load_outcome_codes
    from ..core.conformance_artifact import (
        ARTIFACT_RELPATH,
        ConformanceArtifactError,
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

    errors = validate_artifact(artifact, load_outcome_codes(root))
    if errors:
        click.echo(f"❌ Conformance artifact invalid ({len(errors)} error(s)):", err=True)
        for e in errors:
            click.echo(f"   • {e}", err=True)
        raise SystemExit(1)
    click.echo(f"✅ Conformance artifact valid: {path}", err=True)


@cli.command(name='status')
@click.option('--hub', 'hub_path', type=click.Path(), default=None,
              help='Path to the ontology-hub root (default: auto-detect).')
@click.option('--format', 'output_format',
              type=click.Choice(['text', 'json', 'markdown']), default='text',
              help='Output format. `markdown` emits the scan-derived block for '
                   '.kairos-state/status.md.')
def status_cmd(hub_path, output_format):
    """Report the deterministic lifecycle status of an ontology hub (DD-080).

    Deterministic, AI-free helper for the ``kairos-flow`` orchestrator and the
    ``kairos-diagnose-status`` skill.  Scans committed hub artifacts and reports,
    per lifecycle phase and per instance, an objective state
    (``not-started`` / ``in-progress`` / ``done``).  This is the *objective*
    layer; continuation context (open questions, decisions, intent) lives in the
    markdown layer under ``ontology-hub/.kairos-state/``.

    \\b
    Examples:
      kairos-ontology status
      kairos-ontology status --format json
      kairos-ontology status --format markdown
    """
    import datetime as _dt
    from ..core.status import scan_hub_status, render_markdown
    from ..core.hub_utils import find_hub_root

    if hub_path:
        hub_root = Path(hub_path)
    else:
        hub_root = find_hub_root(Path.cwd(), require_model=False)

    if not hub_root or not hub_root.is_dir():
        click.echo("❌ Could not locate an ontology-hub root. Pass --hub <path>.", err=True)
        raise SystemExit(1)

    status = scan_hub_status(hub_root, toolkit_version=_toolkit_version)

    if output_format == 'json':
        click.echo(json.dumps(status.to_dict(), indent=2))
        return

    if output_format == 'markdown':
        stamped = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds')
        click.echo(render_markdown(status, last_scanned_at=stamped))
        return

    icons = {"done": "✅", "in-progress": "🟡", "not-started": "⬜"}
    click.echo(f"🔎 Hub lifecycle status: {hub_root}")
    for p in status.phases:
        icon = icons.get(p.state, "")
        done = sum(1 for i in p.instances if i.state == 'done')
        total = len(p.instances)
        suffix = f" ({done}/{total})" if total else ""
        click.echo(f"   {icon} {p.phase:<10} {p.state}{suffix}")
        for inst in p.instances:
            if inst.state != 'done':
                click.echo(f"        - {inst.name}: {inst.state} ({inst.detail})")
    nxt = status.next_phase
    if nxt:
        click.echo(f"\n➡️  Next phase: {nxt}  (run the kairos-flow skill to start/continue)")
    else:
        click.echo("\n✅ All lifecycle phases complete.")


@cli.command(name='build-glossary')
@click.option('--extraction-dir', type=click.Path(), default=None,
              help='Path to businessdiscovery/_extractions/ (default: auto-detect from hub).')
@click.option('--output', 'output_path', type=click.Path(), default=None,
              help='Output glossary TTL path (default: businessdiscovery/{company}-glossary.ttl).')
@click.option('--company-domain', 'company_domain', type=str, default=None,
              help='Company domain (e.g. acme.com). Default: auto-detect from hub README.')
@click.option('--company-name', 'company_name', type=str, default=None,
              help='Company display name for the scheme label. Default: auto-detect from hub README.')
@click.option('--glossary-namespace', 'glossary_namespace', type=str, default=None,
              help='Glossary namespace IRI. Default: https://{company-domain}/glossary#.')
@click.option('--company-specific-only', is_flag=True, default=False,
              help='Only include terms flagged company_specific in the extractions.')
def build_glossary_cmd(extraction_dir, output_path, company_domain, company_name,
                       glossary_namespace, company_specific_only):
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
    if result.skipped_terms:
        click.echo(f"   ⏭ Skipped {result.skipped_terms} term(s) (no prefLabel or filtered).")
    click.echo("\n✅ Glossary built.")


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
    # --- Re-root to the real managed hub root (DD-062) -----------------------
    # `update` only ever touches the toolkit pin + managed .github/ files, which
    # live at the managed root.  Running from a content subdirectory (e.g. the
    # ontology-hub/ folder) must NOT scaffold a second hub — walk up to the real
    # root and operate there.
    from ..core.hub_utils import find_managed_root

    managed_root = find_managed_root(Path.cwd())
    if managed_root is not None and managed_root != Path.cwd().resolve():
        print(
            f"↪ Detected hub root at {managed_root} "
            f"(you ran from {Path.cwd()}) — operating there."
        )
        os.chdir(managed_root)

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
            # Auto-generate pyproject.toml from scaffold template only for a
            # legacy managed hub (positive .github marker but no pin file yet).
            # When no managed root was found anywhere up the tree, refuse —
            # fabricating here would manufacture a spurious second hub (DD-062).
            if managed_root is None:
                print(
                    f"❌ No ontology hub found at {Path.cwd()} or any parent directory.\n"
                    "   Run this command from a hub root, or use "
                    "'kairos-ontology new-repo' / 'init' to create one."
                )
                raise SystemExit(1)
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
            # uv run auto-syncs when the lock file is newer.
            print(f"   ✓ Upgraded to {ref}")
        else:
            result = subprocess.run(["uv", "sync"], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"❌ uv sync failed:\n{result.stderr}")
                raise SystemExit(1)
            print(f"   ✓ Upgraded to {ref}")

        # The managed-file refresh below runs in THIS process, which still has the
        # OLD toolkit loaded in memory (_toolkit_version / _SCAFFOLD_DIR are bound
        # to the previously-imported module).  If the version actually changed,
        # refresh under the NEW version's scaffold and version stamp.
        if version != _toolkit_version:
            if sys.platform == "win32":
                # The running kairos-ontology.exe locks its own executable, so a
                # synchronous re-exec (uv sync) here would fail to replace it.
                # Schedule a detached helper that waits for this process to exit
                # — releasing the lock — then syncs and refreshes on its own.
                if _schedule_windows_refresh(check):
                    log_path = Path.cwd() / ".kairos" / "upgrade-refresh.log"
                    print(
                        f"   ↻ Managed-file refresh scheduled — it will run automatically "
                        f"once this process exits.\n"
                        f"     Progress opens in a new window; a transcript is written to "
                        f"{log_path}."
                    )
                    raise SystemExit(0)
                print(
                    "⚠  Could not schedule the automatic managed-file refresh.\n"
                    "   Run `uv run kairos-ontology update` in a fresh shell to finish "
                    "the upgrade."
                )
                raise SystemExit(1)

            reexec_cmd = ["uv", "run", "kairos-ontology", "update"]
            if check:
                reexec_cmd.append("--check")
            print(f"   ↻ Refreshing managed files under {ref} (uv run) ...")
            try:
                reexec = subprocess.run(reexec_cmd)
            except (OSError, FileNotFoundError) as exc:
                print(
                    f"⚠  Could not auto-refresh managed files ({exc}).\n"
                    f"   Run `uv run kairos-ontology update` to finish the upgrade."
                )
                raise SystemExit(1)
            raise SystemExit(reexec.returncode)

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
        hub / "model" / "planning",
        hub / "referencemodels-unpacked",
        hub / "integration" / "sources",
        hub / "integration" / "discovery",
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
        hub / "model" / "planning",
        hub / "referencemodels-unpacked",
        hub / "businessdiscovery",
        hub / "businessdiscovery" / "_extractions",
        hub / "integration" / "sources",
        hub / "integration" / "sources" / "custom-transformations",
        hub / "integration" / "transforms" / "dbt" / "models" / "intermediate",
        hub / "integration" / "transforms" / "dbt" / "macros",
        hub / "integration" / "transforms" / "dbt" / "tests",
        hub / "integration" / "discovery",
        hub / "model" / "mappings" / "custom-transformations",
        hub / "output" / "medallion" / "powerbi",
        hub / "output" / "medallion" / "dbt",
        hub / "output" / "neo4j",
        hub / "output" / "azure-search",
        hub / "output" / "a2ui",
        hub / "output" / "prompt",
        hub / "output" / "report",
        hub / ".sessions-projection",
        hub / ".sessions-design-import",
        hub / ".kairos-state",
        hub / ".kairos-state" / "_archive",
        hub / ".kairos-state" / "phases",
        hub / ".kairos-state" / "phases" / "source",
        hub / ".kairos-state" / "phases" / "domain",
        hub / ".kairos-state" / "phases" / "mapping",
        hub / ".kairos-state" / "phases" / "dbt-transformation",
        hub / ".kairos-state" / "phases" / "silver",
        hub / ".kairos-state" / "phases" / "gold",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    # Business-discovery imports live at the REPO ROOT (like ontology-reference-models),
    # not under ontology-hub/. Created on new-repo so it's ready to receive artifacts.
    imports_bd = repo_dir / ".import" / "businessdiscovery"
    imports_bd.mkdir(parents=True, exist_ok=True)
    imports_readme_src = _SCAFFOLD_DIR / "import" / "businessdiscovery" / "README.md"
    if imports_readme_src.is_file():
        shutil.copy2(imports_readme_src, imports_bd / "README.md")

    # Place .gitkeep in output subdirs so git tracks them
    for target in [
        "medallion/powerbi", "medallion/dbt",
        "neo4j", "azure-search", "a2ui", "prompt", "report",
    ]:
        gitkeep = hub / "output" / target / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()

    # Place .gitkeep in audit session folders so git tracks them
    for session_folder in [
        ".sessions-projection",
        ".sessions-design-import",
    ]:
        sk = hub / session_folder / ".gitkeep"
        if not sk.exists():
            sk.touch()

    # Place .gitkeep in OKF state folders so git tracks the lifecycle memory skeleton
    for state_folder in [
        ".kairos-state",
        ".kairos-state/_archive",
        ".kairos-state/phases",
        ".kairos-state/phases/source",
        ".kairos-state/phases/domain",
        ".kairos-state/phases/mapping",
        ".kairos-state/phases/dbt-transformation",
        ".kairos-state/phases/silver",
        ".kairos-state/phases/gold",
    ]:
        sk = hub / state_folder / ".gitkeep"
        if not sk.exists():
            sk.touch()

    # README files
    readme_map = {
        "model/ontologies": "model/ontologies",
        "model/shapes": "model/shapes",
        "model/mappings": "model/mappings",
        "model/mappings/custom-transformations": "model/mappings/custom-transformations",
        "businessdiscovery": "businessdiscovery",
        "businessdiscovery/_extractions": "businessdiscovery/_extractions",
        "integration/sources": "integration/sources",
        "integration/sources/custom-transformations":
            "integration/sources/custom-transformations",
        "integration/transforms/dbt": "integration/transforms/dbt",
    }
    for scaffold_subdir, hub_subdir in readme_map.items():
        src = _SCAFFOLD_DIR / "ontology-hub" / scaffold_subdir / "README.md"
        dst = hub / hub_subdir / "README.md"
        if src.is_file():
            shutil.copy2(src, dst)

    # Business glossary template into businessdiscovery/
    glossary_tpl_src = _SCAFFOLD_DIR / "ontology-hub" / "businessdiscovery" / "glossary-template.ttl"
    if glossary_tpl_src.is_file():
        shutil.copy2(glossary_tpl_src, hub / "businessdiscovery" / "glossary-template.ttl")

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
        content = provenance_comment("new-repo", editable=True) + "\n" + content
        (hub / "model" / "ontologies" / "_master.ttl").write_text(content, encoding="utf-8")
        print("  ✓ ontology-hub/model/ontologies/_master.ttl")

    # Foundation ontology (shared base for thin domain ontologies)
    foundation_src = _SCAFFOLD_DIR / "ontology-hub" / "model" / "ontologies" / "foundation.ttl.template"
    if foundation_src.is_file():
        content = foundation_src.read_text(encoding="utf-8")
        content = (content
                   .replace("{company_name}", company_name)
                   .replace("{company_domain}", company_domain_val))
        content = provenance_comment("new-repo", editable=True) + "\n" + content
        (hub / "model" / "ontologies" / "_foundation.ttl").write_text(content, encoding="utf-8")
        print("  ✓ ontology-hub/model/ontologies/_foundation.ttl")

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
        _DATAPLATFORM_SCAFFOLD
        / ".github"
        / "fabric"
        / "deployment-settings.json.example.template"
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
    click.echo("   # Configure Fabric secrets and run .github/workflows/deploy-powerbi-semantic-model.yml")
