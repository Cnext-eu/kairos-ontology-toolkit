# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Typed hand-offs for the DD-110 dbt projection pipeline.

``DbtInputs`` is the authoring call boundary and may therefore hold an RDF graph.
Every value returned by a phase is frozen, slotted, deeply immutable, and graph-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping

from .mapping_specs import MappingContractSpec, SourceMappings
from .gold_specs import GoldProductLogicalSpec, GoldProductPhysicalSpec
from .specs import (
    AdapterPlan,
    BindingPolicy,
    BoundCoverage,
    BoundSchemaModel,
    BoundSilverModel,
    ClassBindingObservation,
    ClassFact,
    ContractFact,
    CoverageSpec,
    DqModelPhysicalPlan,
    DocumentPhysicalPlan,
    ForeignKeyPolicy,
    MacroSetSpec,
    ModelPhysicalPlan,
    NormalizedSilverModel,
    NormalizedCoverage,
    NormalizedSchemaModel,
    OntologyMetadataSpec,
    PrepArrayChildModelSpec,
    PrepModelPhysicalPlan,
    PrepModelSpec,
    PrepRouteSpec,
    PrepSchemaPhysicalPlan,
    ProjectConfigPlan,
    ReleasePlan,
    SchemaDocumentSpec,
    SilverModelOutcome,
    SilverPhysicalPlan,
    SilverModelSpec,
    SilverRegistry,
    SourceBindingsFact,
    SourceCatalogSpec,
    SourceSystemFact,
)
from .policy_specs import MedallionPolicyFacts, MedallionPolicySpec

if TYPE_CHECKING:  # pragma: no cover
    from pathlib import Path

    from rdflib import Graph

    from ...dbt_contracts import DbtContractModel
    from ..shared import ForeignKeyAuthoringFact


@dataclass(frozen=True, slots=True)
class DbtInputs:
    """Immutable copy of the public call arguments.

    This is not a phase result: ``graph`` is consumed by :func:`bind_sources` and is
    intentionally absent from every downstream record.
    """

    classes: tuple[ClassFact, ...]
    graph: "Graph"
    template_root: str
    namespace: str
    shapes_root: str | None
    ontology_name: str
    ontology_metadata: OntologyMetadataSpec
    bronze_root: str | None
    sources_root: str | None
    preparation_root: str | None
    mappings_root: str | None
    gold_extension: str | None
    target_platform: str
    silver_extension: str | None
    ref_model_defaults: tuple[str, ...]
    peer_extensions: tuple[str, ...]
    peer_ontologies: tuple[str, ...]
    logical_sources_only: bool
    contracts: tuple[tuple[str, "DbtContractModel"], ...]
    emit_aspirational_stubs: bool
    eligible_class_uris: frozenset[str]

    @classmethod
    def from_call(
        cls,
        *,
        classes: list,
        graph: "Graph",
        template_dir: object,
        namespace: str,
        target_platform: str,
        shapes_dir: "Path | None" = None,
        ontology_name: str | None = None,
        ontology_metadata: dict | None = None,
        bronze_dir: "Path | None" = None,
        sources_dir: "Path | None" = None,
        preparation_dir: "Path | None" = None,
        mappings_dir: "Path | None" = None,
        gold_ext_path: "Path | None" = None,
        silver_ext_path: "Path | None" = None,
        ref_model_defaults: list | None = None,
        peer_ext_paths: list | None = None,
        peer_ontology_paths: list | None = None,
        logical_sources_only: bool = False,
        contract_registry: "Mapping[str, DbtContractModel] | None" = None,
        emit_aspirational_stubs: bool = False,
        eligible_class_uris: set | None = None,
    ) -> "DbtInputs":
        """Copy mutable call arguments into stable authoring inputs."""
        from pathlib import Path

        from .builders import build_metadata

        class_facts = tuple(
            ClassFact(
                uri=str(item.get("uri") or ""),
                name=str(item.get("name") or ""),
                label=str(item.get("label") or item.get("name") or ""),
                comment=str(item.get("comment") or ""),
            )
            for item in classes
        )
        source_location = sources_dir or bronze_dir
        return cls(
            classes=class_facts,
            graph=graph,
            template_root=str(template_dir),
            namespace=namespace,
            shapes_root=str(shapes_dir) if shapes_dir is not None else None,
            ontology_name=ontology_name or "domain",
            ontology_metadata=build_metadata(ontology_metadata),
            bronze_root=str(bronze_dir) if bronze_dir is not None else None,
            sources_root=str(sources_dir) if sources_dir is not None else None,
            preparation_root=(
                str(preparation_dir)
                if preparation_dir is not None
                else str(Path(source_location).parent / "preparation")
                if source_location is not None
                else None
            ),
            mappings_root=str(mappings_dir) if mappings_dir is not None else None,
            gold_extension=str(gold_ext_path) if gold_ext_path is not None else None,
            target_platform=target_platform,
            silver_extension=(
                str(silver_ext_path) if silver_ext_path is not None else None
            ),
            ref_model_defaults=tuple(str(path) for path in (ref_model_defaults or ())),
            peer_extensions=tuple(str(path) for path in (peer_ext_paths or ())),
            peer_ontologies=tuple(
                str(path) for path in (peer_ontology_paths or ())
            ),
            logical_sources_only=logical_sources_only,
            contracts=tuple(sorted((contract_registry or {}).items())),
            emit_aspirational_stubs=emit_aspirational_stubs,
            eligible_class_uris=frozenset(eligible_class_uris or ()),
        )


