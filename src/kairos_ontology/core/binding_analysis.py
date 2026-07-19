# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Canonical binding analysis (B0) for the target-first stub → bind loop.

A single, side-effect-free classifier that decides, per **projected class**,
whether its Silver physical model is:

* ``BOUND``   — one or more bronze source tables map to it (directly or via
  discriminator folding / a contracted virtual source);
* ``FOLDED``  — the class is an S3 discriminator subtype absorbed into its parent
  model (no separate physical model of its own);
* ``STUB``    — the class is an *approved, materialization-eligible* claim that is
  not yet bound to any source (an *aspirational* target); or
* ``SKIPPED`` — an unbound class with no approving claim (today's default: no
  broken placeholders).

The binding facts (``class_to_sources`` + discriminator folding) are computed
once by :func:`medallion_dbt_projector.compute_source_bindings`, so the projector
and every downstream consumer (coverage, release gate, ``status`` scan) share the
*same* notion of "is bound" rather than reimplementing divergent heuristics.

``aspirational`` is **derived, not persisted** (see ``silverfirstdesign.md`` §4a):
a class is aspirational iff it is a materialization-eligible approved claim **and**
:data:`STUB` here — no new field is added to the claim / silver-impact model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rdflib import Graph, RDFS, URIRef

from .projections.shared import KAIROS_EXT

if TYPE_CHECKING:
    from .claim_registry import ClaimRegistry

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
    stubs_enabled: bool,
) -> str:
    """Pure classifier for a single projected class.

    Precedence: a bound class is always :data:`BOUND` (even if it is also a
    discriminator parent); an unbound discriminator subtype is :data:`FOLDED`; an
    unbound materialization-eligible claim is a :data:`STUB` **only** when stub
    emission is enabled; otherwise :data:`SKIPPED`.
    """
    if has_sources:
        return BOUND
    if discriminator_subclass:
        return FOLDED
    if stubs_enabled and is_eligible:
        return STUB
    return SKIPPED


@dataclass
class BindingAnalysis:
    """Per-class binding classification over a domain's projected classes."""

    states: dict[str, str] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    eligible_class_uris: set[str] = field(default_factory=set)

    def state(self, class_uri: str) -> str:
        return self.states.get(class_uri, SKIPPED)

    def is_aspirational(self, class_uri: str) -> bool:
        """True iff the class is an unbound materialization-eligible stub."""
        return self.states.get(class_uri) == STUB

    def class_uris_in_state(self, state: str) -> list[str]:
        return sorted(uri for uri, st in self.states.items() if st == state)


def build(
    *,
    classes: list[dict],
    graph: Graph,
    systems: list[dict],
    mappings: dict,
    contract_registry=None,
    eligible_class_uris: set[str] | None = None,
    stubs_enabled: bool = False,
) -> BindingAnalysis:
    """Compute the canonical :class:`BindingAnalysis` for a domain.

    Uses :func:`medallion_dbt_projector.compute_source_bindings` (imported lazily
    to avoid an import cycle) so the classification is grounded in the exact same
    ``class_to_sources`` the projector materializes from.
    """
    from .projections.medallion_dbt_projector import compute_source_bindings

    eligible = eligible_class_uris or set()
    bindings = compute_source_bindings(
        classes=classes,
        graph=graph,
        systems=systems,
        mappings=mappings,
        contract_registry=contract_registry,
    )

    analysis = BindingAnalysis(eligible_class_uris=set(eligible))
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
            stubs_enabled=stubs_enabled,
        )
        analysis.states[cls_uri] = state
        if state == BOUND:
            analysis.reasons[cls_uri] = "bound to bronze source(s)"
        elif state == FOLDED:
            analysis.reasons[cls_uri] = (
                f"S3 discriminator subclass of {parent_local}"
            )
        elif state == STUB:
            analysis.reasons[cls_uri] = "approved claim, no bronze mapping (aspirational)"
        else:
            analysis.reasons[cls_uri] = "no bronze mapping and no approving claim"
    return analysis
