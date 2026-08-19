# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""A freshly scaffolded hub follows the latest published stable release (issue #542).

A client hub scaffolded on 2026-08-17 was born pinned to reference models v1.28.1 while
v1.33.1 was current, so it ran the ontology semantics that 5.10.0's
``property-domain-unreachable`` warning was written to report as broken.

The cause was ``gh api /repos/.../releases --jq '.[0].tag_name'``. Two independent
defects in that one line:

* ``/releases`` includes **drafts**, and GitHub lists them ahead of published releases.
  The refmodels repo held a draft tagged ``v1.28.1``, so element zero was the draft.
* Element zero is the newest *by creation date*, not by version, so a backport patch cut
  after a higher minor mispins for the same reason.

The mistake was silent because a published ``v1.28.1`` also existed, so the wheel URL
built from the draft's tag resolved and ``uv sync`` succeeded. These tests pin the
policy rather than the symptom: both scaffold pins are the highest published stable
version, chosen by version order over a draft-filtered list.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path
from unittest import mock

from packaging.version import Version

from kairos_ontology.cli.shared import (
    _REFMODELS_FALLBACK_TAG,
    _latest_stable_tag,
    _list_published_release_tags,
    _resolve_channel,
    _resolve_refmodels_tag,
    _resolve_scaffold_refmodels_pin,
    _tag_to_version,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

# The refmodels release list exactly as the API returned it the day the bad hub was
# scaffolded: a draft v1.28.1 first, then published releases newest-created first.
REAL_RELEASES = [
    {"tag_name": "v1.28.1", "draft": True},  # the trap
    {"tag_name": "v1.33.1", "draft": False},
    {"tag_name": "v1.31.0", "draft": False},
    {"tag_name": "v1.30.0", "draft": False},
    {"tag_name": "v1.29.1", "draft": False},
    {"tag_name": "v1.28.1", "draft": False},
    {"tag_name": "v1.20.1", "draft": False},
]


def _fake_gh(releases: list[dict], returncode: int = 0):
    """Stand in for ``gh api … --jq``, applying the jq filter the way gh would.

    The draft filter lives in the jq expression passed to ``gh``, so a fake that ignored
    it would pass no matter how the production filter were written. This one reads the
    real argv and honours the ``select(.draft == false)`` clause.
    """

    def _run(cmd, *args, **kwargs):
        jq = cmd[cmd.index("--jq") + 1]
        chosen = releases
        if "select(.draft == false)" in jq:
            chosen = [r for r in releases if not r["draft"]]
        tags = [r["tag_name"] for r in chosen]
        if ".[0].tag_name" in jq:  # the old, broken expression
            tags = tags[:1]
        return mock.MagicMock(returncode=returncode, stdout="\n".join(tags) + "\n")

    return _run


class TestPublishedReleaseTags:
    def test_drafts_are_excluded(self):
        with mock.patch("subprocess.run", side_effect=_fake_gh(REAL_RELEASES)):
            tags = _list_published_release_tags("Cnext-eu/kairos-ontology-referencemodels")
        assert tags is not None
        # v1.28.1 survives once (the published one), never as the draft's position.
        assert tags[0] == "v1.33.1"

    def test_ordering_is_by_version_not_creation_date(self):
        out_of_order = [
            {"tag_name": "v1.9.0", "draft": False},  # newest-created, lowest version
            {"tag_name": "v1.33.1", "draft": False},
            {"tag_name": "v1.10.0", "draft": False},
        ]
        with mock.patch("subprocess.run", side_effect=_fake_gh(out_of_order)):
            tags = _list_published_release_tags("Cnext-eu/kairos-ontology-referencemodels")
        assert tags == ["v1.33.1", "v1.10.0", "v1.9.0"]
        # Lexicographic sorting would put v1.9.0 above v1.33.1 and v1.10.0.
        assert tags != sorted(["v1.9.0", "v1.33.1", "v1.10.0"], reverse=True)

    def test_unreachable_is_none_not_empty(self):
        """``None`` (degraded) and ``[]`` (never released) must stay distinguishable."""
        with mock.patch("subprocess.run", side_effect=_fake_gh(REAL_RELEASES, returncode=1)):
            assert _list_published_release_tags("whatever") is None
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            assert _list_published_release_tags("whatever") is None
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 15)):
            assert _list_published_release_tags("whatever") is None
        with mock.patch("subprocess.run", side_effect=_fake_gh([])):
            assert _list_published_release_tags("whatever") == []

    def test_latest_stable_skips_prereleases_but_never_returns_nothing(self):
        assert _latest_stable_tag(["v2.0.0rc1", "v1.9.0"]) == "v1.9.0"
        # All pre-releases: a pin is still better than no pin.
        assert _latest_stable_tag(["v2.0.0rc2", "v2.0.0rc1"]) == "v2.0.0rc2"
        assert _latest_stable_tag([]) is None


