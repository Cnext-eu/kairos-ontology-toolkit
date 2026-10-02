# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The authored narrative of a business validation document, and its check (DD-254).

The narrative words and groups facts; it may not add one. ``validate_narrative`` fails
closed: an ID the facts do not carry is an error, and so is a core entity, relationship or
non-deprecated field that the narrative neither places (in a figure, a relationship table or
a field group) nor lists under ``omitted`` with a reason.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any

import yaml

NARRATIVE_FILENAME = "business-doc.narrative.yaml"

_GAP_ID = re.compile(r"^G\d+$")
_DECISION_ID = re.compile(r"^D\d+$")


def load_narrative(path: Path) -> dict[str, Any]:
    """Read *path* as a narrative mapping; ``ValueError`` when it is not one."""
    try:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: not valid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{path}: a narrative is a YAML mapping")
    return document


class Aliases:
    """Maps a CURIE or a full IRI used in a narrative to the facts' CURIE."""

    def __init__(self, facts: dict[str, Any]):
        self.core: dict[str, str] = {}
        self.nodes: dict[str, str] = {}
        self.fields: dict[str, dict[str, str]] = {}
        for entity in facts.get("entities", ()):
            for key in (entity["iri"], entity["uri"]):
                self.core[key] = entity["iri"]
                self.nodes[key] = entity["iri"]
            props: dict[str, str] = {}
            for item in entity.get("fields", ()):
                props[item["property"]] = item["property"]
                props[item["uri"]] = item["property"]
            self.fields[entity["iri"]] = props
        for external in facts.get("externals", ()):
            for key in (external["iri"], external["uri"]):
                self.nodes[key] = external["iri"]

    def entity(self, token: Any) -> str | None:
        return self.core.get(str(token))

    def node(self, token: Any) -> str | None:
        return self.nodes.get(str(token))

    def field(self, entity: str, token: Any) -> str | None:
        return self.fields.get(entity, {}).get(str(token))


def _omitted(block: Any, key: str) -> dict[str, str]:
    """``{item: reason}`` from a list of ``{<key>: ..., reason: ...}`` mappings."""
    result: dict[str, str] = {}
    for entry in block or ():
        if isinstance(entry, dict) and entry.get(key) is not None:
            result[str(entry[key])] = str(entry.get("reason") or "").strip()
    return result


def figure_relationships(facts: dict[str, Any], narrative: dict[str, Any]) -> dict[str, list[str]]:
    """``{figure id: [relationship id]}``: each relationship in the first figure holding both ends."""
    aliases = Aliases(facts)
    placed: dict[str, list[str]] = {}
    taken: set[str] = set()
    for figure in narrative.get("figures") or ():
        if not isinstance(figure, dict):
            continue
        figure_id = str(figure.get("id"))
        members = {aliases.node(token) for token in figure.get("entities") or ()} - {None}
        rows = []
        for rel in facts.get("relationships", ()):
            if rel["id"] not in taken and rel["from"] in members and rel["to"] in members:
                rows.append(rel["id"])
                taken.add(rel["id"])
        placed[figure_id] = rows
    return placed


