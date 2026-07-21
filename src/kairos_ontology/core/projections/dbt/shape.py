# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""dbt projection **shape** phase (DD-102).

Produces every model's shaped data + rendered bytes: source definitions, Silver
entity models (+ warnings + entity metadata), schema YAML with SHACL tests, the
Silver model registry, Gold star-schema models + schema YAML, coverage data, and
platform macros.

Because SQL/template rendering is interleaved with column/FK/test shaping inside the
retained model-generation helpers (``_gen_silver_models`` et al. — not redesigned per
scope, DD-102), this phase materialises both the shaped metadata and the rendered
artifact strings, handing the render phase a graph-free :class:`ShapedProject`.

All FK/binding *policy* is read from the normalize phase's
:class:`ProjectionContract` (FK descriptors + :class:`BindingAnalysis`) and the bind
phase's :class:`SourceBindings`; this phase never reclassifies binding policy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .context import ShapedProject

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .context import BoundSources, DbtInputs, ProjectionContract


def shape_project(
    inputs: "DbtInputs",
    bound: "BoundSources",
    contract: "ProjectionContract",
) -> ShapedProject:
    """Run the shape phase — build all model data + rendered artifact bytes."""
    from ..medallion_dbt_projector import (
        _build_silver_model_registry,
        _gen_gold_models,
        _gen_gold_schema_yaml,
        _gen_macros,
        _gen_schema_yaml,
        _gen_silver_models,
        _gen_sources,
        generate_coverage_data,
        logger,
    )

    env = inputs.env
    meta = inputs.meta
    onto_name = inputs.onto_name
    graph = bound.graph
    systems = bound.systems
    mappings = bound.mappings

    # 1. Sources YAML (minimal — under models/silver/).
    source_artifacts: dict[str, str] = {}
    if systems:
        source_artifacts = _gen_sources(
            systems,
            env,
            mappings,
            inputs.logical_sources_only,
            bound.virtual_table_uris,
            bound.replacement_input_uris,
        )
        logger.info("Generated %d source definition(s)", len(systems))

    # 2. Silver entity models (read directly from bronze via source()).
    silver, silver_warnings, silver_entity_meta = _gen_silver_models(
        inputs.classes,
        graph,
        inputs.namespace,
        systems,
        mappings,
        env,
        meta,
        onto_name,
        platform=inputs.target_platform,
        mapping_ns=bound.mapping_ns,
        contract_registry=bound.contracts,
        emit_aspirational_stubs=inputs.emit_aspirational_stubs,
        eligible_class_uris=inputs.eligible_class_uris,
        fk_classification=contract.fk_classification,
        bindings=bound.source_bindings,
        analysis=contract.binding_analysis,
    )
    logger.info("Generated %d silver model(s)", len(silver))
    if silver_warnings:
        for w in silver_warnings:
            logger.warning("%s", w)
        logger.info(
            "%d class(es) skipped — see projection-report.json for details",
            len(silver_warnings),
        )

    # Determine which classes actually generated silver models (schema filtering).
    # Only filter when source systems are present — without sources, schema YAML is
    # generated for all classes (ontology-only projections without bronze).
    generated_class_names: set[str] | None = None
    if systems:
        generated_class_names = {
            m["class_name"] for m in silver_entity_meta if not m.get("skipped")
        }
    aspirational_class_names = {
        m["class_name"] for m in silver_entity_meta if m.get("aspirational")
    }

    # 3. Schema YAML with SHACL tests.
    schema_artifacts = _gen_schema_yaml(
        inputs.classes,
        graph,
        inputs.namespace,
        inputs.shapes_dir,
        env,
        onto_name,
        meta,
        systems=systems,
        mappings=mappings,
        generated_class_names=generated_class_names,
        platform=inputs.target_platform,
        aspirational_class_names=aspirational_class_names,
        fk_classification=contract.fk_classification,
        naming_conv=contract.naming_conv,
    )

    # 4. Silver registry + Gold star schema (per-domain).
    gold_artifacts: dict[str, str] = {}
    gold_schema_artifacts: dict[str, str] = {}
    silver_name_reg: dict[str, str] = {}
    silver_cols_reg: dict[str, set[str]] = {}
    has_gold = False
    if systems:
        silver_name_reg, silver_cols_reg = _build_silver_model_registry(
            silver_entity_meta, inputs.classes, graph,
        )
        gold_artifacts = _gen_gold_models(
            inputs.classes,
            graph,
            inputs.namespace,
            inputs.shapes_dir,
            onto_name,
            inputs.gold_ext_path,
            env,
            meta,
            silver_name_registry=silver_name_reg,
            silver_columns_registry=silver_cols_reg,
        )
        has_gold = len(gold_artifacts) > 0
        if gold_artifacts:
            logger.info("Generated %d gold model(s)", len(gold_artifacts))

        gold_prefix = f"models/gold/{onto_name}/"
        shared_prefix = "models/gold/shared/"
        generated_gold_names = {
            p.removeprefix(gold_prefix).removesuffix(".sql")
            for p in gold_artifacts
            if p.startswith(gold_prefix) and p.endswith(".sql")
        } | {
            p.removeprefix(shared_prefix).removesuffix(".sql")
            for p in gold_artifacts
            if p.startswith(shared_prefix) and p.endswith(".sql")
        }
        gold_schema_artifacts = _gen_gold_schema_yaml(
            inputs.classes,
            graph,
            inputs.namespace,
            inputs.shapes_dir,
            onto_name,
            inputs.gold_ext_path,
            env,
            meta,
            generated_gold_names=generated_gold_names,
        )

    # 5. Coverage data — merged JSON is written by the orchestrator later.
    coverage_data: dict[str, dict] = {}
    if systems:
        coverage_data = generate_coverage_data(
            inputs.classes, graph, inputs.namespace, systems, mappings, onto_name,
        )
        if coverage_data:
            logger.info("Collected coverage data (%d entities)", len(coverage_data))

    # 6. Platform macros.
    macros = _gen_macros(inputs.template_dir)
    if macros:
        logger.info("Generated %d platform macro(s)", len(macros))

    return ShapedProject(
        source_artifacts=source_artifacts,
        silver_artifacts=silver,
        silver_warnings=silver_warnings,
        silver_entity_meta=silver_entity_meta,
        schema_artifacts=schema_artifacts,
        gold_artifacts=gold_artifacts,
        gold_schema_artifacts=gold_schema_artifacts,
        silver_name_registry=silver_name_reg,
        silver_columns_registry=silver_cols_reg,
        coverage_data=coverage_data,
        macros=macros,
        generated_class_names=(
            frozenset(generated_class_names)
            if generated_class_names is not None
            else None
        ),
        aspirational_class_names=frozenset(aspirational_class_names),
        has_gold=has_gold,
    )
