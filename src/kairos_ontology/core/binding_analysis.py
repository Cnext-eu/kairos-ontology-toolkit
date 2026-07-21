# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Canonical binding analysis (B0) for the target-first stub → bind loop.

This module is the **single** authority for per-class materialization reasoning.
It decides, per **projected class**, whether its Silver physical model is:

* ``BOUND``   — one or more bronze source tables map to it (directly or via
  discriminator folding / a contracted virtual source);
* ``FOLDED``  — the class is an S3 discriminator subtype absorbed into its parent
  model (no separate physical model of its own);
* ``STUB``    — the class is an *approved, materialization-eligible* claim that is
  not yet bound to any source (an *aspirational* target). This state is derived
  **independently of whether projection stub emission is enabled** so status and
  the release gate reason correctly even when the projector's stub flag is off; or
* ``SKIPPED`` — an unbound class with no approving claim (today's default: no
  broken placeholders).

The binding facts (``class_to_sources`` + discriminator folding) are computed
once by :func:`medallion_dbt_projector.compute_source_bindings`, so the projector
and every downstream consumer (coverage, release gate, ``status`` scan) share the
*same* notion of "is bound" rather than reimplementing divergent heuristics. A
caller that already computed the bindings can pass them into :func:`build` to
avoid recomputing them.

``aspirational`` is **derived, not persisted** (see ``silverfirstdesign.md`` §4a
and DD-096): a class is aspirational iff it is a materialization-eligible approved
claim **and** :data:`STUB` here — no field is added to the claim / silver-impact
model. Aspirational derivation (:meth:`BindingAnalysis.is_aspirational`) is kept
distinct from stub *emission* (:meth:`BindingAnalysis.should_emit_stub`, gated by
``stubs_enabled``): decoupling them lets status/release consume one canonical
result while the projector's feature-off byte behaviour stays unchanged.

The registry-fact helpers (:func:`materialization_eligible_class_uris`,
:func:`approved_imported_class_uris`) are the canonical claim filters; the Claim
Registry remains the sole governed eligibility authority (DD-094) and these
helpers never relax its ``status``/``disposition``/``type`` rules.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from rdflib import Graph, RDFS, URIRef

from .projections.shared import KAIROS_EXT

if TYPE_CHECKING:
    from .claim_registry import ClaimRegistry
    from .projections.medallion_dbt_projector import SourceBindings

# Binding states -------------------------------------------------------------
BOUND = "bound"
FOLDED = "folded"
STUB = "stub"
SKIPPED = "skipped"

#: A claim materializes a Silver model only for these dispositions (DD-094 /
#: DEC-5). ``gap`` / ``passthrough`` / ``skip`` never produce a stub.
MATERIALIZATION_DISPOSITIONS = frozenset({"claim", "specialize"})
#: Only class-like claims materialize a Silver entity model.
MATERIALIZATION_TYPES = frozenset({"class", "reference_data"})
#: An imported claim's ``origin`` — the marker for a class pulled in from a
#: reference model (drives ``owl:imports`` / ``silverInclude`` sync, A1).
IMPORTED_ORIGIN = "imported"


def materialization_eligible_class_uris(registry: "ClaimRegistry") -> set[str]:
    """Return class URIs of approved, materialization-eligible claims.

    A claim is materialization-eligible iff ``status == approved`` and its
    ``disposition`` is claim/specialize and its ``type`` is class/reference_data
    (DD-094 authority + DEC-5). These are the classes that *should* have a Silver
    physical model even before a bronze mapping exists.
    """
    uris: set[str] = set()
    for claim in registry.claims:
        if claim.status != "approved":
            continue
        if claim.disposition not in MATERIALIZATION_DISPOSITIONS:
            continue
        if claim.type not in MATERIALIZATION_TYPES:
            continue
        if not claim.class_uri:
            continue
        uris.add(claim.class_uri)
    return uris


