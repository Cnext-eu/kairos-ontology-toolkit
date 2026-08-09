# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused operations CLI commands."""

import os
import re
import sys
import click
import hashlib
import shutil
import subprocess
from pathlib import Path


from .. import __version__ as _toolkit_version

# Importing the design-time MDM package registers the additive ``mdm-profile``
# projection target with the core projector (registry pattern, MDM-DD-002).
# The CLI is the layer that legitimately depends on both core and mdm.
from .. import mdm as _mdm  # noqa: F401  (import for side-effect: target registration)

from .shared import (
    _DependencyFilesSnapshot,
    _MANAGED_MARKER_RE,
    _RETIRED_MANAGED_SCAFFOLD_FILES,
    _RETIRED_SCAFFOLD_DIRECTORIES,
    _REFMODELS_REMOTE,
    _REFMODELS_REMOTE_DIR,
    _SCAFFOLD_DIR,
    _ToolkitTestRefState,
    _add_toolkit_test_ref_state,
    _copy_managed,
    _dependency_files_transaction,
    _detect_refmodels_dest,
    _get_managed_version,
    _lock_and_sync_dependency,
    _managed_dataplatform_map,
    _managed_files_transaction,
    _managed_scaffold_map,
    _read_hub_channel,
    _read_toolkit_test_ref_state,
    _refresh_with_installed_toolkit,
    _remove_toolkit_test_ref_state,
    _resolve_channel,
    _resolve_toolkit_ref_sha,
    _restore_dependency_files,
    _resync_restored_dependency,
    _rewrite_toolkit_dependency_source,
    _single_toolkit_dependency_source,
    _stamp_managed,
    _tag_to_version,
    _toolkit_git_sha_source,
    _write_refmodels_fetch_provenance,
    _whl_url,
)


