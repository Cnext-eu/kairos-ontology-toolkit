# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for hub-authored domain ontology catalog wiring."""

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.catalog_utils import sync_domain_catalog_entry


CATALOG_NS = "urn:oasis:names:tc:entity:xmlns:xml:catalog"


def _catalog_root(catalog_path: Path) -> ET.Element:
    return ET.parse(catalog_path).getroot()


def _uri_entries(catalog_path: Path) -> list[ET.Element]:
    return _catalog_root(catalog_path).findall(f"{{{CATALOG_NS}}}uri")


def test_init_registers_created_domain_ontology_iri_in_catalog(tmp_path):
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["init", "--company-domain", "contoso.example", "--domain", "customer"],
            )

            assert result.exit_code == 0, result.output
            catalog = Path("ontology-hub/catalog-v001.xml")
            entries = {
                entry.get("name"): entry.get("uri")
                for entry in _uri_entries(catalog)
            }

    assert entries["https://contoso.example/ont/customer"] == (
        "model/ontologies/customer.ttl"
    )
    assert "https://contoso.example/ont/customer/" not in entries


def test_sync_domain_catalog_entry_is_idempotent(tmp_path):
    catalog = tmp_path / "catalog-v001.xml"
    ontology = tmp_path / "model" / "ontologies" / "sales.ttl"
    ontology.parent.mkdir(parents=True)
    catalog.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<catalog xmlns="{CATALOG_NS}">\n'
        "</catalog>\n",
        encoding="utf-8",
    )
    ontology.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "<https://contoso.example/ont/sales> a owl:Ontology .\n",
        encoding="utf-8",
    )

    sync_domain_catalog_entry(catalog, ontology)
    sync_domain_catalog_entry(catalog, ontology)

    entries = [
        entry
        for entry in _uri_entries(catalog)
        if entry.get("name") == "https://contoso.example/ont/sales"
    ]
    assert len(entries) == 1
    assert entries[0].get("uri") == "model/ontologies/sales.ttl"


def test_sync_preserves_reference_model_uri_and_next_catalog(tmp_path):
    catalog = tmp_path / "catalog-v001.xml"
    ontology = tmp_path / "model" / "ontologies" / "policy.ttl"
    ontology.parent.mkdir(parents=True)
    catalog.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<catalog xmlns="{CATALOG_NS}">\n'
        '  <uri name="https://spec.example/ref" uri="../reference/ref.ttl"/>\n'
        '  <nextCatalog catalog="../ontology-reference-models/catalog-v001.xml"/>\n'
        "</catalog>\n",
        encoding="utf-8",
    )
    ontology.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "<https://contoso.example/ont/policy> a owl:Ontology .\n",
        encoding="utf-8",
    )

    sync_domain_catalog_entry(catalog, ontology)
    root = _catalog_root(catalog)

    assert root.find(f"{{{CATALOG_NS}}}uri[@name='https://spec.example/ref']") is not None
    assert root.find(f"{{{CATALOG_NS}}}nextCatalog") is not None
    assert root.find(f"{{{CATALOG_NS}}}uri[@name='https://contoso.example/ont/policy']") is not None
