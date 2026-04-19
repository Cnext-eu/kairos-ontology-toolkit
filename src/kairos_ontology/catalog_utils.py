"""
XML Catalog utilities for resolving FIBO ontology imports.

Provides functions to:
- Parse XML catalog files
- Resolve URIs to local file paths
- Load imported ontologies from local files
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional

from rdflib import Graph


def _get_rdf_format(file_path: Path) -> str:
    """
    Detect RDF format from file extension.
    
    Args:
        file_path: Path to the RDF file
        
    Returns:
        Format string for rdflib.Graph.parse()
    """
    suffix = file_path.suffix.lower()
    format_map = {
        '.ttl': 'turtle',
        '.turtle': 'turtle',
        '.rdf': 'xml',
        '.xml': 'xml',
        '.owl': 'xml',
        '.n3': 'n3',
        '.nt': 'nt',
        '.ntriples': 'nt',
        '.jsonld': 'json-ld',
        '.json': 'json-ld',
    }
    return format_map.get(suffix, 'turtle')  # Default to turtle


class CatalogResolver:
    """Resolves ontology URIs to local files using XML catalog."""
    
    CATALOG_NS = "{urn:oasis:names:tc:entity:xmlns:xml:catalog}"
    
    def __init__(self, catalog_path: Path):
        """
        Initialize resolver with catalog file.
        
        Args:
            catalog_path: Path to catalog-v001.xml file
        """
        self.catalog_path = catalog_path
        self.mappings: Dict[str, Path] = {}
        self._load_catalog()
    
    def _load_catalog(self):
        """Parse XML catalog and build URI → local path mappings."""
        if not self.catalog_path.exists():
            raise FileNotFoundError(f"Catalog not found: {self.catalog_path}")
        
        tree = ET.parse(self.catalog_path)
        root = tree.getroot()
        
        # Parse all <uri> elements
        for uri_elem in root.findall(f"{self.CATALOG_NS}uri"):
            uri_name = uri_elem.get("name")
            uri_path = uri_elem.get("uri")
            
            if uri_name and uri_path:
                # Resolve relative path from catalog directory
                catalog_dir = self.catalog_path.parent
                local_path = (catalog_dir / uri_path).resolve()
                
                # Normalize URI (ensure trailing slash consistency)
                normalized_uri = uri_name.rstrip('/') + '/'
                self.mappings[normalized_uri] = local_path
                
                # Also add without trailing slash for flexibility
                self.mappings[normalized_uri.rstrip('/')] = local_path
    
    def resolve(self, uri: str) -> Optional[Path]:
        """
        Resolve an ontology URI to a local file path.
        
        Args:
            uri: Ontology URI (e.g., https://spec.edmcouncil.org/fibo/...)
            
        Returns:
            Local file path if mapping exists, None otherwise
        """
        # Try exact match first
        if uri in self.mappings:
            return self.mappings[uri]
        
        # Try with/without trailing slash
        uri_with_slash = uri.rstrip('/') + '/'
        if uri_with_slash in self.mappings:
            return self.mappings[uri_with_slash]
        
        uri_without_slash = uri.rstrip('/')
        if uri_without_slash in self.mappings:
            return self.mappings[uri_without_slash]
        
        return None
    
    def is_mapped(self, uri: str) -> bool:
        """Check if URI has a catalog mapping."""
        return self.resolve(uri) is not None
    
    def get_all_mappings(self) -> Dict[str, Path]:
        """Get all URI → path mappings."""
        return self.mappings.copy()


def load_graph_with_catalog(ontology_path: Path, catalog_path: Path) -> Graph:
    """
    Load an RDF graph and resolve owl:imports using XML catalog.
    
    Args:
        ontology_path: Path to main ontology file
        catalog_path: Path to catalog-v001.xml
        
    Returns:
        RDF graph with all imports loaded
    """
    from rdflib import OWL
    
    # Initialize resolver
    resolver = CatalogResolver(catalog_path)
    
    # Load main graph
    graph = Graph()
    graph.parse(ontology_path, format=_get_rdf_format(ontology_path))
    
    # Find all owl:imports statements
    imports = list(graph.objects(predicate=OWL.imports))
    
    loaded_count = 0
    for import_uri in imports:
        import_str = str(import_uri)
        
        # Check if it's a file:// URI (old pattern - skip)
        if import_str.startswith('file://'):
            print(f"⚠️  Skipping file:// import (use catalog instead): {import_str}")
            continue
        
        # Resolve via catalog
        local_path = resolver.resolve(import_str)
        
        if local_path and local_path.exists():
            try:
                # Detect format from file extension
                graph.parse(local_path, format=_get_rdf_format(local_path))
                loaded_count += 1
                print(f"✓ Loaded import: {import_str}")
                print(f"  → {local_path}")
            except Exception as e:
                print(f"✗ Error loading {local_path}: {e}")
        else:
            print(f"⚠️  No catalog mapping for: {import_str}")
    
    print(f"\n📦 Loaded {loaded_count}/{len(imports)} imports via catalog")
    
    return graph


def validate_catalog(catalog_path: Path) -> Dict[str, bool]:
    """
    Validate that all catalog mappings point to existing files.
    
    Args:
        catalog_path: Path to catalog file
        
    Returns:
        Dict mapping URI → file_exists (bool)
    """
    resolver = CatalogResolver(catalog_path)
    results = {}
    
    for uri, path in resolver.get_all_mappings().items():
        results[uri] = path.exists()
    
    return results
