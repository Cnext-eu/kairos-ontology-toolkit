# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Package-data contract for the lean v5 hub scaffold."""

from pathlib import Path

import kairos_ontology


def test_packaged_v5_scaffold_contract() -> None:
    scaffold = Path(kairos_ontology.__file__).parent / "scaffold"
    required = {
        "ontology-hub/kairos.yaml.template",
        "ontology-hub/catalog-v001.xml.template",
        "ontology-hub/model/ontologies/master.ttl.template",
        "ontology-hub/model/ontologies/foundation.ttl.template",
        "ontology-hub/model/ontologies/starter.ttl.template",
        "ontology-hub/model/shapes/README.md",
        "ontology-hub/integration/bindings/README.md",
        "ontology-hub/integration/sources/README.md",
        "ontology-hub/integration/transforms/dbt/README.md",
    }
    retired = {
        "ontology-hub/model/governance/release-baseline.yaml",
        "ontology-hub/model/extensions/silver-ext.ttl.template",
        "ontology-hub/integration/preparation/source-prep.ttl.template",
        "ontology-hub/integration/transforms/dbt/evidence/README.md",
    }

    assert all((scaffold / path).is_file() for path in required)
    assert all(not (scaffold / path).exists() for path in retired)


def _git_identity(monkeypatch):
    """Give the scaffold's `git commit` an identity on runners that have none.

    `new-repo` makes a real initial commit. Locally a developer's global config
    supplies user.name/email; CI runners have neither, and git fails with
    "Author identity unknown". Environment variables outrank config, so this
    also cannot leak a developer's real identity into test fixtures.
    """
    for key, value in (
        ("GIT_AUTHOR_NAME", "kairos-tests"),
        ("GIT_AUTHOR_EMAIL", "tests@example.invalid"),
        ("GIT_COMMITTER_NAME", "kairos-tests"),
        ("GIT_COMMITTER_EMAIL", "tests@example.invalid"),
    ):
        monkeypatch.setenv(key, value)


def test_new_repo_local_only_skips_github(tmp_path, monkeypatch):
    """--local-only scaffolds a hub with no remote, for toolkit-iteration use.

    _create_github_repo hard-fails when a remote cannot be made ("repos must never be
    local-only"), which is correct for a client hub and blocks a throwaway hub whose
    whole purpose is exercising the toolkit end to end.
    """
    from unittest import mock

    _git_identity(monkeypatch)

    from click.testing import CliRunner

    from kairos_ontology.cli.main import cli

    with mock.patch("kairos_ontology.cli.setup._create_github_repo") as create, mock.patch(
        "kairos_ontology.cli.setup._configure_branch_protection"
    ) as protect:
        result = CliRunner().invoke(
            cli,
            [
                "new-repo",
                "looptest",
                "--path",
                str(tmp_path),
                "--company-domain",
                "example.com",
                "--local-only",
            ],
        )

    assert result.exit_code == 0, result.output
    create.assert_not_called()
    protect.assert_not_called()
    repo = tmp_path / "looptest-ontology-hub"
    assert (repo / "pyproject.toml").is_file()
    assert (repo / ".git").is_dir()
    # The command must say how to publish later rather than silently leaving no remote.
    assert "gh repo create" in result.output


def test_root_env_example_matches_the_scaffold_copy():
    """The toolkit repo ships the same AI-config template it scaffolds into hubs.

    Without a committed root copy, a contributor cloning the toolkit has no template
    at all -- the only one lives under scaffold/ as packaged data for hubs. Two copies
    invite drift, so they are asserted byte-identical, the same way the two skill trees
    are (see test_v5_skill_scenario).
    """
    root = Path(__file__).resolve().parents[1]
    scaffold = root / "src" / "kairos_ontology" / "scaffold" / ".env.example"
    committed = root / ".env.example"
    assert committed.is_file(), "toolkit root is missing .env.example"
    assert committed.read_bytes() == scaffold.read_bytes()


def test_new_repo_emits_env_example_into_the_initial_commit(tmp_path, monkeypatch):
    """A --local-only hub must be self-describing before `init` ever runs."""
    import subprocess
    from unittest import mock

    _git_identity(monkeypatch)

    from click.testing import CliRunner

    from kairos_ontology.cli.main import cli

    with mock.patch("kairos_ontology.cli.setup._create_github_repo"), mock.patch(
        "kairos_ontology.cli.setup._configure_branch_protection"
    ):
        result = CliRunner().invoke(
            cli,
            [
                "new-repo",
                "envtest",
                "--path",
                str(tmp_path),
                "--company-domain",
                "example.com",
                "--local-only",
            ],
        )
    assert result.exit_code == 0, result.output

    repo = tmp_path / "envtest-ontology-hub"
    assert (repo / ".env.example").is_file()
    tracked = subprocess.run(
        ["git", "ls-files", ".env.example"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert ".env.example" in tracked, "emitted after git init, so it missed the first commit"
