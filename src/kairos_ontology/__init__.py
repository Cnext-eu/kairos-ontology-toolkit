# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Kairos Ontology Toolkit - Validation and projection tools for OWL/Turtle ontologies."""

__version__ = "4.7.0rc1"

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
from kairos_ontology.core.validator import run_validation, validate_content, validate_gdpr
from kairos_ontology.core.projector import run_projections, project_graph
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
    "run_validation",
    "validate_content",
    "validate_gdpr",
    "run_projections",
    "project_graph",
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
]