@click.command()
@click.option(
    "--check",
    is_flag=True,
    help="Report outdated files without modifying anything (exit 1 on drift).",
)
@click.option(
    "--upgrade",
    is_flag=True,
    help="Upgrade the toolkit dependency to the channel's latest version.",
)
@click.option(
    "--test-ref",
    metavar="BRANCH-OR-SHA",
    help="Resolve an unreleased Git ref to an immutable SHA and install it.",
)
@click.option(
    "--restore", is_flag=True, help="Restore the exact dependency source saved by --test-ref."
)
@click.option("--force-managed", is_flag=True, hidden=True)
def update(check, upgrade, test_ref, restore, force_managed):
    """Update toolkit-managed files to the installed toolkit version.

    Scans .github/ for files stamped by kairos-ontology-toolkit and refreshes
    them from the currently installed package.  Missing managed files (e.g.,
    newly added skills) are created automatically.  Skills that have the
    managed marker but are no longer in the current scaffold (renamed or
    removed) are deleted.  Use --check to preview what would change without
    writing anything.

    Use --upgrade to upgrade the toolkit dependency based on the channel
    configured in [tool.kairos] of pyproject.toml (stable or preview).
    Use --test-ref to resolve a branch or SHA to an immutable Git commit, lock,
    sync, and force a managed-file refresh without changing the configured
    release channel.  Then use --restore to return to the exact dependency
    source saved before the test.

    \b
    Exit codes (with --check):
      0  All managed files are up to date
      1  One or more files are outdated, missing, or stale

    \b
    Managed files (do not edit manually):
      .github/copilot-instructions.md
      .github/skills/*/SKILL.md
    """
    selected_modes = sum((bool(upgrade), test_ref is not None, bool(restore)))
    if selected_modes > 1:
        raise click.UsageError("--upgrade, --test-ref, and --restore are mutually exclusive")
    if check and (test_ref is not None or restore):
        raise click.UsageError("--check cannot be combined with --test-ref or --restore")

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

    # --- Temporarily test or restore an exact toolkit dependency source --------
    if test_ref is not None or restore:
        if managed_root is None:
            print(
                f"❌ No ontology hub found at {Path.cwd()} or any parent directory.\n"
                "   Run this command from a hub root containing pyproject.toml."
            )
            raise SystemExit(1)

        action = "restore" if restore else "test-ref"
        snapshot: _DependencyFilesSnapshot | None = None
        try:
            with (
                _dependency_files_transaction(Path.cwd()) as snapshot,
                _managed_files_transaction(Path.cwd()),
            ):
                content = snapshot.pyproject_content.decode("utf-8")
                if restore:
                    without_state, state = _remove_toolkit_test_ref_state(content)
                    new_content = _rewrite_toolkit_dependency_source(
                        without_state, state.restore_source
                    )
                    installed_ref = state.restore_source
                else:
                    if _read_toolkit_test_ref_state(content) is not None:
                        raise ValueError(
                            "a toolkit test-ref session is already active; run "
                            "`kairos-ontology update --restore` first"
                        )
                    sha = _resolve_toolkit_ref_sha(test_ref)
                    if sha is None:
                        raise ValueError(
                            f"could not resolve toolkit ref {test_ref!r} to an immutable "
                            "commit SHA; verify the ref and `gh auth status`, then retry"
                        )
                    prior_source = _single_toolkit_dependency_source(content)
                    state = _ToolkitTestRefState(test_ref, sha, prior_source)
                    new_content = _rewrite_toolkit_dependency_source(
                        content, _toolkit_git_sha_source(sha)
                    )
                    new_content = _add_toolkit_test_ref_state(new_content, state)
                    installed_ref = sha

                snapshot.pyproject.write_bytes(new_content.encode("utf-8"))
                _lock_and_sync_dependency()
                refresh_code = _refresh_with_installed_toolkit(False, installed_ref)
                if refresh_code != 0:
                    raise RuntimeError(f"managed-file refresh exited with status {refresh_code}")
        except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
            resync_error = _resync_restored_dependency()
            if snapshot is not None:
                _restore_dependency_files(snapshot)
            resync_guidance = f"\n   ⚠ {resync_error}" if resync_error else ""
            print(
                f"❌ Toolkit {action} failed; dependency and managed files were rolled back.\n"
                f"   {exc}{resync_guidance}"
            )
            raise SystemExit(1)

        if restore:
            print("   ✓ Restored the exact prior toolkit dependency source")
        else:
            print(f"   ✓ Toolkit test ref {test_ref!r} pinned to {installed_ref}")
        raise SystemExit(0)

    # --- Upgrade toolkit dependency via uv ------------------------------------
    if upgrade:
        channel = _read_hub_channel()
        ref = _resolve_channel(channel)
        if ref is None:
            print(
                f"⚠  Could not resolve channel '{channel}' — is 'gh' installed and "
                f"authenticated?"
            )
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
            whl_url = _whl_url(ref)
            # Match both old git+https format and new .whl URL format, and
            # preserve any extras marker (e.g. kairos-ontology-toolkit[flatfile])
            # so optional-dependencies pins are rewritten too — otherwise they
            # stay on the old version and `uv lock` fails with conflicting URLs.
            new_content = re.sub(
                r"kairos-ontology-toolkit(\[[^\]]*\])?\s*@\s*(?:"
                r'git\+https://github\.com/Cnext-eu/kairos-ontology-toolkit\.git@[^\s"]*'
                r'|https://github\.com/Cnext-eu/kairos-ontology-toolkit/releases/download/[^\s"]*'
                r")",
                lambda m: f"kairos-ontology-toolkit{m.group(1) or ''} @ {whl_url}",
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
            try:
                refresh_code = _refresh_with_installed_toolkit(check, ref)
            except RuntimeError as exc:
                print(
                    f"⚠  Could not auto-refresh managed files ({exc}).\n"
                    f"   Run `uv run kairos-ontology update` to finish the upgrade."
                )
                raise SystemExit(1)
            raise SystemExit(refresh_code)

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

        if local_ver == _toolkit_version and not force_managed:
            current.append(rel_path)
            continue

        scaffold_content = scaffold_src.read_text(encoding="utf-8")
        new_content = _stamp_managed(scaffold_content, _toolkit_version)
        if local_content == new_content:
            current.append(rel_path)
            continue

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
            d.name
            for d in scaffold_skills_dir.iterdir()
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

    retired_assets: list[str] = []
    removed_assets: list[str] = []
    for rel_path, scaffold_hashes in _RETIRED_MANAGED_SCAFFOLD_FILES.items():
        local_path = repo_root / rel_path
        if not local_path.is_file():
            continue
        content = local_path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        is_managed = bool(_MANAGED_MARKER_RE.search(content.decode("utf-8", errors="ignore")))
        if not is_managed and hashlib.sha256(content).hexdigest() not in scaffold_hashes:
            continue
        if check:
            retired_assets.append(rel_path)
        else:
            local_path.unlink()
            removed_assets.append(rel_path)

    for rel_path in _RETIRED_SCAFFOLD_DIRECTORIES:
        local_path = repo_root / rel_path
        if not local_path.is_dir() or any(local_path.iterdir()):
            continue
        if check:
            retired_assets.append(rel_path + "/")
        else:
            local_path.rmdir()
            removed_assets.append(rel_path + "/")

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
        if retired_assets:
            print(f"⚠  {len(retired_assets)} retired scaffold asset(s) to remove:")
            for path in retired_assets:
                print(f"   {path}")
        if not outdated and not missing and not stale and not retired_assets:
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
        if removed_assets:
            print(f"🗑️  Removed {len(removed_assets)} retired scaffold asset(s):")
            for path in removed_assets:
                print(f"   {path}")
        if not updated and not created and not removed and not removed_assets:
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

    # --- Ensure .claude/settings.json exists (TTL access boundary — DD-103) --
    if not check:
        claude_settings_src = _SCAFFOLD_DIR / "claude-settings.json"
        claude_settings_dst = repo_root / ".claude" / "settings.json"
        if not claude_settings_dst.is_file() and claude_settings_src.is_file():
            claude_settings_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(claude_settings_src, claude_settings_dst)
            print("  ✓ Created .claude/settings.json (denies raw TTL Read/Grep)")

    # --- Ensure .devcontainer exists (VS Code Dev Container) -----------------
    if not check:
        devcontainer_dst = repo_root / ".devcontainer"
        devcontainer_src = _SCAFFOLD_DIR / ".devcontainer"
        if not devcontainer_dst.exists() and devcontainer_src.is_dir():
            shutil.copytree(devcontainer_src, devcontainer_dst)
            print("  ✓ Created .devcontainer/ (VS Code Dev Container with Node.js)")


@click.command(name="update-refmodels")
@click.option(
    "--ref",
    "git_ref",
    type=str,
    default="main",
    help="Branch, tag, or SHA to fetch (default: main).",
)
@click.option(
    "--dest",
    "dest_path",
    type=click.Path(),
    default=None,
    help="Destination path for reference models "
    "(default: auto-detect ontology-reference-models/).",
)
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
            ["git", "--version"],
            capture_output=True,
            check=True,
        )
    except FileNotFoundError:
        raise click.ClickException(
            "git is not installed or not on PATH. " "Install git and try again."
        )

    click.echo(f"  ▶ Fetching ref '{git_ref}' from upstream reference models…")

    tmp_dir = Path(tempfile.mkdtemp(prefix="kairos-refmodels-"))

    try:
        # Sparse shallow clone
        result = subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--filter=blob:none",
                "--sparse",
                "--branch",
                git_ref,
                _REFMODELS_REMOTE,
                str(tmp_dir),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise click.ClickException(
                f"git clone failed (ref '{git_ref}'):\n{result.stderr.strip()}"
            )

        # Set sparse-checkout to only the reference models folder
        result = subprocess.run(
            ["git", "-C", str(tmp_dir), "sparse-checkout", "set", _REFMODELS_REMOTE_DIR],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise click.ClickException(f"git sparse-checkout failed:\n{result.stderr.strip()}")

        src = tmp_dir / _REFMODELS_REMOTE_DIR
        if not src.exists():
            raise click.ClickException(
                f"Expected folder '{_REFMODELS_REMOTE_DIR}' not found in cloned repo. "
                f"Check that the ref '{git_ref}' contains this folder."
            )

        # Get commit SHA for reporting
        sha_result = subprocess.run(
            ["git", "-C", str(tmp_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        )
        sha = sha_result.stdout.strip() if sha_result.returncode == 0 else None

        # Replace destination with fetched content
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        _write_refmodels_fetch_provenance(dest, ref=git_ref, commit=sha)

        # Report results
        click.echo(f"  ✓ Reference models updated: {dest}")
        click.echo(f"    Ref    : {git_ref}")
        click.echo(f"    Commit : {sha[:12] if sha else 'unknown'}")

        # Check for VERSION file
        version_file = dest / "VERSION"
        if version_file.exists():
            version = version_file.read_text().strip()
            click.echo(f"    Version: {version}")

    finally:
        # Clean up temp directory
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
