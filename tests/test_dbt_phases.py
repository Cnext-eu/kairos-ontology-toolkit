# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Phase-level unit tests for the five-phase dbt projection pipeline (DD-102).

Output parity (byte-for-byte) is covered by the scenario/golden/determinism suites.
These tests target the *architecture* the decomposition introduces:

* the intermediate models are immutable (frozen dataclasses);
* the phases are deterministic (two runs → identical ordering & bytes);
* the phase *boundaries* hold — bind commits source facts, normalize owns the FK +
  binding contract, and ``render`` consumes only committed strings/metadata (it never
  touches the RDF graph or the SKOS mappings).
"""

from __future__ import annotations

import dataclasses
import inspect
from pathlib import Path

import pytest
from rdflib import Graph
from rdflib.namespace import OWL, RDF, RDFS

from kairos_ontology.core.projections.dbt import (
    BoundSources,
    DbtInputs,
    MaterializationPlan,
    ProjectionContract,
    ShapedProject,
    bind_sources,
    normalize_contract,
    plan_materialization,
    render_project,
    shape_project,
)
from kairos_ontology.core.projections.medallion_dbt_projector import (
    SourceBindings,
    generate_dbt_artifacts,
)
from kairos_ontology.core.projections.shared import KAIROS_EXT
from kairos_ontology.core.projections.uri_utils import extract_local_name

HUB_ROOT = Path(__file__).parent / "scenarios" / "acme-hub"
ONTOLOGIES_DIR = HUB_ROOT / "model" / "ontologies"
EXTENSIONS_DIR = HUB_ROOT / "model" / "extensions"
SHAPES_DIR = HUB_ROOT / "model" / "shapes"
MAPPINGS_DIR = HUB_ROOT / "model" / "mappings"
SOURCES_DIR = HUB_ROOT / "integration" / "sources"
TEMPLATE_DIR = (
    Path(__file__).parent.parent / "src" / "kairos_ontology" / "templates" / "dbt"
)


def _load_client() -> tuple[Graph, str, list[dict]]:
    g = Graph()
    g.parse(ONTOLOGIES_DIR / "client.ttl", format="turtle")
    ext = EXTENSIONS_DIR / "client-silver-ext.ttl"
    if ext.exists():
        g.parse(ext, format="turtle")
    namespace = None
    for onto in g.subjects(RDF.type, OWL.Ontology):
        uri = str(onto)
        namespace = uri + "#" if "#" not in uri else uri.rsplit("#", 1)[0] + "#"
        break
    classes = []
    for cls in g.subjects(RDF.type, OWL.Class):
        cls_uri = str(cls)
        if not cls_uri.startswith(namespace):
            continue
        local = extract_local_name(cls_uri)
        classes.append({
            "uri": cls_uri,
            "name": local,
            "label": str(g.value(cls, RDFS.label) or local),
            "comment": str(g.value(cls, RDFS.comment) or f"{local} entity"),
        })
    return g, namespace, classes


def _client_inputs() -> DbtInputs:
    graph, namespace, classes = _load_client()
    gold_ext = EXTENSIONS_DIR / "client-gold-ext.ttl"
    silver_ext = EXTENSIONS_DIR / "client-silver-ext.ttl"
    return DbtInputs.from_call(
        classes=classes,
        graph=graph,
        template_dir=TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name="client",
        bronze_dir=SOURCES_DIR,
        sources_dir=SOURCES_DIR,
        mappings_dir=MAPPINGS_DIR,
        target_platform="fabric",
        gold_ext_path=gold_ext if gold_ext.exists() else None,
        silver_ext_path=silver_ext if silver_ext.exists() else None,
    )


def _run_all_phases(inputs: DbtInputs):
    bound = bind_sources(inputs)
    contract = normalize_contract(inputs, bound)
    shaped = shape_project(inputs, bound, contract)
    plan = plan_materialization(inputs, bound, contract, shaped)
    artifacts = render_project(shaped, plan)
    return bound, contract, shaped, plan, artifacts


# ---------------------------------------------------------------------------
# DbtInputs derivation
# ---------------------------------------------------------------------------

def test_dbtinputs_from_call_derives_env_meta_onto_name():
    inputs = _client_inputs()
    assert inputs.onto_name == "client"
    assert inputs.meta == {}
    # env is a jinja Environment able to load the silver template.
    assert inputs.env.get_template("silver_model.sql.jinja2") is not None


def test_dbtinputs_from_call_defaults_onto_name_to_domain():
    graph, namespace, classes = _load_client()
    inputs = DbtInputs.from_call(
        classes=classes,
        graph=graph,
        template_dir=TEMPLATE_DIR,
        namespace=namespace,
        target_platform="fabric",
    )
    assert inputs.onto_name == "domain"
    assert inputs.meta == {}


# ---------------------------------------------------------------------------
# Immutability — every intermediate model is a frozen dataclass
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls", [
    DbtInputs, BoundSources, ProjectionContract, ShapedProject, MaterializationPlan,
])
def test_phase_models_are_frozen_dataclasses(cls):
    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen is True


def test_phase_instances_reject_mutation():
    inputs = _client_inputs()
    bound, contract, shaped, plan, _ = _run_all_phases(inputs)
    for instance, field in [
        (inputs, "namespace"),
        (bound, "systems"),
        (contract, "naming_conv"),
        (shaped, "silver_artifacts"),
        (plan, "project_config"),
    ]:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(instance, field, None)


# ---------------------------------------------------------------------------
# Bind boundary — commits source-side facts (systems, mappings, SourceBindings)
# ---------------------------------------------------------------------------

def test_bind_commits_sources_mappings_and_bindings():
    inputs = _client_inputs()
    bound = bind_sources(inputs)
    assert isinstance(bound, BoundSources)
    assert bound.has_sources is True
    assert bound.systems, "client scenario has bronze source systems"
    assert "table_maps" in bound.mappings
    assert isinstance(bound.source_bindings, SourceBindings)
    # class_to_sources is the canonical binding fact consumed downstream.
    assert bound.source_bindings.class_to_sources


def test_bind_merges_silver_ext_into_working_graph():
    inputs = _client_inputs()
    bound = bind_sources(inputs)
    # The ext-merged graph must expose silver-ext annotations (naturalKey) that are
    # absent from the raw domain ontology — proving the merge is committed at bind.
    has_natural_key = any(
        bound.graph.triples((None, KAIROS_EXT.naturalKey, None))
    )
    assert has_natural_key


# ---------------------------------------------------------------------------
# Normalize boundary — owns the FK + binding contract grounded in the bindings
# ---------------------------------------------------------------------------

def test_normalize_grounds_binding_analysis_in_committed_bindings():
    inputs = _client_inputs()
    bound = bind_sources(inputs)
    contract = normalize_contract(inputs, bound)
    assert isinstance(contract, ProjectionContract)
    # FK descriptors are the canonical classification.
    assert contract.fk_classification is not None
    # The binding analysis agrees with the committed SourceBindings: every class the
    # bind phase bound to a source is classified BOUND by normalize (no re-derivation).
    for cls_uri, refs in bound.source_bindings.class_to_sources.items():
        if refs:
            assert contract.binding_analysis.is_bound(cls_uri)


# ---------------------------------------------------------------------------
# Render boundary — consumes ONLY committed strings/metadata (no RDF, no policy)
# ---------------------------------------------------------------------------

def test_render_signature_takes_only_shaped_and_plan():
    params = list(inspect.signature(render_project).parameters)
    assert params == ["shaped", "plan"]


def test_render_is_graph_free_pure_assembly():
    """render_project assembles the final map from plain data — no graph needed."""
    shaped = ShapedProject(
        source_artifacts={"models/silver/_src__sources.yml": "version: 2\n"},
        silver_artifacts={"models/silver/client/client.sql": "select 1 as x\n"},
        silver_warnings=[],
        silver_entity_meta=[],
        schema_artifacts={"models/silver/client/_models.yml": "version: 2\n"},
        gold_artifacts={},
        gold_schema_artifacts={},
        silver_name_registry={},
        silver_columns_registry={},
        coverage_data={"client": {"mapped": 3}},
        macros={"macros/kairos_safe_cast.sql": "-- macro\n"},
        generated_class_names=frozenset({"Client"}),
        aspirational_class_names=frozenset(),
        has_gold=False,
    )
    plan = MaterializationPlan(
        unbound_eligible_names=("Prospect", "Lead"),
        project_config={"dbt_project.yml": "name: p\n"},
        known_models=frozenset(),
    )
    artifacts = render_project(shaped, plan)
    # Special sentinels are attached with the exact shapes the orchestrator expects.
    assert artifacts["__unbound_eligible__"] == ["Prospect", "Lead"]
    assert artifacts["__coverage_data__"] == {"client": {"mapped": 3}}
    # Every shaped/plan artifact is present in the assembled map.
    for key in (
        "models/silver/_src__sources.yml",
        "models/silver/client/client.sql",
        "models/silver/client/_models.yml",
        "macros/kairos_safe_cast.sql",
        "dbt_project.yml",
    ):
        assert key in artifacts


def test_render_omits_empty_sentinels():
    shaped = ShapedProject(
        source_artifacts={},
        silver_artifacts={"models/silver/client/client.sql": "select 1\n"},
        silver_warnings=[],
        silver_entity_meta=[],
        schema_artifacts={},
        gold_artifacts={},
        gold_schema_artifacts={},
        silver_name_registry={},
        silver_columns_registry={},
        coverage_data={},
        macros={},
        generated_class_names=None,
        aspirational_class_names=frozenset(),
        has_gold=False,
    )
    plan = MaterializationPlan(
        unbound_eligible_names=(),
        project_config={},
        known_models=frozenset(),
    )
    artifacts = render_project(shaped, plan)
    assert "__unbound_eligible__" not in artifacts
    assert "__coverage_data__" not in artifacts


# ---------------------------------------------------------------------------
# Orchestration parity + determinism
# ---------------------------------------------------------------------------

def test_phase_pipeline_matches_public_entrypoint(monkeypatch):
    monkeypatch.setenv("KAIROS_GENERATED_AT", "2026-01-01T00:00:00Z")
    graph, namespace, classes = _load_client()
    gold_ext = EXTENSIONS_DIR / "client-gold-ext.ttl"
    silver_ext = EXTENSIONS_DIR / "client-silver-ext.ttl"
    public = generate_dbt_artifacts(
        classes=classes,
        graph=graph,
        template_dir=TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name="client",
        bronze_dir=SOURCES_DIR,
        sources_dir=SOURCES_DIR,
        mappings_dir=MAPPINGS_DIR,
        gold_ext_path=gold_ext if gold_ext.exists() else None,
        silver_ext_path=silver_ext if silver_ext.exists() else None,
    )
    _, _, _, _, via_phases = _run_all_phases(_client_inputs())
    assert via_phases == public


def test_phases_are_deterministic(monkeypatch):
    monkeypatch.setenv("KAIROS_GENERATED_AT", "2026-01-01T00:00:00Z")
    _, _, shaped_a, plan_a, artifacts_a = _run_all_phases(_client_inputs())
    _, _, shaped_b, plan_b, artifacts_b = _run_all_phases(_client_inputs())
    # Identical bytes AND identical key ordering across independent runs.
    assert artifacts_a == artifacts_b
    assert list(artifacts_a.keys()) == list(artifacts_b.keys())
    # Deterministic entity-metadata ordering (drives the session log / report).
    assert [m["class_name"] for m in shaped_a.silver_entity_meta] == \
        [m["class_name"] for m in shaped_b.silver_entity_meta]
    # Release metadata is sorted deterministically.
    assert plan_a.unbound_eligible_names == plan_b.unbound_eligible_names
    assert list(plan_a.unbound_eligible_names) == sorted(plan_a.unbound_eligible_names)


def test_materialization_plan_release_metadata():
    inputs = _client_inputs()
    _, _, shaped, plan, _ = _run_all_phases(inputs)
    # unbound_eligible_names is derived purely from the shaped entity metadata.
    expected = tuple(sorted(
        m["class_name"] for m in shaped.silver_entity_meta
        if m.get("aspirational") or m.get("unbound_eligible")
    ))
    assert plan.unbound_eligible_names == expected
    assert plan.known_models == frozenset()
