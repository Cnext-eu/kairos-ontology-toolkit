# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""v5 SilverContract YAML schema model, loader, and contract-load rules (DD-213).

This module owns the *document* contract for a declared Silver contract:

* a duplicate-key-rejecting YAML loader that preserves source locations;
* JSON-Schema validation of the document shape (``schema/silver-contract.schema.json``);
* frozen dataclasses mirroring the closed schema; and
* the DD-213 §4 contract-load rules that need no ontology resolution.

It deliberately does **not** resolve properties or classes against an ontology closure --
that needs the DD-103 semantic index and belongs to the kernel, which reports
``contract.property-unresolved``/``contract.class-unresolved`` from resolved symbols.

The contract is an *interface declaration*: what Silver promises to expose. It is authored
input, never derived history, so ``compile --check`` stays stateless (DD-213 §2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Any

import yaml
from jsonschema import Draft7Validator

from ..projections.uri_utils import camel_to_snake
from .bindings import _MarkResolver, _collect_duplicate_key_diagnostics
from .result import CompileDiagnostic, CompileError, SourceLocation

_SCHEMA_RESOURCE = "silver-contract.schema.json"

#: Column-name prefix reserved for the DD-104 audit envelope. A contract may never declare
#: one: envelope columns are emitted unconditionally and sit outside the ``closed`` scope
#: (DD-213 §3).
RESERVED_COLUMN_PREFIX = "_"

#: Suffix of the compiler-generated surrogate join key, which is emitted as
#: ``<model_name>_sk`` and so carries no leading underscore. The exact name depends on the
#: entity model name and is checked against the plan in the kernel; this static rule catches
#: the shape before resolution.
RESERVED_COLUMN_SUFFIX = "_sk"


@dataclass(frozen=True, slots=True)
class DeprecationSpec:
    """Declared deprecation window for one contract column.

    Version values are validated for *shape* only. They are never compared against release
    history -- that would make ``compile --check`` stateful (DD-213 §4).
    """

    since: str
    remove_in: str
    replaced_by: str = ""


@dataclass(frozen=True, slots=True)
class ContractProperty:
    """One declared ontology-backed Silver column."""

    property: str
    type: str
    requirement: str
    nullable: bool
    column_name: str = ""
    deprecated: DeprecationSpec | None = None
    pointer: str = ""

    @property
    def required(self) -> bool:
        """Return whether every binding for this entity must map this property."""
        return self.requirement == "required"


@dataclass(frozen=True, slots=True)
class ContractTechnicalColumn:
    """One declared DD-139 technical passthrough column."""

    name: str
    type: str
    requirement: str
    nullable: bool
    deprecated: DeprecationSpec | None = None
    pointer: str = ""

    @property
    def required(self) -> bool:
        """Return whether every binding for this entity must supply this column."""
        return self.requirement == "required"


@dataclass(frozen=True, slots=True)
class ContractRelationship:
    """One declared relationship whose FK column is part of the contract."""

    property: str
    target: str
    column_name: str = ""
    pointer: str = ""


@dataclass(frozen=True, slots=True)
class ContractIdentity:
    """The entity-level identity contract every binding must match."""

    strategy: str
    business_key: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContractEntity:
    """One canonical entity declared Silver interface."""

    target_class: str
    stability: str
    closed: bool
    grain: tuple[str, ...]
    identity: ContractIdentity
    properties: tuple[ContractProperty, ...]
    technical_columns: tuple[ContractTechnicalColumn, ...] = ()
    relationships: tuple[ContractRelationship, ...] = ()
    model_name: str = ""
    pointer: str = ""

    def property_for(self, qname: str) -> ContractProperty | None:
        """Return the declared property with this authored token, if any."""
        for item in self.properties:
            if item.property == qname:
                return item
        return None

    @property
    def required_properties(self) -> tuple[ContractProperty, ...]:
        """Return the properties every conforming binding must map."""
        return tuple(item for item in self.properties if item.required)

    @property
    def optional_properties(self) -> tuple[ContractProperty, ...]:
        """Return the properties a binding may leave unmapped, if declared so."""
        return tuple(item for item in self.properties if not item.required)


@dataclass(frozen=True, slots=True)
class SilverContract:
    """A fully parsed, closed v5 SilverContract document for one domain."""

    api_version: str
    domain: str
    entities: tuple[ContractEntity, ...]
    source_path: str = ""

    def entity_for(self, target_class: str) -> ContractEntity | None:
        """Return the declared entity for this authored class token, if any."""
        for entity in self.entities:
            if entity.target_class == target_class:
                return entity
        return None


def _load_schema() -> dict:
    text = (
        resources.files(__package__)
        .joinpath("schema")
        .joinpath(_SCHEMA_RESOURCE)
        .read_text(encoding="utf-8")
    )
    return json.loads(text)


def _schema_diagnostics(data: Any, resolver: _MarkResolver) -> list[CompileDiagnostic]:
    """Return source-located ``contract.schema`` diagnostics in deterministic order."""
    validator = Draft7Validator(_load_schema())
    diagnostics: list[CompileDiagnostic] = []
    errors = sorted(
        validator.iter_errors(data),
        key=lambda error: ([str(part) for part in error.absolute_path], error.message),
    )
    for error in errors:
        parts = list(error.absolute_path)
        pointer = "/" + "/".join(str(part) for part in parts)
        location = resolver.at(pointer)
        trim = len(parts)
        while location.line == 0 and trim > 0:
            trim -= 1
            location = resolver.at("/" + "/".join(str(part) for part in parts[:trim]))
        diagnostics.append(
            CompileDiagnostic(
                code="contract.schema",
                message=error.message,
                location=location,
            )
        )
    return diagnostics


def _deprecation(raw: Any) -> DeprecationSpec | None:
    if not isinstance(raw, dict):
        return None
    deprecated = raw.get("deprecated")
    if not isinstance(deprecated, dict):
        return None
    return DeprecationSpec(
        since=str(deprecated["since"]),
        remove_in=str(deprecated["removeIn"]),
        replaced_by=str(deprecated.get("replacedBy", "")),
    )


def _build_entity(raw: dict, index: int) -> ContractEntity:
    pointer = f"/entities/{index}"
    identity_raw = raw["identity"]
    properties = tuple(
        ContractProperty(
            property=str(item["property"]),
            type=str(item["type"]),
            requirement=str(item["requirement"]),
            nullable=bool(item["nullable"]),
            column_name=str(item.get("columnName", "")),
            deprecated=_deprecation(item.get("lifecycle")),
            pointer=f"{pointer}/properties/{position}",
        )
        for position, item in enumerate(raw["properties"])
    )
    technical_columns = tuple(
        ContractTechnicalColumn(
            name=str(item["name"]),
            type=str(item["type"]),
            requirement=str(item["requirement"]),
            nullable=bool(item["nullable"]),
            deprecated=_deprecation(item.get("lifecycle")),
            pointer=f"{pointer}/technicalColumns/{position}",
        )
        for position, item in enumerate(raw.get("technicalColumns", ()))
    )
    relationships = tuple(
        ContractRelationship(
            property=str(item["property"]),
            target=str(item["target"]),
            column_name=str(item.get("columnName", "")),
            pointer=f"{pointer}/relationships/{position}",
        )
        for position, item in enumerate(raw.get("relationships", ()))
    )
    return ContractEntity(
        target_class=str(raw["class"]),
        stability=str(raw["stability"]),
        closed=bool(raw["closed"]),
        grain=tuple(str(item) for item in raw["grain"]["properties"]),
        identity=ContractIdentity(
            strategy=str(identity_raw["strategy"]),
            business_key=tuple(str(item) for item in identity_raw.get("businessKey", ())),
        ),
        properties=properties,
        technical_columns=technical_columns,
        relationships=relationships,
        model_name=str(raw.get("modelName", "")),
        pointer=pointer,
    )


def default_column_name(qname: str) -> str:
    """Return the default Silver column name for an authored property token.

    Delegates to the same ``camel_to_snake`` the kernel uses at ``kernel.py:682`` -- a
    second local copy of that rule would be exactly the drift this contract exists to
    prevent. A contract that pins no ``columnName`` therefore reproduces today's emission
    byte for byte, which is what makes adopting a scaffolded contract a no-op.
    """
    return camel_to_snake(qname.split(":", 1)[-1])


def resolved_column_name(item: ContractProperty) -> str:
    """Return the emitted column name for one declared property."""
    return item.column_name or default_column_name(item.property)


def _entity_diagnostics(
    entity: ContractEntity, resolver: _MarkResolver
) -> list[CompileDiagnostic]:
    """Return the DD-213 §4 contract-load rules that need no ontology closure."""
    diagnostics: list[CompileDiagnostic] = []

    def diagnostic(code: str, message: str, pointer: str) -> None:
        diagnostics.append(
            CompileDiagnostic(code=code, message=message, location=resolver.at(pointer))
        )

    # contract.optional-not-nullable -- an optional property may be left unmapped by a
    # source, in which case the column carries a padded NULL for that source rows, so
    # `optional` implies `nullable: true` (DD-213 §4).
    for item in entity.properties:
        if not item.required and not item.nullable:
            diagnostic(
                "contract.optional-not-nullable",
                (
                    f"property '{item.property}' is optional but declares nullable: false; "
                    "an unmapped optional property is padded with NULL for that source rows"
                ),
                item.pointer,
            )
    for technical in entity.technical_columns:
        if not technical.required and not technical.nullable:
            diagnostic(
                "contract.optional-not-nullable",
                (
                    f"technical column '{technical.name}' is optional but declares "
                    "nullable: false"
                ),
                technical.pointer,
            )

    # contract.column-name-collision -- every emitted name must be unique and must not
    # collide with a compiler-owned reserved name.
    seen: dict[str, str] = {}
    emitted: list[tuple[str, str, str]] = [
        (resolved_column_name(item), f"property '{item.property}'", item.pointer)
        for item in entity.properties
    ]
    emitted.extend(
        (technical.name, f"technical column '{technical.name}'", technical.pointer)
        for technical in entity.technical_columns
    )
    emitted.extend(
        (relationship.column_name, f"relationship '{relationship.property}'", relationship.pointer)
        for relationship in entity.relationships
        if relationship.column_name
    )
    for name, label, pointer in emitted:
        key = name.lower()
        if key in seen:
            diagnostic(
                "contract.column-name-collision",
                f"{label} resolves to column '{name}', already used by {seen[key]}",
                pointer,
            )
        else:
            seen[key] = label
        if name.startswith(RESERVED_COLUMN_PREFIX) or key.endswith(RESERVED_COLUMN_SUFFIX):
            diagnostic(
                "contract.column-name-collision",
                (
                    f"{label} resolves to column '{name}', which is reserved for the "
                    "compiler-owned audit envelope and generated surrogate keys"
                ),
                pointer,
            )

    # contract.grain-not-required -- grain and business-key properties must be declared
    # `required`, which makes them mapped-by-construction so the DD-133 §8b source->output
    # resolution always applies (DD-213 §4).
    declared = {item.property: item for item in entity.properties}
    for label, keys, key_pointer in (
        ("grain", entity.grain, f"{entity.pointer}/grain/properties"),
        ("identity businessKey", entity.identity.business_key, f"{entity.pointer}/identity"),
    ):
        for qname in keys:
            item = declared.get(qname)
            if item is None:
                diagnostic(
                    "contract.grain-not-required",
                    f"{label} property '{qname}' is not declared under properties:",
                    key_pointer,
                )
            elif not item.required:
                diagnostic(
                    "contract.grain-not-required",
                    f"{label} property '{qname}' must be declared requirement: required",
                    item.pointer,
                )

    # contract.closed-requires-preview -- an open entity is only tolerable while it is
    # explicitly provisional (DD-213 §3).
    if not entity.closed and entity.stability != "preview":
        diagnostic(
            "contract.closed-requires-preview",
            (
                f"entity '{entity.target_class}' declares closed: false with stability "
                f"'{entity.stability}'; an open contract is permitted only while preview"
            ),
            entity.pointer,
        )

    # contract.deprecated-shape -- shape only; version values are never compared against
    # release history, which would make compile --check stateful (DD-213 §4).
    lifecycles: list[tuple[DeprecationSpec | None, str]] = [
        (item.deprecated, item.pointer) for item in entity.properties
    ]
    lifecycles.extend((tech.deprecated, tech.pointer) for tech in entity.technical_columns)
    for deprecated, pointer in lifecycles:
        if deprecated is None:
            continue
        if deprecated.since == deprecated.remove_in:
            diagnostic(
                "contract.deprecated-shape",
                (
                    f"deprecation declares since and removeIn as the same version "
                    f"'{deprecated.since}'; a deprecation window must span two releases"
                ),
                f"{pointer}/lifecycle/deprecated",
            )
        if deprecated.replaced_by and deprecated.replaced_by not in declared:
            diagnostic(
                "contract.deprecated-shape",
                (
                    f"replacedBy '{deprecated.replaced_by}' is not declared under "
                    "properties: for this entity"
                ),
                f"{pointer}/lifecycle/deprecated",
            )
    return diagnostics


def _document_diagnostics(
    contract: SilverContract, resolver: _MarkResolver
) -> list[CompileDiagnostic]:
    diagnostics: list[CompileDiagnostic] = []
    seen: dict[str, int] = {}
    for index, entity in enumerate(contract.entities):
        if entity.target_class in seen:
            diagnostics.append(
                CompileDiagnostic(
                    code="contract.duplicate-entity",
                    message=(
                        f"class '{entity.target_class}' is declared twice "
                        f"(first at /entities/{seen[entity.target_class]})"
                    ),
                    location=resolver.at(f"/entities/{index}/class"),
                )
            )
        else:
            seen[entity.target_class] = index
        diagnostics.extend(_entity_diagnostics(entity, resolver))

    model_names: dict[str, str] = {}
    for entity in contract.entities:
        name = entity.model_name
        if not name:
            continue
        if name.lower() in model_names:
            diagnostics.append(
                CompileDiagnostic(
                    code="contract.duplicate-entity",
                    message=(
                        f"modelName '{name}' is declared by both "
                        f"'{model_names[name.lower()]}' and '{entity.target_class}'"
                    ),
                    location=resolver.at(f"{entity.pointer}/modelName"),
                )
            )
        else:
            model_names[name.lower()] = entity.target_class
    return diagnostics


def load_silver_contract(text: str, *, path: str = "<contract>") -> SilverContract:
    """Parse and structurally validate one SilverContract document.

    Raises :class:`CompileError` with ordered, source-located diagnostics on any duplicate
    key, unknown field, schema violation, or contract-load rule failure.
    """
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = SourceLocation(
            path=path,
            line=(mark.line + 1) if mark else 0,
            column=(mark.column + 1) if mark else 0,
        )
        raise CompileError(
            [CompileDiagnostic(code="contract.yaml", message=str(exc), location=location)]
        ) from exc

    resolver = _MarkResolver(root, path)
    diagnostics: list[CompileDiagnostic] = []
    _collect_duplicate_key_diagnostics(root, path, diagnostics)
    for item in diagnostics:
        if item.code == "binding.duplicate-key":
            diagnostics[diagnostics.index(item)] = CompileDiagnostic(
                code="contract.duplicate-key",
                message=item.message,
                location=item.location,
            )

    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        diagnostics.append(
            CompileDiagnostic(
                code="contract.not-a-mapping",
                message="a SilverContract document must be a YAML mapping",
                location=resolver.at("/"),
            )
        )
        raise CompileError(diagnostics)

    diagnostics.extend(_schema_diagnostics(data, resolver))
    if diagnostics:
        raise CompileError(diagnostics)

    contract = SilverContract(
        api_version=str(data["apiVersion"]),
        domain=str(data["metadata"]["domain"]),
        entities=tuple(
            _build_entity(raw, index) for index, raw in enumerate(data["entities"])
        ),
        source_path=path,
    )
    diagnostics.extend(_document_diagnostics(contract, resolver))
    if diagnostics:
        raise CompileError(diagnostics)
    return contract
