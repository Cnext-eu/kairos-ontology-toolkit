# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""dbt projection **render** phase (DD-102).

Assembles the final ``{file_path: content}`` artifact map from the committed
:class:`ShapedProject` (rendered strings + metadata) and :class:`MaterializationPlan`
(release metadata + project config), then runs the lightweight post-generation
validation.

By construction this phase is handed only strings / sets / dicts — **never** the RDF
graph or the SKOS mappings — so it structurally cannot reread RDF or reclassify
projection policy.  The special ``__unbound_eligible__`` / ``__coverage_data__``
sentinels are attached exactly where the monolithic entrypoint attached them, so the
orchestrator's downstream handling (release gate, coverage merge) is unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .context import MaterializationPlan, ShapedProject


def render_project(
    shaped: "ShapedProject", plan: "MaterializationPlan"
) -> dict:
    """Run the render phase — assemble + validate the final artifact map."""
    from ..medallion_dbt_projector import _validate_dbt_artifacts

    artifacts: dict = {}
    artifacts.update(shaped.source_artifacts)
    artifacts.update(shaped.silver_artifacts)

    if plan.unbound_eligible_names:
        artifacts["__unbound_eligible__"] = list(plan.unbound_eligible_names)

    artifacts.update(shaped.schema_artifacts)
    artifacts.update(shaped.gold_artifacts)
    artifacts.update(shaped.gold_schema_artifacts)
    artifacts.update(plan.project_config)

    if shaped.coverage_data:
        artifacts["__coverage_data__"] = shaped.coverage_data

    artifacts.update(shaped.macros)

    _validate_dbt_artifacts(artifacts, known_models=set(plan.known_models))

    return artifacts