@dataclass(frozen=True, slots=True)
class ActiveSourceTable:
    """One source table selected for the current ontology projection."""

    table_uri: str
    source_kind: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ActiveSourceScope:
    """The explainable source-table authority shared by every dbt stage."""

    tables: tuple[ActiveSourceTable, ...] = ()

    @property
    def table_uris(self) -> frozenset[str]:
        return frozenset(item.table_uri for item in self.tables)

    def to_dict(self) -> dict[str, object]:
        return {
            "tables": [
                {
                    "table_uri": item.table_uri,
                    "source_kind": item.source_kind,
                    "reasons": list(item.reasons),
                }
                for item in self.tables
            ]
        }


@dataclass(frozen=True, slots=True)
class BoundSources:
    """Graph-free result of bind: immutable authored and extracted facts only."""

    classes: tuple[ClassFact, ...]
    namespace: str
    ontology_name: str
    ontology_metadata: OntologyMetadataSpec
    target_platform: str
    template_root: str
    logical_sources_only: bool
    emit_aspirational_stubs: bool
    systems: tuple[SourceSystemFact, ...]
    mappings: SourceMappings
    contracts: tuple[tuple[str, ContractFact], ...]
    virtual_table_uris: frozenset[str]
    replacement_input_uris: frozenset[str]
    source_bindings: SourceBindingsFact
    binding_observations: tuple[ClassBindingObservation, ...]
    foreign_key_facts: tuple["ForeignKeyAuthoringFact", ...]
    ontology_uri: str
    parent_relations: tuple[tuple[str, str], ...]
    silver_candidates: tuple[BoundSilverModel, ...]
    silver_outcomes: tuple[SilverModelOutcome, ...]
    schema_candidates: tuple[BoundSchemaModel, ...]
    coverage: BoundCoverage | None
    macro_names: tuple[str, ...]
    warnings: tuple[str, ...]
    policy_facts: MedallionPolicyFacts
    active_source_scope: ActiveSourceScope = ActiveSourceScope()

    @property
    def has_sources(self) -> bool:
        return bool(self.systems)


@dataclass(frozen=True, slots=True)
class NormalizedProjectFacts:
    """Graph-free project facts forwarded by normalize to logical shaping."""

    classes: tuple[ClassFact, ...]
    ontology_name: str
    ontology_metadata: OntologyMetadataSpec
    template_root: str
    logical_sources_only: bool
    has_sources: bool
    systems: tuple[SourceSystemFact, ...]
    mappings: MappingContractSpec
    contracts: tuple[str, ...]
    virtual_table_uris: frozenset[str]
    replacement_input_uris: frozenset[str]
    parent_relations: tuple[tuple[str, str], ...]
    silver_models: tuple[NormalizedSilverModel, ...]
    silver_outcomes: tuple[SilverModelOutcome, ...]
    schema_models: tuple[NormalizedSchemaModel, ...]
    coverage: NormalizedCoverage | None
    macro_names: tuple[str, ...]
    warnings: tuple[str, ...]
    policy: MedallionPolicySpec
    active_source_scope: ActiveSourceScope = ActiveSourceScope()

    @property
    def target_platform(self) -> str:
        """Return the adapter selected by the normalized policy authority."""
        return self.policy.target_adapter.value.value


@dataclass(frozen=True, slots=True)
class ProjectionContract:
    """Result of normalize: effective policy and normalized project facts."""

    fk_classification: ForeignKeyPolicy
    binding_policy: BindingPolicy
    ontology_uri: str
    policy: MedallionPolicySpec
    mapping_contract: MappingContractSpec
    project: NormalizedProjectFacts

    @property
    def naming_convention(self) -> str:
        """Return the sole effective naming authority."""
        return self.policy.naming_convention.value.value

@dataclass(frozen=True, slots=True)
class ShapedProject:
    """Result of shape: ordered logical specifications and no artifact content."""

    source_catalogs: tuple[SourceCatalogSpec, ...]
    prep_models: tuple[PrepModelSpec, ...]
    prep_children: tuple[PrepArrayChildModelSpec, ...]
    prep_routes: tuple[PrepRouteSpec, ...]
    silver_models: tuple[SilverModelSpec, ...]
    silver_outcomes: tuple[SilverModelOutcome, ...]
    schema_documents: tuple[SchemaDocumentSpec, ...]
    gold_product: GoldProductLogicalSpec | None
    silver_registry: SilverRegistry
    coverage: CoverageSpec | None
    macros: MacroSetSpec
    warnings: tuple[str, ...]
    policy: MedallionPolicySpec

    @property
    def has_gold(self) -> bool:
        return self.gold_product is not None


@dataclass(frozen=True, slots=True)
class MaterializationPlan:
    """Result of materialize: adapter, physical model, dependency, and release plans."""

    adapter: AdapterPlan
    prep_models: tuple[PrepModelPhysicalPlan, ...]
    prep_documents: tuple[PrepSchemaPhysicalPlan, ...]
    models: tuple[ModelPhysicalPlan, ...]
    quality_models: tuple[DqModelPhysicalPlan, ...]
    documents: tuple[DocumentPhysicalPlan, ...]
    project: ProjectConfigPlan
    release: ReleasePlan
    silver: SilverPhysicalPlan | None = None
    gold: GoldProductPhysicalSpec | None = None
    policy: MedallionPolicySpec | None = None
