# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for ``kairos-ontology domain-coverage`` (issue #393)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.domain_coverage import build_domain_coverage_report

_DATA_DOMAINS_YAML = """\
schema_version: "1.0"
groups:
  - id: party-commercial
    name: "Party & Commercial"
    domains:
      - id: party
        name: "Party, Role & Organisation"
        owns: "Legal entities, customers, suppliers."
        does_not_own: "Contracts, bookings, invoices."
        imports:
          - uri: "https://www.kairosflow.ai/ont/bsp/party#"
            module: "BSP / Party"
      - id: commercial
        name: "Customer, Contract & Commercial Agreement"
        owns: "Commercial relationships, service agreements."
        does_not_own: "Surcharge calculation, invoice posting."
        imports:
          - uri: "https://www.kairosflow.ai/ont/bsp/commercial#"
            module: "BSP / Commercial"
"""


def _write_accelerator_pack(ref_models_dir: Path, name: str) -> None:
    dd_dir = ref_models_dir / "accelerator-packs" / name / "client-hub-blueprint"
    dd_dir.mkdir(parents=True)
    (dd_dir / "data-domains.yaml").write_text(_DATA_DOMAINS_YAML, encoding="utf-8")


def _ontology_ttl(iri: str, label: str) -> str:
    return (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n\n"
        f"<{iri}> a owl:Ontology ;\n"
        f'    rdfs:label "{label}" .\n'
    )


def _binding_yaml(name: str, domain: str) -> str:
    return (
        "apiVersion: kairos.eu/v5\n"
        "kind: EntityBinding\n"
        "metadata:\n"
        f"  name: {name}\n"
        f"  domain: {domain}\n"
    )


@pytest.fixture()
def hub(tmp_path: Path) -> Path:
    """A hub with: a blueprint-listed unmodeled domain, a modeled+bound+imported
    domain, and a custom domain modeled outside any blueprint."""
    hub_root = tmp_path / "hub"
    ontologies_dir = hub_root / "model" / "ontologies"
    bindings_dir = hub_root / "integration" / "bindings"
    ontologies_dir.mkdir(parents=True)
    bindings_dir.mkdir(parents=True)
    (hub_root / "kairos.yaml").write_text("adapter: fabric\n", encoding="utf-8")

    (ontologies_dir / "party.ttl").write_text(
        _ontology_ttl("https://acme.test/ont/party", "Party"), encoding="utf-8"
    )
    (ontologies_dir / "customdomain.ttl").write_text(
        _ontology_ttl("https://acme.test/ont/customdomain", "Custom Domain"), encoding="utf-8"
    )
    (ontologies_dir / "_master.ttl").write_text(
        _ontology_ttl("https://acme.test/ont/master", "Master")
        + "\n<https://acme.test/ont/master> owl:imports <https://acme.test/ont/party> .\n",
        encoding="utf-8",
    )
    (bindings_dir / "party.binding.yaml").write_text(
        _binding_yaml("crm-party", "party"), encoding="utf-8"
    )
    (bindings_dir / "commercial.binding.yaml").write_text(
        _binding_yaml("crm-commercial", "commercial"), encoding="utf-8"
    )

    ref_models_dir = tmp_path / "ontology-reference-models"
    _write_accelerator_pack(ref_models_dir, "logistics")

    return hub_root


def _invoke(hub: Path, monkeypatch, args):
    monkeypatch.chdir(hub)
    ref_dir = hub.parent / "ontology-reference-models"
    if ref_dir.is_dir():
        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref_dir))
    return CliRunner().invoke(cli, ["domain-coverage", *args])


class TestBuildDomainCoverageReport:
    def test_full_matrix_across_blueprint_modeled_bound_imported(self, hub):
        report = build_domain_coverage_report(
            ontologies_dir=hub / "model" / "ontologies",
            bindings_dir=hub / "integration" / "bindings",
            master_path=hub / "model" / "ontologies" / "_master.ttl",
            ref_models_dir=hub.parent / "ontology-reference-models",
            accelerator="logistics",
        )
        rows = {row.domain: row for row in report.rows}

        assert set(rows) == {"party", "commercial", "customdomain"}

        party = rows["party"]
        assert party.in_blueprint is True
        assert party.modeled is True
        assert party.bound is True
        assert party.imported is True

        commercial = rows["commercial"]
        assert commercial.in_blueprint is True
        assert commercial.modeled is False  # blueprint domain not yet modeled
        assert commercial.bound is True
        assert commercial.imported is False

        custom = rows["customdomain"]
        assert custom.in_blueprint is False  # authored domain absent from blueprint
        assert custom.modeled is True
        assert custom.bound is False
        assert custom.imported is False  # modeled but never imported by _master.ttl

    def test_no_accelerator_reports_in_blueprint_as_none(self, hub):
        report = build_domain_coverage_report(
            ontologies_dir=hub / "model" / "ontologies",
            bindings_dir=hub / "integration" / "bindings",
            master_path=hub / "model" / "ontologies" / "_master.ttl",
            ref_models_dir=hub.parent / "ontology-reference-models",
            accelerator=None,
        )
        assert all(row.in_blueprint is None for row in report.rows)
        # Modeled/bound/imported status is still populated without an accelerator.
        rows = {row.domain: row for row in report.rows}
        assert rows["party"].imported is True
        assert rows["customdomain"].modeled is True

    def test_missing_master_ttl_reports_not_imported_without_crashing(self, hub):
        (hub / "model" / "ontologies" / "_master.ttl").unlink()
        report = build_domain_coverage_report(
            ontologies_dir=hub / "model" / "ontologies",
            bindings_dir=hub / "integration" / "bindings",
            master_path=hub / "model" / "ontologies" / "_master.ttl",
            ref_models_dir=hub.parent / "ontology-reference-models",
            accelerator="logistics",
        )
        rows = {row.domain: row for row in report.rows}
        assert rows["party"].imported is False


