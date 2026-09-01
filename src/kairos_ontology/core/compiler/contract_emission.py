# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Contract-driven emission for governed classes (DD-213 §4).

The invariant this module exists to hold:

    the emitted column set of a governed class is a pure function of its contract --
    independent of how many bindings exist, and independent of their filenames.

That last clause is not decoration. The conformance union is built as
``replace(base_model, columns=...)`` where ``base_model`` is
``conformance_bases.setdefault(target_class, model)`` -- the *first binding in path-sorted
order* (``kernel.py``). Today that is harmless only because
``conformance.property-incompatible`` forces every binding in a group to declare an
identical property set. Relaxing that (slice 4) without this module would make the union's
columns depend on a filename, and a ``union all`` across branches with differing column
counts is invalid SQL.

The fix is deliberately *upstream* of the union rather than a rewrite of it. Every governed
binding is expanded, before adaptation, to the contract's full property list in the
contract's declared order, with a typed ``NULL`` padding each property this source does not
supply. Every branch in a group then has identical columns in an identical order, so
``base_model`` is invariant no matter which binding sorts first -- the ordering bug
dissolves instead of being papered over, and the whole downstream pipeline (normalize,
shape, materialize, render) keeps treating these as ordinary mapped columns with no
special-casing anywhere.
"""

from __future__ import annotations

from dataclasses import replace

from .adapter import ResolutionContext
from .bindings import EntityBinding, ExprNull, FieldMapping
from .contracts import ContractEntity, SilverContract, resolved_column_name


def padded_properties(
    binding: EntityBinding, entity: ContractEntity, context: ResolutionContext | None = None
) -> tuple[str, ...]:
    """Return the contract properties this binding does not map, in declared order.

    Only *optional* properties are padded. Padding a required one would hide the very
    violation ``contract.required-property-unmapped`` exists to surface -- the binding would
    quietly emit NULLs for a column every source is supposed to supply.

    A property that does not resolve in the ontology closure is skipped too: that is a
    contract error (``contract.property-unresolved``), and synthesizing a field for it would
    launder it into a far more confusing ``safety.property-unresolved`` against a binding
    whose author never wrote that field.
    """
    mapped = {field.property for field in binding.fields}
    return tuple(
        item.property
        for item in entity.properties
        if item.property not in mapped
        and not item.required
        and (context is None or context.property(item.property) is not None)
    )


def expand_binding(
    binding: EntityBinding, entity: ContractEntity, context: ResolutionContext | None = None
) -> EntityBinding:
    """Return *binding* with its fields completed and reordered to the contract.

    Mapped fields keep their authored expressions; unmapped contract properties are padded
    with an explicit ``NULL``. Fields the contract does not declare are preserved and appended
    afterwards -- rejecting them is Gate A's job (``contract.property-not-declared`` on a
    closed entity), and silently dropping one here would change the emit on the strength of a
    rule the author may have deliberately left open.
    """
    by_property = {field.property: field for field in binding.fields}
    paddable = set(padded_properties(binding, entity, context))
    ordered: list[FieldMapping] = []
    for item in entity.properties:
        existing = by_property.get(item.property)
        if existing is not None:
            ordered.append(existing)
        elif item.property in paddable:
            ordered.append(
                FieldMapping(
                    property=item.property,
                    expression=ExprNull(pointer=f"{item.pointer}/padded"),
                    pointer=f"{item.pointer}/padded",
                )
            )
    declared = {item.property for item in entity.properties}
    ordered.extend(field for field in binding.fields if field.property not in declared)
    return replace(binding, fields=tuple(ordered))


def apply_column_names(
    context: ResolutionContext, contract: SilverContract
) -> ResolutionContext:
    """Return *context* with contract-pinned column names applied.

    This is what decouples an ontology rename from a physical rename: the emitted column
    name is the contract's ``columnName`` rather than ``camel_to_snake`` of the property's
    local name, restoring inside a governed artifact the intent of the v4-only
    ``kairos-ext:silverColumnName``.

    A property left unpinned keeps the kernel default, so an unpinned contract emits
    byte-identically to no contract at all.
    """
    pinned: dict[str, str] = {}
    for entity in contract.entities:
        for item in entity.properties:
            if item.column_name:
                pinned[item.property] = item.column_name
    if not pinned:
        return context
    properties = tuple(
        replace(item, column_name=pinned[item.ref]) if item.ref in pinned else item
        for item in context.properties
    )
    return replace(context, properties=properties)


def mark_padded_columns(bound, padded_columns: frozenset[str]):
    """Exclude padded columns from SCD2 change detection.

    ``ColumnSpec.include_in_change_detection`` defaults to ``True``. A padded NULL that
    joined the canonical hash would re-version the *entire* entity the day its source began
    supplying the column -- every row's hash changing at once, for no business change.
    """
    if not padded_columns:
        return bound
    candidates = tuple(
        replace(
            model,
            columns=tuple(
                replace(column, include_in_change_detection=False)
                if column.name in padded_columns
                else column
                for column in model.columns
            ),
        )
        for model in bound.silver_candidates
    )
    return replace(bound, silver_candidates=candidates)


def padded_column_names(
    binding: EntityBinding, entity: ContractEntity, context: ResolutionContext
) -> frozenset[str]:
    """Return the emitted column names this binding pads with NULL."""
    names: set[str] = set()
    for qname in padded_properties(binding, entity, context):
        item = entity.property_for(qname)
        if item is None:
            continue
        if item.column_name:
            names.add(item.column_name)
            continue
        resolved = context.property(qname)
        names.add(resolved.column_name if resolved is not None else resolved_column_name(item))
    return frozenset(names)