def approved_imported_class_uris(registry: "ClaimRegistry") -> set[str]:
    """Return class URIs of approved, imported class claims (projection sync).

    A claim drives ``owl:imports`` / ``silverInclude`` sync iff ``status ==
    approved``, ``origin == imported`` and its ``disposition`` is claim/specialize
    with a ``class_uri``. This is the canonical filter consumed by
    :mod:`claim_projection_sync` (which additionally drops classes local to the
    importing domain), so import sync and materialization never diverge on which
    claims count. The Claim Registry stays the sole eligibility authority (DD-094);
    proposed/rejected/deferred claims are excluded here.
    """
    uris: set[str] = set()
    for claim in registry.claims:
        if claim.status != "approved":
            continue
        if claim.origin != IMPORTED_ORIGIN:
            continue
        if claim.disposition not in MATERIALIZATION_DISPOSITIONS:
            continue
        if not claim.class_uri:
            continue
        uris.add(claim.class_uri)
    return uris


def is_discriminator_subclass(graph: Graph, class_uri: str) -> tuple[bool, str | None]:
    """Return ``(True, parent_local)`` if the class is S3-folded into a parent.

    Mirrors the discriminator-subclass detection in the silver entity loop: a
    class whose (non-W3C) superclass declares
    ``kairos-ext:inheritanceStrategy = "discriminator"`` has no separate Silver
    model — it is absorbed into the parent.
    """
    from .projections.uri_utils import extract_local_name

    for parent in graph.objects(URIRef(class_uri), RDFS.subClassOf):
        if not isinstance(parent, URIRef):
            continue
        if str(parent).startswith("http://www.w3.org/"):
            continue
        strategy = graph.value(parent, KAIROS_EXT.inheritanceStrategy)
        if strategy and str(strategy) == "discriminator":
            return True, extract_local_name(str(parent))
    return False, None


def classify_binding(
    *,
    has_sources: bool,
    discriminator_subclass: bool,
    is_eligible: bool,
) -> str:
    """Pure classifier for a single projected class.

    Precedence: a bound class is always :data:`BOUND` (even if it is also a
    discriminator parent); an unbound discriminator subtype is :data:`FOLDED`; an
    unbound materialization-eligible claim is a :data:`STUB` (an *aspirational*
    target); otherwise :data:`SKIPPED`.

    The classification is **independent of whether projection stub emission is
    enabled** — :data:`STUB` is the aspirational state itself, so status and the
    release gate reason correctly even when the projector's stub flag is off.
    Whether an aspirational class is *emitted* as a stub model is a separate,
    ``stubs_enabled``-gated decision (:meth:`BindingAnalysis.should_emit_stub`).
    """
    if has_sources:
        return BOUND
    if discriminator_subclass:
        return FOLDED
    if is_eligible:
        return STUB
    return SKIPPED


#: Deterministic per-state reason text (keeps consumers/reasons byte-stable).
_STATE_REASONS = {
    BOUND: "bound to bronze source(s)",
    STUB: "approved claim, no bronze mapping (aspirational)",
    SKIPPED: "no bronze mapping and no approving claim",
}


def _reason_for(state: str, parent_local: str | None) -> str:
    """Return the deterministic reason string for a classified *state*."""
    if state == FOLDED:
        return f"S3 discriminator subclass of {parent_local}"
    return _STATE_REASONS.get(state, _STATE_REASONS[SKIPPED])


