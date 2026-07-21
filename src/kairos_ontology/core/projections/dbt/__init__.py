# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic five-phase dbt projection pipeline (DD-102).

The dbt projector is decomposed into explicit, ordered phases that exchange typed,
immutable intermediate models (see :mod:`.context`):

``bind → normalize → shape → materialize → render``

The public entrypoint ``generate_dbt_artifacts`` in
:mod:`kairos_ontology.core.projections.medallion_dbt_projector` orchestrates these
phases; the leaf shaping/rendering helpers remain in that module and are invoked by
the phase functions (documented retained internal code — DD-102).
"""

from __future__ import annotations

from .bind import bind_sources
from .context import (
    BoundSources,
    DbtInputs,
    MaterializationPlan,
    ProjectionContract,
    ShapedProject,
)
from .materialize import plan_materialization
from .normalize import normalize_contract
from .render import render_project
from .shape import shape_project

__all__ = [
    "BoundSources",
    "DbtInputs",
    "MaterializationPlan",
    "ProjectionContract",
    "ShapedProject",
    "bind_sources",
    "normalize_contract",
    "plan_materialization",
    "render_project",
    "shape_project",
]
