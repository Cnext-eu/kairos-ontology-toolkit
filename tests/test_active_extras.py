# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Optional extras must survive an upgrade (#878).

`uv sync` with no `--extra` installs the default set and removes everything else, so
every `update --upgrade`, `--test-ref` and `--restore` uninstalled whatever extras the
hub was running on. For a hub configured against Azure Foundry that is the provider SDK,
and the next AI-backed command fails on a package nobody removed on purpose.
"""

from kairos_ontology.cli.shared import uv_sync_command
from kairos_ontology.core.active_extras import _SAFE_EXTRA_RE, active_extras

PYPROJECT = """\
[project]
name = "a-hub"
version = "0.1.0"
dependencies = ["kairos-ontology-toolkit"]

[project.optional-dependencies]
installed = ["pytest"]
absent = ["a-package-that-is-not-installed-anywhere"]
empty = []
"""


def _hub(tmp_path, body=PYPROJECT):
    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")
    return tmp_path


class TestActiveExtras:
    def test_an_extra_whose_dependency_is_installed_is_active(self, tmp_path):
        assert "installed" in active_extras(_hub(tmp_path))

    def test_an_extra_whose_dependency_is_missing_is_not(self, tmp_path):
        assert "absent" not in active_extras(_hub(tmp_path))

    def test_an_empty_extra_is_not_reported(self, tmp_path):
        assert "empty" not in active_extras(_hub(tmp_path))

    def test_no_pyproject_is_not_an_error(self, tmp_path):
        assert active_extras(tmp_path) == []

    def test_a_malformed_pyproject_is_not_an_error(self, tmp_path):
        assert active_extras(_hub(tmp_path, "this is not: valid: toml: [[[")) == []

    def test_a_self_referential_extra_expands_through_the_named_package(self, tmp_path):
        """`kairos-ontology-toolkit[foundry]` is the shape every scaffolded hub uses.

        The bare distribution is always installed, so checking it would call every
        extra active; the extra has to resolve through the package's own metadata.
        """
        hub = _hub(
            tmp_path,
            PYPROJECT + '\nselfref = ["kairos-ontology-toolkit[a-nonexistent-extra]"]\n',
        )

        assert "selfref" not in active_extras(hub)


class TestUvSyncCommand:
    def test_active_extras_become_flags(self, tmp_path):
        command = uv_sync_command(_hub(tmp_path))

        assert command[:2] == ["uv", "sync"]
        assert "--extra" in command
        assert "installed" in command
        assert "absent" not in command

    def test_a_hub_with_no_extras_still_syncs(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "a"\nversion = "0.1.0"\n', encoding="utf-8"
        )

        assert uv_sync_command(tmp_path) == ["uv", "sync"]


EVIL_EXTRA = '\n"evil; rm -rf /" = ["pytest"]\n'
SPACED_EXTRA = '\n"two words" = ["pytest"]\n'


class TestExtraNameSafety:
    """Extra names are interpolated into the Windows refresh shell's command line.

    They come from a TOML key in the working tree, and a TOML key may be any quoted
    string — so an ill-formed one would be a command injection into that shell.
    """

    def test_a_shell_metacharacter_name_is_ignored(self, tmp_path):
        detected = active_extras(_hub(tmp_path, PYPROJECT + EVIL_EXTRA))

        assert "installed" in detected, "the well-formed extras still resolve"
        assert not any(";" in name for name in detected)

    def test_a_whitespace_name_is_ignored(self, tmp_path):
        detected = active_extras(_hub(tmp_path, PYPROJECT + SPACED_EXTRA))

        assert not any(" " in name for name in detected)

    def test_every_detected_name_is_shell_safe(self, tmp_path):
        for name in active_extras(_hub(tmp_path, PYPROJECT + EVIL_EXTRA + SPACED_EXTRA)):
            assert _SAFE_EXTRA_RE.match(name), name
