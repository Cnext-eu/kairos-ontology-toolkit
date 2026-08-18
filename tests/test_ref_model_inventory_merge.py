# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``extract_ref_model_inventory`` unions a class's property set across modules (#540).

A class URI reachable from two modules was deduped first-wins, so the *later* module's
view of the same class was discarded. ``bsp:TradeParty`` therefore resolved to 13
properties or 17 depending purely on which module the catalog happened to resolve first.

Two things made that worse than a plain undercount:

* Every consumer reads this one function -- the class candidates ``_score_ref_class``
  ranks, the cross-module property pool, ``resolve_bridge_anchor_classes``, the
  ``anchor-tables`` tie-break, ``class_anchoring`` and ``scaffold_system``. A truncated
  property set silently depresses a class's score against a class that kept its full set.
* It was **order-dependent**, so no seed could make a run reproducible -- which defeats
  the purpose of the DD-175 sorting two functions above it.

Identity is still the URI. Only the property sets are merged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Reuse the sanctioned resolution: conftest installs a blocking sentinel for
# ``kairos_ontology_referencemodels`` so synthetic-fixture tests cannot accidentally
# resolve the real package, and this module already handles clearing and restoring it.
from tests.test_refmodels_contract import REFMODELS_ROOT

from kairos_ontology.core.propose_alignment import (
    _flatten_prop_groups,
    _merge_prop_groups,
    extract_ref_model_inventory,
)

PARTY_NS = "https://www.kairosflow.ai/ont/bsp/party#"
COMMERCIAL_NS = "https://www.kairosflow.ai/ont/bsp/commercial#"

# The same class URI (party#TradeParty) declared in two modules with *different*
# property sets -- the exact shape that lost properties.
PARTY_TTL = """\
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix party: <https://www.kairosflow.ai/ont/bsp/party#> .

<https://www.kairosflow.ai/ont/bsp/party> a owl:Ontology .

party:TradeParty a owl:Class ; rdfs:label "Trade Party" .
party:legalName a owl:DatatypeProperty ; rdfs:domain party:TradeParty ; rdfs:range xsd:string .
party:vatNumber a owl:DatatypeProperty ; rdfs:domain party:TradeParty ; rdfs:range xsd:string .
"""

COMMERCIAL_TTL = """\
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix party: <https://www.kairosflow.ai/ont/bsp/party#> .
@prefix comm:  <https://www.kairosflow.ai/ont/bsp/commercial#> .

<https://www.kairosflow.ai/ont/bsp/commercial> a owl:Ontology .

# Same class, extra properties. These are what used to vanish.
party:TradeParty a owl:Class ; rdfs:label "Trade Party" .
comm:creditLimit a owl:DatatypeProperty ; rdfs:domain party:TradeParty ; rdfs:range xsd:decimal .
comm:paymentTerm a owl:DatatypeProperty ; rdfs:domain party:TradeParty ; rdfs:range xsd:string .
"""

CATALOG_XML = """\
<?xml version="1.0"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <uri name="https://www.kairosflow.ai/ont/bsp/party#" uri="party.ttl"/>
  <uri name="https://www.kairosflow.ai/ont/bsp/commercial#" uri="commercial.ttl"/>
</catalog>
"""


@pytest.fixture
def two_module_catalog(tmp_path: Path) -> Path:
    (tmp_path / "party.ttl").write_text(PARTY_TTL, encoding="utf-8")
    (tmp_path / "commercial.ttl").write_text(COMMERCIAL_TTL, encoding="utf-8")
    catalog = tmp_path / "catalog-v001.xml"
    catalog.write_text(CATALOG_XML, encoding="utf-8")
    return catalog


def _trade_party(inventory: list[dict]) -> dict | None:
    return next((c for c in inventory if c.get("name") == "TradeParty"), None)


def _prop_names(cls: dict) -> list[str]:
    return [p["name"] for p in cls["properties"]]


