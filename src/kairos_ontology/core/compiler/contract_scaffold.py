# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Generate a declared Silver contract from a resolved CompilePlan (DD-213 §6).

This is the adoption path: the generated document records *what is* -- the exact model
names, column names, order, canonical types, and nullability the compiler already emits --
so adopting it is a provable no-op. The reviewed edit that follows records *what is
promised* (marking properties optional, setting stability, pinning names).

Emission order is authoritative and deliberate: mapped ``fields:`` first, then
``technicalFields:`` (DD-139), then relationship foreign keys. That mirrors
``adapter.py`` (semantic columns, then technical) and ``kernel.py`` (foreign keys appended
last). Compiler-owned columns are filtered out by ``SilverColumnRole``, not by name or
position: ``SilverModelSpec.columns`` interleaves a generated ``<model>_sk`` surrogate key and
the ``_source_identity_ref``/``_loaded_at`` envelope with the author-declared columns.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from ..projections.dbt.policy_specs import SilverColumnRole
from ..projections.dbt.silver_contract import canonical_type_label
from ..projections.dbt.specs import ColumnSpec, SilverModelKind, SilverModelSpec
from .bindings import EntityBinding
from .contract_conformance import models_by_class
from .plan import CompilePlan

#: Model kinds that carry the consumer-facing contract. A ``SOURCE_BRANCH`` is an internal
#: implementation detail of a conformance group -- the union above it is what downstream
#: consumers read, so the contract is scaffolded from the union, never from a branch.
_CONTRACT_MODEL_KINDS = frozenset({SilverModelKind.ENTITY, SilverModelKind.UNION})

#: Column roles an author declares, and which the contract therefore governs. Everything
#: else in ``SilverModelSpec.columns`` is compiler-owned -- generated keys, the entity IRI,
#: and the DD-104 audit/source-identity envelope -- emitted unconditionally and outside the
#: ``closed`` scope (DD-213 §3).
_AUTHORED_ROLES = frozenset(
    {SilverColumnRole.BUSINESS.value, SilverColumnRole.BUSINESS_NATURAL_KEY.value}
)


class ContractScaffoldError(RuntimeError):
    """Raised when a plan cannot be projected to a contract without guessing."""


@dataclass(frozen=True, slots=True)
class _EntityColumns:
    """One entity's emitted columns, partitioned by what declared them."""

    semantic: tuple[ColumnSpec, ...]
    technical: tuple[ColumnSpec, ...]
    foreign_keys: tuple[ColumnSpec, ...]


def _column_type(column: ColumnSpec) -> str:
    """Return the adapter-neutral contract type label for one emitted column."""
    if column.canonical_type is not None:
        return canonical_type_label(column.canonical_type)
    return column.data_type or "string"


def _partition(model: SilverModelSpec, binding: EntityBinding) -> _EntityColumns:
    """Split emitted columns into semantic, technical, and foreign-key groups.

    Foreign keys are identified by ``role``, which the kernel sets explicitly; technical
    columns by the authored ``technicalFields:`` names. Everything else is a mapped
    ``fields:`` entry and must line up 1:1 with the binding, in order -- if it does not,
    the plan does not have the shape this scaffolder assumes and we refuse rather than
    emit a contract that would silently change the emit.
    """
    technical_names = {item.name for item in binding.technical_fields}
    semantic: list[ColumnSpec] = []
    technical: list[ColumnSpec] = []
    foreign_keys: list[ColumnSpec] = []
    for column in model.columns:
        if column.role == SilverColumnRole.FOREIGN_KEY.value:
            foreign_keys.append(column)
        elif column.role not in _AUTHORED_ROLES:
            # Compiler-owned: surrogate/integration keys, entity IRI, audit envelope.
            continue
        elif column.name in technical_names:
            technical.append(column)
        else:
            semantic.append(column)
    if len(semantic) != len(binding.fields):
        raise ContractScaffoldError(
            f"model '{model.identity.model_name}' emits {len(semantic)} mapped columns but "
            f"binding '{binding.name}' declares {len(binding.fields)} fields"
        )
    return _EntityColumns(tuple(semantic), tuple(technical), tuple(foreign_keys))


def _models_by_class(plan: CompilePlan) -> dict[str, SilverModelSpec]:
    shaped = plan.shaped_project
    if shaped is None:
        raise ContractScaffoldError("compile plan produced no shaped project")
    return models_by_class(shaped.silver_models)


