# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""`docs/CLI_REFERENCE.md` is generated, and must not drift from the command tree.

The hand-written reference it replaced had fallen 14 commands behind -- `alignment-report`,
`generate-bindings`, `profile-sources`, `promote-transform`, `validate-source-bindings` and
nine others were registered and documented nowhere. A reference is a projection of the
code, so it is derived and this test is what stops the projection going stale.
"""

from __future__ import annotations

import click
import pytest

from kairos_ontology.cli.main import cli
from scripts.generate_cli_reference import OUTPUT, render


@pytest.fixture(scope="module")
def generated() -> str:
    return render(cli)


def test_committed_file_matches_the_command_tree(generated):
    assert OUTPUT.is_file(), "docs/CLI_REFERENCE.md is missing -- run the generator"
    current = OUTPUT.read_text(encoding="utf-8")
    assert current == generated, (
        "docs/CLI_REFERENCE.md is out of date with the CLI.\n"
        "Run: python scripts/generate_cli_reference.py"
    )


def test_every_registered_command_is_documented(generated):
    """States the property directly, so the failure names the missing command.

    A whole-file comparison would also catch this, but only as "the file differs".
    """
    missing = [name for name in sorted(cli.commands) if f"\n## {name}\n" not in generated]
    assert not missing, "commands absent from the reference:\n" + "\n".join(missing)


def test_subcommands_of_groups_are_documented(generated):
    """`decision`, `feedback`, `discovery-conformance` and `source-disposition` are groups.

    Documenting only the group would hide every verb underneath it.
    """
    missing = []
    for name, command in sorted(cli.commands.items()):
        if not isinstance(command, click.Group):
            continue
        for sub in sorted(command.commands):
            if getattr(command.commands[sub], "hidden", False):
                continue
            if f"\n## {name} {sub}\n" not in generated:
                missing.append(f"{name} {sub}")
    assert not missing, "subcommands absent from the reference:\n" + "\n".join(missing)


def test_generation_is_deterministic():
    """Two renders of the same tree must be byte-identical, or the test above flaps."""
    assert render(cli) == render(cli)


def test_index_links_resolve_to_headings(generated):
    """Every index row must point at a heading that exists in the same file."""
    import re

    headings = {line[3:].strip() for line in generated.splitlines() if line.startswith("## ")}
    anchors = re.findall(r"^\| \[`([^`]+)`\]\(#([^)]+)\) \|", generated, re.MULTILINE)
    assert anchors, "index table did not parse"

    broken = [name for name, _ in anchors if name not in headings]
    assert not broken, "index rows with no matching heading:\n" + "\n".join(broken)
