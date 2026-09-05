# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Shared CLI constants and implementation helpers."""

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import click
from packaging.requirements import InvalidRequirement, Requirement

from .. import __version__ as _toolkit_version

# Importing the design-time MDM package registers the additive ``mdm-profile``
# projection target with the core projector (registry pattern, MDM-DD-002).
# The CLI is the layer that legitimately depends on both core and mdm.
from .. import mdm as _mdm  # noqa: F401  (import for side-effect: target registration)

from ..core.extract_schema import DEFAULT_SAMPLE_SIZE


def _ensure_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8, line-buffered.

    The toolkit prints Unicode characters (✓, ✅, 🚀, etc.) which cannot be
    encoded by the default Windows console code pages (cp1252/cp437).  Calling
    this early in the process avoids ``UnicodeEncodeError`` at print time.

    ``line_buffering=True`` is what makes a long-running stage observable when stdout
    is a pipe rather than a terminal (issue #694). Python block-buffers a piped
    stream, so a 26-minute ``propose-alignment`` run emitted **zero bytes** until it
    finished -- from outside, a working run and a hung run were indistinguishable.
    Set here rather than per-command: every command that reports progress has the
    same exposure.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def _warn_if_outside_venv() -> None:
    """Emit a warning if the running interpreter is not the hub's uv-managed environment.

    Identity-based (#587): resolve the managed hub root and compare ``sys.prefix``
    against that hub's own ``.venv``.  This catches *any* other environment — a
    pipx / ``uv tool`` global install is still a venv, which the old
    mechanism-based ``sys.prefix != sys.base_prefix`` check waved through — not
    just a bare system Python.  Outside a managed hub (or when the hub has no
    ``.venv``) the old bare-global heuristic remains as a fallback.
    """
    from ..core.hub_utils import find_managed_root

    managed_root = find_managed_root()
    if managed_root is not None:
        hub_venv = managed_root / ".venv"
        if hub_venv.is_dir():
            # normcase: on Windows the drive-letter case can vary between
            # invocations (c: vs C:), and a case-sensitive compare would emit
            # a false warning on every legitimate `uv run`.
            running = os.path.normcase(str(Path(sys.prefix).resolve()))
            expected = os.path.normcase(str(hub_venv.resolve()))
            if running == expected:
                return  # running this hub's own uv-managed environment
            click.echo(
                "⚠️  Running an interpreter that is not this hub's uv-managed environment\n"
                f"   ({hub_venv}).\n"
                "   Commands may lack hub-pinned packages such as kairos-ontology-referencemodels.\n"
                "   Run `uv run kairos-ontology …` from the hub; no manual activation is needed.\n",
                err=True,
            )
            return

    # Fallback (pre-#587 heuristic): bare system Python next to a local .venv.
    if sys.prefix != sys.base_prefix:
        return  # inside some venv, and no hub .venv to compare identity against

    cwd = Path.cwd()
    candidates = [cwd / ".venv", cwd.parent / ".venv"]
    if not any(p.is_dir() for p in candidates):
        return  # no local venv found — probably intentional

    click.echo(
        "⚠️  Running outside the uv-managed project environment — you may be using a different\n"
        "   toolkit version than the one pinned in this hub.\n"
        "   Run `uv run kairos-ontology`; no manual activation is needed.\n",
        err=True,
    )


def format_load_diagnostic(diagnostic) -> str:  # noqa: ANN001 — OntologyDiagnostic, kept lazy
    """Render one ontology-load diagnostic in the shared two-space CLI line format.

    Used by both ``resolve-ontology``'s human-readable output and the DD-151
    boundary rendering of :class:`OntologyLoadError` so the two cannot drift.
    """
    return f"  {diagnostic.level.upper()}: {diagnostic.message}"


def render_ontology_load_failure(error) -> None:  # noqa: ANN001 — OntologyLoadError, kept lazy
    """Render an ``OntologyLoadError`` and its attached diagnostics to stderr (#587).

    Ordering: ``missing_import`` diagnostics first (the actionable cause), then the
    remaining error-level diagnostics, then the rest.  Matching is on ``code``,
    never on ``level`` — degraded loads downgrade ``missing_import`` to warning
    level.  When missing imports coincide with an absent
    ``kairos-ontology-referencemodels`` package, a wrong-environment hint follows.
    """
    click.echo(f"✗ {error}", err=True)
    result = getattr(error, "result", None)
    diagnostics = tuple(getattr(result, "diagnostics", ()) or ())
    missing = [d for d in diagnostics if d.code == "missing_import"]
    other_errors = [d for d in diagnostics if d.code != "missing_import" and d.level == "error"]
    rest = [d for d in diagnostics if d.code != "missing_import" and d.level != "error"]
    for diagnostic in (*missing, *other_errors, *rest):
        click.echo(format_load_diagnostic(diagnostic), err=True)
    if missing and _read_refmodels_provenance() is None:
        # Deliberately does not claim that every missing import above is caused by
        # the absent package: a hub-local import can be missing for its own reason
        # (a typo'd IRI), and #587 is itself a bug report about a diagnostic that
        # asserted the wrong cause. State the fact; the per-import lines above
        # already say which IRIs actually failed.
        click.echo(
            "kairos-ontology-referencemodels is not installed in this Python environment, "
            "so any reference-model bridge import listed above cannot resolve here. "
            "If you're running a globally-installed kairos-ontology, "
            "try 'uv run kairos-ontology ...' instead.",
            err=True,
        )


_SCAFFOLD_DIR = Path(__file__).resolve().parent.parent / "scaffold"


_SKILL_COVERED_COMMANDS = {
    "compile": "kairos-execute-project",
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
    "analyse-sources": "kairos-design-source",
    "draft-model-report": "kairos-design-domain",
    "discovery-conformance": "kairos-design-discovery",
    # kairos-design-source, not -discovery: a registration is proposed from source analysis
    # (analyse-sources' unassigned tables), which is that skill's own output (#505 Layer B).
    "register-concept": "kairos-design-source",
    "init-dataplatform": "kairos-setup-dataplatform",
    "suggest-shapes": "kairos-execute-validate",
    "mdm-validate": "kairos-design-mdm",
    "validate-dbt": "kairos-execute-validate",
    # Not kairos-execute-validate (which owns validate-dbt): this one lints the *authoring*
    # tree an author is mid-way through writing, and the skill that walks them through
    # writing it is the one that should be running it (issue #504).
    "validate-dbt-contracts": "kairos-develop-dbt-transformation",
    # Alternative entry path into the same skill's workflow: promoting a model authored
    # outside the hub is still that skill's territory, not a separate one (issue #634).
    "promote-transform": "kairos-develop-dbt-transformation",
    "validate-mapping": "kairos-design-mapping",
    "scaffold-mapping": "kairos-design-mapping",
}


_SKILL_CONTEXT_ENV_VARS = ("KAIROS_SKILL_CONTEXT", "KAIROS_VIA_SKILL")


def _in_skill_context() -> bool:
    """Return True if a skill-context sentinel env var is set (truthy)."""
    return any(os.environ.get(var) for var in _SKILL_CONTEXT_ENV_VARS)


def _warn_if_no_skill_context(subcommand: str | None) -> None:
    """Emit a soft skill-gate warning for skill-managed commands.

    If *subcommand* is covered by a skill and the process is not running
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
        f"   Prefer the **{skill}** skill in your AI coding session — it runs\n"
        f"   pre-flight checks and validation gates this raw command skips.\n"
        f"   Continuing anyway… (set KAIROS_SKILL_CONTEXT=1 to silence)\n",
        err=True,
    )


_DATAPLATFORM_SKILLS = [
    "kairos-develop-dataplatform",
    "kairos-package-dataplatform",
    "kairos-help",
    "kairos-diagnose-status",
    "kairos-toolkit-ops",
]


def _run_git(args: list[str], repo_dir: Path, label: str) -> str:
    """Run ``git *args*`` in *repo_dir*, returning stdout and raising on failure.

    Decodes as UTF-8 — git's own path encoding — rather than the platform
    locale, with ``surrogateescape`` so an undecodable byte sequence is carried
    through intact instead of raising mid-parse.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=repo_dir,
        capture_output=True,
        encoding="utf-8",
        errors="surrogateescape",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{label} failed in {repo_dir}: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout


def _git_status_snapshot(repo_dir: Path) -> str:
    """Return ``git status --porcelain -z --untracked-files=all`` output for *repo_dir*.

    ``--untracked-files=all`` is required — plain ``--porcelain`` omits
    untracked files entirely, which would let a new file outside a guarded
    scope slip past undetected.

    ``-z`` is equally required. Without it, porcelain v1 wraps any path holding
    a non-ASCII byte in double quotes and octal-escapes it, so
    ``model/bi/Fee – Actual.ttl`` is emitted as
    ``"model/bi/Fee \\342\\200\\223 Actual.ttl"`` — a string no human-written
    ``--allow`` glob can match and no filesystem call can open. ``-z`` emits
    raw, unquoted path bytes terminated by NUL, the one byte a path can never
    contain and therefore the only unambiguous record separator.

    Beware that ``-z`` also **reverses** the rename/copy encoding: the default
    format writes ``R  OLD -> NEW`` on one line, whereas ``-z`` writes
    ``R  NEW`` and then the bare ``OLD`` as the next NUL-terminated field.

    Used by the ``guard-scope`` command to compare a before/after snapshot; not
    a generic git-runner abstraction — every other git call in this module
    stays inline as-is.
    """
    return _run_git(
        ["status", "--porcelain", "-z", "--untracked-files=all"], repo_dir, "git status"
    )


def _git_ignored_snapshot(repo_root: Path, roots: tuple[str, ...]) -> str:
    """Return ``git status --porcelain -z --ignored=matching --untracked-files=all``
    output for *roots*, run from *repo_root* so pathspecs are unambiguous
    repo-root-relative strings.

    ``--ignored=matching`` (rather than the default ``--ignored=traditional``) is
    required: ``traditional`` collapses a whole ignored directory into a single
    ``!! some/dir/`` entry, which cannot be fingerprinted per file. ``matching``
    reports each ignored *file* individually — but only when the file, not its
    containing directory, is what the ``.gitignore`` pattern matches (a directory
    that is itself fully ignored is still reported as one collapsed entry, no
    matter the mode). The toolkit's own scaffolded ``.gitignore`` for
    ``ontology-hub-publish/`` is written this way on purpose (``ontology-hub-publish/**``
    plus ``!ontology-hub-publish/**/`` to un-ignore the directories themselves),
    so this call sees one entry per ignored file under any ``--ignored-root``
    that follows the same shape.

    No pathspec means "the whole repo", which would make an opt-in guard scan
    unbounded — *roots* must always be a non-empty tuple of caller-supplied,
    repo-root-relative paths.
    """
    return _run_git(
        [
            "status",
            "--porcelain",
            "-z",
            "--ignored=matching",
            "--untracked-files=all",
            "--",
            *roots,
        ],
        repo_root,
        "git status --ignored",
    )


def _git_repo_root(repo_dir: Path) -> Path:
    """Return the absolute repository root containing *repo_dir*.

    Porcelain status paths are repo-root-relative whatever directory git was
    invoked from, so resolving them against ``Path.cwd()`` doubles the prefix
    (``ontology-hub/ontology-hub/…``) whenever a command runs from inside the
    hub rather than from the repo root.
    """
    return Path(_run_git(["rev-parse", "--show-toplevel"], repo_dir, "git rev-parse").strip())


def _git_head_sha(repo_dir: Path) -> str:
    """Return the current HEAD commit sha, or ``""`` when HEAD is unborn.

    A commit made inside a guarded window empties the status output entirely,
    so without recording HEAD the guard would report a pristine tree.
    """
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_dir,
        capture_output=True,
        encoding="utf-8",
        errors="surrogateescape",
    )
    if result.returncode != 0:
        return ""  # unborn HEAD — a repository with no commit yet
    return result.stdout.strip()


