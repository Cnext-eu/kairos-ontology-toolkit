# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Architecture tests for DD-110's byte-free dbt phase boundaries."""

from __future__ import annotations

import dataclasses
import inspect
from enum import Enum
from pathlib import Path

import jinja2
import pytest
from rdflib import Graph
from rdflib.namespace import OWL, RDF, RDFS
from rdflib.term import Identifier

from kairos_ontology.core.projections.dbt import (
    BoundSources,
    DbtInputs,
    DimensionalGoldSpec,
    MaterializationPlan,
    ProjectionContract,
    ShapedProject,
    bind_sources,
    normalize_contract,
    plan_materialization,
    render_project,
    shape_project,
)
from kairos_ontology.core.projections.dbt.specs import (
    BoundCoverage,
    BoundSchemaModel,
    BoundSilverModel,
    CoverageSpec,
    ModelPhysicalPlan,
    NormalizedCoverage,
    NormalizedSchemaModel,
    NormalizedSilverModel,
    ReleasePlan,
    SchemaDocumentSpec,
    SchemaModelSpec,
    SilverModelSpec,
    SourceCatalogSpec,
)
from kairos_ontology.core.projections.medallion_dbt_projector import (
    generate_dbt_artifacts,
)
from kairos_ontology.core.projections.uri_utils import extract_local_name

HUB_ROOT = Path(__file__).parent / "scenarios" / "acme-hub"
ONTOLOGIES_DIR = HUB_ROOT / "model" / "ontologies"
EXTENSIONS_DIR = HUB_ROOT / "model" / "extensions"
SHAPES_DIR = HUB_ROOT / "model" / "shapes"
MAPPINGS_DIR = HUB_ROOT / "model" / "mappings"
SOURCES_DIR = HUB_ROOT / "integration" / "sources"
TEMPLATE_DIR = Path(__file__).parent.parent / "src" / "kairos_ontology" / "templates" / "dbt"


def _load_client() -> tuple[Graph, str, list[dict]]:
    graph = Graph()
    graph.parse(ONTOLOGIES_DIR / "client.ttl", format="turtle")
    extension = EXTENSIONS_DIR / "client-silver-ext.ttl"
    if extension.exists():
        graph.parse(extension, format="turtle")
    namespace = next(
        (str(ontology) + "#" if "#" not in str(ontology) else str(ontology).rsplit("#", 1)[0] + "#")
        for ontology in graph.subjects(RDF.type, OWL.Ontology)
    )
    classes = []
    for class_uri in graph.subjects(RDF.type, OWL.Class):
        uri = str(class_uri)
        if not uri.startswith(namespace):
            continue
        local = extract_local_name(uri)
        classes.append(
            {
                "uri": uri,
                "name": local,
                "label": str(graph.value(class_uri, RDFS.label) or local),
                "comment": str(graph.value(class_uri, RDFS.comment) or f"{local} entity"),
            }
        )
    return graph, namespace, classes


def _client_inputs() -> DbtInputs:
    graph, namespace, classes = _load_client()
    return DbtInputs.from_call(
        classes=classes,
        graph=graph,
        template_dir=TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name="client",
        ontology_metadata={
            "iri": "https://acme.example/ontology/client",
            "version": "1.0.0",
            "toolkit_version": "test",
        },
        bronze_dir=SOURCES_DIR,
        sources_dir=SOURCES_DIR,
        mappings_dir=MAPPINGS_DIR,
        target_platform="fabric",
        gold_ext_path=EXTENSIONS_DIR / "client-gold-ext.ttl",
        silver_ext_path=EXTENSIONS_DIR / "client-silver-ext.ttl",
    )


def _run_all_phases(inputs: DbtInputs):
    bound = bind_sources(inputs)
    contract = normalize_contract(bound)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    return bound, contract, shaped, plan, render_project(shaped, plan)


def test_extension_ontology_version_does_not_override_domain_version():
    inputs = _client_inputs()
    inputs = dataclasses.replace(
        inputs,
        ontology_metadata=dataclasses.replace(inputs.ontology_metadata, version=""),
    )

    bound = bind_sources(inputs)

    assert bound.ontology_metadata.version == "1.0.0"


