# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the Claim Registry schema v1 (``claim_registry``)."""

from __future__ import annotations

import pytest

from kairos_ontology.claim_registry import (
    CLAIM_REGISTRY_SCHEMA_VERSION,
    TRIAGE_TO_DISPOSITION,
    Claim,
    ClaimRegistry,
    CoverageSystem,
    CoverageTable,
    Deviation,
    EvidenceSource,
    Freshness,
    OwnershipOverride,
    ReferenceData,
    SilverImpact,
    dump_registry,
    is_valid_transition,
    load_registry,
    merge_preserving_decisions,
    registry_path,
    validate_registry,
    validation_errors,
    write_registry,
)


def _good_registry() -> ClaimRegistry:
    return ClaimRegistry(
        domain="party",
        generated_at="2026-06-15T19:30:00Z",
        algorithm_version=3,
        freshness=Freshness(affinity_sha256="abc", alignment_params_sha256="def"),
        coverage=[
            CoverageSystem(
                system="crm",
                tables=[
                    CoverageTable(
                        table="account",
                        total_columns=24,
                        mapped_columns=21,
                        custom_columns=3,
                        anchor_state="matched",
                        ref_class="TradeParty",
                    )
                ],
            )
        ],
        claims=[
            Claim(
                id="party-trade-party",
                type="class",
                status="approved",
                disposition="claim",
                origin="imported",
                class_uri="https://ex.org/acc#TradeParty",
                owner="data-domain-party",
                evidence_sources=[
                    EvidenceSource(type="source_table", system="crm", table="account")
                ],
                silver_impact=SilverImpact(table="dim_party", change_type="additive"),
                rationale="closest concept",
            ),
            Claim(
                id="party-credit-limit",
                type="property",
                status="approved",
                disposition="specialize",
                origin="authored",
                property_uri="https://ex.org/client#creditLimit",
                owner="data-domain-party",
                evidence_sources=[
                    EvidenceSource(
                        type="source_column", system="erp", table="customer",
                        column="credit_limit",
                    )
                ],
                silver_impact=SilverImpact(
                    table="dim_party", column="credit_limit", change_type="additive"
                ),
            ),
        ],
    )


class TestRoundTrip:
    def test_to_from_dict_is_stable(self):
        reg = _good_registry()
        again = ClaimRegistry.from_dict(reg.to_dict())
        assert again.to_dict() == reg.to_dict()

    def test_dump_then_load(self, tmp_path):
        reg = _good_registry()
        path = registry_path(tmp_path, "party")
        write_registry(reg, path)
        assert path.name == "party-claims.yaml"
        loaded = load_registry(path)
        assert loaded.to_dict() == reg.to_dict()

    def test_dump_omits_empty_optionals(self):
        reg = ClaimRegistry(domain="x", claims=[Claim(id="x-1", type="class",
                            class_uri="u", status="proposed")])
        text = dump_registry(reg)
        assert "freshness" not in text
        assert "coverage" not in text
        # schema_version + domain + claims always present
        assert "schema_version" in text
        assert "claims" in text

    def test_dump_preserves_key_order(self):
        text = dump_registry(_good_registry())
        assert text.index("schema_version") < text.index("domain") < text.index("claims")


