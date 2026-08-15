# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""fit-report core logic (advisory, DD-144 follow-on).

Answers, deterministically and without any LLM call: "of everything an accelerator already
models for class X, which properties does source table Y already populate, which are still
empty, and which source columns don't map anywhere?"

This module owns only the reusable *library* logic — resolving the class token, building its
property universe via the DD-103 semantic index, and set-differencing it against whichever
evidence source (an ``EntityBinding``'s ``fields:`` or a ``propose-alignment`` output) is
available. It has no Click/CLI dependency so a later ``scaffold-binding`` command can import
and call :func:`run_fit_report` directly as a library function.

**fit-report is advisory input to design, not a completeness check.** It never blocks, never
writes state, and a clean "no evidence source found" result is not a failure — it is signal
that the author has not run ``propose-alignment`` or authored a binding yet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .compiler.bindings import EntityBinding, ExprColumn, load_entity_binding
from .compiler.result import CompileError
from .ontology_loader import SemanticProfile, load_ontology

SCHEMA_VERSION = 1

ADVISORY_NOTICE = "fit-report is advisory input to design, not a completeness check."


class FitReportError(ValueError):
    """Raised when the requested class cannot be resolved against the ontology closure."""


# --------------------------------------------------------------------------------------
# Result shape (plain dataclasses, JSON/dict friendly, no CLI dependency).
# --------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PopulatedProperty:
    """One universe property with evidence that it is already populated."""

    property_uri: str
    name: str
    origin: str
    distance: int
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "property_uri": self.property_uri,
            "name": self.name,
            "origin": self.origin,
            "distance": self.distance,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class UnpopulatedProperty:
    """One universe property with no evidence of population — pick-list material."""

    property_uri: str
    name: str
    property_type: str
    origin: str
    distance: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "property_uri": self.property_uri,
            "name": self.name,
            "property_type": self.property_type,
            "origin": self.origin,
            "distance": self.distance,
        }


@dataclass(frozen=True, slots=True)
class OrphanColumn:
    """One source column with no resolved mapping to any property in the universe."""

    column: str
    data_type: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"column": self.column, "data_type": self.data_type, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class TechnicalFieldSummary:
    """One DD-139 authored technical field — never an ontology property (context only)."""

    name: str
    purpose: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "purpose": self.purpose}


@dataclass(frozen=True, slots=True)
class FitReportResult:
    """Deterministic set-difference between a class's property universe and evidence."""

    class_uri: str
    class_name: str
    evidence_kind: str  # "binding" | "source-alignment" | "none"
    evidence_path: str | None
    source_system: str | None
    source_table: str | None
    populated: tuple[PopulatedProperty, ...]
    unpopulated: tuple[UnpopulatedProperty, ...]
    orphan_columns: tuple[OrphanColumn, ...]
    technical_fields: tuple[TechnicalFieldSummary, ...]
    notes: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "advisory": ADVISORY_NOTICE,
            "class_uri": self.class_uri,
            "class_name": self.class_name,
            "evidence": {
                "kind": self.evidence_kind,
                "path": self.evidence_path,
                "source_system": self.source_system,
                "source_table": self.source_table,
            },
            "populated": [item.to_dict() for item in self.populated],
            "unpopulated": [item.to_dict() for item in self.unpopulated],
            "orphan_columns": [item.to_dict() for item in self.orphan_columns],
            "technical_fields": [item.to_dict() for item in self.technical_fields],
            "notes": list(self.notes),
        }


# --------------------------------------------------------------------------------------
# Class/property token resolution (full IRI or ``prefix:Local`` qname).
#
# DD-103: the semantic index already covers the *entire* resolved ``owl:imports`` closure,
# so an accelerator class/property is already indexed — it is simply never looked up unless
# its authored token is turned into a full URI first. rdflib's own graph namespace_manager
# does not reliably retain a merged multi-file closure's ``@prefix`` bindings, so — exactly
# like the compiler kernel's own binding-resolution fallback (DD-144) — the declared prefix
# is read from the source Turtle text; that syntax alone is used, never a raw fact lookup.
# --------------------------------------------------------------------------------------
_PREFIX_DECLARATION = re.compile(r"(?im)^\s*@prefix\s+([^:\s]*)\s*:\s*<([^>]*)>\s*\.")


