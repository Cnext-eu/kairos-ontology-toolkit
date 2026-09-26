# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The one renderer of semantic-index records into prompt prose (DD-243, DD-244).

An LLM prompt that lists ontology classes and properties is where a partial view becomes a
wrong conclusion: a class shown with 60 of its 90 properties reads as a class with 60
properties, and "no listed property fits" becomes "the reference model lacks it". Every
prompt builder therefore renders its class context through :func:`render_class_context`,
which reads the closure-aware :class:`~.semantic_index.SemanticIndex` (never a single file),
shows inherited properties with their origin, and, when it has to cut, says so in one line
the model can act on. ``tests/test_prompt_context_contract.py`` holds builders to this.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .semantic_index import ClassRecord, SemanticIndex


@dataclass(frozen=True)
class RenderedClassContext:
    """Prompt text plus exactly what it showed, so a response schema can match it."""

    text: str
    #: ``{class_uri: [property_uri, ...]}`` for every property the text lists.
    shown: dict[str, list[str]] = field(default_factory=dict)
    omitted_class_count: int = 0
    omitted_property_count: int = 0

    @property
    def truncated(self) -> bool:
        return bool(self.omitted_class_count or self.omitted_property_count)


#: What the model is told when the context had to be cut. Actionable, and only when true.
DISCLOSURE_TEMPLATE = (
    "NOTE: {classes} further class(es) and {properties} further propert(y/ies) in scope are "
    "not listed above. If nothing listed fits, answer null; do not conclude the concept is "
    "absent from the reference model."
)


def disclosure_line(*, omitted_classes: int = 0, omitted_properties: int = 0) -> str:
    """The one line a prompt adds when it had to cut; empty when it did not."""
    if not (omitted_classes or omitted_properties):
        return ""
    return DISCLOSURE_TEMPLATE.format(classes=omitted_classes, properties=omitted_properties)


def truncate_class_pool(
    ref_classes: list[dict[str, Any]], *, max_properties: int
) -> tuple[list[dict[str, Any]], int]:
    """Cut each dict-shaped class's ``properties`` to *max_properties*.

    Returns ``(shown, omitted_property_count)``. Order is preserved, so a pool sorted
    own-before-inherited drops inherited properties first, and whatever survives here is
    exactly what the prompt lists -- the response schema and the pair check are built
    from the same list (DD-244), so the model is never offered a term it was not shown.
    """
    shown: list[dict[str, Any]] = []
    omitted = 0
    for cls in ref_classes:
        props = list(cls.get("properties") or [])
        kept = props[:max_properties]
        omitted += len(props) - len(kept)
        shown.append({**cls, "properties": kept} if len(kept) != len(props) else cls)
    return shown, omitted


def render_class_context(
    index: SemanticIndex,
    class_uris: Iterable[str] | None = None,
    *,
    max_classes: int | None = None,
    max_properties: int | None = None,
    heading: str = "REFERENCE CLASSES",
) -> RenderedClassContext:
    """Render *class_uris* (or every class) from *index* for a prompt.

    Classes keep the order given. Each class lists its direct properties first, then the
    inherited ones marked ``(inherited from <Class>)``, so a cut at *max_properties* drops
    inherited properties last-listed but never silently: the omitted counts are disclosed
    in the final line, and :attr:`RenderedClassContext.shown` records what survived.
    """
    if class_uris is None:
        records: list[ClassRecord] = list(index.classes)
    else:
        records = [record for uri in class_uris if (record := index.class_by_uri(uri)) is not None]
    included = records[:max_classes] if max_classes is not None else records
    omitted_classes = len(records) - len(included)

    lines = [f"{heading} ({len(included)} listed)"]
    shown: dict[str, list[str]] = {}
    omitted_properties = 0
    for record in included:
        rows = index.class_properties(record.uri)
        kept = rows[:max_properties] if max_properties is not None else rows
        omitted_properties += len(rows) - len(kept)
        shown[record.uri] = [row["property_uri"] for row in kept]
        comment = f" -- {record.comment.strip()}" if record.comment.strip() else ""
        lines.append(f"CLASS: {record.name} ({record.label}){comment}")
        if not rows:
            lines.append("  properties: (none declared)")
            continue
        for row in kept:
            origin = ""
            if row["origin"] == "inherited":
                origin = f" (inherited from {_owner_name(index, record, row['property_uri'])})"
            ranges = ", ".join(_local(uri) for uri in row["ranges"]) or "-"
            lines.append(f"  - {row['name']} [{row['property_type']}: {ranges}]{origin}")
        if len(rows) > len(kept):
            lines.append(f"  … {len(rows) - len(kept)} more not listed")
    if omitted_classes or omitted_properties:
        lines.append("")
        lines.append(
            disclosure_line(omitted_classes=omitted_classes, omitted_properties=omitted_properties)
        )
    return RenderedClassContext(
        text="\n".join(lines),
        shown=shown,
        omitted_class_count=omitted_classes,
        omitted_property_count=omitted_properties,
    )


def _owner_name(index: SemanticIndex, record: ClassRecord, property_uri: str) -> str:
    """The nearest ancestor that declares *property_uri* directly, by name."""
    for ancestor in sorted(record.ancestors, key=lambda link: link.distance):
        owner = index.class_by_uri(ancestor.uri)
        if owner is not None and any(link.uri == property_uri for link in owner.direct_properties):
            return owner.name
    return "an ancestor"


def _local(uri: str) -> str:
    return uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


__all__ = [
    "DISCLOSURE_TEMPLATE",
    "RenderedClassContext",
    "disclosure_line",
    "render_class_context",
    "truncate_class_pool",
]
