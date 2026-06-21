# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for deterministic inventory freshness checking (DD-047)."""

from pathlib import Path

import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.inventory import (
    check_inventories,
    compute_source_hash,
    generate_inventory,
    write_inventory,
)

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

ref-party:regNumber a owl:DatatypeProperty ;
    rdfs:domain ref-party:Organisation ;
    rdfs:range xsd:string .
"""

EMPTY_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://kairos.cnext.eu/ref/empty> a owl:Ontology ; rdfs:label "Empty" .
"""


def _make_ref(tmp_path: Path) -> tuple[Path, Path]:
    ref_dir = tmp_path / "model" / "reference-models"
    ref_dir.mkdir(parents=True)
    (ref_dir / "party.ttl").write_text(SAMPLE_REF_TTL, encoding="utf-8")
    inv_dir = tmp_path / "model" / "inventory"
    inv_dir.mkdir(parents=True)
    return ref_dir, inv_dir


def _generate(ref_dir: Path, inv_dir: Path) -> None:
    ttl = ref_dir / "party.ttl"
    inv = generate_inventory(ttl)
    write_inventory(inv, inv_dir / "party-inventory.yaml")


class TestComputeSourceHash:

    def test_hash_changes_with_content(self, tmp_path):
        f = tmp_path / "a.ttl"
        f.write_text("one", encoding="utf-8")
        h1 = compute_source_hash(f)
        f.write_text("two", encoding="utf-8")
        h2 = compute_source_hash(f)
        assert h1 != h2

    def test_generate_inventory_stores_hash(self, tmp_path):
        ref_dir, _ = _make_ref(tmp_path)
        ttl = ref_dir / "party.ttl"
        inv = generate_inventory(ttl)
        assert inv["source_sha256"] == compute_source_hash(ttl)


class TestCheckInventories:

    def test_ok_when_fresh(self, tmp_path):
        ref_dir, inv_dir = _make_ref(tmp_path)
        _generate(ref_dir, inv_dir)
        report = check_inventories(
            ontology_dir=None, ref_models_dir=ref_dir, inventory_dir=inv_dir
        )
        assert report.ok == ["party"]
        assert not report.is_blocking
        assert not report.has_warnings

    def test_missing_inventory_blocks(self, tmp_path):
        ref_dir, inv_dir = _make_ref(tmp_path)
        # No inventory generated.
        report = check_inventories(
            ontology_dir=None, ref_models_dir=ref_dir, inventory_dir=inv_dir
        )
        assert report.missing == ["party"]
        assert report.is_blocking

    def test_stale_inventory_blocks(self, tmp_path):
        ref_dir, inv_dir = _make_ref(tmp_path)
        _generate(ref_dir, inv_dir)
        # Mutate the source after generation.
        (ref_dir / "party.ttl").write_text(
            SAMPLE_REF_TTL + "\nref-party:extra a owl:Class ; rdfs:label \"Extra\" .\n",
            encoding="utf-8",
        )
        report = check_inventories(
            ontology_dir=None, ref_models_dir=ref_dir, inventory_dir=inv_dir
        )
        assert report.stale == ["party"]
        assert report.is_blocking

    def test_unverifiable_when_no_stored_hash(self, tmp_path):
        ref_dir, inv_dir = _make_ref(tmp_path)
        _generate(ref_dir, inv_dir)
        # Simulate a pre-DD-047 inventory by stripping the hash.
        path = inv_dir / "party-inventory.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data.pop("source_sha256", None)
        path.write_text(yaml.dump(data), encoding="utf-8")
        report = check_inventories(
            ontology_dir=None, ref_models_dir=ref_dir, inventory_dir=inv_dir
        )
        assert report.unverifiable == ["party"]
        assert not report.is_blocking
        assert report.has_warnings

    def test_class_less_source_is_skipped(self, tmp_path):
        ref_dir, inv_dir = _make_ref(tmp_path)
        _generate(ref_dir, inv_dir)
        (ref_dir / "empty.ttl").write_text(EMPTY_TTL, encoding="utf-8")
        report = check_inventories(
            ontology_dir=None, ref_models_dir=ref_dir, inventory_dir=inv_dir
        )
        # empty.ttl yields no classes → not flagged as missing.
        assert "empty" not in report.missing
        assert report.ok == ["party"]

    def test_orphan_inventory_warns(self, tmp_path):
        ref_dir, inv_dir = _make_ref(tmp_path)
        _generate(ref_dir, inv_dir)
        write_inventory(
            {"version": "1.0", "source_sha256": "x", "domain_name": "Ghost",
             "classes": [{"name": "Ghost"}]},
            inv_dir / "ghost-inventory.yaml",
        )
        report = check_inventories(
            ontology_dir=None, ref_models_dir=ref_dir, inventory_dir=inv_dir
        )
        assert "ghost-inventory.yaml" in report.orphan
        assert report.has_warnings


