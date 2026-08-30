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
import importlib.metadata
from pathlib import Path


from .. import __version__ as _toolkit_version

# Importing the design-time MDM package registers the additive ``mdm-profile``
# projection target with the core projector (registry pattern, MDM-DD-002).
# The CLI is the layer that legitimately depends on both core and mdm.
from .. import mdm as _mdm  # noqa: F401  (import for side-effect: target registration)

from .shared import (
    _DependencyFilesSnapshot,
    _KNOWN_CLAUDE_SETTINGS_HASHES,
    _MANAGED_MARKER_RE,
    _MANAGED_SKILLS_TREE,
    _RETIRED_MANAGED_SCAFFOLD_FILES,
    _RETIRED_SCAFFOLD_DIRECTORIES,
    _SCAFFOLD_DIR,
    _ToolkitTestRefState,
    _add_toolkit_test_ref_state,
    _copy_managed,
    _dependency_files_transaction,
    _get_managed_version,
    _has_kairos_channel,
    _lock_and_sync_dependency,
    _managed_dataplatform_map,
    _managed_files_transaction,
    _managed_scaffold_map,
    _parse_hub_package_pin,
    _read_hub_channel,
    _read_pinned_toolkit_version,
    _read_toolkit_test_ref_state,
    _refresh_with_installed_toolkit,
    _remove_toolkit_test_ref_state,
    _resolve_channel,
    _resolve_hub_ref_sha,
    _resolve_refmodels_tag,
    _resolve_toolkit_ref_sha,
    _restore_dependency_files,
    _resync_restored_dependency,
    _rewrite_hub_package_pin,
    _rewrite_toolkit_dependency_source,
    _refmodels_whl_url,
    _single_toolkit_dependency_source,
    _stamp_managed,
    _tag_to_version,
    _toolkit_git_sha_source,
    _whl_url,
)