def _declared_prefixes(source_path: str | None) -> dict[str, tuple[str, ...]]:
    if not source_path:
        return {}
    path = Path(source_path)
    if not path.is_file() or path.suffix.lower() not in {".ttl", ".turtle"}:
        return {}
    text = path.read_text(encoding="utf-8")
    prefixes: dict[str, list[str]] = {}
    for match in _PREFIX_DECLARATION.finditer(text):
        prefixes.setdefault(match.group(1), []).append(match.group(2))
    return {prefix: tuple(namespaces) for prefix, namespaces in prefixes.items()}


def _namespace_for_prefix(loaded, root_path: Path, prefix: str) -> str | None:
    """Resolve a declared Turtle ``@prefix`` to its namespace across the closure.

    Root-declared prefixes win; an imported-only prefix is usable only when every
    declaration across the closure agrees on the same namespace.

    A root ontology conventionally self-declares its own terms under the empty/default
    prefix (``@prefix : <...>``) rather than an explicit alias for its own domain name --
    ``model/ontologies/party.ttl`` typically declares ``@prefix : <https://.../party#> .``,
    never ``@prefix party: <...>``. An author naturally typing the domain name itself as an
    explicit qname prefix (e.g. ``party:Branch`` while working in the ``party`` domain) would
    otherwise get a spurious "no declared prefix matches" error even though ``:Branch`` and
    the full IRI both resolve fine. So when *prefix* matches nothing declared and equals the
    root ontology's own file stem (its domain name), fall back to the root's default-prefix
    namespace, if one is declared.
    """
    root = str(root_path.resolve())
    root_namespace: str | None = None
    root_default_namespace: str | None = None
    imported_namespaces: set[str] = set()
    for source in loaded.sources:
        path = source.manifest.source_path
        if not path:
            continue
        is_root = str(Path(path).resolve()) == root
        declared = _declared_prefixes(path)
        namespaces = declared.get(prefix)
        if namespaces:
            if is_root:
                root_namespace = namespaces[-1]
            else:
                imported_namespaces.update(namespaces)
        if is_root:
            default_namespaces = declared.get("")
            if default_namespaces:
                root_default_namespace = default_namespaces[-1]
    if root_namespace is not None:
        return root_namespace
    if len(imported_namespaces) == 1:
        return next(iter(imported_namespaces))
    if root_default_namespace is not None and prefix == root_path.stem:
        return root_default_namespace
    return None


def resolve_token_uri(loaded, root_path: Path, token: str) -> str | None:
    """Resolve *token* (a full IRI or a ``prefix:Local`` qname) to a full URI, or ``None``."""
    if not token:
        return None
    if "://" in token or token.startswith("urn:"):
        return token
    if ":" not in token:
        return None
    prefix, _, local = token.partition(":")
    namespace = _namespace_for_prefix(loaded, root_path, prefix)
    if namespace is None:
        return None
    return namespace + local


# --------------------------------------------------------------------------------------
# Binding evidence.
# --------------------------------------------------------------------------------------
def _sniff_binding_domain(text: str) -> str | None:
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(document, dict):
        return None
    metadata = document.get("metadata")
    return str(metadata.get("domain", "")) if isinstance(metadata, dict) else None


def _sniff_binding_target_class(text: str) -> str:
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return ""
    if not isinstance(document, dict):
        return ""
    target = document.get("target")
    return str(target.get("class", "")) if isinstance(target, dict) else ""


def _render_expression(expression: Any) -> str:
    """Render a closed scalar expression compactly for advisory display."""
    if isinstance(expression, ExprColumn):
        return expression.column
    return f"<{type(expression).__name__}>"


