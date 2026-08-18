#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""
Keep the pinned ``kairos-ontology-referencemodels`` release current with its channel.

Why this exists
---------------
The reference models are declared in ``pyproject.toml`` as a direct wheel URL under
``[tool.uv.sources]`` (DD-158):

    kairos-ontology-referencemodels = { url = "https://.../v<version>/...whl" }

A URL dependency is exact by construction: ``uv`` resolves precisely that artifact and
will never advance it. So the pin only moves when somebody remembers, and in practice
nobody did — this repo sat on **v1.20.0 while the reference models shipped through
v1.33.1**, thirteen minor versions, and nothing noticed (#541).

Pin drift here is quieter than in the sibling repo, which is exactly why it lasted: the
pin lives in ``[dependency-groups].dev``, so it never reaches the published wheel and no
client hub was ever affected. What it did affect is the *evidence*. The cross-repo
contract and bundle-conformance suites were green against a 1.20-era bundle while every
real hub ran something far newer — green against a bundle that predated the very defects
this repo then spent a week finding (the orphaned ``rdfs:domain`` assertions fixed in
reference models 1.32.0, the module routing fixed in 1.33.0). A contract test passing
against a stale bundle is weaker evidence than it looks.

This is the reciprocal of ``scripts/check_toolkit_pin.py`` in the reference-models repo,
which has failed *that* build on pin drift for some time. The asymmetry was the bug.

Latest-release resolution is deliberately **not** reimplemented here: it imports
``_list_published_release_tags`` / ``_latest_stable_tag`` from the toolkit, so drafts are
filtered and ordering is by version rather than by creation date. Issue #542 was caused
by a second, sloppier copy of exactly this logic; a third copy in a CI script would be
the same mistake again.

Channels: ``[tool.kairos] refmodels-channel`` in ``pyproject.toml``, default ``stable``.
  * ``stable``  — newest final release (no ``rc``/``beta``/``alpha`` suffix)
  * ``preview`` — newest release of any kind, pre-releases included
  * ``<tag>``   — an explicit pin; the check only asserts the pin matches it

Network policy: this script talks to the network, so it degrades rather than fails. With
no network, no ``gh`` and no token it reports "undetermined" and exits 0 — a firewalled
contributor is not a broken build. Run it in a CI job that has network to enforce it.

Usage:
    uv run python scripts/check_refmodels_pin.py            # report
    uv run python scripts/check_refmodels_pin.py --check     # exit 1 when behind
    uv run python scripts/check_refmodels_pin.py --update    # rewrite the pin, then re-lock
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"

# Importable from a bare checkout as well as from an installed venv.
sys.path.insert(0, str(REPO_ROOT / "src"))

try:
    from kairos_ontology.cli.shared import (
        _REFMODELS_REPO,
        _latest_stable_tag,
        _list_published_release_tags,
        _sort_tags_by_version,
        _tag_to_version,
    )
except ImportError as exc:  # pragma: no cover - environment problem, not logic
    print(f"✗ Could not import the toolkit ({exc}).")
    print("  Run this via `uv run python scripts/check_refmodels_pin.py`.")
    sys.exit(1)

RELEASES_API = f"https://api.github.com/repos/{_REFMODELS_REPO}/releases?per_page=100"

# The tag appears in the URL path and the version again in the wheel filename; both must
# be rewritten together, which is why the substitution writes the version twice rather
# than back-referencing it.
_PIN_RE = re.compile(
    r"(kairos-ontology-referencemodels = \{ url = \"https://github\.com/[^/]+/[^/]+"
    r"/releases/download/v)"
    r"(?P<tag>[^/\"]+)"
    r"(/kairos_ontology_referencemodels-)"
    r"(?P<version>[^-\"]+)"
    r"(-py3-none-any\.whl\" \})"
)


def _read_pyproject() -> str:
    """Read ``pyproject.toml`` without translating line endings.

    ``newline=""`` on both read and write matters on Windows: the default translates on
    read *and* again on write, so ``--update`` would rewrite every line of a checked-out
    LF file as CRLF and turn a one-token pin bump into a 178-line diff.
    """
    with PYPROJECT.open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write_pyproject(text: str) -> None:
    with PYPROJECT.open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def pinned_tag(text: str) -> str | None:
    """Return the pinned tag (``v``-prefixed), or None when no pin is found."""
    match = _PIN_RE.search(text)
    return f"v{match.group('tag')}" if match else None


def configured_channel(text: str) -> str:
    """``[tool.kairos] refmodels-channel``, defaulting to ``stable``."""
    data = tomllib.loads(text)
    channel = data.get("tool", {}).get("kairos", {}).get("refmodels-channel")
    return str(channel) if channel else "stable"


def _anonymous_release_tags() -> list[str] | None:
    """Draft-filtered release tags via the unauthenticated API, for hosts without ``gh``.

    Mirrors the draft filter of the ``gh`` path deliberately: a draft has no downloadable
    asset, and a draft sharing a tag with a published release is what mispinned a client
    hub in #542.
    """
    try:
        with urllib.request.urlopen(RELEASES_API, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    if not isinstance(payload, list):
        return None
    return _sort_tags_by_version(
        [
            str(release["tag_name"])
            for release in payload
            if isinstance(release, dict) and release.get("tag_name") and not release.get("draft")
        ]
    )


def latest_release(channel: str) -> str | None:
    """Newest release tag for *channel*, or None when it cannot be determined."""
    tags = _list_published_release_tags(_REFMODELS_REPO)
    if tags is None:
        tags = _anonymous_release_tags()
    if not tags:
        return None
    return tags[0] if channel == "preview" else _latest_stable_tag(tags)


def _is_behind(pinned: str, latest: str) -> bool:
    from packaging.version import InvalidVersion, Version

    try:
        return Version(_tag_to_version(pinned)) < Version(_tag_to_version(latest))
    except InvalidVersion:
        return pinned != latest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the reference-models pin.")
    parser.add_argument("--check", action="store_true", help="Exit 1 if the pin is behind.")
    parser.add_argument("--update", action="store_true", help="Rewrite the pin and re-lock.")
    args = parser.parse_args(argv)

    text = _read_pyproject()
    pinned = pinned_tag(text)
    if pinned is None:
        print("✗ Could not find a kairos-ontology-referencemodels wheel pin in pyproject.toml")
        return 1
    channel = configured_channel(text)

    if channel not in {"stable", "preview"}:
        ok = channel == pinned
        print(
            f"{'✓' if ok else '✗'} channel is an explicit pin ({channel}); "
            f"pyproject has {pinned}"
        )
        return 0 if ok or not args.check else 1

    latest = latest_release(channel)
    if latest is None:
        print(f"⚠ Latest '{channel}' release undetermined (offline or unauthenticated).")
        print(f"  Pinned: {pinned}. Not failing — this check needs network access.")
        return 0

    if not _is_behind(pinned, latest):
        print(f"✓ Reference-models pin {pinned} is current for channel '{channel}'.")
        return 0

    print(f"✗ Reference-models pin is behind: pinned {pinned}, latest '{channel}' is {latest}.")
    if not args.update:
        print("  Run: uv run python scripts/check_refmodels_pin.py --update")
        print("  Then re-run the suite: the newer bundle is what every real hub uses.")
        return 1 if args.check else 0

    tag = latest.lstrip("v")
    version = _tag_to_version(latest)
    _write_pyproject(_PIN_RE.sub(rf"\g<1>{tag}\g<3>{version}\g<5>", text))
    print(f"  ✎ pyproject.toml → {latest}")
    lock = subprocess.run(["uv", "lock"], cwd=REPO_ROOT, capture_output=True, text=True)
    if lock.returncode != 0:
        print(f"✗ `uv lock` failed:\n{lock.stderr.strip()}")
        return 1
    print("  ✎ uv.lock regenerated. Run `uv sync --all-groups`, then the full suite.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
