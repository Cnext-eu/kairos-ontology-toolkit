# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Profile-driven Gold data-product projection (DD-112/DD-113)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from rdflib import Graph

from .dbt import (
    DbtInputs,
    bind_sources,
    collect_materialization,
    normalize_contract,
    plan_materialization,
    render_project,
    shape_project,
)
from .dbt.gold_render import render_powerbi_artifacts
from .dbt.gold_materialize import materialize_gold_product
from .dbt.gold_shape import shape_gold_product
from .dbt.gold_specs import GoldContractError
from .dbt.gold_specs import GoldProductLogicalSpec, GoldProductPhysicalSpec

if TYPE_CHECKING:
    from ..compiler.plan import CompilePlan


def plan_gold_from_compile_plan(
    compile_plan: "CompilePlan",
) -> tuple[GoldProductLogicalSpec, GoldProductPhysicalSpec]:
    """Build optional Gold logical/physical plans from canonical Stage 3 Silver."""
    if compile_plan.blocked:
        raise GoldContractError(
            "gold.compile-plan-blocked",
            "Gold cannot consume a blocked compiler plan",
            rule_id="DD-133-downstream",
        )
    shaped = compile_plan.shaped_project
    contract = compile_plan.normalized_contract
    materialized = compile_plan.materialization_plan
    registry = compile_plan.silver_registry
    if shaped is None or contract is None or materialized is None or registry is None:
        raise GoldContractError(
            "gold.compile-plan-incomplete",
            "Gold requires a shaped compiler plan with a Silver registry",
            rule_id="DD-133-downstream",
        )

    logical = shape_gold_product(
        contract.policy,
        registry,
        shaped.silver_models,
        contract.fk_classification,
        ontology_name=compile_plan.resolution.ontology_name,
        ontology_version=compile_plan.resolution.ontology_version,
        required=True,
    )
    assert logical is not None
    physical = materialize_gold_product(
        logical,
        adapter_version=materialized.adapter.version,
        capability_results=materialized.adapter.capability_results,
    )
    return logical, physical


def generate_gold_from_compile_plan(
    compile_plan: "CompilePlan",
) -> dict[str, str]:
    """Render deterministic optional Gold artifacts without rebuilding Silver."""
    logical, physical = plan_gold_from_compile_plan(compile_plan)
    parity = {
        "status": "pass",
        "authority": "compile-plan",
        "provenance_hash": compile_plan.provenance_hash,
        "models": [name for name, _ in compile_plan.silver_registry.names],
    }
    return render_powerbi_artifacts(logical, physical, silver_parity=parity)


def _require_silver_authority(bound, contract, shaped) -> None:
    missing: list[str] = []
    if not bound.has_sources:
        missing.append("imported source vocabulary")
    if not contract.mapping_contract.tables or not contract.mapping_contract.columns:
        missing.append("validated table/column mappings")
    final_models = tuple(
        model for model in shaped.silver_models if model.kind.value in {"entity", "union"}
    )
    if not final_models:
        missing.append("bound generated Silver models")
    if missing:
        raise GoldContractError(
            "gold.silver-authority-incomplete",
            (
                "Gold consumes the actual Silver registry and cannot infer an "
                "ontology-only product. Missing: " + "; ".join(missing)
            ),
            rule_id="DD-112-silver-binding",
        )


def generate_gold_artifacts(
    classes: list[dict],
    graph: Graph,
    template_dir: Path,
    namespace: str,
    *,
    shapes_dir: Path | None = None,
    ontology_name: str = "domain",
    ontology_metadata: dict | None = None,
    sources_dir: Path | None = None,
    mappings_dir: Path | None = None,
    gold_ext_path: Path | None = None,
    silver_ext_path: Path | None = None,
    ref_model_defaults: list | None = None,
    peer_ext_paths: list | None = None,
    peer_ontology_paths: list | None = None,
    target_platform: str = "fabric",
    contract_registry: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """Generate one registered Gold product from typed Silver and Gold plans."""
    shaped, plan = plan_gold_projection(
        classes=classes,
        graph=graph,
        template_dir=template_dir,
        namespace=namespace,
        shapes_dir=shapes_dir,
        ontology_name=ontology_name,
        ontology_metadata=ontology_metadata,
        sources_dir=sources_dir,
        mappings_dir=mappings_dir,
        gold_ext_path=gold_ext_path,
        silver_ext_path=silver_ext_path,
        ref_model_defaults=ref_model_defaults,
        peer_ext_paths=peer_ext_paths,
        peer_ontology_paths=peer_ontology_paths,
        target_platform=target_platform,
        contract_registry=contract_registry,
    )
    rendered = render_project(shaped, plan)
    release_data = rendered.pop("__release_data__")
    rendered.pop("__coverage_data__", None)
    parity = release_data.get("parity_status", {})
    if parity.get("status") != "pass":
        raise GoldContractError(
            "gold.silver-parity-blocking",
            "Gold projection requires passing Silver registry/artifact parity",
            rule_id="DD-110-parity",
        )
    if shaped.gold_product is None or plan.gold is None:
        raise GoldContractError(
            "gold.plan-missing",
            "registered Gold profile did not produce a typed physical plan",
            rule_id="DD-112-profile",
        )
    artifacts = render_powerbi_artifacts(
        shaped.gold_product,
        plan.gold,
        silver_parity=parity,
    )
    artifacts["__release_data__"] = release_data
    return artifacts


def plan_gold_projection(
    classes: list[dict],
    graph: Graph,
    template_dir: Path,
    namespace: str,
    **kwargs,
):
    """Run the exact Gold bind-to-materialization path without rendering."""

    from .dbt import ExecutionMode

    diagnostic_mode = kwargs.pop("diagnostic_mode", ExecutionMode.FAIL_FAST)
    inputs = DbtInputs.from_call(
        classes=classes,
        graph=graph,
        template_dir=template_dir,
        namespace=namespace,
        **kwargs,
    )
    bound = bind_sources(inputs)
    contract = normalize_contract(bound, mode=diagnostic_mode)
    if contract.policy.gold.profile is None:
        raise GoldContractError(
            "gold.profile-missing",
            "Gold projection requires goldProductProfile",
            rule_id="DD-112-profile",
        )
    shaped = shape_project(contract)
    _require_silver_authority(bound, contract, shaped)
    plan = (
        collect_materialization(contract, shaped)
        if diagnostic_mode is ExecutionMode.COLLECT
        else plan_materialization(contract, shaped)
    )
    return shaped, plan


def generate_master_gold_erd(
    gold_output_path: Path,
    hub_name: str = "master",
) -> str | None:
    """Merge deterministic per-domain Gold ERDs after successful projection."""
    if not gold_output_path.exists():
        return None
    sections: list[tuple[str, list[str]]] = []
    for path in sorted(gold_output_path.rglob("*-gold-erd.mmd")):
        if path.name == "master-gold-erd.mmd":
            continue
        lines = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() != "erDiagram"
        ]
        sections.append((path.parent.name, lines))
    if not sections:
        return None
    result = ["erDiagram", f"    %% Gold data products: {hub_name}"]
    for domain, lines in sections:
        result.append(f"    %% Domain: {domain}")
        result.extend(lines)
    return "\n".join(result) + "\n"
