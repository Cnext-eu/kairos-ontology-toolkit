# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""
XML Catalog utilities for resolving FIBO ontology imports.

Provides functions to:
- Parse XML catalog files
- Resolve URIs to local file paths
- Load imported ontologies from local files
"""

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rdflib import Graph

_logger = logging.getLogger(__name__)


@dataclass
class CatalogLoadResult:
    """Result of loading an ontology graph with catalog-based import resolution.

    Attributes:
        graph: The loaded RDF graph (including resolved imports).
        diagnostics: Structured messages collected during loading.
            Each entry is a dict with keys: level ("warning"|"error"|"info"), message (str).
    """

    graph: Graph = field(default_factory=Graph)
    diagnostics: List[Dict[str, str]] = field(default_factory=list)

    def warnings(self) -> List[str]:
        """Return only warning-level diagnostic messages."""
        return [d["message"] for d in self.diagnostics if d["level"] == "warning"]


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
        self._rewrite_rules: List[Tuple[str, str, Path]] = []
        self._hash_fallback_used: bool = False
        self._rewrite_fallback_used: bool = False
        self._load_catalog()
    
    def _load_catalog(self):
        """Parse XML catalog and build URI → local path mappings."""
        self._load_catalog_file(self.catalog_path)
        # Sort rewrite rules by descending prefix length (longest-prefix-wins)
        self._rewrite_rules.sort(key=lambda r: len(r[0]), reverse=True)

    def _load_catalog_file(self, path: Path):
        """Parse a single catalog file, following <nextCatalog> references."""
        if not path.exists():
            raise FileNotFoundError(f"Catalog not found: {path}")

        tree = ET.parse(path)
        root = tree.getroot()
        catalog_dir = path.parent

        # Parse all <uri> elements
        for uri_elem in root.findall(f"{self.CATALOG_NS}uri"):
            uri_name = uri_elem.get("name")
            uri_path = uri_elem.get("uri")

            if uri_name and uri_path:
                local_path = (catalog_dir / uri_path).resolve()

                # Store exact mapping
                self.mappings[uri_name] = local_path

                # Normalize URI (ensure trailing slash consistency)
                normalized_uri = uri_name.rstrip('/#') + '/'
                self.mappings[normalized_uri] = local_path

                # Also add without trailing slash for flexibility
                self.mappings[normalized_uri.rstrip('/')] = local_path

                # Hash normalization: store both with and without trailing #
                bare = uri_name.rstrip('#')
                self.mappings[bare] = local_path
                self.mappings[bare + '#'] = local_path

        # Follow <nextCatalog> references
        for next_elem in root.findall(f"{self.CATALOG_NS}nextCatalog"):
            next_catalog = next_elem.get("catalog")
            if next_catalog:
                next_path = (catalog_dir / next_catalog).resolve()
                if next_path.exists():
                    self._load_catalog_file(next_path)

        # Parse <rewriteURI> elements
        for rewrite_elem in root.findall(f"{self.CATALOG_NS}rewriteURI"):
            start_string = rewrite_elem.get("uriStartString")
            rewrite_prefix = rewrite_elem.get("rewritePrefix")
            if start_string and rewrite_prefix:
                self._rewrite_rules.append((start_string, rewrite_prefix, catalog_dir))
    
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

        # Try with/without trailing hash
        uri_with_hash = uri.rstrip('#') + '#'
        if uri_with_hash in self.mappings:
            self._hash_fallback_used = True
            return self.mappings[uri_with_hash]

        uri_without_hash = uri.rstrip('#')
        if uri_without_hash in self.mappings:
            self._hash_fallback_used = True
            return self.mappings[uri_without_hash]

        # Try rewriteURI rules (longest-prefix-wins, already sorted)
        resolved = self._resolve_via_rewrite(uri)
        if resolved:
            return resolved

        return None

    # Extension probe order for rewriteURI fallback
    _EXTENSION_FALLBACK = [".rdf", ".ttl", ".owl"]

    def _resolve_via_rewrite(self, uri: str) -> Optional[Path]:
        """Apply rewriteURI rules with extension fallback.

        Returns the resolved file path, or None if no rule matches or no file exists.
        """
        for start_string, rewrite_prefix, catalog_dir in self._rewrite_rules:
            if not uri.startswith(start_string):
                continue

            # Apply prefix replacement
            suffix = uri[len(start_string):]
            candidate = (catalog_dir / rewrite_prefix / suffix).resolve()

            # Direct match — rewritten path is an existing file
            if candidate.is_file():
                self._rewrite_fallback_used = False
                return candidate

            # Extension fallback: strip trailing slash/separator, try extensions
            base = str(candidate).rstrip("/\\")
            found: List[Path] = []
            for ext in self._EXTENSION_FALLBACK:
                probe = Path(base + ext)
                if probe.is_file():
                    found.append(probe)

            if found:
                self._rewrite_fallback_used = True
                if len(found) > 1:
                    _logger.warning(
                        "Ambiguous rewriteURI resolution for <%s>: multiple files exist "
                        "(%s). Using first in priority order: %s",
                        uri,
                        ", ".join(p.name for p in found),
                        found[0].name,
                    )
                return found[0]

        return None
    
    def is_mapped(self, uri: str) -> bool:
        """Check if URI has a catalog mapping."""
        return self.resolve(uri) is not None
    
    def get_all_mappings(self) -> Dict[str, Path]:
        """Get all URI → path mappings."""
        return self.mappings.copy()


def load_graph_with_catalog(
    ontology_path: Path,
    catalog_path: Path,
    *,
    quiet: bool = False,
) -> CatalogLoadResult:
    """
    Load an RDF graph and resolve owl:imports using XML catalog.
    
    Args:
        ontology_path: Path to main ontology file
        catalog_path: Path to catalog-v001.xml
        quiet: Suppress human-readable import progress while retaining diagnostics.
        
    Returns:
        CatalogLoadResult with the loaded graph and any diagnostics collected
        during import resolution.
    """
    from rdflib import OWL
    
    # Initialize resolver
    resolver = CatalogResolver(catalog_path)
    result = CatalogLoadResult()
    
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
            msg = f"Skipping file:// import (use catalog instead): {import_str}"
            result.diagnostics.append({"level": "warning", "message": msg})
            if not quiet:
                print(f"⚠️  {msg}")
            continue
        
        # Resolve via catalog
        hash_before = resolver._hash_fallback_used
        resolver._rewrite_fallback_used = False
        local_path = resolver.resolve(import_str)
        if resolver._hash_fallback_used and not hash_before:
            msg = (
                f"Hash mismatch: owl:imports <{import_str}> resolved via '#' fallback. "
                "Align the catalog name and owl:imports URI to avoid ambiguity."
            )
            _logger.warning(msg)
            result.diagnostics.append({"level": "warning", "message": msg})
            if not quiet:
                print(
                    f"  ⚠️  Hash mismatch for import: {import_str} "
                    f"(resolved via '#' fallback — consider aligning catalog/imports)"
                )
        if resolver._rewrite_fallback_used:
            msg = (
                f"Resolved via rewriteURI extension fallback: "
                f"<{import_str}> → {local_path}"
            )
            _logger.info(msg)
            result.diagnostics.append({"level": "info", "message": msg})
            if not quiet:
                print(f"  ℹ️  {msg}")
        
        if local_path and local_path.exists():
            try:
                # Detect format from file extension
                graph.parse(local_path, format=_get_rdf_format(local_path))
                loaded_count += 1
                if not quiet:
                    print(f"✓ Loaded import: {import_str}")
                    print(f"  → {local_path}")
            except Exception as e:
                msg = f"Error loading {local_path}: {e}"
                result.diagnostics.append({"level": "error", "message": msg})
                if not quiet:
                    print(f"✗ {msg}")
        else:
            msg = f"No catalog mapping for: {import_str}"
            result.diagnostics.append({"level": "warning", "message": msg})
            if not quiet:
                print(f"⚠️  {msg}")
    
    if not quiet:
        print(f"\n📦 Loaded {loaded_count}/{len(imports)} imports via catalog")
    
    result.graph = graph
    return result


def resolve_import_paths(
    ontology_path: Path, catalog_path: Path
) -> Dict[str, Path]:
    """Resolve owl:imports URIs to local file paths without loading triples.

    This is useful for discovering sibling files (e.g., extension defaults)
    alongside resolved imports without the cost of parsing them into a graph.

    Args:
        ontology_path: Path to main ontology file
        catalog_path: Path to catalog-v001.xml

    Returns:
        Dict mapping import URI string → resolved local Path (only for
        imports that have a catalog mapping and whose file exists).
    """
    from rdflib import OWL

    resolver = CatalogResolver(catalog_path)

    graph = Graph()
    graph.parse(ontology_path, format=_get_rdf_format(ontology_path))

    imports = list(graph.objects(predicate=OWL.imports))
    resolved: Dict[str, Path] = {}

    for import_uri in imports:
        import_str = str(import_uri)
        if import_str.startswith("file://"):
            continue
        local_path = resolver.resolve(import_str)
        if local_path and local_path.exists():
            resolved[import_str] = local_path

    return resolved


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
