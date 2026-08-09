# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Core logic for ``kairos-ontology scaffold-binding``.

Writes a first-draft v5 ``EntityBinding`` YAML (``core/compiler/bindings.py``) for one Bronze
source table, so authoring a binding is no longer 100% manual. Reuses, rather than
reimplements:

* DD-144 accelerator-direct binding resolution -- a scaffolded ``target.class`` defaults to
  pointing directly at an accelerator/reference-model class; no local subclass is minted.
* DD-139 ``technicalFields:`` -- primary-key / foreign-key-shaped columns that do not resolve
  to a real ontology property are materialized as technical fields instead of being silently
  dropped or given a decorative local property (C2 enforcement).
* DD-138 ``externalReference`` -- the ``line-item-child`` archetype scaffolds one heavily
  commented worked example of the cross-domain relationship shape.
* ``fit-report``'s (``core/fit_report.py``) class-token resolution
  (:func:`kairos_ontology.core.fit_report.resolve_token_uri`) and the DD-103 semantic index's
  ``class_properties`` for the target class's full property universe.
* ``analyse_sources.parse_source_vocabulary`` for reading a Bronze table's columns, and its
  ``distinct_count`` field (for the passthrough archetype's grain proposal).

Three fields carry irreducible modeling judgement and are **never** silently guessed for any
canonical-tier archetype: ``grain.columns``, ``identity.sourceKey``, and (``merged-master``
only) the ``conformance:`` survivorship policy. Each is written as an obviously-invalid
``<CONFIRM_...>`` sentinel placeholder; the existing compiler safety diagnostics
(``binding.unknown-key-column`` for a grain/identity column that does not exist, or a JSON
Schema violation for an out-of-range ``sourcePrecedence``) already reject these until a human
supplies the real answer -- no new compiler enforcement is needed.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from rdflib import URIRef
from rdflib.namespace import OWL

from .analyse_sources import parse_source_primary_keys, parse_source_vocabulary
from .binding_archetypes import BindingArchetype, load_binding_archetype
from .compiler.bindings import (
    Expression,
    ExprCase,
    ExprColumn,
    ExprFunction,
    ExprLiteral,
    ExprMacro,
    ExprNull,
    ExprOperator,
    load_entity_binding,
)
from .fit_report import resolve_token_uri
from .ontology_loader import SemanticProfile, load_ontology
from .reference_modules import load_accelerator_module_config, resolve_hub_accelerator_detailed

SENTINEL_GRAIN_COLUMN = "<CONFIRM_GRAIN_COLUMN>"
SENTINEL_IDENTITY_KEY = "<CONFIRM_IDENTITY_KEY>"
SENTINEL_SOURCE_PRECEDENCE = -1
SENTINEL_DEDUP_KEY = "<CONFIRM_DEDUP_KEY>"
SENTINEL_ORDER_COLUMN = "<CONFIRM_ORDER_COLUMN>"
SENTINEL_PARENT_PROPERTY = "<CONFIRM_PARENT_RELATIONSHIP_PROPERTY>"
SENTINEL_PARENT_CLASS = "<CONFIRM_PARENT_CLASS>"
SENTINEL_PARENT_DOMAIN = "<CONFIRM_PARENT_DOMAIN>"
SENTINEL_PARENT_ENTITY_NAME = "<CONFIRM_PARENT_ENTITY_NAME>"
SENTINEL_PARENT_KEY_COLUMN = "<CONFIRM_PARENT_KEY_COLUMN>"
SENTINEL_LOCAL_FK_COLUMN = "<CONFIRM_LOCAL_FK_COLUMN>"

_TECHNICAL_FIELD_TYPES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"bigint", re.IGNORECASE), "int64"),
    (re.compile(r"smallint|tinyint|^int\b|integer|^int4?$", re.IGNORECASE), "int32"),
    (re.compile(r"decimal|numeric|money|float|double|real", re.IGNORECASE), "decimal"),
    (re.compile(r"\bbool|^bit$", re.IGNORECASE), "boolean"),
    (re.compile(r"datetime|timestamp", re.IGNORECASE), "timestamp"),
    (re.compile(r"^date$", re.IGNORECASE), "date"),
)

_FK_SHAPED_NAME = re.compile(r"(_id|_fk|_code)$", re.IGNORECASE)
_EVENT_TIME_NAME = re.compile(r"(event.?time|occurred.?at|created.?at|event.?date|timestamp)", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]")


class ScaffoldBindingError(ValueError):
    """Raised for a user-facing ``scaffold-binding`` failure (bad input, unresolved class)."""


# --------------------------------------------------------------------------------------
# Source-column evidence (Bronze contract).
# --------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SourceColumn:
    """One Bronze source column plus the table-level primary-key flag."""

    name: str
    data_type: str
    nullable: bool
    samples: tuple[str, ...]
    distinct_count: int | None
    is_primary_key: bool


def _system_dir(hub_root: Path, system: str) -> Path:
    return hub_root / "integration" / "sources" / system


def list_source_tables(hub_root: Path, system: str) -> dict[str, list[dict[str, Any]]]:
    """Return every table's raw column-dict list for *system* (merged across vocabulary files)."""
    system_dir = _system_dir(hub_root, system)
    tables: dict[str, list[dict[str, Any]]] = {}
    if not system_dir.is_dir():
        return tables
    for ttl in sorted(system_dir.glob("*.ttl")):
        for table, columns in parse_source_vocabulary(ttl).items():
            tables.setdefault(table, []).extend(columns)
    return tables


