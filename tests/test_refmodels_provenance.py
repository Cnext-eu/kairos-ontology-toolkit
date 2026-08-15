# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for reference-model package provenance (DD-158).

The old provenance tests checked the FETCH_PROVENANCE.json writer and the
sparse-clone ``update-refmodels --ref`` flow.  Both are gone.  Provenance is
now read from the installed package metadata via ``importlib.metadata``.
"""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.cli.shared import (
    _read_refmodels_provenance,
    _format_refmodels_fetch_provenance,
)


_PARTY_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<https://kairos.cnext.eu/ref/party> a owl:Ontology ;
    rdfs:label "Party" .

<https://kairos.cnext.eu/ref/party#Party> a owl:Class ;
    rdfs:label "Party" .
"""


def test_read_refmodels_provenance_returns_package_version():
    """_read_refmodels_provenance returns version from importlib.metadata."""
    with patch("importlib.metadata.version", return_value="1.19.0"):
        prov = _read_refmodels_provenance()
    assert prov is not None
    assert prov["version"] == "1.19.0"
    assert prov["ref"] == "1.19.0"
    assert prov["source"] == "pip"


def test_read_refmodels_provenance_returns_none_when_not_installed():
    """_read_refmodels_provenance returns None when package is not installed."""
    import importlib.metadata as md

    with patch("importlib.metadata.version", side_effect=md.PackageNotFoundError("x")):
        prov = _read_refmodels_provenance()
    assert prov is None


def test_format_refmodels_provenance_returns_label():
    """_format_refmodels_fetch_provenance returns 'v<version> (pip)' label."""
    with patch("importlib.metadata.version", return_value="1.20.0"):
        label = _format_refmodels_fetch_provenance(Path("/nonexistent"))
        assert label == "v1.20.0 (pip)"


def test_format_refmodels_provenance_returns_none_when_not_installed():
    """_format_refmodels_fetch_provenance returns None when package is not installed."""
    import importlib.metadata as md

    with patch("importlib.metadata.version", side_effect=md.PackageNotFoundError("x")):
        label = _format_refmodels_fetch_provenance(Path("/nonexistent"))
    assert label is None


def test_check_inventory_surfaces_refmodels_provenance(tmp_path):
    """check-inventory output includes the package version and provenance label."""
    refmodels = tmp_path / "ontology-reference-models"
    inventory = tmp_path / "referencemodels-unpacked"
    refmodels.mkdir()
    inventory.mkdir()
    (refmodels / "VERSION").write_text("2026.07\n", encoding="utf-8")

    with patch("importlib.metadata.version", return_value="1.20.0"):
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
    assert "Reference models provenance: v1.20.0 (pip)" in result.output


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

    result = runner.invoke(
        cli,
        ["check-inventory", "--domains", "party", "--explain-scope",
         "--ref-models-dir", str(refmodels)],
    )

    assert result.exit_code == 0, result.output
    assert "Reference models VERSION: not present" in result.output
    assert "party: matched direct inventory" in result.output
    assert "inventories are ready" in result.output
