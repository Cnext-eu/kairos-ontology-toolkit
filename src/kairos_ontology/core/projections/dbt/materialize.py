# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""dbt projection **materialize** phase (DD-102).

Owns the orchestration-level materialization / release decisions:

* the release-gate set — every approved, materialization-eligible claim with no
  bronze mapping (aspirational **or** unbound-eligible), surfaced as
  ``unbound_eligible_names`` → the ``__unbound_eligible__`` sentinel so the
  orchestrator can enforce ``project --strict`` (DD-096 / DEC-1); and
* the per-project dbt configuration (``dbt_project.yml`` / ``packages.yml`` /
  ``README.md``) with its gold-domain wiring.

Per-model view/table/incremental/SCD selection is decided inside the retained Silver
helper (``_gen_silver_models`` — documented retained internal code, DD-102); this
phase records the project-level materialization/release facts the render phase emits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .context import MaterializationPlan

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .context import BoundSources, DbtInputs, ProjectionContract, ShapedProject


def plan_materialization(
    inputs: "DbtInputs",
    bound: "BoundSources",
    contract: "ProjectionContract",
    shaped: "ShapedProject",
) -> MaterializationPlan:
    """Run the materialize phase — release metadata + project configuration."""
    from ..medallion_dbt_projector import _gen_project_config

    # Release gate (DD-096 / DEC-1): every approved, materialization-eligible claim
    # with no bronze mapping — whether emitted as a stub or skipped — is an unbound
    # target. Derived from the canonical entity metadata (release-blocking ==
    # aspirational) regardless of whether a stub was emitted.
    unbound_eligible_names = tuple(sorted(
        m["class_name"]
        for m in shaped.silver_entity_meta
        if m.get("aspirational") or m.get("unbound_eligible")
    ))

    # Per-domain project config (the orchestrator generates the definitive,
    # all-domains version afterwards; this remains the per-domain fallback).
    project_config: dict[str, str] = {}
    if bound.has_sources:
        gold_domains = [{"name": inputs.onto_name}] if shaped.has_gold else []
        project_config = _gen_project_config(
            bound.systems,
            [inputs.onto_name],
            inputs.env,
            f"{inputs.onto_name}_project",
            gold_domains=gold_domains,
            platform=inputs.target_platform,
        )

    return MaterializationPlan(
        unbound_eligible_names=unbound_eligible_names,
        project_config=project_config,
        known_models=frozenset(bound.contracts),
    )
