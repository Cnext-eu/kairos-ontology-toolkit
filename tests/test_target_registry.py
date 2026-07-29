# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused tests for projection target registration and compatibility views."""

from pathlib import Path
from types import MappingProxyType

from click.testing import CliRunner
from rdflib import Graph
import pytest

import kairos_ontology.core.projector as projector
import kairos_ontology.mdm as mdm
from kairos_ontology.cli.main import cli

BUILTIN_TARGETS = (
    "neo4j",
    "azure-search",
    "a2ui",
    "prompt",
    "powerbi",
    "report",
    "ddd",
)
ALL_TARGETS = tuple(target for target in BUILTIN_TARGETS if target != "powerbi")
CLI_TARGETS = (*BUILTIN_TARGETS, "mdm-profile")
PROJECT_CLI_TARGETS = ("dbt", "silver", "gold", *CLI_TARGETS)
COMPATIBILITY_TARGETS = (
    "neo4j",
    "azure-search",
    "a2ui",
    "prompt",
    "gold",
    "report",
    "ddd",
    "mdm-profile",
)


@pytest.fixture
def isolated_registry(monkeypatch):
    registry = dict(projector.TARGET_REGISTRY)
    monkeypatch.setattr(projector, "_TARGET_REGISTRY", registry)
    monkeypatch.setattr(projector, "TARGET_REGISTRY", MappingProxyType(registry))
    monkeypatch.setattr(projector, "VALID_TARGETS", list(projector.VALID_TARGETS))
    return registry


def _discover_extension(ontology_name, source_file, extensions_dir):
    del ontology_name, source_file, extensions_dir
    return None


def _project_external(*, graph, namespace, ontology_name, ext_path, ontology_metadata):
    del graph, namespace, ontology_name, ext_path, ontology_metadata
    return {"external.txt": "external\n"}


def _project_external_collision(*, graph, namespace, ontology_name, ext_path, ontology_metadata):
    del graph, namespace, ontology_name, ext_path, ontology_metadata
    return {}


def test_registry_derives_order_aliases_classification_and_external_metadata():
    assert tuple(projector.TARGET_REGISTRY) == CLI_TARGETS
    assert tuple(projector.VALID_TARGETS) == COMPATIBILITY_TARGETS
    assert projector.projection_target_choices() == CLI_TARGETS
    assert projector.projection_targets_for_all() == ALL_TARGETS

    gold = projector.get_target_spec("gold")
    assert gold is projector.get_target_spec("powerbi")
    assert gold.canonical_name == "powerbi"
    assert gold.output_category is projector.OutputCategory.MEDALLION
    assert gold.output_path(Path("output")) == Path("output/medallion/powerbi")

    report = projector.get_target_spec("report")
    assert report.execution_phase is projector.ExecutionPhase.POST_DOMAIN
    assert report.output_category is projector.OutputCategory.REPORTS

    ddd = projector.get_target_spec("ddd")
    assert ddd.output_category is projector.OutputCategory.ARCHITECTURE

    mdm_spec = projector.get_target_spec("mdm-profile")
    assert mdm_spec.output_path(Path("output")) == Path("output/mdm")
    assert mdm_spec.external_dispatch is not None
    assert mdm_spec.include_in_all is False


def test_gold_alias_cannot_dispatch_graph_projector(monkeypatch):
    monkeypatch.setattr(
        projector,
        "_run_projection",
        lambda *args, **kwargs: pytest.fail("legacy graph authority was invoked"),
    )

    with pytest.raises(projector.ProjectionRunError, match="immutable CompilePlan"):
        projector.project_graph(Graph(), targets=["gold"])


def test_gold_cli_alias_reaches_compile_plan_guidance():
    result = CliRunner().invoke(cli, ["project", "--target", "gold"])

    assert result.exit_code != 0
    assert "bypasses the immutable CompilePlan" in result.output
    assert "Invalid value for '--target'" not in result.output


def test_default_graph_projection_excludes_compile_plan_only_targets(monkeypatch):
    dispatched = []
    monkeypatch.setattr(
        projector,
        "_run_projection",
        lambda target, *args, **kwargs: dispatched.append(target) or {},
    )

    projector.project_graph(Graph())

    assert dispatched == list(ALL_TARGETS)


def test_external_registration_is_one_operation_and_idempotent(isolated_registry):
    before_all = projector.projection_targets_for_all()

    for _ in range(2):
        projector.register_target(
            "external-example",
            aliases=("external-alias",),
            discover_ext=_discover_extension,
            project=_project_external,
            output_subdir="plugins/example",
        )

    spec = projector.get_target_spec("external-example")
    assert spec is projector.get_target_spec("external-alias")
    assert spec.external_dispatch is not None
    assert spec.output_subdir == "plugins/example"
    assert tuple(projector.VALID_TARGETS).count("external-example") == 1
    assert tuple(projector.TARGET_REGISTRY).count("external-example") == 1
    assert projector.projection_target_choices()[-1] == "external-example"
    assert projector.projection_targets_for_all() == before_all


@pytest.mark.parametrize(
    ("name", "aliases", "match"),
    [
        ("dbt", (), "reserved for the compile command"),
        ("gold", (), "already registered for 'powerbi'"),
        ("external-example", ("neo4j",), "already registered for 'neo4j'"),
        ("external-example", ("same", "same"), "duplicated"),
        ("all", (), "reserved"),
    ],
)
def test_registration_rejects_canonical_and_alias_collisions(
    isolated_registry, name, aliases, match
):
    with pytest.raises(ValueError, match=match):
        projector.register_target(
            name,
            aliases=aliases,
            discover_ext=_discover_extension,
            project=_project_external,
            output_subdir="plugins/example",
        )


def test_registration_rejects_different_repeat(isolated_registry):
    projector.register_target(
        "external-example",
        discover_ext=_discover_extension,
        project=_project_external,
        output_subdir="plugins/example",
    )

    with pytest.raises(ValueError, match="already registered with different metadata"):
        projector.register_target(
            "external-example",
            discover_ext=_discover_extension,
            project=_project_external_collision,
            output_subdir="plugins/example",
        )


def test_mdm_registration_can_be_repeated_without_mutating_registry():
    before = tuple(projector.TARGET_REGISTRY.items())
    mdm._register_projection_target()
    assert tuple(projector.TARGET_REGISTRY.items()) == before


def test_project_help_derives_preserved_target_choice_order():
    result = CliRunner().invoke(cli, ["project", "--help"])

    assert result.exit_code == 0, result.output
    compact = "".join(result.output.split())
    choices = "[all|" + "|".join(PROJECT_CLI_TARGETS) + "]"
    assert choices in compact