def _assert_deeply_immutable(value: object, path: str = "result") -> None:
    forbidden = (
        Graph,
        Identifier,
        jinja2.Environment,
        jinja2.BaseLoader,
        jinja2.Template,
        list,
        dict,
        set,
        bytearray,
        bytes,
        Path,
    )
    assert not isinstance(value, forbidden), f"{path} leaked {type(value).__name__}"
    if dataclasses.is_dataclass(value):
        assert value.__dataclass_params__.frozen is True
        assert "__slots__" in type(value).__dict__
        for field in dataclasses.fields(value):
            _assert_deeply_immutable(getattr(value, field.name), f"{path}.{field.name}")
    elif isinstance(value, tuple):
        for index, item in enumerate(value):
            _assert_deeply_immutable(item, f"{path}[{index}]")
    elif isinstance(value, frozenset):
        for item in value:
            _assert_deeply_immutable(item, f"{path}[{item!r}]")
    else:
        assert value is None or isinstance(value, (str, int, float, bool, Enum))
        if isinstance(value, str):
            rendered_markers = (
                "-- Silver model",
                "-- Gold model",
                "version: 2\nmodels:",
                "# dbt Project",
                "{% macro ",
            )
            assert not any(marker in value for marker in rendered_markers), (
                f"{path} leaked rendered artifact content"
            )


def _contains_type(value: object, expected: tuple[type, ...]) -> bool:
    if isinstance(value, expected):
        return True
    if dataclasses.is_dataclass(value):
        return any(
            _contains_type(getattr(value, field.name), expected)
            for field in dataclasses.fields(value)
        )
    if isinstance(value, (tuple, frozenset)):
        return any(_contains_type(item, expected) for item in value)
    return False


@pytest.mark.parametrize(
    "record_type",
    [DbtInputs, BoundSources, ProjectionContract, ShapedProject, MaterializationPlan],
)
def test_phase_records_are_frozen_slotted_dataclasses(record_type):
    assert dataclasses.is_dataclass(record_type)
    assert record_type.__dataclass_params__.frozen is True
    assert "__slots__" in record_type.__dict__


def test_call_inputs_copy_mutable_values_without_creating_jinja():
    inputs = _client_inputs()
    assert inputs.ontology_name == "client"
    assert inputs.ontology_metadata.iri == "https://acme.example/ontology/client"
    assert isinstance(inputs.classes, tuple)
    assert not hasattr(inputs, "env")


def test_every_phase_result_is_deeply_immutable_and_authoring_free():
    bound, contract, shaped, plan, _ = _run_all_phases(_client_inputs())
    for result in (bound, contract, shaped, plan):
        _assert_deeply_immutable(result)


def test_bind_consumes_rdf_into_domain_specific_facts():
    bound = bind_sources(_client_inputs())
    assert bound.has_sources
    assert bound.systems[0].tables
    assert bound.mappings.tables
    assert bound.source_bindings.class_to_sources
    assert bound.foreign_key_facts
    assert all(isinstance(item, BoundSilverModel) for item in bound.silver_candidates)
    assert all(isinstance(item, BoundSchemaModel) for item in bound.schema_candidates)
    assert isinstance(bound.coverage, BoundCoverage)
    assert not _contains_type(
        bound,
        (SilverModelSpec, SchemaModelSpec, CoverageSpec),
    )
    assert not hasattr(bound, "graph")


def test_normalize_is_the_effective_policy_boundary():
    bound = bind_sources(_client_inputs())
    contract = normalize_contract(bound)
    for class_uri, sources in bound.source_bindings.class_to_sources:
        if sources:
            assert contract.binding_policy.is_bound(class_uri)
    assert contract.fk_classification.descriptors
    assert contract.naming_convention
    assert all(isinstance(item, NormalizedSilverModel) for item in contract.project.silver_models)
    assert all(isinstance(item, NormalizedSchemaModel) for item in contract.project.schema_models)
    assert isinstance(contract.project.coverage, NormalizedCoverage)
    assert not _contains_type(
        contract,
        (SilverModelSpec, SchemaModelSpec, CoverageSpec),
    )