_REF_MODELS_PATH = "ontology-reference-models"


def resolve_refmodels_dir(cwd: Path, hub_root: Path | None) -> Path | None:
    """Locate the reference-models directory from an explicit override or installed package.

    Resolution order:
    1. ``KAIROS_REFMODELS_ROOT`` environment variable (explicit override / air-gap).
    2. Installed ``kairos-ontology-referencemodels`` package (via ``importlib.resources``).

    The legacy folder-scan fallback is removed — new hubs do not vendor
    ``ontology-reference-models/`` into the repo.
    """
    # 1. KAIROS_REFMODELS_ROOT env var (explicit override)
    env = os.environ.get("KAIROS_REFMODELS_ROOT")
    if env and Path(env).is_dir():
        return Path(env)
    # 2. Package resolution
    try:
        from kairos_ontology_referencemodels import refmodels_root

        root = refmodels_root()
        if root.is_dir():
            return root
    except ImportError:
        pass
    return None


def _resolve_import_dir(cwd: Path, hub_root: Path | None) -> Path:
    """Locate the business-discovery import directory.

    Raw discovery artifacts live at the **repository root** in
    ``.import/businessdiscovery/`` (a sibling of ``ontology-hub/``),
    not under ``ontology-hub/``.  Like :func:`resolve_refmodels_dir`, this
    resolves the dual layout so the command works both from the repo root and
    from inside ``ontology-hub/`` (DD-064).

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


def _resolve_modeling_dir(cwd: Path, hub_root: Path | None, subdir: str) -> Path:
    """Locate a toolkit-managed OKF-style record directory under ``.import/modeling/``.

    Distinct from :func:`_resolve_import_dir`: ``.import/modeling/`` holds structured,
    git-tracked records the toolkit itself authors (e.g. modeling-feedback), not raw
    client evidence. Both live under ``.import/`` at the repository root (a sibling of
    ``ontology-hub/``) and resolve the same dual layout (DD-064) so a command works both
    from the repo root and from inside ``ontology-hub/``.

    Returns the first existing candidate, or ``cwd/.import/modeling/<subdir>`` as a
    stable fallback when none exist.
    """
    rel = Path(".import") / "modeling" / subdir
    candidates = [
        cwd / rel,
        (hub_root.parent / rel) if hub_root else None,
        (hub_root / rel) if hub_root else None,
    ]
    for candidate in candidates:
        if candidate and candidate.is_dir():
            return candidate
    return cwd / rel


_TOOLKIT_REPO = "Cnext-eu/kairos-ontology-toolkit"


def _sort_tags_by_version(tags: list[str]) -> list[str]:
    """Sort release tags by PEP 440 version, highest first (never lexicographically)."""
    from packaging.version import InvalidVersion, Version

    def _parse_version(tag: str) -> Version:
        try:
            return Version(_tag_to_version(tag))
        except InvalidVersion:
            return Version("0.0.0")

    return sorted(tags, key=_parse_version, reverse=True)


def _list_published_release_tags(repo: str) -> list[str] | None:
    """Return every *published* release tag of ``repo``, highest version first.

    Two properties this guarantees, both of which the naive ``.[0].tag_name`` read of
    ``/releases`` lacks (issue #542):

    1. **Drafts are excluded.** A draft has no downloadable asset, so pinning its tag
       yields a hub whose first ``uv sync`` 404s — or, far worse, one that silently
       resolves to a same-named published release from an older line. That is exactly
       how a client hub was born on reference models v1.28.1 while v1.33.1 was current.
    2. **Order is by version, not by creation date.** GitHub lists releases newest-created
       first and puts drafts ahead of published ones, so element zero is neither the
       newest version nor necessarily published at all. A backport patch cut after a
       higher minor would mispin for the same reason.

    Returns ``None`` when the release list cannot be fetched, which callers must keep
    distinct from an empty list: unreachable is a degraded scaffold, empty is a repo
    that has genuinely never released.
    """
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"/repos/{repo}/releases?per_page=100",
                "--jq",
                ".[] | select(.draft == false) | .tag_name",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0 or not isinstance(result.stdout, str):
        return None
    return _sort_tags_by_version([t.strip() for t in result.stdout.splitlines() if t.strip()])


def _latest_stable_tag(tags: list[str]) -> str | None:
    """Highest non-pre-release tag, falling back to the highest tag if all are pre-releases."""
    from packaging.version import InvalidVersion, Version

    for tag in tags:
        try:
            if not Version(_tag_to_version(tag)).is_prerelease:
                return tag
        except InvalidVersion:
            continue
    return tags[0] if tags else None


def _resolve_channel(channel: str) -> str | None:
    """Resolve a channel name to a git ref (tag) using GitHub releases.

    Returns the tag name (e.g. 'v2.17.0') or None if resolution fails.
    Channels:
      - "stable"  → latest non-prerelease tag
      - "preview" → latest tag (including pre-releases)
      - anything else → treated as an explicit ref (returned as-is)

    Only published releases are considered, so the pin always has a wheel to download.
    """
    if channel not in ("stable", "preview"):
        return channel  # explicit ref like "v2.16.0" or "main"

    tags = _list_published_release_tags(_TOOLKIT_REPO)
    if not tags:
        return None
    if channel == "preview":
        return tags[0]  # highest version (may be pre-release)
    return _latest_stable_tag(tags)


def _resolve_scaffold_toolkit_pin(channel: str | None = None) -> tuple[str, str]:
    """Return the ``(ref, channel)`` a freshly scaffolded hub must pin.

    One policy, shared by ``init`` and ``new-repo`` so the two scaffolders cannot
    drift apart (issue #297):

    1. Only ever pin a ref that has a **published** GitHub release, taken from the
       live release list.  The running toolkit's own ``__version__`` is never
       preferred: a development build (e.g. ``5.2.0rc17``) has no release, so the
       wheel URL ``…/download/v5.2.0rc17/…`` would 404 on the hub's first
       ``uv sync``.  That is what ``new-repo`` used to do.
    2. Never pin a release older than the running toolkit while a newer release is
       published.  The scaffold being written comes from the running toolkit, so a
       pin behind it installs a toolkit that predates the files it just generated.
       This is the drift reported in #297: ``init`` pinned ``v5.0.2`` (the newest
       *non*-pre-release) while ``v5.2.0rc12`` did the scaffolding, and every
       command then printed a version-mismatch banner.
    3. Write the channel that matches the chosen ref, so the pin and
       ``[tool.kairos] channel`` are a single truth and ``update --upgrade`` is not
       an immediate downgrade.  A hub scaffolded by a pre-release toolkit
       therefore follows ``preview``.
    4. Last resort only: when releases cannot be listed at all (no ``gh``, no
       network) fall back to ``v<running version>`` and say so.  The pin may not
       exist yet; the hub is repairable with ``update --upgrade``.

    When *channel* is explicitly passed (``"stable"`` or ``"preview"``), skip the
    auto-detection and pin the latest published release on that channel directly.
    This lets the user choose a channel at scaffold time instead of always
    following the running toolkit's version.
    """
    from packaging.version import InvalidVersion, Version

    def _version_of(tag: str | None) -> Version | None:
        if tag is None:
            return None
        try:
            return Version(_tag_to_version(tag))
        except InvalidVersion:
            return None

    # Explicit channel choice from the user — pin the latest release on it.
    if channel in ("stable", "preview"):
        ref = _resolve_channel(channel)
        if ref is not None:
            return ref, channel
        print(
            f"  ⚠ Could not list toolkit releases for channel '{channel}'. "
            f"Falling back to auto-detection."
        )

    try:
        running = Version(_toolkit_version)
    except InvalidVersion:  # pragma: no cover - __version__ is always PEP 440
        running = None

    stable_ref = _resolve_channel("stable")
    stable = _version_of(stable_ref)
    if stable_ref is not None and (stable is None or running is None or stable >= running):
        return stable_ref, "stable"

    preview_ref = _resolve_channel("preview")
    preview = _version_of(preview_ref)
    if preview_ref is not None and (stable is None or (preview is not None and preview > stable)):
        return preview_ref, "preview"
    if stable_ref is not None:
        return stable_ref, "stable"

    print(
        f"  ⚠ Could not list toolkit releases (is 'gh' installed and authenticated?); "
        f"pinning v{_toolkit_version}, which may not be published.\n"
        f"    Run `uv run kairos-ontology update --upgrade` once releases are reachable."
    )
    return f"v{_toolkit_version}", "stable"


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
    return f"https://github.com/{_TOOLKIT_REPO}/releases/download/{tag}/{filename}"


def _refmodels_whl_url(tag: str) -> str:
    """Build the GitHub Releases download URL for the referencemodels .whl artifact."""
    version = _tag_to_version(tag)
    filename = f"kairos_ontology_referencemodels-{version}-py3-none-any.whl"
    return f"https://github.com/Cnext-eu/kairos-ontology-referencemodels/releases/download/{tag}/{filename}"


_REFMODELS_REPO = "Cnext-eu/kairos-ontology-referencemodels"

# Last-resort pin, used only when the release list is unreachable (no `gh`, no network).
# Kept at or above the reference-models version this toolkit is tested against — see
# `tests/test_scaffold_refmodels_pin.py`, which fails when the two drift apart, so a
# degraded scaffold still lands on a bundle the toolkit has actually seen.
_REFMODELS_FALLBACK_TAG = "v1.35.2"


def _resolve_scaffold_refmodels_pin(version_tag: str | None = None) -> tuple[str, str]:
    """Return ``(tag, version)`` for the referencemodels wheel URL in scaffold templates.

    One policy, shared with the toolkit pin (:func:`_resolve_scaffold_toolkit_pin`): a
    freshly scaffolded hub follows the **latest published stable release**, chosen by
    version order over the draft-filtered release list. It must never be born on a
    stale bundle — the ontology semantics live in the reference models (DD-188), so a
    hub pinned behind them is running different semantics from the toolkit that
    scaffolded it.

    *version_tag* pins an explicit release instead (``--ref-models-version``), for the
    rare hub that must reproduce a known-good bundle.

    Falls back to a hardcoded default only when releases cannot be listed at all.
    """
    if version_tag:
        tag = version_tag if version_tag.startswith("v") else f"v{version_tag}"
        return tag, _tag_to_version(tag)

    tags = _list_published_release_tags(_REFMODELS_REPO)
    if tags:
        tag = _latest_stable_tag(tags)
        if tag:
            return tag, _tag_to_version(tag)
    print(
        f"  ⚠ Could not list referencemodels releases (is 'gh' installed and "
        f"authenticated?); pinning {_REFMODELS_FALLBACK_TAG}, which is stale.\n"
        f"    Run `uv run kairos-ontology update-refmodels` once releases are reachable."
    )
    return _REFMODELS_FALLBACK_TAG, _tag_to_version(_REFMODELS_FALLBACK_TAG)


def _resolve_refmodels_tag(version_tag: str | None = None) -> str | None:
    """Resolve the reference-models release tag an upgrade should install.

    Same policy as :func:`_resolve_scaffold_refmodels_pin` — the latest published
    **stable** release, routed through the same draft-filtering, version-ordered
    resolver (:func:`_list_published_release_tags` / :func:`_latest_stable_tag`)
    every other caller uses, rather than a second implementation of "what's
    latest" (issue #542 was caused by exactly that kind of second copy).

    *version_tag* pins an explicit release instead, normalized to the ``v``-prefixed
    form GitHub release tags and wheel URLs both require (``1.33.1`` and ``v1.33.1``
    are the same release, but only the latter is a valid tag/URL segment).

    Unlike the scaffold-time resolver, there is **no fallback to a hardcoded tag**
    when the release list cannot be fetched: scaffolding with no evidence at all
    still needs *something* to pin, but an upgrade is protecting an existing,
    working pin — returning ``None`` and refusing is correct; silently reusing a
    stale hardcoded tag would move the pin backwards without saying so.
    """
    if version_tag:
        return version_tag if version_tag.startswith("v") else f"v{version_tag}"

    tags = _list_published_release_tags(_REFMODELS_REPO)
    if not tags:
        return None
    return _latest_stable_tag(tags)


_COMMIT_SHA_RE = re.compile(r"[0-9a-f]{40}")


_TOOLKIT_NAME = "kairos-ontology-toolkit"


_TOOLKIT_GIT_URL = f"git+https://github.com/{_TOOLKIT_REPO}.git"


_TOOLKIT_RELEASE_URL_RE = re.compile(
    rf"https://github\.com/{re.escape(_TOOLKIT_REPO)}/releases/download/"
    r"[^/\s]+/kairos_ontology_toolkit-[^/\s]+\.whl"
)


_TOOLKIT_GIT_SOURCE_RE = re.compile(rf"{re.escape(_TOOLKIT_GIT_URL)}@[^\s]+")


_TEST_REF_TABLE = "tool.kairos.test-ref"


_TEST_REF_KEYS = frozenset({"requested", "sha", "restore-source"})


_TOML_STRING_RE = re.compile(r'"(?P<double>(?:\\.|[^"\\])*)"|\'(?P<single>[^\']*)\'')


def _resolve_toolkit_ref_sha(ref: str) -> str | None:
    """Resolve a toolkit GitHub ref to an immutable, lowercase commit SHA."""
    ref = ref.strip()
    if not ref:
        return None
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"/repos/{_TOOLKIT_REPO}/commits/{quote(ref, safe='')}",
                "--jq",
                ".sha",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip().lower()
    return sha if _COMMIT_SHA_RE.fullmatch(sha) else None


def _toolkit_git_sha_source(sha: str) -> str:
    """Return the PEP 508 source URL for an immutable toolkit commit."""
    normalized = sha.strip().lower()
    if not _COMMIT_SHA_RE.fullmatch(normalized):
        raise ValueError("toolkit test ref must resolve to a 40-character hexadecimal SHA")
    return f"{_TOOLKIT_GIT_URL}@{normalized}"


def _resolve_hub_ref_sha(ref: str, hub_repo: str, host: str = "github.com") -> str | None:
    """Resolve a hub GitHub ref to an immutable, lowercase commit SHA.

    Sibling of :func:`_resolve_toolkit_ref_sha` (DD-206 §12 item 4), resolving
    against the *hub's* ``org/repo`` — discovered from the dataplatform's own
    ``packages.yml`` (see :func:`_parse_hub_package_pin`) rather than a second
    hardcoded repo constant, since a hub pairs with exactly one dataplatform and
    that pairing is already recorded there. Fails closed on any error: missing
    ``gh``, a timeout, a non-zero exit, or a malformed SHA all return ``None``.
    """
    ref = ref.strip()
    if not ref:
        return None
    # --hostname routes the call at the host the pin actually names, so a GitHub
    # Enterprise Server hub resolves against its own API rather than github.com (#702).
    hostname = (host or "github.com").strip() or "github.com"
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                "--hostname",
                hostname,
                f"/repos/{hub_repo}/commits/{quote(ref, safe='')}",
                "--jq",
                ".sha",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip().lower()
    return sha if _COMMIT_SHA_RE.fullmatch(sha) else None


@dataclass(frozen=True)
class _HubPackagePin:
    """Current state of the hub package block in a dataplatform ``packages.yml``."""

    org_repo: str
    previous_revision: str
    was_commented: bool
    #: The host the pin points at. Captured rather than assumed, so a GitHub Enterprise
    #: Server hub is supported (#702) and `gh api` can be routed to it via --hostname.
    host: str = "github.com"


# Matches the exact three-line hub package block the dataplatform scaffold writes
# (``packages.yml.template``), whether still commented out (fresh scaffold, no hub
# release yet) or already active (a prior ``bump-hub`` uncommented it). Captures
# each line's own EOL sequence so a rewrite never flips CRLF/LF on an unrelated
# line -- this repo's tree is mixed, and a blanket normalization explodes diffs.
_HUB_PACKAGE_BLOCK_RE = re.compile(
    r'(?P<indent>[ \t]*)(?P<hash1>#[ \t]*)?-[ \t]*git:[ \t]*"'
    r'(?P<url>https://(?P<host>[^/"]+)/(?P<org>[^/"]+)/(?P<repo>[^"]+?)(?:\.git)?)"[ \t]*'
    r"(?P<eol1>\r?\n)"
    r'[ \t]*(?P<hash2>#[ \t]*)?revision:[ \t]*"(?P<rev>[^"]*)"[^\r\n]*(?P<eol2>\r?\n)'
    r"[ \t]*(?P<hash3>#[ \t]*)?subdirectory:[ \t]*(?P<subdir>[^\r\n]+?)[ \t]*(?P<eol3>\r?\n)?"
)


def _find_hub_package_block(content: str) -> re.Match[str]:
    """Locate the hub git/revision/subdirectory block, raising if absent."""
    match = _HUB_PACKAGE_BLOCK_RE.search(content)
    if match is None:
        raise ValueError(
            "could not find the hub package block (git/revision/subdirectory) in packages.yml"
        )
    return match


def _parse_hub_package_pin(content: str) -> _HubPackagePin:
    """Read the hub org/repo and current revision from a dataplatform ``packages.yml``."""
    match = _find_hub_package_block(content)
    return _HubPackagePin(
        org_repo=f"{match.group('org')}/{match.group('repo')}",
        previous_revision=match.group("rev"),
        was_commented=match.group("hash1") is not None,
        host=match.group("host"),
    )


def _rewrite_hub_package_pin(content: str, sha: str) -> str:
    """Uncomment (first use) or update (subsequent bumps) the hub package pin.

    Rewrites only the matched three-line block to the canonical, uncommented
    form DD-206 §2 requires -- ``- git:``/``revision:``/``subdirectory:`` at a
    fixed two-space list-item indent -- using *sha* as the new ``revision``.
    Every other line in the file, including any custom comments the caller
    added elsewhere, is left untouched.
    """
    normalized = sha.strip().lower()
    if not _COMMIT_SHA_RE.fullmatch(normalized):
        raise ValueError("hub package revision must resolve to a 40-character hexadecimal SHA")
    # The scaffold's fresh `packages.yml.template` renders `packages: []` (bug #1: a
    # bare `packages:` key with only commented lines beneath it parses to `None`, not
    # `[]`, and crashes dbt). An explicit `[]` is itself only valid while the list is
    # actually empty -- once this rewrite uncomments the git block into a real block
    # sequence below it, `packages: []` followed by `- git: ...` is invalid YAML. Drop
    # the `[]` back to a bare key first so the uncommented sequence parses.
    content = re.sub(r"(?m)^([ \t]*packages:)[ \t]*\[[ \t]*\][ \t]*(\r?\n)", r"\1\2", content)
    match = _find_hub_package_block(content)
    base_indent = match.group("indent")
    url = match.group("url")
    subdir = match.group("subdir")
    eol1 = match.group("eol1")
    eol2 = match.group("eol2")
    eol3 = match.group("eol3") or ""
    replacement = (
        f'{base_indent}- git: "{url}"{eol1}'
        f'{base_indent}  revision: "{normalized}"{eol2}'
        f"{base_indent}  subdirectory: {subdir}{eol3}"
    )
    return content[: match.start()] + replacement + content[match.end() :]


def _decode_toml_string(match: re.Match[str]) -> str:
    """Decode one TOML basic or literal string regex match."""
    if match.group("double") is not None:
        return tomllib.loads(f"value = {match.group(0)}")["value"]
    return match.group("single")


def _toolkit_requirement_matches(content: str) -> list[tuple[re.Match[str], Requirement]]:
    """Return direct-reference toolkit requirements and their TOML string matches."""
    try:
        tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid pyproject.toml: {exc}") from exc

    matches: list[tuple[re.Match[str], Requirement]] = []
    for match in _TOML_STRING_RE.finditer(content):
        line_start = content.rfind("\n", 0, match.start()) + 1
        if "#" in content[line_start : match.start()]:
            continue
        value = _decode_toml_string(match)
        try:
            requirement = Requirement(value)
        except InvalidRequirement:
            continue
        if requirement.name.lower().replace("_", "-") != _TOOLKIT_NAME:
            continue
        if requirement.url is None:
            # A bare extras requirement (e.g. "kairos-ontology-toolkit[flatfile]") carries
            # no source: it resolves through the single direct URL declared in
            # [project.dependencies], which is the only place a hub pins the toolkit
            # version (issue #297).  There is nothing here to validate or rewrite.
            continue
        matches.append((match, requirement))
    if not matches:
        raise ValueError("no kairos-ontology-toolkit dependency found in pyproject.toml")
    return matches


def _validate_toolkit_dependency_source(source: str) -> str:
    """Validate and return one supported release-wheel or git toolkit source."""
    source = source.strip()
    if _TOOLKIT_RELEASE_URL_RE.fullmatch(source) or _TOOLKIT_GIT_SOURCE_RE.fullmatch(source):
        return source
    raise ValueError(
        "unsupported kairos-ontology-toolkit dependency source; expected the toolkit "
        "GitHub release wheel or git repository"
    )


def _single_toolkit_dependency_source(content: str) -> str:
    """Return the one validated source shared by every toolkit requirement."""
    sources = {
        _validate_toolkit_dependency_source(requirement.url or "")
        for _, requirement in _toolkit_requirement_matches(content)
    }
    if len(sources) != 1:
        raise ValueError("all kairos-ontology-toolkit dependencies must use the same source")
    return next(iter(sources))


def _rewrite_toolkit_dependency_source(content: str, source: str) -> str:
    """Rewrite every PEP 508 toolkit direct reference while preserving extras."""
    source = _validate_toolkit_dependency_source(source)
    _single_toolkit_dependency_source(content)
    matches = _toolkit_requirement_matches(content)
    rewritten = content
    for match, requirement in reversed(matches):
        value = _decode_toml_string(match)
        url_start, url_end = requirement.url, requirement.url
        assert url_start is not None and url_end is not None
        start = value.index(url_start)
        replacement = value[:start] + source + value[start + len(url_end) :]
        quote_char = match.group(0)[0]
        if quote_char == '"':
            replacement = json.dumps(replacement, ensure_ascii=False)
        else:
            if "'" in replacement:
                replacement = json.dumps(replacement, ensure_ascii=False)
            else:
                replacement = f"'{replacement}'"
        rewritten = rewritten[: match.start()] + replacement + rewritten[match.end() :]
    return rewritten


@dataclass(frozen=True)
class _ToolkitTestRefState:
    """Temporary restore metadata persisted in ``[tool.kairos.test-ref]``."""

    requested: str
    sha: str
    restore_source: str

    def validated(self) -> "_ToolkitTestRefState":
        requested = self.requested.strip()
        if not requested:
            raise ValueError("test-ref metadata requested ref must not be empty")
        sha = self.sha.strip().lower()
        if not _COMMIT_SHA_RE.fullmatch(sha):
            raise ValueError("test-ref metadata SHA must be 40 hexadecimal characters")
        restore_source = _validate_toolkit_dependency_source(self.restore_source)
        return _ToolkitTestRefState(requested, sha, restore_source)


def _read_toolkit_test_ref_state(content: str) -> _ToolkitTestRefState | None:
    """Decode and validate temporary test-ref metadata from TOML content."""
    try:
        document = tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid pyproject.toml: {exc}") from exc
    kairos = document.get("tool", {}).get("kairos", {})
    if not isinstance(kairos, dict):
        raise ValueError("[tool.kairos] must be a table")
    state_data = kairos.get("test-ref")
    if state_data is None:
        return None
    if not isinstance(state_data, dict) or set(state_data) != _TEST_REF_KEYS:
        raise ValueError(
            "[tool.kairos.test-ref] must contain only requested, sha, and restore-source"
        )
    if not all(isinstance(state_data[key], str) for key in _TEST_REF_KEYS):
        raise ValueError("[tool.kairos.test-ref] values must be strings")
    return _ToolkitTestRefState(
        requested=state_data["requested"],
        sha=state_data["sha"],
        restore_source=state_data["restore-source"],
    ).validated()


def _add_toolkit_test_ref_state(content: str, state: _ToolkitTestRefState) -> str:
    """Append validated test-ref metadata without rewriting unrelated TOML."""
    if _read_toolkit_test_ref_state(content) is not None:
        raise ValueError("a toolkit test-ref session is already active")
    state = state.validated()
    separator = "\n" if content else ""
    return (
        content
        + separator
        + f"[{_TEST_REF_TABLE}]\n"
        + f"requested = {json.dumps(state.requested)}\n"
        + f"sha = {json.dumps(state.sha)}\n"
        + f"restore-source = {json.dumps(state.restore_source)}\n"
    )


def _remove_toolkit_test_ref_state(content: str) -> tuple[str, _ToolkitTestRefState]:
    """Remove and return valid test-ref metadata, preserving all other TOML text."""
    state = _read_toolkit_test_ref_state(content)
    if state is None:
        raise ValueError("no active toolkit test-ref session to restore")
    header = re.compile(rf"(?m)^\[{re.escape(_TEST_REF_TABLE)}\][ \t]*(?:#.*)?\r?\n")
    match = header.search(content)
    if match is None:
        raise ValueError("test-ref metadata must use a dedicated table")
    next_table = re.search(r"(?m)^\s*\[", content[match.end() :])
    end = match.end() + next_table.start() if next_table else len(content)
    start = match.start()
    if start > 0 and content[start - 1] == "\n":
        start -= 1
        if start > 0 and content[start - 1] == "\r":
            start -= 1
    return content[:start] + content[end:], state


@dataclass(frozen=True)
class _DependencyFilesSnapshot:
    """Exact dependency-file bytes captured before a transactional update."""

    pyproject: Path
    pyproject_content: bytes
    lockfile: Path
    lockfile_content: bytes | None


def _snapshot_dependency_files(root: Path) -> _DependencyFilesSnapshot:
    """Snapshot ``pyproject.toml`` and the optional ``uv.lock`` exactly."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise FileNotFoundError(f"{pyproject} does not exist")
    lockfile = root / "uv.lock"
    return _DependencyFilesSnapshot(
        pyproject=pyproject,
        pyproject_content=pyproject.read_bytes(),
        lockfile=lockfile,
        lockfile_content=lockfile.read_bytes() if lockfile.is_file() else None,
    )


def _restore_dependency_files(snapshot: _DependencyFilesSnapshot) -> None:
    """Restore dependency files to an exact snapshot."""
    snapshot.pyproject.write_bytes(snapshot.pyproject_content)
    if snapshot.lockfile_content is None:
        snapshot.lockfile.unlink(missing_ok=True)
    else:
        snapshot.lockfile.write_bytes(snapshot.lockfile_content)


@contextmanager
def _dependency_files_transaction(root: Path) -> Iterator[_DependencyFilesSnapshot]:
    """Roll dependency files back when an update operation raises or exits."""
    snapshot = _snapshot_dependency_files(root)
    try:
        yield snapshot
    except BaseException:
        _restore_dependency_files(snapshot)
        raise


# Skills live under .claude/skills/ — both Claude Code and GitHub Copilot (since
# Copilot's December 2025 Agent Skills release) read that location directly, so
# a single tree serves both tools without a .github/skills/ mirror.
_MANAGED_SKILLS_TREE = ".claude/skills"


@dataclass(frozen=True)
class _ManagedFilesSnapshot:
    """Managed-file state that a forced refresh may replace or remove."""

    root: Path
    copilot_content: bytes | None
    skill_files: dict[str, bytes | None]
    managed_skill_trees: dict[str, dict[str, bytes]]


def _snapshot_managed_files(root: Path) -> _ManagedFilesSnapshot:
    """Capture managed paths without including unrelated custom skill content."""
    copilot = root / ".github" / "copilot-instructions.md"
    skills_dir = root / _MANAGED_SKILLS_TREE
    skill_files: dict[str, bytes | None] = {}
    managed_skill_trees: dict[str, dict[str, bytes]] = {}

    if skills_dir.is_dir():
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            content = skill_file.read_bytes() if skill_file.is_file() else None
            skill_files[skill_dir.name] = content
            if content is not None and _MANAGED_MARKER_RE.search(
                content.decode("utf-8", errors="replace")
            ):
                managed_skill_trees[skill_dir.name] = {
                    str(path.relative_to(skill_dir)): path.read_bytes()
                    for path in skill_dir.rglob("*")
                    if path.is_file()
                }

    return _ManagedFilesSnapshot(
        root=root,
        copilot_content=copilot.read_bytes() if copilot.is_file() else None,
        skill_files=skill_files,
        managed_skill_trees=managed_skill_trees,
    )


def _restore_managed_files(snapshot: _ManagedFilesSnapshot) -> None:
    """Restore only paths a managed refresh is allowed to touch."""
    copilot = snapshot.root / ".github" / "copilot-instructions.md"
    if snapshot.copilot_content is None:
        copilot.unlink(missing_ok=True)
    else:
        copilot.parent.mkdir(parents=True, exist_ok=True)
        copilot.write_bytes(snapshot.copilot_content)

    skills_dir = snapshot.root / _MANAGED_SKILLS_TREE
    if skills_dir.is_dir():
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name in snapshot.skill_files:
                continue
            skill_file = skill_dir / "SKILL.md"
            if skill_file.is_file() and _MANAGED_MARKER_RE.search(
                skill_file.read_text(encoding="utf-8", errors="replace")
            ):
                shutil.rmtree(skill_dir)

    for name, content in snapshot.skill_files.items():
        skill_file = skills_dir / name / "SKILL.md"
        if content is None:
            skill_file.unlink(missing_ok=True)
        else:
            skill_file.parent.mkdir(parents=True, exist_ok=True)
            skill_file.write_bytes(content)

    for name, files in snapshot.managed_skill_trees.items():
        skill_dir = skills_dir / name
        for rel_path, content in files.items():
            path = skill_dir / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


@contextmanager
def _managed_files_transaction(root: Path) -> Iterator[_ManagedFilesSnapshot]:
    """Roll managed paths back if a forced refresh fails after partial writes."""
    snapshot = _snapshot_managed_files(root)
    try:
        yield snapshot
    except BaseException:
        _restore_managed_files(snapshot)
        raise


def _resync_restored_dependency() -> str | None:
    """Best-effort environment repair after restoring dependency files."""
    if sys.platform == "win32":
        return "close the current shell and run `uv sync` to restore the prior environment"
    try:
        result = subprocess.run(["uv", "sync"], capture_output=True, text=True)
    except OSError as exc:
        return f"could not resync the prior dependency source: {exc}"
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        return f"could not resync the prior dependency source: {detail}"
    return None


#: The CLI-visible default for --max-workers on analyse-sources/propose-alignment,
#: used only when neither an explicit flag nor a hub config value is given. Kept
#: separate from core._concurrency.DEFAULT_MAX_WORKERS (8, the library default for
#: direct callers bypassing the CLI) -- both CLI commands have always hardcoded 16
#: here, so DEFAULT_MAX_WORKERS is already dead for CLI users; this issue is about
#: giving a hub a config-level override, not reconciling that pre-existing split.
_CLI_DEFAULT_MAX_WORKERS = 16


def _read_hub_max_workers(hub_root: Path | None) -> int | None:
    """Read ``[tool.kairos].max_workers`` from the hub's pyproject.toml.

    Same dual-candidate lookup ``resolve_hub_accelerator_detailed`` (DD-125)
    uses -- ``hub_root/pyproject.toml`` then ``hub_root.parent/pyproject.toml``
    -- since the caller's own ``hub_root`` may already point at the
    ``ontology-hub`` subdirectory rather than the repo root that holds
    ``pyproject.toml``.

    Returns ``None`` when *hub_root* is ``None``, no pyproject is found, or
    the key is absent -- callers then keep their own CLI default exactly as
    before this setting existed (DD-1XX, issue #562 Problem 1). A present but
    invalid value (non-integer, boolean, zero, or negative) is a
    configuration error and raises rather than silently falling back --
    unlike an absent key, a wrong one must not be indistinguishable from "not
    set".
    """
    if hub_root is None:
        return None
    for candidate in (Path(hub_root) / "pyproject.toml", Path(hub_root).parent / "pyproject.toml"):
        if not candidate.is_file():
            continue
        try:
            document = tomllib.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            continue
        value = document.get("tool", {}).get("kairos", {}).get("max_workers")
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise click.ClickException(
                f"{candidate}: [tool.kairos].max_workers must be a positive integer, "
                f"got {value!r}"
            )
        return value
    return None


def _read_hub_channel() -> str:
    """Read the [tool.kairos] channel from the current directory's pyproject.toml.

    Parsed with ``tomllib`` so commented-out keys are ignored.  The previous
    ``re.search(..., re.DOTALL)`` scan matched the first ``channel = "…"`` anywhere
    after ``[tool.kairos]``, so a commented ``# channel = "preview"`` sitting above
    the real key won — and ``update --upgrade`` then resolved the wrong channel.
    Falls back to a comment-skipping line scan only when the file is not valid TOML.
    """
    pyproject = Path.cwd() / "pyproject.toml"
    if not pyproject.is_file():
        return "stable"
    content = pyproject.read_text(encoding="utf-8")
    try:
        channel = tomllib.loads(content).get("tool", {}).get("kairos", {}).get("channel")
    except (tomllib.TOMLDecodeError, AttributeError):
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            match = re.match(r'channel\s*=\s*"([^"]+)"', stripped)
            if match:
                return match.group(1)
        return "stable"
    return channel if isinstance(channel, str) and channel.strip() else "stable"


def _has_kairos_channel() -> bool:
    """Return whether the cwd's ``pyproject.toml`` genuinely configures a channel.

    Unlike :func:`_read_hub_channel`, this does not default to ``"stable"`` when
    ``[tool.kairos].channel`` is absent -- a dataplatform repo has no such table at
    all, and defaulting there is indistinguishable from a hub that genuinely chose
    ``stable``, which previously let ``update --upgrade`` silently no-op while
    claiming success for a dataplatform (item #20).
    """
    pyproject = Path.cwd() / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        channel = (
            tomllib.loads(pyproject.read_text(encoding="utf-8"))
            .get("tool", {})
            .get("kairos", {})
            .get("channel")
        )
    except tomllib.TOMLDecodeError:
        return False
    return isinstance(channel, str) and bool(channel.strip())


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
    version = _tag_to_version(m.group(1))
    # A git pin may reference a bare commit SHA rather than a release tag. Such a pin is not
    # PEP 440-comparable against the running semver, so return None (stay silent) instead of
    # emitting a perpetual "different from" banner that can never match.
    try:
        from packaging.version import Version

        Version(version)
    except Exception:
        return None
    return version


def _warn_if_version_mismatch() -> None:
    """Warn when the running toolkit version differs from the hub's pin.

    The remedy depends on the *direction* of the mismatch:

    * running **older** than the pin — the classic case this guard was written for:
      a globally-installed ``kairos-ontology`` shadowing ``uv run``.  Syncing to the
      pin is the fix.
    * running **newer** than the pin — the normal case when working from a toolkit
      checkout, or after a hub was scaffolded/pinned by an older release.  Here the
      user is *not* on a stale global install and ``uv sync`` would downgrade them
      into whatever the pinned release still gets wrong, so the advice is to move
      the hub's pin forward instead.
    """
    pinned = _read_pinned_toolkit_version()
    if not pinned or pinned == _toolkit_version:
        return

    running_is_older = False
    running_is_newer = False
    try:
        from packaging.version import parse as _parse_version

        running_is_older = _parse_version(_toolkit_version) < _parse_version(pinned)
        running_is_newer = _parse_version(_toolkit_version) > _parse_version(pinned)
    except Exception:  # pragma: no cover - packaging always present via deps
        pass

    if running_is_newer:
        message = (
            f"⚠️  Running kairos-ontology v{_toolkit_version}, which is NEWER than the\n"
            f"   version pinned in this hub (v{pinned}).\n"
            f"   This hub pins an older toolkit; `uv sync` would downgrade you to it.\n"
            f"   Fix: run `uv run kairos-ontology update --upgrade` to move the pin forward.\n"
        )
    else:
        relation = "OLDER than" if running_is_older else "different from"
        message = (
            f"⚠️  Running kairos-ontology v{_toolkit_version}, which is {relation} the\n"
            f"   version pinned in this hub (v{pinned}).\n"
            f"   You may be using a globally-installed toolkit.\n"
            f"   Fix: run `uv run kairos-ontology …` (or `uv sync`) to use the pin.\n"
        )
    click.echo(message, err=True)


_MANAGED_MARKER_RE = re.compile(r"<!-- kairos-ontology-toolkit:managed v([\d]+(?:\.[\d]+)*\S*) -->")


_MANAGED_MARKER_TEMPLATE = "<!-- kairos-ontology-toolkit:managed v{version} -->"

# The fresh-hub contract is intentionally narrower than the complete set of
# directories the toolkit can consume.  These are the directories created by
# both ``init`` and ``new-repo`` for a v5 hub.
_V5_HUB_DIRECTORIES = (
    "model/ontologies",
    "model/shapes",
    "businessdiscovery",
    "businessdiscovery/_extractions",
    "decisions",
    "integration/bindings",
    "integration/discovery",
    "integration/discovery/bi",
    "integration/sources",
    "integration/transforms/dbt/models",
    "integration/transforms/dbt/macros",
    "integration/transforms/dbt/tests",
    "integration/transforms/dbt/seeds",
)

# Derived/emitted output subdirectories.  These are created under the sibling
# publish root (``<repo>/ontology-hub-publish/``), NOT under the hub — derived
# artifacts live outside the authored hub directory.
_V5_OUTPUT_DIRECTORIES = (
    "medallion/dbt",
    "powerbi",
    "neo4j",
    "azure-search",
    "a2ui",
    "prompt",
    "reports/details",
    "architecture/ddd",
    "architecture/erd",
    "mdm",
)

# Exact toolkit-owned paths installed by pre-v5 scaffolds.  ``update`` may
# remove these files, then prune only directories that are empty; user content
# in any retired directory is therefore preserved.
_RETIRED_MANAGED_SCAFFOLD_FILES = {
    "ontology-hub/update-referencemodels.ps1": (
        "61b4f1c8584365c1b1805afa8eeb7ef958f5ae7a222fa1a07432cc85b499b25e",
    ),
    "ontology-hub/integration/sources/custom-transformations/README.md": (
        "5107ce76e390542b1699fa5e98faffde59eb07be12254c4bafe54ca91d9907b2",
    ),
    "ontology-hub/model/mappings/README.md": (
        "f5faf9c1b52bc87a5f26232c90030b819943232f6e2fa4767bf032568edd9b47",
    ),
    "ontology-hub/model/mappings/custom-transformations/README.md": (
        "53a721474b83044c4cabf9d4e800aa1e04306668cc2faf395d5695485a88e68a",
    ),
    "ontology-hub/model/planning/dbt-transformations/README.md": (
        "ec33addad352f3ecb1fe7385a08588d0eb0399339cdcf948f722b3185f41133a",
    ),
    "ontology-hub/model/governance/README.md": (
        "45ac817d279bd83196c801874d2f84d80518bc3f565760ac89fbeb907554b16d",
    ),
    "ontology-hub/model/governance/release-baseline.yaml": (
        "e1cccb241e8a752d1dcacf70155ba8ae8bb0de1e5cca408a298d02e018ab198c",
    ),
    "ontology-hub/model/shapes/kairos-prep-shapes.shacl.ttl": (
        "b03e21cb531cae12ba45566a04c8594ddcfaf892a40f83deb12c32866ad9612d",
    ),
    "ontology-hub/model/shapes/kairos-ext-shapes.shacl.ttl": (
        "624ca5737407b7f68f64c4545d23aa1a004f4f176fa3f69fbb1145e6a2f48ab9",
        "9351a0feb3021abfe65ad45281d6242b38c72efc6196fefca4cbf61cdab20b10",
    ),
    "ontology-hub/model/shapes/kairos-map-shapes.shacl.ttl": (
        "322cfce3b8b203c94acb0e2626ab7dc300a4bb513261c92d86e7cdeda5e81aa4",
        "c94957988e609d43ab470f8064c75380ccd9bab45ae8944820b600a4d32bac48",
    ),
    "ontology-hub/integration/preparation/README.md": (
        "d0c6a385ac565ba09c3d275e0cba3393c8c120e3ca28a14292bcc48027fd4ad0",
    ),
    "ontology-hub/integration/preparation/source-prep.ttl.template": (
        "96a14086770d955d65c4325d94af99b737629fd3869dd8096adb8a800a7f3e05",
    ),
    "ontology-hub/integration/preparation/source-prep.example.ttl": (
        "13c80020cda3bea0e3fc8fdaeb63623fb7f4d8e9daec2cb85ddef3f38e358f2f",
    ),
    "ontology-hub/integration/transforms/dbt/evidence/README.md": (
        "06a428039ceac67de2dea6e23c297023ac374e3bd3ab122cb9807559b6c7c2c3",
    ),
    "ontology-hub/.sessions-projection/.gitkeep": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    "ontology-hub/.sessions-design-import/.gitkeep": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    "ontology-hub/output/report/.gitkeep": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
}

# Every previously-shipped scaffold/claude-settings.json generation, mapped to a description of
# what changed *after* it. `update` replaces a hub's file only when it matches one of these, so a
# hand-extended settings file (extra allow rules, hooks, model settings) is never destroyed — it
# gets an advisory instead.
#
# Two things about this table are load-bearing (issue #684).
#
# **The hashes are of LF-normalized bytes.** They used to be raw-byte hashes, and the #659 entry
# had been captured from a CRLF checkout. A hub carrying that generation was then classified by
# line ending rather than by content: `update --check` exited 1 on Windows and 0 on Linux for the
# identical commit, and only the Windows path went on to overwrite the file. Callers must hash the
# LF-normalized bytes, never the raw bytes.
#
# **The description is per-generation.** The report used to hard-code one sentence about the
# ".ttl -> .ttl/.rdf/.owl" broadening, which is only true of the oldest entry. A hub sitting on the
# #659 generation was told its pending change concerned file extensions, when it was actually the
# removal of twelve `Read` denies -- which is why that overwrite read as destroying local edits.
_KNOWN_CLAUDE_SETTINGS_GENERATIONS = {
    "08c0b53faf0ea032c4746e460ae85e41e8f7731f999778d730e114e50ce037f5": (
        "the DD-103 semantic-access boundary was broadened "
        "(.ttl/.rdf/.owl, not just .ttl, and both path anchorings)"
    ),
    "7be2c70ddda8878e179930ce9dcaf0ac8d12cd09f982170f4d6b85acc515db08": (
        "the reference-model deny rules were dropped when reference models moved from "
        "copy-in-scaffold to pip-package distribution (DD-158)"
    ),
    "6ce03d5dcc389b92b387545e41c3d7b1936112bd87b66b6dc6cee2f4b965e680": (
        "Edit/Write of compiler-owned ontology-hub-publish/** is now denied, so emitted "
        "output cannot be hand-edited"
    ),
    "6e6ee7d78b3f32e890ac2c7f4bbd4c77546a068bee136f61f96a7cb4a3d4a0e6": (
        "the twelve Read denies on model/ontologies and model/shapes were REMOVED: denying "
        "Read also disables Edit (Claude Code requires a prior Read), which made authoring a "
        "domain .ttl or its SHACL structurally impossible (issue #659). If your hub restored "
        "them by hand, that revert is what blocks kairos-design-domain -- let this update land"
    ),
}

# Retained for callers that only need membership (e.g. the static boundary test).
_KNOWN_CLAUDE_SETTINGS_HASHES = tuple(_KNOWN_CLAUDE_SETTINGS_GENERATIONS)

_RETIRED_SCAFFOLD_DIRECTORIES = (
    "ontology-hub/referencemodels-unpacked",
    "ontology-hub/.kairos-state/phases/dbt-transformation",
    "ontology-hub/.kairos-state/phases/mapping",
    "ontology-hub/.kairos-state/phases/domain",
    "ontology-hub/.kairos-state/phases/source",
    "ontology-hub/.kairos-state/phases",
    "ontology-hub/.kairos-state/_archive",
    "ontology-hub/.kairos-state",
    "ontology-hub/.sessions-projection",
    "ontology-hub/.sessions-design-import",
    "ontology-hub/integration/transforms/dbt/evidence",
    "ontology-hub/integration/sources/custom-transformations",
    "ontology-hub/integration/preparation",
    "ontology-hub/model/governance",
    "ontology-hub/model/planning/dbt-transformations",
    "ontology-hub/model/planning",
    "ontology-hub/model/mappings/custom-transformations",
    "ontology-hub/model/mappings",
    "ontology-hub/model/extensions",
    "ontology-hub/output/report",
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

    cicd = _SCAFFOLD_DIR / "CICD.md.template"
    if cicd.is_file():
        result["CICD.md"] = cicd

    contributing = _SCAFFOLD_DIR / "CONTRIBUTING.md.template"
    if contributing.is_file():
        result["CONTRIBUTING.md"] = contributing

    ci = _SCAFFOLD_DIR / "copilot-instructions.md"
    if ci.is_file():
        result[".github/copilot-instructions.md"] = ci

    for rel_path in (
        "ontology-hub/decisions/README.md",
        "ontology-hub/decisions/HUB-DD-template.md.template",
    ):
        scaffold_file = _SCAFFOLD_DIR / rel_path
        if scaffold_file.is_file():
            result[rel_path] = scaffold_file

    # Modeling — toolkit-managed, git-tracked OKF-style records. Scaffold source
    # lives under "import/" but is installed to ".import/" (leading dot) in the
    # repo, so source and destination relative paths differ -- same pattern as
    # copilot-instructions.md above, unlike the decisions/ entries where they
    # happen to match. Originally ".import/businessdiscovery/insights/" (#608);
    # relocated to ".import/modeling/feedback/" (#591).
    modeling_readme = _SCAFFOLD_DIR / "import" / "modeling" / "README.md"
    if modeling_readme.is_file():
        result[".import/modeling/README.md"] = modeling_readme
    for filename in ("README.md", "FEEDBACK-template.md.template"):
        scaffold_file = _SCAFFOLD_DIR / "import" / "modeling" / "feedback" / filename
        if scaffold_file.is_file():
            result[f".import/modeling/feedback/{filename}"] = scaffold_file

    # Per-directory guidance, one README beside the thing it explains. These were
    # write-once until DD-219: written at `init` and then frozen, so a wrong instruction
    # could only ever be corrected in hubs created after the fix -- half the scaffold's
    # documentation lines were unreachable that way. They carry no substitution tokens
    # (the `{company}` / `{slug}` braces in the discovery ones are filename examples in
    # prose), so the verbatim-copy managed path handles them as-is.
    #
    # Deliberately NOT here: `decisions/index.md` and `.import/modeling/feedback/index.md`
    # are regenerated from the hub's own records by `kairos-ontology decision` and
    # `... feedback`. Managing either would have `update` overwrite a client's accumulated
    # log with an empty table.
    for rel_path in (
        "ontology-hub/.input/README.md",
        "ontology-hub/businessdiscovery/README.md",
        "ontology-hub/businessdiscovery/_extractions/README.md",
        "ontology-hub/integration/bindings/README.md",
        "ontology-hub/integration/discovery/bi/README.md",
        "ontology-hub/integration/sources/README.md",
        "ontology-hub/integration/sources/source-system-template/README.md",
        "ontology-hub/integration/transforms/dbt/README.md",
        "ontology-hub/model/ontologies/README.md",
        "ontology-hub/model/shapes/README.md",
    ):
        scaffold_file = _SCAFFOLD_DIR / rel_path
        if scaffold_file.is_file():
            result[rel_path] = scaffold_file

    # Same, but installed under the leading-dot ".import/" tree.
    discovery_readme = _SCAFFOLD_DIR / "import" / "businessdiscovery" / "README.md"
    if discovery_readme.is_file():
        result[".import/businessdiscovery/README.md"] = discovery_readme

    skills = _SCAFFOLD_DIR / "skills"
    if skills.is_dir():
        for skill_dir in sorted(skills.iterdir()):
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.is_file():
                    # .claude/skills/ is read directly by both Claude Code and
                    # GitHub Copilot (since Copilot's Dec 2025 Agent Skills release).
                    result[f".claude/skills/{skill_dir.name}/SKILL.md"] = skill_file

    return result


def _managed_dataplatform_map() -> dict[str, Path]:
    """Return managed-file map for dataplatform repos (skill subset)."""
    result: dict[str, Path] = {}

    cicd = _DATAPLATFORM_SCAFFOLD / "CICD.md.template"
    if cicd.is_file():
        result["CICD.md"] = cicd

    contributing = _DATAPLATFORM_SCAFFOLD / "CONTRIBUTING.md.template"
    if contributing.is_file():
        result["CONTRIBUTING.md"] = contributing

    ci = _SCAFFOLD_DIR / "dataplatform-copilot-instructions.md"
    if ci.is_file():
        result[".github/copilot-instructions.md"] = ci

    skills = _SCAFFOLD_DIR / "skills"
    for skill_name in _DATAPLATFORM_SKILLS:
        skill_file = skills / skill_name / "SKILL.md"
        if skill_file.is_file():
            result[f".claude/skills/{skill_name}/SKILL.md"] = skill_file

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
    update_cmd = "uv run kairos-ontology update --force-managed"
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
        "try { Start-Transcript -Path $env:KAIROS_REFRESH_LOG -Force | Out-Null } catch {} ; "
        f"Write-Host 'Refreshing managed files under the upgraded toolkit...'; "
        f"uv sync; "
        f"{update_cmd}; "
        f"try {{ Stop-Transcript | Out-Null }} catch {{}}"
    )

    # DETACHED_PROCESS=0x8, CREATE_NEW_CONSOLE=0x10, CREATE_NEW_PROCESS_GROUP=0x200.
    # A visible console lets the user watch progress; the transcript keeps a record.
    creationflags = 0x00000010 | 0x00000200
    try:
        child_env = os.environ.copy()
        child_env["KAIROS_REFRESH_LOG"] = str(log_path)
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            creationflags=creationflags,
            close_fds=True,
            env=child_env,
        )
    except (OSError, ValueError):
        return False
    return True


