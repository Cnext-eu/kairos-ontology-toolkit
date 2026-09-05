# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``kairos-ontology propose-relationships`` core logic (issue #493, DD-160).

Authoring a ``relationships:`` entry is a multi-step manual job -- find the target
binding, name the object property, derive join keys, and (cross-domain) hand-write an
``externalReference`` key contract with type-compatible columns. The CLdN dogfooding hub
shipped **27 bindings with zero relationships**: every silver model isolated, no
cross-domain joins possible anywhere.

The toolkit already held everything needed to propose them, in two artifacts nothing in
the v5 binding path ever read:

* the accelerator blueprint's ``cross_domain_relationships`` -- 24 declared bridges for
  the logistics pack, each naming an exact ``property_uri`` plus its domain/range class
  URIs. Until now this was consumed *only* by the legacy v2 report template
  (``report_projector.py``), so the v5 author never saw it. This is what makes the
  proposal authoritative rather than a name-matching guess: the object property is
  **read, not inferred**.
* the hub's own domain ontologies, whose ``owl:ObjectProperty`` declarations with a
  resolvable ``rdfs:domain``/``rdfs:range`` give the same signal for hub-local
  relationships and for hubs with no accelerator installed.

Join columns are then matched deterministically against the parent binding's
``identity.sourceKey``: first a column the author declared ``purpose: relationship``
(DD-139), then exact normalized name equality over the child's other authored columns --
the same high-precision rule as ``scaffold_binding.scan_cross_source_fks`` -- excluding
any column that is the child's entire identity, which is a surrogate-name coincidence
rather than a foreign key (#722).

Nothing here is auto-authored. The output is a proposal a human pastes and confirms;
anything not derivable is emitted as an explicit sentinel rather than a plausible guess.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

#: Bumped when the machine-readable proposal contract changes.
#: 2 (#722): proposals matching an already-authored ``(property, target)`` pair are
#: skipped and reported under ``already_authored``; proposals gain ``join_candidates``.
SCHEMA_VERSION = 2

#: Emitted where a value cannot be derived deterministically. Mirrors the
#: ``scaffold-binding`` sentinel convention (#450) -- a compile-visible placeholder beats a
#: plausible-looking guess.
SENTINEL_JOIN_COLUMN = "<CONFIRM_JOIN_COLUMN>"
SENTINEL_KEY_TYPE = "<CONFIRM_KEY_TYPE>"

_NON_ALNUM = re.compile(r"[^a-z0-9]")


def _normalize(name: str) -> str:
    return _NON_ALNUM.sub("", name.lower())


def _local_name(uri: str) -> str:
    for separator in ("#", "/"):
        if separator in uri:
            return uri.rsplit(separator, 1)[-1]
    return uri


def _class_token(ref: str) -> str:
    """Comparison token for a class or property reference.

    A binding's ``target.class`` and a relationship's ``target:`` may each be a full URI,
    a ``prefix:Local`` qname, or a bare local name -- the compiler accepts all three
    (``kernel._relationship_ref_uri``), and the canonical example authors
    ``target: {class: party:Customer}``. ``_local_name`` splits on ``#`` and ``/`` only, so
    it hands a qname straight back; strip the prefix too, then case-fold.

    Deliberately **not** ``_normalize``, which strips every non-alphanumeric: ``hasParty``
    and ``has_party`` are different property local names, and collapsing them would
    manufacture a false already-authored match -- which, because such a match *suppresses*
    a proposal (#722), would silently hide real work.
    """
    tail = _local_name(ref)
    if ":" in tail:
        tail = tail.rsplit(":", 1)[-1]
    return tail.strip().lower()


def _slug(class_uri: str) -> str:
    """Generated dbt model name for a target class -- mirrors ``adapter._slug``."""
    local = _local_name(class_uri)
    out = "".join(char if char.isalnum() else "_" for char in local).strip("_").lower()
    return out


def _snake(name: str) -> str:
    """``customerCompanyId`` / ``Customer Company Id`` -> ``customer_company_id``."""
    spaced = re.sub(r"[^0-9A-Za-z]+", "_", name)
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", spaced)
    return re.sub(r"_+", "_", spaced).strip("_").lower()


# --------------------------------------------------------------------------------------
# Blueprint bridges
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BlueprintBridge:
    """One declared cross-domain relationship from the accelerator blueprint."""

    id: str
    property_uri: str
    domain_class_uri: str
    range_class_uri: str
    source_domain: str
    target_domain: str
    description: str
    status: str


def load_blueprint_bridges(
    ref_models_dir: Optional[Path], accelerator: Optional[str]
) -> tuple[BlueprintBridge, ...]:
    """Read ``cross_domain_relationships`` from the accelerator's ``data-domains.yaml``.

    Returns an empty tuple (never raises) when no accelerator, no reference models, or no
    blueprint is available -- the ontology fallback still produces proposals in that case.
    """
    if ref_models_dir is None or not Path(ref_models_dir).is_dir():
        return ()
    pattern = (
        f"accelerator-packs/{accelerator}/client-hub-blueprint/data-domains.yaml"
        if accelerator
        else "accelerator-packs/*/client-hub-blueprint/data-domains.yaml"
    )
    for path in sorted(Path(ref_models_dir).glob(pattern)):
        try:
            with open(path, encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
        except Exception as exc:  # defensive: advisory command, never fail the hub
            logger.warning("Could not read blueprint %s: %s", path, exc)
            continue
        if not isinstance(data, dict):
            continue
        bridges: list[BlueprintBridge] = []
        for entry in data.get("cross_domain_relationships") or []:
            if not isinstance(entry, dict):
                continue
            bridges.append(
                BlueprintBridge(
                    id=str(entry.get("id", "")),
                    property_uri=str(entry.get("property_uri", "")),
                    domain_class_uri=str(entry.get("domain_class_uri", "")),
                    range_class_uri=str(entry.get("range_class_uri", "")),
                    source_domain=str(entry.get("source_domain", "")),
                    target_domain=str(entry.get("target_domain", "")),
                    description=str(entry.get("description", "")),
                    status=str(entry.get("status", "")),
                )
            )
        if bridges:
            return tuple(bridges)
    return ()


# --------------------------------------------------------------------------------------
# Binding index
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BoundEntity:
    """The facts one authored EntityBinding contributes to relationship proposals."""

    name: str
    domain: str
    target_class: str
    source_relation: str
    source_key: tuple[str, ...]
    #: Authored source column -> materialized output column name (technicalFields only;
    #: ``fields:`` outputs are derived from the ontology property, not authored here).
    technical_outputs: dict[str, str] = field(default_factory=dict)
    #: Authored source column -> canonical type, from technicalFields.
    technical_types: dict[str, str] = field(default_factory=dict)
    #: Every source column the binding references (fields + technicalFields + identity).
    referenced_columns: tuple[str, ...] = ()
    relationship_count: int = 0
    #: ``(property token, target token)`` pairs already present in ``relationships:``,
    #: normalized with :func:`_class_token` so an authored qname target matches a parent
    #: whose ``target.class`` is the full URI. Kept alongside -- not derived from --
    #: ``relationship_count``: this set drops malformed entries, so a binding that *does*
    #: author relationships could otherwise be reported as having none.
    authored_relationships: frozenset[tuple[str, str]] = frozenset()
    #: Source columns the author declared ``purpose: relationship`` (DD-139). The author
    #: stating "this column is a foreign key", as opposed to anything we infer.
    relationship_columns: tuple[str, ...] = ()

    def output_column_for(self, source_column: str) -> tuple[str, str]:
        """Return (output column, canonical type) for a parent key column.

        Falls back to a snake_case rendering of the source column with a sentinel type
        when the parent never materialized it as a technical field -- the author must
        confirm both rather than trust a guess.
        """
        key = _normalize(source_column)
        for authored, output in self.technical_outputs.items():
            if _normalize(authored) == key:
                return output, self.technical_types.get(authored, SENTINEL_KEY_TYPE)
        return _snake(source_column), SENTINEL_KEY_TYPE


def _bare_column(expression: Any) -> Optional[str]:
    """Return the source column of a bare-column expression, else ``None``.

    Only the shorthand (``expression: order_id``) and the explicit ``{column: ...}`` node
    are treated as column references. Anything computed has no single source column, so it
    can never be a join key.
    """
    if isinstance(expression, str) and expression:
        return expression
    if isinstance(expression, dict):
        column = expression.get("column")
        if isinstance(column, str) and column:
            return column
    return None


def index_bindings(bindings_dir: Path) -> tuple[BoundEntity, ...]:
    """Read every authored EntityBinding into a :class:`BoundEntity` index."""
    if not Path(bindings_dir).is_dir():
        return ()
    entities: list[BoundEntity] = []
    for path in sorted(Path(bindings_dir).glob("*.binding.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        meta = data.get("metadata")
        if not isinstance(meta, dict):
            continue
        target = data.get("target") or {}
        identity = data.get("identity") or {}
        source = data.get("source") or {}

        source_key = tuple(
            col for col in (identity.get("sourceKey") or []) if isinstance(col, str) and col
        )
        technical_outputs: dict[str, str] = {}
        technical_types: dict[str, str] = {}
        referenced: list[str] = list(source_key)
        relationship_columns: list[str] = []
        for tech in data.get("technicalFields") or []:
            if not isinstance(tech, dict):
                continue
            column = _bare_column(tech.get("expression"))
            if column:
                technical_outputs[column] = str(tech.get("name", _snake(column)))
                technical_types[column] = str(tech.get("type", SENTINEL_KEY_TYPE))
                referenced.append(column)
                if str(tech.get("purpose", "")) == "relationship":
                    # The *source* column, not the technical field's output ``name``:
                    # ``join.local`` names the source column, which is why the canonical
                    # example joins ``local: account_id`` while the carrier is
                    # ``name: account_ref, expression: account_id``.
                    relationship_columns.append(column)
        for mapped in data.get("fields") or []:
            if not isinstance(mapped, dict):
                continue
            column = _bare_column(mapped.get("expression"))
            if column:
                referenced.append(column)

        authored: set[tuple[str, str]] = set()
        for relationship in data.get("relationships") or []:
            if not isinstance(relationship, dict):
                continue
            prop, rel_target = relationship.get("property"), relationship.get("target")
            if isinstance(prop, str) and prop and isinstance(rel_target, str) and rel_target:
                authored.add((_class_token(prop), _class_token(rel_target)))

        entities.append(
            BoundEntity(
                name=str(meta.get("name", path.stem)),
                domain=str(meta.get("domain", "")),
                target_class=str(target.get("class", "")) if isinstance(target, dict) else "",
                source_relation=str(source.get("relation", ""))
                if isinstance(source, dict)
                else "",
                source_key=source_key,
                technical_outputs=technical_outputs,
                technical_types=technical_types,
                referenced_columns=tuple(dict.fromkeys(referenced)),
                relationship_count=len(data.get("relationships") or []),
                authored_relationships=frozenset(authored),
                relationship_columns=tuple(dict.fromkeys(relationship_columns)),
            )
        )
    return tuple(entities)


# --------------------------------------------------------------------------------------
# Ontology-declared object properties (fallback / hub-local relationships)
# --------------------------------------------------------------------------------------


def load_ontology_edges(ontologies_dir: Path) -> tuple[tuple[str, str, str], ...]:
    """Return ``(property_uri, domain_class_uri, range_class_uri)`` from hub ontologies.

    Routed through the DD-103 canonical loader rather than parsing Turtle directly, so the
    import closure and the ``rdfs`` profile apply -- a relationship declared on an imported
    superclass is just as real an endpoint as one declared locally.

    Only properties with a **named** domain and range appear: a class-expression range
    (``owl:unionOf`` / ``owl:Restriction``) is a blank node the semantic index does not
    surface as a named class, so there is no endpoint to propose (DD-133 s7).
    """
    from .ontology_loader import SemanticProfile, load_ontology

    directory = Path(ontologies_dir)
    if not directory.is_dir():
        return ()
    edges: list[tuple[str, str, str]] = []
    for path in sorted(directory.glob("*.ttl")):
        if path.name.startswith("_"):
            continue
        try:
            result = load_ontology(path, profile=SemanticProfile.RDFS, degraded=True)
        except Exception:  # defensive: resolution errors are reported by `validate`
            continue
        index = getattr(result, "semantic_index", None)
        if index is None:
            continue
        for prop in index.properties:
            if prop.property_type != "object":
                continue
            for domain_link in prop.domains:
                for range_link in prop.ranges:
                    edges.append((prop.uri, domain_link.uri, range_link.uri))
        # DD-190 follow-up: derive the edge an owl:inverseOf entails when the
        # inverse property declares no domain/range of its own. Data FKs run
        # child→parent while blueprint properties are often declared
        # parent→child (TransportOrder coversConsignment); without the
        # entailed inverse edge, the FK side can never receive a proposal.
        # Read from the merged graph directly: the RDFS semantic profile this
        # loader uses deliberately does not surface inverse links (they are a
        # design-profile concern), but the assertion itself is in the closure.
        from rdflib import OWL

        inverse_pairs: set[tuple[str, str]] = set()
        for subject, obj in result.graph.subject_objects(OWL.inverseOf):
            inverse_pairs.add((str(subject), str(obj)))
            inverse_pairs.add((str(obj), str(subject)))
        own_edges = {
            p.uri for p in index.properties
            if p.property_type == "object" and p.domains and p.ranges
        }
        inverses_of: dict[str, list[str]] = {}
        for a, b in sorted(inverse_pairs):
            inverses_of.setdefault(a, []).append(b)
        for prop in index.properties:
            if prop.property_type != "object" or not (prop.domains and prop.ranges):
                continue
            for inverse_uri in inverses_of.get(prop.uri, ()):
                if inverse_uri in own_edges:
                    continue  # the inverse asserts its own endpoints; already emitted
                for domain_link in prop.domains:
                    for range_link in prop.ranges:
                        edges.append((inverse_uri, range_link.uri, domain_link.uri))
    return tuple(dict.fromkeys(edges))


# --------------------------------------------------------------------------------------
# Proposals
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RelationshipProposal:
    """One proposed ``relationships:`` entry, with its provenance."""

    child_binding: str
    child_domain: str
    parent_binding: str
    parent_domain: str
    property_uri: str
    target_class: str
    #: ``blueprint`` (declared bridge) or ``ontology`` (hub object property).
    evidence: str
    evidence_id: str
    #: How the edge's endpoint classes were matched to authored bindings: ``uri`` (exact
    #: class-URI equality) or ``local-name`` (same local name in a different namespace).
    endpoint_match: str
    local_column: str
    foreign_column: str
    #: True when the join columns were matched deterministically rather than sentinelled.
    join_resolved: bool
    external_reference: Optional[dict[str, Any]]
    #: How the join columns were matched: ``declared-fk`` (tier-0, a column the
    #: author declared ``purpose: relationship``), ``name`` (tier-1 equality),
    #: ``fk-inclusion`` (tier-2 measured containment, DD-189), or ``""`` when
    #: unresolved.
    join_evidence: str = ""
    #: Declared ``purpose: relationship`` columns offered as a hint when the join is
    #: unresolved. A hint, never a value -- "this child declares FK carriers, none of
    #: which names your key; you pick" (#722).
    join_candidates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "child_binding": self.child_binding,
            "child_domain": self.child_domain,
            "parent_binding": self.parent_binding,
            "parent_domain": self.parent_domain,
            "property": self.property_uri,
            "target": self.target_class,
            "evidence": self.evidence,
            "evidence_id": self.evidence_id,
            "endpoint_match": self.endpoint_match,
            "join": [{"local": self.local_column, "foreign": self.foreign_column}],
            "join_resolved": self.join_resolved,
            "join_evidence": self.join_evidence,
            "join_candidates": list(self.join_candidates),
            "external_reference": self.external_reference,
            "yaml": self.to_yaml(),
        }

    def to_yaml(self) -> str:
        """Render the proposal as a pasteable ``relationships:`` entry."""
        entry: dict[str, Any] = {
            "property": self.property_uri,
            "target": self.target_class,
            "join": [{"local": self.local_column, "foreign": self.foreign_column}],
            "cardinality": "many-to-one",
            "mode": "non-temporal",
            "missingParent": "error",
            "ambiguousParent": "error",
        }
        if self.external_reference is not None:
            entry["externalReference"] = self.external_reference
        return yaml.safe_dump([entry], sort_keys=False, allow_unicode=True).rstrip()


@dataclass(frozen=True, slots=True)
class RelationshipProposalReport:
    """All proposals plus the coverage facts that explain an empty result."""

    proposals: tuple[RelationshipProposal, ...]
    bindings_scanned: int
    bindings_without_relationships: tuple[str, ...]
    blueprint_bridges: int
    bridges_with_both_endpoints_bound: int
    notes: tuple[str, ...] = ()
    #: ``(child binding, property, target)`` triples suppressed because the child already
    #: authors that exact pair (#722). Reported rather than merely counted: the match is
    #: made on :func:`_class_token`, which is deliberately tolerant of namespace, so a
    #: reviewer must be able to see precisely what was withheld.
    already_authored: tuple[tuple[str, str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "bindings_scanned": self.bindings_scanned,
            "bindings_without_relationships": list(self.bindings_without_relationships),
            "blueprint_bridges": self.blueprint_bridges,
            "bridges_with_both_endpoints_bound": self.bridges_with_both_endpoints_bound,
            "proposals": [proposal.to_dict() for proposal in self.proposals],
            "already_authored": [
                {"child_binding": child, "property": prop, "target": target}
                for child, prop, target in self.already_authored
            ],
            "notes": list(self.notes),
        }


def _relation_parts(entity: BoundEntity) -> Optional[tuple[str, str]]:
    """``(system_lower, table)`` from a ``source.relation`` binding, else ``None``."""
    relation = entity.source_relation or ""
    if "." not in relation:
        return None
    system, table = relation.split(".", 1)
    return system.lower(), table


def _match_join(
    child: BoundEntity,
    parent: BoundEntity,
    fk_evidence: dict[tuple[str, str], dict[str, set[tuple[str, str]]]],
) -> tuple[str, str, bool, str]:
    """Match a child column to a parent key column. Returns
    ``(local, foreign, resolved, join_evidence)``.

    Tier 0 (#722) — a column the author declared ``purpose: relationship``
    (DD-139), matched by the same name equality as tier 1. Its value is not
    better matching but **exemption from the tier-1 identity exclusion below**:
    tier 1 is our inference and must yield to that structural argument, while a
    declaration is the author saying "this column is a foreign key" and must
    not. It is also the escape hatch for the one shape the exclusion costs — a
    1:1 extension table keyed by its parent's key.

    Matching stays by name here too, never positional: a child routinely carries
    several ``purpose: relationship`` columns aimed at different parents
    (``parent_invoice_source_id``, ``parent_subject_id``, …), so "one carrier,
    one parent key, therefore they pair" is a coin flip that would emit a
    *confidently* wrong join. A declared carrier that names no parent key falls
    through to the sentinel and is surfaced as a candidate instead.

    Tier 1 — exact normalized name equality, deliberately the same
    high-precision rule as ``scan_cross_source_fks``: prefix-stripped or fuzzy
    matches would manufacture false joins in a proposal a human is meant to
    trust.

    A tier-1 candidate that constitutes the child's **entire** identity is
    excluded (#722). A child whose whole ``sourceKey`` is one column that
    name-matches the parent's key has the same grain as the parent under the
    same name — the same-entity shape ``build_relationship_proposals`` already
    refuses (#334), not a many-to-one FK. Without this, a hub using one uniform
    surrogate identity name proposes ``source_record_id = source_record_id`` for
    every pair of relations, joining a row to itself. Narrower than "exclude
    every ``identity.sourceKey`` column" on purpose: that would kill the
    line-item child whose grain is ``[order_id, line_no]``, where ``order_id``
    genuinely *is* the FK.

    Tier 2 (DD-189) — measured value containment from the source profile: a
    child column tagged ``fk?-><parent table>.<key column>`` where that key
    column is in the parent's ``identity.sourceKey``. This is data evidence,
    not name similarity, so it resolves exactly the joins tier 1 cannot see
    (``goods.consignment_id → consignments``) without weakening tier 1's
    precision. Applies only within one source system — profiles are
    per-system and cross-system containment was never measured.
    """
    parent_keys = {_normalize(col): col for col in parent.source_key}
    child_identity = {_normalize(col) for col in child.source_key}

    for column in child.relationship_columns:
        match = parent_keys.get(_normalize(column))
        if match is not None:
            return column, match, True, "declared-fk"

    for column in child.referenced_columns:
        key = _normalize(column)
        match = parent_keys.get(key)
        if match is None:
            continue
        if child_identity == {key}:
            continue
        return column, match, True, "name"

    child_parts, parent_parts = _relation_parts(child), _relation_parts(parent)
    if child_parts and parent_parts and child_parts[0] == parent_parts[0]:
        for column in sorted(fk_evidence.get(child_parts, {})):
            for target_table, target_column in sorted(fk_evidence[child_parts][column]):
                if target_table != parent_parts[1]:
                    continue
                match = parent_keys.get(_normalize(target_column))
                if match is not None:
                    return column, match, True, "fk-inclusion"
    return SENTINEL_JOIN_COLUMN, SENTINEL_JOIN_COLUMN, False, ""


def _external_reference(child: BoundEntity, parent: BoundEntity, foreign: str) -> Optional[dict]:
    """Build the DD-138 external-reference contract for a cross-domain parent.

    ``name`` is the parent's generated dbt model name, which the compiler derives from the
    target *class* local name (``adapter._slug``), never from the binding or source table.
    """
    if child.domain == parent.domain:
        return None  # same-domain refs are rejected outright (#335)
    if foreign == SENTINEL_JOIN_COLUMN:
        # No parent key was matched, so there is no output column to name. Deriving one
        # from the sentinel would emit a real-looking `confirm_join_column`.
        column, canonical_type = SENTINEL_JOIN_COLUMN, SENTINEL_KEY_TYPE
    else:
        column, canonical_type = parent.output_column_for(foreign)
    return {
        "name": _slug(parent.target_class) or parent.name,
        "domain": parent.domain,
        "key": [{"column": column, "type": canonical_type}],
    }


def build_relationship_proposals(
    *,
    hub_root: Path,
    ref_models_dir: Optional[Path] = None,
    accelerator: Optional[str] = None,
    domain: Optional[str] = None,
) -> RelationshipProposalReport:
    """Propose ``relationships:`` entries for every authored binding in a hub."""
    from .profile_sources import load_fk_evidence

    bindings = index_bindings(Path(hub_root) / "integration" / "bindings")
    fk_evidence = load_fk_evidence(Path(hub_root) / "integration" / "sources")
    by_class: dict[str, list[BoundEntity]] = {}
    by_local_name: dict[str, list[BoundEntity]] = {}
    for entity in bindings:
        if entity.target_class:
            by_class.setdefault(entity.target_class, []).append(entity)
            by_local_name.setdefault(_local_name(entity.target_class).lower(), []).append(entity)

    def _endpoints(class_uri: str) -> tuple[list[BoundEntity], str]:
        """Resolve one edge endpoint to authored bindings.

        Exact class-URI equality first. Blueprint bridges name *reference-model* URIs,
        while a hub routinely authors its own classes in its own namespace (the CLdN hub
        binds ``https://cldn.com/ont/consignment#Consignment``, not the blueprint's
        ``.../mmt/consignment#Consignment``), so a URI-only match silently discards almost
        every declared bridge. The local-name fallback recovers them and is reported
        separately via ``endpoint_match`` so a weaker match is never mistaken for an exact
        one.
        """
        exact = by_class.get(class_uri)
        if exact:
            return exact, "uri"
        return by_local_name.get(_local_name(class_uri).lower(), []), "local-name"

    bridges = load_blueprint_bridges(ref_models_dir, accelerator)
    edges: list[tuple[str, str, str, str, str]] = [
        (b.property_uri, b.domain_class_uri, b.range_class_uri, "blueprint", b.id)
        for b in bridges
    ]
    for prop, dom, rng in load_ontology_edges(Path(hub_root) / "model" / "ontologies"):
        edges.append((prop, dom, rng, "ontology", _local_name(prop)))

    proposals: list[RelationshipProposal] = []
    already_authored: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    bridges_matched = 0
    for property_uri, domain_class, range_class, evidence, evidence_id in edges:
        children, child_match = _endpoints(domain_class)
        parents, parent_match = _endpoints(range_class)
        if not children or not parents:
            continue
        endpoint_match = "uri" if child_match == "uri" and parent_match == "uri" else "local-name"
        if evidence == "blueprint":
            bridges_matched += 1
        for child in children:
            if domain is not None and child.domain != domain:
                continue
            for parent in parents:
                if parent.name == child.name:
                    continue  # self-reference is unsupported by design (#334)
                if parent.target_class == child.target_class:
                    continue  # same class on both sides is the #334 shape too
                key = (child.name, parent.name, property_uri)
                if key in seen:
                    continue
                seen.add(key)
                # Compare against `parent.target_class` -- the very value that would have
                # become `RelationshipProposal.target_class` and been rendered by
                # `to_yaml`. The question is "is the entry I am about to render already
                # there?", not "does some relationship exist" (#722).
                authored_pair = (
                    _class_token(property_uri),
                    _class_token(parent.target_class),
                )
                if authored_pair in child.authored_relationships:
                    already_authored.append(
                        (child.name, property_uri, parent.target_class)
                    )
                    continue
                local, foreign, resolved, join_evidence = _match_join(
                    child, parent, fk_evidence
                )
                proposals.append(
                    RelationshipProposal(
                        child_binding=child.name,
                        child_domain=child.domain,
                        parent_binding=parent.name,
                        parent_domain=parent.domain,
                        property_uri=property_uri,
                        # The authored target must be a class the hub actually binds, not
                        # the blueprint's reference-model URI, or the endpoint would not
                        # resolve in the hub's own import closure.
                        target_class=parent.target_class,
                        evidence=evidence,
                        evidence_id=evidence_id,
                        endpoint_match=endpoint_match,
                        local_column=local,
                        foreign_column=foreign,
                        join_resolved=resolved,
                        external_reference=_external_reference(child, parent, foreign),
                        join_evidence=join_evidence,
                        join_candidates=(
                            () if resolved else child.relationship_columns
                        ),
                    )
                )

    # Resolved joins first, then blueprint over ontology evidence: the proposals a human
    # can accept with least verification lead.
    proposals.sort(
        key=lambda p: (
            not p.join_resolved,
            p.endpoint_match != "uri",
            p.evidence != "blueprint",
            p.child_binding,
            p.property_uri,
        )
    )

    notes: list[str] = []
    if not bridges:
        notes.append(
            "No accelerator blueprint cross_domain_relationships were available; "
            "proposals come from hub ontology object properties only."
        )
    if any(not p.join_resolved for p in proposals):
        notes.append(
            f"Join columns could not be matched for some proposals; those carry "
            f"{SENTINEL_JOIN_COLUMN} and must be completed by the author."
        )
    if already_authored:
        notes.append(
            f"{len(already_authored)} relationship(s) are already authored in the child "
            "binding and were not re-proposed, matched on (property, target) by local "
            "name. An authored entry's cardinality/mode/missingParent/ambiguousParent are "
            "the author's deliberate policy and must never be overwritten by a paste; see "
            "'already_authored' in --format json for the exact pairs withheld."
        )
    local_name_matches = sum(1 for p in proposals if p.endpoint_match == "local-name")
    if local_name_matches:
        notes.append(
            f"{local_name_matches} proposal(s) matched their endpoint classes by local "
            "name across namespaces, not by exact class URI — the hub authored its own "
            "class rather than binding the reference-model one. Confirm the endpoint is "
            "genuinely the same concept before accepting."
        )

    return RelationshipProposalReport(
        proposals=tuple(proposals),
        bindings_scanned=len(bindings),
        bindings_without_relationships=tuple(
            e.name for e in bindings if e.relationship_count == 0
        ),
        blueprint_bridges=len(bridges),
        bridges_with_both_endpoints_bound=bridges_matched,
        notes=tuple(notes),
        already_authored=tuple(already_authored),
    )