def _autodetect_binding(
    loaded, ontology_path: Path, bindings_dir: Path, class_uri: str
) -> tuple[Path | None, tuple[str, ...]]:
    """Return the single binding whose ``target.class`` resolves to *class_uri*.

    Returns ``(None, notes)`` when zero or more-than-one candidate is found — fit-report
    never guesses which of several bindings the caller meant.
    """
    domain = ontology_path.stem
    candidates: list[Path] = []
    for path in sorted(bindings_dir.glob("*.binding.yaml")):
        text = path.read_text(encoding="utf-8")
        binding_domain = _sniff_binding_domain(text)
        if binding_domain and binding_domain != domain:
            continue
        token = _sniff_binding_target_class(text)
        if not token:
            continue
        resolved = resolve_token_uri(loaded, ontology_path, token)
        if resolved == class_uri:
            candidates.append(path)
    if len(candidates) == 1:
        return candidates[0], ()
    if len(candidates) > 1:
        names = ", ".join(str(p) for p in candidates)
        return None, (
            f"{len(candidates)} bindings target this class ({names}); "
            "pass --binding to disambiguate.",
        )
    return None, ()


def _binding_evidence(
    loaded,
    ontology_path: Path,
    binding_path: Path,
    universe_by_uri: dict[str, dict[str, Any]],
) -> tuple[dict[str, str], tuple[TechnicalFieldSummary, ...], tuple[str, ...]]:
    """Return ``(populated_source_by_uri, technical_fields, notes)`` from one binding."""
    text = binding_path.read_text(encoding="utf-8")
    try:
        binding: EntityBinding = load_entity_binding(text, path=str(binding_path))
    except CompileError as exc:
        messages = "; ".join(item.message for item in exc.diagnostics)
        return (
            {},
            (),
            (f"binding at {binding_path} failed to parse and was skipped: {messages}",),
        )

    populated: dict[str, str] = {}
    for field_mapping in binding.fields:
        resolved = resolve_token_uri(loaded, ontology_path, field_mapping.property)
        if resolved in universe_by_uri and resolved not in populated:
            populated[resolved] = _render_expression(field_mapping.expression)

    technical_fields = tuple(
        TechnicalFieldSummary(name=item.name, purpose=item.purpose)
        for item in binding.technical_fields
    )
    return populated, technical_fields, ()


