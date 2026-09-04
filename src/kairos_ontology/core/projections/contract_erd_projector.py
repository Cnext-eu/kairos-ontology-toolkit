# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Declared Silver contract diagram (DD-216 / issue #698).

DD-213 places the declared contract "between the ontology (meaning) and the bindings
(source fulfilment)". Both neighbours already had a diagram and the contract did not --
it was the one layer a consumer had to read as raw YAML, and it is the layer that *is*
the published promise.

The emitted-Silver ERD does not cover it, because the two describe different things. For
one real party entity the emitted diagram carried fifteen columns in adapter-physical
types, five of them machinery (``<model>_sk``, ``_source_identity_ref``, ``_loaded_at``,
a DQ match-count), against the ten canonical-typed columns that are actually promised.
The emitted view also cannot express what the contract adds -- ``requirement``, declared
nullability, ``stability``, ``closed``, per-column deprecation -- and it hides
cross-domain reach behind ``_sk`` columns.

``erDiagram`` rather than the canonical target's ``classDiagram``: a contract describes a
physical Silver table, which has no class hierarchy, so the same reasoning DD-212 used to
keep the Silver/Gold bound ERDs on ``erDiagram`` applies here.

Reads the authored contract document, never a ``CompilePlan``: the promise is what was
declared, so a contract that no binding currently fulfils must still render.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..compiler.contracts import (
    ContractEntity,
    SilverContract,
    load_silver_contract,
    resolved_column_name,
)
from .shared import mmd_type
from .uri_utils import extract_local_name


def _entity_node(entity: ContractEntity) -> str:
    """Mermaid entity name: the emitted model name, upper-cased as the Silver ERD does."""
    name = entity.model_name or extract_local_name(entity.target_class)
    return mmd_type(name).upper()


def _comment(*parts: str) -> str:
    """Join note fragments, guaranteeing a Mermaid comment is never left bare.

    A ``%%`` line with no text after it fails the ``erDiagram`` parser outright, and the
    reported line number is post-comment-stripping so it does not point at the offending
    line (#698). Verified against mermaid-cli 11.12.0: a bare ``%%`` really does fail,
    while the same issue's CRLF claim does not reproduce.
    """
    text = ", ".join(part for part in parts if part)
    return f"%% {text}" if text else "%% (no detail)"


def _lifecycle(deprecated) -> str:
    if deprecated is None:
        return ""
    replaced = f", replaced by {extract_local_name(deprecated.replaced_by)}" if (
        deprecated.replaced_by
    ) else ""
    return f"deprecated since {deprecated.since}, removed in {deprecated.remove_in}{replaced}"


def _attribute(name: str, type_label: str, key: str, note: str) -> str:
    """One Mermaid ``erDiagram`` attribute line.

    The trailing quoted comment is where ``requirement`` and deprecation live -- the whole
    reason this diagram beats reading the YAML.
    """
    parts = [f"        {mmd_type(type_label) or 'string'} {mmd_type(name)}"]
    if key:
        parts.append(key)
    if note:
        parts.append(f'"{note}"')
    return " ".join(parts)


def _entity_block(entity: ContractEntity) -> list[str]:
    grain = {name.casefold() for name in entity.grain}
    business_key = {name.casefold() for name in entity.identity.business_key}
    relationship_columns = {
        item.column_name.casefold() for item in entity.relationships if item.column_name
    }

    lines = [
        "",
        _comment(
            extract_local_name(entity.target_class),
            f"stability={entity.stability}",
            "closed" if entity.closed else "open",
            f"identity={entity.identity.strategy}",
        ),
        f"    {_entity_node(entity)} {{",
    ]
    for item in entity.properties:
        column = resolved_column_name(item)
        key = "PK" if column.casefold() in grain or column.casefold() in business_key else ""
        if not key and column.casefold() in relationship_columns:
            key = "FK"
        lines.append(
            _attribute(
                column,
                item.type,
                key,
                ", ".join(
                    part
                    for part in (
                        item.requirement,
                        "" if item.nullable else "not null",
                        _lifecycle(item.deprecated),
                    )
                    if part
                ),
            )
        )
    for technical in entity.technical_columns:
        key = "PK" if technical.name.casefold() in grain else ""
        if not key and technical.name.casefold() in relationship_columns:
            key = "FK"
        lines.append(
            _attribute(
                technical.name,
                technical.type,
                key,
                ", ".join(
                    part
                    for part in (
                        "technical",
                        technical.requirement,
                        "" if technical.nullable else "not null",
                        _lifecycle(technical.deprecated),
                    )
                    if part
                ),
            )
        )
    if len(lines) == 3:
        # `erDiagram` accepts an empty block, but an entity promising no column at all is
        # worth seeing as a statement rather than as a blank box.
        lines.append('        string none "no column declared"')
    lines.append("    }")
    return lines


def _relationship_lines(contract: SilverContract) -> list[str]:
    """One edge per declared relationship, marking targets outside this domain.

    Cross-domain reach is the thing the emitted ERD cannot show -- it disappears behind a
    ``_sk`` column -- so an external target is called out rather than silently drawn.
    """
    by_class = {entity.target_class: entity for entity in contract.entities}
    lines: list[str] = []
    for entity in contract.entities:
        child = _entity_node(entity)
        for item in sorted(entity.relationships, key=lambda value: (value.property, value.target)):
            target = by_class.get(item.target)
            label = extract_local_name(item.property)
            if target is None:
                parent = mmd_type(extract_local_name(item.target)).upper()
                label = f"{label} [external]"
            else:
                parent = _entity_node(target)
            lines.append(f'    {parent} ||--o{{ {child} : "{label}"')
    return sorted(set(lines))


def render_contract_erd(contract: SilverContract) -> str:
    """Render one declared Silver contract as a Mermaid ``erDiagram``."""
    lines = [
        _comment(
            f"Declared Silver contract ERD: {contract.domain}",
            "generated by kairos-ontology -- do not edit",
        ),
        _comment(
            "The published promise (DD-213), not what any binding emits today",
            "canonical types",
        ),
        _comment("PK = grain or business key", "FK = declared relationship column"),
        "erDiagram",
    ]
    for entity in contract.entities:
        lines.extend(_entity_block(entity))
    relationships = _relationship_lines(contract)
    if relationships:
        lines.append("")
        lines.extend(relationships)
    return "\n".join(lines) + "\n"


def generate_contract_erd_artifacts(
    contracts_dir: Optional[Path],
    ontology_name: str,
) -> dict:
    """Return ``{filename: content}`` for one domain's declared contract, if it has one.

    An ungoverned domain returns ``{}`` -- adopting a contract is opt-in (DD-213 §6), so a
    hub that has not adopted one must not start emitting an empty diagram for it.
    """
    domain = ontology_name or "domain"
    if contracts_dir is None:
        return {}
    path = Path(contracts_dir) / f"{domain}.contract.yaml"
    if not path.is_file():
        return {}
    contract = load_silver_contract(path.read_text(encoding="utf-8"), path=str(path))
    if not contract.entities:
        return {}
    return {f"{domain}-contract-erd.mmd": render_contract_erd(contract)}
