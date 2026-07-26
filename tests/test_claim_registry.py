# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the Claim Registry schema v1 (``claim_registry``)."""

from __future__ import annotations

from dataclasses import fields

import pytest

from kairos_ontology.core.claim_registry import (
    CLAIM_REGISTRY_SCHEMA_VERSION,
    DOMAIN_HANDOFF_SCHEMA_VERSION,
    GENERATION_OUTCOME_SCHEMA_VERSION,
    HUMAN_CURATED_FIELDS,
    TRIAGE_TO_DISPOSITION,
    VALID_ANCHOR_STATES,
    Claim,
    ClaimRegistry,
    CoverageSystem,
    CoverageTable,
    Deviation,
    DomainHandoff,
    EvidenceSource,
    Freshness,
    GenerationOutcome,
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


class TestGenerationOutcome:
    """Alignment-reliability: the additive per-table generation-outcome record."""

    def test_default_schema_version(self):
        gen = GenerationOutcome(system="s", table="t", outcome="provider_failure")
        assert gen.schema_version == GENERATION_OUTCOME_SCHEMA_VERSION

    def test_to_from_dict_round_trip(self):
        gen = GenerationOutcome(
            system="crm", table="account", outcome="provider_failure",
            provider="github", model="gpt-5.4-mini", error="RuntimeError: boom",
        )
        again = GenerationOutcome.from_dict(gen.to_dict())
        assert again == gen

    def test_optional_fields_omitted_when_none(self):
        gen = GenerationOutcome(system="crm", table="account", outcome="fallback_only")
        d = gen.to_dict()
        assert "provider" not in d
        assert "model" not in d
        assert "error" not in d

    def test_registry_omits_empty_generation_outcomes(self):
        # Byte-identical happy path: a registry with no generation_outcomes never
        # emits the key at all.
        reg = _good_registry()
        assert "generation_outcomes" not in reg.to_dict()
        assert "generation_outcomes" not in dump_registry(reg)

    def test_registry_round_trips_generation_outcomes(self):
        reg = _good_registry()
        reg.generation_outcomes = [
            GenerationOutcome(system="crm", table="account", outcome="provider_failure",
                               error="boom"),
        ]
        again = ClaimRegistry.from_dict(reg.to_dict())
        assert again.generation_outcomes == reg.generation_outcomes
        assert again.to_dict() == reg.to_dict()



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

    def test_unknown_generation_outcome_warns_not_errors(self):
        # Alignment-reliability: an unrecognized outcome is additive/forward-
        # compat only — warning-level, never a structural-validity error.
        reg = _good_registry()
        reg.generation_outcomes = [
            GenerationOutcome(system="crm", table="account", outcome="bogus"),
        ]
        issues = validate_registry(reg)
        assert any(
            i.level == "warning" and "unknown outcome" in i.message for i in issues
        )
        assert validation_errors(issues) == []

    def test_known_generation_outcomes_produce_no_issues(self):
        reg = _good_registry()
        reg.generation_outcomes = [
            GenerationOutcome(system="crm", table="account", outcome="provider_failure",
                               error="boom"),
        ]
        assert validate_registry(reg) == []


class TestUriAnchorContract:
    """uri-anchor-contract: confirmed/unresolved anchor states + URI diagnostics."""

    def test_confirmed_and_unresolved_are_valid_anchor_states(self):
        assert "confirmed" in VALID_ANCHOR_STATES
        assert "unresolved" in VALID_ANCHOR_STATES

    def test_confirmed_anchor_state_passes_validation(self):
        reg = _good_registry()
        reg.coverage[0].tables[0].anchor_state = "confirmed"
        assert validation_errors(validate_registry(reg)) == []

    def test_unresolved_anchor_state_passes_validation(self):
        reg = _good_registry()
        reg.coverage[0].tables[0].anchor_state = "unresolved"
        assert validation_errors(validate_registry(reg)) == []

    def test_coverage_table_likely_entity_uri_round_trips(self):
        table = CoverageTable(
            table="account", total_columns=1, mapped_columns=1, custom_columns=0,
            anchor_state="confirmed", ref_class="TradeParty",
            likely_entity_uri="https://ex.org/acc#TradeParty",
        )
        again = CoverageTable.from_dict(table.to_dict())
        assert again.likely_entity_uri == "https://ex.org/acc#TradeParty"

    def test_coverage_table_likely_entity_uri_omitted_when_empty(self):
        table = CoverageTable(
            table="account", total_columns=1, mapped_columns=1, custom_columns=0,
        )
        assert "likely_entity_uri" not in table.to_dict()

    def test_imported_claim_without_class_uri_warns_not_errors(self):
        reg = ClaimRegistry(domain="d", claims=[
            Claim(id="d-1", type="class", status="proposed", disposition="claim",
                  origin="imported", class_uri=None)
        ])
        issues = validate_registry(reg)
        assert any(
            i.level == "warning" and "no resolvable class_uri" in i.message
            for i in issues
        )
        assert validation_errors(issues) == []

    def test_imported_specialize_without_property_uri_warns(self):
        reg = ClaimRegistry(domain="d", claims=[
            Claim(id="d-1", type="property", status="proposed", disposition="specialize",
                  origin="imported", property_uri=None)
        ])
        issues = validate_registry(reg)
        assert any(
            i.level == "warning" and "no resolvable property_uri" in i.message
            for i in issues
        )
        assert validation_errors(issues) == []

    def test_authored_claim_without_uri_does_not_warn(self):
        # The diagnostic is scoped to *imported* claims only — an authored
        # claim legitimately has no source-derived URI to resolve.
        reg = ClaimRegistry(domain="d", claims=[
            Claim(id="d-1", type="class", status="proposed", disposition="claim",
                  origin="authored", class_uri=None)
        ])
        assert validate_registry(reg) == []

    def test_passthrough_disposition_without_uri_does_not_warn(self):
        reg = ClaimRegistry(domain="d", claims=[
            Claim(id="d-1", type="property", status="proposed", disposition="passthrough",
                  origin="imported", property_uri=None)
        ])
        assert validate_registry(reg) == []

    def test_imported_claim_with_resolved_uri_does_not_warn(self):
        reg = ClaimRegistry(domain="d", claims=[
            Claim(id="d-1", type="class", status="proposed", disposition="claim",
                  origin="imported", class_uri="https://ex.org/acc#TradeParty")
        ])
        assert validate_registry(reg) == []

    def test_good_registry_from_existing_fixture_has_no_new_warnings(self):
        # Backward compatibility: a pre-feature registry with populated URIs
        # (the shared _good_registry fixture) must not pick up any new
        # diagnostics from this feature.
        issues = validate_registry(_good_registry())
        assert not any("uri-anchor-contract" in i.message for i in issues)


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

    def test_decided_claim_confidence_refreshed(self):
        existing = self._existing(proposed_confidence=0.4)
        new = self._new_proposed()
        new.claims[0].proposed_confidence = 0.9

        merged = merge_preserving_decisions(new, existing)

        assert merged.claims[0].proposed_confidence == 0.9

    def test_decided_claim_type_is_governed(self):
        new = self._new_proposed()
        new.claims[0].type = "property"
        new.claims[0].property_uri = "https://ex.org/generated#tradeParty"

        merged = merge_preserving_decisions(new, self._existing())

        assert merged.claims[0].type == "class"
        assert merged.claims[0].property_uri is None

    def test_empty_new_evidence_keeps_prior_evidence(self):
        new = self._new_proposed()
        new.claims[0].evidence_sources = []

        merged = merge_preserving_decisions(new, self._existing())

        assert [(e.system, e.table) for e in merged.claims[0].evidence_sources] == [
            ("crm", "account")
        ]

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
        new.freshness = Freshness(
            affinity_sha256="new-affinity", alignment_params_sha256="new-params"
        )
        new.coverage = [CoverageSystem(system="erp", tables=[CoverageTable(
            table="customer", anchor_state="matched")])]
        merged = merge_preserving_decisions(new, self._existing())
        assert merged.algorithm_version == 4
        assert merged.generated_at == "2026-06-15T20:00:00Z"
        assert merged.freshness == new.freshness
        assert merged.coverage[0].system == "erp"

    def test_generation_outcomes_always_from_new(self):
        # Alignment-reliability: generation_outcomes is per-run reliability
        # metadata (like coverage/freshness), never a curated decision — it must
        # always come from the new run, even when the existing registry had its
        # own (now stale) outcomes.
        new = self._new_proposed()
        new.generation_outcomes = [
            GenerationOutcome(system="erp", table="customer", outcome="provider_failure",
                               error="boom"),
        ]
        existing = self._existing()
        existing.generation_outcomes = [
            GenerationOutcome(system="crm", table="account", outcome="fallback_only"),
        ]
        merged = merge_preserving_decisions(new, existing)
        assert merged.generation_outcomes == new.generation_outcomes

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

    def test_dump_keeps_sorted_claims_and_claim_key_order(self):
        new = self._new_proposed()
        new.claims.insert(
            0,
            Claim(
                id="party-a",
                type="property",
                property_uri="https://ex.org/party#a",
                evidence_sources=[
                    EvidenceSource(
                        type="source_column",
                        system="erp",
                        table="customer",
                        column="a",
                    )
                ],
                proposed_confidence=0.8,
            ),
        )

        text = dump_registry(merge_preserving_decisions(new, self._existing()))

        assert text.index("id: party-a") < text.index("id: party-trade-party")
        assert text.index("type: property") < text.index("property_uri:")
        assert text.index("property_uri:") < text.index("origin:")
        assert text.index("evidence_sources:") < text.index("proposed_confidence:")

    def test_different_domains_are_rejected(self):
        existing = self._existing()
        existing.domain = "invoice"

        with pytest.raises(ValueError, match="different domains"):
            merge_preserving_decisions(self._new_proposed(), existing)


def test_claim_merge_policy_covers_every_claim_field():
    """Adding a Claim field requires an explicit curated-or-refreshed policy choice."""
    identity_fields = {"id"}
    refreshed_fields = {"evidence_sources", "proposed_confidence"}
    claim_fields = {claim_field.name for claim_field in fields(Claim)}

    assert claim_fields == identity_fields | refreshed_fields | set(HUMAN_CURATED_FIELDS)


def test_every_curated_claim_field_survives_regeneration():
    previous = Claim(
        id="party-country",
        type="reference_data",
        status="approved",
        disposition="specialize",
        origin="authored",
        class_uri="https://ex.org/common#Country",
        property_uri="https://ex.org/common#countryCode",
        owner="data-governance",
        evidence_sources=[EvidenceSource(type="source_table", system="mdm", table="country")],
        silver_impact=SilverImpact(table="dim_country", column="code", change_type="breaking"),
        reference_data=ReferenceData(
            authority_system="iso",
            code_system="ISO-3166-1",
            key="alpha2",
            scd_type=1,
        ),
        mdm_anchor=True,
        deviation=Deviation(reason="approved exception", owner="architecture"),
        ownership_override=OwnershipOverride(owner="cdo", rationale="conformed dimension"),
        passthrough_reviewed=True,
        rationale="reviewed decision",
        proposed_confidence=0.2,
        superseded_by="party-country-v2",
    )
    candidate = Claim(
        id=previous.id,
        type="property",
        status="proposed",
        disposition="claim",
        origin="imported",
        property_uri="https://ex.org/generated#country",
        owner="generated-owner",
        evidence_sources=[
            EvidenceSource(
                type="source_column",
                system="erp",
                table="customer",
                column="country",
            )
        ],
        silver_impact=SilverImpact(table="generated_country"),
        rationale="generated rationale",
        proposed_confidence=0.95,
    )

    merged = merge_preserving_decisions(
        ClaimRegistry(domain="party", claims=[candidate]),
        ClaimRegistry(domain="party", claims=[previous]),
    ).claims[0]

    for field_name in HUMAN_CURATED_FIELDS:
        assert getattr(merged, field_name) == getattr(previous, field_name)
    assert merged.evidence_sources == candidate.evidence_sources
    assert merged.proposed_confidence == candidate.proposed_confidence


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


class TestDomainHandoff:
    """proposal-quality — cross-domain evidence kept out of in-domain claims."""

    def test_round_trip(self):
        handoff = DomainHandoff(
            ref_class="Party",
            ref_property="legalName",
            owning_domains=["party"],
            ref_module="party-core",
            ref_module_uri="https://ex.org/ont/party#",
            evidence_sources=[
                EvidenceSource(type="source_column", system="tms", table="booking",
                                column="shipper_name"),
            ],
        )
        again = DomainHandoff.from_dict(handoff.to_dict())
        assert again == handoff
        assert again.schema_version == DOMAIN_HANDOFF_SCHEMA_VERSION

    def test_to_dict_omits_empty_optional_fields(self):
        handoff = DomainHandoff(ref_class="Party", ref_property="legalName")
        out = handoff.to_dict()
        assert "ref_module" not in out
        assert "ref_module_uri" not in out
        assert "evidence_sources" not in out
        assert out["owning_domains"] == []

    def test_registry_omits_empty_domain_handoffs(self):
        reg = ClaimRegistry(domain="booking")
        assert "domain_handoffs" not in reg.to_dict()

    def test_registry_round_trips_domain_handoffs(self):
        reg = ClaimRegistry(domain="booking", domain_handoffs=[
            DomainHandoff(ref_class="Party", ref_property="legalName",
                          owning_domains=["party"]),
        ])
        restored = ClaimRegistry.from_dict(reg.to_dict())
        assert restored.domain_handoffs == reg.domain_handoffs

    def test_validate_warns_when_handoff_names_own_domain(self):
        reg = ClaimRegistry(domain="booking", domain_handoffs=[
            DomainHandoff(ref_class="Party", ref_property="legalName",
                          owning_domains=["booking"]),
        ])
        issues = validate_registry(reg)
        assert any(
            i.level == "warning" and "domain_handoffs" in i.message for i in issues
        )
        assert validation_errors(issues) == []

    def test_merge_always_takes_new_domain_handoffs(self):
        existing = ClaimRegistry(domain="booking", domain_handoffs=[
            DomainHandoff(ref_class="Stale", ref_property="stale", owning_domains=["x"]),
        ])
        new = ClaimRegistry(domain="booking", domain_handoffs=[
            DomainHandoff(ref_class="Party", ref_property="legalName",
                          owning_domains=["party"]),
        ])
        merged = merge_preserving_decisions(new, existing)
        assert merged.domain_handoffs == new.domain_handoffs


class TestRelationshipCandidateClusterMerge:
    """proposal-quality — stable cluster_id survives membership refresh."""

    def test_membership_refreshes_curated_field_survives(self):
        existing = ClaimRegistry(domain="booking", relationship_candidates=[
            {"type": "address_relationship_candidate", "source_table": "companies",
             "role": None, "suggested_relationship": "hasAddress",
             "target_concept": "Address", "source_columns": ["street", "city"],
             "address_parts": ["city", "street"], "cardinality": "1:n",
             "cluster_id": "abc123", "requires_human_confirmation": True,
             "rationale": "old", "curator_note": "confirmed by Jane"},
        ])
        new = ClaimRegistry(domain="booking", relationship_candidates=[
            {"type": "address_relationship_candidate", "source_table": "companies",
             "role": None, "suggested_relationship": "hasAddress",
             "target_concept": "Address",
             "source_columns": ["street", "city", "postal_code"],
             "address_parts": ["city", "postal", "street"], "cardinality": "1:n",
             "cluster_id": "abc123", "requires_human_confirmation": True,
             "rationale": "new"},
        ])
        merged = merge_preserving_decisions(new, existing)
        cand = merged.relationship_candidates[0]
        # detector-owned fields refresh (membership change is reported)
        assert cand["source_columns"] == ["street", "city", "postal_code"]
        assert cand["rationale"] == "new"
        # human-curated field (not detector-owned) survives the refresh
        assert cand["curator_note"] == "confirmed by Jane"

    def test_no_cluster_id_passes_through_unmerged(self):
        existing = ClaimRegistry(domain="booking", relationship_candidates=[])
        new = ClaimRegistry(domain="booking", relationship_candidates=[
            {"type": "address_relationship_candidate", "source_table": "t",
             "source_columns": ["a"]},
        ])
        merged = merge_preserving_decisions(new, existing)
        assert merged.relationship_candidates == new.relationship_candidates
