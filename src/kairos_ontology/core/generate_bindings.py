# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic EntityBinding generation from the design sheet (DD-191).

The last missing pipeline stage DD-185 deferred ("the binding-draft
generator"). One sheet row (DD-190) plus its ``propose-alignment`` output plus
the source profile (DD-189) already contain everything a first-draft binding
needs — this module assembles them with **zero model calls** and validates
every draft through the compiler's own ``load_entity_binding`` before writing.

Rules, each kernel-verified on the signal-first validation corpus (the
generated drafts passed ``compile --check`` clean on four domains):

* **Reuse-first**: ``target.class`` is the sheet's ``anchor_uri`` — a
  reference-model IRI directly (DD-144). No local class is authored here.
* **Module-scoped property resolution**: a mapped property resolves only in
  the anchor copy's own module inventory. Cross-module URI picks produced
  ``safety.property-unresolved`` live; an unresolvable property becomes a
  reported gap, never a guess.
* **Datatype/object split**: alignment maps columns to property *names*; the
  DD-172 inventory says which are object properties. Those become
  ``technicalFields purpose: relationship`` FK carriers — ``fields:``
  materializes scalars only (``safety.relationship-endpoint``).
* **Duplicate property claims dedupe**: several columns mapped to one
  property keep the highest-confidence column; the rest are reported.
* **Grain/identity materialization**: sheet grain and natural-key columns not
  already mapped become ``technicalFields purpose: identity``, typed from the
  profile (or the alignment's recorded SQL type, which the compiler
  normalizes by kind).
* **Sheet relationships → FK carriers**: the interim DD-139 pattern;
  ``propose-relationships`` upgrades carriers to real ``relationships:``
  entries as parents get bound.
* **Profile-proven quality only**: ``unique``/``not-null`` tests are emitted
  only when the profile measured them on the grain column.

Drafts are written to ``integration/bindings/`` (the authored space — review
is the git diff, per the scaffold-binding convention) and never overwrite an
existing binding without ``force``. Everything generation cannot decide lands
in the returned report, never silently: unresolved properties, dropped
duplicate claims, skipped tables, and the secondary-entity worklist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from .compiler.bindings import load_entity_binding
from .compiler.result import CompileError

logger = logging.getLogger(__name__)

Reporter = Callable[..., None]

#: Arrow-type → canonical-type-token map (profile types). Anything unknown
#: falls back to the alignment's recorded SQL type, which the compiler
#: normalizes by kind (``varchar(n)``, ``bigint``, …) — never to a guess.
_ARROW_TO_CANONICAL = {
    "string": "string", "large_string": "string", "utf8": "string",
    "int8": "int16", "int16": "int16", "int32": "int32", "int64": "int64",
    "double": "float64", "float": "float64", "bool": "boolean",
    "date32[day]": "date", "date64": "date",
}


def _canonical_type(arrow_or_sql: str) -> str:
    """Normalize an arrow or SQL type to a canonical token.

    ``technicalFields.type`` is a CLOSED enum in the binding schema (unlike
    ``externalReference.key[].type``, which accepts SQL aliases), so every
    input must land on a canonical token — unknowns default to ``string``,
    the one kind every source value can materialize as.
    """
    lowered = (arrow_or_sql or "").strip().lower()
    if lowered.startswith(("timestamp", "datetime")):
        return "timestamp"
    if lowered.startswith(("decimal", "numeric", "money")):
        return "decimal"
    if lowered.startswith(("varchar", "nvarchar", "char", "nchar", "text", "uuid",
                           "uniqueidentifier")):
        return "string"
    if lowered.startswith("varbinary") or lowered == "binary":
        return "binary"
    if lowered.startswith(("float", "real")):
        return "float64"
    if lowered.startswith("date3") or lowered in ("date", "date64"):
        return "date"
    if lowered.startswith("time") :
        return "time"
    sql_aliases = {"bigint": "int64", "int": "int32", "integer": "int32",
                   "smallint": "int16", "tinyint": "int16", "bit": "boolean",
                   "boolean": "boolean", "json": "json"}
    if lowered in sql_aliases:
        return sql_aliases[lowered]
    return _ARROW_TO_CANONICAL.get(lowered, "string")


def _module_of(class_uri: str) -> str:
    """The module URI a class IRI belongs to (fragment or last-segment strip)."""
    if "#" in class_uri:
        return class_uri.rsplit("#", 1)[0]
    return class_uri.rsplit("/", 1)[0]


@dataclass(slots=True)
class GeneratedBinding:
    """Outcome for one sheet row."""

    system: str
    table: str
    binding_name: str
    domain: str
    outcome: str  # written | would-write | exists | invalid | skipped
    path: Optional[Path] = None
    fields: int = 0
    technical_fields: int = 0
    note: str = ""


@dataclass(slots=True)
class GenerateBindingsReport:
    """Everything generation decided — and everything it could not."""

    generated: list[GeneratedBinding] = field(default_factory=list)
    unresolved_properties: list[dict[str, Any]] = field(default_factory=list)
    duplicate_property_claims: list[dict[str, Any]] = field(default_factory=list)
    secondary_entity_worklist: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "generated": [
                {
                    "system": g.system, "table": g.table, "binding": g.binding_name,
                    "domain": g.domain, "outcome": g.outcome,
                    "fields": g.fields, "technical_fields": g.technical_fields,
                    "note": g.note,
                }
                for g in self.generated
            ],
            "unresolved_properties": self.unresolved_properties,
            "duplicate_property_claims": self.duplicate_property_claims,
            "secondary_entity_worklist": self.secondary_entity_worklist,
        }