def _primary_key_columns(hub_root: Path, system: str, table: str) -> tuple[str, ...]:
    # Reuses analyse_sources.parse_source_primary_keys (an already-DD-103-exempted Bronze
    # vocabulary parse site) instead of parsing the vocabulary graph directly here.
    system_dir = _system_dir(hub_root, system)
    for ttl in sorted(system_dir.glob("*.ttl")):
        try:
            keys = parse_source_primary_keys(ttl)
        except Exception:  # noqa: BLE001 - a malformed sibling vocabulary file must not block
            continue
        if table in keys and keys[table]:
            return keys[table]
    return ()


def load_table_columns(hub_root: Path, system: str, table: str) -> tuple[SourceColumn, ...]:
    """Return the resolved :class:`SourceColumn` list for one Bronze table.

    Raises:
        ScaffoldBindingError: if the table cannot be found under
            ``integration/sources/<system>/``.
    """
    tables = list_source_tables(hub_root, system)
    matched = table if table in tables else next(
        (name for name in tables if name.lower() == table.lower()), None
    )
    if matched is None:
        available = ", ".join(sorted(tables)) or "(none)"
        raise ScaffoldBindingError(
            f"Table '{table}' not found for source system '{system}' under "
            f"{_system_dir(hub_root, system)}. Available tables: {available}."
        )
    pk_columns = set(_primary_key_columns(hub_root, system, matched))
    return tuple(
        SourceColumn(
            name=col["name"],
            data_type=str(col.get("data_type") or ""),
            nullable=bool(col.get("nullable")),
            samples=tuple(col.get("samples") or ()),
            distinct_count=col.get("distinct_count"),
            is_primary_key=col["name"] in pk_columns,
        )
        for col in tables[matched]
    )


