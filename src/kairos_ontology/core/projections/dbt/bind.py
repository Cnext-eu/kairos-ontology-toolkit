# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""dbt projection **bind** phase (DD-102).

Commits every source-side fact the rest of the pipeline consumes:

* the ext-merged working graph (silver-extension / ref-model-default / peer triples
  are merged here because source binding needs them);
* the parsed bronze ``systems`` and SKOS ``mappings`` (+ namespace bindings);
* the active contract registry and its contracted virtual-source resolution
  (``virtual_table_uris`` / ``replacement_input_uris``); and
* the canonical :class:`SourceBindings` (``class_to_sources`` + discriminator
  folding), so the normalize/shape phases never re-derive "is bound".

The heavy leaf helpers (``_parse_bronze``, ``_parse_skos_mappings``,
``compute_source_bindings`` …) remain in
:mod:`kairos_ontology.core.projections.medallion_dbt_projector` and are invoked here
via a lazy import (documented retained internal code — DD-102).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .context import BoundSources

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .context import DbtInputs


def bind_sources(inputs: "DbtInputs") -> BoundSources:
    """Run the bind phase — resolve committed source bindings from *inputs*."""
    from ..medallion_dbt_projector import (
        _parse_bronze,
        _parse_skos_mappings,
        _validate_contract_boundaries,
        compute_source_bindings,
    )
    from ..shared import merge_ext_graph

    # Merge silver-ext (+ ref-model defaults, peer extensions) into a working copy
    # of the graph so naturalKey / FK / discriminator annotations are visible to
    # binding. DD-023: ref-model defaults are a fallback layer; cross-domain NK
    # resolution needs the peer extension files.
    graph = merge_ext_graph(
        inputs.graph,
        inputs.silver_ext_path,
        fallback_paths=inputs.ref_model_defaults,
        peer_ext_paths=inputs.peer_ext_paths,
    )

    # Parse source vocabulary — prefer sources_dir, fall back to bronze_dir.
    systems = _parse_bronze(inputs.sources_dir or inputs.bronze_dir)
    mappings, mapping_ns = _parse_skos_mappings(inputs.mappings_dir)

    contracts = inputs.contract_registry or {}
    _validate_contract_boundaries(
        contracts,
        inputs.classes,
        graph,
        systems,
        mappings,
        inputs.target_platform,
    )
    virtual_table_uris = frozenset(
        contract.virtual_source_iri for contract in contracts.values()
    )
    class_uris = {item["uri"] for item in inputs.classes}
    replacement_input_uris = frozenset(
        replacement.table_iri
        for contract in contracts.values()
        if contract.target_class in class_uris
        for replacement in contract.replaces_sources
    )

    source_bindings = compute_source_bindings(
        classes=inputs.classes,
        graph=graph,
        systems=systems,
        mappings=mappings,
        contract_registry=contracts,
    )

    return BoundSources(
        graph=graph,
        systems=systems,
        mappings=mappings,
        mapping_ns=mapping_ns,
        contracts=contracts,
        virtual_table_uris=virtual_table_uris,
        replacement_input_uris=replacement_input_uris,
        source_bindings=source_bindings,
    )
