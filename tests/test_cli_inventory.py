# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the generate-inventory CLI command (DD-044)."""


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

    def test_autodetects_repo_root_refmodels(self, tmp_path, monkeypatch):
        # Reference models live at the REPO ROOT (ontology-reference-models/),
        # not under model/reference-models/. Auto-detect must find them.
        ref_dir = tmp_path / "ontology-reference-models"
        ref_dir.mkdir(parents=True)
        (ref_dir / "party.ttl").write_text(SAMPLE_REF_TTL, encoding="utf-8")
        # model/ontologies/ marks the hub root for find_hub_root(require_model=True)
        (tmp_path / "model" / "ontologies").mkdir(parents=True)

        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["generate-inventory"])

        assert result.exit_code == 0, result.output
        assert (tmp_path / "referencemodels-unpacked" / "party-inventory.yaml").exists()


class TestCheckInventoryCLI:

    def test_autodetects_repo_root_refmodels(self, tmp_path, monkeypatch):
        ref_dir = tmp_path / "ontology-reference-models"
        ref_dir.mkdir(parents=True)
        (ref_dir / "party.ttl").write_text(SAMPLE_REF_TTL, encoding="utf-8")
        (tmp_path / "model" / "ontologies").mkdir(parents=True)

        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        # Generate inventories first (also auto-detects repo-root ref models)
        gen = runner.invoke(cli, ["generate-inventory"])
        assert gen.exit_code == 0, gen.output

        # check-inventory (bare, auto-detect) should now pass
        check = runner.invoke(cli, ["check-inventory"])
        assert check.exit_code == 0, check.output


class TestInventoryCollisionRegression:
    """DD-054: same-named modules from different reference models must not
    overwrite one another (the party.ttl last-write-wins data-loss bug)."""

    def _ref_ttl(self, label, cls):
        return f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://kairos.cnext.eu/ref/{cls}> a owl:Ontology ; rdfs:label "{label}" .
