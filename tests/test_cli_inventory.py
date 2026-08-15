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
        result = runner.invoke(
            cli,
            [
                "generate-inventory",
                "--ref-models-dir",
                str(ref_dir),
                "--output-dir",
                str(out_dir),
            ],
        )

        assert result.exit_code == 0, result.output
        assert "1 generated" in result.output

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
        result = runner.invoke(
            cli,
            [
                "generate-inventory",
                "--ontology-dir",
                str(ont_dir),
                "--output-dir",
                str(out_dir),
            ],
        )

        assert result.exit_code == 0, result.output
        yaml_file = out_dir / "client-inventory.yaml"
        assert yaml_file.exists()

        with open(yaml_file, encoding="utf-8") as f:
            inv = yaml.safe_load(f)

        assert inv["domain_name"] == "Client"
        # Domain ontologies don't include specializations
        customer = next(c for c in inv["classes"] if c["name"] == "Customer")
        assert "specializations" not in customer

    def test_second_run_reports_unchanged_not_generated(self, tmp_path):
        """Issue #419 / DD-154: a rerun over unchanged sources writes nothing —
        "generated" counts actual writes, unchanged files are reported separately,
        and the on-disk inventory is byte-identical across runs."""
        ref_dir = tmp_path / "model" / "reference-models"
        ref_dir.mkdir(parents=True)
        ttl = ref_dir / "party.ttl"
        ttl.write_text(SAMPLE_REF_TTL, encoding="utf-8")
        out_dir = tmp_path / "model" / "inventory"
        args = [
            "generate-inventory",
            "--ref-models-dir",
            str(ref_dir),
            "--output-dir",
            str(out_dir),
        ]
        runner = CliRunner()

        first = runner.invoke(cli, args)
        assert first.exit_code == 0, first.output
        assert "1 generated, 0 unchanged" in first.output
        yaml_file = out_dir / "party-inventory.yaml"
        first_bytes = yaml_file.read_bytes()

        second = runner.invoke(cli, args)
        assert second.exit_code == 0, second.output
        assert "0 generated, 1 unchanged" in second.output
        assert "⏭ party: up to date" in second.output
        assert yaml_file.read_bytes() == first_bytes

        # A real content change regenerates.
        ttl.write_text(
            SAMPLE_REF_TTL + '\nref-party:Person a owl:Class ; rdfs:label "Person" .\n',
            encoding="utf-8",
        )
        third = runner.invoke(cli, args)
        assert third.exit_code == 0, third.output
        assert "1 generated, 0 unchanged" in third.output
        assert yaml_file.read_bytes() != first_bytes

    def test_no_dirs_fails(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "generate-inventory",
                "--ontology-dir",
                str(tmp_path / "nonexistent"),
            ],
        )
        assert result.exit_code != 0

    def test_autodetects_repo_root_refmodels(self, tmp_path, monkeypatch):
        # Reference models resolved via KAIROS_REFMODELS_ROOT (package or env-var,
        # not folder-scan auto-detection since DD-158).
        ref_dir = tmp_path / "ontology-reference-models"
        ref_dir.mkdir(parents=True)
        (ref_dir / "party.ttl").write_text(SAMPLE_REF_TTL, encoding="utf-8")
        # model/ontologies/ marks the hub root for find_hub_root(require_model=True)
        (tmp_path / "model" / "ontologies").mkdir(parents=True)

        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref_dir))
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

        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref_dir))
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
            ttl = ref_root / "derived-ontologies" / model / "current" / "party" / "party.ttl"
            ttl.parent.mkdir(parents=True, exist_ok=True)
            ttl.write_text(self._ref_ttl(model, cls), encoding="utf-8")

        (tmp_path / "model" / "ontologies").mkdir(parents=True)
        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref_root))
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

    def test_local_and_reference_module_with_same_stem_coexist(self, tmp_path, monkeypatch):
        ref_root = tmp_path / "ontology-reference-models"
        ref_ttl = ref_root / "derived-ontologies" / "DCSA" / "current" / "booking" / "booking.ttl"
        ref_ttl.parent.mkdir(parents=True)
        ref_ttl.write_text(self._ref_ttl("DCSA", "ReferenceBooking"), encoding="utf-8")

        ontology_dir = tmp_path / "model" / "ontologies"
        ontology_dir.mkdir(parents=True)
        (ontology_dir / "booking.ttl").write_text(
            self._ref_ttl("Local", "LocalBooking"),
            encoding="utf-8",
        )

        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref_root))
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        generated = runner.invoke(cli, ["generate-inventory"])

        assert generated.exit_code == 0, generated.output
        inventory_dir = tmp_path / "referencemodels-unpacked"
        assert (inventory_dir / "booking-inventory.yaml").is_file()
        assert (inventory_dir / "dcsa-booking-inventory.yaml").is_file()

        checked = runner.invoke(cli, ["check-inventory"])
        assert checked.exit_code == 0, checked.output
        assert "MIGRATION REQUIRED" not in checked.output

    def test_generate_inventory_ignores_archived_reference_model_versions(
        self, tmp_path, monkeypatch
    ):
        ref_root = tmp_path / "ontology-reference-models"
        current = ref_root / "derived-ontologies" / "BSP" / "current" / "party" / "party.ttl"
        archived = (
            ref_root / "derived-ontologies" / "BSP" / "archive" / "1.4.0" / "party" / "party.ttl"
        )
        current.parent.mkdir(parents=True, exist_ok=True)
        archived.parent.mkdir(parents=True, exist_ok=True)
        current.write_text(self._ref_ttl("BSP", "CurrentTradeParty"), encoding="utf-8")
        archived.write_text(self._ref_ttl("BSP", "ArchivedTradeParty"), encoding="utf-8")
        (tmp_path / "model" / "ontologies").mkdir(parents=True)

        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref_root))
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


