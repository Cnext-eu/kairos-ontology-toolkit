# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Architecture tests for the v5-only Silver compiler boundary."""

from __future__ import annotations

import ast
from pathlib import Path

import kairos_ontology
from kairos_ontology.core import projector


def test_registry_and_projector_have_no_legacy_dbt_dispatch():
    assert projector.RETIRED_COMPILER_TARGETS == ("dbt", "silver")
    assert "dbt" not in projector.TARGET_REGISTRY
    assert "silver" not in projector.TARGET_REGISTRY
    assert "dbt" not in projector.projection_targets_for_all()
    assert "silver" not in projector.projection_targets_for_all()

    source = Path(projector.__file__).read_text(encoding="utf-8")
    imports = {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "generate_dbt_artifacts" not in imports
    assert "plan_dbt_projection" not in imports


def test_public_service_boundary_exposes_compiler_plan_apis():
    assert kairos_ontology.build_compile_plan is not None
    assert kairos_ontology.compile_domain is not None
    assert kairos_ontology.compile_plan_result is not None
    assert kairos_ontology.render_compile_plan is not None