def _refresh_with_installed_toolkit(check: bool, ref: str) -> int:
    """Refresh managed files using the dependency source just installed by uv."""
    if sys.platform == "win32":
        if not _schedule_windows_refresh(check):
            raise RuntimeError(
                "could not schedule the Windows managed-file refresh; close any shell "
                "using the hub environment and retry"
            )
        log_path = Path.cwd() / ".kairos" / "upgrade-refresh.log"
        print(
            "   ↻ Managed-file refresh scheduled — it will run automatically "
            "once this process exits.\n"
            "     Progress opens in a new window; a transcript is written to "
            f"{log_path}."
        )
        return 0

    command = ["uv", "run", "kairos-ontology", "update", "--force-managed"]
    if check:
        command.append("--check")
    print(f"   ↻ Refreshing managed files under {ref} (uv run) ...")
    try:
        return subprocess.run(command).returncode
    except (OSError, FileNotFoundError) as exc:
        raise RuntimeError(
            f"could not refresh managed files under the installed toolkit: {exc}"
        ) from exc


def _lock_and_sync_dependency() -> None:
    """Lock and install the current pyproject toolkit source."""
    print("   Syncing environment with uv ...")
    result = subprocess.run(["uv", "lock"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"uv lock failed:\n{result.stderr.strip()}")
    if sys.platform == "win32":
        return
    result = subprocess.run(["uv", "sync"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"uv sync failed:\n{result.stderr.strip()}")


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
            cwd=parent,
            capture_output=True,
            text=True,
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


def _ontology_domain_hints(ontologies_path: Path | None) -> list[str]:
    """Derive candidate domain ids from the resolved ontology input (accelerator
    resolution fallback hint — the domain(s) actually being validated/projected).

    A single ``--ontology`` file or a ``model/ontologies/`` directory of per-domain
    TTLs both name-match the ``data-domains.yaml`` ``groups[].domains[].id`` values
    used elsewhere, so file stems are a reasonable, best-effort hint. Returns an
    empty list when nothing can be inferred (no domain-ownership inference is then
    attempted, and genuine ambiguity across multiple installed accelerators still
    errors).
    """
    if ontologies_path is None:
        return []
    if ontologies_path.is_file():
        return [ontologies_path.stem]
    if ontologies_path.is_dir():
        return sorted({p.stem for p in ontologies_path.glob("*.ttl")})
    return []


def _resolve_projection_cli_scope(
    ontologies, ontology, catalog, ref_models, accelerator
) -> tuple[Path, Path | None, Path | None, Path | None, str | None]:
    """Resolve the shared project input scope."""

    from ..core.hub_utils import find_hub_root
    from ..core.reference_modules import resolve_hub_accelerator

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=False)
    if ontology is not None and ontologies is not None:
        raise click.UsageError(
            "Use either --ontology for one file or --ontologies for a directory, not both."
        )
    if ontology is not None:
        ontologies_path = Path(ontology)
    elif ontologies is not None:
        ontologies_path = Path(ontologies)
    elif hub_root is not None:
        ontologies_path = hub_root / "model" / "ontologies"
    else:
        ontologies_path = cwd / "ontology-hub" / "model" / "ontologies"
    if not ontologies_path.is_dir() and not ontologies_path.is_file():
        raise click.ClickException(
            f"Cannot find ontology input at {ontologies_path}. Run from the hub root "
            "(or inside ontology-hub/), pass --ontologies for a directory, or pass "
            "--ontology for one file."
        )
    ref_models_path = Path(ref_models) if ref_models else resolve_refmodels_dir(cwd, hub_root)
    catalog_path = _resolve_catalog(catalog, hub_root, cwd, ref_models_path)
    try:
        resolved_accelerator = resolve_hub_accelerator(
            explicit=accelerator,
            hub_root=hub_root,
            ref_models_dir=ref_models_path,
            domain_hint=_ontology_domain_hints(ontologies_path),
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    return ontologies_path, catalog_path, ref_models_path, hub_root, resolved_accelerator


_CATALOG_FILENAME = "catalog-v001.xml"


_CATALOG_CANDIDATES = [
    Path("ontology-hub/catalog-v001.xml"),
]


def _resolve_catalog(
    explicit: str | Path | None,
    hub_root: Path | None = None,
    cwd: Path | None = None,
    ref_models_dir: Path | None = None,
) -> Path | None:
    """Return the catalog path to use.

    If *explicit* is given (user passed ``--catalog``), use it directly.
    Otherwise search, in order:

    1. ``hub_root/catalog-v001.xml`` (the hub-local catalog),
    2. an explicitly resolved reference-models directory,
    3. the auto-detected reference-models catalog,
    4. the legacy cwd-relative ``_CATALOG_CANDIDATES`` (repo-root invocation).

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
    if ref_models_dir is not None:
        candidates.append(ref_models_dir / _CATALOG_FILENAME)
    detected_ref_models_dir = resolve_refmodels_dir(cwd, hub_root)
    if detected_ref_models_dir is not None:
        candidates.append(detected_ref_models_dir / _CATALOG_FILENAME)
    candidates.extend(_CATALOG_CANDIDATES)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _resolve_semantic_input(
    value: str,
    catalog: str | None,
) -> tuple[Path, Path | None]:
    """Resolve a CLI ontology path or catalog-mapped ontology IRI."""
    candidate = Path(value)
    catalog_path = Path(catalog) if catalog else None
    if candidate.is_file():
        return candidate, catalog_path
    if catalog_path is None:
        raise click.ClickException(
            f"{value!r} is not a file; --catalog is required to resolve an ontology IRI."
        )
    from ..core.catalog_utils import CatalogResolver

    resolved = CatalogResolver.with_reference_models(catalog_path).resolve(value)
    if resolved is None or not resolved.is_file():
        raise click.ClickException(f"No catalog mapping for ontology IRI: {value}")
    return resolved, catalog_path


@click.command(name="extract-schema")
@click.option(
    "--profile", "profile_name", required=True, help="dbt profile name (from profiles.yml)."
)
@click.option("--target", default="dev", help="dbt target name (default: dev).")
@click.option("--schema", "schema_name", required=True, help="Database schema to introspect.")
@click.option(
    "--system",
    "system_name",
    required=True,
    help="Logical source system name (used for output directory).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="extracted",
    help="Output base directory (default: extracted/).",
)
@click.option(
    "--profiles-dir",
    "profiles_dir",
    type=click.Path(exists=True),
    default=".dbt",
    help="Directory containing profiles.yml (default: .dbt/).",
)
@click.option(
    "--tables",
    "table_list",
    default=None,
    help="Comma-separated list of tables to introspect (default: all).",
)
@click.option(
    "--sample-size",
    default=DEFAULT_SAMPLE_SIZE,
    type=int,
    help=f"Number of sample rows per table (default: {DEFAULT_SAMPLE_SIZE}).",
)
@click.option(
    "--emit-seed",
    is_flag=True,
    default=False,
    help="Also write each table's samples as a dbt seed CSV. Requires --redact-pii, "
    "because seed CSVs are committed and released.",
)
@click.option(
    "--seeds-dir",
    "seeds_dir",
    type=click.Path(),
    default="seeds",
    help="Output directory for --emit-seed CSV files (default: seeds/).",
)
@click.option(
    "--redact-pii",
    "redact_pii",
    is_flag=True,
    default=False,
    help="Apply the redact-detected-pii sample policy. Off by default (issue #692): the "
    "detector's false positives destroyed the sample evidence binding design reads.",
)
@click.option(
    "--no-redact-pii",
    "no_redact_pii",
    is_flag=True,
    default=False,
    help="Deprecated no-op -- this is now the default. Accepted so scripts and docs that "
    "pass it keep working.",
)
def extract_schema(
    profile_name,
    target,
    schema_name,
    system_name,
    output,
    profiles_dir,
    table_list,
    sample_size,
    emit_seed,
    seeds_dir,
    redact_pii,
    no_redact_pii,
):
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
    With --emit-seed, each table's already-redacted sample rows (the same
    rows written to <table>.samples.yaml) are also serialized as a dbt
    seed CSV under --seeds-dir (default: seeds/):
      seeds/<system>__<table1>__sample.csv
      seeds/<system>__<table2>__sample.csv

    \b
    Examples:
      kairos-ontology extract-schema --profile myproject --schema bronze --system adminpulse
      kairos-ontology extract-schema --profile myproject --schema dbo --system nms \\
          --tables "tblClient,tblInvoice" --sample-size 10
      kairos-ontology extract-schema --profile myproject --schema bronze --system adminpulse \\
          --emit-seed --seeds-dir seeds
    """
    from ..core.extract_schema import run_extract_schema

    tables = [t.strip() for t in table_list.split(",")] if table_list else None
    output_path = Path(output)
    profiles_path = Path(profiles_dir)
    seeds_path = Path(seeds_dir)

    click.echo(f"🔍 Extracting schema: {schema_name}")
    click.echo(f"   Profile: {profile_name} (target: {target})")
    click.echo(f"   System: {system_name}")
    click.echo(f"   Profiles dir: {profiles_path}")
    if tables:
        click.echo(f"   Tables: {', '.join(tables)}")
    else:
        click.echo("   Tables: all in schema")
    click.echo(f"   Sample size: {sample_size}")
    if emit_seed and not redact_pii:
        click.echo(
            "\n❌ --emit-seed requires --redact-pii.\n"
            "   Seed CSVs are not gitignored, and the emitted copy under\n"
            "   ontology-hub-publish/medallion/dbt/ is explicitly un-ignored and\n"
            "   packaged into a GitHub Release -- so unredacted rows would leave the\n"
            "   repo.",
            err=True,
        )
        raise SystemExit(1)
    if emit_seed:
        click.echo(f"   Emit seed CSVs: yes ({seeds_path})")
    if redact_pii:
        click.echo("   PII redaction: enabled (--redact-pii)")
    else:
        click.echo("   ⚠ PII redaction: off (default) -- sample values written as-is")
    click.echo()

    try:
        extraction = run_extract_schema(
            profiles_dir=profiles_path,
            profile_name=profile_name,
            target=target,
            schema=schema_name,
            system_name=system_name,
            output_dir=output_path,
            tables=tables,
            sample_size=sample_size,
            emit_seed=emit_seed,
            seeds_dir=seeds_path,
            redact_pii=redact_pii,
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

    # Report what THIS run extracted, from the run itself rather than from the output
    # directory (#679). Globbing "*.yaml" there counted tables left by earlier runs and
    # double-counted every table, because each one writes both <table>.yaml and
    # <table>.samples.yaml -- so a single-table refresh reported "Extracted 8 tables".
    result_dir = extraction.directory
    click.echo(f"✅ Extracted {len(extraction.tables)} table(s) to: {result_dir}")
    for table_name in extraction.tables:
        click.echo(f"   📄 {table_name}")

    if emit_seed and seeds_path.is_dir():
        seed_files = sorted(seeds_path.glob(f"{system_name}__*__sample.csv"))
        if seed_files:
            click.echo(f"✅ Wrote {len(seed_files)} seed CSV(s) to: {seeds_path}")
            for f in seed_files:
                click.echo(f"   🌱 {f.name}")


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
    "--format",
    "output_format",
    type=click.Choice(["json", "yaml"]),
    default="json",
    help="Machine-output format on stdout (default: json).",
)


_REFMODELS_OPTION = click.option(
    "--refmodels-root",
    "refmodels_root",
    type=click.Path(),
    default=None,
    help="Reference-models checkout (default: $KAIROS_REFMODELS_ROOT or sibling scan).",
)


_MIGRATE_DIR_MAP = {
    # model
    "ontologies": "model/ontologies",
    "shapes": "model/shapes",
    # integration
    "sources": "integration/sources",
    "mappings": "model/mappings",
    "bronze": "integration/sources",
}


_MIGRATE_OUTPUT_MAP = {
    "silver": "medallion/dbt",
    "dbt": "medallion/dbt",
}


def _is_old_layout(hub: Path) -> bool:
    """Return True if *hub* still has the old flat directory layout."""
    return (hub / "ontologies").is_dir() and not (hub / "model").is_dir()


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


def _read_refmodels_provenance() -> dict[str, str | None] | None:
    """Read reference-model provenance from the installed package metadata."""
    try:
        import importlib.metadata

        v = importlib.metadata.version("kairos-ontology-referencemodels")
        return {"ref": v, "version": v, "source": "pip"}
    except importlib.metadata.PackageNotFoundError:
        return None
    except ImportError:
        return None


def _format_refmodels_fetch_provenance(ref_models_dir: Path | None) -> str | None:
    """Return a concise reference-model provenance label for CLI output.

    Reads the installed package version via ``importlib.metadata`` rather than
    a ``FETCH_PROVENANCE.json`` file.  The *ref_models_dir* parameter is kept
    for call-site compatibility but no longer read from.
    """
    import importlib.metadata

    try:
        v = importlib.metadata.version("kairos-ontology-referencemodels")
        return f"v{v} (pip)"
    except importlib.metadata.PackageNotFoundError:
        return None


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
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                f"/repos/{full_name}",
                "-f",
                "delete_branch_on_merge=true",
            ],
            cwd=repo_dir,
            capture_output=True,
            check=True,
        )
        print("  ✓ Enabled delete_branch_on_merge")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode().strip() if exc.stderr else str(exc)
        print(f"  ⚠ Could not enable delete_branch_on_merge: {stderr}")

    # 2. Create branch protection on main
    protection_payload = json.dumps(
        {
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
        }
    )

    try:
        subprocess.run(
            [
                "gh",
                "api",
                "--method",
                "PUT",
                f"/repos/{full_name}/branches/main/protection",
                "--input",
                "-",
            ],
            input=protection_payload.encode(),
            cwd=repo_dir,
            capture_output=True,
            check=True,
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
            cwd=repo_dir,
            capture_output=True,
            check=True,
        )
        raw = result.stdout
        text = raw.decode() if isinstance(raw, bytes) else str(raw)
        protection = json.loads(text)
        if protection.get("required_pull_request_reviews"):
            print("  ✓ Protection verified: main branch is protected")
        else:
            print("  ⚠ Protection set but could not verify PR requirement")
    except (
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        TypeError,
        UnicodeDecodeError,
        AttributeError,
    ):
        print("  ⚠ Could not verify branch protection (may still be active)")


