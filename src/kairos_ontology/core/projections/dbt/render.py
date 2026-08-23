# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The sole dbt artifact-content and validation phase (DD-110)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError

from .context import MaterializationPlan, ShapedProject
from .canonical_hash import temporal_match_count_column, validate_runtime_sql_static
from .gold_render import gold_product_report, render_gold_dbt_artifacts
from .mapping_specs import (
    CaseExpression,
    FunctionExpression,
    LiteralExpression,
    MacroExpression,
    MappingExpression,
    NullExpression,
    OperatorExpression,
    SourceColumnExpression,
)
from .model_renderers import (
    render_schema_models,
    render_silver_model,
)
from .quality_renderers import (
    render_dq_accepted_model,
    render_dq_quarantine,
    render_dq_result,
    render_dq_runtime_contract,
    render_dq_test,
)
from .specs import CoverageSpec, ModelOutcome, SchemaKind, SilverModelKind, SourceCatalogSpec

logger = logging.getLogger(__name__)


# Jinja environments are cached rather than rebuilt per render call.
#
# Every ``template_root`` in the codebase resolves to the package's own read-only
# ``kairos_ontology/templates/dbt`` directory, and these environments are only ever
# read from (``get_template``/``parse``) — never mutated with per-call globals or
# filters — so one instance per root is safe to share. Building a fresh
# ``Environment`` each call gave every call a fresh, empty template cache, so the
# same handful of templates were re-read and re-compiled on every render.
# ``FileSystemLoader`` keeps ``auto_reload=True``, so a template edited on disk is
# still picked up; only the redundant recompilation is avoided.
@lru_cache(maxsize=8)
def _template_environment(template_root: str) -> Environment:
    """Return the shared Jinja environment for ``template_root``."""
    return Environment(loader=FileSystemLoader(template_root))


# Standalone environment used only to syntax-check *rendered* output. The content
# differs every call, but the environment itself carries no per-call state.
_SYNTAX_CHECK_ENV = Environment()


class RuntimeRenderBlocked(ValueError):
    """A DD-109 physical plan has no supported adapter implementation."""

    def __init__(self, blocking_rules: tuple[tuple[str, str], ...]) -> None:
        self.blocking_rules = blocking_rules
        detail = "; ".join(f"{rule_id}: {message}" for rule_id, message in blocking_rules)
        super().__init__(f"Runtime materialization blocked: {detail}")


def _type_data(value) -> dict[str, object]:
    return {
        "kind": value.kind.value,
        "precision": value.precision,
        "scale": value.scale,
        "length": value.length,
    }


def _mapping_expression_data(expression: MappingExpression) -> dict[str, object]:
    metadata = expression.metadata
    result: dict[str, object] = {
        "node": type(expression).__name__,
        "output_type": _type_data(metadata.output_type),
        "nullable": metadata.nullable,
        "null_policy": metadata.null_policy.value,
        "determinism": metadata.determinism.value,
        "referenced_inputs": [
            {
                "source_column_uri": item.source_column_uri,
                "source_table_uri": item.source_table_uri,
                "authored_name": item.authored_name,
                "physical_name": item.physical_name,
                "data_type": _type_data(item.data_type),
                "nullable": item.nullable,
                "origin": item.origin,
            }
            for item in metadata.referenced_inputs
        ],
        "capability_requirements": [item.value for item in metadata.capability_requirements],
        "supported_adapters": list(metadata.supported_adapters),
        "provenance": {
            "mapping_resource_uri": metadata.provenance.mapping_resource_uri,
            "expression_resource_uri": metadata.provenance.expression_resource_uri,
            "source": metadata.provenance.source,
            "rule_id": metadata.provenance.rule_id,
        },
    }
    if isinstance(expression, SourceColumnExpression):
        result["source_column_uri"] = expression.input.source_column_uri
    elif isinstance(expression, LiteralExpression):
        result["literal"] = {
            "lexical": expression.lexical,
            "datatype": expression.datatype_uri,
        }
    elif isinstance(expression, NullExpression):
        result["literal"] = None
    elif isinstance(expression, OperatorExpression):
        result["operator"] = expression.operator
        result["arguments"] = [_mapping_expression_data(item) for item in expression.arguments]
    elif isinstance(expression, FunctionExpression):
        result["function"] = expression.function
        result["arguments"] = [_mapping_expression_data(item) for item in expression.arguments]
    elif isinstance(expression, MacroExpression):
        result["macro_uri"] = expression.macro_uri
        result["macro_name"] = expression.macro_name
        result["arguments"] = [_mapping_expression_data(item) for item in expression.arguments]
    elif isinstance(expression, CaseExpression):
        result["branches"] = [
            {
                "when": _mapping_expression_data(item.condition),
                "then": _mapping_expression_data(item.result),
            }
            for item in expression.branches
        ]
        result["else"] = _mapping_expression_data(expression.else_expression)
    return result


def _render_source(spec: SourceCatalogSpec, env: Environment) -> str:
    return env.get_template("sources.yml.jinja2").render(
        source_name=spec.source_name,
        system_label=spec.system_label,
        database=spec.database,
        schema=spec.schema,
        tables=[{"name": table.name, "label": table.label} for table in spec.tables],
        logical_sources_only=spec.logical_sources_only,
    )


