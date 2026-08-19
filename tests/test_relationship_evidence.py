# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tier-2 join evidence and inverse-edge derivation for propose-relationships.

Two measured gaps from the signal-first validation (runs 4b/8): the tier-1
name matcher returned ``<CONFIRM_JOIN_COLUMN>`` for joins the DD-189 profile
already proved by value containment, and a property declared parent→child
(``TransportOrder coversConsignment``) could never yield a proposal on the
side that actually carries the FK unless its ``owl:inverseOf`` edge is
entailed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kairos_ontology.core.profile_sources import load_fk_evidence
from kairos_ontology.core.propose_relationships import (
    SENTINEL_JOIN_COLUMN,
    BoundEntity,
    _match_join,
    load_ontology_edges,
)


def _entity(name: str, relation: str, source_key: tuple[str, ...],
            referenced: tuple[str, ...] = ()) -> BoundEntity:
    return BoundEntity(
        name=name, domain="d", target_class=f"https://t/ont#{name}",
        source_relation=relation, source_key=source_key,
        referenced_columns=referenced,
    )


def _profile_dir(tmp_path: Path, system: str, tables: dict) -> Path:
    sources = tmp_path / "sources"
    sysdir = sources / system
    sysdir.mkdir(parents=True)
    (sysdir / f"{system}.profile.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "system": system,
                        "basis": "import-extract(full)", "tables": tables}),
        encoding="utf-8",
    )
    return sources


class TestFkEvidence:
    def test_load_fk_evidence_reads_tags(self, tmp_path):
        sources = _profile_dir(tmp_path, "src", {
            "bookings": {"rows": 5, "table_tags": [], "columns": {
                "parent_ref": {"type": "string", "null_ratio": 0.0, "distinct": 5,
                               "distinct_ratio": 1.0,
                               "tags": ["id-like", "fk?->consignments.consignment_id"]},
                "plain": {"type": "string", "null_ratio": 0.0, "distinct": 5,
                          "distinct_ratio": 1.0, "tags": []},
            }}})
        evidence = load_fk_evidence(sources)
        assert evidence == {("src", "bookings"): {
            "parent_ref": {("consignments", "consignment_id")}}}

    def test_absent_profiles_yield_empty_evidence(self, tmp_path):
        assert load_fk_evidence(tmp_path / "nowhere") == {}


class TestTierTwoJoin:
    CHILD = _entity("bookings", "Src.bookings", ("booking_id",),
                    referenced=("booking_id", "parent_ref"))
    PARENT = _entity("consignments", "Src.consignments", ("consignment_id",))
    EVIDENCE = {("src", "bookings"): {"parent_ref": {("consignments", "consignment_id")}}}

    def test_fk_inclusion_resolves_what_name_equality_cannot(self):
        local, foreign, resolved, evidence = _match_join(
            self.CHILD, self.PARENT, self.EVIDENCE)
        assert (local, foreign, resolved, evidence) == (
            "parent_ref", "consignment_id", True, "fk-inclusion")

    def test_tier_one_name_match_still_wins_and_is_labelled(self):
        child = _entity("goods", "Src.goods", ("good_id",),
                        referenced=("good_id", "consignment_id"))
        local, foreign, resolved, evidence = _match_join(
            child, self.PARENT, self.EVIDENCE)
        assert (local, foreign, resolved, evidence) == (
            "consignment_id", "consignment_id", True, "name")

    def test_cross_system_containment_is_never_used(self):
        parent = _entity("consignments", "Other.consignments", ("consignment_id",))
        local, foreign, resolved, evidence = _match_join(
            self.CHILD, parent, self.EVIDENCE)
        assert (resolved, evidence) == (False, "")
        assert local == SENTINEL_JOIN_COLUMN

    def test_no_evidence_falls_back_to_the_sentinel(self):
        local, _foreign, resolved, evidence = _match_join(self.CHILD, self.PARENT, {})
        assert (local, resolved, evidence) == (SENTINEL_JOIN_COLUMN, False, "")


_INVERSE_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://t/ont> a owl:Ontology ; rdfs:label "t" ; owl:versionInfo "1" .
<https://t/ont#Order> a owl:Class ; rdfs:label "Order" .
<https://t/ont#Consignment> a owl:Class ; rdfs:label "Consignment" .
<https://t/ont#covers> a owl:ObjectProperty ;
    rdfs:label "covers" ;
    rdfs:domain <https://t/ont#Order> ;
    rdfs:range <https://t/ont#Consignment> ;
    owl:inverseOf <https://t/ont#coveredBy> .
<https://t/ont#coveredBy> a owl:ObjectProperty ; rdfs:label "covered by" .
"""


class TestInverseEdges:
    @pytest.fixture()
    def ontologies(self, tmp_path):
        d = tmp_path / "ontologies"
        d.mkdir()
        (d / "t.ttl").write_text(_INVERSE_TTL, encoding="utf-8")
        return d

    def test_declared_inverse_without_own_endpoints_gets_the_entailed_edge(
        self, ontologies
    ):
        edges = load_ontology_edges(ontologies)
        assert ("https://t/ont#covers", "https://t/ont#Order",
                "https://t/ont#Consignment") in edges
        assert ("https://t/ont#coveredBy", "https://t/ont#Consignment",
                "https://t/ont#Order") in edges, (
            "the FK side must be proposable: owl:inverseOf entails the swapped edge"
        )

    def test_inverse_with_its_own_endpoints_is_not_duplicated(self, tmp_path):
        d = tmp_path / "ontologies"
        d.mkdir()
        (d / "t.ttl").write_text(
            _INVERSE_TTL
            + "<https://t/ont#coveredBy> rdfs:domain <https://t/ont#Consignment> ;\n"
            + "    rdfs:range <https://t/ont#Order> .\n",
            encoding="utf-8",
        )
        edges = load_ontology_edges(d)
        covered_by = [e for e in edges if e[0] == "https://t/ont#coveredBy"]
        assert covered_by == [("https://t/ont#coveredBy", "https://t/ont#Consignment",
                               "https://t/ont#Order")]