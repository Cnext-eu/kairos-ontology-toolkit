# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Facts of a domain for its business validation document (DD-254).

Every fact is read from an authoritative hub input and nothing else: the ontology import
closure through ``load_ontology`` (DD-243, never a bare parse), the Silver contract, the
compile plan and its bindings, the source disposition ledgers and the decision bundle. The
narrative may word and group these facts but never add one, so this module is the only place
a fact enters the document.

Cardinality comes from ``erd_projector.edge_multiplicities`` (DD-241), the one derivation every
diagram in the toolkit uses, mapped to the four line-end codes ``1 | 01 | 1n | 0n``.

The same hub produces byte-identical JSON: every collection is sorted, and the document
carries no timestamp. ``facts_hash`` is the SHA-256 of that JSON without the hash itself.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from rdflib import Literal, URIRef
from rdflib.namespace import OWL, SKOS

from ...analysis_paths import analysis_dir
from ...hub_config import hub_display_name
from ...hub_utils import is_domain_ontology_stem
from ...ontology_loader import OntologyLoadResult, SemanticProfile, load_ontology
from ...semantic_index import ClassRecord, SemanticIndex
from ..erd_projector import declared_inverse, edge_multiplicities
from ..shared import KAIROS_EXT
from ..uri_utils import camel_to_snake, extract_local_name

SCHEMA_VERSION = 1
FACTS_FILENAME = "business-doc.facts.json"

# Declared in scaffold/kairos-mdm.ttl. Core never imports the MDM package, so the IRI is
# spelled here rather than taken from ``mdm.vocabulary``.
_MDM_REFERENCE_LIST = URIRef("https://kairos.cnext.eu/mdm#referenceList")
_XSD = "http://www.w3.org/2001/XMLSchema#"
_GAP_DISPOSITIONS = ("deferred", "blueprint-gap")


class BusinessDocError(Exception):
    """A business validation document cannot be built from the inputs given."""


# --------------------------------------------------------------------------------------
# Pure mappings (unit-tested on their own).
# --------------------------------------------------------------------------------------
def cardinality_code(min_bound: Optional[int], max_bound: Optional[int]) -> str:
    """Map OWL ``(min, max)`` bounds of one line end to ``1 | 01 | 1n | 0n``.

    ``max <= 1`` (an ``owl:FunctionalProperty`` or a max/exact cardinality of one) is "at most
    one"; a ``min >= 1`` makes it mandatory. An undeclared bound is the open-world default:
    zero or more.
    """
    mandatory = (min_bound or 0) >= 1
    if max_bound is not None and max_bound <= 1:
        return "1" if mandatory else "01"
    return "1n" if mandatory else "0n"


_CONTRACT_TYPES = (
    ("string", "Text"),
    ("int", "Whole number"),
    ("decimal", "Decimal"),
    ("float", "Decimal"),
    ("double", "Decimal"),
    ("timestamp", "Date and time (UTC)"),
    ("datetime", "Date and time (UTC)"),
    ("date", "Date"),
    ("time", "Time"),
    ("bool", "Yes/No"),
)

_XSD_TYPES = {
    "string": "Text",
    "normalizedString": "Text",
    "token": "Text",
    "anyURI": "Text",
    "langString": "Text",
    "integer": "Whole number",
    "int": "Whole number",
    "long": "Whole number",
    "short": "Whole number",
    "byte": "Whole number",
    "nonNegativeInteger": "Whole number",
    "positiveInteger": "Whole number",
    "unsignedInt": "Whole number",
    "unsignedLong": "Whole number",
    "decimal": "Decimal",
    "double": "Decimal",
    "float": "Decimal",
    "date": "Date",
    "dateTime": "Date and time (UTC)",
    "dateTimeStamp": "Date and time (UTC)",
    "time": "Time",
    "gYear": "Year",
    "gYearMonth": "Year and month",
    "boolean": "Yes/No",
    "duration": "Duration",
}


def business_type(contract_type: Optional[str], range_uri: Optional[str]) -> str:
    """Business-readable data type: the contract's canonical type first, else the XSD range."""
    if contract_type:
        lowered = contract_type.strip().lower()
        for prefix, label in _CONTRACT_TYPES:
            if lowered.startswith(prefix):
                return label
    if range_uri and range_uri.startswith(_XSD):
        return _XSD_TYPES.get(range_uri[len(_XSD) :], "Text")
    return "Text"


