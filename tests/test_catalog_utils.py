"""Tests for catalog utilities."""

import pytest
from pathlib import Path
from kairos_ontology.catalog_utils import CatalogResolver, _get_rdf_format


class TestGetRdfFormat:
    """Test the RDF format detection from file extension."""
    
    def test_turtle_extensions(self):
        """Test .ttl and .turtle extensions return turtle format."""
        assert _get_rdf_format(Path("ontology.ttl")) == "turtle"
        assert _get_rdf_format(Path("ontology.turtle")) == "turtle"
        assert _get_rdf_format(Path("ontology.TTL")) == "turtle"  # Case insensitive
    
    def test_xml_extensions(self):
        """Test .rdf, .xml, and .owl extensions return xml format."""
        assert _get_rdf_format(Path("ontology.rdf")) == "xml"
        assert _get_rdf_format(Path("ontology.xml")) == "xml"
        assert _get_rdf_format(Path("ontology.owl")) == "xml"
        assert _get_rdf_format(Path("ontology.OWL")) == "xml"  # Case insensitive
    
    def test_other_formats(self):
        """Test other RDF format extensions."""
        assert _get_rdf_format(Path("data.n3")) == "n3"
        assert _get_rdf_format(Path("data.nt")) == "nt"
        assert _get_rdf_format(Path("data.ntriples")) == "nt"
        assert _get_rdf_format(Path("data.jsonld")) == "json-ld"
        assert _get_rdf_format(Path("data.json")) == "json-ld"
    
    def test_unknown_extension_defaults_to_turtle(self):
        """Test unknown extensions default to turtle format."""
        assert _get_rdf_format(Path("ontology.unknown")) == "turtle"
        assert _get_rdf_format(Path("ontology")) == "turtle"


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