class TestValidation:
    def test_good_registry_has_no_errors(self):
        assert validation_errors(validate_registry(_good_registry())) == []

    def test_bad_schema_version(self):
        reg = _good_registry()
        reg.schema_version = 99
        msgs = [i.message for i in validation_errors(validate_registry(reg))]
        assert any("schema_version" in m for m in msgs)

    def test_duplicate_id(self):
        reg = _good_registry()
        reg.claims[1].id = reg.claims[0].id
        msgs = [i.message for i in validation_errors(validate_registry(reg))]
        assert any("duplicate claim id" in m for m in msgs)

    def test_invalid_enums(self):
        reg = _good_registry()
        reg.claims[0].status = "bogus"
        reg.claims[0].disposition = "nope"
        reg.claims[0].type = "frob"
        reg.claims[0].origin = "elsewhere"
        msgs = " ".join(i.message for i in validation_errors(validate_registry(reg)))
        assert "invalid status" in msgs
        assert "invalid disposition" in msgs
        assert "invalid type" in msgs
        assert "invalid origin" in msgs

    def test_class_requires_class_uri(self):
        reg = ClaimRegistry(domain="d", claims=[
            Claim(id="d-1", type="class", status="approved", disposition="claim",
                  class_uri=None, evidence_sources=[
                      EvidenceSource(type="source_table", system="s", table="t")])
        ])
        msgs = [i.message for i in validation_errors(validate_registry(reg))]
        assert any("requires 'class_uri'" in m for m in msgs)

    def test_property_requires_property_uri(self):
        reg = ClaimRegistry(domain="d", claims=[
            Claim(id="d-1", type="property", status="approved", disposition="claim",
                  property_uri=None, evidence_sources=[
                      EvidenceSource(type="source_column", system="s", table="t",
                                     column="c")])
        ])
        msgs = [i.message for i in validation_errors(validate_registry(reg))]
        assert any("requires 'property_uri'" in m for m in msgs)

    def test_proposed_class_may_lack_uri(self):
        # migration lands candidates as proposed without a resolved URI
        reg = ClaimRegistry(domain="d", claims=[
            Claim(id="d-1", type="class", status="proposed", disposition="claim",
                  class_uri=None)
        ])
        assert validation_errors(validate_registry(reg)) == []

    def test_passthrough_claim_needs_no_uri(self):
        reg = ClaimRegistry(domain="d", claims=[
            Claim(id="d-1", type="property", status="approved", disposition="passthrough",
                  property_uri=None, evidence_sources=[
                      EvidenceSource(type="source_column", system="s", table="t",
                                     column="c")])
        ])
        assert validation_errors(validate_registry(reg)) == []

    def test_gap_claim_needs_no_uri(self):
        reg = ClaimRegistry(domain="d", claims=[
            Claim(id="d-1", type="class", status="proposed", disposition="gap",
                  class_uri=None)
        ])
        assert validation_errors(validate_registry(reg)) == []

    def test_approved_claim_needs_evidence(self):
        reg = ClaimRegistry(domain="d", claims=[
            Claim(id="d-1", type="class", status="approved", class_uri="u",
                  evidence_sources=[])
        ])
        msgs = [i.message for i in validation_errors(validate_registry(reg))]
        assert any("no evidence_sources" in m for m in msgs)

    def test_proposed_claim_may_lack_evidence(self):
        reg = ClaimRegistry(domain="d", claims=[
            Claim(id="d-1", type="class", status="proposed", class_uri="u",
                  evidence_sources=[])
        ])
        assert validation_errors(validate_registry(reg)) == []

    def test_duplicate_approved_uri(self):
        reg = _good_registry()
        reg.claims[1].type = "class"
        reg.claims[1].property_uri = None
        reg.claims[1].class_uri = reg.claims[0].class_uri
        msgs = [i.message for i in validation_errors(validate_registry(reg))]
        assert any("duplicate approved claim" in m for m in msgs)

    def test_superseded_by_must_resolve(self):
        reg = _good_registry()
        reg.claims[0].status = "deprecated"
        reg.claims[0].superseded_by = "does-not-exist"
        msgs = [i.message for i in validation_errors(validate_registry(reg))]
        assert any("not a known claim id" in m for m in msgs)

    def test_superseded_by_on_non_deprecated_warns(self):
        reg = _good_registry()
        reg.claims[0].superseded_by = "party-credit-limit"
        issues = validate_registry(reg)
        assert any(i.level == "warning" and "non-deprecated" in i.message for i in issues)
        assert validation_errors(issues) == []

    def test_invalid_anchor_state(self):
        reg = _good_registry()
        reg.coverage[0].tables[0].anchor_state = "weird"
        msgs = [i.message for i in validation_errors(validate_registry(reg))]
        assert any("invalid anchor_state" in m for m in msgs)

    def test_invalid_change_type(self):
        reg = _good_registry()
        reg.claims[0].silver_impact.change_type = "huge"
        msgs = [i.message for i in validation_errors(validate_registry(reg))]
        assert any("change_type" in m for m in msgs)


class TestTransitions:
    @pytest.mark.parametrize("current,target,ok", [
        ("proposed", "approved", True),
        ("proposed", "rejected", True),
        ("proposed", "deferred", True),
        ("approved", "deprecated", True),
        ("deferred", "approved", True),
        ("approved", "rejected", False),
        ("rejected", "approved", False),
        ("deprecated", "approved", False),
        ("proposed", "deprecated", False),
    ])
    def test_transition_matrix(self, current, target, ok):
        assert is_valid_transition(current, target) is ok


class TestTriageMap:
    def test_triage_values(self):
        assert TRIAGE_TO_DISPOSITION["model"] == "specialize"
        assert TRIAGE_TO_DISPOSITION["silver-passthrough"] == "passthrough"
        assert TRIAGE_TO_DISPOSITION["skip"] == "skip"


