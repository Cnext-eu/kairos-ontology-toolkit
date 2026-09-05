# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Profile-driven Gold data-product projection (DD-112/DD-113)."""

from __future__ import annotations

from ..adapters import FABRIC_WAREHOUSE

from pathlib import Path
from collections.abc import Sequence
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
from .dbt.gold_connection import (
    GoldProductConfig,
    load_gold_databricks_connection,
    load_gold_direct_lake_connection,
)
from .dbt.gold_render import render_powerbi_artifacts
from .dbt.gold_materialize import materialize_gold_product
from .dbt.gold_shape import GoldDomainInput, shape_gold_product, shape_gold_products
from .dbt.gold_specs import GoldContractError
from .dbt.gold_specs import GoldProductLogicalSpec, GoldProductPhysicalSpec

if TYPE_CHECKING:
    from ..compiler.plan import CompilePlan


def _domain_input(compile_plan: "CompilePlan") -> GoldDomainInput:
    """Validate one compile plan and reduce it to the inputs Gold shaping needs."""
    if compile_plan.blocked:
        raise GoldContractError(
            "gold.compile-plan-blocked",
            "Gold cannot consume a blocked compiler plan",
            rule_id="DD-133-downstream",
        )
    shaped = compile_plan.shaped_project
    contract = compile_plan.normalized_contract
    registry = compile_plan.silver_registry
    if (
        shaped is None
        or contract is None
        or compile_plan.materialization_plan is None
        or registry is None
    ):
        raise GoldContractError(
            "gold.compile-plan-incomplete",
            "Gold requires a shaped compiler plan with a Silver registry",
            rule_id="DD-133-downstream",
        )
    return GoldDomainInput(
        policy=contract.policy,
        registry=registry,
        silver_models=shaped.silver_models,
        foreign_keys=contract.fk_classification,
        ontology_name=compile_plan.resolution.ontology_name,
        ontology_version=compile_plan.resolution.ontology_version,
    )


def plan_gold_from_compile_plan(
    compile_plan: "CompilePlan",
) -> tuple[GoldProductLogicalSpec, GoldProductPhysicalSpec]:
    """Build optional Gold logical/physical plans from canonical Stage 3 Silver."""
    member = _domain_input(compile_plan)
    materialized = compile_plan.materialization_plan
    logical = shape_gold_product(
        member.policy,
        member.registry,
        member.silver_models,
        member.foreign_keys,
        ontology_name=member.ontology_name,
        ontology_version=member.ontology_version,
        required=True,
    )
    assert logical is not None
    physical = materialize_gold_product(
        logical,
        adapter_version=materialized.adapter.version,
        capability_results=materialized.adapter.capability_results,
    )
    return logical, physical


def plan_gold_from_compile_plans(
    compile_plans: "Sequence[CompilePlan]",
    product: GoldProductConfig,
) -> tuple[GoldProductLogicalSpec, GoldProductPhysicalSpec]:
    """Build one Gold product from every participating domain's compile plan (#744).

    Silver compilation stays per domain -- each plan is built exactly as before -- and only
    Gold shaping spans them, which is what lets a fact in one domain join a conformed
    dimension in another. The plans arrive in the product's declared domain order; the
    first is the primary, and supplies the adapter and schema defaults.
    """
    if not compile_plans:
        raise GoldContractError(
            "gold.product-without-domains",
            f"Gold product {product.name!r} has no participating domain",
            rule_id="DD-222-gold-product-scope",
        )
    members = tuple(_domain_input(plan) for plan in compile_plans)
    logical = shape_gold_products(members, product_name=product.name, required=True)
    assert logical is not None
    materialized = compile_plans[0].materialization_plan
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
    return _render(logical, physical, (compile_plan,))


def generate_gold_from_compile_plans(
    compile_plans: "Sequence[CompilePlan]",
    product: GoldProductConfig,
) -> dict[str, str]:
    """Render one Gold product's artifacts from every participating domain (#744)."""
    logical, _ = plan_gold_from_compile_plans(compile_plans, product)
    return render_gold_product(logical, compile_plans, product)


