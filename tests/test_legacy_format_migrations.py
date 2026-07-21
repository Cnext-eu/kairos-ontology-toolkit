# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused tests for explicit inventory and managed-block format migrations."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.claim_projection_sync import evaluate_projection_sync
from kairos_ontology.core.claim_registry import Claim, ClaimRegistry, registry_path, write_registry
from kairos_ontology.core.inventory import (
    InventoryMigrationRequiredError,
    check_inventories,
    generate_inventory,
    load_inventory,
    write_inventory,
)
from kairos_ontology.core.migrate_claims import (
    apply_legacy_format_migration,
    legacy_format_backup_dir,
    plan_legacy_format_migration,
)
from kairos_ontology.core.propose_alignment import _load_inventory_classes
import kairos_ontology.core.migrate_claims as legacy_migrations


def _reference_ttl(label: str, class_name: str) -> str:
    return f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ref: <https://example.org/ref/{class_name.lower()}#> .

<https://example.org/ref/{class_name.lower()}> a owl:Ontology ;
    rdfs:label "{label}" .

ref:{class_name} a owl:Class ;
    rdfs:label "{class_name}" .
"""


def _reference_source(hub, model: str, stem: str, class_name: str):
    path = (
        hub
        / "ontology-reference-models"
        / "derived-ontologies"
        / model
        / "current"
        / stem
        / f"{stem}.ttl"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_reference_ttl(model, class_name), encoding="utf-8")
    return path


def _legacy_inventory(hub, source):
    path = hub / "referencemodels-unpacked" / f"{source.stem}-inventory.yaml"
    write_inventory(generate_inventory(source), path)
    return path


def _write_projection_fixture(hub):
    claims = hub / "model" / "claims"
    ontologies = hub / "model" / "ontologies"
    extensions = hub / "model" / "extensions"
    ontologies.mkdir(parents=True)
    extensions.mkdir(parents=True)
    (ontologies / "_foundation.ttl").write_text(
        """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<https://example.org/domain/_foundation> a owl:Ontology .
""",
        encoding="utf-8",
    )
    write_registry(
        ClaimRegistry(
            domain="party",
            claims=[
                Claim(
                    id="party-trade-party",
                    type="class",
                    status="approved",
                    disposition="claim",
                    origin="imported",
                    class_uri="https://example.org/ref/party#TradeParty",
                )
            ],
        ),
        registry_path(claims, "party"),
    )
    ontology = """\
# KEEP: authored heading
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dom: <https://example.org/domain/party#> .

<https://example.org/domain/party> a owl:Ontology ;
    rdfs:label "Party"@en ;
    owl:imports <https://example.org/domain/_foundation> ;
    owl:imports <https://example.org/ref/party> .

# KEEP: authored local class
dom:VipParty a owl:Class ;
    rdfs:label "VIP party"@en .
"""
    extension = """\
# KEEP: extension comment
@prefix dom: <https://example.org/domain/party#> .
@prefix ref: <https://example.org/ref/party#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