@dataclass
class BindingAnalysis:
    """Per-class binding classification over a domain's projected classes.

    This is the one canonical result consumed by the projector (stub emission),
    the ``status`` scan (aspirational reporting), and the ``--strict`` release
    gate (release eligibility). ``stubs_enabled`` records whether projection stub
    *emission* is turned on; it never affects the :data:`STUB` classification,
    only :meth:`should_emit_stub` / :meth:`is_materialized`.
    """

    states: dict[str, str] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    eligible_class_uris: set[str] = field(default_factory=set)
    stubs_enabled: bool = False

    def state(self, class_uri: str) -> str:
        return self.states.get(class_uri, SKIPPED)

    def reason(self, class_uri: str) -> str:
        """Return the deterministic classification reason for *class_uri*."""
        return self.reasons.get(class_uri, _STATE_REASONS[SKIPPED])

    def is_bound(self, class_uri: str) -> bool:
        return self.states.get(class_uri) == BOUND

    def is_folded(self, class_uri: str) -> bool:
        return self.states.get(class_uri) == FOLDED

    def is_eligible(self, class_uri: str) -> bool:
        """True iff *class_uri* is a materialization-eligible approved claim."""
        return class_uri in self.eligible_class_uris

    def is_aspirational(self, class_uri: str) -> bool:
        """True iff the class is an unbound materialization-eligible stub.

        Derived independently of ``stubs_enabled`` (DD-096): an aspirational class
        is aspirational whether or not the projector emits a stub for it.
        """
        return self.states.get(class_uri) == STUB

    def should_emit_stub(self, class_uri: str) -> bool:
        """True iff the projector should emit a physical stub model for the class.

        This is the only place the ``stubs_enabled`` byte-gate combines with the
        derived aspirational state, keeping feature-off output byte-identical.
        """
        return self.stubs_enabled and self.is_aspirational(class_uri)

    def is_release_blocking(self, class_uri: str) -> bool:
        """True iff the class blocks a ``--strict`` release (unbound eligible).

        Release eligibility is independent of stub emission: an approved,
        materialization-eligible, unbound claim blocks release whether or not a
        vacuous stub was emitted for it (DD-096 / DEC-1).
        """
        return self.is_aspirational(class_uri)

    def is_materialized(self, class_uri: str) -> bool:
        """True iff the class yields a physical Silver model in this projection.

        A bound class always materializes; an aspirational class materializes only
        when stub emission is enabled. Folded/skipped classes never do.
        """
        state = self.states.get(class_uri)
        if state == BOUND:
            return True
        if state == STUB:
            return self.stubs_enabled
        return False

    def class_uris_in_state(self, state: str) -> list[str]:
        return sorted(uri for uri, st in self.states.items() if st == state)

    def aspirational_class_uris(self) -> list[str]:
        """Return the sorted set of aspirational (unbound eligible) class URIs."""
        return self.class_uris_in_state(STUB)

    def release_blocking_class_uris(self) -> list[str]:
        """Return the sorted class URIs that block a ``--strict`` release."""
        return self.class_uris_in_state(STUB)

    def materialized_class_uris(self) -> list[str]:
        """Return the sorted class URIs that yield a physical Silver model."""
        return sorted(uri for uri in self.states if self.is_materialized(uri))


def build(
    *,
    classes: list[dict],
    graph: Graph,
    systems: list[dict],
    mappings: dict,
    contract_registry=None,
    eligible_class_uris: set[str] | None = None,
    stubs_enabled: bool = False,
    bindings: "SourceBindings | None" = None,
) -> BindingAnalysis:
    """Compute the canonical :class:`BindingAnalysis` for a domain.

    Grounds the classification in :func:`medallion_dbt_projector.compute_source_bindings`
    so the projector and every downstream consumer share the exact same
    ``class_to_sources`` (discriminator folding + contracted virtual sources
    resolved). A caller that already has the ``SourceBindings`` — e.g. the dbt
    projector inside ``_gen_silver_models`` — passes them via *bindings* so they
    are never recomputed; otherwise they are computed here (imported lazily to
    avoid an import cycle).

    ``stubs_enabled`` records whether projection stub emission is on. It does
    **not** influence the :data:`STUB` classification (aspirational is derived
    regardless); it only feeds :meth:`BindingAnalysis.should_emit_stub` and
    :meth:`BindingAnalysis.is_materialized`.
    """
    eligible = eligible_class_uris or set()
    if bindings is None:
        from .projections.medallion_dbt_projector import compute_source_bindings

        bindings = compute_source_bindings(
            classes=classes,
            graph=graph,
            systems=systems,
            mappings=mappings,
            contract_registry=contract_registry,
        )

    analysis = BindingAnalysis(
        eligible_class_uris=set(eligible), stubs_enabled=stubs_enabled
    )
    for cls in classes:
        cls_uri = cls["uri"]
        has_sources = bool(bindings.class_to_sources.get(cls_uri))
        disc, parent_local = (False, None)
        if not has_sources:
            disc, parent_local = is_discriminator_subclass(graph, cls_uri)
        state = classify_binding(
            has_sources=has_sources,
            discriminator_subclass=disc,
            is_eligible=cls_uri in eligible,
        )
        analysis.states[cls_uri] = state
        analysis.reasons[cls_uri] = _reason_for(state, parent_local)
    return analysis


