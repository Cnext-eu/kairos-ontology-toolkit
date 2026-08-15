# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The scaffolded hub pins the toolkit version exactly once (issue #297).

A hub used to repeat the toolkit release-wheel URL five times — once in
``[project.dependencies]`` and once per extra — each copy embedding both the tag and
the PEP 440 version.  Nothing kept the five in agreement, and
``_read_pinned_toolkit_version`` only ever read the first, so a hub could report a
version it was not running.  Extras of the same distribution resolve through the single
direct reference, so there is exactly one URL now.

These tests also cover the shared pin policy used by both scaffolders (``init`` and
``new-repo``), which previously disagreed: ``init`` resolved the ``stable`` channel
while ``new-repo`` pinned the *running* toolkit version, which for a development build
has no published release at all.
"""

import re
import tomllib
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner
from packaging.version import Version

from kairos_ontology.cli.main import cli
from kairos_ontology.cli.shared import (
    _TOOLKIT_RELEASE_URL_RE,
    _read_hub_channel,
    _resolve_scaffold_toolkit_pin,
    _tag_to_version,
)

TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "kairos_ontology"
    / "scaffold"
    / "pyproject.toml.template"
)

USER_FACING_EXTRAS = ("azure", "foundry", "flatfile", "parquet", "otel")

# A tag whose PEP 440 form differs from the tag text, so a template that reused
# {toolkit_ref} where {toolkit_version} belongs cannot pass by accident.
REF = "v9.9.0-rc.3"
VERSION = "9.9.0rc3"

# The release list as it really is: every release after v5.0.2 is a pre-release, so
# `stable` resolves to an ancient version while `preview` tracks the current one.
FAKE_STABLE = "v5.0.2"
FAKE_PREVIEW = "v5.2.0rc12"
RUNNING = "5.2.0rc17"  # a development build: no published release


def _render(ref: str = REF, channel: str = "stable") -> str:
    """Render the template the way ``init`` / ``new-repo`` do."""
    return (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("{repo_name}", "acme-ontology-hub")
        .replace("{description}", "acme-ontology-hub")
        .replace("{toolkit_ref}", ref)
        .replace("{toolkit_version}", _tag_to_version(ref))
        .replace("{toolkit_channel}", channel)
        .replace("{refmodels_ref}", "v1.20.0")
        .replace("{refmodels_version}", "1.20.0")
    )


def _fake_resolve_channel(channel: str) -> str | None:
    if channel == "stable":
        return FAKE_STABLE
    if channel == "preview":
        return FAKE_PREVIEW
    return channel


class TestTemplateDeclaresOnePin:
    def test_version_and_ref_placeholders_appear_exactly_once(self):
        raw = TEMPLATE.read_text(encoding="utf-8")
        assert raw.count("{toolkit_version}") == 1
        assert raw.count("{toolkit_ref}") == 1

    def test_exactly_one_direct_reference_url_with_agreeing_tag_and_version(self):
        """One URL, and its tag and wheel filename version describe the same release.

        A tag/version disagreement *inside* a single URL is invisible to any test that
        only checks that all URLs are equal.
        """
        urls = _TOOLKIT_RELEASE_URL_RE.findall(_render())
        assert len(urls) == 1, f"expected exactly one toolkit URL, got {urls}"
        match = re.fullmatch(
            r".+/releases/download/(?P<tag>[^/]+)/"
            r"kairos_ontology_toolkit-(?P<version>.+)-py3-none-any\.whl",
            urls[0],
        )
        assert match is not None, urls[0]
        assert _tag_to_version(match.group("tag")) == match.group("version")
        assert match.group("tag") == REF
        assert match.group("version") == VERSION

    def test_every_user_facing_extra_is_a_bare_requirement(self):
        """Extras must carry no URL — the base dependency is the only pin."""
        optional = tomllib.loads(_render())["project"]["optional-dependencies"]
        for extra in USER_FACING_EXTRAS:
            assert optional[extra] == [f"kairos-ontology-toolkit[{extra}]"], (
                f"extra '{extra}' must be a bare requirement resolving through the single "
                f"direct reference, got {optional.get(extra)}"
            )

    def test_render_leaves_no_unsubstituted_placeholder(self):
        rendered = _render()
        assert not re.search(r"\{[a-z_]+\}", rendered), rendered


class TestSharedScaffoldPinPolicy:
    """`init` and `new-repo` share one policy: pin a published release, never behind
    the running toolkit, and write the channel that matches the pin."""

    def test_prefers_stable_when_stable_is_current(self):
        with (
            mock.patch(
                "kairos_ontology.cli.shared._resolve_channel", side_effect=_fake_resolve_channel
            ),
            mock.patch("kairos_ontology.cli.shared._toolkit_version", "5.0.2"),
        ):
            assert _resolve_scaffold_toolkit_pin() == (FAKE_STABLE, "stable")

    def test_uses_preview_when_stable_is_behind_the_running_toolkit(self):
        with (
            mock.patch(
                "kairos_ontology.cli.shared._resolve_channel", side_effect=_fake_resolve_channel
            ),
            mock.patch("kairos_ontology.cli.shared._toolkit_version", RUNNING),
        ):
            assert _resolve_scaffold_toolkit_pin() == (FAKE_PREVIEW, "preview")

    def test_keeps_stable_when_preview_is_no_newer(self):
        with (
            mock.patch(
                "kairos_ontology.cli.shared._resolve_channel",
                side_effect=lambda channel: FAKE_STABLE,
            ),
            mock.patch("kairos_ontology.cli.shared._toolkit_version", RUNNING),
        ):
            assert _resolve_scaffold_toolkit_pin() == (FAKE_STABLE, "stable")

    def test_never_pins_the_running_dev_version_when_a_release_is_reachable(self):
        with (
            mock.patch(
                "kairos_ontology.cli.shared._resolve_channel", side_effect=_fake_resolve_channel
            ),
            mock.patch("kairos_ontology.cli.shared._toolkit_version", RUNNING),
        ):
            ref, _ = _resolve_scaffold_toolkit_pin()
        assert ref != f"v{RUNNING}"
        assert ref in (FAKE_STABLE, FAKE_PREVIEW)

    def test_last_resort_falls_back_to_running_version_and_says_so(self, capsys):
        with (
            mock.patch("kairos_ontology.cli.shared._resolve_channel", return_value=None),
            mock.patch("kairos_ontology.cli.shared._toolkit_version", RUNNING),
        ):
            assert _resolve_scaffold_toolkit_pin() == (f"v{RUNNING}", "stable")
        out = capsys.readouterr().out
        assert "may not be published" in out
        assert "update --upgrade" in out


def _pin_of(pyproject: Path) -> str:
    urls = _TOOLKIT_RELEASE_URL_RE.findall(pyproject.read_text(encoding="utf-8"))
    assert len(urls) == 1, urls
    return re.search(r"/releases/download/([^/]+)/", urls[0]).group(1)


class TestScaffoldedHubPinAgreesWithItsChannel:
    """A fresh hub must not be born already needing (or refusing) an upgrade."""

    def test_init_pin_is_not_older_than_its_channel_resolves_to(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with (
            mock.patch(
                "kairos_ontology.cli.shared._resolve_channel", side_effect=_fake_resolve_channel
            ),
            mock.patch("kairos_ontology.cli.shared._toolkit_version", RUNNING),
        ):
            result = CliRunner().invoke(
                cli,
                ["init", "--company-domain", "acme.com", "--skip-refmodels"],
            )
            assert result.exit_code == 0, result.output

            pin = _pin_of(tmp_path / "pyproject.toml")
            channel = _read_hub_channel()
            resolved = _fake_resolve_channel(channel)

            # The channel this hub follows must not resolve behind its own pin:
            # `update --upgrade` would otherwise be an immediate downgrade.
            assert Version(_tag_to_version(resolved)) >= Version(_tag_to_version(pin))
            # And the pin must be the newest published release, not the newest
            # *non*-pre-release two minor versions behind the toolkit that scaffolded it.
            assert pin == FAKE_PREVIEW
            assert channel == "preview"

    def test_new_repo_uses_the_same_policy_as_init(self, tmp_path):
        with (
            mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run,
            mock.patch(
                "kairos_ontology.cli.shared._resolve_channel", side_effect=_fake_resolve_channel
            ),
            mock.patch("kairos_ontology.cli.shared._toolkit_version", RUNNING),
        ):
            mock_run.return_value = mock.MagicMock(returncode=0)
            result = CliRunner().invoke(cli, ["new-repo", "acme", "--path", str(tmp_path)])
        assert result.exit_code == 0, result.output

        pyproject = tmp_path / "acme-ontology-hub" / "pyproject.toml"
        assert _pin_of(pyproject) == FAKE_PREVIEW
        content = pyproject.read_text(encoding="utf-8")
        assert 'channel = "preview"' in content
        # The running (unpublished) development version must never become the pin.
        assert RUNNING not in content


@pytest.mark.parametrize("extra", USER_FACING_EXTRAS)
def test_toolkit_actually_ships_every_scaffolded_extra(extra):
    """A bare ``kairos-ontology-toolkit[<extra>]`` only resolves if the wheel declares it."""
    toolkit_pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with toolkit_pyproject.open("rb") as fh:
        data = tomllib.load(fh)
    assert extra in data["project"]["optional-dependencies"]