def test_shape_contains_logical_specs_and_no_artifact_maps():
    bound = bind_sources(_client_inputs())
    contract = normalize_contract(bound)
    shaped = shape_project(contract)
    assert shaped.source_catalogs
    assert all(isinstance(item, SourceCatalogSpec) for item in shaped.source_catalogs)
    assert all(isinstance(item, SilverModelSpec) for item in shaped.silver_models)
    assert all(isinstance(item, SchemaDocumentSpec) for item in shaped.schema_documents)
    assert isinstance(shaped.gold_product, DimensionalGoldSpec)
    assert not any(field.name.endswith("artifacts") for field in dataclasses.fields(shaped))
    assert list(inspect.signature(shape_project).parameters) == ["contract"]


def test_materialize_selects_physical_adapter_models_dependencies_and_release():
    bound = bind_sources(_client_inputs())
    contract = normalize_contract(bound)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    assert plan.adapter.platform == "fabric"
    assert plan.models
    assert all(isinstance(item, ModelPhysicalPlan) for item in plan.models)
    assert all(item.template_name for item in plan.models)
    assert len(plan.documents) == len(shaped.schema_documents)
    assert all(item.template_name for item in plan.documents)
    assert plan.project.emit is True
    assert isinstance(plan.release, ReleasePlan)
    assert list(inspect.signature(plan_materialization).parameters) == [
        "contract",
        "shaped",
    ]


def test_normalize_shape_and_materialize_cannot_read_authoring_or_templates(
    monkeypatch,
):
    bound = bind_sources(_client_inputs())

    def forbidden(*_args, **_kwargs):
        raise AssertionError("post-bind phase attempted authoring/template I/O")

    for name in ("parse", "subjects", "objects", "triples", "value"):
        monkeypatch.setattr(Graph, name, forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(jinja2.Environment, "get_template", forbidden)

    contract = normalize_contract(bound)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    assert plan.models


def test_render_imports_no_monolithic_projector():
    source = inspect.getsource(inspect.getmodule(render_project))
    assert "medallion_dbt_projector" not in source
    assert list(inspect.signature(render_project).parameters) == ["shaped", "plan"]


def test_render_needs_no_rdf(monkeypatch):
    bound = bind_sources(_client_inputs())
    contract = normalize_contract(bound)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("render attempted RDF access")

    for name in ("parse", "subjects", "objects", "triples", "value"):
        monkeypatch.setattr(Graph, name, forbidden)
    artifacts = render_project(shaped, plan)
    assert any(path.endswith("/client.sql") for path in artifacts)
    assert any(path.endswith("__gold_models.yml") for path in artifacts)


def test_phase_pipeline_matches_public_entrypoint(monkeypatch):
    monkeypatch.setenv("KAIROS_GENERATED_AT", "2026-01-01T00:00:00Z")
    graph, namespace, classes = _load_client()
    public = generate_dbt_artifacts(
        classes=classes,
        graph=graph,
        template_dir=TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name="client",
        ontology_metadata={
            "iri": "https://acme.example/ontology/client",
            "version": "1.0.0",
            "toolkit_version": "test",
        },
        bronze_dir=SOURCES_DIR,
        sources_dir=SOURCES_DIR,
        mappings_dir=MAPPINGS_DIR,
        gold_ext_path=EXTENSIONS_DIR / "client-gold-ext.ttl",
        silver_ext_path=EXTENSIONS_DIR / "client-silver-ext.ttl",
    )
    *_, via_phases = _run_all_phases(_client_inputs())
    assert via_phases == public


def test_phases_are_deterministic(monkeypatch):
    monkeypatch.setenv("KAIROS_GENERATED_AT", "2026-01-01T00:00:00Z")
    *_, artifacts_a = _run_all_phases(_client_inputs())
    *_, artifacts_b = _run_all_phases(_client_inputs())
    assert artifacts_a == artifacts_b
    assert list(artifacts_a) == list(artifacts_b)
