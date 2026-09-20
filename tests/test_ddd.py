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
STRATEGIC = EXTENSIONS / ddd.STRATEGIC_FILE_NAME

_BASE = """@prefix acme: <https://acme.example/ontology/client#> .
@prefix acme-ddd: <https://acme.example/ddd/client#> .
@prefix kairos-ddd: <https://kairos.cnext.eu/ddd#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
"""

_CONTEXT = 'acme-ddd:C1 a kairos-ddd:BoundedContext ; rdfs:label "C1" .\n'


def _write(tmp_path: Path, body: str, name: str = "sample-ddd-ext.ttl") -> Path:
    p = tmp_path / name
    p.write_text(_BASE + body, encoding="utf-8")
    return p


def _strategic(tmp_path: Path, body: str) -> Path:
    return _write(tmp_path, body, name=ddd.STRATEGIC_FILE_NAME)


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
        for cls in (
            "BoundedContext",
            "ContextRelationship",
            "TacticalPattern",
            "ContextRelationshipPattern",
        ):
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

    def test_the_strategic_file_is_not_an_overlay(self):
        """It has no domain, so it must never be validated as one (#848 would flag it)."""
        assert ddd.STRATEGIC_FILE_NAME not in {
            p.name for p in ddd.discover_ddd_overlays(EXTENSIONS)
        }
        assert not ddd.STRATEGIC_FILE_NAME.endswith("-ddd-ext.ttl")
        assert ddd.find_strategic_file(EXTENSIONS) == STRATEGIC

    def test_find_strategic_file_absent(self, tmp_path):
        assert ddd.find_strategic_file(tmp_path) is None
        assert ddd.find_strategic_file(None) is None

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
        # `client` declares its contexts in the overlay (pre-DD-229 layout); `invoice`
        # references contexts declared hub-wide in the strategic file. Both must pass.
        res = ddd.validate_ddd_overlay(overlay, onto, strategic_path=STRATEGIC)
        assert res["passed"], res

    def test_invoice_overlay_needs_the_strategic_file(self):
        """Rule 8: a context referenced but declared nowhere in the merged graph fails."""
        res = ddd.validate_ddd_overlay(
            EXTENSIONS / "invoice-ddd-ext.ttl", ONTOLOGIES / "invoice.ttl"
        )
        assert not res["passed"]
        assert "boundedContext must point to a declared" in res["shacl"]["report"]

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
        p = _write(
            tmp_path, "acme:Identifier kairos-ddd:tacticalPattern kairos-ddd:AggregateMember .\n"
        )
        res = ddd.validate_ddd_overlay(p, ONTOLOGIES / "client.ttl")
        assert not res["passed"]
        assert not res["shacl"]["passed"]

    def test_aggregate_root_unknown_class(self, tmp_path):
        p = _write(
            tmp_path,
            "acme:Identifier kairos-ddd:tacticalPattern kairos-ddd:AggregateMember ; "
            "kairos-ddd:aggregateRoot acme:NoSuchClass .\n",
        )
        res = ddd.validate_ddd_overlay(p, ONTOLOGIES / "client.ttl")
        assert not res["passed"]
        assert not res["shacl"]["passed"]

    def test_context_relationship_missing_parts(self, tmp_path):
        p = _write(
            tmp_path,
            "acme-ddd:R a kairos-ddd:ContextRelationship ; "
            "kairos-ddd:sourceContext acme-ddd:C1 .\n"
            'acme-ddd:C1 a kairos-ddd:BoundedContext ; rdfs:label "C1" .\n',
        )
        res = ddd.validate_ddd_overlay(p, ONTOLOGIES / "client.ttl")
        assert not res["passed"]
        assert not res["shacl"]["passed"]

    def test_bounded_context_without_label(self, tmp_path):
        p = _write(tmp_path, "acme-ddd:C1 a kairos-ddd:BoundedContext .\n")
        res = ddd.validate_ddd_overlay(p, ONTOLOGIES / "client.ttl")
        assert not res["passed"]
        assert not res["shacl"]["passed"]

    def test_silver_projection_leak_fails(self, tmp_path):
        p = _write(
            tmp_path,
            "acme:Client kairos-ddd:tacticalPattern kairos-ddd:Entity ; "
            '<https://kairos.cnext.eu/ext#silverTableName> "x" .\n',
        )
        res = ddd.validate_ddd_overlay(p, ONTOLOGIES / "client.ttl")
        assert not res["passed"]
        assert not res["ext_leak"]["passed"]
        assert "kairos-ext:silverTableName" in res["ext_leak"]["predicates"]

    def test_gold_projection_leak_fails(self, tmp_path):
        p = _write(
            tmp_path,
            "acme:Client kairos-ddd:tacticalPattern kairos-ddd:Entity ; "
            '<https://kairos.cnext.eu/ext#goldTableType> "fact" .\n',
        )
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

    def test_ubiquitous_language_predicates_are_not_a_leak(self, tmp_path):
        """skos:scopeNote / skos:example / skos:altLabel are language, not projection control."""
        p = _write(
            tmp_path,
            _CONTEXT + "acme:Client kairos-ddd:boundedContext acme-ddd:C1 ; "
            'skos:scopeNote "In C1 a client is a contracted counterparty." ; '
            'skos:example "ACME-0001" ; skos:altLabel "Account"@en .\n',
        )
        res = ddd.validate_ddd_overlay(p, ONTOLOGIES / "client.ttl")
        assert res["passed"], res


