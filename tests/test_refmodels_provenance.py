# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for reference-model fetch provenance."""

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.cli.shared import _write_refmodels_fetch_provenance


_PARTY_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<https://kairos.cnext.eu/ref/party> a owl:Ontology ;
    rdfs:label "Party" .

<https://kairos.cnext.eu/ref/party#Party> a owl:Class ;
    rdfs:label "Party" .
"""


def test_refmodels_provenance_writer_keeps_ref_and_commit_separate(tmp_path):
    """Fetch provenance records ref and commit without inventing a semantic VERSION."""
    dest = tmp_path / "ontology-reference-models"
    dest.mkdir()

    path = _write_refmodels_fetch_provenance(
        dest,
        ref="release/2026.07",
        commit="abcdef1234567890",
        source_repo="https://example.test/refmodels.git",
        fetched_at="2026-07-28T14:50:28Z",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "commit": "abcdef1234567890",
        "fetched_at": "2026-07-28T14:50:28Z",
        "ref": "release/2026.07",
        "source_repo": "https://example.test/refmodels.git",
    }
    assert "VERSION" not in payload
    assert "version" not in payload


def test_refmodels_provenance_writer_records_unknown_commit_as_null(tmp_path):
    """Fetch provenance is truthful when a fetch path cannot resolve a commit."""
    dest = tmp_path / "ontology-reference-models"
    dest.mkdir()

    path = _write_refmodels_fetch_provenance(
        dest,
        ref="main",
        commit=None,
        fetched_at="2026-07-28T14:50:28Z",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["ref"] == "main"
    assert payload["commit"] is None


def test_update_refmodels_persists_resolved_fetch_provenance(tmp_path):
    """The fetch flow persists requested ref and resolved commit after copying the subtree."""
    dest = tmp_path / "ontology-reference-models"
    fake_clone_dir = tmp_path / "fake-clone"
    fake_refmodels = fake_clone_dir / "ontology-reference-models"
    fake_refmodels.mkdir(parents=True)
    (fake_refmodels / "party.ttl").write_text("# Party reference model\n", encoding="utf-8")

    def mock_run_side_effect(cmd, **kwargs):
        if cmd[0] == "git" and cmd[1] == "--version":
            return MagicMock(returncode=0)
        if cmd[0] == "git" and cmd[1] == "clone":
            clone_dest = Path(cmd[-1])
            if clone_dest.exists():
                shutil.rmtree(clone_dest)
            shutil.copytree(fake_clone_dir, clone_dest)
            return MagicMock(returncode=0)
        if cmd[0] == "git" and "sparse-checkout" in cmd:
            return MagicMock(returncode=0)
        if cmd[0] == "git" and "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout="abcdef1234567890\n")
        return MagicMock(returncode=0)

    with patch("kairos_ontology.cli.operations.subprocess.run", side_effect=mock_run_side_effect):
        result = CliRunner().invoke(
            cli,
            ["update-refmodels", "--ref", "release/2026.07", "--dest", str(dest)],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads((dest / "FETCH_PROVENANCE.json").read_text(encoding="utf-8"))
    assert payload["ref"] == "release/2026.07"
    assert payload["commit"] == "abcdef1234567890"
    assert "VERSION" not in payload
    assert "version" not in payload


def test_check_inventory_surfaces_refmodels_provenance(tmp_path):
    """Gate-0 inventory output includes semantic VERSION plus fetch ref and short commit."""
    refmodels = tmp_path / "ontology-reference-models"
    inventory = tmp_path / "referencemodels-unpacked"
    refmodels.mkdir()
    inventory.mkdir()
    (refmodels / "VERSION").write_text("2026.07\n", encoding="utf-8")
    _write_refmodels_fetch_provenance(
        refmodels,
        ref="main",
        commit="abcdef1234567890",
        fetched_at="2026-07-28T14:50:28Z",
    )

    result = CliRunner().invoke(
        cli,
        [
            "check-inventory",
            "--ref-models-dir",
            str(refmodels),
            "--inventory-dir",
            str(inventory),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Reference models VERSION: 2026.07" in result.output
    assert "Reference models provenance: ref main @ abcdef123456" in result.output


def test_check_inventory_reports_present_refmodels_version(tmp_path):
    """A populated VERSION is reported as the local reference-model version."""
    refmodels = tmp_path / "ontology-reference-models"
    inventory = tmp_path / "referencemodels-unpacked"
    refmodels.mkdir()
    inventory.mkdir()
    (refmodels / "VERSION").write_text("2026.08\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "check-inventory",
            "--ref-models-dir",
            str(refmodels),
            "--inventory-dir",
            str(inventory),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Reference models VERSION: 2026.08" in result.output


def test_check_inventory_missing_refmodels_version_is_informative_and_non_blocking(
    tmp_path, monkeypatch
):
    """A missing VERSION is reported separately from unreadable metadata and stays non-blocking."""
    refmodels = tmp_path / "ontology-reference-models"
    refmodels.mkdir()
    (refmodels / "party.ttl").write_text(_PARTY_TTL, encoding="utf-8")
    (tmp_path / "model" / "ontologies").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    generated = runner.invoke(cli, ["generate-inventory"])
    assert generated.exit_code == 0, generated.output

    result = runner.invoke(cli, ["check-inventory", "--domains", "party", "--explain-scope"])

    assert result.exit_code == 0, result.output
    assert "Reference models VERSION: not present" in result.output
    assert "unknown" not in result.output
    assert "party: matched direct inventory" in result.output
    assert "Inventories are present and up to date" in result.output