# --------------------------------------------------------------------------------------
# propose-alignment evidence.
# --------------------------------------------------------------------------------------
def _find_source_alignment(
    analysis_dir: Path, system: str, table: str
) -> tuple[Path, dict[str, Any]] | None:
    for alignment_path in sorted(analysis_dir.glob("*-alignment.yaml")):
        try:
            document = yaml.safe_load(alignment_path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(document, dict):
            continue
        for table_dict in document.get("tables", ()) or ():
            if not isinstance(table_dict, dict):
                continue
            if (
                str(table_dict.get("system", "")).lower() == system.lower()
                and str(table_dict.get("table", "")).lower() == table.lower()
            ):
                return alignment_path, table_dict
    return None


def _source_alignment_evidence(
    table_dict: dict[str, Any],
    name_to_uri: dict[str, str],
) -> tuple[dict[str, str], tuple[OrphanColumn, ...]]:
    """Return ``(populated_source_by_uri, orphan_columns)`` from one aligned table."""
    populated: dict[str, str] = {}
    orphans: dict[str, OrphanColumn] = {}
    for column_dict in table_dict.get("columns", ()) or ():
        if not isinstance(column_dict, dict):
            continue
        column_name = str(column_dict.get("column", ""))
        ref_property = str(column_dict.get("ref_property") or "")
        if ref_property and ref_property in name_to_uri:
            uri = name_to_uri[ref_property]
            if uri not in populated:
                populated[uri] = column_name
        elif column_name:
            orphans[column_name] = OrphanColumn(
                column=column_name,
                data_type=str(column_dict.get("data_type", "")),
                reason=str(column_dict.get("rationale", "")),
            )
    for custom_dict in table_dict.get("custom_columns", ()) or ():
        if not isinstance(custom_dict, dict):
            continue
        column_name = str(custom_dict.get("column", ""))
        if column_name and column_name not in orphans:
            orphans[column_name] = OrphanColumn(
                column=column_name,
                data_type=str(custom_dict.get("data_type", "")),
                reason=str(custom_dict.get("rationale", "")),
            )
    return populated, tuple(orphans[key] for key in sorted(orphans))


# --------------------------------------------------------------------------------------
# Entry point.
# --------------------------------------------------------------------------------------
def run_fit_report(
    ontology_path: Path,
    class_token: str,
    *,
    catalog_path: Path | None = None,
    binding_path: Path | None = None,
    bindings_dir: Path | None = None,
    source: str | None = None,
    analysis_dir: Path | None = None,
) -> FitReportResult:
    """Compute the advisory fit report for one class against one evidence source.

    Args:
        ontology_path: Path to the domain ontology TTL that declares/imports *class_token*.
        class_token: A full class IRI or a ``prefix:Local`` qname declared in that ontology.
        catalog_path: Optional explicit XML catalog for import resolution.
        binding_path: An explicit ``EntityBinding`` YAML to use as evidence (highest priority).
        bindings_dir: A directory of ``*.binding.yaml`` files to auto-detect a single binding
            whose ``target.class`` resolves to *class_token*, when *binding_path* is not given.
        source: ``"<system>.<table>"`` — looked up in a ``propose-alignment`` output under
            *analysis_dir* when no binding evidence is used.
        analysis_dir: Directory holding ``*-alignment.yaml`` files (``propose-alignment``
            output).

    Returns:
        A :class:`FitReportResult`. Raises :class:`FitReportError` only when *class_token*
        itself cannot be resolved — every other gap (no evidence, ambiguous binding, ...) is
        reported advisory-style in ``notes`` rather than raised.
    """
    loaded = load_ontology(
        ontology_path,
        catalog_path=catalog_path,
        profile=SemanticProfile.KAIROS_DESIGN,
    )
    class_uri = resolve_token_uri(loaded, ontology_path, class_token)
    if class_uri is None:
        raise FitReportError(
            f"cannot resolve class token {class_token!r}: no declared prefix matches it in "
            f"{ontology_path}"
        )
    index = loaded.semantic_index
    cls = index.class_by_uri(class_uri)
    if cls is None:
        raise FitReportError(f"class does not resolve in the scoped domain closure: {class_uri}")

    universe = index.class_properties(class_uri)
    universe_by_uri = {row["property_uri"]: row for row in universe}
    name_to_uri = {row["name"]: row["property_uri"] for row in universe}

    notes: list[str] = []
    evidence_kind = "none"
    evidence_path: str | None = None
    source_system: str | None = None
    source_table: str | None = None
    populated_source: dict[str, str] = {}
    orphan_columns: tuple[OrphanColumn, ...] = ()
    technical_fields: tuple[TechnicalFieldSummary, ...] = ()

    resolved_binding_path = binding_path
    if resolved_binding_path is None and bindings_dir is not None and bindings_dir.is_dir():
        resolved_binding_path, autodetect_notes = _autodetect_binding(
            loaded, ontology_path, bindings_dir, class_uri
        )
        notes.extend(autodetect_notes)

    if resolved_binding_path is not None:
        populated_source, technical_fields, binding_notes = _binding_evidence(
            loaded, ontology_path, resolved_binding_path, universe_by_uri
        )
        notes.extend(binding_notes)
        if not binding_notes:
            evidence_kind = "binding"
            evidence_path = str(resolved_binding_path)

    if evidence_kind == "none" and source:
        if "." not in source:
            raise FitReportError(f"--source must be '<system>.<table>', got {source!r}")
        source_system, source_table = source.split(".", 1)
        if analysis_dir is not None and analysis_dir.is_dir():
            found = _find_source_alignment(analysis_dir, source_system, source_table)
            if found is not None:
                alignment_path, table_dict = found
                populated_source, orphan_columns = _source_alignment_evidence(
                    table_dict, name_to_uri
                )
                evidence_kind = "source-alignment"
                evidence_path = str(alignment_path)
            else:
                notes.append(
                    f"no propose-alignment evidence found for {source} under {analysis_dir}."
                )
        else:
            notes.append(
                "no propose-alignment output directory found; run `kairos-ontology "
                "propose-alignment` first, or pass --binding directly."
            )

    if evidence_kind == "none" and not notes:
        notes.append(
            "no evidence source found: pass --binding, or --source with existing "
            "propose-alignment output, to see what is already populated."
        )

    populated = tuple(
        PopulatedProperty(
            property_uri=uri,
            name=universe_by_uri[uri]["name"],
            origin=universe_by_uri[uri]["origin"],
            distance=universe_by_uri[uri]["distance"],
            source=populated_source[uri],
        )
        for uri in sorted(populated_source)
        if uri in universe_by_uri
    )
    populated_uris = {item.property_uri for item in populated}
    # #451: when no evidence source was found, do NOT list every universe property as
    # "unpopulated" — that reads like a finding ("everything is empty") when the truth is
    # "nothing was evaluated." Leave the unpopulated list empty; the notes explain absent
    # evidence and the remediation path.
    if evidence_kind == "none":
        unpopulated: tuple[UnpopulatedProperty, ...] = ()
    else:
        unpopulated = tuple(
            UnpopulatedProperty(
                property_uri=row["property_uri"],
                name=row["name"],
                property_type=row["property_type"],
                origin=row["origin"],
                distance=row["distance"],
            )
            for row in universe
            if row["property_uri"] not in populated_uris
        )

    return FitReportResult(
        class_uri=class_uri,
        class_name=cls.name,
        evidence_kind=evidence_kind,
        evidence_path=evidence_path,
        source_system=source_system,
        source_table=source_table,
        populated=populated,
        unpopulated=unpopulated,
        orphan_columns=orphan_columns,
        technical_fields=technical_fields,
        notes=tuple(notes),
    )


# --------------------------------------------------------------------------------------
# #452 — inverse class→candidate-source scan (deterministic tier only).
#
# Given a canonical class, scan every source table across every source system under
# ``integration/sources/`` and report which tables have columns whose names deterministically
# match the class's datatype or object properties. This is the inverse of fit-report's
# usual direction (source→class): here we start from the class and find candidate sources.
#
# Only the deterministic tier (exact column-name equality via the class-name-aware candidate
# ladder from ``scaffold_binding.match_columns_to_properties``) is evaluated. What was NOT
# evaluated — LLM-assisted semantic matching, fuzzy/phonetic name similarity, value-sample
# inference, or cross-system relationship discovery — is explicitly labelled in the result
# notes so a reader never mistakes a short candidate list for a completeness finding.
# --------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CandidateSourceMatch:
    """One source table with at least one column matching a class property."""

    source_system: str
    source_table: str
    matched_properties: tuple[str, ...]
    matched_columns: tuple[str, ...]
    total_columns: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_system": self.source_system,
            "source_table": self.source_table,
            "matched_properties": list(self.matched_properties),
            "matched_columns": list(self.matched_columns),
            "total_columns": self.total_columns,
        }


