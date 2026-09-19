# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""`_active_source_inputs` consumes `class_uris` three ways, deliberately (#735).

One input, three filters, and the split was undocumented and partly accidental:

* the contract filter and the table-mapping filter compared against the bare set;
* the property filter walked `rdfs:subClassOf` upward transitively;
* the widened set was then consulted **only in the fallback arm** of the column filter --
  for columns whose `source_column_uri` did not resolve to a known table -- so whether the
  ancestor walk had any effect depended on whether the source column happened to be
  registered. That is not a semantic distinction.

Under #729's policy (*traverse for compatibility, exact for identity*): contracts and
table mappings answer "does this domain own this?", which does not inherit; the property
filter answers "could a class in scope carry this?", which does.

This is live on the Gold path -- `medallion_gold_projector` calls `bind_sources` -- not
legacy-only.
"""

from __future__ import annotations

from rdflib import Graph, RDFS, URIRef

from kairos_ontology.core.projections.dbt.bind import _active_source_inputs
from kairos_ontology.core.projections.dbt.mapping_specs import (
    ColumnMappingFact,
    SourceMappings,
    TableMappingFact,
)

_NS = "https://example.test/ont#"
_PARENT = f"{_NS}Party"
_CHILD = f"{_NS}Customer"
_TABLE = "https://example.test/src#customers"


def _graph(*, owl_thing: bool = False) -> Graph:
    graph = Graph()
    graph.add((URIRef(_CHILD), RDFS.subClassOf, URIRef(_PARENT)))
    graph.add((URIRef(f"{_NS}partyName"), RDFS.domain, URIRef(_PARENT)))
    graph.add((URIRef(f"{_NS}customerCode"), RDFS.domain, URIRef(_CHILD)))
    if owl_thing:
        graph.add((URIRef(_PARENT), RDFS.subClassOf, URIRef("http://www.w3.org/2002/07/owl#Thing")))
        graph.add(
            (
                URIRef(f"{_NS}strayProperty"),
                RDFS.domain,
                URIRef("http://www.w3.org/2002/07/owl#Thing"),
            )
        )
    return graph


class _Contract:
    def __init__(self, target_class: str) -> None:
        self.target_class = target_class
        self.virtual_source_iri = f"{target_class}#virtual"


def _run(*, class_uris: set[str], contracts=None, tables=(), columns=(), graph=None):
    return _active_source_inputs(
        systems=[
            {
                "uri": "https://example.test/src",
                "tables": [
                    {
                        "uri": _TABLE,
                        "relation_kind": "physical",
                        "columns": [{"uri": f"{_TABLE}#code"}],
                    }
                ],
            }
        ],
        mappings=SourceMappings(tables=tuple(tables), columns=tuple(columns)),
        contracts=contracts or {},
        class_uris=class_uris,
        graph=graph if graph is not None else _graph(),
    )


def _table_mapping(target: str) -> TableMappingFact:
    return TableMappingFact(
        resource_uri=f"{target}#tm",
        source_table_uri=_TABLE,
        target_class_uri=target,
        mapping_type="direct",
        match_type="exact",
    )


def _column_mapping(prop: str, *, registered: bool) -> ColumnMappingFact:
    return ColumnMappingFact(
        resource_uri=f"{prop}#cm",
        source_column_uri=f"{_TABLE}#code" if registered else "https://example.test/src#ghost",
        target_property_uri=prop,
        match_type="exact",
    )


class TestOwnershipIsExact:
    """A contract or table mapping declared against an ancestor belongs to whoever
    declared it, not to every domain that specialises the class."""

    def test_a_contract_on_an_ancestor_is_not_pulled_in(self):
        _, _, contracts, _ = _run(
            class_uris={_CHILD}, contracts={"parent": _Contract(_PARENT)}
        )
        assert contracts == {}

    def test_a_contract_on_the_class_itself_is_active(self):
        _, _, contracts, _ = _run(
            class_uris={_CHILD}, contracts={"own": _Contract(_CHILD)}
        )
        assert set(contracts) == {"own"}

    def test_a_table_mapping_targeting_an_ancestor_is_dropped(self):
        _, mappings, _, _ = _run(class_uris={_CHILD}, tables=[_table_mapping(_PARENT)])
        assert mappings.tables == ()


class TestPropertyScopeTraversesUp:
    """A property declared on an ancestor genuinely applies to its descendants."""

    def test_an_inherited_property_is_in_scope(self):
        _, mappings, _, _ = _run(
            class_uris={_CHILD},
            columns=[_column_mapping(f"{_NS}partyName", registered=False)],
        )
        assert [item.target_property_uri for item in mappings.columns] == [f"{_NS}partyName"]

    def test_an_unrelated_property_is_not(self):
        _, mappings, _, _ = _run(
            class_uris={_CHILD},
            columns=[_column_mapping(f"{_NS}vesselName", registered=False)],
        )
        assert mappings.columns == ()


class TestWidenedScopeIsNotGatedOnColumnRegistration:
    """The accidental part: whether the ancestor walk mattered depended on whether the
    source column resolved to a known table, which is not a semantic distinction."""

    def test_a_registered_column_on_an_active_table_still_survives(self):
        _, mappings, _, _ = _run(
            class_uris={_CHILD},
            tables=[_table_mapping(_CHILD)],
            columns=[_column_mapping(f"{_NS}partyName", registered=True)],
        )
        assert len(mappings.columns) == 1


class TestW3CGuard:
    """`owl:Thing` in scope would match any property declaring `rdfs:domain owl:Thing` --
    a common symptom of a missing `owl:imports` -- pulling in every class at once."""

    def test_owl_thing_does_not_widen_the_scope(self):
        _, mappings, _, _ = _run(
            class_uris={_CHILD},
            columns=[_column_mapping(f"{_NS}strayProperty", registered=False)],
            graph=_graph(owl_thing=True),
        )
        assert mappings.columns == ()

    def test_a_real_ancestor_still_widens_it(self):
        _, mappings, _, _ = _run(
            class_uris={_CHILD},
            columns=[_column_mapping(f"{_NS}partyName", registered=False)],
            graph=_graph(owl_thing=True),
        )
        assert len(mappings.columns) == 1
