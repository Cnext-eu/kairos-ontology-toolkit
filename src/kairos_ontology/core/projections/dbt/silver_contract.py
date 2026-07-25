# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic serialization for the shared DD-110 Silver authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from .policy_specs import CanonicalTypeKind, CanonicalTypeSpec
from .specs import SilverModelSpec


def canonical_type_label(value: CanonicalTypeSpec) -> str:
    """Return the stable adapter-neutral label for a canonical type."""
    if value.kind is CanonicalTypeKind.DECIMAL:
        return f"decimal({value.precision or 18},{value.scale or 4})"
    if value.kind is CanonicalTypeKind.STRING and value.length:
        return f"string({value.length})"
    return value.kind.value


def canonical_data(value: object) -> Any:
    """Convert a deeply immutable typed contract to deterministic JSON data."""
    if is_dataclass(value):
        return {
            field.name: canonical_data(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [canonical_data(item) for item in value]
    if isinstance(value, frozenset):
        items = [canonical_data(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    if isinstance(value, dict):
        return {
            str(key): canonical_data(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    return value


def canonical_json(value: object) -> str:
    """Serialize a typed value without platform-dependent whitespace."""
    return json.dumps(
        canonical_data(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def silver_model_fingerprint(model: SilverModelSpec) -> str:
    """Hash every logical field of one Silver model specification."""
    return hashlib.sha256(canonical_json(model).encode("utf-8")).hexdigest()


def silver_column_marker(model: SilverModelSpec) -> str:
    """Return the exact ordered-column marker embedded in SQL and DDL."""
    return json.dumps(
        [column.name for column in model.columns],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def silver_parity_fields(model: SilverModelSpec) -> tuple[tuple[str, str], ...]:
    """Hash every logical field without duplicating nested policy in the manifest."""
    result: list[tuple[str, str]] = []

    def append(path: str, value: object) -> None:
        result.append(
            (
                path,
                hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest(),
            )
        )

    for field in fields(model):
        value = getattr(model, field.name)
        if field.name == "columns":
            for index, column in enumerate(value):
                for column_field in fields(column):
                    append(
                        f"columns.{index}.{column_field.name}",
                        getattr(column, column_field.name),
                    )
        elif field.name in {"sources", "joins", "unique_keys", "foreign_keys"}:
            if not value:
                append(field.name, ())
            for index, item in enumerate(value):
                for item_field in fields(item):
                    append(
                        f"{field.name}.{index}.{item_field.name}",
                        getattr(item, item_field.name),
                    )
        elif is_dataclass(value) and field.name != "authority":
            for item_field in fields(value):
                append(
                    f"{field.name}.{item_field.name}",
                    getattr(value, item_field.name),
                )
        else:
            append(field.name, value)
    return tuple(result)