def _coverage_data(spec: CoverageSpec) -> dict[str, dict]:
    return {
        entity.model_name: {
            "ontology_properties_total": entity.ontology_properties_total,
            "ontology_properties_required": entity.ontology_properties_required,
            "ontology_properties_optional": entity.ontology_properties_optional,
            "ontology_properties_derived": entity.ontology_properties_derived,
            "populated_from_source": entity.populated_from_source,
            "always_null": entity.always_null,
            "null_columns": list(entity.null_columns),
            "missing_required_mappings": list(entity.missing_required_mappings),
            "source_coverage": {
                source.name: {
                    "available_columns": source.available_columns,
                    "consumed_columns": source.consumed_columns,
                    "unused_columns": list(source.unused_columns),
                }
                for source in entity.source_coverage
            },
        }
        for entity in spec.entities
    }


def _render_project_config(
    plan: MaterializationPlan,
    env: Environment,
) -> dict[str, str]:
    if not plan.project.emit:
        return {}
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", plan.project.project_name)
    if safe_name and safe_name[0].isdigit():
        safe_name = f"p_{safe_name}"
    artifacts = {
        "dbt_project.yml": env.get_template("dbt_project.yml.jinja2").render(
            project_name=safe_name,
            domains=[{"name": name} for name in plan.project.domains],
            gold_domains=[{"name": name} for name in plan.project.gold_domains],
            adapter=plan.adapter.platform,
        ),
        "packages.yml": env.get_template("packages.yml.jinja2").render(),
    }
    platform = plan.adapter.platform
    if platform == "fabric":
        adapter = "dbt-fabric"
        platform_label = "Microsoft Fabric Warehouse"
    elif platform == "databricks":
        adapter = "dbt-databricks"
        platform_label = "Azure Databricks"
    else:
        raise ValueError(f"Unsupported dbt adapter {platform!r}; expected 'fabric' or 'databricks'")
    artifacts["README.md"] = f"""# dbt Project — {plan.project.project_name}

Generated by **Kairos Ontology Toolkit** (dbt projector).

## Target Platform

| Setting | Value |
|---------|-------|
| Platform | {platform_label} |
| dbt adapter | `{adapter}` |
| SQL dialect | {"T-SQL" if platform == "fabric" else "Spark SQL"} |

## Getting Started

This is the single, unified build target for the whole hub: every domain (and any
Gold products) emits into this one `ontology-hub-publish/medallion/dbt` project. Point
`dbt` and `kairos-ontology validate-dbt` at this directory — there is no per-domain dbt
project.

```bash
# Install dbt and the adapter
pip install dbt-core
pip install {adapter}

# Install dbt packages (dbt_utils, dbt_expectations)
dbt deps

# Optional offline gate: parse + compile this project with no warehouse
kairos-ontology validate-dbt --platform {platform}

# Configure your connection in profiles.yml
# Then run:
dbt run
```

## Project Structure

```
models/
├── silver/           # Domain-aligned: maps bronze → canonical entities
│   └── <domain>/    # One folder per ontology domain
└── gold/             # Star schema: facts, dimensions, measures
    └── <domain>/

seeds/                # Hub-authored reference/lookup catalogs

macros/               # Platform-abstraction macros (kairos_safe_cast, etc.)
```

## Layer Contracts

| Layer | Materialization | Purpose |
|-------|----------------|---------|
| Bronze | (platform-managed) | Raw source tables — outside dbt |
| Silver | Table | Domain entities mapped from bronze via `{{{{ source() }}}}` |
| Gold | Table | Star schema for BI (Power BI DirectLake / Databricks SQL) |
| Reference | Seed | Hub-authored reference/lookup catalogs (`schema: reference`) |

## Platform Macros

The `macros/` folder contains platform-abstraction macros:
- `kairos_safe_cast(column, type)` — safe casting (TRY_CAST)
- `kairos_json_value(column, path)` — extract single JSON value
- `kairos_surrogate_key(columns)` — surrogate key generation
- `kairos_concat(...)` — string concatenation
"""
    return artifacts


def render_project_config(plan: MaterializationPlan) -> dict[str, str]:
    """Render a standalone project configuration through the render authority."""
    env = _template_environment(plan.adapter.template_root)
    return _render_project_config(plan, env)


