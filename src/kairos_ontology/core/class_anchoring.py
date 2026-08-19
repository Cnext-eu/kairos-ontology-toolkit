# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Suggest reference-model anchors for locally declared terms (DD-165).

DD-163 made an unanchored local class *visible* — ``integrity.class-unanchored`` and
``integrity.local-class-shadows-reference-model`` both report it. Visibility alone does
not change what gets authored: a full 21-domain run anchored 5 of 132 classes (4%) and
0 of 473 properties, while declaring 57 ``owl:imports`` and referencing 4 of them. The
reference models were installed, imported, and then ignored.

The reason is mundane. Finding the class to specialise means knowing which of ~80
materialized inventories covers the domain's imports, then reading it for a plausible
match — expensive enough that inventing a local class is always the cheaper move. A
hand-built hub reached 87% anchoring precisely because a human paid that cost.

This module pays it deterministically. Given a domain, it reads the inventories for the
modules the domain already imports and ranks candidate anchors for each unanchored local
term, emitting the exact ``rdfs:subClassOf`` / ``rdfs:subPropertyOf`` line to paste.

It suggests and never writes. Whether ``party:Party`` should specialise
``mmt:TransportParty`` is a modelling judgement, and one the pattern library has strong
views about: ``qualified-role-assignment`` names five party parents that are "not the
durable identity on its own". So every candidate carries its score, its reason, and any
pattern-library caution — but a flagged candidate is still ranked on its evidence.
Demoting it instead buried ``TransportParty``, the class the archetype marks *required*
for this domain, beneath two deprecated role overlays. Warn on the ranked answer; do not
quietly reorder around the warning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA_VERSION = 1

#: Below this, a name similarity is coincidence rather than a candidate.
#:
#: An early version also scored "same head noun", which produced
#: ``companyBillingPostalCode -> companyCode`` and ``companyLegalName -> contactName``.
#: Suggestions like those are worse than silence: they are wrong, they look considered,
#: and acting on one writes a false subsumption into the canonical model.
SCORE_FLOOR = 0.7

#: At or above this, the name evidence is strong enough to emit a paste-ready
#: ``rdfs:subClassOf`` line. Below it the candidates are shown for review but the Turtle
#: is withheld, because the remaining matches ("X is a qualified form of Y") cannot
#: distinguish the right specialisation from a sibling: ``Party`` matches both
#: ``TransportParty`` (the archetype's required durable identity) and ``NotifyParty``
#: (a deprecated role overlay) equally well on name alone.
AUTO_ANCHOR_SCORE = 0.9

#: Candidates offered per local term. Three is enough to show the shape of the choice
#: without turning the output into a second inventory to read.
MAX_CANDIDATES = 3


@dataclass(frozen=True)
class ReferenceTerm:
    """One class or property declared by a reference-model module."""

    uri: str
    name: str
    label: str
    comment: str
    module: str
    kind: str  # "class" | "property"


@dataclass(frozen=True)
class AnchorCandidate:
    uri: str
    name: str
    label: str
    module: str
    score: float
    reason: str
    caution: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "label": self.label,
            "module": self.module,
            "score": round(self.score, 3),
            "reason": self.reason,
            "caution": self.caution,
        }


@dataclass(frozen=True)
class AnchorSuggestion:
    local_name: str
    local_uri: str
    kind: str  # "class" | "property"
    candidates: tuple[AnchorCandidate, ...]

    @property
    def predicate(self) -> str:
        return "rdfs:subClassOf" if self.kind == "class" else "rdfs:subPropertyOf"

    @property
    def confident(self) -> bool:
        """True when the top candidate's name evidence justifies a paste-ready line."""
        return bool(self.candidates) and self.candidates[0].score >= AUTO_ANCHOR_SCORE

    def turtle_line(self) -> str:
        """The line to paste, or a comment saying why one is withheld.

        Turtle is only emitted for a confident match. Below that the candidates are
        real but indistinguishable on name alone, and handing over a paste-ready line
        would convert "these three are worth a look" into "this one is correct".
        """
        if not self.candidates:
            return f"# {self.local_name}: no reference-model candidate in imported modules"
        if not self.confident:
            # Qualify by module: the same term name legitimately occurs in several
            # modules ("currency" in three), and a bare repeated name reads as a bug.
            names = ", ".join(
                f"{c.name} [{c.module.rstrip('#/').rsplit('/', 1)[-1]}]" for c in self.candidates
            )
            return f"# {self.local_name}: review candidates ({names}) — choose deliberately"
        return f"{self.predicate} <{self.candidates[0].uri}> ;"

    def to_dict(self) -> dict[str, Any]:
        return {
            "local_name": self.local_name,
            "local_uri": self.local_uri,
            "kind": self.kind,
            "predicate": self.predicate,
            "turtle": self.turtle_line(),
            "candidates": [c.to_dict() for c in self.candidates],
        }


