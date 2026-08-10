# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Stage 3 typed-plan integration tests for optional Gold and MDM consumers."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from rdflib import URIRef
from rdflib.namespace import RDFS

from kairos_ontology.core.compiler import build_compile_plan
from kairos_ontology.core.projector import (
    ProjectionRunError,
    get_target_spec,
    project_downstream_compile_plan,
    projection_targets_for_all,
    run_projections,
)
from kairos_ontology.core.projections.dbt.gold_specs import GoldContractError
from kairos_ontology.core.projections.medallion_gold_projector import (
    generate_gold_from_compile_plan,
)
from kairos_ontology.mdm.profile_projector import (
    MdmCompilePlanError,
    _typed_policy_graph,
    generate_mdm_profile_from_compile_plan,
)

_V5_HUB = Path(__file__).parent / "scenarios" / "v5-governed-hub"
_AUTHORITATIVE_SUFFIXES = (".ttl", ".yaml")
_RETIRED_PARTS = {
    ".kairos-state",
    "claims",
    "evidence",
    "governance",
    "mappings",
    "preparation",
    "readiness",
}


def _copy_hub(tmp_path: Path) -> Path:
    hub = tmp_path / "hub"
    shutil.copytree(_V5_HUB, hub)
    return hub


def _mdm_extension(path: Path, *, property_name: str = "customerName") -> Path:
    path.write_text(
        f"""
        @prefix party: <https://example.test/party#> .
        @prefix kairos-mdm: <https://kairos.cnext.eu/mdm#> .
        party:Customer
            kairos-mdm:mastered true ;
            kairos-mdm:mdmStyle "registry" .
        party:{property_name}
            kairos-mdm:matchAttribute true ;
            kairos-mdm:identifier true .
        """,
        encoding="utf-8",
    )
    return path


def test_governed_fixture_contains_only_current_authoring_authority():
    files = {path.relative_to(_V5_HUB) for path in _V5_HUB.rglob("*") if path.is_file()}

    assert files
    assert all(path.suffix in _AUTHORITATIVE_SUFFIXES or path.name == "README.md" for path in files)
    assert not any(_RETIRED_PARTS.intersection(path.parts) for path in files)
    assert not any("silver-ext" in path.name or "ddd-ext" in path.name for path in files)
    assert (_V5_HUB / "integration" / "bindings" / "customer.binding.yaml").is_file()
    assert (_V5_HUB / "model" / "extensions" / "party-gold-ext.ttl").is_file()
    assert (_V5_HUB / "model" / "extensions" / "party-mdm-ext.ttl").is_file()


def test_real_gold_policy_is_bound_into_canonical_compile_plan(tmp_path):
    hub = _copy_hub(tmp_path)

    plan = build_compile_plan(hub, "party")
    artifacts = generate_gold_from_compile_plan(plan)

    assert plan.normalized_contract.policy.gold.profile is not None
    assert artifacts
    assert any(item.name == "model/extensions/party-gold-ext.ttl" for item in plan.scope.inputs)


def test_gold_consumes_exact_shaped_registry_without_rebuilding(tmp_path, monkeypatch):
    plan = build_compile_plan(_copy_hub(tmp_path), "party")
    logical = object()
    physical = object()
    observed = {}

    def shape(policy, registry, silver_models, foreign_keys, **kwargs):
        observed["registry"] = registry
        observed["models"] = silver_models
        observed["domain"] = kwargs["ontology_name"]
        return logical

    def materialize(spec, **kwargs):
        assert spec is logical
        observed["adapter_version"] = kwargs["adapter_version"]
        return physical

    def render(spec, physical_plan, *, silver_parity):
        assert spec is logical
        assert physical_plan is physical
        observed["parity"] = silver_parity
        return {"party/gold.sql": "select 1\n"}

    monkeypatch.setattr(
        "kairos_ontology.core.projections.medallion_gold_projector.shape_gold_product",
        shape,
    )
    monkeypatch.setattr(
        "kairos_ontology.core.projections.medallion_gold_projector.materialize_gold_product",
        materialize,
    )
    monkeypatch.setattr(
        "kairos_ontology.core.projections.medallion_gold_projector.render_powerbi_artifacts",
        render,
    )

    first = generate_gold_from_compile_plan(plan)
    second = generate_gold_from_compile_plan(plan)

    assert first == second == {"party/gold.sql": "select 1\n"}
    assert observed["registry"] is plan.silver_registry
    assert observed["models"] is plan.shaped_project.silver_models
    assert observed["domain"] == "party"
    assert observed["parity"]["authority"] == "compile-plan"
    assert observed["parity"]["provenance_hash"] == plan.provenance_hash


def test_gold_rejects_blocked_compile_plan(tmp_path):
    hub = _copy_hub(tmp_path)
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace(
            "expression: customer_name", "expression: missing_name"
        ),
        encoding="utf-8",
    )
    plan = build_compile_plan(hub, "party")
    assert plan.blocked
    with pytest.raises(GoldContractError, match="blocked compiler plan"):
        generate_gold_from_compile_plan(plan)