def render_canonical_project(
    shaped: ShapedProject,
    plan: MaterializationPlan,
) -> dict[str, str]:
    """Render only canonical v5 Silver/dbt files.

    Release-review, runtime-result, and other design-time products are
    deliberately outside this renderer. Focused binding quality checks are ordinary dbt
    tests and are added by the compiler after this shared render phase.
    """
    env = _template_environment(plan.adapter.template_root)
    physical = {item.artifact_path: item for item in plan.models}
    document_plans = {item.artifact_path: item for item in plan.documents}
    quality_by_model = {item.model_name: item for item in plan.quality_models}
    artifacts: dict[str, str] = {}
    canonical_models = tuple(
        model for model in shaped.silver_models if model.identity.outcome is ModelOutcome.GENERATED
    )
    canonical_names = {model.identity.model_name for model in canonical_models}

    runtime_blockers = tuple(
        reason
        for model_plan in plan.models
        if model_plan.runtime is not None
        for reason in model_plan.runtime.blocking_reasons
    )
    if runtime_blockers:
        raise RuntimeRenderBlocked(runtime_blockers)

    for source in shaped.source_catalogs:
        artifacts[source.artifact_path] = _render_source(source, env)
    for model in canonical_models:
        path = model.identity.artifact_path
        if path is None:
            continue
        model_plan = physical[path]
        content = render_silver_model(model, env, model_plan, plan.adapter.platform)
        if model_plan.runtime is not None:
            validate_runtime_sql_static(content, plan.adapter.platform)
        quality = quality_by_model.get(model.identity.model_name)
        if quality is not None and quality.quarantines_rows:
            artifacts[quality.evaluated_artifact_path] = content
            marker_header = "\n".join(content.splitlines()[:2]) + "\n"
            artifacts[path] = marker_header + render_dq_accepted_model(quality, model)
            artifacts[quality.quarantine_artifact_path] = render_dq_quarantine(
                quality,
                model,
                adapter=plan.adapter.platform,
            )
        else:
            artifacts[path] = content
    for quality in plan.quality_models:
        for rule in quality.rules:
            artifacts[rule.result_artifact_path] = render_dq_result(
                rule,
                adapter=plan.adapter.platform,
                adapter_version=plan.adapter.version,
            )
            artifacts[rule.test_artifact_path] = render_dq_test(rule)
    if plan.policy is not None and plan.quality_models:
        artifacts["contracts/dq-runtime-result-contract.schema.json"] = render_dq_runtime_contract(
            plan.policy.dq_runtime_result
        )
    for document in shaped.schema_documents:
        if document.kind is not SchemaKind.SILVER:
            continue
        models = tuple(model for model in document.models if model.name in canonical_names)
        if not models:
            continue
        artifacts[document.artifact_path] = render_schema_models(
            models,
            env,
            template_name=document_plans[document.artifact_path].template_name,
            physical_models=(
                tuple(model for model in plan.silver.models if model.model_name in canonical_names)
                if plan.silver is not None
                else ()
            ),
        )
    if plan.silver is not None and plan.silver.models and canonical_models:
        from ..medallion_silver_projector import generate_silver_artifacts

        canonical_silver = replace(
            plan.silver,
            models=tuple(
                model for model in plan.silver.models if model.model_name in canonical_names
            ),
        )
        schema_paths = {
            model.name: document.artifact_path
            for document in shaped.schema_documents
            if document.kind is SchemaKind.SILVER
            for model in document.models
            if model.name in canonical_names
        }
        silver_artifacts, _ = generate_silver_artifacts(
            models=canonical_models,
            physical_plan=canonical_silver,
            rendered_artifacts=artifacts,
            schema_paths=schema_paths,
        )
        artifacts.update(silver_artifacts)
    artifacts.update(_render_project_config(plan, env))
    macro_root = Path(plan.adapter.template_root) / "macros"
    for name in shaped.macros.names:
        artifacts[f"macros/{name}"] = (macro_root / name).read_text(encoding="utf-8")

    _validate_dbt_artifacts(artifacts)
    return artifacts