class TestDomainCoverageCLI:
    def test_text_output_lists_all_domains_and_flags_gaps(self, hub, monkeypatch):
        result = _invoke(hub, monkeypatch, [])
        assert result.exit_code == 0
        assert "party" in result.output
        assert "commercial" in result.output
        assert "customdomain" in result.output
        assert "Gaps" in result.output

    def test_json_output_shape(self, hub, monkeypatch):
        result = _invoke(hub, monkeypatch, ["--json-output"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["schema_version"] == 2  # v2: optional explain/owns payloads (DD-157)
        assert payload["accelerator"] == "logistics"
        domains = {entry["domain"]: entry for entry in payload["domains"]}
        assert domains["party"] == {
            "domain": "party",
            "in_blueprint": True,
            "modeled": True,
            "bound": True,
            "imported": True,
        }
        assert domains["customdomain"]["in_blueprint"] is False

    def test_no_accelerator_installed_exits_zero_with_notice(self, hub, monkeypatch):
        # Remove the only accelerator pack so none is installed at all.
        import shutil

        shutil.rmtree(hub.parent / "ontology-reference-models" / "accelerator-packs")

        result = _invoke(hub, monkeypatch, [])
        assert result.exit_code == 0
        assert "No accelerator pack installed" in result.output
        # Modeled/bound/imported columns are still populated.
        assert "party" in result.output

    def test_no_accelerator_installed_json_still_emits_rows(self, hub, monkeypatch):
        import shutil

        shutil.rmtree(hub.parent / "ontology-reference-models" / "accelerator-packs")

        result = _invoke(hub, monkeypatch, ["--json-output"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["accelerator"] is None
        assert all(entry["in_blueprint"] is None for entry in payload["domains"])

    def test_ambiguous_accelerator_is_a_click_exception(self, hub, monkeypatch):
        _write_accelerator_pack(hub.parent / "ontology-reference-models", "finance")

        result = _invoke(hub, monkeypatch, [])
        assert result.exit_code != 0
        assert "ambiguous" in result.output.lower()


# ---------------------------------------------------------------------------
# Issue #418 / DD-157 — domain ownership surfacing
# ---------------------------------------------------------------------------

_OWNERSHIP_DATA_DOMAINS_YAML = """\
schema_version: "2.0"
module_profiles:
  - id: party-mod
    ontology_iri: https://ref.test/ont/party
    catalog_uri: "https://ref.test/ont/party#"
    version_pin: "1.0"
  - id: shared-mod
    ontology_iri: https://ref.test/ont/shared
    version_pin: "1.0"
  - id: orphan-mod
    ontology_iri: https://ref.test/ont/orphan
    version_pin: "1.0"
groups:
  - id: party-commercial
    name: "Party & Commercial"
    domains:
      - id: party
        name: "Party, Role & Organisation"
        owns: "Legal entities, customers, suppliers."
        does_not_own: "Contracts, bookings, invoices."
        imports:
          - profile: party-mod
          - profile: shared-mod
      - id: commercial
        name: "Customer, Contract & Commercial Agreement"
        owns: "Commercial relationships, service agreements."
        does_not_own: "Surcharge calculation, invoice posting."
        imports:
          - profile: shared-mod
"""


def _inventory_yaml(classes: list[tuple[str, str, str]]) -> str:
    lines = ["version: 4", "domain_name: Test", "classes:"]
    for name, uri, source_identity in classes:
        lines += [
            f"  - uri: {uri}",
            f"    name: {name}",
            f"    label: {name}",
            "    comment: ''",
            "    provenance:",
            f"      source_identity: {source_identity}",
            "      import_depth: 0",
            "      asserted: true",
            "    properties: []",
        ]
    return "\n".join(lines) + "\n"


@pytest.fixture()
def ownership_hub(hub: Path) -> Path:
    """The base hub plus a typed-profile blueprint and materialized inventories."""
    dd_path = (
        hub.parent
        / "ontology-reference-models"
        / "accelerator-packs"
        / "logistics"
        / "client-hub-blueprint"
        / "data-domains.yaml"
    )
    dd_path.write_text(_OWNERSHIP_DATA_DOMAINS_YAML, encoding="utf-8")

    inv_dir = hub / "referencemodels-unpacked"
    inv_dir.mkdir()
    (inv_dir / "party-inventory.yaml").write_text(
        _inventory_yaml(
            [
                ("Person", "https://ref.test/ont/party#Person", "https://ref.test/ont/party"),
                # Same class name asserted by a second managed module (multi-row case).
                ("Person", "https://ref.test/ont/shared#Person", "https://ref.test/ont/shared"),
                # Asserted by a managed module that no blueprint domain activates.
                ("Orphan", "https://ref.test/ont/orphan#Orphan", "https://ref.test/ont/orphan"),
                # Asserted by an ontology that is no managed module at all.
                ("LocalThing", "https://acme.test/ont/party#LocalThing", "https://acme.test/ont/party"),
            ]
        ),
        encoding="utf-8",
    )
    return hub


class TestDomainCoverageExplain:
    def test_explain_prints_owns_and_does_not_own_and_imports(self, ownership_hub, monkeypatch):
        result = _invoke(ownership_hub, monkeypatch, ["--explain", "party"])
        assert result.exit_code == 0
        assert "OWNS: Legal entities, customers, suppliers." in result.output
        assert "DOES NOT OWN: Contracts, bookings, invoices." in result.output
        assert "party-mod" in result.output
        assert "shared-mod" in result.output

    def test_explain_unknown_domain_lists_valid_ids_and_exits_zero(
        self, ownership_hub, monkeypatch
    ):
        result = _invoke(ownership_hub, monkeypatch, ["--explain", "nonsense"])
        assert result.exit_code == 0
        assert "Unknown domain 'nonsense'" in result.output
        assert "commercial" in result.output
        assert "party" in result.output

    def test_explain_without_accelerator_is_clean_informational_exit_zero(
        self, hub, monkeypatch
    ):
        import shutil

        shutil.rmtree(hub.parent / "ontology-reference-models" / "accelerator-packs")
        result = _invoke(hub, monkeypatch, ["--explain", "party"])
        assert result.exit_code == 0
        assert "ownership metadata is unavailable" in result.output

    def test_explain_json_payload_included(self, ownership_hub, monkeypatch):
        result = _invoke(ownership_hub, monkeypatch, ["--explain", "party", "--json-output"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["schema_version"] == 2
        assert payload["domains"]  # base coverage table still present
        explain = payload["explain"]
        assert explain["found"] is True
        assert explain["owns"] == "Legal entities, customers, suppliers."
        assert explain["does_not_own"] == "Contracts, bookings, invoices."
        assert {imp["profile"] for imp in explain["imports"]} == {"party-mod", "shared-mod"}


class TestDomainCoverageOwns:
    def test_owns_lists_owning_domains_case_insensitively(self, ownership_hub, monkeypatch):
        result = _invoke(ownership_hub, monkeypatch, ["--owns", "person"])
        assert result.exit_code == 0
        # Two managed modules assert a Person class — both rows must be listed.
        assert result.output.count("• Person") == 2
        assert "party-mod" in result.output
        assert "shared-mod" in result.output
        # shared-mod is activated by two domains — ownership is plural.
        assert "commercial, party" in result.output

    def test_owns_module_assigned_to_no_domain_says_so(self, ownership_hub, monkeypatch):
        result = _invoke(ownership_hub, monkeypatch, ["--owns", "Orphan"])
        assert result.exit_code == 0
        assert "orphan-mod" in result.output
        assert "assigned to no domain" in result.output

    def test_owns_class_outside_managed_modules_says_so(self, ownership_hub, monkeypatch):
        result = _invoke(ownership_hub, monkeypatch, ["--owns", "LocalThing"])
        assert result.exit_code == 0
        assert "not asserted by a managed reference module" in result.output

    def test_owns_class_found_nowhere_says_so(self, ownership_hub, monkeypatch):
        result = _invoke(ownership_hub, monkeypatch, ["--owns", "DoesNotExist"])
        assert result.exit_code == 0
        assert "not found in any materialized inventory" in result.output

    def test_owns_without_inventories_advises_generate_inventory(self, hub, monkeypatch):
        result = _invoke(hub, monkeypatch, ["--owns", "Person"])
        assert result.exit_code == 0
        assert "generate-inventory" in result.output

    def test_owns_json_payload_included(self, ownership_hub, monkeypatch):
        result = _invoke(ownership_hub, monkeypatch, ["--owns", "Person", "--json-output"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        owns = payload["owns"]
        assert owns["inventories_present"] is True
        by_module = {m["module_id"]: m for m in owns["matches"]}
        assert by_module["party-mod"]["domains"] == ["party"]
        assert by_module["shared-mod"]["domains"] == ["commercial", "party"]