dom:VipParty kairos-ext:silverInclude true .
ref:TradeParty kairos-ext:silverInclude true .
"""
    (ontologies / "party.ttl").write_text(ontology, encoding="utf-8")
    (extensions / "party-silver-ext.ttl").write_text(extension, encoding="utf-8")
    return claims, ontologies, extensions


def test_inventory_migration_moves_unambiguous_stem_and_is_idempotent(tmp_path):
    hub = tmp_path / "hub"
    source = _reference_source(hub, "BSP", "party", "TradeParty")
    legacy = _legacy_inventory(hub, source)

    plan = plan_legacy_format_migration(
        hub,
        ref_models_dir=hub / "ontology-reference-models",
    )
    assert plan.is_valid
    assert plan.inventory_moves == [(legacy, hub / "referencemodels-unpacked" / "bsp-party-inventory.yaml")]

    apply_legacy_format_migration(plan)

    canonical = hub / "referencemodels-unpacked" / "bsp-party-inventory.yaml"
    assert canonical.exists()
    assert not legacy.exists()
    assert (legacy_format_backup_dir(hub) / "referencemodels-unpacked" / legacy.name).exists()
    assert not plan_legacy_format_migration(
        hub, ref_models_dir=hub / "ontology-reference-models"
    ).has_changes

    report = check_inventories(
        ontology_dir=None,
        ref_models_dir=hub / "ontology-reference-models",
        inventory_dir=hub / "referencemodels-unpacked",
    )
    assert report.migration_required == []
    assert report.ok == ["bsp-party"]


def test_inventory_migration_detects_colliding_legacy_stem_without_writing(tmp_path):
    hub = tmp_path / "hub"
    bsp = _reference_source(hub, "BSP", "party", "TradeParty")
    _reference_source(hub, "IMO", "party", "MaritimeParty")
    legacy = _legacy_inventory(hub, bsp)
    before = legacy.read_bytes()

    plan = plan_legacy_format_migration(
        hub,
        ref_models_dir=hub / "ontology-reference-models",
    )

    assert not plan.is_valid
    assert any("collides" in error for error in plan.errors)
    assert legacy.read_bytes() == before
    assert not (hub / "referencemodels-unpacked" / "bsp-party-inventory.yaml").exists()


def test_inventory_migration_handles_mixed_canonical_and_legacy_files(tmp_path):
    hub = tmp_path / "hub"
    bsp = _reference_source(hub, "BSP", "party", "TradeParty")
    imo = _reference_source(hub, "IMO", "booking", "Booking")
    inventory_dir = hub / "referencemodels-unpacked"
    inventory_dir.mkdir()
    write_inventory(generate_inventory(bsp), inventory_dir / "bsp-party-inventory.yaml")
    legacy = _legacy_inventory(hub, imo)

    plan = plan_legacy_format_migration(
        hub,
        ref_models_dir=hub / "ontology-reference-models",
    )
    assert plan.is_valid
    assert plan.inventory_moves == [(legacy, inventory_dir / "imo-booking-inventory.yaml")]
    apply_legacy_format_migration(plan)

    assert (inventory_dir / "bsp-party-inventory.yaml").exists()
    assert (inventory_dir / "imo-booking-inventory.yaml").exists()
    assert not legacy.exists()


def test_inventory_migration_rejects_malformed_legacy_input_and_runtime_reader_diagnoses(tmp_path):
    hub = tmp_path / "hub"
    source = _reference_source(hub, "BSP", "party", "TradeParty")
    legacy = hub / "referencemodels-unpacked" / "party-inventory.yaml"
    legacy.parent.mkdir()
    legacy.write_text("- not\n- a mapping\n", encoding="utf-8")

    plan = plan_legacy_format_migration(
        hub,
        ref_models_dir=hub / "ontology-reference-models",
    )
    assert not plan.is_valid
    assert any("does not contain a YAML mapping" in error for error in plan.errors)
    assert legacy.exists()

    # Provenance-aware direct readers reject old names rather than silently loading
    # them; malformed files remain an ordinary validation failure.
    write_inventory(generate_inventory(source), legacy)
    with pytest.raises(InventoryMigrationRequiredError, match="migrate"):
        load_inventory(legacy)
    with pytest.raises(InventoryMigrationRequiredError, match="migrate"):
        _load_inventory_classes(legacy.parent)


def test_projection_migration_preserves_authored_ttl_and_claim_registry_authority(tmp_path):
    hub = tmp_path / "hub"
    claims, ontologies, extensions = _write_projection_fixture(hub)
    before_ontology = (ontologies / "party.ttl").read_text(encoding="utf-8")
    before_extension = (extensions / "party-silver-ext.ttl").read_text(encoding="utf-8")

    preflight = evaluate_projection_sync(
        claims_dir=claims,
        ontologies_dir=ontologies,
        extensions_dir=extensions,
    )
    assert preflight.is_blocking
    assert "migrate --hub" in (preflight.domains[0].error or "")

    plan = plan_legacy_format_migration(hub)
    assert plan.is_valid, plan.errors
    assert plan.projection_domains == ["party"]
    apply_legacy_format_migration(plan)

    ontology = (ontologies / "party.ttl").read_text(encoding="utf-8")
    extension = (extensions / "party-silver-ext.ttl").read_text(encoding="utf-8")
    assert "# KEEP: authored heading" in ontology
    assert "# KEEP: authored local class" in ontology
    assert "dom:VipParty a owl:Class" in ontology
    assert "# KEEP: extension comment" in extension
    assert "dom:VipParty kairos-ext:silverInclude true ." in extension
    assert ontology.count("# >>> kairos-managed") == 1
    assert extension.count("# >>> kairos-managed") == 1
    authored_ontology = ontology.split("# >>> kairos-managed")[0]
    authored_extension = extension.split("# >>> kairos-managed")[0]
    assert "<https://example.org/ref/party>" not in authored_ontology
    assert "ref:TradeParty kairos-ext:silverInclude true ." not in authored_extension
    assert (legacy_format_backup_dir(hub) / "model" / "ontologies" / "party.ttl").read_text(
        encoding="utf-8"
    ) == before_ontology
    assert (
        legacy_format_backup_dir(hub) / "model" / "extensions" / "party-silver-ext.ttl"
    ).read_text(encoding="utf-8") == before_extension

    assert not evaluate_projection_sync(
        claims_dir=claims,
        ontologies_dir=ontologies,
        extensions_dir=extensions,
    ).is_blocking
    assert not plan_legacy_format_migration(hub).has_changes


def test_migrate_cli_check_and_dry_run_do_not_write_then_apply(tmp_path):
    hub = tmp_path / "hub"
    source = _reference_source(hub, "BSP", "party", "TradeParty")
    legacy = _legacy_inventory(hub, source)
    (hub / "model" / "ontologies").mkdir(parents=True)
    runner = CliRunner()

    preview = runner.invoke(cli, ["migrate", "--hub", str(hub), "--check"])
    assert preview.exit_code == 0, preview.output
    assert "Legacy-format migration preview" in preview.output
    assert legacy.exists()
    assert not (hub / "referencemodels-unpacked" / "bsp-party-inventory.yaml").exists()
    assert not legacy_format_backup_dir(hub).exists()

    dry_run = runner.invoke(cli, ["migrate", "--hub", str(hub), "--dry-run"])
    assert dry_run.exit_code == 0, dry_run.output
    assert legacy.exists()

    applied = runner.invoke(cli, ["migrate", "--hub", str(hub)])
    assert applied.exit_code == 0, applied.output
    assert not legacy.exists()
    assert (hub / "referencemodels-unpacked" / "bsp-party-inventory.yaml").exists()


def test_projection_migration_rejects_malformed_managed_block_without_writing(tmp_path):
    hub = tmp_path / "hub"
    _claims, ontologies, _extensions = _write_projection_fixture(hub)
    ontology = ontologies / "party.ttl"
    ontology.write_text(
        ontology.read_text(encoding="utf-8")
        + "\n# >>> kairos-managed (generated from the Claim Registry — do not edit)\n",
        encoding="utf-8",
    )
    before = ontology.read_bytes()

    plan = plan_legacy_format_migration(hub)

    assert not plan.is_valid
    assert any("malformed managed-block" in error for error in plan.errors)
    assert ontology.read_bytes() == before


def test_migration_rolls_back_all_originals_when_atomic_publish_fails(tmp_path, monkeypatch):
    hub = tmp_path / "hub"
    source = _reference_source(hub, "BSP", "party", "TradeParty")
    legacy = _legacy_inventory(hub, source)
    _claims, ontologies, extensions = _write_projection_fixture(hub)
    ontology = ontologies / "party.ttl"
    extension = extensions / "party-silver-ext.ttl"
    originals = {
        legacy: legacy.read_bytes(),
        ontology: ontology.read_bytes(),
        extension: extension.read_bytes(),
    }
    plan = plan_legacy_format_migration(
        hub,
        ref_models_dir=hub / "ontology-reference-models",
    )
    assert plan.is_valid, plan.errors

    original_replace = legacy_migrations.os.replace
    calls = 0

    def fail_after_first_publish(source_path, destination_path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated atomic publish failure")
        return original_replace(source_path, destination_path)

    monkeypatch.setattr(legacy_migrations.os, "replace", fail_after_first_publish)
    with pytest.raises(OSError, match="simulated atomic publish failure"):
        apply_legacy_format_migration(plan)

    assert all(path.read_bytes() == content for path, content in originals.items())
    assert not (hub / "referencemodels-unpacked" / "bsp-party-inventory.yaml").exists()
