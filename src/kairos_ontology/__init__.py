"""Kairos Ontology Toolkit - Validation and projection tools for OWL/Turtle ontologies."""

__version__ = "1.7.7"

from kairos_ontology.catalog_utils import CatalogResolver, load_graph_with_catalog
from kairos_ontology.validator import run_validation, validate_content
from kairos_ontology.projector import run_projections, project_graph
from kairos_ontology.ontology_ops import (
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
    "CatalogResolver",
    "load_graph_with_catalog",
    "run_validation",
    "validate_content",
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
