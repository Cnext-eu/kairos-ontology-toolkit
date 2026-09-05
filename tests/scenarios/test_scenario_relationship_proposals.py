# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Every ``propose-relationships`` join tier, on one hub (#722, DD-220).

``tests/test_relationship_evidence.py`` pins ``_match_join`` in isolation. This module
exists because the defects #722 reports were not tier bugs in isolation -- they were tier
*interactions* over a whole hub. The tier-1 rule read as high-precision when you looked at
one pair of bindings; on a hub that named every primary key ``source_record_id`` it matched
every pair at once, and each individual proposal still looked locally plausible.

So the assertion that matters here is the **whole matrix at once**: which pairs resolve, by
which evidence, and which deliberately do not. A future change that fixes one tier by
quietly widening another shows up as a diff in this table and nowhere else.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kairos_ontology.core.propose_relationships import build_relationship_proposals

HUB_ROOT = Path(__file__).parent / "relationship-proposal-hub"

SALES = "https://synthetic.test/ont/sales#"
REF = "https://synthetic.test/ont/ref#"


@pytest.fixture(scope="module")
def report():
    # No accelerator: the blueprint path is covered by tests/test_propose_relationships.py,
    # and leaving it out keeps every edge here traceable to a declaration in sales.ttl.
    return build_relationship_proposals(hub_root=HUB_ROOT, ref_models_dir=None)


@pytest.fixture(scope="module")
def matrix(report):
    """``{(child, parent): (property local name, join, evidence, candidates)}``."""
    return {
        (p.child_binding, p.parent_binding): (
            p.property_uri.rsplit("#", 1)[-1],
            f"{p.local_column} = {p.foreign_column}",
            p.join_evidence or "UNRESOLVED",
            p.join_candidates,
        )
        for p in report.proposals
    }


def test_the_whole_proposal_matrix(matrix):
    """One assertion over every pair, so a regression cannot hide behind a plausible row."""
    assert matrix == {
        ("order", "ref-customer"): (
            "placedByCustomer", "customer_id = customer_id", "declared-fk", ()),
        ("order-addendum", "order"): (
            "addsToOrder", "order_id = order_id", "declared-fk", ()),
        ("order-line", "order"): (
            "belongsToOrder", "order_id = order_id", "name", ()),
        ("order-line", "ref-product"): (
            "refersToProduct", "product_id = product_id", "declared-fk", ()),
        ("order-ext", "order"): (
            "extendsOrder",
            "<CONFIRM_JOIN_COLUMN> = <CONFIRM_JOIN_COLUMN>", "UNRESOLVED", ()),
        ("shipment-leg", "shipment"): (
            "legOfShipment",
            "<CONFIRM_JOIN_COLUMN> = <CONFIRM_JOIN_COLUMN>", "UNRESOLVED",
            ("parent_shipment_ref",)),
    }


def test_a_uniform_surrogate_identity_never_joins_a_row_to_itself(matrix):
    """The #722 defect. Both relations key on ``source_record_id``.

    The old tier-1 rule matched the child's own primary key against the parent's and
    reported a resolved join, which would have emitted SQL joining a row to itself across
    two relations.
    """
    _prop, join, evidence, candidates = matrix[("shipment-leg", "shipment")]
    assert join == "<CONFIRM_JOIN_COLUMN> = <CONFIRM_JOIN_COLUMN>"
    assert evidence == "UNRESOLVED"
    # The FK it used to ignore is the one DD-139 already made the author declare.
    assert candidates == ("parent_shipment_ref",)


def test_a_composite_grain_still_contributes_its_fk_component(matrix):
    """The guard against reading #722's fix too broadly.

    ``order_id`` is part of ``order-line``'s identity, but not the whole of it -- it is a
    genuine foreign key, and the line-item archetype the toolkit itself scaffolds.
    """
    assert matrix[("order-line", "order")][1:3] == ("order_id = order_id", "name")


def test_a_declared_carrier_is_exempt_from_the_identity_exclusion(matrix):
    """``order-ext`` and ``order-addendum`` are the same shape; only the annotation differs.

    Both are 1:1 extensions keyed by their parent's key, which is name-indistinguishable
    from the self-join above. Declaring the column ``purpose: relationship`` is the
    documented way to recover the join DD-220 otherwise withholds.
    """
    assert matrix[("order-ext", "order")][2] == "UNRESOLVED"
    assert matrix[("order-addendum", "order")][1:3] == ("order_id = order_id", "declared-fk")


def test_two_carriers_on_one_child_each_find_their_own_parent(matrix):
    """Why tier 0 matches by name and not positionally.

    ``order-line`` declares ``product_id`` and keys on ``order_id``; pairing "the" carrier
    with "the" parent key would resolve one of these to the wrong column with confidence.
    """
    assert matrix[("order-line", "order")][1] == "order_id = order_id"
    assert matrix[("order-line", "ref-product")][1] == "product_id = product_id"


def test_a_cross_domain_parent_still_gets_its_key_contract(report):
    """DD-138: the externalReference is derived from the parent's materialized output."""
    proposal = next(
        p for p in report.proposals
        if (p.child_binding, p.parent_binding) == ("order", "ref-customer")
    )
    assert proposal.external_reference == {
        "name": "customer",
        "domain": "ref",
        "key": [{"column": "customer_id", "type": "string"}],
    }


def test_nothing_is_already_authored_in_the_baseline_hub(report):
    """Every binding here authors ``relationships: []``.

    Pinned so the suppression counts asserted below start from a known zero rather than
    from whatever the fixture happens to carry.
    """
    assert report.already_authored == ()
    assert len(report.bindings_without_relationships) == report.bindings_scanned == 8


def test_authoring_a_relationship_withdraws_exactly_that_proposal(tmp_path, report):
    """Re-run against a copy where one proposal has been accepted and pasted.

    This is the loop the command is actually used in: propose, author, re-run. Before
    DD-220 the re-run handed back the entry just authored -- with default policy fields in
    place of whatever the author chose.
    """
    import shutil

    hub = tmp_path / "hub"
    shutil.copytree(HUB_ROOT, hub)
    binding = hub / "integration" / "bindings" / "order-addendum.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace(
            "relationships: []",
            "relationships:\n"
            # A qname target against a parent whose target.class is a full URI, and a
            # deliberate `missingParent: null` -- the policy #722 reports being overwritten.
            "  - property: sales:addsToOrder\n"
            "    target: sales:Order\n"
            "    join: [{local: order_id, foreign: order_id}]\n"
            "    cardinality: many-to-one\n"
            "    mode: non-temporal\n"
            '    missingParent: "null"\n'
            "    ambiguousParent: error\n",
        ),
        encoding="utf-8",
    )

    after = build_relationship_proposals(hub_root=hub, ref_models_dir=None)
    assert after.already_authored == (
        ("order-addendum", f"{SALES}addsToOrder", f"{SALES}Order"),
    )
    # Exactly one proposal withdrawn; every other pair is untouched.
    assert {(p.child_binding, p.parent_binding) for p in after.proposals} == {
        (c, p) for c, p in
        {(x.child_binding, x.parent_binding) for x in report.proposals}
        if (c, p) != ("order-addendum", "order")
    }
