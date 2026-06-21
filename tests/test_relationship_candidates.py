# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for issue #192 Phase A1 — deterministic address-relationship candidates.

Covers the detector (clustering, role split, false-positive rejection, additivity),
its surfacing in ``alignment_to_dict``, and the advisory ``relationship_candidates``
round-trip through the Claim Registry (including merge preservation).
"""

from __future__ import annotations

from kairos_ontology.claim_registry import (
    Claim,
    ClaimRegistry,
    merge_preserving_decisions,
)
from kairos_ontology.migrate_claims import alignment_to_registry
from kairos_ontology.propose_alignment import (
    ColumnAlignment,
    DomainAlignment,
    TableAlignment,
    _address_part_kind,
    _address_relationship_name,
    _address_role,
    _detect_address_relationship_candidates,
    alignment_to_dict,
)


def _cols(*names: str) -> list[dict[str, str]]:
    return [{"name": n} for n in names]


# ---------------------------------------------------------------------------
# _address_part_kind / _address_role / _address_relationship_name
# ---------------------------------------------------------------------------


class TestAddressPartKind:
    def test_canonical_kinds(self):
        assert _address_part_kind("billing_street") == "street"
        assert _address_part_kind("postal_code") == "postal"
        assert _address_part_kind("zip") == "postal"
        assert _address_part_kind("house_number") == "house_number"
        assert _address_part_kind("city") == "city"
        assert _address_part_kind("country") == "country"
        assert _address_part_kind("province") == "state"
        assert _address_part_kind("address_line_1") == "address_line"

    def test_compound_compact_forms(self):
        assert _address_part_kind("postalcode") == "postal"
        assert _address_part_kind("housenumber") == "house_number"

    def test_non_address_returns_none(self):
        assert _address_part_kind("company_id") is None
        assert _address_part_kind("vat_number") is None

    def test_substring_false_positive_avoided(self):
        # 'ethnicity' contains 'city' as a substring but is not a token.
        assert _address_part_kind("ethnicity") is None


class TestAddressRole:
    def test_qualifier_is_role(self):
        assert _address_role("billing_city") == "billing"
        assert _address_role("shipping_street") == "shipping"

    def test_unqualified_is_default(self):
        assert _address_role("street") == "default"
        assert _address_role("postal_code") == "default"


class TestRelationshipName:
    def test_default_and_qualified(self):
        assert _address_relationship_name("default") == "hasAddress"
        assert _address_relationship_name("billing") == "hasBillingAddress"
        assert _address_relationship_name("shipping") == "hasShippingAddress"


# ---------------------------------------------------------------------------
# _detect_address_relationship_candidates
# ---------------------------------------------------------------------------


class TestDetectAddressRelationshipCandidates:
    def test_clustered_columns_emit_single_candidate(self):
        out = _detect_address_relationship_candidates(
            "companies",
            _cols("billing_street", "billing_city", "billing_postal_code",
                  "company_id", "vat"),
        )
        assert len(out) == 1
        c = out[0]
        assert c["type"] == "address_relationship_candidate"
        assert c["source_table"] == "companies"
        assert c["role"] == "billing"
        assert c["suggested_relationship"] == "hasBillingAddress"
        assert c["target_concept"] == "Address"
        assert c["requires_human_confirmation"] is True
        assert c["source_columns"] == [
            "billing_city", "billing_postal_code", "billing_street"
        ]
        assert c["address_parts"] == ["city", "postal", "street"]
        # No resolvable URI is emitted (A2 deferred).
        assert "target_uri" not in c
        assert "class_uri" not in c

    def test_billing_and_shipping_split_into_two_roles(self):
        out = _detect_address_relationship_candidates(
            "orders",
            _cols("billing_street", "billing_city",
                  "shipping_street", "shipping_city"),
        )
        rels = {c["suggested_relationship"] for c in out}
        assert rels == {"hasBillingAddress", "hasShippingAddress"}
        billing = next(c for c in out if c["role"] == "billing")
        assert billing["source_columns"] == ["billing_city", "billing_street"]

    def test_unqualified_strong_parts_use_default_role(self):
        out = _detect_address_relationship_candidates(
            "site", _cols("street", "postcode")
        )
        assert len(out) == 1
        assert out[0]["role"] is None
        assert out[0]["suggested_relationship"] == "hasAddress"

    def test_single_part_does_not_fire(self):
        # One complementary part is below the >=2 threshold.
        assert _detect_address_relationship_candidates(
            "t", _cols("billing_street")
        ) == []

    def test_country_of_origin_is_not_an_address_cluster(self):
        assert _detect_address_relationship_candidates(
            "t", _cols("country_of_origin", "product_name")
        ) == []

    def test_billing_email_is_not_address(self):
        assert _detect_address_relationship_candidates(
            "t", _cols("billing_email", "billing_phone")
        ) == []

    def test_deterministic_ordering(self):
        a = _detect_address_relationship_candidates(
            "t", _cols("shipping_city", "shipping_street",
                       "billing_city", "billing_street"))
        b = _detect_address_relationship_candidates(
            "t", _cols("billing_street", "shipping_street",
                       "billing_city", "shipping_city"))
        assert [c["suggested_relationship"] for c in a] == [
            "hasBillingAddress", "hasShippingAddress"
        ]
        assert a == b


# ---------------------------------------------------------------------------
# Surfacing through alignment_to_dict (additive — scalars untouched)
# ---------------------------------------------------------------------------


def _domain_with_candidates() -> DomainAlignment:
    ta = TableAlignment(
        system="erp",
        table="companies",
        ref_class="Organization",
        ref_class_confidence=0.9,
        columns=[
            ColumnAlignment(
                column="billing_street", data_type="varchar", ref_class="Address",
                ref_property="streetName", alignment="custom", confidence=0.4,
            ),
        ],
    )
    ta.relationship_candidates = _detect_address_relationship_candidates(
        "companies", _cols("billing_street", "billing_city", "billing_postal_code")
    )
    return DomainAlignment(
        domain="party", domain_uris=["https://ex.org/party"],
        generated_at="2026-06-20", model_used="test", tables=[ta],
    )


class TestAlignmentToDict:
    def test_candidates_emitted_on_table(self):
        data = alignment_to_dict(_domain_with_candidates())
        table = data["tables"][0]
        assert "relationship_candidates" in table
        assert table["relationship_candidates"][0]["suggested_relationship"] == (
            "hasBillingAddress"
        )
        # Additive: the scalar column mapping is still present and untouched.
        assert table["columns"][0]["column"] == "billing_street"

    def test_no_candidates_no_key(self):
        ta = TableAlignment(
            system="erp", table="invoices", ref_class="Invoice",
            ref_class_confidence=0.9,
            columns=[
                ColumnAlignment(
                    column="invoice_id", data_type="int", ref_class="Invoice",
                    ref_property="invoiceIdentifier", alignment="exact",
                    confidence=0.99,
                ),
            ],
        )
        dom = DomainAlignment(
            domain="invoice", domain_uris=["https://ex.org/invoice"],
            generated_at="2026-06-20", model_used="test", tables=[ta],
        )
        table = alignment_to_dict(dom)["tables"][0]
        assert "relationship_candidates" not in table


# ---------------------------------------------------------------------------
# Claim Registry round-trip + merge preservation
# ---------------------------------------------------------------------------


class TestRegistryRoundTrip:
    def test_candidates_collected_into_registry(self):
        registry = alignment_to_registry(alignment_to_dict(_domain_with_candidates()))
        assert len(registry.relationship_candidates) == 1
        cand = registry.relationship_candidates[0]
        assert cand["suggested_relationship"] == "hasBillingAddress"
        # Advisory only — it is NOT emitted as a governed claim.
        assert all(c.type != "relationship" for c in registry.claims)

    def test_to_dict_emits_advisory_section_before_claims(self):
        registry = alignment_to_registry(alignment_to_dict(_domain_with_candidates()))
        out = registry.to_dict()
        assert "relationship_candidates" in out
        keys = list(out.keys())
        assert keys.index("relationship_candidates") < keys.index("claims")

    def test_from_dict_round_trip(self):
        registry = alignment_to_registry(alignment_to_dict(_domain_with_candidates()))
        restored = ClaimRegistry.from_dict(registry.to_dict())
        assert restored.relationship_candidates == registry.relationship_candidates

    def test_empty_when_no_clusters(self):
        out = ClaimRegistry(domain="x").to_dict()
        assert "relationship_candidates" not in out

    def test_merge_carries_fresh_candidates(self):
        new = alignment_to_registry(alignment_to_dict(_domain_with_candidates()))
        existing = ClaimRegistry(
            domain="party",
            claims=[Claim(id="party-organization", type="class", status="approved",
                          class_uri="https://ex.org/party#Organization")],
        )
        merged = merge_preserving_decisions(new, existing)
        assert merged.relationship_candidates == new.relationship_candidates