def test_mdm_consumes_registry_and_is_byte_deterministic(tmp_path):
    hub = _copy_hub(tmp_path)
    plan = build_compile_plan(hub, "party")
    extension = hub / "model" / "extensions" / "party-mdm-ext.ttl"
    plan_with_registry_only = replace(
        plan,
        shaped_project=replace(plan.shaped_project, silver_models=()),
    )

    first = generate_mdm_profile_from_compile_plan(plan_with_registry_only, mdm_ext_path=extension)
    second = generate_mdm_profile_from_compile_plan(plan_with_registry_only, mdm_ext_path=extension)

    assert first == second
    payload = json.loads(first["party-mdm-profile.json"])
    assert payload["provenance"]["domain"] == "party"
    assert payload["provenance"]["generated_at"] == ""
    assert payload["mastered_concepts"][0]["name"] == "Customer"
    assert payload["mastered_concepts"][0]["match_attributes"][0]["name"] == "customerName"


def test_mdm_typed_policy_graph_preserves_subclass_edges(tmp_path):
    hub = _copy_hub(tmp_path)
    ontology = hub / "model" / "ontologies" / "party.ttl"
    ontology.write_text(
        ontology.read_text(encoding="utf-8")
        + "\nparty:PreferredCustomer a owl:Class ; rdfs:subClassOf party:Customer .\n",
        encoding="utf-8",
    )
    extension = hub / "model" / "extensions" / "party-mdm-ext.ttl"

    graph = _typed_policy_graph(build_compile_plan(hub, "party"), extension)

    assert (
        URIRef("https://example.test/party#PreferredCustomer"),
        RDFS.subClassOf,
        URIRef("https://example.test/party#Customer"),
    ) in graph


def test_mdm_rejects_blocked_or_unshaped_policy(tmp_path):
    blocked_hub = _copy_hub(tmp_path / "blocked")
    binding = blocked_hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace(
            "expression: customer_name", "expression: missing_name"
        ),
        encoding="utf-8",
    )
    extension = blocked_hub / "model" / "extensions" / "party-mdm-ext.ttl"
    blocked = build_compile_plan(blocked_hub, "party")
    with pytest.raises(MdmCompilePlanError, match="blocked compiler plan"):
        generate_mdm_profile_from_compile_plan(blocked, mdm_ext_path=extension)

    plan = build_compile_plan(_copy_hub(tmp_path / "valid"), "party")
    unknown = _mdm_extension(
        tmp_path / "unknown-mdm-ext.ttl",
        property_name="unknownAttribute",
    )
    with pytest.raises(MdmCompilePlanError, match="absent from shaped Silver"):
        generate_mdm_profile_from_compile_plan(plan, mdm_ext_path=unknown)


def test_registry_wires_mdm_plan_consumer_without_core_importing_mdm(tmp_path):
    hub = _copy_hub(tmp_path)
    plan = build_compile_plan(hub, "party")
    extension = hub / "model" / "extensions" / "party-mdm-ext.ttl"
    spec = get_target_spec("mdm-profile")

    assert spec is not None
    assert spec.include_in_all is False
    assert spec.external_dispatch is not None
    assert spec.external_dispatch.project_compile_plan is not None
    assert project_downstream_compile_plan(
        "mdm-profile",
        plan,
        ext_path=extension,
    ) == generate_mdm_profile_from_compile_plan(plan, mdm_ext_path=extension)


def test_registry_dispatches_gold_alias_to_typed_consumer(tmp_path, monkeypatch):
    plan = build_compile_plan(_copy_hub(tmp_path), "party")
    monkeypatch.setattr(
        "kairos_ontology.core.projections.medallion_gold_projector.generate_gold_from_compile_plan",
        lambda compile_plan: {"party/gold.sql": compile_plan.provenance_hash},
    )

    assert project_downstream_compile_plan("gold", plan) == {"party/gold.sql": plan.provenance_hash}


@pytest.mark.parametrize("target", ("powerbi", "gold", "mdm-profile"))
def test_legacy_project_rejects_compile_plan_consumers_before_graph_loading(
    tmp_path, monkeypatch, target
):
    monkeypatch.setattr(
        "kairos_ontology.core.ontology_loader.load_ontology",
        lambda *args, **kwargs: pytest.fail("legacy graph authority was invoked"),
    )

    with pytest.raises(ProjectionRunError, match="bypasses the immutable CompilePlan"):
        run_projections(
            ontologies_path=_copy_hub(tmp_path) / "model" / "ontologies",
            catalog_path=tmp_path / "missing.xml",
            output_path=tmp_path / "output",
            target=target,
        )


def test_project_all_excludes_compile_plan_only_consumers():
    assert "powerbi" not in projection_targets_for_all()
    assert "mdm-profile" not in projection_targets_for_all()
