# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""dbt projection **normalize** phase (DD-102).

Derives the graph/extension/claim projection *contract* from the committed
:class:`BoundSources`:

* the canonical FK descriptors (:func:`classify_foreign_keys`), and
* the canonical :class:`BindingAnalysis` (grounded in the bind phase's
  :class:`SourceBindings` so binding is never re-derived), plus
* the domain naming convention + ontology URI used to shape Silver names.

This phase owns projection *policy*: the shape phase reads these committed
descriptors instead of re-querying the graph for FK/binding classification.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .context import ProjectionContract

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .context import BoundSources, DbtInputs


def normalize_contract(
    inputs: "DbtInputs", bound: "BoundSources"
) -> ProjectionContract:
    """Run the normalize phase — derive the projection contract from *bound*."""
    from ... import binding_analysis as _ba
    from ..shared import (
        classify_foreign_keys,
        detect_ontology_uri,
        silver_naming_convention,
    )

    graph = bound.graph
    fk_classification = classify_foreign_keys(graph)
    ontology_uri = detect_ontology_uri(graph, inputs.namespace)
    naming_conv = silver_naming_convention(graph, ontology_uri)

    # Canonical binding analysis (DD-096): grounded in the committed SourceBindings
    # so stub emission and the release gate consume the *same* bound/folded/stub/
    # skipped classification as status and the strict gate.
    binding_analysis = _ba.build(
        classes=inputs.classes,
        graph=graph,
        systems=bound.systems,
        mappings=bound.mappings,
        contract_registry=bound.contracts,
        eligible_class_uris=inputs.eligible_class_uris,
        stubs_enabled=inputs.emit_aspirational_stubs,
        bindings=bound.source_bindings,
    )

    return ProjectionContract(
        fk_classification=fk_classification,
        binding_analysis=binding_analysis,
        naming_conv=naming_conv,
        ontology_uri=ontology_uri,
    )
