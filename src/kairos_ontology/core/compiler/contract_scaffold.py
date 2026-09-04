# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Generate a declared Silver contract from a resolved CompilePlan (DD-213 §6).

This is the adoption path: the generated document records *what is* -- the exact model
names, column names, order, canonical types, and nullability the compiler already emits --
so adopting it is a provable no-op. The reviewed edit that follows records *what is
promised* (marking properties optional, setting stability, pinning names).

Emission order is authoritative and deliberate: mapped ``fields:`` first, then
``technicalFields:`` (DD-139). That mirrors ``adapter.py`` (semantic columns, then
technical).

A column is claimed by **what declared it**, never by name or position:
``SilverModelSpec.columns`` interleaves a generated ``<model>_sk`` surrogate key and the
``_source_identity_ref``/``_loaded_at`` envelope with the author-declared columns. Role
alone is not sufficient either -- see :func:`_partition`, where an authored
``technicalFields:`` entry that a relationship joins on carries ``role=foreign-key`` and
must still be claimed as technical (#697).

Relationships are declared as ``(property, target)`` with no ``columnName``: every
emitted relationship column is compiler-owned and carries a reserved name that DD-213 §3
puts outside the contract's ``closed`` scope.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from ..projections.dbt.policy_specs import SilverColumnRole
from ..projections.dbt.silver_contract import canonical_type_label
from ..projections.dbt.specs import ColumnSpec, SilverModelKind, SilverModelSpec
from .bindings import EntityBinding
from .contract_conformance import models_by_class
from .contracts import RESERVED_COLUMN_PREFIX, RESERVED_COLUMN_SUFFIX
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


def _column_type(column: ColumnSpec) -> str:
    """Return the adapter-neutral contract type label for one emitted column."""
    if column.canonical_type is not None:
        return canonical_type_label(column.canonical_type)
    return column.data_type or "string"


def _is_authored_foreign_key(column: ColumnSpec) -> bool:
    """True when a ``role=foreign-key`` column was declared by the author, not generated.

    The role is stamped onto whatever ``relationships[].join.local`` names, which may be
    a mapped ``fields:`` entry whose emitted name happens to equal the source column.
    Such a column is an ordinary semantic property that also happens to carry a join.

    The discriminator is DD-213 §3's own reserved-name definition: every *generated*
    relationship column is reserved -- the parent's ``<parent>_sk`` join key and the
    ``_kairos_fk_*_match_count`` DQ column -- and a contract that declares a reserved
    name is rejected. So a non-reserved foreign-key column can only have come from the
    author.
    """
    if column.role != SilverColumnRole.FOREIGN_KEY.value:
        return False
    name = column.name
    return not (
        name.startswith(RESERVED_COLUMN_PREFIX) or name.casefold().endswith(RESERVED_COLUMN_SUFFIX)
    )


def _partition(model: SilverModelSpec, binding: EntityBinding) -> _EntityColumns:
    """Split emitted columns into the two groups an author actually declared.

    Partitioning is by **what declared the column**, not by ``role`` alone. The authored
    ``technicalFields:`` names are therefore tested *first* (#697): the kernel stamps
    ``role=foreign-key`` on whatever ``relationships[].join.local`` names
    (``policy_normalize._column_role`` against ``ForeignKeyAuthoringFact.silver_column_name``),
    and for the DD-139 shape that names an authored technical field. Testing ``role``
    first classified that column as compiler-owned plumbing, so it never reached
    ``technicalColumns:`` and ``contract.technical-field-not-declared`` fired the moment
    the generated contract was adopted -- while ``_key_columns`` below also stopped
    resolving a grain stated on it, refusing to scaffold the domain at all.

    Everything still unclaimed after the two authored groups is compiler-owned and is
    dropped: the ``<model>_sk`` surrogate, the parent's ``<parent>_sk`` join key, the
    ``_kairos_fk_*_match_count`` DQ column, the entity IRI, and the DD-104 audit
    envelope. All of those carry a reserved name (``_`` prefix or ``_sk`` suffix) that
    DD-213 §3 places outside the contract's ``closed`` scope and that
    ``contract.column-name-collision`` rejects outright, so none of them can be declared.

    The mapped ``fields:`` set must still line up 1:1 with the binding, in order -- if it
    does not, the plan lacks the shape this scaffolder assumes and we refuse rather than
    emit a contract that would silently change the emit.
    """
    technical_names = {item.name for item in binding.technical_fields}
    semantic: list[ColumnSpec] = []
    technical: list[ColumnSpec] = []
    for column in model.columns:
        if column.name in technical_names:
            technical.append(column)
        elif column.role in _AUTHORED_ROLES or _is_authored_foreign_key(column):
            semantic.append(column)
    if len(semantic) != len(binding.fields):
        raise ContractScaffoldError(
            f"model '{model.identity.model_name}' emits {len(semantic)} mapped columns but "
            f"binding '{binding.name}' declares {len(binding.fields)} fields"
        )
    return _EntityColumns(tuple(semantic), tuple(technical))


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

        # Declared as (property, target) only -- exactly the pair
        # `contract.relationship-not-declared` matches on, taken from the binding so the
        # authored spelling agrees by construction.
        #
        # No `columnName` (#697). This used to positionally `zip` the authored
        # relationships against every `role=foreign-key` column, which pinned the wrong
        # name in both shapes a real hub produces: the DD-139 technical column (already
        # declared under `technicalColumns:`, so pinning it here collided with itself),
        # or -- with no technical field at all -- the compiler-generated `<parent>_sk`,
        # whose reserved suffix `contract.column-name-collision` rejects outright. Either
        # way the generated contract failed on adoption, contradicting the no-op
        # guarantee this module's header states.
        #
        # Nothing is lost by omitting it: `apply_contract_column_names`
        # (`contract_emission.py`) pins **properties** only, so a relationship
        # `columnName` never reached emission and governed nothing. Parent renames are
        # handled the way DD-213 §3 settles them -- `BuildScope` resolves the foreign
        # domain's contract and the parent's declared `modelName` is authoritative --
        # not by pinning a reserved name in the child.
        relationships = [
            {"property": relationship.property, "target": relationship.target}
            for relationship in binding.relationships
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
    expression is exactly that source column (its emitted name often differs -- a client hub
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