class TestGenerateInventoryExcludesPatternTemplates:
    """Issue #406: every ``blueprints/patterns/<id>/template.ttl`` collapses onto the
    same ``template-inventory.yaml`` name (``_ref_model_id`` only namespaces paths
    under ``derived-ontologies``) — a collision that scales with the pattern library,
    not a two-file accident. These files are copyable authoring stubs (placeholder
    ``https://example.org/`` namespaces, deliberately no ``owl:versionInfo``) and
    should never have been inventoried at all.

    Modeled directly on
    ``test_generate_inventory_ignores_archived_reference_model_versions`` above.
    """

    _TEMPLATE_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://example.org/pattern> a owl:Ontology ; rdfs:label "Pattern Template" .
<https://example.org/pattern#Thing> a owl:Class ; rdfs:label "Thing" .
"""

    def test_generate_inventory_excludes_pattern_library_templates(self, tmp_path, monkeypatch):
        ref_root = tmp_path / "ontology-reference-models"
        real = ref_root / "derived-ontologies" / "BSP" / "current" / "party" / "party.ttl"
        real.parent.mkdir(parents=True, exist_ok=True)
        real.write_text(
            TestInventoryCollisionRegression()._ref_ttl("BSP", "TradeParty"), encoding="utf-8"
        )

        for pattern_id in ("deferred-relationship", "multimodal-order-leg"):
            template = ref_root / "blueprints" / "patterns" / pattern_id / "template.ttl"
            template.parent.mkdir(parents=True, exist_ok=True)
            template.write_text(self._TEMPLATE_TTL, encoding="utf-8")

        (tmp_path / "model" / "ontologies").mkdir(parents=True)
        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref_root))
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(cli, ["generate-inventory"])
        assert result.exit_code == 0, result.output
        assert "❌" not in result.output
        assert "collision" not in result.output.lower()

        inv_dir = tmp_path / "referencemodels-unpacked"
        assert (inv_dir / "bsp-party-inventory.yaml").is_file()
        # Neither pattern template produced an inventory, under any name.
        assert not (inv_dir / "template-inventory.yaml").exists()
        assert not any(p.name == "template-inventory.yaml" for p in inv_dir.glob("*"))

        check = CliRunner().invoke(cli, ["check-inventory"])
        assert check.exit_code == 0, check.output
        assert "MIGRATION REQUIRED" not in check.output


class TestGenerateInventoryExitCodeInvariant:
    """Issue #405 / DD-153: a source that never produces an artifact must fail the
    command *only when the failure is author-actionable* — a DD-054 name collision
    always blocks, but a parse exception on a source the hub author does not own
    (e.g. a vendored reference-model checkout) is advisory unless it is the *only*
    thing a target attempted (total failure), or ``--strict`` escalates it.

    Both directions of the DD-153 invariant are asserted: ``exit != 0 ⟹ a ❌ line was
    printed`` and ``❌ printed ⟹ exit != 0``. The repo violated the second direction
    before the #405 fix — a DD-054 name collision printed ``❌`` but still exited 0
    (``cli/inspection.py`` around the old ``produced_by`` collision check). It was
    later violated the *other* way (this suite's regression target): every partial
    failure was made blocking regardless of reason, which relocated #405's
    unconvergeable-forever pathology from ``check-inventory`` to
    ``generate-inventory`` whenever the failing source was vendored and unfixable by
    the hub author — exactly what DD-153 rejects.
    """

    def test_partial_parse_failure_on_unowned_source_exits_zero_and_prints_warning(
        self, tmp_path, monkeypatch
    ):
        """A mix of one good and one unparseable reference-model source (the actual
        #405 shape once dozens of vendored TTLs are involved: most build, a few
        vendored ones don't) must not block — REASON_EXCEPTION is advisory, not a
        blocking-kind reason, and the target still produced an artifact overall."""
        ref_dir = tmp_path / "ontology-reference-models"
        ref_dir.mkdir(parents=True)
        (ref_dir / "party.ttl").write_text(SAMPLE_REF_TTL, encoding="utf-8")
        (ref_dir / "broken.ttl").write_text("this is not valid turtle @@@ ###", encoding="utf-8")
        (tmp_path / "model" / "ontologies").mkdir(parents=True)
        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref_dir))
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(cli, ["generate-inventory"])

        # Direction: no ❌ was printed, so exit == 0 (not blocking).
        assert result.exit_code == 0, result.output
        assert "❌" not in result.output
        assert "⚠" in result.output
        assert "1 failed" in result.output

    def test_total_failure_of_a_target_exits_nonzero_and_prints_cross_mark(
        self, tmp_path, monkeypatch
    ):
        """The exact #405 regression, unchanged: a ref-models dir whose *only*
        source is un-inventoriable produces nothing at all for that target — a total
        failure, which blocks regardless of reason (not merely "was it a
        collision")."""
        ref_dir = tmp_path / "ontology-reference-models"
        ref_dir.mkdir(parents=True)
        (ref_dir / "broken.ttl").write_text("this is not valid turtle @@@ ###", encoding="utf-8")
        (tmp_path / "model" / "ontologies").mkdir(parents=True)
        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref_dir))
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(cli, ["generate-inventory"])

        assert result.exit_code != 0
        assert "❌" in result.output
        assert "1 failed" in result.output

    def test_collision_exits_nonzero_and_prints_cross_mark(self, tmp_path, monkeypatch):
        """A DD-054 name collision must block, even though the other source in the
        same run succeeds — fixing the exit!=0 ⟺ ❌-printed invariant's violated
        direction (a collision used to print ❌ and still exit 0)."""
        ref_root = tmp_path / "ontology-reference-models"
        first = ref_root / "derived-ontologies" / "BSP" / "current" / "party" / "party.ttl"
        second = ref_root / "derived-ontologies" / "BSP" / "current" / "legacy-party" / "party.ttl"
        for path, cls in ((first, "TradeParty"), (second, "LegacyTradeParty")):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                TestInventoryCollisionRegression()._ref_ttl("BSP", cls), encoding="utf-8"
            )
        (tmp_path / "model" / "ontologies").mkdir(parents=True)
        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref_root))
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(cli, ["generate-inventory"])

        # Direction 1: exit != 0 ⟹ a ❌ line was printed.
        assert result.exit_code != 0
        assert "❌" in result.output
        # Direction 2 (the previously-violated one): a collision was reported, and
        # that reporting is exactly why the exit is non-zero.
        assert "collision" in result.output.lower()
        assert "1 failed" in result.output


