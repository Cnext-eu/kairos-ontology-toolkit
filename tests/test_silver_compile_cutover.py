# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Regression tests for the v5-only Silver compiler cutover."""

from __future__ import annotations

import ast
from pathlib import Path

from click.testing import CliRunner
from rdflib import Graph
import pytest

import kairos_ontology
from kairos_ontology.cli.main import cli
from kairos_ontology.core import projector


@pytest.mark.parametrize("target", ("dbt", "silver"))
def test_legacy_project_target_fails_before_resolution_or_writes(target, tmp_path, monkeypatch):
    output = tmp_path / "output"

    def unexpected(*args, **kwargs):
        raise AssertionError("legacy project path must fail before resolving or projecting")

    monkeypatch.setattr("kairos_ontology.cli.main._resolve_projection_cli_scope", unexpected)
    monkeypatch.setattr("kairos_ontology.cli.main.run_projections", unexpected)

    result = CliRunner().invoke(
        cli,
        ["project", "--target", target, "--output", str(output)],
    )

    assert result.exit_code == 1
    assert "compile <domain> --emit <directory>" in result.output
    assert not output.exists()


@pytest.mark.parametrize("target", ("dbt", "silver"))
def test_projector_entry_points_reject_retired_silver_paths(target, tmp_path):
    output = tmp_path / "output"

    with pytest.raises(projector.ProjectionRunError, match=r"compile <domain> --emit"):
        projector.run_projections(
            ontologies_path=tmp_path / "missing",
            catalog_path=None,
            output_path=output,
            target=target,
        )
    with pytest.raises(projector.ProjectionRunError, match=r"compile <domain> --emit"):
        projector.project_graph(Graph(), targets=[target])
    with pytest.raises(projector.ProjectionRunError, match=r"compile <domain> --emit"):
        projector._run_projection(
            target,
            Graph(),
            output,
            tmp_path,
            "https://example.com/domain#",
        )

    assert not output.exists()


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