def render_project(
    shaped: ShapedProject,
    plan: MaterializationPlan,
) -> dict:
    """Render and validate artifacts from logical specs plus physical plans only."""
    env = _template_environment(plan.adapter.template_root)
    physical = {item.artifact_path: item for item in plan.models}
    quality_by_model = {item.model_name: item for item in plan.quality_models}
    document_plans = {item.artifact_path: item for item in plan.documents}
    artifacts: dict = {}
    parity_status: dict[str, object] = {
        "status": "not-applicable",
        "required": False,
        "errors": [],
    }

    runtime_blockers = tuple(
        reason
        for model_plan in plan.models
        if model_plan.runtime is not None
        for reason in model_plan.runtime.blocking_reasons
    )
    if runtime_blockers:
        raise RuntimeRenderBlocked(runtime_blockers)
    mapping_blockers = tuple(
        item for item in plan.release.mapping_capability_results if not item.supported
    )
    if mapping_blockers:
        detail = "; ".join(
            (
                f"{item.mapping_resource_uri}: {item.capability.value} is unsupported "
                f"on {item.adapter}"
            )
            for item in mapping_blockers
        )
        raise ValueError(f"Mapping expression rendering blocked: {detail}")

    for source in shaped.source_catalogs:
        artifacts[source.artifact_path] = _render_source(source, env)
    for model in shaped.silver_models:
        path = model.identity.artifact_path
        if path is not None:
            model_plan = physical[path]
            content = render_silver_model(
                model,
                env,
                model_plan,
                plan.adapter.platform,
            )
            if model_plan.runtime is not None:
                validate_runtime_sql_static(content, plan.adapter.platform)
            quality = quality_by_model.get(model.identity.model_name)
            if quality is not None and quality.quarantines_rows:
                artifacts[quality.evaluated_artifact_path] = content
                marker_header = "\n".join(content.splitlines()[:2]) + "\n"
                artifacts[path] = marker_header + render_dq_accepted_model(
                    quality,
                    model,
                )
                artifacts[quality.quarantine_artifact_path] = render_dq_quarantine(
                    quality,
                    model,
                    adapter=plan.adapter.platform,
                )
            else:
                artifacts[path] = content
            if model_plan.runtime is not None:
                quarantine_paths = {
                    lookup.quarantine_artifact_path
                    for lookup in model_plan.runtime.temporal_lookups
                    if lookup.quarantine_artifact_path
                }
                for quarantine_path in sorted(quarantine_paths):
                    conditions: list[str] = []
                    for lookup in model_plan.runtime.temporal_lookups:
                        if lookup.quarantine_artifact_path != quarantine_path:
                            continue
                        diagnostic = temporal_match_count_column(lookup.property_uri)
                        if lookup.missing_action in {"quarantine", "retry"}:
                            conditions.append(f"{diagnostic} = 0")
                        if lookup.ambiguous_action in {"quarantine", "retry"}:
                            conditions.append(f"{diagnostic} > 1")
                    predicate = " OR ".join(conditions) or "1 = 0"
                    artifacts[quarantine_path] = (
                        f"-- DD-109 temporal FK quarantine/retry rows for "
                        f"{model.identity.model_name}\n"
                        f"select *\nfrom {{{{ ref('{model.identity.model_name}') }}}}\n"
                        f"where {predicate}\n"
                    )
    for quality in plan.quality_models:
        for rule in quality.rules:
            artifacts[rule.result_artifact_path] = render_dq_result(
                rule,
                adapter=plan.adapter.platform,
                adapter_version=plan.adapter.version,
            )
            artifacts[rule.test_artifact_path] = render_dq_test(rule)
    if plan.policy is not None:
        artifacts["contracts/dq-runtime-result-contract.schema.json"] = render_dq_runtime_contract(
            plan.policy.dq_runtime_result
        )

    for document in shaped.schema_documents:
        if document.kind is not SchemaKind.SILVER:
            continue
        artifacts[document.artifact_path] = render_schema_models(
            document.models,
            env,
            template_name=document_plans[document.artifact_path].template_name,
            physical_models=(plan.silver.models if plan.silver is not None else ()),
        )
    if shaped.gold_product is not None and plan.gold is not None:
        artifacts.update(render_gold_dbt_artifacts(shaped.gold_product, plan.gold))
    if plan.silver is not None and plan.silver.models:
        from ..medallion_silver_projector import generate_silver_artifacts

        schema_paths = {
            model.name: document.artifact_path
            for document in shaped.schema_documents
            if document.kind is SchemaKind.SILVER
            for model in document.models
        }
        silver_artifacts, parity_status = generate_silver_artifacts(
            models=shaped.silver_models,
            physical_plan=plan.silver,
            rendered_artifacts=artifacts,
            schema_paths=schema_paths,
        )
        parity_status["required"] = True
        artifacts.update(silver_artifacts)
    if shaped.gold_product is not None and plan.gold is not None:
        artifacts[f"metadata/{shaped.gold_product.ontology_name}-gold-product.json"] = (
            json.dumps(
                gold_product_report(
                    shaped.gold_product,
                    plan.gold,
                    silver_parity=parity_status,
                ),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    artifacts.update(_render_project_config(plan, env))
    if shaped.coverage is not None:
        artifacts["__coverage_data__"] = _coverage_data(shaped.coverage)
    artifacts["__release_data__"] = {
        "schema_version": "1.0",
        "mode": "review-only",
        "release_ready": False,
        "policy_version": plan.release.policy_version,
        "toolkit_version": plan.release.toolkit_version,
        "ontology_version": plan.release.ontology_version,
        "closure_version": plan.release.closure_version,
        "adapter": {
            "name": plan.adapter.platform,
            "version": plan.adapter.version,
        },
        "parity_status": parity_status,
        "policy_issues": [
            {
                "code": issue.code,
                "message": issue.message,
                "rule_id": issue.rule_id,
                "resource_uri": issue.resource_uri,
                "blocking": issue.blocking,
            }
            for issue in shaped.policy.issues
        ],
        "coverage_status": {
            "status": (
                "blocking"
                if shaped.coverage is not None
                and any(entity.missing_required_mappings for entity in shaped.coverage.entities)
                else "ready"
            ),
            "missing_required_mappings": [
                {
                    "model_name": entity.model_name,
                    "columns": list(entity.missing_required_mappings),
                }
                for entity in (shaped.coverage.entities if shaped.coverage is not None else ())
                if entity.missing_required_mappings
            ],
        },
        "adapter_compile_evidence": [
            {
                "resource_uri": evidence.resource_uri,
                "adapter": evidence.adapter.value.value,
                "adapter_version": evidence.adapter_version.value,
                "scope": evidence.scope.value,
                "capabilities": [capability.value for capability in evidence.capabilities.value],
                "status": evidence.status.value.value,
                "compile_evidence": list(evidence.compile_evidence.value),
            }
            for evidence in shaped.policy.adapter_evidence
        ],
        "deviations": [
            {
                "resource_uri": deviation.resource_uri,
                "adapter": (deviation.adapter.value if deviation.adapter is not None else None),
                "policy_reference": deviation.policy_reference.value,
                "scope": deviation.scope.value,
                "rationale": deviation.rationale.value,
                "owner_role": deviation.owner_role.value,
                "approval_status": deviation.approval_status.value,
                "review_date": deviation.review_date.value,
                "expiry_date": deviation.expiry_date.value,
                "evidence": list(deviation.evidence),
            }
            for deviation in shaped.policy.deviations
        ],
        "dq_runtime_result_contract": {
            "schema_version": shaped.policy.dq_runtime_result.schema_version,
            "relation_name": shaped.policy.dq_runtime_result.relation_name,
            "statuses": [status.value for status in shaped.policy.dq_runtime_result.statuses],
            "fields": [
                {
                    "name": field.name,
                    "data_type": field.data_type,
                    "nullable": field.nullable,
                    "description": field.description,
                }
                for field in shaped.policy.dq_runtime_result.fields
            ],
            "immutable_imported_evidence": (
                shaped.policy.dq_runtime_result.immutable_imported_evidence
            ),
            "artifact": "contracts/dq-runtime-result-contract.schema.json",
        },
        "dq_rules": [
            {
                "rule_id": rule.rule.rule_id.value,
                "rule_version": rule.rule.version.value,
                "rule_hash": rule.rule.rule_hash,
                "model_name": rule.target_model_name,
                "category": rule.rule.category.value.value,
                "check_kind": rule.rule.check.check_kind.value.value,
                "parameters": {
                    parameter.name: list(parameter.values)
                    for parameter in rule.rule.check.parameters
                },
                "test_refs": list(rule.rule.check.test_refs.value),
                "severity": rule.rule.severity.value.value,
                "tolerance": {
                    "kind": rule.rule.tolerance.value.kind.value,
                    "value": rule.rule.tolerance.value.value,
                    "unit": rule.rule.tolerance.value.unit,
                },
                "owner_role": rule.rule.owner_role.value,
                "action": rule.rule.action.value.value,
                "evidence": list(rule.rule.evidence.value),
                "result_artifact": rule.result_artifact_path,
                "test_artifact": rule.test_artifact_path,
                "quarantine_artifact": (
                    quality.quarantine_artifact_path
                    if rule.rule.action.value.value == "quarantine"
                    else None
                ),
                "result_status": "not-evaluated",
            }
            for quality in plan.quality_models
            for rule in quality.rules
        ],
        "gold_status": {
            "profile": (
                shaped.policy.gold.profile.value.value
                if shaped.policy.gold.profile is not None
                else None
            ),
            "security": (
                "not-applicable"
                if shaped.policy.gold.profile is None or shaped.policy.gold.security is None
                else "ready"
            ),
            "calendar": (
                "not-applicable"
                if shaped.policy.gold.profile is None or shaped.policy.gold.calendar is None
                else "ready"
                if shaped.policy.gold.calendar.approved
                else "blocking"
            ),
            "measures": (
                "not-applicable"
                if shaped.policy.gold.profile is None
                else (
                    "ready"
                    if all(
                        measure.lifecycle.value.value == "approved"
                        for measure in shaped.policy.gold.measures
                    )
                    else "blocking"
                )
            ),
            "tables": (
                "not-applicable"
                if shaped.policy.gold.profile is None
                else "ready"
                if shaped.gold_product is not None
                else "blocking"
            ),
            "adapter": (
                "not-applicable"
                if shaped.policy.gold.profile is None
                else "ready"
                if plan.gold is not None
                else "blocking"
            ),
            "tmdl_compile": (
                "not-applicable"
                if shaped.policy.gold.profile is None
                else (
                    "ready"
                    if any(
                        evidence.adapter.value.value == plan.adapter.platform
                        and evidence.adapter_version.value == plan.adapter.version
                        and evidence.scope.value in {"*", "project", "gold"}
                        and "tmdl"
                        in {capability.value for capability in evidence.capabilities.value}
                        and evidence.status.value.value == "supported"
                        and evidence.compile_evidence.value
                        for evidence in shaped.policy.adapter_evidence
                    )
                    else "blocking"
                )
            ),
            "measure_lifecycle": [
                {
                    "measure_id": measure.measure_id.value,
                    "status": measure.lifecycle.value.value,
                    "tests": list(measure.validation_tests.value),
                    "evidence": list(measure.validation_evidence.value),
                    "data_validated_by_projection": False,
                }
                for measure in shaped.policy.gold.measures
            ],
        },
        "identity_lineage": [
            {
                "model_name": model.identity.model_name,
                "class_uri": model.identity.class_uri,
                "business_grain": authority.entity_identity.business_grain.value,
                "identity_strategy": authority.entity_identity.strategy.value.value,
                "key_scope": authority.entity_identity.key_scope.value.value,
                "source_identity_refs": list(
                    authority.entity_identity.source.record_key_refs.value
                ),
                "natural_key_columns": list(authority.entity_identity.business.keys.value),
                "integration_key_emitted": (authority.entity_identity.integration.emitted),
                "mastered_identifier_refs": list(
                    authority.entity_identity.mastered.external_identifier_refs.value
                ),
                "entity_instance_iri_policy": (authority.entity_identity.iri.mode.value.value),
                "driving_source": {
                    "mode": authority.entity_identity.driving_source.mode.value.value,
                    "source_ref": (
                        authority.entity_identity.driving_source.source_ref.value
                        if authority.entity_identity.driving_source.source_ref is not None
                        else None
                    ),
                },
                "roles": [
                    {
                        "role": role.role.value,
                        "columns": list(role.columns),
                        "emitted": role.emitted,
                        "establishes_business_identity": (role.establishes_business_identity),
                        "key_scope": role.key_scope.value,
                    }
                    for role in authority.identity_roles
                ],
                "timestamps": [
                    {
                        "role": timestamp.role.value,
                        "column": timestamp.column_name,
                        "origin": timestamp.origin.value.value,
                        "source_column": timestamp.source_column,
                        "supplied": timestamp.supplied,
                        "sources": [
                            {
                                "source_identity_ref": source.source_identity_ref,
                                "source_column": source.source_column,
                                "origin": source.origin.value,
                                "supplied": source.supplied,
                            }
                            for source in timestamp.sources
                        ],
                    }
                    for timestamp in authority.audit.columns
                ],
                "multi_source": (
                    {
                        "relationship": authority.multi_source.relationship.value.value,
                        "exact_equivalence_approved": (
                            authority.multi_source.exact_equivalence.approved
                        ),
                        "normalization": (authority.multi_source.normalization.statement.value),
                        "precedence_mode": (authority.multi_source.precedence.mode.value.value),
                        "ordered_sources": list(
                            authority.multi_source.precedence.ordered_sources.value
                        ),
                        "conflict_action": authority.multi_source.conflict.value.value,
                        "collision_action": authority.multi_source.collision.value.value,
                        "deletion_action": authority.multi_source.deletion.value.value,
                        "late_arrival_action": (authority.multi_source.late_arrival.value.value),
                        "reconciliation_tests": list(
                            authority.multi_source.reconciliation_tests.value
                        ),
                    }
                    if authority.multi_source is not None
                    else None
                ),
                "contribution_lineage": (
                    {
                        "relation_name": authority.contribution_lineage.relation_name,
                        "parent_key_column": (authority.contribution_lineage.parent_key_column),
                        "source_system_column": (
                            authority.contribution_lineage.source_system_column
                        ),
                        "source_record_key_column": (
                            authority.contribution_lineage.source_record_key_column
                        ),
                        "source_role_column": (authority.contribution_lineage.source_role_column),
                        "source_identity_ref_column": (
                            authority.contribution_lineage.source_identity_ref_column
                        ),
                    }
                    if authority.contribution_lineage is not None
                    else None
                ),
                "mdm_routed": authority.entity_identity.mastered.routed_to_mdm,
                "reconciliation_limitation": (
                    authority.entity_identity.surrogate.reconciliation_limitation.value
                    if authority.entity_identity.surrogate.reconciliation_limitation is not None
                    else None
                ),
            }
            for model in shaped.silver_models
            if model.kind in {SilverModelKind.ENTITY, SilverModelKind.UNION}
            and (authority := model.authority) is not None
            and authority.entity_identity is not None
        ],
        "mdm_routing": [
            {
                "entity_uri": route.entity_uri,
                "probabilistic_matching_owner": route.probabilistic_matching_owner,
                "survivorship_owner": route.survivorship_owner,
                "persistent_enterprise_identity_owner": (
                    route.persistent_enterprise_identity_owner
                ),
                "merge_split_owner": route.merge_split_owner,
            }
            for route in shaped.policy.mdm_routing
        ],
        "runtime_semantics": [
            {
                "model_name": model.identity.model_name,
                "rule_id": "DD-109",
                "scd_type": runtime.authority.history.scd_type.value.value,
                "time_basis": (
                    runtime.authority.history.time_basis.value.value
                    if runtime.authority.history.time_basis is not None
                    else "current-state"
                ),
                "merge_identity": list(runtime.authority.incremental.merge_identity.value),
                "cdc_operation": runtime.authority.incremental.cdc_operation.value,
                "source_updated_at": (
                    runtime.authority.incremental.ordering.source_updated_at.value
                ),
                "source_effective_at": (
                    runtime.authority.incremental.ordering.source_effective_at.value
                ),
                "ingested_at": (runtime.authority.incremental.ordering.ingested_at.value),
                "loaded_at": "_loaded_at",
                "total_order": list(runtime.ordering_columns),
                "lookback": {
                    "amount": runtime.authority.incremental.lookback.value.amount,
                    "unit": runtime.authority.incremental.lookback.value.unit.value,
                },
                "hard_delete": (runtime.authority.incremental.hard_delete.value.value),
                "soft_delete": (runtime.authority.incremental.soft_delete.value.value),
                "delete_semantics": {
                    "captured_cdc_delete": "hard-delete",
                    "hard_delete_disposition": (
                        runtime.authority.incremental.hard_delete.value.value
                    ),
                    "soft_delete_signal": "normalized-operation:soft-delete",
                    "soft_delete_disposition": (
                        "tombstone"
                        if runtime.authority.incremental.soft_delete.value.value
                        == "apply-operation"
                        else runtime.authority.incremental.soft_delete.value.value
                    ),
                    "snapshot_absence_detection": "unsupported-fail-closed",
                },
                "late_arrival": (runtime.authority.incremental.late_arrival.value.value),
                "correction": (runtime.authority.incremental.correction.value.value),
                "replay": runtime.authority.incremental.replay.value.value,
                "backfill": runtime.authority.incremental.backfill.value.value,
                "schema_evolution": (
                    runtime.authority.incremental.schema_evolution.action.value.value
                ),
                "hash": (
                    {
                        "contract_version": (
                            runtime.authority.canonical_hash.contract_version.value
                        ),
                        "algorithm": runtime.authority.canonical_hash.algorithm.value,
                        "encoding": runtime.authority.canonical_hash.encoding.value,
                        "null_representation": (
                            runtime.authority.canonical_hash.null_representation.value
                        ),
                        "inputs": [
                            {
                                "property_uri": item.property_uri,
                                "column": item.column_name,
                                "type": item.data_type.kind.value,
                                "precision": item.data_type.precision,
                                "scale": item.data_type.scale,
                                "length": item.data_type.length,
                            }
                            for item in runtime.canonical_hash_columns
                        ],
                        "rule_id": "DD-109-hash",
                        "evidence": [
                            runtime.authority.canonical_hash.resource_uri,
                            runtime.authority.canonical_hash.algorithm.provenance.predicate_uri,
                            *runtime.authority.canonical_hash.algorithm.provenance.evidence,
                        ],
                    }
                    if runtime.authority.canonical_hash is not None
                    else {
                        "strategy": "typed-null-safe-column-compare",
                        "columns": list(runtime.compare_columns),
                        "rule_id": "DD-109-scd",
                    }
                ),
                "evidence": {
                    "policy_resource": runtime.authority.incremental.resource_uri,
                    "merge": [
                        runtime.authority.incremental.merge_identity.provenance.predicate_uri,
                        *runtime.authority.incremental.merge_identity.provenance.evidence,
                    ],
                    "ordering": [
                        (
                            runtime.authority.incremental.ordering.tie_breakers.provenance.predicate_uri
                        ),
                        *runtime.authority.incremental.ordering.tie_breakers.provenance.evidence,
                    ],
                    "time_basis": (
                        [
                            runtime.authority.history.time_basis.provenance.predicate_uri,
                            *runtime.authority.history.time_basis.provenance.evidence,
                        ]
                        if runtime.authority.history.time_basis is not None
                        else []
                    ),
                },
            }
            for model in shaped.silver_models
            if model.kind in {SilverModelKind.ENTITY, SilverModelKind.UNION}
            and (runtime := model.runtime) is not None
        ],
        "fact_runtime_semantics": [
            {
                "resource_uri": table.resource_uri,
                "rule_id": "DD-109-fact-runtime",
                "fact_grain": table.fact_grain.value,
                "fact_type": table.fact_type.value.value,
                "dimension_version_binding": table.version_binding.value.value,
                "incremental_policy_ref": table.incremental_policy_ref,
                "merge_identity": list(runtime.merge_identity.value),
                "cdc_operation": runtime.cdc_operation.value,
                "source_updated_at": runtime.ordering.source_updated_at.value,
                "source_effective_at": runtime.ordering.source_effective_at.value,
                "ingested_at": runtime.ordering.ingested_at.value,
                "total_order": [
                    runtime.ordering.source_effective_at.value,
                    runtime.ordering.source_updated_at.value,
                    runtime.ordering.ingested_at.value,
                    *runtime.ordering.tie_breakers.value,
                ],
                "lookback": {
                    "amount": runtime.lookback.value.amount,
                    "unit": runtime.lookback.value.unit.value,
                },
                "hard_delete": runtime.hard_delete.value.value,
                "soft_delete": runtime.soft_delete.value.value,
                "late_arrival": table.late_arrival.value.value,
                "correction": table.correction.value.value,
                "replay": runtime.replay.value.value,
                "backfill": runtime.backfill.value.value,
                "schema_evolution": runtime.schema_evolution.action.value.value,
                "evidence": [
                    table.resource_uri,
                    runtime.resource_uri,
                    runtime.merge_identity.provenance.predicate_uri,
                ],
            }
            for table in shaped.policy.gold.tables
            if table.role.value.value == "fact"
            and table.fact_grain is not None
            and table.fact_type is not None
            and table.version_binding is not None
            and table.incremental_policy_ref is not None
            and table.correction is not None
            and table.late_arrival is not None
            and (
                runtime := next(
                    (
                        item
                        for item in shaped.policy.incremental
                        if item.resource_uri == table.incremental_policy_ref
                    ),
                    None,
                )
            )
            is not None
        ],
        "temporal_foreign_keys": [
            {
                "model_name": model.identity.model_name,
                "property_uri": relationship.property_uri,
                "mode": relationship.mode.value.value,
                "interval": (
                    relationship.interval.value.value if relationship.interval is not None else None
                ),
                "time_zone": (
                    relationship.time_zone.value if relationship.time_zone is not None else None
                ),
                "precision": (
                    relationship.precision.value if relationship.precision is not None else None
                ),
                "cardinality": relationship.cardinality.value.value,
                "missing_action": relationship.missing_action.value.value,
                "ambiguous_action": relationship.ambiguous_action.value.value,
                "late_parent_action": relationship.late_parent_action.value.value,
                "participates_in_change_detection": (
                    relationship.participates_in_change_detection.value
                ),
                "rule_id": "DD-109-temporal-fk",
                "evidence": [
                    relationship.property_uri,
                    relationship.mode.provenance.predicate_uri,
                    *relationship.mode.provenance.evidence,
                ],
            }
            for model in shaped.silver_models
            if model.kind in {SilverModelKind.ENTITY, SilverModelKind.UNION}
            and model.authority is not None
            for relationship in model.authority.foreign_keys
        ],
        "blocking_reasons": [
            {"rule_id": rule_id, "reason": reason}
            for rule_id, reason in plan.release.blocking_rules
        ],
        "capabilities": [
            {
                "adapter": result.adapter.value,
                "capability": result.capability.value,
                "disposition": result.disposition.value,
                "rule_id": result.rule_id,
                "scope": result.scope,
                "reason": result.message,
                "evidence": list(result.evidence),
                "deviation_ref": result.deviation_ref,
            }
            for result in plan.release.capability_results
        ],
        "mapping_contracts": (
            {
                "version": plan.release.mapping_contract.version,
                "tables": [
                    {
                        "resource_uri": item.resource_uri,
                        "source_table_uri": item.source_table_uri,
                        "target_class_uri": item.target_class_uri,
                        "mapping_type": item.mapping_type,
                        "match_type": item.match_type,
                        "route": item.route.value,
                        "contract_name": item.contract_name,
                        "row_filter": (
                            _mapping_expression_data(item.row_filter)
                            if item.row_filter is not None
                            else None
                        ),
                    }
                    for item in plan.release.mapping_contract.tables
                ],
                "columns": [
                    {
                        "resource_uri": item.resource_uri,
                        "source_column_uri": item.source_column_uri,
                        "target_property_uri": item.target_property_uri,
                        "target_column_name": item.target_column_name,
                        "target_data_type": _type_data(item.target_data_type),
                        "match_type": item.match_type,
                        "route": item.route.value,
                        "contract_name": item.contract_name,
                        "expression": _mapping_expression_data(item.expression),
                    }
                    for item in plan.release.mapping_contract.columns
                ],
                "transformation_authorities": [
                    {
                        "name": item.name,
                        "target_class_uri": item.target_class_uri,
                        "virtual_source_iri": item.virtual_source_iri,
                        "replaces_source_iris": list(item.replaces_source_iris),
                        "supported_adapters": list(item.supported_adapters),
                        "grain_key": list(item.grain_key),
                        "decision_statuses": list(item.decision_statuses),
                        "evidence_artifacts": list(item.evidence_artifacts),
                        "verified_tests": list(item.verified_tests),
                        "approved": item.approved,
                    }
                    for item in plan.release.mapping_contract.transformation_authorities
                ],
            }
            if plan.release.mapping_contract is not None
            else {
                "version": "2.0",
                "tables": [],
                "columns": [],
                "transformation_authorities": [],
            }
        ),
        "mapping_capabilities": [
            {
                "mapping_resource_uri": item.mapping_resource_uri,
                "adapter": item.adapter,
                "capability": item.capability.value,
                "supported": item.supported,
                "rule_id": item.rule_id,
                "reason": item.reason,
            }
            for item in plan.release.mapping_capability_results
        ],
    }
    macro_root = Path(plan.adapter.template_root) / "macros"
    for name in shaped.macros.names:
        artifacts[f"macros/{name}"] = (macro_root / name).read_text(encoding="utf-8")

    expected_paths = {source.artifact_path for source in shaped.source_catalogs}
    expected_paths.update(document.artifact_path for document in shaped.schema_documents)
    if plan.silver is not None and plan.silver.models:
        expected_paths.update(
            {
                plan.silver.ddl_artifact_path,
                plan.silver.constraint_artifact_path,
                plan.silver.erd_artifact_path,
                plan.silver.parity_artifact_path,
            }
        )
    expected_paths.update(f"macros/{name}" for name in shaped.macros.names)
    expected_paths.add("contracts/dq-runtime-result-contract.schema.json")
    if plan.project.emit:
        expected_paths.update({"README.md", "dbt_project.yml", "packages.yml"})
    quality_paths: set[str] = set()
    for quality in plan.quality_models:
        if quality.quarantines_rows:
            quality_paths.update(
                {
                    quality.original_artifact_path,
                    quality.evaluated_artifact_path,
                    quality.quarantine_artifact_path,
                }
            )
        for rule in quality.rules:
            quality_paths.update({rule.result_artifact_path, rule.test_artifact_path})
    expected_paths.update(quality_paths)
    quality_models = {item.model_name: item for item in plan.quality_models}
    for model in shaped.silver_models:
        if model.identity.artifact_path is None:
            continue
        quality = quality_models.get(model.identity.model_name)
        if quality is None or not quality.quarantines_rows:
            expected_paths.add(model.identity.artifact_path)
    if shaped.gold_product is not None and plan.gold is not None:
        expected_paths.add(plan.gold.dbt_schema_artifact_path)
        for table in plan.gold.tables:
            expected_paths.add(f"models/gold/{shaped.gold_product.ontology_name}/{table.name}.sql")
            if table.dual_current_name:
                expected_paths.add(
                    f"models/gold/{shaped.gold_product.ontology_name}/{table.dual_current_name}.sql"
                )
        if shaped.gold_product.calendar is not None and shaped.gold_product.calendar.approved:
            expected_paths.update(
                {
                    "models/gold/shared/dim_date.sql",
                    "models/gold/shared/_shared__gold_models.yml",
                }
            )
    expected_paths.update(
        lookup.quarantine_artifact_path
        for model in plan.models
        if model.runtime is not None
        for lookup in model.runtime.temporal_lookups
        if lookup.quarantine_artifact_path
    )
    missing_artifacts = sorted(path for path in expected_paths if path not in artifacts)
    release_data = artifacts["__release_data__"]
    tangible_artifacts = {
        path: content for path, content in artifacts.items() if not path.startswith("__")
    }
    release_data["artifact_completeness"] = {
        "status": "blocking" if missing_artifacts else "ready",
        "expected_count": len(expected_paths),
        "generated_count": len(tangible_artifacts),
        "missing": missing_artifacts,
    }
    release_data["generated_artifacts"] = [
        {
            "path": path,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }
        for path, content in sorted(tangible_artifacts.items())
    ]
    release_data["review_disposition"] = (
        "blocking" if release_data["blocking_reasons"] or missing_artifacts else "supported"
    )
    artifacts[f"metadata/{plan.release.ontology_name}-release-review.json"] = (
        json.dumps(release_data, indent=2, sort_keys=True) + "\n"
    )

    _validate_dbt_artifacts(
        artifacts,
        known_models=set(plan.release.known_models),
    )
    return artifacts


def _validate_dbt_artifacts(
    artifacts: dict[str, str],
    *,
    known_models: set[str] | None = None,
) -> None:
    model_names = _extract_model_names(artifacts) | (known_models or set())
    known_refs = model_names | _collect_join_ref_targets(artifacts)
    for path, content in artifacts.items():
        if path.endswith(".sql"):
            _check_jinja_syntax(path, content)
            _check_refs(path, content, known_refs)


def _extract_model_names(artifacts: dict[str, str]) -> set[str]:
    return {
        path.rsplit("/", 1)[-1].removesuffix(".sql") for path in artifacts if path.endswith(".sql")
    }


_JOIN_REF_PATTERN = re.compile(
    r"""join\s+\{?\{?\s*ref\(\s*['"]([^'"]+)['"]\s*\)""",
    re.I,
)


def _collect_join_ref_targets(artifacts: dict[str, str]) -> set[str]:
    return {
        match.group(1)
        for path, content in artifacts.items()
        if path.endswith(".sql")
        for match in _JOIN_REF_PATTERN.finditer(content)
    }


def _check_jinja_syntax(path: str, content: str) -> None:
    if "{% test " in content:
        return
    try:
        _SYNTAX_CHECK_ENV.parse(content)
    except TemplateSyntaxError as exc:
        logger.warning(
            "dbt validation: Jinja syntax error in %s line %s: %s",
            path,
            exc.lineno,
            exc.message,
        )


_REF_PATTERN = re.compile(r"""\bref\(\s*['"]([^'"]+)['"]\s*\)""")


def _check_refs(path: str, content: str, model_names: set[str]) -> None:
    model_name = path.rsplit("/", 1)[-1].removesuffix(".sql")
    for match in _REF_PATTERN.finditer(content):
        target = match.group(1)
        if target == model_name:
            logger.warning(
                "dbt validation: self-referential ref('%s') in %s",
                target,
                path,
            )
        elif target not in model_names:
            logger.warning(
                "dbt validation: ref('%s') in %s does not match any generated model",
                target,
                path,
            )
