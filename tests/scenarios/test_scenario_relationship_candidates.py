# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario coverage for issue #192 Phase A1 relationship candidates.

Exercises the persisted governance artifact end-to-end: a domain alignment with a
clustered set of address columns is written through ``write_claims_output`` into a
``{domain}-claims.yaml``, reloaded, and re-written to confirm:

* the advisory ``relationship_candidates`` section is persisted (and is NOT a
  governed claim), and
* a human decision on a real claim is preserved across a re-run while the
  freshly-detected candidates are carried forward.
"""

from __future__ import annotations

from kairos_ontology.claim_registry import load_registry, registry_path
from kairos_ontology.propose_alignment import (
    ColumnAlignment,
    DomainAlignment,
    TableAlignment,
    _detect_address_relationship_candidates,
    write_claims_output,
)


def _client_alignment() -> DomainAlignment:
    """A client-domain alignment whose tblCompany has a billing-address cluster."""
    ta = TableAlignment(
        system="adminpulse",
        table="tblCompany",
        ref_class="Party",
        ref_class_confidence=0.92,
        columns=[
            ColumnAlignment(
                column="CompanyID", data_type="int", ref_class="Party",
                ref_property="partyIdentifier", alignment="semantic", confidence=0.8,
            ),
            # Address-part columns force-fit as scalars (the #192 failure mode).
            ColumnAlignment(
                column="BillingStreet", data_type="varchar", ref_class="Party",
                ref_property="partyName", alignment="custom", confidence=0.3,
            ),
        ],
    )
    ta.relationship_candidates = _detect_address_relationship_candidates(
        "tblCompany",
        [{"name": n} for n in
         ("CompanyID", "BillingStreet", "BillingCity", "BillingPostalCode")],
    )
    return DomainAlignment(
        domain="client",
        domain_uris=["https://kairos.cnext.eu/ref/party#"],
        generated_at="2026-06-20T00:00:00Z",
        model_used="test",
        tables=[ta],
    )


class TestRelationshipCandidatesScenario:
    def test_candidates_persisted_as_advisory(self, tmp_path):
        write_claims_output(_client_alignment(), tmp_path)
        registry = load_registry(registry_path(tmp_path, "client"))

        assert len(registry.relationship_candidates) == 1
        cand = registry.relationship_candidates[0]
        assert cand["type"] == "address_relationship_candidate"
        assert cand["source_table"] == "tblCompany"
        assert cand["role"] == "billing"
        assert cand["suggested_relationship"] == "hasBillingAddress"
        assert cand["requires_human_confirmation"] is True
        assert cand["source_columns"] == [
            "BillingCity", "BillingPostalCode", "BillingStreet"
        ]
        # Advisory only — never emitted as a governed relationship claim.
        assert all(c.type != "relationship" for c in registry.claims)

    def test_rerun_preserves_decisions_and_carries_candidates(self, tmp_path):
        # First run establishes the registry; approve the party class claim.
        write_claims_output(_client_alignment(), tmp_path)
        path = registry_path(tmp_path, "client")
        text = path.read_text(encoding="utf-8").replace(
            "status: proposed", "status: approved", 1
        )
        path.write_text(text, encoding="utf-8")
        approved_ids = {
            c.id for c in load_registry(path).claims if c.status == "approved"
        }
        assert approved_ids

        # Re-run merges the fresh candidates over the curated registry.
        write_claims_output(_client_alignment(), tmp_path)
        merged = load_registry(path)

        assert len(merged.relationship_candidates) == 1
        assert {c.id for c in merged.claims if c.status == "approved"} == approved_ids