def _class_pools(
    catalog_path: Path, class_uri: str
) -> tuple[dict[str, str], set[str]]:
    """(scalar property name → URI, object property names) for one class copy.

    Scoped to the copy's own module inventory — the kernel-verified rule that
    keeps every emitted property resolvable in the domain's closure.
    """
    from .propose_alignment import extract_ref_model_inventory

    module = _module_of(class_uri)
    scalar: dict[str, str] = {}
    objects: set[str] = set()
    for cls in extract_ref_model_inventory([module], catalog_path):
        if cls.get("uri") != class_uri:
            continue
        for prop in cls.get("properties") or []:
            name = str(prop.get("name") or "")
            if not name:
                continue
            if prop.get("type") == "object":
                objects.add(name)
            elif prop.get("uri"):
                scalar[name] = str(prop["uri"])
        break
    return scalar, objects


def _profile_column(profile: dict | None, table: str, column: str) -> dict[str, Any]:
    return (((profile or {}).get("tables") or {}).get(table) or {}).get(
        "columns", {}
    ).get(column) or {}


def generate_binding_doc(
    entry: dict[str, Any],
    alignment_table: dict[str, Any],
    *,
    catalog_path: Path,
    profile: dict | None,
    report: GenerateBindingsReport,
) -> tuple[Optional[dict[str, Any]], str]:
    """Assemble one closed EntityBinding document from sheet + alignment + profile.

    Returns ``(doc, reason)``: ``doc`` is ``None`` and ``reason`` explains why when
    the row cannot be generated at all — no anchor URI/domain, no grain, or zero
    scalar fields mapped. ``reason`` is ``""`` when ``doc`` is not ``None``.

    Recognizing these cases here, before ever building a document, is what keeps
    them ``skipped`` rather than ``invalid`` (issue #565): this generator never
    emits a ``relationships:`` block (deferred to ``propose-relationships``, see
    ``run_generate_bindings``'s own docstring), so an empty ``grain`` or an empty
    ``fields`` is unconditionally unwritable under the v5 contract regardless of
    what else is true about the row — that is a property of *this table*, not a
    defect in the draft, and must not be reported as one.
    """
    system = str(entry.get("system") or "")
    table = str(entry.get("table") or "")
    class_uri = str(entry.get("anchor_uri") or "")
    domain = str(entry.get("domain") or "")
    if not (system and table and class_uri and domain):
        return None, "no anchor URI or derived domain on the sheet"

    grain = [str(c) for c in entry.get("grain_columns") or []]
    if not grain:
        return None, "no grain identified on the sheet row"

    scalar_uri, object_names = _class_pools(catalog_path, class_uri)
    align_types = {
        str(c.get("column") or ""): str(c.get("data_type") or "")
        for c in alignment_table.get("columns") or []
        if isinstance(c, dict)
    }

    # fields: best column per SCALAR property, module-scoped resolution.
    by_property: dict[str, list[tuple[float, str]]] = {}
    relationship_cols: list[str] = []
    for col in alignment_table.get("columns") or []:
        if not isinstance(col, dict):
            continue
        name = str(col.get("column") or "")
        prop = str(col.get("ref_property") or "")
        if not (name and prop):
            continue
        if prop in object_names:
            relationship_cols.append(name)
            continue
        by_property.setdefault(prop, []).append(
            (float(col.get("confidence") or 0.0), name)
        )
    fields: list[dict[str, Any]] = []
    mapped_cols: set[str] = set()
    for prop, claims in sorted(by_property.items()):
        claims.sort(reverse=True)
        _confidence, column = claims[0]
        uri = scalar_uri.get(prop)
        if not uri:
            report.unresolved_properties.append(
                {"system": system, "table": table, "property": prop, "column": column,
                 "reason": "not a scalar property of the anchor's module inventory"}
            )
            continue
        fields.append({"property": uri, "expression": column})
        mapped_cols.add(column)
        for _c, dropped in claims[1:]:
            report.duplicate_property_claims.append(
                {"system": system, "table": table, "property": prop,
                 "kept": column, "dropped": dropped}
            )

    if not fields:
        # A carrier's presence changes the reason text, never the outcome: this
        # generator never emits relationships: (deferred to propose-relationships),
        # so an empty fields: is unwritable under the v5 contract either way.
        if relationship_cols or entry.get("relationships"):
            return None, (
                "no scalar fields mapped for this table (relationship wiring is "
                "deferred to propose-relationships)"
            )
        return None, "no scalar fields mapped for this table"

    def _column_type(column: str) -> tuple[str, bool]:
        meta = _profile_column(profile, table, column)
        if meta:
            return _canonical_type(str(meta.get("type") or "")), (
                float(meta.get("null_ratio") or 0.0) > 0
            )
        return _canonical_type(align_types.get(column, "")), True

    source_key = [str(c) for c in entry.get("natural_key") or []] or grain
    technical: list[dict[str, Any]] = []
    for column in dict.fromkeys([*grain, *source_key]):
        if column in mapped_cols:
            continue
        ctype, nullable = _column_type(column)
        technical.append({"name": column, "expression": column, "type": ctype,
                          "nullable": nullable, "purpose": "identity"})

    fk_columns = [
        str(r.get("local_column") or "")
        for r in entry.get("relationships") or []
        if isinstance(r, dict)
    ] + relationship_cols
    for column in dict.fromkeys(c for c in fk_columns if c):
        if column in mapped_cols or any(t["name"] == column for t in technical):
            continue
        ctype, nullable = _column_type(column)
        technical.append({"name": column, "expression": column, "type": ctype,
                          "nullable": nullable, "purpose": "relationship"})

    quality: list[dict[str, Any]] = []
    if len(grain) == 1:
        meta = _profile_column(profile, table, grain[0])
        tags = meta.get("tags") or []
        # NOTE: null_ratio == 0.0 is falsy — never `or`-default this read.
        if meta and float(meta.get("null_ratio", 1.0)) == 0.0:
            quality.append({"kind": "not-null", "columns": list(grain)})
        if "unique" in tags:
            quality.append({"kind": "unique", "columns": list(grain)})

    for secondary in entry.get("secondary_entities") or []:
        if isinstance(secondary, dict):
            report.secondary_entity_worklist.append(
                {"system": system, "table": table, **secondary}
            )

    doc: dict[str, Any] = {
        "apiVersion": "kairos.eu/v5",
        "kind": "EntityBinding",
        "metadata": {
            "name": f"{system}-{table.replace('_', '-')}-to-{domain}",
            "domain": domain,
        },
        "source": {"relation": f"{system}.{table}"},
        "target": {"class": class_uri},
        "grain": {"columns": grain},
        "identity": {"strategy": "source-natural", "sourceKey": source_key},
        "load": {"mode": "full-refresh"},
        "fields": fields,
    }
    if technical:
        doc["technicalFields"] = technical
    if quality:
        doc["quality"] = quality
    return doc, ""