def list_unscaffolded_tables(hub_root: Path, system: str) -> tuple[str, ...]:
    """Return the sorted tables under ``integration/sources/<system>/`` with no binding yet.

    Read-only: matches by ``source.relation`` (``"<system>.<table>"``) across every
    ``*.binding.yaml`` under ``integration/bindings/``, of any tier.
    """
    tables = list_source_tables(hub_root, system)
    bound_relations: set[str] = set()
    bindings_dir = hub_root / "integration" / "bindings"
    if bindings_dir.is_dir():
        for path in sorted(bindings_dir.glob("*.binding.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                continue
            if not isinstance(data, dict):
                continue
            source = data.get("source")
            if isinstance(source, dict):
                relation = source.get("relation")
                if isinstance(relation, str) and relation:
                    bound_relations.add(relation.lower())
    return tuple(
        table
        for table in sorted(tables)
        if f"{system}.{table}".lower() not in bound_relations
    )


# --------------------------------------------------------------------------------------
# Domain inference (analyse-sources affinity evidence).
# --------------------------------------------------------------------------------------
def infer_domain(analysis_dir: Path | None, system: str, table: str) -> str | None:
    """Infer the hub domain for *table* from an existing ``analyse-sources`` affinity report.

    Reads ``<analysis_dir>/<system>-affinity.yaml`` (``analyse_sources.write_analysis_output``'s
    on-disk shape) and returns the primary ``domain`` id assigned to *table*, or ``None`` when
    no such report/table entry exists -- callers must then require an explicit ``--domain``.
    """
    if analysis_dir is None or not analysis_dir.is_dir():
        return None
    affinity_path = analysis_dir / f"{system}-affinity.yaml"
    if not affinity_path.is_file():
        return None
    try:
        data = yaml.safe_load(affinity_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    for entry in data.get("tables", ()) or ():
        if isinstance(entry, dict) and str(entry.get("table", "")).lower() == table.lower():
            domain = entry.get("domain")
            return str(domain) if domain else None
    return None


# --------------------------------------------------------------------------------------
# Column <-> property matching (C2: never mint a decorative local property).
# --------------------------------------------------------------------------------------
def _normalize(name: str) -> str:
    return _NON_ALNUM.sub("", name.lower())


def match_columns_to_properties(
    columns: tuple[SourceColumn, ...], universe: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Return ``{column_name: universe_row}`` for exact normalized-name matches.

    Deterministic, no LLM: a column matches a property when their names are equal after
    stripping non-alphanumeric characters and lowercasing (``org_id`` <-> ``orgId``). *universe*
    rows are consumed in their given (URI-sorted) order so a rare normalized-name collision
    resolves deterministically to the first (lexicographically smallest URI) candidate.
    """
    by_normalized: dict[str, dict[str, Any]] = {}
    for row in universe:
        by_normalized.setdefault(_normalize(str(row["name"])), row)
    return {
        column.name: by_normalized[_normalize(column.name)]
        for column in columns
        if _normalize(column.name) in by_normalized
    }


def _technical_field_type(data_type: str) -> str:
    for pattern, canonical in _TECHNICAL_FIELD_TYPES:
        if pattern.search(data_type):
            return canonical
    return "string"


def classify_technical_field(column: SourceColumn) -> str | None:
    """Return the DD-139 ``purpose`` for an unmapped column, or ``None`` (a true orphan).

    Heuristic: a declared primary-key column becomes an ``identity`` technical field; any
    other unmapped column whose name is FK-shaped (``*_id`` / ``*_fk`` / ``*_code``) becomes a
    ``relationship`` technical field. Everything else is a genuine orphan column.
    """
    if column.is_primary_key:
        return "identity"
    if _FK_SHAPED_NAME.search(column.name):
        return "relationship"
    return None


# --------------------------------------------------------------------------------------
# Grain proposal (passthrough only -- the one archetype allowed to derive it).
# --------------------------------------------------------------------------------------
def propose_grain_columns(
    columns: tuple[SourceColumn, ...], pk_columns: tuple[str, ...]
) -> tuple[tuple[str, ...], str]:
    """Propose ``grain.columns`` for the passthrough archetype. Returns ``(columns, note)``.

    Priority: the non-nullable column with the highest ``distinct_count``; falling back (only
    when *no* non-nullable column carries ``distinct_count`` evidence, e.g. samples were never
    profiled) to the Bronze contract's declared ``primaryKeyColumns``, then the first
    non-nullable column, then the first column at all.
    """
    non_nullable = [c for c in columns if not c.nullable]
    with_distinct = [c for c in non_nullable if c.distinct_count is not None]
    if with_distinct:
        best = max(with_distinct, key=lambda c: (c.distinct_count, c.name))
        return (best.name,), (
            f"grain.columns proposed from the highest distinct_count among non-nullable "
            f"columns ({best.name}: {best.distinct_count} distinct values)."
        )
    if pk_columns:
        return tuple(pk_columns), (
            "grain.columns proposed from the Bronze contract's declared primaryKeyColumns "
            "(no distinct_count evidence was available -- run analyse-sources with sampling "
            "for a stronger signal next time)."
        )
    if non_nullable:
        return (non_nullable[0].name,), (
            f"grain.columns fell back to the first non-nullable column ({non_nullable[0].name}): "
            "no distinct_count or primary-key evidence was available. Verify this is a real key."
        )
    if columns:
        return (columns[0].name,), (
            f"grain.columns fell back to the first column ({columns[0].name}): every column is "
            "nullable and no distinct_count or primary-key evidence was available. Verify this "
            "is a real key."
        )
    return (), "grain.columns could not be proposed: the table has no columns."


def _detect_event_grain_hint(columns: tuple[SourceColumn, ...], pk_columns: tuple[str, ...]) -> str:
    """Return an event-stream grain sentinel, embedding detected hints when identifiable.

    Still an obviously-invalid ``<CONFIRM_...>`` placeholder (grain is never silently guessed)
    -- the detected column names are folded into the sentinel text as a hint only.
    """
    time_column = next((c.name for c in columns if _EVENT_TIME_NAME.search(c.name)), None)
    subject_column = next(iter(pk_columns), None) or next(
        (c.name for c in columns if c.name.lower().endswith("_id")), None
    )
    hints = []
    if time_column:
        hints.append(f"event_time~{time_column}")
    if subject_column:
        hints.append(f"subject~{subject_column}")
    if not hints:
        return SENTINEL_GRAIN_COLUMN
    return f"<CONFIRM_GRAIN_COLUMN:{','.join(hints)}>"


# --------------------------------------------------------------------------------------
# Domain namespace derivation + machine-managed ontology stub (DD-144 point 3).
# --------------------------------------------------------------------------------------
def _read_hub_name(hub_root: Path) -> str | None:
    config_path = hub_root / "kairos.yaml"
    if not config_path.is_file():
        return None
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    if isinstance(data, dict):
        name = data.get("name")
        if isinstance(name, str) and name.strip():
            return re.sub(r"[^a-z0-9-]", "-", name.strip().lower())
    return None


def _derive_domain_ontology_iri(
    hub_root: Path, domain: str, *, catalog_path: Path | None
) -> tuple[str, list[str]]:
    """Derive a new domain's ontology IRI, mirroring a sibling domain's namespace pattern.

    There is no persisted hub-wide "company domain" convention to read back (the ``init``/
    ``new-repo`` scaffolds bake ``{company_domain}`` literally into each generated ontology
    file and do not retain it in ``kairos.yaml``), so the most defensible reconstruction is to
    mirror whichever base namespace an existing sibling ``model/ontologies/*.ttl`` already
    uses. With no sibling domain yet, a placeholder ``https://<hub-name>.kairos.local/ont``
    base is used and flagged as a note for the author to confirm.

    Every sibling is read through the DD-103 canonical loader (:func:`load_ontology`), never
    parsed directly -- ``degraded=True`` tolerates a sibling whose own imports do not resolve
    in this context, since only its *own* declared ``owl:Ontology`` IRI (the ``import_depth==0``
    manifest entry) is needed here.
    """
    notes: list[str] = []
    ontologies_dir = hub_root / "model" / "ontologies"
    base: str | None = None
    if ontologies_dir.is_dir():
        for path in sorted(ontologies_dir.glob("*.ttl")):
            if path.stem == domain:
                continue
            try:
                loaded = load_ontology(
                    path,
                    catalog_path=catalog_path,
                    profile=SemanticProfile.ASSERTED,
                    degraded=True,
                )
            except Exception:  # noqa: BLE001 - a malformed/unresolvable sibling must not block
                continue
            root_entry = next(
                (item for item in loaded.manifest if item.import_depth == 0), None
            )
            iri = root_entry.ontology_iri if root_entry else None
            if not iri:
                continue
            sibling_domain = path.stem
            if iri.endswith("/" + sibling_domain):
                base = iri[: -(len(sibling_domain) + 1)]
                break
    if base is None:
        hub_name = _read_hub_name(hub_root) or "hub"
        base = f"https://{hub_name}.kairos.local/ont"
        notes.append(
            "no sibling model/ontologies/*.ttl declares an owl:Ontology IRI to mirror; used a "
            f"placeholder base namespace ({base}) for the new domain ontology -- update the "
            "ontology IRI/prefix to your organization's real convention before publishing."
        )
    return f"{base}/{domain}", notes


def resolve_accelerator_import(
    *,
    hub_root: Path | None,
    ref_models_dir: Path | None,
    accelerator: str | None,
    domain: str,
    target_class_uri: str,
) -> tuple[str | None, tuple[str, ...]]:
    """Resolve the accelerator module document IRI that owns *target_class_uri*.

    Reuses the same typed ``data-domains.yaml`` module-profile registry
    (:mod:`kairos_ontology.core.reference_modules`) every other accelerator-aware command
    reads: a module profile's ``term_namespaces`` already declares which namespace(s) it owns,
    so the owning module (and its ``ontology_iri`` document to ``owl:imports``) is found by
    checking which profile's ``term_namespaces`` prefixes *target_class_uri*. Returns
    ``(None, notes)`` -- never raises -- when no accelerator/registry is available or the
    owning module cannot be determined unambiguously; the caller surfaces the notes and the
    human adds the import by hand.
    """
    if ref_models_dir is None:
        return None, (
            "no reference-models checkout found; owl:imports for the accelerator module was "
            "not added automatically -- add it by hand.",
        )
    try:
        resolution = resolve_hub_accelerator_detailed(
            explicit=accelerator,
            hub_root=hub_root,
            ref_models_dir=ref_models_dir,
            domain_hint=[domain],
        )
    except ValueError as exc:
        return None, (f"could not resolve an accelerator pack: {exc}",)
    if resolution.accelerator is None:
        return None, (
            "no accelerator pack could be resolved; owl:imports for the accelerator module "
            "was not added automatically -- add it by hand.",
        )
    config = load_accelerator_module_config(ref_models_dir, resolution.accelerator)
    if config is None:
        return None, (
            f"accelerator {resolution.accelerator!r} has no data-domains.yaml module "
            "configuration; owl:imports was not added automatically -- add it by hand.",
        )
    candidates = [
        profile
        for profile in config.profiles
        if any(target_class_uri.startswith(namespace) for namespace in profile.term_namespaces)
    ]
    if len(candidates) == 1:
        return candidates[0].ontology_iri, ()
    if len(candidates) > 1:
        names = ", ".join(sorted(p.id for p in candidates))
        return None, (
            f"{len(candidates)} accelerator module profiles claim the namespace of "
            f"{target_class_uri} ({names}); owl:imports was not added automatically -- add "
            "the correct one by hand.",
        )
    return None, (
        f"no accelerator module profile in {config.source_path} declares a term_namespaces "
        f"entry covering {target_class_uri}; owl:imports was not added automatically -- add "
        "it by hand.",
    )


@dataclass(frozen=True, slots=True)
class OntologyStubOutcome:
    """What happened to ``model/ontologies/<domain>.ttl`` during this scaffold run.

    ``preview_path`` is set only for a ``dry_run=True`` call that *would* have created or
    modified ``path``: the content that would have been written was instead written to this
    temporary file so the caller can still load/validate it (class resolution, property
    universe) without touching the real hub. The caller is responsible for deleting it.
    """

    path: Path
    created: bool
    import_added: bool
    accelerator_ontology_iri: str | None
    notes: tuple[str, ...] = ()
    dry_run: bool = False
    preview_path: Path | None = None


_STUB_HEADER = (
    "# MACHINE-MANAGED by kairos-ontology scaffold-binding — do not hand-edit; a local class\n"
    "# here is fine, but the owl:imports block above is kept in sync automatically.\n"
)


def _write_preview_ttl(text: str) -> Path:
    """Write dry-run-preview Turtle *text* to a fresh temp file and return its path."""
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".ttl", delete=False, encoding="utf-8"
    )
    try:
        handle.write(text)
    finally:
        handle.close()
    return Path(handle.name)


def ensure_domain_ontology_stub(
    hub_root: Path,
    domain: str,
    *,
    accelerator_ontology_iri: str | None,
    catalog_path: Path | None = None,
    dry_run: bool = False,
) -> OntologyStubOutcome:
    """Create or update ``model/ontologies/<domain>.ttl`` per the DD-144 point 3 contract.

    * Missing file: generate a minimal machine-managed stub -- an ``owl:Ontology`` declaration
      plus (when resolved) one ``owl:imports`` triple for the accelerator module that owns the
      target class. Zero locally-declared classes.
    * Existing file: append a **new** ``owl:imports`` triple only when the domain does not
      already import this accelerator module (idempotent); every other line is left untouched.

    An existing file is inspected through the DD-103 canonical loader (:func:`load_ontology`,
    ``degraded=True``), never parsed directly -- its manifest's root (``import_depth==0``) entry
    gives the file's own declared ``owl:Ontology`` subject, and its merged graph is used only to
    check for the specific ``owl:imports`` triple already being present (idempotency).

    ``dry_run=True`` never touches *hub_root*: whenever a create/update would occur, the would-be
    content is written to a throwaway temp file instead (see :class:`OntologyStubOutcome`'s
    ``preview_path``) so a caller can still load/validate the closure.
    """
    path = hub_root / "model" / "ontologies" / f"{domain}.ttl"
    if path.is_file():
        if accelerator_ontology_iri is None:
            return OntologyStubOutcome(path, False, False, None)
        try:
            loaded = load_ontology(
                path, catalog_path=catalog_path, profile=SemanticProfile.ASSERTED, degraded=True
            )
        except Exception as exc:  # noqa: BLE001 - an unloadable existing file must not crash
            return OntologyStubOutcome(
                path,
                False,
                False,
                accelerator_ontology_iri,
                (
                    f"{path} could not be loaded to check/add owl:imports ({exc}); add it by "
                    f"hand: <subject> owl:imports <{accelerator_ontology_iri}> .",
                ),
            )
        root_entry = next((item for item in loaded.manifest if item.import_depth == 0), None)
        subject = root_entry.ontology_iri if root_entry else None
        if not subject:
            return OntologyStubOutcome(
                path,
                False,
                False,
                accelerator_ontology_iri,
                (
                    f"{path} does not declare exactly one owl:Ontology subject; owl:imports "
                    f"was not added automatically -- add it by hand: <subject> owl:imports "
                    f"<{accelerator_ontology_iri}> .",
                ),
            )
        if (URIRef(subject), OWL.imports, URIRef(accelerator_ontology_iri)) in loaded.graph:
            return OntologyStubOutcome(path, False, False, accelerator_ontology_iri)
        text = path.read_text(encoding="utf-8")
        addition = f"\n<{subject}> <http://www.w3.org/2002/07/owl#imports> <{accelerator_ontology_iri}> .\n"
        combined = text.rstrip("\n") + "\n" + addition.lstrip("\n")
        if dry_run:
            return OntologyStubOutcome(
                path, False, True, accelerator_ontology_iri,
                dry_run=True, preview_path=_write_preview_ttl(combined),
            )
        path.write_text(combined, encoding="utf-8")
        return OntologyStubOutcome(path, False, True, accelerator_ontology_iri)

    ontology_iri, base_notes = _derive_domain_ontology_iri(hub_root, domain, catalog_path=catalog_path)
    label = domain.replace("-", " ").replace("_", " ").title()
    predicates = [f'rdfs:label "{label} domain ontology"@en']
    if accelerator_ontology_iri:
        predicates.append(f"owl:imports <{accelerator_ontology_iri}>")
    predicates.append('owl:versionInfo "0.1.0"')
    body = " ;\n    ".join(predicates)
    text = (
        _STUB_HEADER
        + "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        + "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        + "\n"
        + f"<{ontology_iri}> a owl:Ontology ;\n"
        + f"    {body} .\n"
    )
    if dry_run:
        return OntologyStubOutcome(
            path, True, accelerator_ontology_iri is not None, accelerator_ontology_iri,
            tuple(base_notes), dry_run=True, preview_path=_write_preview_ttl(text),
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return OntologyStubOutcome(
        path, True, accelerator_ontology_iri is not None, accelerator_ontology_iri, tuple(base_notes)
    )


# --------------------------------------------------------------------------------------
# Expression AST -> YAML value (for --from-binding field seeding).
# --------------------------------------------------------------------------------------
def _expression_to_yaml_value(expr: Expression) -> Any:
    if isinstance(expr, ExprColumn):
        if not expr.null_policy:
            return expr.column
        return {"column": expr.column, "nullPolicy": expr.null_policy}
    if isinstance(expr, ExprLiteral):
        node: dict[str, Any] = {"literal": expr.lexical, "datatype": expr.datatype}
        if expr.null_policy:
            node["nullPolicy"] = expr.null_policy
        return node
    if isinstance(expr, ExprNull):
        return None
    if isinstance(expr, ExprOperator):
        node = {"op": expr.op, "args": [_expression_to_yaml_value(a) for a in expr.args]}
        if expr.null_policy:
            node["nullPolicy"] = expr.null_policy
        return node
    if isinstance(expr, ExprFunction):
        node = {"fn": expr.fn, "args": [_expression_to_yaml_value(a) for a in expr.args]}
        if expr.null_policy:
            node["nullPolicy"] = expr.null_policy
        return node
    if isinstance(expr, ExprMacro):
        node = {"macro": expr.macro, "args": [_expression_to_yaml_value(a) for a in expr.args]}
        if expr.null_policy:
            node["nullPolicy"] = expr.null_policy
        return node
    if isinstance(expr, ExprCase):
        node = {
            "case": [
                {
                    "when": _expression_to_yaml_value(branch.when),
                    "then": _expression_to_yaml_value(branch.then),
                }
                for branch in expr.branches
            ]
        }
        if expr.else_ is not None:
            node["else"] = _expression_to_yaml_value(expr.else_)
        if expr.null_policy:
            node["nullPolicy"] = expr.null_policy
        return node
    raise TypeError(f"unsupported expression node: {type(expr)!r}")  # pragma: no cover - closed grammar


# --------------------------------------------------------------------------------------
# dbt staging model (passthrough only).
# --------------------------------------------------------------------------------------
def render_staging_sql(
    system: str, table: str, columns: tuple[SourceColumn, ...], *, platform: str = "fabric"
) -> str:
    """Render a conservative dbt staging SELECT for one Bronze table.

    Reuses the existing source-type -> platform-type mapping table in the medallion dbt
    projector (:mod:`kairos_ontology.core.projections.medallion_dbt_projector`) rather than
    inventing a new one. String-shaped columns are trimmed and blank-normalized to NULL;
    everything else is a plain CAST. This model is a convenience artifact only -- a
    passthrough binding's ``source.relation`` binds directly to the Bronze table (Silver
    models consume Bronze via ``source()``, with no staging layer required to compile); wire
    this model in via ``source.dbtModel`` once its cleanup should become authoritative.
    """
    from .projections.medallion_dbt_projector import _source_type_to_target

    lines = [
        "-- MACHINE-GENERATED by kairos-ontology scaffold-binding (passthrough archetype).",
        f"-- Conservative staging cleanup for {system}.{table}: casts every column to its",
        f"-- {platform} target type and normalizes blank strings to NULL.",
        "-- Not yet referenced by any EntityBinding (source.relation binds directly to the",
        "-- Bronze table) -- wire it in via source.dbtModel once ready. Review before",
        "-- productionizing.",
        "",
        "with source as (",
        "    select * from {{ source('" + system + "', '" + table + "') }}",
        "),",
        "",
        "renamed as (",
        "    select",
    ]
    select_lines: list[str] = []
    for column in columns:
        target_type = _source_type_to_target(column.data_type, platform)
        is_stringy = target_type.upper().startswith(("VARCHAR", "STRING", "TEXT", "CHAR", "NCHAR", "NVARCHAR"))
        cast_expr = f"CAST({column.name} AS {target_type})"
        expr = f"NULLIF(TRIM({cast_expr}), '')" if is_stringy else cast_expr
        select_lines.append(f"        {expr} as {column.name}")
    select_lines.append(f"        '{system}' as source_system")
    lines.append(",\n".join(select_lines))
    lines.append("    from source")
    lines.append(")")
    lines.append("")
    lines.append("select * from renamed")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# YAML rendering (structured dict via yaml.safe_dump, then targeted comment injection so
# explanatory prose can sit next to the exact field it explains, mirroring
# schema/example-entity-binding.yaml's comment style).
# --------------------------------------------------------------------------------------
def _insert_comment_before(text: str, top_level_key: str, comment_lines: list[str]) -> str:
    if not comment_lines:
        return text
    prefix = f"{top_level_key}:"
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        if line == prefix or line.startswith(prefix + " "):
            out.extend(comment_lines)
        out.append(line)
    return "\n".join(out)


@dataclass(frozen=True, slots=True)
class ScaffoldBindingResult:
    """Everything produced (or that would be produced) by one ``scaffold-binding`` run."""

    binding_path: Path
    binding_text: str
    written: bool
    archetype: BindingArchetype
    domain: str
    target_class: str
    mapped_columns: tuple[str, ...] = ()
    technical_field_columns: tuple[str, ...] = ()
    orphan_columns: tuple[str, ...] = ()
    dbt_model_path: Path | None = None
    dbt_model_text: str | None = None
    dbt_model_written: bool = False
    ontology_stub: OntologyStubOutcome | None = None
    notes: tuple[str, ...] = ()
    dry_run: bool = False


def _build_field_entries(
    columns: tuple[SourceColumn, ...], matches: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    # Emits the resolved property's full URI rather than reverse-deriving a "prefix:Local"
    # qname: a full IRI is always unambiguously resolvable (proven by
    # test_full_iri_accelerator_class_and_property_resolve in
    # tests/test_compiler_accelerator_direct.py) regardless of which prefixes the domain
    # ontology happens to declare, at the cost of being more verbose than a qname. A human is
    # free to rewrite these as qnames for readability once the binding compiles.
    return [
        {"property": matches[column.name]["property_uri"], "expression": column.name}
        for column in columns
        if column.name in matches
    ]


def _resolve_class(
    hub_root: Path,
    domain: str,
    target_class_token: str,
    *,
    catalog_path: Path | None,
) -> tuple[str, Any, Path]:
    """Resolve *target_class_token* against the domain ontology, creating no files.

    Returns ``(class_uri, loaded_ontology_or_None, ontology_path)``. ``loaded`` is ``None``
    when the domain ontology does not exist yet.
    """
    ontology_path = hub_root / "model" / "ontologies" / f"{domain}.ttl"
    if ontology_path.is_file():
        loaded = load_ontology(
            ontology_path, catalog_path=catalog_path, profile=SemanticProfile.KAIROS_DESIGN
        )
        class_uri = resolve_token_uri(loaded, ontology_path, target_class_token)
        if class_uri is None:
            raise ScaffoldBindingError(
                f"cannot resolve --target-class {target_class_token!r}: no declared prefix "
                f"matches it in {ontology_path}."
            )
        return class_uri, loaded, ontology_path
    if "://" in target_class_token or target_class_token.startswith("urn:"):
        return target_class_token, None, ontology_path
    raise ScaffoldBindingError(
        f"domain ontology {ontology_path} does not exist yet, so --target-class "
        f"{target_class_token!r} (a prefix:Local qname) cannot be resolved -- no ontology "
        "declares that prefix. Pass --target-class as a full IRI so scaffold-binding can "
        "create the domain ontology stub, or author model/ontologies/"
        f"{domain}.ttl's @prefix declarations by hand first."
    )


def run_scaffold_binding(
    hub_root: Path,
    *,
    system: str,
    table: str,
    archetype_id: str,
    target_class: str | None = None,
    domain: str | None = None,
    from_binding: Path | None = None,
    out_path: Path | None = None,
    force: bool = False,
    ref_models_dir: Path | None = None,
    catalog_path: Path | None = None,
    accelerator: str | None = None,
    analysis_dir: Path | None = None,
    platform: str = "fabric",
    dry_run: bool = False,
) -> ScaffoldBindingResult:
    """Scaffold one v5 ``EntityBinding`` YAML (and, for ``passthrough``, a dbt staging model).

    ``dry_run=True`` computes and returns the full result (``binding_text``, ``dbt_model_text``,
    the ``OntologyStubOutcome`` preview, mapped/orphan columns, ...) exactly as a real run would,
    but writes nothing under *hub_root*: not the binding YAML, not the dbt staging model, and not
    the domain ontology stub (which is instead previewed via a throwaway temp file so the target
    class can still be resolved -- see :func:`ensure_domain_ontology_stub`).

    Raises:
        ScaffoldBindingError: for any user-facing failure (unknown archetype/table, no domain
            could be inferred, an unresolvable ``--target-class``, an existing output path
            without ``--force``).
    """
    archetype = load_binding_archetype(archetype_id)
    notes: list[str] = []

    columns = load_table_columns(hub_root, system, table)
    if not columns:
        raise ScaffoldBindingError(
            f"table '{table}' has no columns under {_system_dir(hub_root, system)}."
        )
    pk_columns = tuple(c.name for c in columns if c.is_primary_key)

    seed_fields: list[dict[str, Any]] | None = None
    from_binding_target_class: str | None = None
    from_binding_domain: str | None = None
    if from_binding is not None:
        text = Path(from_binding).read_text(encoding="utf-8")
        seeded = load_entity_binding(text, path=str(from_binding))
        from_binding_target_class = seeded.target_class
        from_binding_domain = seeded.domain
        seed_fields = [
            {"property": fm.property, "expression": _expression_to_yaml_value(fm.expression)}
            for fm in seeded.fields
        ]
        notes.append(
            f"fields: seeded from --from-binding {from_binding} ({len(seed_fields)} field(s)); "
            "confirm grain/identity, add conformance, and add the remaining source slices by "
            "hand."
        )

    resolved_domain = domain or from_binding_domain or infer_domain(analysis_dir, system, table)
    if not resolved_domain:
        raise ScaffoldBindingError(
            f"cannot infer --domain for {system}.{table}: no analyse-sources affinity evidence "
            "found. Pass --domain explicitly, or run `kairos-ontology analyse-sources` first."
        )

    target_class_token = target_class or from_binding_target_class
    if not target_class_token:
        raise ScaffoldBindingError(
            "provide --target-class (or --from-binding, whose target class is reused)."
        )

    class_uri, loaded, ontology_path = _resolve_class(
        hub_root, resolved_domain, target_class_token, catalog_path=catalog_path
    )

    accelerator_ontology_iri: str | None = None
    stub_outcome: OntologyStubOutcome | None = None
    reload_path = ontology_path
    preview_ttl_path: Path | None = None
    needs_import_check = loaded is None or (
        loaded.semantic_index.class_by_uri(class_uri) is None
    )
    if not ontology_path.is_file() or needs_import_check:
        accelerator_ontology_iri, accel_notes = resolve_accelerator_import(
            hub_root=hub_root,
            ref_models_dir=ref_models_dir,
            accelerator=accelerator,
            domain=resolved_domain,
            target_class_uri=class_uri,
        )
        notes.extend(accel_notes)
    if not ontology_path.is_file() or accelerator_ontology_iri is not None:
        stub_outcome = ensure_domain_ontology_stub(
            hub_root,
            resolved_domain,
            accelerator_ontology_iri=accelerator_ontology_iri,
            catalog_path=catalog_path,
            dry_run=dry_run,
        )
        notes.extend(stub_outcome.notes)
        loaded = None  # force a reload below with the just-written/updated (or previewed) stub
        if stub_outcome.preview_path is not None:
            reload_path = preview_ttl_path = stub_outcome.preview_path

    try:
        if loaded is None:
            loaded = load_ontology(
                reload_path, catalog_path=catalog_path, profile=SemanticProfile.KAIROS_DESIGN
            )
            resolved_uri = resolve_token_uri(loaded, reload_path, target_class_token)
            if resolved_uri is not None:
                class_uri = resolved_uri

        cls = loaded.semantic_index.class_by_uri(class_uri)
    finally:
        if preview_ttl_path is not None:
            preview_ttl_path.unlink(missing_ok=True)
    if cls is None:
        raise ScaffoldBindingError(
            f"class does not resolve in the scoped domain closure: {class_uri} (from "
            f"--target-class {target_class_token!r}). Check the accelerator owl:imports and "
            "catalog mapping."
        )

    universe = loaded.semantic_index.class_properties(class_uri)
    matches = match_columns_to_properties(columns, universe)

    mapped_columns = tuple(c.name for c in columns if c.name in matches)
    remaining = [c for c in columns if c.name not in matches]
    technical_entries: list[dict[str, Any]] = []
    technical_columns: list[str] = []
    orphan_columns: list[str] = []
    for column in remaining:
        purpose = classify_technical_field(column)
        if purpose is None:
            orphan_columns.append(column.name)
            continue
        technical_columns.append(column.name)
        technical_entries.append(
            {
                "name": column.name,
                "expression": column.name,
                "type": _technical_field_type(column.data_type),
                "nullable": column.nullable,
                "purpose": purpose,
            }
        )

    if archetype.grain_mode == "derive":
        grain_columns, grain_note = propose_grain_columns(columns, pk_columns)
        notes.append(grain_note)
        if not grain_columns:
            raise ScaffoldBindingError(f"cannot propose grain.columns: {grain_note}")
    elif archetype.grain_hint_mode == "event-subject":
        grain_columns = (_detect_event_grain_hint(columns, pk_columns),)
    else:
        grain_columns = (SENTINEL_GRAIN_COLUMN,)

    if archetype.identity_mode == "derive":
        identity_key = grain_columns
    else:
        identity_key = (SENTINEL_IDENTITY_KEY,)

    doc: dict[str, Any] = {
        "apiVersion": "kairos.eu/v5",
        "kind": "EntityBinding",
        "metadata": {
            "name": f"{system}-{table}-to-{resolved_domain}",
            "domain": resolved_domain,
            "tier": archetype.tier,
        },
        "source": {"relation": f"{system}.{table}"},
        "target": {"class": target_class_token},
        "grain": {"columns": list(grain_columns)},
        "identity": {"strategy": "source-natural", "sourceKey": list(identity_key)},
        "load": {"mode": archetype.load_mode},
        "fields": seed_fields if seed_fields is not None else _build_field_entries(columns, matches),
    }
    if technical_entries:
        doc["technicalFields"] = technical_entries
    comment_hooks: dict[str, list[str]] = {}
    if archetype.scaffold_relationship_example:
        doc["relationships"] = [
            {
                "property": SENTINEL_PARENT_PROPERTY,
                "target": SENTINEL_PARENT_CLASS,
                "externalReference": {
                    "name": SENTINEL_PARENT_ENTITY_NAME,
                    "domain": SENTINEL_PARENT_DOMAIN,
                    "key": [{"column": SENTINEL_PARENT_KEY_COLUMN, "type": "string"}],
                },
                "join": [{"local": SENTINEL_LOCAL_FK_COLUMN, "foreign": SENTINEL_PARENT_KEY_COLUMN}],
                "cardinality": "many-to-one",
                "mode": "non-temporal",
                "missingParent": "error",
                "ambiguousParent": "error",
            }
        ]
        comment_hooks["relationships"] = [
            "# DD-138 cross-domain relationship worked example (line-item-child archetype).",
            "# A line-item child belongs to a parent entity materialized by a DIFFERENT domain's",
            "# binding, so it cannot be looked up via a same-domain `target:` -- it is referenced",
            "# by the parent's already-materialized output column via `externalReference`.",
            "# Confirm every <CONFIRM_...> placeholder below against the real parent binding:",
            "#   * property                  -- this table's own relationship property.",
            "#   * target                    -- the parent's class token.",
            "#   * externalReference.name    -- a short label for the parent reference.",
            "#   * externalReference.domain  -- the OTHER domain that materializes the parent.",
            "#   * externalReference.key     -- the PARENT's materialized output column(s), not",
            "#                                  this table's own column.",
            "#   * join.local                -- this table's own foreign-key source column.",
            "#   * join.foreign               -- MUST equal externalReference.key[0].column.",
        ]
    if archetype.scaffold_conformance:
        doc["conformance"] = {
            "group": f"{resolved_domain}-{table}",
            "sourcePrecedence": SENTINEL_SOURCE_PRECEDENCE,
            "conflict": "prefer-precedence",
            "union": {
                "mode": "deduplicate",
                "deduplicateBy": [SENTINEL_DEDUP_KEY],
                "orderBy": [{"column": SENTINEL_ORDER_COLUMN, "direction": "descending"}],
            },
        }
        comment_hooks["conformance"] = [
            "# Survivorship policy across merged source slices is never silently guessed.",
            "# CONFIRM sourcePrecedence (1 = highest priority; must be a positive integer) and",
            "# the union policy (deduplicateBy / orderBy) before this compiles. Add the other",
            "# contributing source slices as additional bindings sharing this conformance group.",
        ]
    if archetype.tier == "passthrough":
        doc["quality"] = [
            {"kind": "not-null", "columns": list(grain_columns)},
            {"kind": "unique", "columns": list(grain_columns)},
        ]

    if technical_entries:
        comment_hooks["technicalFields"] = [
            "# DD-139: materializes a source column as a Silver output without asserting a new",
            "# ontology property (C2 -- no decorative local property is minted for an unmapped",
            "# key/FK-shaped column). Never auto-materialized for a column that has a real",
            "# accelerator/local-extension property match -- only for the columns below, which",
            "# had none.",
        ]
    if archetype.tier == "canonical":
        confirm_lines = [
            "# CONFIRM: this skeleton's grain.columns and identity.sourceKey carry irreducible",
            "# modeling judgement and are intentionally invalid placeholders -- `compile --check`",
            "# will reject them (binding.unknown-key-column) until you replace them with the",
            "# real answer.",
        ]
        comment_hooks.setdefault("grain", []).extend(confirm_lines)

    rendered = yaml.safe_dump(doc, sort_keys=False, default_flow_style=False, allow_unicode=True, width=100)
    for key, comment_lines in comment_hooks.items():
        rendered = _insert_comment_before(rendered, key, comment_lines)

    header_lines = [
        f"# Generated by `kairos-ontology scaffold-binding` ({archetype.label} archetype).",
        f"# Source: {system}.{table}   Domain: {resolved_domain}   Target: {target_class_token}",
    ]
    if mapped_columns:
        header_lines.append(f"# Mapped columns ({len(mapped_columns)}): {', '.join(mapped_columns)}")
    if technical_columns:
        header_lines.append(
            f"# Technical fields, DD-139, not ontology properties ({len(technical_columns)}): "
            f"{', '.join(technical_columns)}"
        )
    if orphan_columns:
        header_lines.append(
            f"# Orphan columns -- no accelerator/local-extension property or technical-field "
            f"match ({len(orphan_columns)}): {', '.join(orphan_columns)}"
        )
        header_lines.append(
            "# Review these by hand: either the accelerator model is missing a property, or "
            "they are genuinely unused."
        )
    for note in notes:
        header_lines.append(f"# NOTE: {note}")
    binding_text = "\n".join(header_lines) + "\n" + rendered

    default_out = hub_root / "integration" / "bindings" / f"{doc['metadata']['name']}.binding.yaml"
    resolved_out = Path(out_path) if out_path is not None else default_out
    if resolved_out.is_file() and not force:
        raise ScaffoldBindingError(f"{resolved_out} already exists; pass --force to overwrite.")
    written = False
    if dry_run:
        notes.append(f"dry-run: {resolved_out} was not written.")
    else:
        resolved_out.parent.mkdir(parents=True, exist_ok=True)
        resolved_out.write_text(binding_text, encoding="utf-8")
        written = True

    dbt_model_path: Path | None = None
    dbt_model_text: str | None = None
    dbt_model_written = False
    if archetype.tier == "passthrough":
        dbt_model_text = render_staging_sql(system, table, columns, platform=platform)
        dbt_model_path = (
            hub_root
            / "integration"
            / "transforms"
            / "dbt"
            / "models"
            / "intermediate"
            / resolved_domain
            / f"stg_{system}__{table}.sql"
        )
        if dbt_model_path.is_file() and not force:
            notes.append(f"{dbt_model_path} already exists; not overwritten (pass --force).")
        elif dry_run:
            notes.append(f"dry-run: {dbt_model_path} was not written.")
        else:
            dbt_model_path.parent.mkdir(parents=True, exist_ok=True)
            dbt_model_path.write_text(dbt_model_text, encoding="utf-8")
            dbt_model_written = True

    return ScaffoldBindingResult(
        binding_path=resolved_out,
        binding_text=binding_text,
        written=written,
        archetype=archetype,
        domain=resolved_domain,
        target_class=target_class_token,
        mapped_columns=mapped_columns,
        technical_field_columns=tuple(technical_columns),
        orphan_columns=tuple(orphan_columns),
        dbt_model_path=dbt_model_path,
        dbt_model_text=dbt_model_text,
        dbt_model_written=dbt_model_written,
        ontology_stub=stub_outcome,
        notes=tuple(notes),
        dry_run=dry_run,
    )