class TestRefmodelsScaffoldPin:
    def test_pins_latest_stable_not_the_draft_at_position_zero(self):
        """The exact regression: v1.33.1, never the draft-tagged v1.28.1."""
        with mock.patch("subprocess.run", side_effect=_fake_gh(REAL_RELEASES)):
            assert _resolve_scaffold_refmodels_pin() == ("v1.33.1", "1.33.1")

    def test_prefers_stable_over_a_newer_prerelease(self):
        releases = [
            {"tag_name": "v1.34.0rc1", "draft": False},
            {"tag_name": "v1.33.1", "draft": False},
        ]
        with mock.patch("subprocess.run", side_effect=_fake_gh(releases)):
            assert _resolve_scaffold_refmodels_pin() == ("v1.33.1", "1.33.1")

    def test_explicit_version_tag_wins(self):
        """``--ref-models-version`` was accepted and silently ignored before this."""
        with mock.patch("subprocess.run", side_effect=_fake_gh(REAL_RELEASES)):
            assert _resolve_scaffold_refmodels_pin(version_tag="v1.29.0") == ("v1.29.0", "1.29.0")
            # Tolerate a bare version, since the option's help shows a v-prefixed tag.
            assert _resolve_scaffold_refmodels_pin(version_tag="1.29.0") == ("v1.29.0", "1.29.0")

    def test_unreachable_falls_back_and_says_the_pin_is_stale(self, capsys):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            tag, version = _resolve_scaffold_refmodels_pin()
        assert tag == _REFMODELS_FALLBACK_TAG
        assert version == _tag_to_version(_REFMODELS_FALLBACK_TAG)
        out = capsys.readouterr().out
        assert "stale" in out
        assert "update-refmodels" in out


class TestResolveRefmodelsTag:
    """`update-refmodels`'s own resolver (issue #551) — same policy as scaffolding
    (latest published *stable* release, draft-filtered, version-ordered), but with
    no hardcoded fallback: an upgrade protects an existing pin, so an unreachable
    release list must refuse rather than silently reuse a stale hardcoded tag."""

    def test_resolves_latest_stable_not_the_draft(self):
        with mock.patch("subprocess.run", side_effect=_fake_gh(REAL_RELEASES)):
            assert _resolve_refmodels_tag() == "v1.33.1"

    def test_explicit_version_tag_wins_and_is_v_normalized(self):
        assert _resolve_refmodels_tag(version_tag="v1.29.0") == "v1.29.0"
        assert _resolve_refmodels_tag(version_tag="1.29.0") == "v1.29.0"

    def test_unreachable_returns_none_with_no_hardcoded_fallback(self):
        """Unlike the scaffold-time resolver, this must not fall back to
        _REFMODELS_FALLBACK_TAG -- that would silently move a real pin to a
        stale tag instead of refusing."""
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            assert _resolve_refmodels_tag() is None

    def test_empty_release_list_returns_none(self):
        with mock.patch("subprocess.run", side_effect=_fake_gh([])):
            assert _resolve_refmodels_tag() is None


class TestToolkitChannelExcludesDrafts:
    """``_resolve_scaffold_toolkit_pin`` promises to only ever pin a *published*
    release, but it delegates to ``_resolve_channel``, which used to read drafts too."""

    def test_stable_channel_ignores_a_draft_release(self):
        releases = [
            {"tag_name": "v9.9.9", "draft": True},  # unpublished: no wheel to download
            {"tag_name": "v5.10.1", "draft": False},
        ]
        with mock.patch("subprocess.run", side_effect=_fake_gh(releases)):
            assert _resolve_channel("stable") == "v5.10.1"

    def test_preview_channel_ignores_a_draft_release(self):
        releases = [
            {"tag_name": "v9.9.9", "draft": True},
            {"tag_name": "v5.11.0rc1", "draft": False},
            {"tag_name": "v5.10.1", "draft": False},
        ]
        with mock.patch("subprocess.run", side_effect=_fake_gh(releases)):
            assert _resolve_channel("preview") == "v5.11.0rc1"

    def test_explicit_ref_passes_through_untouched(self):
        assert _resolve_channel("v5.10.1") == "v5.10.1"
        assert _resolve_channel("main") == "main"


def _toolkit_dev_refmodels_pin() -> str:
    """The reference-models tag this toolkit's own test suite runs against."""
    with (_REPO_ROOT / "pyproject.toml").open("rb") as fh:
        data = tomllib.load(fh)
    url = data["tool"]["uv"]["sources"]["kairos-ontology-referencemodels"]["url"]
    match = re.search(r"/releases/download/(?P<tag>[^/]+)/", url)
    assert match is not None, url
    return match.group("tag")


def test_fallback_pin_is_not_behind_the_version_the_toolkit_is_tested_against() -> None:
    """Tether the hardcoded fallback to something the repo actually maintains.

    The fallback was ``v1.20.0`` while CI validated against ``v1.33.1`` — thirteen minor
    versions of drift that nothing would have caught. This needs no network: bumping the
    dev pin (as #539 did) now forces the fallback to keep up.
    """
    dev_pin = _toolkit_dev_refmodels_pin()
    assert Version(_tag_to_version(_REFMODELS_FALLBACK_TAG)) >= Version(_tag_to_version(dev_pin)), (
        f"_REFMODELS_FALLBACK_TAG is {_REFMODELS_FALLBACK_TAG} but this toolkit is tested "
        f"against {dev_pin}. A degraded scaffold would pin reference models the toolkit "
        f"has never been run against — raise the fallback to {dev_pin}."
    )