<https://kairos.cnext.eu/ref/{cls}#{cls}> a owl:Class ; rdfs:label "{cls}" .
"""

    def test_six_party_modules_produce_six_inventories(self, tmp_path, monkeypatch):
        ref_root = tmp_path / "ontology-reference-models"
        models = {
            "BSP": "TradeParty",
            "DCSA": "ShippingParty",
            "IMO": "MaritimeParty",
            "MMT": "TransportParty",
            "TIC": "InspectionParty",
            "WCO": "Declarant",
        }
        for model, cls in models.items():
            ttl = (
                ref_root / "derived-ontologies" / model / "current" / "party"
                / "party.ttl"
            )
            ttl.parent.mkdir(parents=True, exist_ok=True)
            ttl.write_text(self._ref_ttl(model, cls), encoding="utf-8")

        (tmp_path / "model" / "ontologies").mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        gen = runner.invoke(cli, ["generate-inventory"])
        assert gen.exit_code == 0, gen.output

        inv_dir = tmp_path / "referencemodels-unpacked"
        # One inventory per model — no collision.
        for model, cls in models.items():
            f = inv_dir / f"{model.lower()}-party-inventory.yaml"
            assert f.exists(), f"missing {f.name}: {gen.output}"
            with open(f, encoding="utf-8") as fh:
                inv = yaml.safe_load(fh)
            names = {c["name"] for c in inv["classes"]}
            assert cls in names, f"{model} class {cls} dropped from {f.name}"

        # check-inventory must be GREEN (no spurious stale, no deadlock).
        check = runner.invoke(cli, ["check-inventory"])
        assert check.exit_code == 0, check.output
        assert "STALE" not in check.output

    def test_prune_removes_legacy_stem_inventory(self, tmp_path, monkeypatch):
        ref_root = tmp_path / "ontology-reference-models"
        ttl = (
            ref_root / "derived-ontologies" / "BSP" / "current" / "party" / "party.ttl"
        )
        ttl.parent.mkdir(parents=True, exist_ok=True)
        ttl.write_text(self._ref_ttl("BSP", "TradeParty"), encoding="utf-8")

        inv_dir = tmp_path / "referencemodels-unpacked"
        inv_dir.mkdir(parents=True)
        # Legacy collision artifact from the old stem-keyed scheme.
        (inv_dir / "party-inventory.yaml").write_text("version: '1.0'\n", encoding="utf-8")
        (tmp_path / "model" / "ontologies").mkdir(parents=True)

        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        gen = runner.invoke(cli, ["generate-inventory"])
        assert gen.exit_code == 0, gen.output

        assert (inv_dir / "bsp-party-inventory.yaml").exists()
        assert not (inv_dir / "party-inventory.yaml").exists()

    def test_no_prune_keeps_legacy_file(self, tmp_path, monkeypatch):
        ref_root = tmp_path / "ontology-reference-models"
        ttl = (
            ref_root / "derived-ontologies" / "BSP" / "current" / "party" / "party.ttl"
        )
        ttl.parent.mkdir(parents=True, exist_ok=True)
        ttl.write_text(self._ref_ttl("BSP", "TradeParty"), encoding="utf-8")

        inv_dir = tmp_path / "referencemodels-unpacked"
        inv_dir.mkdir(parents=True)
        (inv_dir / "party-inventory.yaml").write_text("version: '1.0'\n", encoding="utf-8")
        (tmp_path / "model" / "ontologies").mkdir(parents=True)

        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        gen = runner.invoke(cli, ["generate-inventory", "--no-prune"])
        assert gen.exit_code == 0, gen.output
        assert (inv_dir / "party-inventory.yaml").exists()

    def test_generate_inventory_ignores_archived_reference_model_versions(
        self, tmp_path, monkeypatch
    ):
        ref_root = tmp_path / "ontology-reference-models"
        current = (
            ref_root / "derived-ontologies" / "BSP" / "current" / "party" / "party.ttl"
        )
        archived = (
            ref_root / "derived-ontologies" / "BSP" / "archive" / "1.4.0"
            / "party" / "party.ttl"
        )
        current.parent.mkdir(parents=True, exist_ok=True)
        archived.parent.mkdir(parents=True, exist_ok=True)
        current.write_text(self._ref_ttl("BSP", "CurrentTradeParty"), encoding="utf-8")
        archived.write_text(self._ref_ttl("BSP", "ArchivedTradeParty"), encoding="utf-8")
        (tmp_path / "model" / "ontologies").mkdir(parents=True)

        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(cli, ["generate-inventory"])

        assert result.exit_code == 0, result.output
        with open(
            tmp_path / "referencemodels-unpacked" / "bsp-party-inventory.yaml",
            encoding="utf-8",
        ) as fh:
            inv = yaml.safe_load(fh)
        names = {c["name"] for c in inv["classes"]}
        assert "CurrentTradeParty" in names
        assert "ArchivedTradeParty" not in names


class TestResolveRefModelsDir:

    def test_prefers_repo_root_over_legacy(self, tmp_path):
        from kairos_ontology.cli.main import _resolve_ref_models_dir

        repo_root_dir = tmp_path / "ontology-reference-models"
        repo_root_dir.mkdir()
        legacy_dir = tmp_path / "model" / "reference-models"
        legacy_dir.mkdir(parents=True)

        resolved = _resolve_ref_models_dir(tmp_path, tmp_path)
        assert resolved == repo_root_dir

    def test_legacy_fallback(self, tmp_path):
        from kairos_ontology.cli.main import _resolve_ref_models_dir

        legacy_dir = tmp_path / "model" / "reference-models"
        legacy_dir.mkdir(parents=True)

        resolved = _resolve_ref_models_dir(tmp_path, tmp_path)
        assert resolved == legacy_dir

    def test_returns_none_when_missing(self, tmp_path):
        from kairos_ontology.cli.main import _resolve_ref_models_dir

        assert _resolve_ref_models_dir(tmp_path, tmp_path) is None


SAMPLE_BOOKING_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ref-booking: <https://kairos.cnext.eu/ref/booking#> .

<https://kairos.cnext.eu/ref/booking> a owl:Ontology ;
    rdfs:label "Booking" .

ref-booking:Booking a owl:Class ;
    rdfs:label "Booking" .

ref-booking:bookingRef a owl:DatatypeProperty ;
    rdfs:domain ref-booking:Booking ;
    rdfs:range xsd:string .
"""

_CATALOG_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog" prefer="public">
  <uri name="https://kairos.cnext.eu/ref/party" uri="ontology-reference-models/party.ttl"/>
  <uri name="https://kairos.cnext.eu/ref/booking" uri="ontology-reference-models/booking.ttl"/>
</catalog>
"""

_DATA_DOMAINS_YAML = """\
groups:
  - id: logistics
    domains:
      - id: party
        name: Party
        imports:
          - uri: https://kairos.cnext.eu/ref/party#
            module: party
      - id: booking
        name: Booking
        imports:
          - uri: https://kairos.cnext.eu/ref/booking#
            module: booking
