# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario coverage for the Core Concepts Conformance artifact (DD-090).

The acme-hub ships a sample ``integration/discovery/core-concepts-conformance.yaml``
representing what ``kairos-design-discovery`` Phase 2.5 persists. These tests assert
the artifact is well-formed and that ``kairos-design-domain`` can consume it the way
the skill prescribes: read the ref-model modules to pre-seed imports, read renames /
deviations / not-applicable exclusions, and surface the coverage scorecard.
"""


from kairos_ontology.core.conformance_artifact import (
    ARTIFACT_RELPATH,
    read_artifact,
    validate_artifact,
)

from .conftest import HUB_ROOT

# Shared outcome enum (mirrors blueprints/archetypes/_schema/outcome-codes.yaml).
OUTCOME_CODES = [
    "conforms",
    "conforms-with-rename",
    "partial",
    "deviates",
    "not-applicable",
]

ARTIFACT_PATH = HUB_ROOT / ARTIFACT_RELPATH


def test_scenario_conformance_artifact_present_and_valid():
    """The acme-hub sample artifact loads and passes contract validation."""
    artifact = read_artifact(ARTIFACT_PATH)
    errors = validate_artifact(artifact, OUTCOME_CODES)
    assert errors == [], errors


def test_design_domain_can_preseed_imports_from_modules():
    """design-domain reads ref_model_modules to pre-seed owl:imports."""
    artifact = read_artifact(ARTIFACT_PATH)
    modules = artifact["ref_model_modules"]
    iris = {m["iri"] for m in modules}
    assert "https://kairos.cnext.eu/ref/party#" in iris
    assert "https://kairos.cnext.eu/ref/invoice#" in iris
    # Tiers are preserved so design-domain can prioritise required modules.
    assert all(m["tier"] in {"required", "recommended", "optional"} for m in modules)


def test_design_domain_can_read_renames_and_exclusions():
    """Renames pre-fill naming alignment; not-applicable surfaces as exclusions."""
    artifact = read_artifact(ARTIFACT_PATH)
    by_outcome = {}
    for c in artifact["core_concepts"]:
        by_outcome.setdefault(c["outcome"], []).append(c)

    # conforms-with-rename carries the business alt-name for Checkpoint 1.
    renames = by_outcome["conforms-with-rename"]
    assert any(c.get("rename_to") == "Client" for c in renames)

    # deviates carries a captured reason for the modeling rationale.
    assert all(c.get("deviation_reason") for c in by_outcome["deviates"])

    # not-applicable concepts are excludable.
    assert by_outcome["not-applicable"]


def test_scenario_scorecard_matches_outcomes():
    """The persisted scorecard total matches the number of core concepts."""
    artifact = read_artifact(ARTIFACT_PATH)
    assert artifact["scorecard"]["total"] == len(artifact["core_concepts"])