@dataclass
class AnchorReport:
    schema_version: int = SCHEMA_VERSION
    domain: str = ""
    suggestions: list[AnchorSuggestion] = field(default_factory=list)
    already_anchored: int = 0
    unanchored: int = 0
    modules_read: tuple[str, ...] = ()
    available_terms: int = 0
    notices: list[str] = field(default_factory=list)

    @property
    def with_candidates(self) -> list[AnchorSuggestion]:
        return [s for s in self.suggestions if s.candidates]

    @property
    def confident(self) -> list[AnchorSuggestion]:
        """Suggestions strong enough to paste without further judgement."""
        return [s for s in self.suggestions if s.confident]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "domain": self.domain,
            "totals": {
                "already_anchored": self.already_anchored,
                "unanchored": self.unanchored,
                "with_candidates": len(self.with_candidates),
                "confident": len(self.confident),
                "modules_read": len(self.modules_read),
                "available_terms": self.available_terms,
            },
            "modules": list(self.modules_read),
            "suggestions": [s.to_dict() for s in self.suggestions],
            "notices": list(self.notices),
        }


# ---------------------------------------------------------------------------
# Inventory reading
# ---------------------------------------------------------------------------


def _local_name(uri: str) -> str:
    if "#" in uri:
        return uri.rsplit("#", 1)[1]
    return uri.rstrip("/").rsplit("/", 1)[-1]


def _module_of(uri: str) -> str:
    if "#" in uri:
        return uri.rsplit("#", 1)[0]
    return uri.rstrip("/").rsplit("/", 1)[0]