@dataclass(frozen=True, slots=True)
class InverseScanResult:
    """Deterministic inverse scan: given a class, which source tables look like candidates."""

    class_uri: str
    class_name: str
    universe_property_count: int
    candidates: tuple[CandidateSourceMatch, ...]
    source_systems_scanned: tuple[str, ...]
    tables_scanned: int
    notes: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "advisory": ADVISORY_NOTICE,
            "class_uri": self.class_uri,
            "class_name": self.class_name,
            "universe_property_count": self.universe_property_count,
            "candidates": [item.to_dict() for item in self.candidates],
            "source_systems_scanned": list(self.source_systems_scanned),
            "tables_scanned": self.tables_scanned,
            "notes": list(self.notes),
        }


_INVERSE_SCAN_NOT_EVALUATED = (
    "Not evaluated: LLM-assisted semantic matching, fuzzy/phonetic name similarity, "
    "value-sample inference, and cross-system relationship discovery. A short candidate "
    "list is NOT a completeness finding — it means only exact column-name matches were found."
)


def run_inverse_scan(
    ontology_path: Path,
    class_token: str,
    hub_root: Path,
    *,
    catalog_path: Path | None = None,
) -> InverseScanResult:
    """Scan all source tables for deterministic column-name matches to *class_token*'s properties.

    This is the inverse of :func:`run_fit_report`: instead of "given a source, what is
    populated," it answers "given a class, which source tables have columns that
    deterministically match its properties?"

    Only the deterministic tier is evaluated — exact normalized column-name equality via
    the class-name-aware candidate ladder from
    :func:`scaffold_binding.match_columns_to_properties`. What was not evaluated is
    explicitly labelled in the result notes (LLM matching, fuzzy similarity, etc.).

    Args:
        ontology_path: Path to the domain ontology TTL that declares/imports *class_token*.
        class_token: A full class IRI or a ``prefix:Local`` qname.
        hub_root: The hub root directory (containing ``integration/sources/``).
        catalog_path: Optional explicit XML catalog for import resolution.

    Returns:
        An :class:`InverseScanResult`. Raises :class:`FitReportError` only when *class_token*
        cannot be resolved.
    """
    from .scaffold_binding import (
        SourceColumn,
        list_source_tables,
        match_columns_to_properties,
    )

    loaded = load_ontology(
        ontology_path,
        catalog_path=catalog_path,
        profile=SemanticProfile.KAIROS_DESIGN,
    )
    class_uri = resolve_token_uri(loaded, ontology_path, class_token)
    if class_uri is None:
        raise FitReportError(
            f"cannot resolve class token {class_token!r}: no declared prefix matches it in "
            f"{ontology_path}"
        )
    index = loaded.semantic_index
    cls = index.class_by_uri(class_uri)
    if cls is None:
        raise FitReportError(f"class does not resolve in the scoped domain closure: {class_uri}")

    universe = index.class_properties(class_uri)
    universe_property_count = len(universe)

    sources_dir = hub_root / "integration" / "sources"
    source_systems = sorted(
        d.name for d in sources_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
    ) if sources_dir.is_dir() else []

    candidates: list[CandidateSourceMatch] = []
    tables_scanned = 0

    for system in source_systems:
        tables = list_source_tables(hub_root, system)
        for table_name, column_dicts in sorted(tables.items()):
            tables_scanned += 1
            columns = tuple(
                SourceColumn(
                    name=str(col["name"]),
                    data_type=str(col.get("data_type") or ""),
                    nullable=bool(col.get("nullable")),
                    samples=tuple(col.get("samples") or ()),
                    distinct_count=col.get("distinct_count"),
                    is_primary_key=False,
                )
                for col in column_dicts
            )
            if not columns:
                continue
            match = match_columns_to_properties(
                columns, universe, target_class_uri=class_uri
            )
            if match.fields or match.relationship_candidates:
                matched_props = tuple(sorted(match.fields.keys()))
                matched_cols = tuple(sorted(match.fields.keys()))
                if match.relationship_candidates:
                    matched_props = matched_props + tuple(sorted(match.relationship_candidates.keys()))
                    matched_cols = matched_cols + tuple(sorted(match.relationship_candidates.keys()))
                candidates.append(
                    CandidateSourceMatch(
                        source_system=system,
                        source_table=table_name,
                        matched_properties=matched_props,
                        matched_columns=matched_cols,
                        total_columns=len(columns),
                    )
                )

    candidates.sort(key=lambda c: (-len(c.matched_properties), c.source_system, c.source_table))

    notes = [
        f"Scanned {tables_scanned} table(s) across {len(source_systems)} source system(s) "
        f"using deterministic column-name matching only.",
        _INVERSE_SCAN_NOT_EVALUATED,
    ]

    return InverseScanResult(
        class_uri=class_uri,
        class_name=cls.name,
        universe_property_count=universe_property_count,
        candidates=tuple(candidates),
        source_systems_scanned=tuple(source_systems),
        tables_scanned=tables_scanned,
        notes=tuple(notes),
    )