def run_generate_bindings(
    hub_root: Path,
    *,
    analysis_dir: Optional[Path] = None,
    catalog_path: Optional[Path] = None,
    tables: Optional[list[str]] = None,
    domain: Optional[str] = None,
    force: bool = False,
    dry_run: bool = False,
    report_fn: Reporter | None = None,
) -> GenerateBindingsReport:
    """Generate first-draft bindings for every eligible design-sheet row.

    Eligible: an anchored, non-``rejected`` entry with a derived domain and a
    ``propose-alignment`` result for its table. Every draft is validated with
    ``load_entity_binding`` before it is written; an invalid draft is reported
    and never lands on disk.
    """
    from .anchor_tables import load_table_anchors
    from .fit_report import find_source_alignment
    from .profile_sources import load_profile

    say = report_fn or (lambda *_a, **_k: None)
    hub = Path(hub_root)
    analysis = Path(analysis_dir) if analysis_dir else hub / "integration" / "sources" / "_analysis"
    catalog = Path(catalog_path) if catalog_path else hub / "catalog-v001.xml"
    sources_dir = hub / "integration" / "sources"
    bindings_dir = hub / "integration" / "bindings"

    anchors = load_table_anchors(analysis)
    if not anchors:
        raise FileNotFoundError(
            f"no table-anchors.yaml under {analysis} — run `kairos-ontology "
            "anchor-tables` first; the design sheet is generation's input."
        )

    report = GenerateBindingsReport()
    profiles: dict[str, dict | None] = {}
    for (system, table), entry in sorted(anchors.items()):
        key = f"{system}.{table}"
        if tables and key not in tables:
            continue
        if domain and str(entry.get("domain") or "") != domain:
            continue
        if str(entry.get("status") or "") == "rejected":
            continue
        if not entry.get("anchor_uri") or not entry.get("domain"):
            report.generated.append(GeneratedBinding(
                system, table, "", str(entry.get("domain") or ""),
                "skipped", note="no anchor URI or derived domain on the sheet"))
            continue
        found = find_source_alignment(analysis, system, table)
        if found is None:
            report.generated.append(GeneratedBinding(
                system, table, "", str(entry.get("domain") or ""), "skipped",
                note="no propose-alignment result; run propose-alignment first"))
            continue
        if system not in profiles:
            profiles[system] = load_profile(sources_dir, system)
        doc, skip_reason = generate_binding_doc(
            entry, found[1], catalog_path=catalog,
            profile=profiles[system], report=report,
        )
        if doc is None:
            report.generated.append(GeneratedBinding(
                system, table, "", str(entry.get("domain") or ""),
                "skipped", note=skip_reason))
            continue

        name = doc["metadata"]["name"]
        out_path = bindings_dir / f"{name}.binding.yaml"
        text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
        try:
            load_entity_binding(text, path=str(out_path))
        except CompileError as exc:
            report.generated.append(GeneratedBinding(
                system, table, name, doc["metadata"]["domain"], "invalid",
                note=str(exc)))
            say(f"  ✗ {key}: draft failed contract validation — {exc}", "warning")
            continue
        outcome = GeneratedBinding(
            system, table, name, doc["metadata"]["domain"], "would-write",
            path=out_path, fields=len(doc["fields"]),
            technical_fields=len(doc.get("technicalFields") or []),
        )
        if out_path.exists() and not force:
            outcome.outcome = "exists"
            outcome.note = "already exists; not overwritten (pass --force)"
        elif not dry_run:
            bindings_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(text, encoding="utf-8")
            outcome.outcome = "written"
        report.generated.append(outcome)
        say(
            f"  ✅ {key} → {name} ({outcome.fields} field(s), "
            f"{outcome.technical_fields} technical) [{outcome.outcome}]"
        )
    return report
