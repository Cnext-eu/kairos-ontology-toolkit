# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the DDD overlay vocabulary, validation, and discovery (DD-091)."""

from pathlib import Path

import pytest
from rdflib import Graph

from kairos_ontology.core import ddd

ACME_HUB = Path(__file__).parent / "scenarios" / "acme-hub"
ONTOLOGIES = ACME_HUB / "model" / "ontologies"
EXTENSIONS = ACME_HUB / "model" / "extensions"

_BASE = """@prefix acme: <https://acme.example/ontology/client#> .
@prefix acme-ddd: <https://acme.example/ddd/client#> .
@prefix kairos-ddd: <https://kairos.cnext.eu/ddd#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
"""


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "sample-ddd-ext.ttl"
    p.write_text(_BASE + body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Vocabulary + packaged assets
# ---------------------------------------------------------------------------

class TestPackagedAssets:
    def test_vocabulary_parses(self):
        assert ddd.DDD_VOCAB_PATH.exists()
        g = Graph()
        g.parse(ddd.DDD_VOCAB_PATH, format="turtle")
        assert len(g) > 0

    def test_shapes_parse(self):
        assert ddd.DDD_SHAPES_PATH.exists()
        g = Graph()
        g.parse(ddd.DDD_SHAPES_PATH, format="turtle")
        assert len(g) > 0

    def test_vocabulary_defines_core_classes(self):
        from rdflib.namespace import OWL, RDF
        g = ddd.load_ddd_vocabulary()
        for cls in ("BoundedContext", "ContextRelationship", "TacticalPattern",
                    "ContextRelationshipPattern"):
            assert (ddd.DDD_NS[cls], RDF.type, OWL.Class) in g, f"missing {cls}"

    def test_vocabulary_has_tactical_individuals(self):
        g = ddd.load_ddd_vocabulary()
        roots = list(g.subjects(None, ddd.DDD_NS.TacticalPattern))
        names = {str(r).rsplit("#", 1)[-1] for r in roots}
        assert {"AggregateRoot", "AggregateMember", "Entity", "ValueObject"} <= names


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_discovers_overlays(self):
        overlays = ddd.discover_ddd_overlays(EXTENSIONS)
        names = {p.name for p in overlays}
        assert {"client-ddd-ext.ttl", "invoice-ddd-ext.ttl"} <= names

    def test_discover_empty_dir(self, tmp_path):
        assert ddd.discover_ddd_overlays(tmp_path) == []

    def test_domain_name(self):
        assert ddd.overlay_domain_name(Path("client-ddd-ext.ttl")) == "client"

    def test_find_domain_ontology(self):
        overlay = EXTENSIONS / "client-ddd-ext.ttl"
        assert ddd.find_domain_ontology(overlay, ONTOLOGIES) == ONTOLOGIES / "client.ttl"


# ---------------------------------------------------------------------------
# Validation — happy path
# ---------------------------------------------------------------------------

class TestValidationPass:
    @pytest.mark.parametrize("domain", ["client", "invoice"])
    def test_scenario_overlays_pass(self, domain):
        overlay = EXTENSIONS / f"{domain}-ddd-ext.ttl"
        onto = ONTOLOGIES / f"{domain}.ttl"
        res = ddd.validate_ddd_overlay(overlay, onto)
        assert res["passed"], res

    def test_no_overlays_skips(self, tmp_path, capsys):
        failures = ddd.run_ddd_validation(tmp_path, ONTOLOGIES)
        assert failures == 0
        assert "not applicable" in capsys.readouterr().out

    def test_run_validation_all_pass(self):
        assert ddd.run_ddd_validation(EXTENSIONS, ONTOLOGIES) == 0


# ---------------------------------------------------------------------------
# Validation — failures
# ---------------------------------------------------------------------------

class TestValidationFailures:
    def test_syntax_error(self, tmp_path):
        p = tmp_path / "bad-ddd-ext.ttl"
        p.write_text("this is not turtle @@@", encoding="utf-8")
        res = ddd.validate_ddd_overlay(p, ONTOLOGIES / "client.ttl")
        assert not res["passed"]
        assert not res["syntax"]["passed"]

    def test_unknown_tactical_pattern(self, tmp_path):
        p = _write(tmp_path, "acme:Client kairos-ddd:tacticalPattern kairos-ddd:Wizard .\n")
        res = ddd.validate_ddd_overlay(p, ONTOLOGIES / "client.ttl")
        assert not res["passed"]
        assert not res["shacl"]["passed"]

    def test_aggregate_member_without_root(self, tmp_path):
        p = _write(tmp_path,
                   "acme:Identifier kairos-ddd:tacticalPattern kairos-ddd:AggregateMember .\n")
        res = ddd.validate_ddd_overlay(p, ONTOLOGIES / "client.ttl")
        assert not res["passed"]
        assert not res["shacl"]["passed"]

    def test_aggregate_root_unknown_class(self, tmp_path):
        p = _write(tmp_path,
                   "acme:Identifier kairos-ddd:tacticalPattern kairos-ddd:AggregateMember ; "
                   "kairos-ddd:aggregateRoot acme:NoSuchClass .\n")
        res = ddd.validate_ddd_overlay(p, ONTOLOGIES / "client.ttl")
        assert not res["passed"]
        assert not res["shacl"]["passed"]

    def test_context_relationship_missing_parts(self, tmp_path):
        p = _write(tmp_path,
                   'acme-ddd:R a kairos-ddd:ContextRelationship ; '
                   'kairos-ddd:sourceContext acme-ddd:C1 .\n'
                   'acme-ddd:C1 a kairos-ddd:BoundedContext ; rdfs:label "C1" .\n')
        res = ddd.validate_ddd_overlay(p, ONTOLOGIES / "client.ttl")
        assert not res["passed"]
        assert not res["shacl"]["passed"]

    def test_bounded_context_without_label(self, tmp_path):
        p = _write(tmp_path, "acme-ddd:C1 a kairos-ddd:BoundedContext .\n")
        res = ddd.validate_ddd_overlay(p, ONTOLOGIES / "client.ttl")
        assert not res["passed"]
        assert not res["shacl"]["passed"]

    def test_silver_projection_leak_fails(self, tmp_path):
        p = _write(tmp_path,
                   'acme:Client kairos-ddd:tacticalPattern kairos-ddd:Entity ; '
                   '<https://kairos.cnext.eu/ext#silverTableName> "x" .\n')
        res = ddd.validate_ddd_overlay(p, ONTOLOGIES / "client.ttl")
        assert not res["passed"]
        assert not res["ext_leak"]["passed"]
        assert "kairos-ext:silverTableName" in res["ext_leak"]["predicates"]

    def test_gold_projection_leak_fails(self, tmp_path):
        p = _write(tmp_path,
                   'acme:Client kairos-ddd:tacticalPattern kairos-ddd:Entity ; '
                   '<https://kairos.cnext.eu/ext#goldTableType> "fact" .\n')
        res = ddd.validate_ddd_overlay(p, ONTOLOGIES / "client.ttl")
        assert not res["ext_leak"]["passed"]

    def test_run_validation_counts_failures(self, tmp_path):
        (tmp_path / "bad-ddd-ext.ttl").write_text(
            _BASE + "acme-ddd:C1 a kairos-ddd:BoundedContext .\n", encoding="utf-8"
        )
        assert ddd.run_ddd_validation(tmp_path, ONTOLOGIES) == 1


# ---------------------------------------------------------------------------
# Domain-inherited kairos-ext annotations must NOT count as a leak
# ---------------------------------------------------------------------------

class TestLeakScope:
    def test_domain_naturalkey_not_flagged(self):
        # client.ttl uses kairos-ext:naturalKey inline; the overlay scan must
        # only inspect the overlay graph, not the merged domain graph.
        overlay = EXTENSIONS / "client-ddd-ext.ttl"
        res = ddd.validate_ddd_overlay(overlay, ONTOLOGIES / "client.ttl")
        assert res["ext_leak"]["passed"]