def test_load_rejects_non_mapping(tmp_path):
    bad = tmp_path / "bad-claims.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_registry(bad)


def test_schema_version_constant():
    assert CLAIM_REGISTRY_SCHEMA_VERSION == 1


class TestMergePreservingDecisions:
    def _existing(self, status="approved", **overrides):
        claim = Claim(
            id="party-trade-party", type="class", status=status, disposition="claim",
            origin="imported", class_uri="https://ex.org/acc#TradeParty",
            owner="data-domain-party",
            evidence_sources=[EvidenceSource(type="source_table", system="crm",
                                             table="account")],
            silver_impact=SilverImpact(table="dim_party", change_type="additive"),
            rationale="curated by human",
        )
        for k, v in overrides.items():
            setattr(claim, k, v)
        return ClaimRegistry(domain="party", claims=[claim])

    def _new_proposed(self):
        return ClaimRegistry(
            domain="party",
            generated_at="2026-06-15T20:00:00Z",
            algorithm_version=4,
            claims=[Claim(
                id="party-trade-party", type="class", status="proposed",
                disposition="claim", origin="imported", class_uri=None,
                evidence_sources=[EvidenceSource(type="source_table", system="erp",
                                                 table="customer")],
                rationale="freshly proposed",
            )],
        )

    def test_decided_claim_curation_preserved(self):
        merged = merge_preserving_decisions(self._new_proposed(), self._existing())
        c = merged.claims[0]
        assert c.status == "approved"
        assert c.class_uri == "https://ex.org/acc#TradeParty"
        assert c.owner == "data-domain-party"
        assert c.rationale == "curated by human"
        assert c.silver_impact.table == "dim_party"

    def test_decided_claim_evidence_refreshed(self):
        merged = merge_preserving_decisions(self._new_proposed(), self._existing())
        ev = merged.claims[0].evidence_sources
        assert [(e.system, e.table) for e in ev] == [("erp", "customer")]

    def test_proposed_existing_is_replaced(self):
        merged = merge_preserving_decisions(
            self._new_proposed(), self._existing(status="proposed")
        )
        c = merged.claims[0]
        assert c.status == "proposed"
        assert c.rationale == "freshly proposed"
        assert c.class_uri is None

    def test_coverage_and_meta_from_new(self):
        new = self._new_proposed()
        new.coverage = [CoverageSystem(system="erp", tables=[CoverageTable(
            table="customer", anchor_state="matched")])]
        merged = merge_preserving_decisions(new, self._existing())
        assert merged.algorithm_version == 4
        assert merged.generated_at == "2026-06-15T20:00:00Z"
        assert merged.coverage[0].system == "erp"

    def test_vanished_decided_claim_retained(self):
        existing = ClaimRegistry(domain="party", claims=[
            self._existing().claims[0],
            Claim(id="party-old", type="class", status="approved", disposition="claim",
                  class_uri="u", evidence_sources=[EvidenceSource(type="source_table",
                  system="s", table="t")]),
        ])
        merged = merge_preserving_decisions(self._new_proposed(), existing)
        ids = {c.id for c in merged.claims}
        assert "party-old" in ids  # decided claim not dropped

    def test_vanished_proposed_claim_dropped(self):
        existing = ClaimRegistry(domain="party", claims=[
            Claim(id="party-stale", type="class", status="proposed", class_uri=None),
        ])
        merged = merge_preserving_decisions(self._new_proposed(), existing)
        assert all(c.id != "party-stale" for c in merged.claims)

    def test_new_claim_added(self):
        new = self._new_proposed()
        new.claims.append(Claim(id="party-brand-new", type="class", status="proposed",
                                class_uri=None))
        merged = merge_preserving_decisions(new, self._existing())
        assert any(c.id == "party-brand-new" for c in merged.claims)

    def test_result_sorted_and_valid(self):
        merged = merge_preserving_decisions(self._new_proposed(), self._existing())
        ids = [c.id for c in merged.claims]
        assert ids == sorted(ids)
        assert validation_errors(validate_registry(merged)) == []