def _migrate_dataplatform_custom_models(repo_root: Path, check: bool) -> None:
    """Migrate a legacy ``models/custom/`` directory to ``models/downstream_only/``.

    DD-206 Phase 1 renamed the *fresh-scaffold* placeholder, but a dataplatform
    repo scaffolded before that rename still has a real ``models/custom/``
    directory -- possibly with real user-authored dbt models in it. Nothing
    else migrates an existing repo, so ``update`` does it here, as part of its
    normal managed-file refresh.

    Idempotent: a repo with no ``models/custom/`` (never had one, or already
    migrated) is a silent no-op -- this is what makes repeated ``update`` runs
    print nothing about this step after the first successful migration.

    Never touches anything when both directories already exist -- that is a
    real conflict (e.g. a partial hand-migration) the user must resolve; this
    prints a warning and lets the rest of ``update`` continue normally.
    """
    custom_dir = repo_root / "models" / "custom"
    downstream_dir = repo_root / "models" / "downstream_only"

    if not custom_dir.is_dir():
        return  # never existed, or already migrated -- nothing to do

    if downstream_dir.exists():
        print(
            "⚠  Both models/custom/ and models/downstream_only/ exist.\n"
            "   DD-206 renamed models/custom/ to models/downstream_only/, but this repo\n"
            "   has content in both directories -- resolve the conflict by hand (merge\n"
            "   the two, or remove whichever is stale) and re-run `update`. Nothing was\n"
            "   moved automatically."
        )
        return

    if check:
        print(
            "ℹ  models/custom/ exists and will be migrated to models/downstream_only/\n"
            "   (DD-206) on the next `update` run without --check."
        )
        return

    # Prefer `git mv` -- it preserves file history -- but only when this repo
    # is (or is inside) a git repo and the move succeeds cleanly. Any failure
    # (not a git repo, dirty index conflict, etc.) falls back to a plain
    # filesystem move so the migration still completes.
    git_result = subprocess.run(
        ["git", "mv", "models/custom", "models/downstream_only"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if git_result.returncode != 0:
        shutil.move(str(custom_dir), str(downstream_dir))

    print(
        "📦 Migrated models/custom/ -> models/downstream_only/ (DD-206): downstream-owned\n"
        "   dbt models now live under the new path. Update any dbt selectors, docs, or\n"
        "   CI configuration that still reference models/custom/."
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
@click.option(
    "--allow-downgrade",
    is_flag=True,
    help="Allow --upgrade to move the toolkit pin backwards to an older version.",
)
@click.option("--force-managed", is_flag=True, hidden=True)
def update(check, upgrade, test_ref, restore, allow_downgrade, force_managed):
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

    --upgrade never moves the pin backwards: if the channel resolves to a version
    older than the hub's current pin it refuses, unless --allow-downgrade is given.

    \b
    Exit codes (with --check):
      0  All managed files are up to date
      1  One or more files are outdated, missing, or stale

    \b
    Managed files (do not edit manually):
      .github/copilot-instructions.md
      .claude/skills/*/SKILL.md
    """
    selected_modes = sum((bool(upgrade), test_ref is not None, bool(restore)))
    if selected_modes > 1:
        raise click.UsageError("--upgrade, --test-ref, and --restore are mutually exclusive")
    if check and (test_ref is not None or restore):
        raise click.UsageError("--check cannot be combined with --test-ref or --restore")
    if allow_downgrade and not upgrade:
        raise click.UsageError("--allow-downgrade only applies to --upgrade")

    # --- Re-root to the real managed hub root (DD-062) -----------------------
    # `update` only ever touches the toolkit pin + managed .github/ files, which
    # live at the managed root.  Running from a content subdirectory (e.g. the
    # ontology-hub/ folder) must NOT scaffold a second hub — walk up to the real
    # root and operate there.
    from ..core.hub_utils import find_managed_root

    managed_root = find_managed_root(Path.cwd())
    if managed_root is not None and managed_root != Path.cwd().resolve():
        print(
            f"↪ Detected hub root at {managed_root} (you ran from {Path.cwd()}) — operating there."
        )
        os.chdir(managed_root)

    # Detect repo type: dataplatform (has dbt_project.yml) vs ontology-hub. Computed
    # once, up front, so both the --upgrade channel gate below and the managed-file
    # refresh further down agree on which repo kind they're operating on.
    repo_root = Path.cwd()
    is_dataplatform = (repo_root / "dbt_project.yml").is_file()

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
        if is_dataplatform and not _has_kairos_channel():
            print(
                "❌ This dataplatform repo has no [tool.kairos] channel configured.\n"
                "   The toolkit dependency is pinned as an unversioned git source, so\n"
                "   there is nothing for --upgrade to resolve against or write a result\n"
                "   into. Recently-scaffolded dataplatforms (kairos-ontology "
                "init-dataplatform)\n"
                "   get a channel-based pin automatically; see CICD.md for the manual\n"
                "   migration steps for a repo scaffolded before this existed."
            )
            raise SystemExit(1)
        channel = _read_hub_channel()
        ref = _resolve_channel(channel)
        if ref is None:
            print(
                f"⚠  Could not resolve channel '{channel}' — is 'gh' installed and authenticated?"
            )
            raise SystemExit(1)
        print(f"📦 Channel: {channel} → {ref}")

        # Update the pyproject.toml dependency pin first
        pyproject = Path.cwd() / "pyproject.toml"
        version = _tag_to_version(ref)

        # Refuse to move the pin backwards unless explicitly allowed.  Every release
        # after v5.0.2 is a pre-release, so the 'stable' channel resolves to v5.0.2:
        # a hub pinned to a current pre-release would otherwise be silently
        # downgraded to a toolkit predating the fixes its scaffold depends on.
        current_pin = _read_pinned_toolkit_version()
        if current_pin is not None and not allow_downgrade:
            from packaging.version import InvalidVersion, Version

            try:
                is_downgrade = Version(version) < Version(current_pin)
            except InvalidVersion:
                is_downgrade = False
            if is_downgrade:
                print(
                    f"❌ Refusing to downgrade the toolkit pin: channel '{channel}' resolves to\n"
                    f"   v{version}, which is OLDER than this hub's current pin v{current_pin}.\n"
                    "   Change [tool.kairos] channel, or pass --allow-downgrade to proceed."
                )
                raise SystemExit(1)

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
                content = content.replace("{toolkit_channel}", channel)
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

        # Upgrading the toolkit only ever moved the toolkit pin -- reference models
        # drifted independently (issue #551), sometimes for over a dozen minor
        # versions, because nothing upgraded that pin in the same pass. A hub that
        # actually pins one (an ontology hub; a dataplatform repo never does) gets
        # it upgraded here too, non-atomically with the toolkit upgrade above (that
        # upgrade was never transactional either) but never silently left behind.
        if pyproject.is_file() and "kairos-ontology-referencemodels" in pyproject.read_text(
            encoding="utf-8"
        ):
            try:
                _upgrade_refmodels(None)
            except click.ClickException as exc:
                print(
                    f"⚠  Toolkit upgraded to {ref}, but the reference-models upgrade failed:\n"
                    f"   {exc}\n"
                    "   Run `kairos-ontology update-refmodels` to retry."
                )
                raise SystemExit(1)

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

    if is_dataplatform:
        managed_map = _managed_dataplatform_map()
    else:
        managed_map = _managed_scaffold_map()

    # --- models/custom/ -> models/downstream_only/ migration (DD-206 follow-up) --
    # DD-206 Phase 1 renamed the *fresh-scaffold* placeholder from models/custom/
    # to models/downstream_only/, but a dataplatform repo scaffolded before that
    # rename still has a real models/custom/ directory -- possibly containing
    # real user-authored dbt models, not just a placeholder. Nothing else
    # migrates that repo, so `update` does it here: automatically, idempotently
    # (silent no-op once migrated, or if the repo never had models/custom/), and
    # only for dataplatform repos -- a hub repo never has a models/ directory in
    # the first place.
    if is_dataplatform:
        _migrate_dataplatform_custom_models(repo_root, check)

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
    skills_dir = repo_root / _MANAGED_SKILLS_TREE
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

    # --- Reconcile .claude/settings.json (semantic-access boundary — DD-103) -
    # This file cannot be added to the managed-refresh loop above: it has no
    # version marker because `_stamp_managed` injects an HTML comment, which
    # would make the JSON invalid — and Claude Code rejects an invalid
    # settings file as a whole, silently voiding every deny rule in it.
    # Instead, `update` only ever replaces a hub's copy when its hash matches
    # a *known, superseded* scaffold generation (`_KNOWN_CLAUDE_SETTINGS_HASHES`).
    # A hand-extended settings file (extra allow rules, hooks, model config)
    # is never overwritten — it gets an advisory instead.
    #
    # This status is deliberately tracked outside the managed_map `created` /
    # `missing` / `outdated` / `updated` lists above: only the "superseded
    # hash" case is real drift that should fail `update --check` (so
    # scaffold/github-workflows/managed-check.yml catches it). A hub simply
    # missing the file, or one carrying local customizations, is reported but
    # must not flip the exit code.
    claude_settings_status: str | None = None  # "missing" | "outdated" | "advisory"
    claude_settings_src = _SCAFFOLD_DIR / "claude-settings.json"
    claude_settings_dst = repo_root / ".claude" / "settings.json"
    claude_settings_rel = ".claude/settings.json"
    if claude_settings_src.is_file():
        if not claude_settings_dst.is_file():
            claude_settings_status = "missing"
            if not check:
                claude_settings_dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(claude_settings_src, claude_settings_dst)
        else:
            local_hash = hashlib.sha256(claude_settings_dst.read_bytes()).hexdigest()
            scaffold_hash = hashlib.sha256(claude_settings_src.read_bytes()).hexdigest()
            if local_hash == scaffold_hash:
                pass  # already current; silent no-op
            elif local_hash in _KNOWN_CLAUDE_SETTINGS_HASHES:
                claude_settings_status = "outdated"
                if not check:
                    shutil.copy2(claude_settings_src, claude_settings_dst)
            else:
                claude_settings_status = "advisory"

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
                print(f"   {_MANAGED_SKILLS_TREE}/{name}/")
        if retired_assets:
            print(f"⚠  {len(retired_assets)} retired scaffold asset(s) to remove:")
            for path in retired_assets:
                print(f"   {path}")
        if claude_settings_status == "missing":
            print(
                f"ℹ  {claude_settings_rel} not present — run `update` (without --check) to create it."
            )
        elif claude_settings_status == "outdated":
            print(
                f"⚠  {claude_settings_rel} needs updating: the DD-103 semantic-access boundary\n"
                f"   was broadened (.ttl/.rdf/.owl, not just .ttl)."
            )
        elif claude_settings_status == "advisory":
            print(
                f"ℹ  {claude_settings_rel} has local customizations and was left alone.\n"
                f"   The DD-103 semantic-access boundary was broadened (.ttl/.rdf/.owl, not\n"
                f"   just .ttl) — please review and merge the updated deny rules by hand."
            )
        if (
            not outdated
            and not missing
            and not stale
            and not retired_assets
            and claude_settings_status != "outdated"
        ):
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
                print(f"   {_MANAGED_SKILLS_TREE}/{name}/")
        if removed_assets:
            print(f"🗑️  Removed {len(removed_assets)} retired scaffold asset(s):")
            for path in removed_assets:
                print(f"   {path}")
        if claude_settings_status == "missing":
            print(f"  ✓ Created {claude_settings_rel} (denies raw ttl/rdf/owl Read/Grep)")
        elif claude_settings_status == "outdated":
            print(f"  ✓ Updated {claude_settings_rel} (semantic-access boundary broadened)")
        elif claude_settings_status == "advisory":
            print(
                f"ℹ  {claude_settings_rel} has local customizations and was left alone.\n"
                f"   The DD-103 semantic-access boundary was broadened (.ttl/.rdf/.owl, not\n"
                f"   just .ttl) — please review and merge the updated deny rules by hand."
            )
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

    # --- Ensure .devcontainer exists (VS Code Dev Container) -----------------
    if not check:
        devcontainer_dst = repo_root / ".devcontainer"
        devcontainer_src = _SCAFFOLD_DIR / ".devcontainer"
        if not devcontainer_dst.exists() and devcontainer_src.is_dir():
            shutil.copytree(devcontainer_src, devcontainer_dst)
            print("  ✓ Created .devcontainer/ (VS Code Dev Container with Node.js)")


def _upgrade_refmodels(version_tag: str | None) -> str:
    """Upgrade the hub's pinned reference-models release, and return the new tag.

    Shared by the standalone ``update-refmodels`` command and ``update --upgrade``
    (issue #551), so both install the exact same resolved wheel rather than one of
    them trusting the pip index. Raises :class:`click.ClickException` on any
    failure — a caller that wants to treat this as a non-fatal partial failure
    (as ``update --upgrade`` does) must catch it itself.
    """
    repo_dir = Path.cwd()
    pyproject = repo_dir / "pyproject.toml"

    tag = _resolve_refmodels_tag(version_tag)
    if tag is None:
        raise click.ClickException(
            "Could not resolve a reference-models release "
            "(is 'gh' installed and authenticated?). Pin left unchanged."
        )

    # Install the exact resolved wheel — never the pip index, which has no
    # kairos-ontology-referencemodels package to find at all (it ships only as a
    # GitHub Release wheel, DD-158), so "uv pip install --upgrade <name>" without
    # --version silently did nothing while still reporting success.
    whl_url = _refmodels_whl_url(tag)
    print(f"   Installing kairos-ontology-referencemodels {tag} …")
    result = subprocess.run(["uv", "pip", "install", whl_url], capture_output=True, text=True)
    if result.returncode != 0:
        raise click.ClickException(f"uv pip install failed:\n{result.stderr.strip()}")
    print("   ✓ Package installed")

    try:
        installed_version = importlib.metadata.version("kairos-ontology-referencemodels")
    except importlib.metadata.PackageNotFoundError:
        raise click.ClickException(
            "kairos-ontology-referencemodels not found after install — check uv environment."
        )

    if pyproject.is_file():
        content = pyproject.read_text(encoding="utf-8")
        new_content = re.sub(
            r"kairos-ontology-referencemodels\s*@\s*(?:"
            r"git\+https://github\.com/Cnext-eu/kairos-ontology-referencemodels\.git@[^\s\"]*"
            r"|https://github\.com/Cnext-eu/kairos-ontology-referencemodels/releases/download/[^\s\"]*"
            r")",
            f"kairos-ontology-referencemodels @ {whl_url}",
            content,
        )
        if new_content != content:
            pyproject.write_text(new_content, encoding="utf-8")
            print(f"   ✓ Updated pyproject.toml pin to {tag} (.whl)")
        else:
            print(f"   ℹ  pyproject.toml already pinned to {tag}")

    print("   Syncing lockfile with uv ...")
    result = subprocess.run(["uv", "lock"], capture_output=True, text=True)
    if result.returncode != 0:
        raise click.ClickException(f"uv lock failed:\n{result.stderr.strip()}")

    click.echo(f"  ✓ Reference models updated: v{installed_version} ({tag})")
    return tag


@click.command(name="update-refmodels")
@click.option(
    "--version",
    "version_tag",
    type=str,
    default=None,
    help="Specific version tag to pin (e.g. v1.33.1). Default: latest published release.",
)
def update_refmodels(version_tag):
    """Update the reference-models package to the latest (or a specific) release.

    Resolves the latest published GitHub release the same way scaffolding does
    (draft-filtered, version-ordered — not the pip index, which has no
    kairos-ontology-referencemodels package to find), installs that exact wheel,
    rewrites the pin in ``pyproject.toml``, and refreshes the lockfile.

    \b
    Examples:
        kairos-ontology update-refmodels
        kairos-ontology update-refmodels --version v1.33.1
    """
    _upgrade_refmodels(version_tag)


@click.command(name="bump-hub")
@click.argument("ref")
def bump_hub(ref):
    """Pin the hub dbt package in packages.yml to REF's full commit SHA.

    Run from a dataplatform repository root containing packages.yml (DD-206
    §2, §12 item 4). REF is a hub branch, tag, or commit SHA; it is resolved
    against the hub's GitHub repository -- read from the existing ``git:``
    line in packages.yml, commented or not -- to an immutable 40-character
    commit SHA via `gh api`. The hub package block is uncommented and pinned
    on first use, and its ``revision:`` is updated in place on every
    subsequent bump. Fails closed if REF cannot be resolved: packages.yml is
    left untouched.

    \b
    Examples:
      kairos-ontology bump-hub v1.4.0
      kairos-ontology bump-hub main
      kairos-ontology bump-hub 0123456789abcdef0123456789abcdef01234567
    """
    packages_path = Path.cwd() / "packages.yml"
    if not packages_path.is_file():
        print(
            f"❌ {packages_path} not found.\n"
            "   Run this command from a dataplatform repository root."
        )
        raise SystemExit(1)

    content = packages_path.read_text(encoding="utf-8")
    try:
        pin = _parse_hub_package_pin(content)
    except ValueError as exc:
        print(f"❌ {exc}")
        raise SystemExit(1)

    sha = _resolve_hub_ref_sha(ref, pin.org_repo)
    if sha is None:
        print(
            f"❌ Could not resolve hub ref {ref!r} against {pin.org_repo} to an immutable\n"
            "   commit SHA; verify the ref and `gh auth status`, then retry."
        )
        raise SystemExit(1)

    new_content = _rewrite_hub_package_pin(content, sha)
    packages_path.write_text(new_content, encoding="utf-8")

    previous = pin.previous_revision or "(none)"
    action = "Uncommented and pinned" if pin.was_commented else "Updated"
    print(f"✅ {action} hub package pin in {packages_path.name}")
    print(f"   Hub:      {pin.org_repo}")
    print(f"   Ref:      {ref}")
    print(f"   Previous: {previous}")
    print(f"   New SHA:  {sha}")