def _create_github_repo(
    repo_dir: Path, repo_slug: str, org: str, description: str, is_private: bool
):
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
            [
                "gh",
                "repo",
                "create",
                full_name,
                visibility,
                "--description",
                description,
                "--source",
                ".",
                "--push",
            ],
            cwd=repo_dir,
            capture_output=True,
            check=True,
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
            capture_output=True,
            text=True,
            timeout=10,
            cwd=hub_root.parent if hub_root.name == "ontology-hub" else hub_root,
        )
        if result.returncode == 0:
            repo_url = result.stdout.strip()
            # Parse org/repo from URL (https or ssh)
            import re as _re

            m = _re.search(r"[/:]([^/]+)/([^/]+?)(?:\.git)?$", repo_url)
            if m:
                org = m.group(1)
                repo_name = m.group(2)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Detect version from VERSION.json
    version = "v0.1.0"
    version_file = hub_root.parent if hub_root.name == "ontology-hub" else hub_root
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


# --- Scaffolded GitHub Actions workflows (issue #658) -----------------------------
#
# Written once at scaffold time and, until #658, never revisited -- so a correctness or
# security fix landing in a workflow template could not reach any repo that already
# existed. These are NOT part of `_managed_scaffold_map`: `_stamp_managed` injects an
# HTML comment, which is not valid YAML, and workflow files carry real local
# customization that must never be silently overwritten. See `cli/workflow_refresh.py`.