# ---------------------------------------------------------------------------
# DD-229: the hub-wide strategic file, the new shapes, and the cross-file audit
# ---------------------------------------------------------------------------


class TestVocabulary11:
    def test_subdomain_types_and_invariant_are_declared(self):
        from rdflib.namespace import OWL, RDF

        g = ddd.load_ddd_vocabulary()
        assert (ddd.DDD_NS.SubdomainType, RDF.type, OWL.Class) in g
        kinds = {str(s).rsplit("#", 1)[-1] for s in g.subjects(RDF.type, ddd.DDD_NS.SubdomainType)}
        assert kinds == {"CoreDomain", "SupportingSubdomain", "GenericSubdomain"}
        assert (ddd.DDD_NS.subdomainType, RDF.type, OWL.AnnotationProperty) in g
        assert (ddd.DDD_NS.invariant, RDF.type, OWL.AnnotationProperty) in g

    def test_version_bumped(self):
        from rdflib import URIRef
        from rdflib.namespace import OWL

        g = ddd.load_ddd_vocabulary()
        assert str(g.value(URIRef("https://kairos.cnext.eu/ddd"), OWL.versionInfo)) == "1.1.0"


class TestStrategicFile:
    def test_scenario_strategic_file_passes(self):
        res = ddd.validate_strategic_file(STRATEGIC)
        assert res["passed"], res

    def test_contexts_declared_only_in_the_strategic_file_resolve_from_an_overlay(self, tmp_path):
        strategic = _strategic(tmp_path, _CONTEXT)
        overlay = _write(tmp_path, "acme:Client kairos-ddd:boundedContext acme-ddd:C1 .\n")
        assert not ddd.validate_ddd_overlay(overlay, ONTOLOGIES / "client.ttl")["passed"]
        res = ddd.validate_ddd_overlay(overlay, ONTOLOGIES / "client.ttl", strategic_path=strategic)
        assert res["passed"], res

    def test_relationship_in_strategic_file_needs_both_contexts_there(self, tmp_path):
        """The strategic file stands alone: a relationship naming a context still declared only
        in an overlay fails rule 6 -- move contexts and relationships together."""
        strategic = _strategic(
            tmp_path,
            _CONTEXT + "acme-ddd:R a kairos-ddd:ContextRelationship ; "
            "kairos-ddd:sourceContext acme-ddd:C1 ; kairos-ddd:targetContext acme-ddd:C2 ; "
            "kairos-ddd:relationshipPattern kairos-ddd:Conformist .\n",
        )
        res = ddd.validate_strategic_file(strategic)
        assert not res["passed"]
        assert not res["shacl"]["passed"]

    def test_tactical_predicates_are_refused_in_the_strategic_file(self, tmp_path):
        strategic = _strategic(
            tmp_path,
            _CONTEXT + "acme:Client kairos-ddd:tacticalPattern kairos-ddd:AggregateRoot .\n",
        )
        res = ddd.validate_strategic_file(strategic)
        assert not res["passed"]
        assert res["strategic"]["tactical_predicates"] == ["kairos-ddd:tacticalPattern"]

    def test_unknown_subdomain_type(self, tmp_path):
        strategic = _strategic(
            tmp_path,
            'acme-ddd:C1 a kairos-ddd:BoundedContext ; rdfs:label "C1" ; '
            "kairos-ddd:subdomainType kairos-ddd:Sideline .\n",
        )
        res = ddd.validate_strategic_file(strategic)
        assert not res["shacl"]["passed"]

    def test_relationship_must_join_two_different_contexts(self, tmp_path):
        strategic = _strategic(
            tmp_path,
            _CONTEXT + "acme-ddd:R a kairos-ddd:ContextRelationship ; "
            "kairos-ddd:sourceContext acme-ddd:C1 ; kairos-ddd:targetContext acme-ddd:C1 ; "
            "kairos-ddd:relationshipPattern kairos-ddd:SharedKernel .\n",
        )
        assert not ddd.validate_strategic_file(strategic)["shacl"]["passed"]

    def test_syntax_error_in_strategic_file(self, tmp_path):
        p = tmp_path / ddd.STRATEGIC_FILE_NAME
        p.write_text("not turtle @@@", encoding="utf-8")
        res = ddd.validate_strategic_file(p)
        assert not res["passed"] and not res["syntax"]["passed"]


