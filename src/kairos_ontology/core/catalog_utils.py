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

from rdflib import Graph, OWL

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


@dataclass(frozen=True)
class CatalogResolution:
    """One catalog lookup, including the resolution strategy and ambiguity."""

    uri: str
    path: Optional[Path]
    method: str
    candidates: Tuple[Path, ...] = ()

    @property
    def ambiguous(self) -> bool:
        """Return whether more than one local source matched the URI."""
        return len(self.candidates) > 1


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
        self._visited_catalogs: set[Path] = set()
        self.diagnostics: List[Dict[str, str]] = []
        self._load_catalog()
    
    def _load_catalog(self):
        """Parse XML catalog and build URI → local path mappings."""
        self._load_catalog_file(self.catalog_path)
        # Sort rewrite rules by descending prefix length (longest-prefix-wins)
        self._rewrite_rules.sort(key=lambda r: len(r[0]), reverse=True)

    def _load_catalog_file(self, path: Path):
        """Parse a single catalog file, following <nextCatalog> references."""
        path = path.resolve()
        if path in self._visited_catalogs:
            self.diagnostics.append(
                {
                    "level": "warning",
                    "code": "catalog_cycle",
                    "message": f"Catalog cycle detected at: {path}",
                }
            )
            return
        self._visited_catalogs.add(path)
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
                else:
                    self.diagnostics.append(
                        {
                            "level": "warning",
                            "code": "missing_next_catalog",
                            "message": f"Referenced nextCatalog does not exist: {next_path}",
                        }
                    )

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
        return self.resolve_detailed(uri).path

    def resolve_detailed(self, uri: str) -> CatalogResolution:
        """Resolve *uri* and disclose the strategy and candidate set."""
        self._hash_fallback_used = False
        self._rewrite_fallback_used = False

        # Try exact match first
        if uri in self.mappings:
            return CatalogResolution(uri, self.mappings[uri], "exact")
        
        # Try with/without trailing slash
        uri_with_slash = uri.rstrip('/') + '/'
        if uri_with_slash in self.mappings:
            return CatalogResolution(uri, self.mappings[uri_with_slash], "slash_fallback")
        
        uri_without_slash = uri.rstrip('/')
        if uri_without_slash in self.mappings:
            return CatalogResolution(uri, self.mappings[uri_without_slash], "slash_fallback")

        # Try with/without trailing hash
        uri_with_hash = uri.rstrip('#') + '#'
        if uri_with_hash in self.mappings:
            self._hash_fallback_used = True
            return CatalogResolution(uri, self.mappings[uri_with_hash], "hash_fallback")

        uri_without_hash = uri.rstrip('#')
        if uri_without_hash in self.mappings:
            self._hash_fallback_used = True
            return CatalogResolution(uri, self.mappings[uri_without_hash], "hash_fallback")

        # Try rewriteURI rules (longest-prefix-wins, already sorted)
        return self._resolve_via_rewrite(uri)

    # Extension probe order for rewriteURI fallback
    _EXTENSION_FALLBACK = [".rdf", ".ttl", ".owl"]

    def _resolve_via_rewrite(self, uri: str) -> CatalogResolution:
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
                return CatalogResolution(uri, candidate, "rewrite")

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
                return CatalogResolution(
                    uri,
                    found[0],
                    "rewrite_extension",
                    tuple(found),
                )

        return CatalogResolution(uri, None, "unresolved")
    
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
    from .ontology_loader import load_ontology

    loaded = load_ontology(
        ontology_path,
        catalog_path=catalog_path,
        degraded=True,
    )
    diagnostics: List[Dict[str, str]] = []
    for diagnostic in loaded.diagnostics:
        if diagnostic.code == "missing_import":
            message = f"No catalog mapping for: {diagnostic.import_uri}"
            level = "warning"
        elif diagnostic.code == "unsupported_file_import":
            message = (
                f"Skipping file:// import (use catalog instead): "
                f"{diagnostic.import_uri}"
            )
            level = "warning"
        elif diagnostic.code == "import_parse_error":
            message = diagnostic.message
            level = "error"
        else:
            message = diagnostic.message
            level = diagnostic.level
        diagnostics.append({"level": level, "message": message})
        if not quiet:
            prefix = "✗" if level == "error" else "⚠️" if level == "warning" else "ℹ️"
            print(f"{prefix}  {message}")

    loaded_imports = sum(1 for entry in loaded.manifest if entry.import_depth > 0)
    direct_imports = len(list(loaded.graph.objects(predicate=OWL.imports)))
    if not quiet:
        print(f"\n📦 Loaded {loaded_imports}/{direct_imports} imports via catalog")

    return CatalogLoadResult(graph=loaded.graph, diagnostics=diagnostics)


def resolve_import_paths(
    ontology_path: Path, catalog_path: Path
) -> Dict[str, Path]:
    """Resolve direct owl:imports URIs to local file paths.

    This is useful for discovering sibling files (e.g., extension defaults)
    alongside directly imported reference models.

    Args:
        ontology_path: Path to main ontology file
        catalog_path: Path to catalog-v001.xml

    Returns:
        Dict mapping import URI string → resolved local Path (only for
        imports that have a catalog mapping and whose file exists).
    """
    from .ontology_loader import load_ontology

    loaded = load_ontology(
        ontology_path,
        catalog_path=catalog_path,
        degraded=True,
    )
    return {
        entry.import_uri: Path(entry.source_path)
        for entry in loaded.manifest
        if entry.import_uri is not None and entry.import_depth == 1
    }


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