"""


class TestScopeInventoryReport:
    """F5: pure projection of a repo-wide report onto selected domains."""

    def test_intersects_and_scopes_blocking(self):
        from kairos_ontology.core.inventory import (
            InventoryCheckReport,
            scope_inventory_report,
        )

        report = InventoryCheckReport(
            missing=["refdata-codes"],  # out of scope
            stale=["bsp-booking"],       # in scope
            ok=["bsp-party"],            # in scope
        )
        scope = scope_inventory_report(
            report, {"booking": {"bsp-booking"}, "party": {"bsp-party"}}
        )
        assert scope.stale == ["bsp-booking"]
        assert scope.ok == ["bsp-party"]
        assert scope.missing == []  # refdata-codes is out of scope
        assert scope.is_blocking is True  # bsp-booking stale is in scope

    def test_unrelated_failure_not_blocking_in_scope(self):
        from kairos_ontology.core.inventory import (
            InventoryCheckReport,
            scope_inventory_report,
        )

        report = InventoryCheckReport(missing=["refdata-codes"], ok=["bsp-booking"])
        scope = scope_inventory_report(report, {"booking": {"bsp-booking"}})
        assert scope.is_blocking is False


class TestResolveDomainInventoryKeys:
    """F5: catalog-based domain→inventory-key resolution."""

    def _setup(self, tmp_path):
        ref_dir = tmp_path / "ontology-reference-models"
        ref_dir.mkdir(parents=True)
        (ref_dir / "party.ttl").write_text(SAMPLE_REF_TTL, encoding="utf-8")
        (ref_dir / "booking.ttl").write_text(SAMPLE_BOOKING_TTL, encoding="utf-8")
        dd_dir = ref_dir / "accelerator-packs" / "logistics" / "client-hub-blueprint"
        dd_dir.mkdir(parents=True)
        (dd_dir / "data-domains.yaml").write_text(_DATA_DOMAINS_YAML, encoding="utf-8")
        catalog = tmp_path / "catalog-v001.xml"
        catalog.write_text(_CATALOG_XML, encoding="utf-8")
        return ref_dir, catalog

    def test_resolves_selected_domain(self, tmp_path):
        from kairos_ontology.core.inventory import resolve_domain_inventory_keys

        ref_dir, catalog = self._setup(tmp_path)
        keys, unresolved = resolve_domain_inventory_keys(
            ["booking"], ref_models_dir=ref_dir, catalog_path=catalog
        )
        assert keys == {"booking": {"booking"}}
        assert unresolved == {}

    def test_unresolved_uri_is_recorded(self, tmp_path):
        from kairos_ontology.core.inventory import resolve_domain_inventory_keys

        ref_dir, _catalog = self._setup(tmp_path)
        # No catalog → import URIs cannot be resolved to a TTL path.
        keys, unresolved = resolve_domain_inventory_keys(
            ["party"], ref_models_dir=ref_dir, catalog_path=None
        )
        assert keys == {"party": set()}
        assert unresolved["party"] == ["https://kairos.cnext.eu/ref/party#"]


class TestCheckInventoryDomainScope:
    """F5: end-to-end --domains scoping via the CLI."""

    def _build_hub(self, tmp_path):
        ref_dir = tmp_path / "ontology-reference-models"
        ref_dir.mkdir(parents=True)
        (ref_dir / "party.ttl").write_text(SAMPLE_REF_TTL, encoding="utf-8")
        (ref_dir / "booking.ttl").write_text(SAMPLE_BOOKING_TTL, encoding="utf-8")
        dd_dir = ref_dir / "accelerator-packs" / "logistics" / "client-hub-blueprint"
        dd_dir.mkdir(parents=True)
        (dd_dir / "data-domains.yaml").write_text(_DATA_DOMAINS_YAML, encoding="utf-8")
        (tmp_path / "catalog-v001.xml").write_text(_CATALOG_XML, encoding="utf-8")
        (tmp_path / "model" / "ontologies").mkdir(parents=True)

    def test_domains_scopes_blocking(self, tmp_path, monkeypatch):
        self._build_hub(tmp_path)
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        gen = runner.invoke(cli, ["generate-inventory"])
        assert gen.exit_code == 0, gen.output

        # Remove the party inventory to create a repo-wide (but party-scoped) failure.
        (tmp_path / "referencemodels-unpacked" / "party-inventory.yaml").unlink()

        # Repo-wide check blocks (party is missing).
        bare = runner.invoke(cli, ["check-inventory"])
        assert bare.exit_code == 1, bare.output

        # Scoped to booking: party's missing inventory is out of scope → passes.
        booking = runner.invoke(
            cli, ["check-inventory", "--domains", "booking", "--explain-scope"]
        )
        assert booking.exit_code == 0, booking.output
        assert "out of scope" in booking.output

        # Scoped to party: the missing inventory is in scope → blocks.
        party = runner.invoke(cli, ["check-inventory", "--domains", "party"])
        assert party.exit_code == 1, party.output

