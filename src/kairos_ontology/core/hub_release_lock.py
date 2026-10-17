# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The hub release a dataplatform deploys, pinned in one reviewed file (DD-256, #1114).

A promotion deploys two things from the hub: the dbt package (pinned by SHA in
``packages.yml``, DD-206 §2) and the Power BI archive of a hub *release* (tag, SHA and the
archive's SHA-256, DD-206 §8). The deploy used to take the second set as three
hand-typed workflow inputs on every run. ``hub-release.lock`` records them once, at the
repository root, and changes only through a reviewed pull request -- ``bump-hub`` writes
both files together -- so promoting a commit through dev, uat and prod deploys exactly
what was reviewed, and rolling back to an older commit brings its release with it.

The lock must name the same hub commit ``packages.yml`` pins: a dbt package from one hub
commit and a semantic model from another would not agree on the Gold tables.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

#: Repository-relative path of the lock.
HUB_RELEASE_LOCK_PATH = "hub-release.lock"

_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+-]*$")

_HEADER = """\
# The ontology-hub release this dataplatform deploys (DD-256). Written by
# `kairos-ontology bump-hub <tag>`, together with the packages.yml pin; change it only
# through a pull request. The promote workflow deploys the Power BI archive of this
# release to every environment, after verifying the tag still resolves to `hub_sha` and
# the archive's SHA-256 is `archive_sha256`.
"""


class HubReleaseLockError(Exception):
    """``hub-release.lock`` is malformed or disagrees with ``packages.yml``."""


@dataclass(frozen=True, slots=True)
class HubReleaseLock:
    """One hub release: its tag, the commit it resolves to, and its archive checksum."""

    tag: str
    hub_sha: str
    archive_sha256: str


def parse_hub_release_lock(text: str, *, where: str = HUB_RELEASE_LOCK_PATH) -> HubReleaseLock:
    """Parse and validate the lock's content."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise HubReleaseLockError(f"{where} is not YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise HubReleaseLockError(f"{where} must be a mapping of tag, hub_sha, archive_sha256")
    unknown = sorted(set(map(str, document)) - {"tag", "hub_sha", "archive_sha256"})
    if unknown:
        raise HubReleaseLockError(f"{where} has unknown key(s) {unknown}")
    tag = str(document.get("tag") or "").strip()
    hub_sha = str(document.get("hub_sha") or "").strip().lower()
    archive = str(document.get("archive_sha256") or "").strip().lower()
    if not _TAG.match(tag):
        raise HubReleaseLockError(f"{where}: `tag` {tag!r} is not a release tag")
    if not _SHA.match(hub_sha):
        raise HubReleaseLockError(f"{where}: `hub_sha` must be a full 40-character commit SHA")
    if not _SHA256.match(archive):
        raise HubReleaseLockError(f"{where}: `archive_sha256` must be a 64-character SHA-256")
    return HubReleaseLock(tag=tag, hub_sha=hub_sha, archive_sha256=archive)


def read_hub_release_lock(root: Path) -> HubReleaseLock | None:
    """Return the lock at *root*, or ``None`` when the repository has none."""
    path = Path(root) / HUB_RELEASE_LOCK_PATH
    if not path.is_file():
        return None
    return parse_hub_release_lock(path.read_text(encoding="utf-8"), where=str(path))


def render_hub_release_lock(lock: HubReleaseLock) -> str:
    """Render the lock file, header included."""
    body = yaml.safe_dump(
        {"tag": lock.tag, "hub_sha": lock.hub_sha, "archive_sha256": lock.archive_sha256},
        sort_keys=False,
        default_flow_style=False,
    )
    return _HEADER + body


def check_lock_matches_pin(lock: HubReleaseLock, pinned_sha: str | None) -> None:
    """Fail when the lock's hub commit is not the one ``packages.yml`` pins."""
    pinned = (pinned_sha or "").strip().lower()
    if pinned != lock.hub_sha:
        raise HubReleaseLockError(
            f"{HUB_RELEASE_LOCK_PATH} deploys hub release {lock.tag} ({lock.hub_sha}), but "
            f"packages.yml pins hub commit {pinned or '(none)'}: the dbt package and the "
            f"semantic model would come from different hub commits. Run "
            f"`kairos-ontology bump-hub <release tag>` to move both together."
        )