def validate_narrative(facts: dict[str, Any], narrative: dict[str, Any]) -> list[str]:
    """Every reason *narrative* cannot be rendered against *facts*; empty when it can."""
    errors: list[str] = []
    aliases = Aliases(facts)
    relationship_ids = [rel["id"] for rel in facts.get("relationships", ())]
    top_omitted = _omitted(narrative.get("omitted"), "item")
    for item, reason in top_omitted.items():
        if not reason:
            errors.append(f"omitted: {item} has no reason")
        if item not in relationship_ids and aliases.entity(item) is None:
            errors.append(f"omitted: {item} is neither a relationship nor a core entity")

    document = narrative.get("document")
    if not isinstance(document, dict):
        errors.append("document: missing (needs version and date)")
    else:
        version = document.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            errors.append("document.version: a whole number of at least 1")
        date = document.get("date")
        if isinstance(date, str):
            try:
                _dt.date.fromisoformat(date)
            except ValueError:
                errors.append(f"document.date: {date!r} is not an ISO date (YYYY-MM-DD)")
        elif not isinstance(date, _dt.date):
            errors.append("document.date: missing (YYYY-MM-DD)")

    # Relationships: wording for every one, no wording for one the facts lack.
    wording = narrative.get("relationships") or {}
    if not isinstance(wording, dict):
        errors.append("relationships: a mapping of relationship id to {one, other}")
        wording = {}
    for rel_id in wording:
        if str(rel_id) not in relationship_ids:
            errors.append(f"relationships.{rel_id}: no such relationship in the facts")
    for rel_id in relationship_ids:
        if rel_id in top_omitted:
            continue
        entry = wording.get(rel_id)
        if not isinstance(entry, dict) or not entry.get("one") or not entry.get("other"):
            errors.append(f"relationships.{rel_id}: needs both 'one' and 'other' sentences")

    # Figures: known members, every core entity and relationship placed somewhere.
    figures = narrative.get("figures") or []
    if not isinstance(figures, list) or not figures:
        errors.append("figures: at least one figure is needed")
        figures = []
    seen_figures: set[str] = set()
    in_figure: set[str] = set()
    for position, figure in enumerate(figures):
        if not isinstance(figure, dict):
            errors.append(f"figures[{position}]: a mapping with id, title and entities")
            continue
        figure_id = str(figure.get("id"))
        if figure_id in seen_figures:
            errors.append(f"figures: id {figure_id} is used twice")
        seen_figures.add(figure_id)
        if not figure.get("title"):
            errors.append(f"figures.{figure_id}: needs a title")
        for token in figure.get("entities") or ():
            node = aliases.node(token)
            if node is None:
                errors.append(f"figures.{figure_id}: {token} is not an entity in the facts")
            else:
                in_figure.add(node)
    for entity in facts.get("entities", ()):
        if entity["iri"] not in in_figure and entity["iri"] not in top_omitted:
            errors.append(f"figures: core entity {entity['iri']} is in no figure")
    placed = {rid for rows in figure_relationships(facts, narrative).values() for rid in rows}
    for rel_id in relationship_ids:
        if rel_id not in placed and rel_id not in top_omitted:
            errors.append(f"figures: {rel_id} has no figure holding both its ends")

    # Entities: one block per core entity, fields placed or omitted.
    blocks = narrative.get("entities") or {}
    if not isinstance(blocks, dict):
        errors.append("entities: a mapping of entity IRI to its block")
        blocks = {}
    by_entity: dict[str, dict[str, Any]] = {}
    for token, block in blocks.items():
        entity = aliases.entity(token)
        if entity is None:
            errors.append(f"entities.{token}: not a core entity in the facts")
            continue
        by_entity[entity] = block if isinstance(block, dict) else {}
    for entity in facts.get("entities", ()):
        iri = entity["iri"]
        if iri in top_omitted:
            continue
        block = by_entity.get(iri)
        if block is None:
            errors.append(f"entities.{iri}: missing")
            continue
        if not str(block.get("definition") or "").strip():
            errors.append(f"entities.{iri}.definition: missing")
        deprecated = {f["property"] for f in entity["fields"] if f["deprecated"]}
        grouped: set[str] = set()
        for group in block.get("field_groups") or ():
            title = group.get("title") if isinstance(group, dict) else None
            if not title:
                errors.append(f"entities.{iri}.field_groups: every group needs a title")
            for token in (group.get("properties") if isinstance(group, dict) else None) or ():
                prop = aliases.field(iri, token)
                if prop is None:
                    errors.append(f"entities.{iri}.field_groups: {token} is not a field of it")
                elif prop in deprecated:
                    errors.append(f"entities.{iri}.field_groups: {token} is deprecated")
                elif prop in grouped:
                    errors.append(f"entities.{iri}.field_groups: {token} is placed twice")
                else:
                    grouped.add(prop)
        omitted_fields = _omitted(block.get("omitted"), "property")
        resolved_omitted: set[str] = set()
        for token, reason in omitted_fields.items():
            prop = aliases.field(iri, token)
            if prop is None:
                errors.append(f"entities.{iri}.omitted: {token} is not a field of it")
            elif not reason:
                errors.append(f"entities.{iri}.omitted: {token} has no reason")
            else:
                resolved_omitted.add(prop)
        for item in entity["fields"]:
            prop = item["property"]
            if prop in deprecated or prop in grouped or prop in resolved_omitted:
                continue
            errors.append(f"entities.{iri}: field {prop} is in no field group and not omitted")
        for key in ("field_meanings", "held_references"):
            for token in block.get(key) or {}:
                if aliases.field(iri, token) is None:
                    errors.append(f"entities.{iri}.{key}: {token} is not a field of it")

    neighbours = {row["domain"] for row in facts.get("neighbour_domains", ())}
    rows = ((narrative.get("domain_view") or {}).get("rows")) or {}
    for name in rows:
        if name not in neighbours:
            errors.append(f"domain_view.rows.{name}: not a neighbour domain in the facts")

    for key, pattern in (("gaps", _GAP_ID), ("decisions", _DECISION_ID)):
        seen: set[str] = set()
        for entry in narrative.get(key) or ():
            entry_id = str(entry.get("id")) if isinstance(entry, dict) else ""
            if not pattern.match(entry_id):
                errors.append(f"{key}: id {entry_id!r} must look like {pattern.pattern[1:2]}1")
            elif entry_id in seen:
                errors.append(f"{key}: id {entry_id} is used twice")
            seen.add(entry_id)
    for entry in narrative.get("glossary") or ():
        if not isinstance(entry, dict) or not entry.get("term") or not entry.get("meaning"):
            errors.append("glossary: every entry needs a term and a meaning")
    return errors
