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


def test_new_repo_local_only_skips_github(tmp_path, monkeypatch):
    """--local-only scaffolds a hub with no remote, for toolkit-iteration use.

    _create_github_repo hard-fails when a remote cannot be made ("repos must never be
    local-only"), which is correct for a client hub and blocks a throwaway hub whose
    whole purpose is exercising the toolkit end to end.
    """
    from unittest import mock

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