def read_reference_terms(
    catalog_path: Optional[Path],
    *,
    module_scope: Optional[Iterable[str]] = None,
) -> list[ReferenceTerm]:
    """Resolve reference-model classes and properties, live from the catalog (DD-173).

    Reads through ``parse_reference_model`` — the same canonical DD-103 loader path the
    aligner uses, resolving ``owl:imports`` and honouring the DD-131 domain authority —
    rather than the materialized ``referencemodels-unpacked/*.yaml`` snapshots this used
    to consume.

    The snapshots were removed because they were indistinguishable from truth. Generated
    once per hub, nothing marked them invalid when the resolver itself was fixed, so a
    hub carried the old wrong answer indefinitely: every inventory written before the
    ``schema:domainIncludes`` fix omits the whole REUSABLE property family, and the same
    class appeared with 9 or 13 properties depending on which snapshot a caller happened
    to read. Resolving live costs ~60ms for two modules, which is nothing against the
    LLM stages this feeds, and it cannot go stale.

    *module_scope* (DD-193): when given, restrict the seed module set to these
    module URIs (matched with a trailing ``#``/``/`` stripped, the same
    normalization ``build_class_catalog`` uses for ownership) instead of every
    module the whole installed reference-models catalog happens to map.
    ``None`` (the default) keeps the unrestricted behaviour every existing
    caller relies on — only ``build_class_catalog`` opts in, seeded with the
    resolved accelerator's own declared imports. Each seed module's
    ``owl:imports`` closure is still resolved in full through the canonical
    loader (unchanged): scoping restricts *which modules seed the walk*, not
    how far each seed's own closure reaches, so a foundation module reached
    only via ``owl:imports`` from an accelerator-declared module remains
    visible. A module the accelerator never imports, directly or
    transitively — FIBO in a logistics hub with no financial-services domain
    — is excluded outright rather than merely marked ``UNOWNED``.

    Returns ``[]`` when no catalog resolves; callers report that as a notice.
    """
    terms: list[ReferenceTerm] = []
    if catalog_path is None or not Path(catalog_path).is_file():
        return terms

    from .catalog_utils import CatalogResolver
    from .propose_alignment import extract_ref_model_inventory

    try:
        resolver = CatalogResolver.with_reference_models(Path(catalog_path))
    except Exception:  # defensive: a broken catalog must not fail the suggestion
        return terms

    # Every IRI the catalog maps, minus the hub's own domain ontologies — those are the
    # thing being checked, not reference material, and a hub class must never be offered
    # as an anchor for itself.
    #
    # Selected by resolved path rather than by hostname: an earlier version filtered on
    # "kairosflow.ai", which silently excluded every other vendor's reference model and
    # any test fixture.
    own_domains = (Path(catalog_path).parent / "model" / "ontologies").resolve()

    def _is_reference(target: Path) -> bool:
        try:
            return own_domains not in Path(target).resolve().parents
        except OSError:
            return True

    module_uris = sorted(
        {
            uri
            for uri, target in resolver.mappings.items()
            if uri.startswith("http") and _is_reference(Path(target))
        }
    )
    if module_scope is not None:
        normalized_scope = {str(u).rstrip("#/") for u in module_scope}
        module_uris = [u for u in module_uris if u.rstrip("#/") in normalized_scope]
    if not module_uris:
        return terms

    seen: set[str] = set()
    for cls in extract_ref_model_inventory(module_uris, Path(catalog_path)):
        uri = str(cls.get("uri") or "")
        if uri.startswith("http") and uri not in seen:
            seen.add(uri)
            terms.append(
                ReferenceTerm(
                    uri=uri,
                    name=str(cls.get("name") or _local_name(uri)),
                    label=str(cls.get("label") or ""),
                    comment=str(cls.get("comment") or ""),
                    module=_module_of(uri),
                    kind="class",
                )
            )
        for prop in cls.get("properties") or []:
            puri = str(prop.get("uri") or "")
            if not puri.startswith("http") or puri in seen:
                continue
            seen.add(puri)
            terms.append(
                ReferenceTerm(
                    uri=puri,
                    name=str(prop.get("name") or _local_name(puri)),
                    label=str(prop.get("label") or ""),
                    comment=str(prop.get("comment") or ""),
                    module=_module_of(puri),
                    kind="property",
                )
            )
    return terms


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _split_camel(name: str) -> list[str]:
    return [p.lower() for p in re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+", name)]


def _singular(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        return token[:-1]
    return token


def score_anchor(local_name: str, candidate: ReferenceTerm) -> tuple[float, str]:
    """Score *candidate* as an anchor for *local_name*, with a stated reason.

    Deliberately lexical and explainable. A semantic match this cannot see is a
    modelling judgement the author still has to make; a confident-looking score derived
    from an opaque similarity would make that judgement harder, not easier.
    """
    if local_name == candidate.name:
        return 1.0, "exact name match"
    if local_name.lower() == candidate.name.lower():
        return 0.95, "name matches, different casing"

    local_parts = _split_camel(local_name)
    cand_parts = _split_camel(candidate.name)
    if not local_parts or not cand_parts:
        return 0.0, ""

    if [_singular(p) for p in local_parts] == [_singular(p) for p in cand_parts]:
        return 0.9, "same name in singular/plural form"

    # "Party" vs "TransportParty": the reference class is the same concept, qualified.
    if cand_parts[-len(local_parts) :] == local_parts:
        return 0.8, f"'{candidate.name}' is a qualified form of '{local_name}'"
    if local_parts[-len(cand_parts) :] == cand_parts:
        return 0.8, f"'{local_name}' is a qualified form of '{candidate.name}'"

    label_parts = _split_camel(candidate.label.replace(" ", "")) if candidate.label else []
    if label_parts and [_singular(p) for p in label_parts] == [_singular(p) for p in local_parts]:
        return 0.85, f"matches the reference label '{candidate.label}'"

    # Nothing weaker scores. A shared head noun alone ("...Code", "...Name", "...Number")
    # is the single most common way two unrelated terms look similar.
    return 0.0, ""


#: Reference classes the pattern library marks as grain collisions — role-bearing party
#: parents that are not the durable identity. Offering one as a top anchor would push an
#: author straight into ``subclass-identity-by-role``, the exact anti-pattern
#: ``qualified-role-assignment`` exists to prevent, so they are flagged, not hidden:
#: a hub may still have a defensible reason, but it must be a decision.
_GRAIN_COLLISION_URIS: frozenset[str] = frozenset(
    {
        "https://www.kairosflow.ai/ont/bsp/party#TradeParty",
        "https://www.kairosflow.ai/ont/mmt/party#TransportParty",
        "https://www.kairosflow.ai/ont/dcsa/party#ShippingParty",
        "https://www.kairosflow.ai/ont/imo/party#MaritimeParty",
        "https://www.kairosflow.ai/ont/tic/party#TerminalParty",
        "https://www.kairosflow.ai/ont/dcsa/locations#PortOfLoading",
        "https://www.kairosflow.ai/ont/dcsa/locations#PortOfDischarge",
    }
)

_GRAIN_COLLISION_NOTE = (
    "pattern library flags this as a grain collision (role-bearing parent, not the "
    "durable identity) — see blueprints/patterns/qualified-role-assignment before "
    "subclassing it"
)


#: Nudge applied to a candidate the hub's archetype actually asks for.
#:
#: Name evidence cannot separate ``TransportParty`` from ``NotifyParty`` as anchors for a
#: local ``Party`` -- eight classes in the party modules end in "Party" and all score
#: identically. The archetype can: it lists ``mmt/party#TransportParty`` as *required*
#: ("the durable identity") and ``NotifyParty`` as *optional* ("deprecated role
#: overlay"). Without this the arbitrary alphabetical cut dropped the one class the
#: archetype mandates. Deliberately smaller than the gap between score tiers, so tier
#: breaks ties and never overturns stronger name evidence.
_TIER_BOOST: dict[str, float] = {"required": 0.06, "recommended": 0.04, "optional": 0.02}


def rank_candidates(
    local_name: str,
    kind: str,
    pool: Iterable[ReferenceTerm],
    archetype_tiers: Optional[dict[str, str]] = None,
) -> tuple[AnchorCandidate, ...]:
    """Return the best anchors for one local term, strongest first.

    *archetype_tiers* maps a reference-model class URI to its archetype tier. When
    supplied, a class the archetype asks for outranks an equally-named one it does not.
    """
    tiers = archetype_tiers or {}
    scored: list[AnchorCandidate] = []
    for term in pool:
        if term.kind != kind:
            continue
        score, reason = score_anchor(local_name, term)
        if score < SCORE_FLOOR:
            continue
        tier = tiers.get(term.uri, "")
        boost = _TIER_BOOST.get(tier, 0.0)
        if boost:
            reason = f"{reason}; archetype tier: {tier}"
        scored.append(
            AnchorCandidate(
                uri=term.uri,
                name=term.name,
                label=term.label,
                module=term.module,
                score=score + boost,
                reason=reason,
                caution=(_GRAIN_COLLISION_NOTE if term.uri in _GRAIN_COLLISION_URIS else ""),
            )
        )
    # Ordering is by evidence only. An earlier version sorted flagged grain collisions
    # last, which buried TransportParty -- the archetype's required party identity, and a
    # flagged collision -- beneath two deprecated role overlays. The caution belongs in
    # the annotation, where the author reads it, not in the ranking.
    scored.sort(key=lambda c: (-c.score, c.name))
    return tuple(scored[:MAX_CANDIDATES])


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def suggest_anchors(
    *,
    ontologies_dir: Path,
    domain: str,
    catalog_path: Optional[Path],
    archetype_tiers: Optional[dict[str, str]] = None,
) -> AnchorReport:
    """Rank reference-model anchors for every unanchored term in *domain*.

    *archetype_tiers* maps a reference-model class URI to its tier in the hub's selected
    archetype. Optional: without it ranking falls back to name evidence alone, which is
    correct but cannot separate same-named siblings.
    """
    from .ontology_integrity import scan_domain_ontology

    report = AnchorReport(domain=domain)
    path = Path(ontologies_dir) / f"{domain}.ttl"
    if not path.is_file():
        report.notices.append(f"No ontology found at {path}.")
        return report

    onto = scan_domain_ontology(path, domain)
    if onto is None:
        report.notices.append(f"{path} could not be parsed; fix syntax first.")
        return report

    all_terms = read_reference_terms(catalog_path)
    if not all_terms:
        report.notices.append(
            "No reference models resolved from the hub catalog "
            "(ontology-hub/catalog-v001.xml)."
        )
        return report

    # Only the modules this domain already imports. Suggesting an anchor from a module
    # the domain does not import would produce a dangling reference that
    # validate's managed-import check then rejects.
    imported = set(onto.imports)
    pool = [t for t in all_terms if t.module.rstrip("#/") in imported]
    report.modules_read = tuple(sorted({t.module for t in pool}))
    report.available_terms = len(pool)
    if not pool:
        report.notices.append(
            f"Domain '{domain}' imports {len(imported)} module(s), none of which "
            "resolve through the hub catalog."
        )
        return report

    for kind, terms, anchored in (
        ("class", onto.classes, onto.anchored_classes),
        ("property", onto.properties, onto.anchored_properties),
    ):
        for name, uri in sorted(terms.items()):
            if name in anchored:
                report.already_anchored += 1
                continue
            report.unanchored += 1
            report.suggestions.append(
                AnchorSuggestion(
                    local_name=name,
                    local_uri=uri,
                    kind=kind,
                    candidates=rank_candidates(name, kind, pool, archetype_tiers),
                )
            )

    if not onto.classes and not onto.properties:
        report.notices.append(
            f"Domain '{domain}' declares no local terms yet; {len(pool)} reference-model "
            "term(s) are available from its imports to reuse directly."
        )
    return report
