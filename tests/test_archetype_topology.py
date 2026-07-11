# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for kairos_ontology.core.archetype_topology (DD-090)."""

from __future__ import annotations

import pytest

from archetype_fixtures import build_refmodels_root
from kairos_ontology.core.archetype_loader import load_archetype
from kairos_ontology.core.archetype_topology import derive_archetype_topology


@pytest.fixture()
def refroot(tmp_path):
    return build_refmodels_root(tmp_path)


@pytest.fixture()
def topology(refroot):
    archetype = load_archetype(refroot, "test-carrier")
    return derive_archetype_topology(refroot, archetype)


def test_all_present_concepts_resolved(topology):
    # 3 real concepts present; the GhostConcept is declared but absent from the graph.
    assert sorted(c.split("#")[-1] for c in topology.present_concepts) == [
        "Booking", "BookingParty", "CargoItem",
    ]


def test_missing_concept_warns_and_is_listed(topology):
    assert any(c.endswith("#GhostConcept") for c in topology.missing_concepts)
    assert any("GhostConcept" in w for w in topology.warnings())


def test_all_modules_loaded(topology):
    assert len(topology.loaded_modules) == 2


def test_edges_restricted_to_concept_set(topology):
    props = {e.property_uri.split("#")[-1] for e in topology.edges}
    # Both object properties connect concepts inside the set.
    assert props == {"hasCargoItem", "hasBookingParty"}


def test_min_cardinality_marks_mandatory(topology):
    cargo = next(e for e in topology.edges if e.property_uri.endswith("#hasCargoItem"))
    assert cargo.min_cardinality == 1
    assert cargo.mandatory is True
    # No upper bound declared → must still be asked.
    assert cargo.cardinality_declared is False


def test_max_cardinality_and_functional_declared(topology):
    party = next(e for e in topology.edges if e.property_uri.endswith("#hasBookingParty"))
    assert party.max_cardinality == 1
    assert party.functional is True
    assert party.cardinality_declared is True


def test_umbrella_import_not_required(tmp_path):
    """Regression: topology must parse module IRIs directly, not rely on owl:imports.

    The fixture catalog maps each module independently with NO umbrella ontology importing
    them, yet topology must still resolve every concept and edge. This guards against the
    load_graph_with_catalog() umbrella-import 0-result bug.
    """
    root = build_refmodels_root(tmp_path)
    archetype = load_archetype(root, "test-carrier")
    result = derive_archetype_topology(root, archetype)
    assert len(result.present_concepts) == 3
    assert len(result.edges) == 2