class TestSlice4Schema:
    """MDM / reference-data / ownership / deviation schema additions (Slice 4)."""

    def test_reference_data_round_trip(self):
        rd = ReferenceData(
            authority_system="iso", code_system="ISO-3166-1", key="alpha2", scd_type=1
        )
        assert ReferenceData.from_dict(rd.to_dict()) == rd

    def test_reference_data_omits_none(self):
        rd = ReferenceData(code_system="ISO-3166-1")
        assert rd.to_dict() == {"code_system": "ISO-3166-1"}

    def test_deviation_round_trip(self):
        dev = Deviation(reason="no equivalent", owner="arch", gap_request="GH-42")
        assert Deviation.from_dict(dev.to_dict()) == dev

    def test_ownership_override_round_trip(self):
        ovr = OwnershipOverride(owner="cdo", rationale="conformed dimension")
        assert OwnershipOverride.from_dict(ovr.to_dict()) == ovr

    def test_claim_round_trip_with_new_fields(self):
        claim = Claim(
            id="party-country", type="reference_data", status="approved",
            disposition="claim", class_uri="https://ex.org/common#Country",
            mdm_anchor=True,
            reference_data=ReferenceData(code_system="ISO-3166-1", scd_type=1),
            deviation=Deviation(reason="x", owner="y"),
            ownership_override=OwnershipOverride(owner="cdo", rationale="shared"),
            passthrough_reviewed=True,
            evidence_sources=[EvidenceSource(type="source_table", system="mdm",
                                             table="country")],
        )
        again = Claim.from_dict(claim.to_dict())
        assert again.to_dict() == claim.to_dict()
        assert again.mdm_anchor is True
        assert again.passthrough_reviewed is True
        assert again.reference_data.code_system == "ISO-3166-1"
        assert again.ownership_override.owner == "cdo"

    def test_dump_omits_default_new_fields(self):
        reg = ClaimRegistry(domain="x", claims=[
            Claim(id="x-1", type="class", class_uri="u", status="proposed")
        ])
        text = dump_registry(reg)
        assert "mdm_anchor" not in text
        assert "passthrough_reviewed" not in text
        assert "reference_data" not in text
        assert "ownership_override" not in text
        assert "deviation" not in text

    def test_ownership_override_requires_owner_and_rationale(self):
        reg = ClaimRegistry(domain="d", claims=[
            Claim(id="d-1", type="class", status="proposed", class_uri="u",
                  ownership_override=OwnershipOverride(owner="cdo", rationale=None))
        ])
        msgs = [i.message for i in validation_errors(validate_registry(reg))]
        assert any("ownership_override requires" in m for m in msgs)

    def test_well_formed_override_validates(self):
        reg = ClaimRegistry(domain="d", claims=[
            Claim(id="d-1", type="class", status="proposed", class_uri="u",
                  ownership_override=OwnershipOverride(owner="cdo", rationale="shared"))
        ])
        assert validation_errors(validate_registry(reg)) == []

    def test_mdm_anchor_on_non_reference_data_warns(self):
        reg = ClaimRegistry(domain="d", claims=[
            Claim(id="d-1", type="class", status="proposed", class_uri="u",
                  mdm_anchor=True)
        ])
        issues = validate_registry(reg)
        assert any(i.level == "warning" and "mdm_anchor" in i.message for i in issues)
        assert validation_errors(issues) == []

    def test_reference_data_on_non_reference_data_warns(self):
        reg = ClaimRegistry(domain="d", claims=[
            Claim(id="d-1", type="class", status="proposed", class_uri="u",
                  reference_data=ReferenceData(code_system="x"))
        ])
        issues = validate_registry(reg)
        assert any(
            i.level == "warning" and "reference_data" in i.message for i in issues
        )

    def test_merge_preserves_new_curated_fields(self):
        existing = ClaimRegistry(domain="party", claims=[Claim(
            id="party-country", type="reference_data", status="approved",
            disposition="claim", class_uri="https://ex.org/common#Country",
            mdm_anchor=True,
            reference_data=ReferenceData(code_system="ISO-3166-1"),
            ownership_override=OwnershipOverride(owner="cdo", rationale="shared"),
            passthrough_reviewed=True,
            evidence_sources=[EvidenceSource(type="source_table", system="mdm",
                                             table="country")],
        )])
        new = ClaimRegistry(domain="party", claims=[Claim(
            id="party-country", type="reference_data", status="proposed",
            disposition="claim", class_uri=None,
            evidence_sources=[EvidenceSource(type="affinity", system="mdm",
                                             table="country")],
        )])
        merged = merge_preserving_decisions(new, existing)
        c = merged.claims[0]
        assert c.status == "approved"
        assert c.mdm_anchor is True
        assert c.reference_data.code_system == "ISO-3166-1"
        assert c.ownership_override.owner == "cdo"
        assert c.passthrough_reviewed is True
        # evidence still refreshed from the new run
        assert {e.type for e in c.evidence_sources} == {"affinity"}

