# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Typed, immutable intermediate models for the dbt projection pipeline (DD-102).

The dbt projector is an **orchestrator** over five explicit, deterministic phases:

``bind → normalize → shape → materialize → render``

Each phase consumes and produces one of the frozen dataclasses defined here, so a
downstream phase can only ever read *committed* facts from an upstream phase — never
re-derive policy from the RDF graph or the SKOS mappings.  In particular the
``render`` phase is handed only :class:`ShapedProject` + :class:`MaterializationPlan`
(pure strings / metadata), which structurally guarantees it cannot reread RDF or
reclassify projection policy.

The dataclasses are ``frozen=True`` — attribute rebinding raises
``FrozenInstanceError``.  Referenced RDF graphs and mapping dicts remain the shared
working objects (deep-freezing rdflib graphs is neither practical nor free); the
freeze is at the container boundary, which is what makes the phase hand-offs
auditable.

Only container-shaped fields live here; the heavy leaf helpers that actually shape
columns / FKs / SCD config still live in
:mod:`kairos_ontology.core.projections.medallion_dbt_projector` and are invoked by
the phase modules (documented retained internal code — see DD-102).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids import cycles
    from pathlib import Path

    from jinja2 import Environment
    from rdflib import Graph, URIRef

    from ...binding_analysis import BindingAnalysis
    from ...dbt_contracts import DbtContractModel
    from ..shared import ForeignKeyClassification
    from ..medallion_dbt_projector import SourceBindings


@dataclass(frozen=True)
class DbtInputs:
    """Committed inputs to the dbt projection pipeline.

    Mirrors the public ``generate_dbt_artifacts`` signature plus the three derived
    values (``env`` / ``meta`` / ``onto_name``) every phase needs.  Constructed once
    via :meth:`from_call` so the derivation is centralised and deterministic.
    """

    classes: list
    graph: "Graph"
    template_dir: Any
    namespace: str
    shapes_dir: "Optional[Path]"
    ontology_name: Optional[str]
    ontology_metadata: Optional[dict]
    bronze_dir: "Optional[Path]"
    sources_dir: "Optional[Path]"
    mappings_dir: "Optional[Path]"
    gold_ext_path: "Optional[Path]"
    target_platform: str
    silver_ext_path: "Optional[Path]"
    ref_model_defaults: Optional[list]
    peer_ext_paths: Optional[list]
    logical_sources_only: bool
    contract_registry: "Optional[Mapping[str, DbtContractModel]]"
    emit_aspirational_stubs: bool
    eligible_class_uris: Optional[set]
    env: "Environment"
    meta: dict
    onto_name: str

    @classmethod
    def from_call(
        cls,
        *,
        classes: list,
        graph: "Graph",
        template_dir: Any,
        namespace: str,
        target_platform: str,
        shapes_dir: "Optional[Path]" = None,
        ontology_name: Optional[str] = None,
        ontology_metadata: Optional[dict] = None,
        bronze_dir: "Optional[Path]" = None,
        sources_dir: "Optional[Path]" = None,
        mappings_dir: "Optional[Path]" = None,
        gold_ext_path: "Optional[Path]" = None,
        silver_ext_path: "Optional[Path]" = None,
        ref_model_defaults: Optional[list] = None,
        peer_ext_paths: Optional[list] = None,
        logical_sources_only: bool = False,
        contract_registry: "Optional[Mapping[str, DbtContractModel]]" = None,
        emit_aspirational_stubs: bool = False,
        eligible_class_uris: Optional[set] = None,
    ) -> "DbtInputs":
        """Build the committed inputs, deriving ``env`` / ``meta`` / ``onto_name``."""
        from jinja2 import Environment, FileSystemLoader

        return cls(
            classes=classes,
            graph=graph,
            template_dir=template_dir,
            namespace=namespace,
            shapes_dir=shapes_dir,
            ontology_name=ontology_name,
            ontology_metadata=ontology_metadata,
            bronze_dir=bronze_dir,
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            gold_ext_path=gold_ext_path,
            target_platform=target_platform,
            silver_ext_path=silver_ext_path,
            ref_model_defaults=ref_model_defaults,
            peer_ext_paths=peer_ext_paths,
            logical_sources_only=logical_sources_only,
            contract_registry=contract_registry,
            emit_aspirational_stubs=emit_aspirational_stubs,
            eligible_class_uris=eligible_class_uris,
            env=Environment(loader=FileSystemLoader(str(template_dir))),
            meta=ontology_metadata or {},
            onto_name=ontology_name or "domain",
        )


@dataclass(frozen=True)
class BoundSources:
    """Result of the **bind** phase — committed source-side facts.

    Owns the ext-merged working ``graph`` (committed here because source binding
    requires the silver-extension triples), the parsed source ``systems`` + SKOS
    ``mappings``, the active contract registry with its contracted virtual-source
    resolution (``virtual_table_uris`` / ``replacement_input_uris``), and the
    canonical :class:`SourceBindings` (``class_to_sources`` + discriminator folding).
    """

    graph: "Graph"
    systems: list
    mappings: dict
    mapping_ns: dict
    contracts: "Mapping[str, DbtContractModel]"
    virtual_table_uris: frozenset
    replacement_input_uris: frozenset
    source_bindings: "SourceBindings"

    @property
    def has_sources(self) -> bool:
        """Whether any bronze source systems were discovered."""
        return bool(self.systems)


@dataclass(frozen=True)
class ProjectionContract:
    """Result of the **normalize** phase — the graph/claim-derived projection policy.

    Consumes the canonical FK descriptors (:class:`ForeignKeyClassification`) and the
    canonical :class:`BindingAnalysis` (grounded in the bind phase's
    :class:`SourceBindings`) rather than recomputing binding/FK policy.  Downstream
    phases read these committed facts instead of re-querying the graph for policy.
    """

    fk_classification: "ForeignKeyClassification"
    binding_analysis: "BindingAnalysis"
    naming_conv: str
    ontology_uri: "URIRef"


@dataclass(frozen=True)
class ShapedProject:
    """Result of the **shape** phase — every model's shaped data + rendered bytes.

    Because SQL/template rendering is interleaved with column/FK/test shaping inside
    the retained model-generation helpers (not redesigned per scope — DD-102), the
    shape phase materialises both the shaped model metadata (``silver_entity_meta``,
    registries, class-name sets) and the rendered artifact bytes.  The
    ``render`` phase then assembles and validates these strings without any RDF
    access.
    """

    source_artifacts: dict
    silver_artifacts: dict
    silver_warnings: list
    silver_entity_meta: list
    schema_artifacts: dict
    gold_artifacts: dict
    gold_schema_artifacts: dict
    silver_name_registry: dict
    silver_columns_registry: dict
    coverage_data: dict
    macros: dict
    generated_class_names: Optional[frozenset]
    aspirational_class_names: frozenset
    has_gold: bool


@dataclass(frozen=True)
class MaterializationPlan:
    """Result of the **materialize** phase — release metadata + project config.

    Owns the release-gate facts (``unbound_eligible_names`` → the
    ``__unbound_eligible__`` sentinel) and the per-project dbt configuration
    (``project_config``).  Per-model view/table/incremental/SCD selection remains
    inside the retained silver helper (documented retained internal code — DD-102);
    this plan captures the orchestration-level materialization/release decisions.
    """

    unbound_eligible_names: tuple
    project_config: dict
    known_models: frozenset
