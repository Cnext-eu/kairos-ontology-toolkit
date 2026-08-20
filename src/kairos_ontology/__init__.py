# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Kairos Ontology Toolkit - Validation and projection tools for OWL/Turtle ontologies."""

__version__ = "5.13.0rc20"

from kairos_ontology.core.catalog_utils import (
    CatalogLoadResult,
    CatalogResolver,
    load_graph_with_catalog,
    resolve_import_paths,
)
from kairos_ontology.core.ontology_loader import (
    ImportManifestEntry,
    ImportRequirement,
    OntologyDiagnostic,
    OntologyLoadError,
    OntologyLoadResult,
    SemanticProfile,
    load_ontology,
)
from kairos_ontology.core.semantic_index import (
    SEMANTIC_INDEX_VERSION,
    SemanticIndex,
    build_semantic_index,
)
from kairos_ontology.core.reference_modules import (
    AcceleratorModuleConfig,
    ManagedImportPlan,
    ReferenceModuleContext,
    ReferenceModuleProfile,
    build_activation_inventory,
    build_managed_import_plan,
    build_reference_module_context,
    load_accelerator_module_config,
)
from kairos_ontology.core.validator import run_validation, validate_content, validate_gdpr
from kairos_ontology.core.projector import run_projections, project_graph
from kairos_ontology.core.compiler import (
    build_compile_plan,
    compile_domain,
    compile_plan_result,
    render_compile_plan,
)
from kairos_ontology.core.ontology_ops import (
    list_classes,
    list_properties,
    list_relationships,
    add_class,
    add_property,
    modify_class,
    remove_class,
    serialize_graph,
    parse_ontology,
    parse_ontology_content,
)
from kairos_ontology.core.next_actions import (
    NextAction,
    NextActionProposal,
    HubInputSnapshot,
    DomainSnapshot,
    propose_next_actions,
)
from kairos_ontology.core.hub_inspection import gather_hub_input_snapshot

__all__ = [
    "__version__",
    "CatalogLoadResult",
    "CatalogResolver",
    "load_graph_with_catalog",
    "resolve_import_paths",
    "ImportManifestEntry",
    "ImportRequirement",
    "OntologyDiagnostic",
    "OntologyLoadError",
    "OntologyLoadResult",
    "SemanticProfile",
    "load_ontology",
    "SEMANTIC_INDEX_VERSION",
    "SemanticIndex",
    "build_semantic_index",
    "AcceleratorModuleConfig",
    "ManagedImportPlan",
    "ReferenceModuleContext",
    "ReferenceModuleProfile",
    "build_activation_inventory",
    "build_managed_import_plan",
    "build_reference_module_context",
    "load_accelerator_module_config",
    "run_validation",
    "validate_content",
    "validate_gdpr",
    "run_projections",
    "project_graph",
    "build_compile_plan",
    "compile_domain",
    "compile_plan_result",
    "render_compile_plan",
    "list_classes",
    "list_properties",
    "list_relationships",
    "add_class",
    "add_property",
    "modify_class",
    "remove_class",
    "serialize_graph",
    "parse_ontology",
    "parse_ontology_content",
    "NextAction",
    "NextActionProposal",
    "HubInputSnapshot",
    "DomainSnapshot",
    "propose_next_actions",
    "gather_hub_input_snapshot",
]