class TestGenerateInventoryPrune:
    """Issue #405/#406 (A2): ``--prune`` must never delete a still-live source's
    committed inventory, whether because that source failed this run, or because
    one of the two scope roots was not resolved this run."""

    def test_failing_source_keeps_its_existing_inventory(self, tmp_path, monkeypatch):
        ref_dir = tmp_path / "ontology-reference-models"
        ref_dir.mkdir(parents=True)
        ttl = ref_dir / "party.ttl"
        ttl.write_text(SAMPLE_REF_TTL, encoding="utf-8")
        (tmp_path / "model" / "ontologies").mkdir(parents=True)
        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref_dir))
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        first = runner.invoke(cli, ["generate-inventory"])
        assert first.exit_code == 0, first.output
        inv_path = tmp_path / "referencemodels-unpacked" / "party-inventory.yaml"
        assert inv_path.is_file()

        # Break the source after it has a committed, good inventory.
        ttl.write_text("this is not valid turtle @@@ ###", encoding="utf-8")

        second = runner.invoke(cli, ["generate-inventory"])
        assert second.exit_code != 0, second.output
        # The previously-good inventory must survive — it was never re-produced
        # this run, but it is still a live (merely currently-broken) source, not
        # an orphan.
        assert inv_path.is_file()

    def test_ontology_dir_only_run_does_not_delete_reference_model_inventories(
        self, tmp_path, monkeypatch
    ):
        hub = tmp_path / "hub"
        ont_dir = hub / "model" / "ontologies"
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
        # Deliberately NOT under any location `_resolve_ref_models_dir` auto-detects,
        # so a plain `--ontology-dir`-only rerun cannot find it either.
        ref_dir = tmp_path / "elsewhere" / "ontology-reference-models"
        ref_dir.mkdir(parents=True)
        (ref_dir / "party.ttl").write_text(SAMPLE_REF_TTL, encoding="utf-8")

        monkeypatch.chdir(hub)
        runner = CliRunner()

        first = runner.invoke(
            cli,
            [
                "generate-inventory",
                "--ontology-dir",
                str(ont_dir),
                "--ref-models-dir",
                str(ref_dir),
            ],
        )
        assert first.exit_code == 0, first.output
        ref_inv = hub / "referencemodels-unpacked" / "party-inventory.yaml"
        assert ref_inv.is_file()

        second = runner.invoke(cli, ["generate-inventory", "--ontology-dir", str(ont_dir)])
        assert second.exit_code == 0, second.output
        assert "Skipping prune" in second.output
        # The reference-model inventory must survive an ontology-only run that could
        # not resolve the reference-models scope at all.
        assert ref_inv.is_file()