def build_contract_document(plan: CompilePlan) -> dict:
    """Return the contract document for every governed class in one compile plan."""
    models = _models_by_class(plan)
    context = plan.resolution
    entities: list[dict] = []
    seen: set[str] = set()
    for binding in sorted(plan.bindings, key=lambda item: (item.target_class, item.name)):
        if binding.target_class in seen:
            # Conformance peers share one contract entity; the first binding in canonical
            # order supplies it, and Gate A then holds every peer to it.
            continue
        resolved_class = context.klass(binding.target_class)
        if resolved_class is None:
            raise ContractScaffoldError(
                f"binding '{binding.name}' target class '{binding.target_class}' did not resolve"
            )
        model = models.get(resolved_class.uri)
        if model is None:
            raise ContractScaffoldError(
                f"no Silver model was planned for class '{binding.target_class}'"
            )
        seen.add(binding.target_class)
        columns = _partition(model, binding)

        properties: list[dict] = []
        for field, column in zip(binding.fields, columns.semantic, strict=True):
            entry: dict = {
                "property": field.property,
                "columnName": column.name,
                "type": _column_type(column),
                # Everything the plan already emits is supplied by every binding in the
                # group today, so `required` is the accurate record of what *is*. Relaxing
                # a property to `optional` is the reviewed edit that follows adoption.
                "requirement": "required",
                "nullable": bool(column.nullable),
            }
            properties.append(entry)

        technical_columns = [
            {
                "name": column.name,
                "type": _column_type(column),
                "requirement": "required",
                "nullable": bool(column.nullable),
            }
            for column in columns.technical
        ]

        relationships = [
            {
                "property": relationship.property,
                "target": relationship.target,
                # Pinned, not defaulted: the default embeds the *parent's* model name, so
                # an unpinned child column would rename whenever a parent's `modelName`
                # changed. Recording it here makes the child's contract self-contained.
                "columnName": column.name,
            }
            for relationship, column in zip(
                binding.relationships, columns.foreign_keys, strict=False
            )
        ]

        grain_columns = _key_columns(binding, binding.grain.columns, columns)
        if not grain_columns:
            raise ContractScaffoldError(
                f"binding '{binding.name}' declares no grain column that maps to an emitted "
                "column; a contract grain must name emitted columns"
            )
        entity: dict = {
            "class": binding.target_class,
            "modelName": model.identity.model_name,
            "stability": "preview",
            "closed": True,
            "grain": {"columns": grain_columns},
            "identity": {"strategy": binding.identity.strategy},
            "properties": properties,
        }
        business_key = _key_columns(binding, binding.identity.business_key, columns)
        if business_key:
            entity["identity"]["businessKey"] = business_key
        if technical_columns:
            entity["technicalColumns"] = technical_columns
        if relationships:
            entity["relationships"] = relationships
        entities.append(entity)

    if not entities:
        raise ContractScaffoldError(
            f"domain '{plan.domain}' has no bindings to scaffold a contract from"
        )
    return {
        "apiVersion": "kairos.eu/v5",
        "kind": "SilverContract",
        "metadata": {"domain": plan.domain},
        "entities": entities,
    }


def _key_columns(
    binding: EntityBinding, source_columns: tuple[str, ...], columns: _EntityColumns
) -> list[str]:
    """Map authored SOURCE key columns to the EMITTED column names carrying them.

    Three routes, because real bindings use all three: a semantic ``fields:`` entry whose
    expression is exactly that source column; a DD-139 ``technicalFields:`` entry whose
    expression is exactly that source column (its emitted name often differs -- fracht
    grains on ``BL_PK`` through a technical column named ``source_record_id``); or a
    technical entry whose name simply equals the source column.
    """
    semantic = list(zip(binding.fields, columns.semantic, strict=False))
    technical_names = {column.name for column in columns.technical}
    result: list[str] = []
    for source_column in source_columns:
        emitted: str | None = None
        for field, column in semantic:
            if getattr(field.expression, "column", None) == source_column:
                emitted = column.name
                break
        if emitted is None:
            for item in binding.technical_fields:
                if (
                    getattr(item.expression, "column", None) == source_column
                    and item.name in technical_names
                ):
                    emitted = item.name
                    break
        if emitted is None and source_column in technical_names:
            emitted = source_column
        if emitted is not None and emitted not in result:
            result.append(emitted)
    return result




CONTRACT_HEADER = """# Declared Silver contract (DD-213).
#
# Generated by `kairos-ontology scaffold-contract` from the current compile plan: it
# records what the compiler emits today, so adopting it is a no-op. Now record what Silver
# *promises*: relax properties a future source may not supply to `requirement: optional`
# (which requires `nullable: true`), set `stability` to `stable` once the shape is agreed,
# and pin `columnName` wherever an ontology rename is anticipated.
"""


def render_contract_yaml(document: dict) -> str:
    """Serialize a contract document deterministically, preserving declared order."""
    body = yaml.safe_dump(document, sort_keys=False, default_flow_style=False, width=100)
    return CONTRACT_HEADER + body