class TestNewOverlayShapes:
    def test_dangling_context_reference_fails(self, tmp_path):
        p = _write(tmp_path, "acme:Client kairos-ddd:boundedContext acme-ddd:Typo .\n")
        res = ddd.validate_ddd_overlay(p, ONTOLOGIES / "client.ttl")
        assert not res["passed"]
        assert "must point to a declared" in res["shacl"]["report"]

    def test_two_contexts_on_one_class_fails(self, tmp_path):
        p = _write(
            tmp_path,
            _CONTEXT + 'acme-ddd:C2 a kairos-ddd:BoundedContext ; rdfs:label "C2" .\n'
            "acme:Client kairos-ddd:boundedContext acme-ddd:C1 , acme-ddd:C2 .\n",
        )
        res = ddd.validate_ddd_overlay(p, ONTOLOGIES / "client.ttl")
        assert not res["passed"]
        assert "exactly one bounded context" in res["shacl"]["report"]

    def test_invariant_is_accepted(self, tmp_path):
        p = _write(
            tmp_path,
            "acme:Client kairos-ddd:tacticalPattern kairos-ddd:AggregateRoot ; "
            'kairos-ddd:invariant "A client has exactly one primary identifier." .\n',
        )
        assert ddd.validate_ddd_overlay(p, ONTOLOGIES / "client.ttl")["passed"]


class TestConsistencyAudit:
    def _two_overlays(self, tmp_path: Path, second_label: str) -> list[Path]:
        first = _write(tmp_path, _CONTEXT, name="client-ddd-ext.ttl")
        second = _write(
            tmp_path,
            f'acme-ddd:C1 a kairos-ddd:BoundedContext ; rdfs:label "{second_label}" .\n',
            name="invoice-ddd-ext.ttl",
        )
        return [first, second]

    def test_consistent_redeclaration_is_a_warning(self, tmp_path):
        diags = ddd.audit_ddd_consistency(self._two_overlays(tmp_path, "C1"))
        assert [(d.level, d.code) for d in diags] == [("warning", ddd.CODE_CONTEXT_REDECLARED)]
        assert ddd.STRATEGIC_FILE_NAME in diags[0].message

    def test_label_conflict_is_an_error(self, tmp_path):
        diags = ddd.audit_ddd_consistency(self._two_overlays(tmp_path, "Context One"))
        assert [(d.level, d.code) for d in diags] == [("error", ddd.CODE_CONTEXT_LABEL_CONFLICT)]
        assert "'C1'" in diags[0].message and "'Context One'" in diags[0].message

    def test_class_in_two_contexts_across_files_is_an_error(self, tmp_path):
        strategic = _strategic(
            tmp_path, _CONTEXT + 'acme-ddd:C2 a kairos-ddd:BoundedContext ; rdfs:label "C2" .\n'
        )
        a = _write(
            tmp_path, "acme:Client kairos-ddd:boundedContext acme-ddd:C1 .\n", "a-ddd-ext.ttl"
        )
        b = _write(
            tmp_path, "acme:Client kairos-ddd:boundedContext acme-ddd:C2 .\n", "b-ddd-ext.ttl"
        )
        diags = ddd.audit_ddd_consistency([a, b], strategic)
        assert [(d.level, d.code) for d in diags] == [("error", ddd.CODE_CLASS_IN_TWO_CONTEXTS)]

    def test_same_context_from_two_files_is_fine(self, tmp_path):
        strategic = _strategic(tmp_path, _CONTEXT)
        a = _write(
            tmp_path, "acme:Client kairos-ddd:boundedContext acme-ddd:C1 .\n", "a-ddd-ext.ttl"
        )
        b = _write(
            tmp_path, "acme:Client kairos-ddd:boundedContext acme-ddd:C1 .\n", "b-ddd-ext.ttl"
        )
        assert ddd.audit_ddd_consistency([a, b], strategic) == []

    def test_scenario_hub_is_consistent(self):
        assert ddd.audit_ddd_consistency(ddd.discover_ddd_overlays(EXTENSIONS), STRATEGIC) == []

    def test_run_validation_reports_the_strategic_file_and_the_audit(self, tmp_path, capsys):
        _strategic(tmp_path, _CONTEXT)
        _write(
            tmp_path,
            _CONTEXT + "acme:Client kairos-ddd:boundedContext acme-ddd:C1 .\n",
            "client-ddd-ext.ttl",
        )
        assert ddd.run_ddd_validation(tmp_path, ONTOLOGIES) == 0
        out = capsys.readouterr().out
        assert f"✅ {ddd.STRATEGIC_FILE_NAME}" in out
        assert ddd.CODE_CONTEXT_REDECLARED in out
        assert "1 warning(s)" in out

    def test_run_validation_counts_audit_errors(self, tmp_path):
        _strategic(tmp_path, _CONTEXT)
        _write(
            tmp_path,
            'acme-ddd:C1 a kairos-ddd:BoundedContext ; rdfs:label "Other" .\n',
            "client-ddd-ext.ttl",
        )
        assert ddd.run_ddd_validation(tmp_path, ONTOLOGIES) == 1

    def test_strategic_file_alone_is_validated(self, tmp_path, capsys):
        _strategic(tmp_path, "acme-ddd:C1 a kairos-ddd:BoundedContext .\n")  # no label
        assert ddd.run_ddd_validation(tmp_path, ONTOLOGIES) == 1
        assert "strategic" in capsys.readouterr().out