class TestPropertyUnion:
    def test_properties_from_both_modules_survive(self, two_module_catalog):
        cls = _trade_party(
            extract_ref_model_inventory([PARTY_NS, COMMERCIAL_NS], two_module_catalog)
        )
        assert cls is not None, "TradeParty missing entirely"
        names = _prop_names(cls)
        # From the first module...
        assert "legalName" in names
        assert "vatNumber" in names
        # ...and from the second, which first-wins used to discard.
        assert "creditLimit" in names
        assert "paymentTerm" in names

    def test_result_is_order_independent(self, two_module_catalog):
        """The regression that made runs irreproducible: swap the module order."""
        forward = _trade_party(
            extract_ref_model_inventory([PARTY_NS, COMMERCIAL_NS], two_module_catalog)
        )
        reverse = _trade_party(
            extract_ref_model_inventory([COMMERCIAL_NS, PARTY_NS], two_module_catalog)
        )
        assert _prop_names(forward) == _prop_names(reverse)

    def test_class_is_still_deduped_to_one_entry(self, two_module_catalog):
        """Identity is the URI: merging must not emit the class twice."""
        inventory = extract_ref_model_inventory([PARTY_NS, COMMERCIAL_NS], two_module_catalog)
        assert [c["name"] for c in inventory].count("TradeParty") == 1

    def test_properties_are_not_duplicated(self, two_module_catalog):
        cls = _trade_party(
            extract_ref_model_inventory([PARTY_NS, COMMERCIAL_NS], two_module_catalog)
        )
        names = _prop_names(cls)
        assert len(names) == len(set(names)), names

    def test_contributing_uris_records_both_modules(self, two_module_catalog):
        """So a merged class can say where its properties came from."""
        cls = _trade_party(
            extract_ref_model_inventory([PARTY_NS, COMMERCIAL_NS], two_module_catalog)
        )
        assert set(cls["_semantic"]["contributing_uris"]) == {PARTY_NS, COMMERCIAL_NS}

    def test_single_module_carries_no_merge_bookkeeping(self, two_module_catalog):
        """The common case must be untouched: no contributing_uris when nothing merged."""
        cls = _trade_party(extract_ref_model_inventory([PARTY_NS], two_module_catalog))
        assert _prop_names(cls) == ["legalName", "vatNumber"]
        assert "contributing_uris" not in cls["_semantic"]


class TestMergeHelpers:
    """Unit-level: ordering and own-vs-inherited precedence (DD-175)."""

    def test_merge_adds_missing_and_keeps_first_metadata(self):
        target = {"properties": {"a": {"name": "a", "label": "first"}}}
        incoming = {
            "properties": {
                "a": {"name": "a", "label": "second"},
                "b": {"name": "b", "label": "new"},
            }
        }
        _merge_prop_groups(target, incoming)
        assert target["properties"]["a"]["label"] == "first"  # first-wins per property
        assert target["properties"]["b"]["label"] == "new"  # but new ones are added

    def test_flatten_puts_own_before_inherited_each_sorted(self):
        grouped = {
            "properties": {
                "z": {"name": "zebra", "uri": "z"},
                "a": {"name": "apple", "uri": "a"},
            },
            "inherited_properties": {
                "m": {"name": "mango", "uri": "m"},
                "b": {"name": "banana", "uri": "b"},
            },
        }
        assert [p["name"] for p in _flatten_prop_groups(grouped)] == [
            "apple",
            "zebra",
            "banana",
            "mango",
        ]

    def test_own_declaration_wins_over_inherited_and_appears_once(self):
        """Declared on the class in one module, inherited in another: own is more specific."""
        grouped = {
            "properties": {"p": {"name": "prop", "uri": "p", "label": "own"}},
            "inherited_properties": {"p": {"name": "prop", "uri": "p", "label": "inherited"}},
        }
        flat = _flatten_prop_groups(grouped)
        assert len(flat) == 1
        assert flat[0]["label"] == "own"

    def test_flatten_of_empty_groups_is_empty(self):
        assert _flatten_prop_groups({}) == []


@pytest.mark.skipif(REFMODELS_ROOT is None, reason="reference models not installed")
class TestAgainstShippedReferenceModels:
    """The figure quoted in #540, measured against the real bundle."""

    BSP = "https://www.kairosflow.ai/ont/bsp/"
    MODULES = [BSP + "party", BSP + "commercial", BSP + "financial"]

    def _catalog(self) -> Path:
        return Path(REFMODELS_ROOT) / "catalog-v001.xml"

    def _count(self, uris: list[str]) -> int:
        cls = _trade_party(extract_ref_model_inventory(uris, self._catalog()))
        assert cls is not None, "bsp:TradeParty not resolvable from these modules"
        return len(cls["properties"])

    def test_trade_party_keeps_every_property_in_either_order(self):
        """Was 13 forward / 17 reversed; must now be the union both ways.

        Asserted as an inequality against the truncated count rather than a hard 17, so a
        reference-model release that legitimately adds a property does not fail this.
        """
        forward = self._count(self.MODULES)
        reverse = self._count(list(reversed(self.MODULES)))
        assert forward == reverse, f"order-dependent: {forward} vs {reverse}"
        assert forward > 13, f"expected the union, got the truncated set ({forward})"