def facts_json(facts: dict[str, Any]) -> str:
    """Canonical JSON of *facts*: sorted keys, two-space indent, trailing newline."""
    return json.dumps(facts, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _hash_of(facts: dict[str, Any]) -> str:
    body = {key: value for key, value in facts.items() if key != "facts_hash"}
    return hashlib.sha256(facts_json(body).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------
# Closure access.
# --------------------------------------------------------------------------------------
@dataclass
class _Closure:
    """The domain's import closure with the lookups the facts need."""

    domain: str
    path: Path
    loaded: OntologyLoadResult
    index: SemanticIndex
    classes: dict[str, ClassRecord] = field(default_factory=dict)
    prefixes: list[tuple[str, str]] = field(default_factory=list)
    domain_of_source: dict[str, str] = field(default_factory=dict)
    # The compile plan's resolution context, when there is a plan: authored tokens resolve
    # exactly as the compiler resolves them, the file prefixes are the fallback.
    resolution: Any = None

    @property
    def graph(self):
        return self.loaded.graph

    def curie(self, uri: str) -> str:
        """``prefix:Local`` from the prefixes the closure's own files declare, else the IRI."""
        for namespace, prefix in self.prefixes:
            if uri.startswith(namespace) and len(uri) > len(namespace):
                return f"{prefix}:{uri[len(namespace) :]}"
        return uri

    def resolve(self, token: str) -> Optional[str]:
        """Full IRI for an authored ``prefix:Local`` token or IRI."""
        if not token:
            return None
        if "://" in token or token.startswith("urn:"):
            return token
        if self.resolution is not None:
            resolved = self.resolution.klass(token) or self.resolution.property(token)
            if resolved is not None:
                return resolved.uri
        prefix, _, local = token.partition(":")
        for namespace, known in self.prefixes:
            if known == prefix:
                return namespace + local
        return None

    def owner(self, uri: str) -> str:
        """The domain (or reference module) that declares *uri*."""
        record = self.classes.get(uri)
        if record is None:
            return ""
        if record.provenance.import_depth == 0:
            return self.domain
        identity = record.provenance.source_identity
        return self.domain_of_source.get(identity) or extract_local_name(identity.rstrip("/#"))

    def label(self, uri: str) -> str:
        record = self.classes.get(uri)
        if record is not None and record.label:
            return record.label
        prop = self.index.property_by_uri(uri)
        if prop is not None and prop.label:
            return prop.label
        return extract_local_name(uri)

    def deprecated(self, uri: str) -> bool:
        for value in self.graph.objects(URIRef(uri), OWL.deprecated):
            if str(value).strip().lower() in {"true", "1"}:
                return True
        return False

    def is_code_list(self, uri: str) -> bool:
        """A governed code class: marked as reference data, or a ``skos:Concept``."""
        subject = URIRef(uri)
        for predicate in (KAIROS_EXT.isReferenceData, _MDM_REFERENCE_LIST):
            value = self.graph.value(subject, predicate)
            if isinstance(value, Literal) and str(value).strip().lower() in {"true", "1"}:
                return True
        record = self.classes.get(uri)
        if record is None:
            return False
        return any(link.uri == str(SKOS.Concept) for link in record.ancestors)


def _open_closure(hub: Path, domain: str, catalog: Optional[Path]) -> _Closure:
    ontologies = hub / "model" / "ontologies"
    path = ontologies / f"{domain}.ttl"
    if not path.is_file():
        raise BusinessDocError(f"no domain ontology at {path}")
    loaded = load_ontology(path, catalog_path=catalog, profile=SemanticProfile.KAIROS_DESIGN)
    closure = _Closure(domain=domain, path=path, loaded=loaded, index=loaded.semantic_index)
    closure.classes = {record.uri: record for record in loaded.semantic_index.classes}

    # Prefixes from the files of the closure, nearest first: the merged graph keeps only
    # rdflib's defaults, so a domain prefix such as ``party:`` is read from its own file.
    seen: dict[str, str] = {}
    for source in sorted(
        loaded.sources, key=lambda s: (s.manifest.import_depth, s.manifest.source_identity)
    ):
        for prefix, namespace in sorted(source.graph.namespaces()):
            if prefix and str(namespace) not in seen and prefix not in seen.values():
                seen[str(namespace)] = prefix
    # Longest namespace first so ``ex:`` never shadows ``exsub:`` under the same root.
    closure.prefixes = sorted(seen.items(), key=lambda item: (-len(item[0]), item[1]))

    root = ontologies.resolve()
    for entry in loaded.manifest:
        source = Path(entry.source_path)
        try:
            in_hub = source.resolve().parent == root
        except OSError:
            in_hub = False
        if in_hub and is_domain_ontology_stem(source.stem):
            owner = source.stem
        else:
            owner = extract_local_name((entry.ontology_iri or entry.source_identity).rstrip("/#"))
        for key in (entry.source_identity, entry.ontology_iri, entry.import_uri):
            if key:
                closure.domain_of_source.setdefault(key, owner)
    return closure


# --------------------------------------------------------------------------------------
# Silver-side inputs (all optional: a domain without them still gets ontology facts).
# --------------------------------------------------------------------------------------
@dataclass
class _Silver:
    contract: Any = None
    plan: Any = None
    explain: Any = None
    warnings: list[str] = field(default_factory=list)


def _load_silver(hub: Path, domain: str) -> _Silver:
    from ...compiler import CompileError, CompileMode, build_compile_plan, compile_plan_result
    from ...compiler.contracts import load_silver_contract

    silver = _Silver()
    contract_path = hub / "model" / "contracts" / f"{domain}.contract.yaml"
    if contract_path.is_file():
        try:
            silver.contract = load_silver_contract(
                contract_path.read_text(encoding="utf-8"), path=str(contract_path)
            )
        except CompileError as exc:
            silver.warnings.append(f"Silver contract not used: {exc}")
    try:
        silver.plan = build_compile_plan(hub, domain)
        result = compile_plan_result(silver.plan, CompileMode.EXPLAIN, render=False)
        silver.explain = result.explain
    except CompileError as exc:
        silver.warnings.append(f"compile plan not used: {exc}")
    return silver


def _bindings_for(silver: _Silver, closure: _Closure, uri: str) -> list[Any]:
    if silver.plan is None:
        return []
    return sorted(
        (b for b in silver.plan.bindings if closure.resolve(b.target_class) == uri),
        key=lambda b: b.name,
    )


def _contract_entity(silver: _Silver, closure: _Closure, uri: str) -> Any:
    if silver.contract is None:
        return None
    for entity in silver.contract.entities:
        if closure.resolve(entity.target_class) == uri:
            return entity
    return None


def _source_systems(hub: Path, silver: _Silver, bindings: list[Any], domain: str) -> list[str]:
    """Source system names only -- never a table's content (the document holds no samples)."""
    systems: set[str] = set()
    owners: Optional[dict] = None
    for binding in bindings:
        relation = (
            silver.plan.resolution.relation(binding.source.relation)
            if binding.source.relation
            else None
        )
        if relation is not None and relation.system_label and relation.system_label != "dbt":
            systems.add(relation.system_label)
            continue
        # A contracted dbt model: walk its ref() chain to the bronze systems it reads.
        if owners is None:
            from ...source_disposition import load_binding_owners

            owners = load_binding_owners(hub / "integration" / "bindings", hub)
        file_name = Path(binding.source_path).name if binding.source_path else ""
        for (system, _table), owned_by in owners.items():
            if (domain, file_name) in owned_by:
                systems.add(system)
    return sorted(systems)


# --------------------------------------------------------------------------------------
# Facts.
# --------------------------------------------------------------------------------------
def _core_entities(closure: _Closure, silver: _Silver, requested: Iterable[str]) -> list[str]:
    requested = list(requested)
    if requested:
        uris = []
        for token in requested:
            uri = closure.resolve(token)
            if uri is None or uri not in closure.classes:
                raise BusinessDocError(f"entity {token!r} is not a class of the closure")
            uris.append(uri)
        return sorted(set(uris))
    uris: set[str] = set()
    if silver.plan is not None:
        uris.update(filter(None, (closure.resolve(b.target_class) for b in silver.plan.bindings)))
    if silver.contract is not None:
        uris.update(
            filter(None, (closure.resolve(e.target_class) for e in silver.contract.entities))
        )
    uris = {uri for uri in uris if uri in closure.classes}
    if not uris:
        # Nothing bound yet: every class the domain file declares that is not a code list.
        uris = {
            record.uri
            for record in closure.index.classes
            if record.provenance.import_depth == 0 and not closure.is_code_list(record.uri)
        }
    if not uris:
        raise BusinessDocError(f"domain {closure.domain!r} declares no class")
    return sorted(uris)


def _required(closure: _Closure, cls: str, declared_on: str, prop: str, rng: str) -> bool:
    _source, (min_bound, _max) = edge_multiplicities(
        closure.graph, URIRef(cls), URIRef(declared_on), URIRef(prop), URIRef(rng)
    )
    return (min_bound or 0) >= 1


def _entity_facts(
    hub: Path, closure: _Closure, silver: _Silver, uri: str
) -> tuple[dict[str, Any], list[dict[str, Any]], set[str]]:
    """``(entity, relationship candidates, code lists)`` for one core class."""
    from ...compiler.adapter import field_target
    from ...compiler.contracts import resolved_column_name

    record = closure.classes[uri]
    bindings = _bindings_for(silver, closure, uri)
    contract_entity = _contract_entity(silver, closure, uri)

    contract_props: dict[str, Any] = {}
    contract_rel_columns: dict[str, str] = {}
    if contract_entity is not None:
        for item in contract_entity.properties:
            resolved = closure.resolve(item.property)
            if resolved:
                contract_props[resolved] = item
        for rel in contract_entity.relationships:
            resolved = closure.resolve(rel.property)
            if resolved and rel.column_name:
                contract_rel_columns[resolved] = rel.column_name
    binding_columns: dict[str, str] = {}
    for binding in bindings:
        for mapping in binding.fields:
            prop, column = field_target(mapping, silver.plan.resolution)
            if prop is not None and column:
                binding_columns.setdefault(prop.uri, column)

    if contract_entity is not None and contract_entity.identity.business_key:
        business_key = list(contract_entity.identity.business_key)
    elif bindings:
        identity = bindings[0].identity
        business_key = list(identity.business_key or identity.source_key)
    else:
        business_key = []

    fields: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    code_lists: set[str] = set()
    for item in closure.index.class_properties(uri):
        prop_uri = item["property_uri"]
        kind = item["property_type"]
        if kind not in ("datatype", "object"):
            continue
        prop_record = closure.index.property_by_uri(prop_uri)
        ancestor = closure.index.inherited_from(uri, prop_uri)
        declared_on = ancestor or uri
        ranges = sorted(item["ranges"])
        contract_item = contract_props.get(prop_uri)
        deprecated = closure.deprecated(prop_uri) or bool(
            contract_item is not None and contract_item.deprecated is not None
        )
        code_range = next((r for r in ranges if closure.is_code_list(r)), None)
        if kind == "object" and code_range is None:
            for rng in ranges or [str(OWL.Thing)]:
                if rng == str(OWL.Thing):
                    continue
                candidates.append(
                    {
                        "from": uri,
                        "property": prop_uri,
                        "to": rng,
                        "declared_on": declared_on,
                        "deprecated": deprecated,
                    }
                )
            continue
        if code_range is not None:
            code_lists.add(code_range)
        rng = code_range or (ranges[0] if ranges else "")
        if contract_item is not None:
            column = resolved_column_name(contract_item)
        elif prop_uri in contract_rel_columns:
            column = contract_rel_columns[prop_uri]
        elif prop_uri in binding_columns:
            column = binding_columns[prop_uri]
        else:
            column = camel_to_snake(extract_local_name(prop_uri))
        required = (
            contract_item.required
            if contract_item is not None
            else _required(closure, uri, declared_on, prop_uri, rng or str(OWL.Thing))
        )
        fields.append(
            {
                "property": closure.curie(prop_uri),
                "uri": prop_uri,
                "label": prop_record.label if prop_record else extract_local_name(prop_uri),
                "comment": prop_record.comment if prop_record else "",
                "column": column,
                "datatype": business_type(
                    contract_item.type if contract_item is not None else None,
                    None if code_range else rng,
                ),
                "required": bool(required),
                "code_list": (
                    {"iri": closure.curie(code_range), "label": closure.label(code_range)}
                    if code_range
                    else None
                ),
                "deprecated": deprecated,
                "inherited_from": closure.curie(ancestor) if ancestor else None,
                "in_silver": prop_uri in contract_props
                or prop_uri in contract_rel_columns
                or prop_uri in binding_columns,
            }
        )
    fields.sort(key=lambda f: (f["label"].lower(), f["uri"]))

    entity = {
        "iri": closure.curie(uri),
        "uri": uri,
        "label": record.label or record.name,
        "comment": record.comment,
        "domain": closure.owner(uri),
        "sources": _source_systems(hub, silver, bindings, closure.domain),
        "bindings": [b.name for b in bindings],
        "in_silver": bool(bindings) or contract_entity is not None,
        "identification": {
            "technical_id": {"column": f"{record.name.lower()}_sk", "type": "Text (hash)"},
            "business_key": {"columns": business_key},
        },
        "fields": fields,
    }
    return entity, candidates, code_lists


def _relationships(
    closure: _Closure, silver: _Silver, candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    keyed = {(c["from"], c["property"], c["to"]): c for c in candidates if not c["deprecated"]}
    shapes: dict[tuple[str, str], Any] = {}
    if silver.explain is not None:
        for entity in silver.explain.entities:
            for shape in entity.relationship_shapes:
                key = (closure.resolve(entity.target_class), closure.resolve(shape.property))
                shapes.setdefault(key, shape)
    rows = []
    for (src, prop, dst), cand in sorted(keyed.items()):
        inverse = declared_inverse(closure.graph, URIRef(prop))
        inverse_uri = str(inverse) if inverse is not None else None
        # An inverse pair drawn from both ends is one relationship: keep the IRI-first
        # direction, as the class diagram does (#753).
        if inverse_uri and (dst, inverse_uri, src) in keyed and inverse_uri < prop:
            continue
        (s_min, s_max), (t_min, t_max) = edge_multiplicities(
            closure.graph,
            URIRef(src),
            URIRef(cand["declared_on"]),
            URIRef(prop),
            URIRef(dst),
            inverse,
        )
        label = closure.label(prop)
        role = f"{label} / {closure.label(inverse_uri)}" if inverse_uri else label
        shape = shapes.get((src, prop))
        rows.append(
            {
                "property": closure.curie(prop),
                "uri": prop,
                "inverse": closure.curie(inverse_uri) if inverse_uri else None,
                "from": closure.curie(src),
                "to": closure.curie(dst),
                "from_card": cardinality_code(s_min, s_max),
                "to_card": cardinality_code(t_min, t_max),
                "role_label": role,
                "comment": (closure.index.property_by_uri(prop) or _NoComment).comment,
                "in_silver": shape is not None,
                "silver_cardinality": shape.cardinality if shape is not None else None,
            }
        )
    rows.sort(
        key=lambda r: (
            closure.label(closure.resolve(r["from"]) or r["from"]).lower(),
            r["uri"],
            r["to"],
        )
    )
    for number, row in enumerate(rows, start=1):
        row["id"] = f"R{number}"
        # The document states the ontology's cardinality. When Silver joins to one parent
        # but OWL still allows many, say so: the reviewer is confirming the stricter reading.
        if (row["silver_cardinality"] or "").endswith("-to-one") and row["to_card"] in (
            "0n",
            "1n",
        ):
            silver.warnings.append(
                f"{row['id']} ({row['property']}): Silver joins {row['silver_cardinality']} "
                "but the ontology allows more than one; make the property functional or "
                "add a max cardinality of 1"
            )
    return rows


class _NoComment:
    comment = ""


def _candidate_gaps(hub: Path, domain: str) -> list[dict[str, Any]]:
    from ...anchor_tables import load_table_anchors
    from ...source_disposition import load_binding_owners, load_dispositions

    entries = load_dispositions(hub)
    if not entries:
        return []
    anchors = load_table_anchors(analysis_dir(hub))
    owners = load_binding_owners(hub / "integration" / "bindings", hub)
    gaps = []
    for (system, table, column), entry in sorted(entries.items()):
        disposition = entry.get("disposition")
        if disposition not in _GAP_DISPOSITIONS:
            continue
        anchor_domain = (anchors.get((system, table)) or {}).get("domain")
        owner_domains = {owner for owner, _file in owners.get((system, table), ())}
        if anchor_domain != domain and domain not in owner_domains:
            continue
        source = f"{system}.{table}" + (f".{column}" if column else "")
        gaps.append(
            {
                "source": source,
                "disposition": disposition,
                "rationale": str(entry.get("rationale") or ""),
            }
        )
    return gaps


def _decisions(hub: Path, domain: str) -> list[dict[str, Any]]:
    from ...decision_records import validate_decision_bundle

    result = validate_decision_bundle(hub / "decisions")
    rows = [
        {
            "id": record.id,
            "title": record.title,
            "status": (record.decision_state or record.status or "").lower(),
        }
        for record in result.records
        if record.domain == domain and record.id
    ]
    return sorted(rows, key=lambda r: r["id"])


def build_facts(
    hub: Path,
    domain: str,
    *,
    entities: Iterable[str] = (),
    catalog: Optional[Path] = None,
) -> dict[str, Any]:
    """Return the facts of *domain* in *hub* (schema version 1, see DD-254).

    *entities* overrides the core entities (default: the classes bound in the domain, else
    every non-code-list class the domain file declares). Raises ``BusinessDocError`` when the
    domain cannot be read; ``OntologyLoadError`` propagates for an incomplete closure.
    """
    hub = Path(hub)
    closure = _open_closure(hub, domain, catalog)
    silver = _load_silver(hub, domain)
    if silver.plan is not None:
        closure.resolution = silver.plan.resolution
    core = _core_entities(closure, silver, entities)

    entity_rows: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    code_lists: set[str] = set()
    for uri in core:
        entity, entity_candidates, entity_codes = _entity_facts(hub, closure, silver, uri)
        entity_rows.append(entity)
        candidates.extend(entity_candidates)
        code_lists |= entity_codes
    entity_rows.sort(key=lambda e: (e["label"].lower(), e["uri"]))
    relationships = _relationships(closure, silver, candidates)

    core_curies = {e["iri"] for e in entity_rows}
    external_uris = sorted(
        {closure.resolve(r[end]) or r[end] for r in relationships for end in ("from", "to")}
        - {closure.resolve(c) or c for c in core_curies}
    )
    externals = [
        {
            "iri": closure.curie(uri),
            "uri": uri,
            "label": closure.label(uri),
            "domain": closure.owner(uri) or "unknown",
        }
        for uri in external_uris
    ]
    neighbours: dict[str, dict[str, Any]] = {}
    for ext in externals:
        if ext["domain"] == domain:
            continue
        row = neighbours.setdefault(
            ext["domain"], {"domain": ext["domain"], "master_of": [], "relationships": []}
        )
        row["master_of"].append(ext["label"])
        for rel in relationships:
            if ext["iri"] in (rel["from"], rel["to"]) and rel["id"] not in row["relationships"]:
                row["relationships"].append(rel["id"])
    for row in neighbours.values():
        row["master_of"].sort(key=str.lower)
        row["relationships"].sort(key=lambda rid: int(rid[1:]))

    manifest_root = next((m for m in closure.loaded.manifest if m.import_depth == 0), None)
    facts: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "hub": hub_display_name(hub),
        "domain": domain,
        "model_version": (manifest_root.ontology_version if manifest_root else "") or "",
        "closure_hash": closure.loaded.closure_hash,
        "closure_complete": closure.loaded.complete,
        "entities": entity_rows,
        "relationships": relationships,
        "externals": externals,
        "neighbour_domains": [neighbours[name] for name in sorted(neighbours)],
        "code_lists": sorted(
            (
                {
                    "iri": closure.curie(uri),
                    "uri": uri,
                    "label": closure.label(uri),
                    "domain": closure.owner(uri) or "unknown",
                }
                for uri in code_lists
            ),
            key=lambda c: (c["label"].lower(), c["uri"]),
        ),
        "candidate_gaps": _candidate_gaps(hub, domain),
        "decisions": _decisions(hub, domain),
        "warnings": sorted(silver.warnings),
    }
    facts["facts_hash"] = _hash_of(facts)
    return facts