class TestResolveRefModelsDir:
    def test_returns_none_when_missing(self, tmp_path, monkeypatch):
        # Package not installed and no env var → resolve_refmodels_dir returns None.
        monkeypatch.delenv("KAIROS_REFMODELS_ROOT", raising=False)
        from kairos_ontology.cli.shared import resolve_refmodels_dir

        assert resolve_refmodels_dir(tmp_path, tmp_path) is None


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
            stale=["bsp-booking"],  # in scope
            ok=["bsp-party"],  # in scope
        )
        scope = scope_inventory_report(report, {"booking": {"bsp-booking"}, "party": {"bsp-party"}})
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
        ref_dir = tmp_path / "ontology-reference-models"
        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref_dir))
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
        booking = runner.invoke(cli, ["check-inventory", "--domains", "booking", "--explain-scope"])
        assert booking.exit_code == 0, booking.output
        assert "out of scope" in booking.output

        # Scoped to party: the missing inventory is in scope → blocks.
        party = runner.invoke(cli, ["check-inventory", "--domains", "party"])
        assert party.exit_code == 1, party.output

    def test_domains_collapses_out_of_scope_noise_by_default(self, tmp_path, monkeypatch):
        """Without --verbose/--explain-scope, out-of-scope missing inventories are
        collapsed to a one-line non-blocking summary instead of a wall of ❌ lines."""
        self._build_hub(tmp_path)
        ref_dir = tmp_path / "ontology-reference-models"
        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref_dir))
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        gen = runner.invoke(cli, ["generate-inventory"])
        assert gen.exit_code == 0, gen.output
        (tmp_path / "referencemodels-unpacked" / "party-inventory.yaml").unlink()

        # Default (collapsed): no per-module ❌ MISSING line, just the summary.
        booking = runner.invoke(cli, ["check-inventory", "--domains", "booking"])
        assert booking.exit_code == 0, booking.output
        assert "MISSING inventory" not in booking.output
        assert "out-of-scope module" in booking.output

        # --verbose restores the full per-module listing.
        verbose = runner.invoke(cli, ["check-inventory", "--domains", "booking", "--verbose"])
        assert verbose.exit_code == 0, verbose.output
        assert "MISSING inventory" in verbose.output
