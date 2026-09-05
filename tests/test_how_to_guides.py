# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The how-to guides must stay executable, not merely plausible.

Documentation that names a command or a flag which no longer exists is worse than none:
it reads authoritative and fails on contact. Every `kairos-ontology ...` invocation in
`docs/guide/how-to/` is parsed out of its fenced block and checked against the real Click tree,
so renaming a flag breaks the build rather than the reader.
"""

from __future__ import annotations

import re
from pathlib import Path

import click
import pytest

from kairos_ontology.cli.main import cli

_HOW_TO = Path(__file__).resolve().parent.parent / "docs" / "guide" / "how-to"
_FENCE = re.compile(r"```(?:bash|sh|shell|powershell)?\n(.*?)```", re.DOTALL)


def _guides() -> list[Path]:
    return sorted(path for path in _HOW_TO.glob("*.md") if path.name != "README.md")


def _invocations(text: str) -> list[list[str]]:
    """Return the token list of every `kairos-ontology ...` line in a fenced block."""
    found: list[list[str]] = []
    for block in _FENCE.findall(text):
        # rejoin backslash-continued lines before splitting
        joined = re.sub(r"\\\n\s*", " ", block)
        for line in joined.splitlines():
            line = line.strip()
            if not line.startswith("kairos-ontology "):
                continue
            found.append(line.split()[1:])
    return found


def _resolve(tokens: list[str]) -> tuple[click.Command | None, list[str], str]:
    """Walk the command tree by leading tokens. Returns (command, rest, path)."""
    command: click.Command = cli
    path: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("-"):
            break
        if isinstance(command, click.Group) and token in command.commands:
            command = command.commands[token]
            path.append(token)
            index += 1
            continue
        break
    if not path:
        return None, tokens, " ".join(tokens[:1])
    return command, tokens[index:], " ".join(path)


def _declared_flags(command: click.Command) -> set[str]:
    flags: set[str] = {"--help"}
    for param in command.params:
        flags.update(param.opts)
        flags.update(param.secondary_opts)
    return {flag for flag in flags if flag.startswith("--")}


def test_guides_exist():
    assert _guides(), "no how-to guides found"


@pytest.mark.parametrize("guide", _guides(), ids=lambda p: p.name)
def test_every_command_invoked_exists(guide: Path):
    text = guide.read_text(encoding="utf-8")
    unknown = []
    for tokens in _invocations(text):
        command, _rest, path = _resolve(tokens)
        if command is None:
            unknown.append(" ".join(tokens))
    assert not unknown, f"{guide.name} invokes commands that do not exist:\n" + "\n".join(unknown)


@pytest.mark.parametrize("guide", _guides(), ids=lambda p: p.name)
def test_every_flag_used_exists_on_its_command(guide: Path):
    """The failure mode a reader actually hits: right command, renamed flag."""
    text = guide.read_text(encoding="utf-8")
    offenders = []
    for tokens in _invocations(text):
        command, rest, path = _resolve(tokens)
        if command is None:
            continue  # reported by the test above
        declared = _declared_flags(command)
        for token in rest:
            if not token.startswith("--"):
                continue
            flag = token.split("=", 1)[0]
            if flag not in declared:
                offenders.append(f"{path}: {flag}")
    assert not offenders, f"{guide.name} uses flags that do not exist:\n" + "\n".join(offenders)


@pytest.mark.parametrize("guide", _guides(), ids=lambda p: p.name)
def test_relative_links_resolve(guide: Path):
    text = guide.read_text(encoding="utf-8")
    text = re.sub(r"`[^`]*`", "", re.sub(r"```.*?```", "", text, flags=re.DOTALL))
    broken = []
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        path = target.split("#", 1)[0]
        if path and not (guide.parent / path).resolve().exists():
            broken.append(target)
    assert not broken, f"{guide.name} has broken links:\n" + "\n".join(broken)


def test_index_lists_every_guide():
    """A guide nobody links to is a guide nobody finds."""
    index = (_HOW_TO / "README.md").read_text(encoding="utf-8")
    missing = [guide.name for guide in _guides() if f"({guide.name})" not in index]
    assert not missing, "guides missing from docs/guide/how-to/README.md:\n" + "\n".join(missing)


def test_every_guide_names_its_skill_or_says_there_is_none():
    """Each recipe should say which skill automates it, so the reader can prefer it."""
    missing = [
        guide.name
        for guide in _guides()
        if not re.search(r"^\*\*Skills?:\*\*", guide.read_text(encoding="utf-8"), re.MULTILINE)
    ]
    assert not missing, "guides with no skill line:\n" + "\n".join(missing)


class TestRecipesActuallyRun:
    """The create-a-hub recipe, executed. Prose that has never been run is a guess.

    Writing these guides against the CLI reference was not enough: the first draft told
    the reader to verify a fresh hub with `kairos-ontology validate`, which fails on a
    fresh hub because the business-discovery gate has not been cleared. Only running it
    surfaced that.
    """

    @staticmethod
    def _init(runner, args=("init", "--company-domain", "acme.example", "--domain", "party")):
        from kairos_ontology.cli.main import cli as _cli

        return runner.invoke(_cli, list(args))

    def test_create_a_hub_then_update_check(self, tmp_path):
        from unittest import mock

        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli as _cli

        runner = CliRunner()
        with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)
            with runner.isolated_filesystem(temp_dir=tmp_path):
                created = self._init(runner)
                assert created.exit_code == 0, created.output
                checked = runner.invoke(_cli, ["update", "--check"])

        assert checked.exit_code == 0, checked.output

    def test_validate_is_gated_on_discovery_as_the_guide_says(self, tmp_path):
        """`create-a-hub.md` tells the reader not to expect `validate` to pass yet.

        If that stops being true the guide is wrong, so pin it rather than trusting the
        prose to stay accurate.
        """
        from unittest import mock

        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli as _cli

        runner = CliRunner()
        with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)
            with runner.isolated_filesystem(temp_dir=tmp_path):
                assert self._init(runner).exit_code == 0
                validated = runner.invoke(_cli, ["validate"])

        assert validated.exit_code != 0
        assert "business discovery" in validated.output.lower(), validated.output

        guide = (_HOW_TO / "create-a-hub.md").read_text(encoding="utf-8")
        assert "No business discovery evidence found" in guide