@dataclass
class DomainBindingSnapshot:
    """The canonical :class:`BindingAnalysis` for one domain, resolved directly
    from committed hub authorities — the Claim Registry (eligibility), the domain
    ontology + Silver extension (the projected class set), and the source
    vocabularies + SKOS mappings (binding). No generated output is read.

    This is the single "from-hub-authorities" entrypoint shared by the ``status``
    scan (D4 aspirational-stub reporting, DD-096) and the deterministic lifecycle
    gate (release eligibility), so both derive identical bound/aspirational facts
    from one computation instead of two divergent implementations.
    """

    analysis: BindingAnalysis
    classes_by_uri: dict[str, str]

    def local_names(self, uris: Iterable[str]) -> list[str]:
        """Return the sorted local names of *uris* that are known classes."""
        return sorted(self.classes_by_uri[u] for u in uris if u in self.classes_by_uri)

    def aspirational_names(self) -> list[str]:
        """Sorted local names of aspirational (unbound eligible/release-blocking) classes."""
        return self.local_names(self.analysis.aspirational_class_uris())

    def bound_names(self) -> list[str]:
        """Sorted local names of bound classes."""
        return self.local_names(u for u in self.classes_by_uri if self.analysis.is_bound(u))


def analyze_domain_from_hub(hub_root: Path, domain: str) -> DomainBindingSnapshot | None:
    """Resolve one domain's canonical :class:`BindingAnalysis` from committed hub
    authorities, without running a projection.

    Loads the Claim Registry (``model/claims/{domain}-claims.yaml``) for
    materialization eligibility, the domain ontology (+ catalog-resolved imports
    and Silver extension, when present) for the projected class set, and the
    source vocabularies + SKOS mappings for binding, then delegates classification
    to the canonical :func:`build` — never a re-implementation of its rules.

    Returns ``None`` when the domain has no claims registry or ontology (no
    eligibility authority to derive from), when the ontology has no local
    classes, or on any load error — callers degrade to "nothing to report",
    keeping this as robust and deterministic as the rest of the scan surface.
    """
    hub_root = Path(hub_root)
    try:
        from rdflib import OWL, RDF

        from .claim_registry import load_registry
        from .projections.medallion_dbt_projector import (
            _parse_bronze,
            _parse_skos_mappings,
        )
        from .projections.uri_utils import extract_local_name

        claims_file = hub_root / "model" / "claims" / f"{domain}-claims.yaml"
        onto_file = hub_root / "model" / "ontologies" / f"{domain}.ttl"
        if not claims_file.exists() or not onto_file.exists():
            return None

        eligible = materialization_eligible_class_uris(load_registry(claims_file))

        catalog_file = hub_root / "catalog-v001.xml"
        from .ontology_loader import SemanticProfile, load_ontology

        graph = load_ontology(
            onto_file,
            catalog_path=catalog_file if catalog_file.is_file() else None,
            profile=SemanticProfile.KAIROS_DESIGN,
        ).graph
        silver_ext = hub_root / "model" / "extensions" / f"{domain}-silver-ext.ttl"
        if silver_ext.exists():
            graph.parse(silver_ext, format="turtle")

        # Detect the domain base to select local classes (bare IRI + #// variants).
        base = None
        for subj in graph.subjects(RDF.type, OWL.Ontology):
            if isinstance(subj, URIRef) and not str(subj).endswith("-silver-ext"):
                base = str(subj).rstrip("#/")
                break
        classes: list[dict] = []
        for cls in graph.subjects(RDF.type, OWL.Class):
            if not isinstance(cls, URIRef):
                continue
            uri = str(cls)
            is_local = base is None or (
                uri.startswith(base + "#") or uri.startswith(base + "/")
            )
            if not is_local and uri not in eligible:
                continue
            classes.append({"uri": uri, "name": extract_local_name(uri)})
        if not classes:
            return None

        sources_dir = hub_root / "integration" / "sources"
        mappings_dir = hub_root / "model" / "mappings"
        systems = _parse_bronze(sources_dir) if sources_dir.is_dir() else []
        mappings, _ = (
            _parse_skos_mappings(mappings_dir) if mappings_dir.is_dir() else ({}, {})
        )

        analysis = build(
            classes=classes,
            graph=graph,
            systems=systems,
            mappings=mappings,
            eligible_class_uris=eligible,
        )
        return DomainBindingSnapshot(
            analysis=analysis,
            classes_by_uri={c["uri"]: c["name"] for c in classes},
        )
    except Exception:  # noqa: BLE001 — callers must never fail on bad/partial input
        return None