#: ``{repo_relative_destination: scaffold_source}`` for a hub repo's workflows.
_HUB_WORKFLOW_SOURCES = {
    ".github/workflows/managed-check.yml": "github-workflows/managed-check.yml",
    ".github/workflows/pr-validate.yml": "github-workflows/pr-validate.yml",
    ".github/workflows/release-projections.yml": "github-workflows/release-projections.yml",
    ".github/workflows/assign-copilot.yml": "github-workflows/assign-copilot.yml",
    ".github/workflows/copilot-setup-steps.yml": "github-workflows/copilot-setup-steps.yml",
}

#: Same, for a dataplatform repo. These are `.template` files with `{ORG}`-style
#: placeholders, so their rendered bytes are repo-specific -- which is precisely why
#: detection reverse-templates rather than comparing hashes.
_DATAPLATFORM_WORKFLOW_SOURCES = {
    ".github/workflows/pr-validate.yml": (
        "dataplatform/.github/workflows/pr-validate.yml.template"
    ),
    ".github/workflows/deploy-powerbi-semantic-model.yml": (
        "dataplatform/.github/workflows/deploy-powerbi-semantic-model.yml.template"
    ),
}

#: Previously-shipped generations of a workflow template, by repo-relative destination.
#: A file matching one of these is an *untouched older generation*, so refreshing it is
#: pure gain rather than an overwrite -- that distinction is the whole safety property.
#:
#: MAINTENANCE: when you change a workflow template, copy its outgoing content to
#: ``scaffold/superseded-workflows/<slug>/<n>.template`` and list it here. Skipping this
#: does not break anything, but every already-scaffolded repo will then report
#: "customized" and need a manual refresh instead of an automatic one.
_SUPERSEDED_WORKFLOW_TEMPLATES: dict[str, tuple[str, ...]] = {
    # Pre-#650 generation, before `pr-validate.yml` gained its guard against
    # `local:` dbt package pins. This is the concrete fix #658 was filed about:
    # it shipped in a release that no existing dataplatform could receive.
    # The destination path is the same for a hub and a dataplatform, so both repo
    # kinds' outgoing generations live under this one key.
    ".github/workflows/pr-validate.yml": (
        "dataplatform-pr-validate/1.template",
        # Pre-DD-215 dataplatform generation, before the `dbt build --empty` guidance.
        "dataplatform-pr-validate/2.template",
        # Pre-DD-215 hub generation, before `validate-dbt-contracts` became a CI gate.
        "hub-pr-validate/1.template",
    ),
}


def _workflow_sources(repo_root: Path) -> dict[str, Path]:
    """Return ``{destination: template_path}`` for whichever repo kind *repo_root* is."""
    sources = (
        _DATAPLATFORM_WORKFLOW_SOURCES
        if (repo_root / "dbt_project.yml").is_file()
        else _HUB_WORKFLOW_SOURCES
    )
    resolved = {}
    for destination, relative in sources.items():
        path = _SCAFFOLD_DIR / relative
        if path.is_file():
            resolved[destination] = path
    return resolved


def _superseded_workflow_templates(destination: str) -> tuple[str, ...]:
    """Load the recorded prior generations of *destination*'s template."""
    root = _SCAFFOLD_DIR / "superseded-workflows"
    return tuple(
        (root / name).read_text(encoding="utf-8")
        for name in _SUPERSEDED_WORKFLOW_TEMPLATES.get(destination, ())
        if (root / name).is_file()
    )
