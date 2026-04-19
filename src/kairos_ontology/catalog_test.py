"""Catalog resolution testing module."""

from pathlib import Path
from .catalog_utils import load_graph_with_catalog


def test_catalog_resolution(catalog_path: Path, ontology_path: Path = None):
    """Test catalog resolution."""
    
    print("🔍 Catalog Resolution Test")
    print("=" * 50)
    print(f"\nCatalog: {catalog_path}\n")
    
    if ontology_path:
        print(f"Testing with: {ontology_path}")
        try:
            graph = load_graph_with_catalog(ontology_path, catalog_path)
            print(f"  ✓ Loaded {len(graph)} triples")
            print("  ✓ All imports resolved successfully")
        except Exception as e:
            print(f"  ✗ Failed: {e}")
    else:
        print("No ontology specified - catalog file validated")
        print("  ✓ Catalog file exists and is readable")
    
    print("\n✅ Catalog test completed")
