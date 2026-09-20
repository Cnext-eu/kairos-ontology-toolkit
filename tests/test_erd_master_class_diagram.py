# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The canonical ERD target's hub-wide master diagram is drawn from the graphs (#753).

The bound Silver and Gold families merge their per-domain ERDs into a master by text. The
first canonical master did the same, keyed on the Mermaid node id -- the class's local
name -- with two consequences, both reproduced before this rewrite: `party:Address` and
`billing:Address` collapsed into one block and one of them vanished without a warning, and
one IRI two domains had disambiguated differently (#806 assigns ids per rendered set) was
drawn as several nodes, with the edges landing on a stub and the block carrying the
members orphaned.

Rendering from the graphs makes the rendered set the whole hub, so `_node_ids` runs once
and one IRI is one node by construction. A per-domain file left behind by a renamed domain
cannot leak into the master either, because no file is read.
"""

from __future__ import annotations

import re
import textwrap

from rdflib import Graph

from kairos_ontology.core.projections.erd_projector import generate_master_class_diagram

_PARTY_NS = "https://example.test/ontology/party#"
_BILLING_NS = "https://example.test/ontology/billing#"

_PREFIXES = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix party: <https://example.test/ontology/party#> .
@prefix billing: <https://example.test/ontology/billing#> .
"""

_PARTY = """
party:Customer a owl:Class .
party:customerName a owl:DatatypeProperty ; rdfs:domain party:Customer ; rdfs:range xsd:string .
party:Country a owl:Class .
party:code a owl:DatatypeProperty ; rdfs:domain party:Country ; rdfs:range xsd:string .
party:country a owl:ObjectProperty ; rdfs:domain party:Customer ; rdfs:range party:Country .
party:Address a owl:Class .
party:street a owl:DatatypeProperty ; rdfs:domain party:Address ; rdfs:range xsd:string .
"""

# `billing` imports `party`: it reaches `party:Customer` across a relationship and
# specialises it, and it declares its own, unrelated `Address`.
_BILLING = """
billing:Invoice a owl:Class .
billing:amount a owl:DatatypeProperty ; rdfs:domain billing:Invoice ; rdfs:range xsd:decimal .
billing:billedTo a owl:ObjectProperty ; rdfs:domain billing:Invoice ; rdfs:range party:Customer .
billing:Address a owl:Class .
billing:iban a owl:DatatypeProperty ; rdfs:domain billing:Address ; rdfs:range xsd:string .
billing:billedAt a owl:ObjectProperty ; rdfs:domain billing:Invoice ; rdfs:range billing:Address .
billing:Customer a owl:Class ; rdfs:subClassOf party:Customer .
"""


def _graph(*bodies: str) -> Graph:
    graph = Graph()
    graph.parse(
        data=_PREFIXES + "".join(textwrap.dedent(body) for body in bodies), format="turtle"
    )
    return graph


def _hub():
    party_local = _graph(_PARTY)
    billing_local = _graph(_BILLING)
    return [
        (party_local, _PARTY_NS, party_local),
        (_graph(_PARTY, _BILLING), _BILLING_NS, billing_local),
    ]


def _blocks(text: str) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("class ") and stripped.endswith("{"):
            current = stripped[len("class ") : -1].strip()
            blocks[current] = []
        elif stripped == "}":
            current = None
        elif current is not None:
            blocks[current].append(stripped)
    return blocks


def _block_with(blocks: dict[str, list[str]], member: str) -> str:
    matches = [node for node, body in blocks.items() if member in body]
    assert len(matches) == 1, (member, matches)
    return matches[0]


class TestMasterClassDiagram:
    def test_every_domain_contributes(self):
        text = generate_master_class_diagram(_hub())
        blocks = _blocks(text)
        for member in ("string customerName", "string code", "decimal amount"):
            _block_with(blocks, member)

    def test_a_class_two_domains_reach_is_one_node(self):
        text = generate_master_class_diagram(_hub())
        # party declares it; billing used to draw it again as a stereotyped external. Once,
        # hub-wide -- the `#`-prefixed copy on billing:Customer is an inherited member.
        own = [line for line in text.splitlines() if line.strip() == "string customerName"]
        assert len(own) == 1

    def test_two_classes_that_share_a_local_name_stay_two(self):
        """The text merge keyed on `class Address {` kept whichever block ranked higher
        and dropped the other; `party:street` disappeared from the hub-wide diagram."""
        blocks = _blocks(generate_master_class_diagram(_hub()))
        addresses = sorted(node for node in blocks if node.startswith("Address"))
        assert len(addresses) == 2, addresses
        assert _block_with(blocks, "string street") in addresses
        assert _block_with(blocks, "string iban") in addresses

    def test_one_iri_is_one_node_and_the_edges_land_on_it(self):
        """`party` drew `party:Customer` as `Customer`; `billing`, where the name was
        contested, drew it as a suffixed stub beside its own `Customer_billing`. The text
        merge kept all three, with the inheritance and `billedTo` edges on the stub."""
        text = generate_master_class_diagram(_hub())
        blocks = _blocks(text)
        customers = [node for node in blocks if node.startswith("Customer")]
        assert len(customers) == 2, customers  # party:Customer and billing:Customer
        full = _block_with(blocks, "string customerName")
        assert re.search(rf"^\s+{re.escape(full)} <\|-- ", text, re.MULTILINE), text
        assert re.search(rf'--> "[^"]*" {re.escape(full)} : billedTo$', text, re.MULTILINE)

    def test_it_renders_one_classdiagram_header_stamped_with_the_toolkit(self):
        text = generate_master_class_diagram(_hub(), "acme-hub")
        assert text.count("classDiagram") == 1
        assert text.startswith("---\nconfig:\n  layout: elk\n---\n%% Generated by kairos-ontology")
        assert "for acme-hub:" in text

    def test_the_output_is_deterministic(self):
        assert generate_master_class_diagram(_hub()) == generate_master_class_diagram(_hub())
        # Domain order is not a degree of freedom either.
        assert generate_master_class_diagram(list(reversed(_hub()))) == (
            generate_master_class_diagram(_hub())
        )

    def test_no_domains_returns_none(self):
        assert generate_master_class_diagram([]) is None

    def test_a_hub_with_no_classes_returns_none(self):
        assert generate_master_class_diagram([(Graph(), _PARTY_NS, None)]) is None
