# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the generate-inventory CLI command (DD-044)."""

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli

SAMPLE_REF_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ref-party: <https://kairos.cnext.eu/ref/party#> .

<https://kairos.cnext.eu/ref/party> a owl:Ontology ;
    rdfs:label "Party" .

ref-party:Party a owl:Class ;
    rdfs:label "Party" .

ref-party:Organisation a owl:Class ;
    rdfs:subClassOf ref-party:Party ;
    rdfs:label "Organisation" .

ref-party:partyName a owl:DatatypeProperty ;
    rdfs:domain ref-party:Party ;
    rdfs:range xsd:string .

ref-party:regNumber a owl:DatatypeProperty ;
    rdfs:domain ref-party:Organisation ;
    rdfs:range xsd:string .
"""


class TestGenerateInventoryCLI:

    def test_generates_ref_model_inventory(self, tmp_path):
        ref_dir = tmp_path / "model" / "reference-models"
        ref_dir.mkdir(parents=True)
        (ref_dir / "party.ttl").write_text(SAMPLE_REF_TTL, encoding="utf-8")

        out_dir = tmp_path / "model" / "inventory"

        runner = CliRunner()
        result = runner.invoke(cli, [
            "generate-inventory",
            "--ref-models-dir", str(ref_dir),
            "--output-dir", str(out_dir),
        ])

        assert result.exit_code == 0, result.output
        assert "Generated" in result.output

        yaml_file = out_dir / "party-inventory.yaml"
        assert yaml_file.exists()

        with open(yaml_file, encoding="utf-8") as f:
            inv = yaml.safe_load(f)

        assert inv["domain_name"] == "Party"
        assert len(inv["classes"]) >= 2

        party_cls = next(c for c in inv["classes"] if c["name"] == "Party")
        assert "specializations" in party_cls
        spec_names = {s["class"] for s in party_cls["specializations"]}
        assert "Organisation" in spec_names

    def test_generates_domain_ontology_inventory(self, tmp_path):
        ont_dir = tmp_path / "model" / "ontologies"
        ont_dir.mkdir(parents=True)
        (ont_dir / "client.ttl").write_text(
            """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://acme.example/ontology/client> a owl:Ontology ; rdfs:label "Client" .
<https://acme.example/ontology/client#Customer> a owl:Class ; rdfs:label "Customer" .
""",
            encoding="utf-8",
        )

        out_dir = tmp_path / "model" / "inventory"

        runner = CliRunner()
        result = runner.invoke(cli, [
            "generate-inventory",
            "--ontology-dir", str(ont_dir),
            "--output-dir", str(out_dir),
        ])

        assert result.exit_code == 0, result.output
        yaml_file = out_dir / "client-inventory.yaml"
        assert yaml_file.exists()

        with open(yaml_file, encoding="utf-8") as f:
            inv = yaml.safe_load(f)

        assert inv["domain_name"] == "Client"
        # Domain ontologies don't include specializations
        customer = next(c for c in inv["classes"] if c["name"] == "Customer")
        assert "specializations" not in customer

    def test_no_dirs_fails(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "generate-inventory",
            "--ontology-dir", str(tmp_path / "nonexistent"),
        ])
        assert result.exit_code != 0