def render_gold_product(
    logical: GoldProductLogicalSpec,
    compile_plans: "Sequence[CompilePlan]",
    product: GoldProductConfig,
) -> dict[str, str]:
    """Render artifacts from an already-shaped product.

    Separate from :func:`generate_gold_from_compile_plans` so a caller that needs the
    shaped spec as well -- `emit-gold`, which reports insight coverage against it -- does
    not shape the same product twice.
    """
    materialized = compile_plans[0].materialization_plan
    physical = materialize_gold_product(
        logical,
        adapter_version=materialized.adapter.version,
        capability_results=materialized.adapter.capability_results,
    )
    artifacts = _render(logical, physical, compile_plans, display_name=product.display_name)
    artifacts.update(_insight_brief(logical, product, Path(compile_plans[0].scope.hub_root)))
    return artifacts


def _insight_brief(
    logical: GoldProductLogicalSpec,
    product: GoldProductConfig,
    hub_root: Path,
) -> dict[str, str]:
    """Render the persona/KPI brief for this product, when any insight is authored.

    Emitted only when the hub authors insights for this product: a file of headings with
    nothing under them is worse than no file, and every existing hub authors none.
    """
    from ..insights import check_coverage, load_insights, render_insight_brief

    insight_set = load_insights(hub_root)
    insights = insight_set.for_product(product.name)
    if not insights:
        return {}
    coverage = check_coverage(insights, logical)
    return {
        f"{product.name}/{product.name}-insight-brief.md": render_insight_brief(
            product.name, insight_set, coverage
        )
    }


def insight_coverage_for(
    logical: GoldProductLogicalSpec,
    product: GoldProductConfig,
    hub_root: Path,
):
    """Return coverage for this product's *confirmed* insights, for CLI reporting.

    Only confirmed ones: a `draft` insight is a proposal nobody has agreed to, usually
    written by an agent reading the legacy report usage, and warning about gaps in a guess
    would train an operator to ignore the warning.
    """
    from ..insights import check_coverage, load_insights

    insight_set = load_insights(hub_root)
    confirmed = tuple(item for item in insight_set.for_product(product.name) if item.confirmed)
    return check_coverage(confirmed, logical)


def _render(
    logical: GoldProductLogicalSpec,
    physical: GoldProductPhysicalSpec,
    compile_plans: "Sequence[CompilePlan]",
    *,
    display_name: str = "",
) -> dict[str, str]:
    parity = {
        "status": "pass",
        "authority": "compile-plan",
        # One hash per participating domain, in the product's declared order: the product
        # has no provenance of its own, and collapsing several into one would invent an
        # identity no compile ever produced.
        "provenance_hash": (
            compile_plans[0].provenance_hash
            if len(compile_plans) == 1
            else {plan.resolution.ontology_name: plan.provenance_hash for plan in compile_plans}
        ),
        "models": sorted(
            {name for plan in compile_plans for name, _ in plan.silver_registry.names}
        ),
    }
    hub_root = Path(compile_plans[0].scope.hub_root)
    return render_powerbi_artifacts(
        logical,
        physical,
        silver_parity=parity,
        # Only for a product that authored one; otherwise the renderer names the Fabric
        # item after the product exactly as it always has.
        **({"display_name": display_name} if display_name else {}),
        # The compiler already resolved and hashed this hub's kairos.yaml, which is
        # where the per-environment Databricks connection is authored (issue #283),
        # and where the per-environment Direct Lake workspace/lakehouse IDs are
        # authored the same way (#619 Bugs 4/6).
        connection=load_gold_databricks_connection(hub_root),
        direct_lake_connection=load_gold_direct_lake_connection(hub_root),
    )


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
    target_platform: str = FABRIC_WAREHOUSE,
    contract_registry: Mapping[str, object] | None = None,
    hub_root: Path | None = None,
) -> dict[str, str]:
    """Generate one registered Gold product from typed Silver and Gold plans.

    ``hub_root`` locates the ``kairos.yaml`` that authors the per-environment
    Databricks connection required by a ``directQuery`` product (issue #283), and the
    per-environment Direct Lake workspace/lakehouse IDs required by a Direct Lake
    product (#619 Bugs 4/6).
    """
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
        connection=load_gold_databricks_connection(hub_root),
        direct_lake_connection=load_gold_direct_lake_connection(hub_root),
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
