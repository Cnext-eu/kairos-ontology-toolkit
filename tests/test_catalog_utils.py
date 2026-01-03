"""Tests for catalog utilities."""

import pytest
from pathlib import Path
from kairos_ontology.catalog_utils import CatalogResolver


class TestCatalogResolver:
    """Test the catalog resolver."""
    
    def test_catalog_creation(self, temp_dir):
        """Test creating a simple catalog file."""
        catalog_content = """<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
    <uri name="urn:example:test" uri="test.ttl"/>
</catalog>
"""
        catalog_file = temp_dir / "catalog.xml"
        catalog_file.write_text(catalog_content, encoding='utf-8')
        
        resolver = CatalogResolver(catalog_file)
        assert len(resolver.mappings) > 0
    
    def test_catalog_resolve_uri(self, temp_dir):
        """Test resolving a URI through catalog."""
        catalog_content = """<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
    <uri name="urn:example:test" uri="ontologies/test.ttl"/>
</catalog>
"""
        catalog_file = temp_dir / "catalog.xml"
        catalog_file.write_text(catalog_content, encoding='utf-8')
        
        resolver = CatalogResolver(catalog_file)
        resolved = resolver.resolve("urn:example:test")
        
        assert resolved is not None
        assert "test.ttl" in str(resolved)
    
    def test_catalog_missing_file(self, temp_dir):
        """Test catalog with non-existent file."""
        catalog_file = temp_dir / "missing.xml"
        
        with pytest.raises(FileNotFoundError):
            CatalogResolver(catalog_file)