class TestCollisionFreshness:
    """DD-054: same-named modules across reference models stay individually fresh
    (no spurious stale, no double-listing of a stem in both ok and stale)."""

    def _write(self, ref_root: Path, model: str, cls: str) -> Path:
        ttl = ref_root / "derived-ontologies" / model / "current" / "party" / "party.ttl"
        ttl.parent.mkdir(parents=True, exist_ok=True)
        ttl.write_text(
            f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://kairos.cnext.eu/ref/{cls}> a owl:Ontology ; rdfs:label "{model}" .
<https://kairos.cnext.eu/ref/{cls}#{cls}> a owl:Class ; rdfs:label "{cls}" .
""",
            encoding="utf-8",
        )
        return ttl

    def test_all_models_fresh_no_spurious_stale(self, tmp_path):
        from kairos_ontology.inventory import inventory_filename

        ref_root = tmp_path / "ontology-reference-models"
        inv_dir = tmp_path / "model" / "inventory"
        inv_dir.mkdir(parents=True)
        models = {"BSP": "TradeParty", "IMO": "MaritimeParty", "WCO": "Declarant"}
        for model, cls in models.items():
            ttl = self._write(ref_root, model, cls)
            inv = generate_inventory(ttl)
            write_inventory(inv, inv_dir / inventory_filename(ttl, ref_models_dir=ref_root))

        report = check_inventories(
            ontology_dir=None, ref_models_dir=ref_root, inventory_dir=inv_dir
        )
        assert sorted(report.ok) == ["bsp-party", "imo-party", "wco-party"]
        assert report.stale == []
        assert not report.is_blocking
        # No key may appear in both ok and stale (the old double-listing glitch).
        assert set(report.ok).isdisjoint(report.stale)

    def test_archived_versions_do_not_make_current_inventory_stale(self, tmp_path):
        from kairos_ontology.inventory import inventory_filename

        ref_root = tmp_path / "ontology-reference-models"
        inv_dir = tmp_path / "model" / "inventory"
        inv_dir.mkdir(parents=True)
        current = self._write(ref_root, "BSP", "CurrentTradeParty")
        archived = (
            ref_root / "derived-ontologies" / "BSP" / "archive" / "1.4.0"
            / "party" / "party.ttl"
        )
        archived.parent.mkdir(parents=True, exist_ok=True)
        archived.write_text(
            """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://kairos.cnext.eu/ref/ArchivedTradeParty> a owl:Ontology ; rdfs:label "BSP" .
<https://kairos.cnext.eu/ref/ArchivedTradeParty#ArchivedTradeParty> a owl:Class ;
    rdfs:label "ArchivedTradeParty" .
""",
            encoding="utf-8",
        )
        inv = generate_inventory(current)
        write_inventory(inv, inv_dir / inventory_filename(current, ref_models_dir=ref_root))

        report = check_inventories(
            ontology_dir=None, ref_models_dir=ref_root, inventory_dir=inv_dir
        )

        assert report.ok == ["bsp-party"]
        assert report.stale == []
        assert not report.is_blocking


class TestCheckInventoryCLI:

    def test_cli_passes_when_fresh(self, tmp_path):
        ref_dir, inv_dir = _make_ref(tmp_path)
        _generate(ref_dir, inv_dir)
        result = CliRunner().invoke(cli, [
            "check-inventory",
            "--ref-models-dir", str(ref_dir),
            "--inventory-dir", str(inv_dir),
        ])
        assert result.exit_code == 0, result.output
        assert "up to date" in result.output

    def test_cli_fails_when_missing(self, tmp_path):
        ref_dir, inv_dir = _make_ref(tmp_path)
        result = CliRunner().invoke(cli, [
            "check-inventory",
            "--ref-models-dir", str(ref_dir),
            "--inventory-dir", str(inv_dir),
        ])
        assert result.exit_code == 1
        assert "MISSING" in result.output

    def test_cli_warn_only_never_blocks(self, tmp_path):
        ref_dir, inv_dir = _make_ref(tmp_path)
        result = CliRunner().invoke(cli, [
            "check-inventory",
            "--ref-models-dir", str(ref_dir),
            "--inventory-dir", str(inv_dir),
            "--warn-only",
        ])
        assert result.exit_code == 0
        assert "MISSING" in result.output

    def test_cli_strict_fails_on_unverifiable(self, tmp_path):
        ref_dir, inv_dir = _make_ref(tmp_path)
        _generate(ref_dir, inv_dir)
        path = inv_dir / "party-inventory.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data.pop("source_sha256", None)
        path.write_text(yaml.dump(data), encoding="utf-8")
        result = CliRunner().invoke(cli, [
            "check-inventory",
            "--ref-models-dir", str(ref_dir),
            "--inventory-dir", str(inv_dir),
            "--strict",
        ])
        assert result.exit_code == 1
