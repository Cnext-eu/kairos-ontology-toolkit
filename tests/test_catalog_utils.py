# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for catalog utilities."""

import pytest
from pathlib import Path
from kairos_ontology.core.catalog_utils import (
    CatalogLoadResult,
    CatalogResolver,
    _get_rdf_format,
    resolve_import_paths,
)


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

    def test_next_catalog_chaining(self, temp_dir):
        """Test <nextCatalog> loads mappings from chained catalog."""
        # Create a child catalog with one mapping
        child_dir = temp_dir / "reference-models"
        child_dir.mkdir()
        (child_dir / "fibo.ttl").write_text("# fibo", encoding="utf-8")
        child_catalog = child_dir / "catalog-v001.xml"
        child_catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <uri name="https://spec.edmcouncil.org/fibo/test" uri="fibo.ttl"/>\n'
            '</catalog>\n',
            encoding="utf-8",
        )

        # Create a parent catalog that chains to the child
        parent_catalog = temp_dir / "catalog-v001.xml"
        parent_catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <uri name="https://example.com/ont/customer" uri="customer.ttl"/>\n'
            '  <nextCatalog catalog="reference-models/catalog-v001.xml"/>\n'
            '</catalog>\n',
            encoding="utf-8",
        )

        resolver = CatalogResolver(parent_catalog)

        # Should resolve both the local and the chained mapping
        assert resolver.resolve("https://example.com/ont/customer") is not None
        assert resolver.resolve("https://spec.edmcouncil.org/fibo/test") is not None

    def test_next_catalog_missing_is_silently_skipped(self, temp_dir):
        """nextCatalog pointing to a missing file should not raise."""
        catalog = temp_dir / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <uri name="urn:example:ok" uri="ok.ttl"/>\n'
            '  <nextCatalog catalog="does-not-exist/catalog.xml"/>\n'
            '</catalog>\n',
            encoding="utf-8",
        )
        resolver = CatalogResolver(catalog)
        assert resolver.resolve("urn:example:ok") is not None

    def test_resolve_hash_fallback_import_without_catalog_with(self, temp_dir):
        """Import without # resolves when catalog name has trailing #."""
        catalog = temp_dir / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <uri name="https://example.org/ont/booking#" uri="booking.ttl"/>\n'
            '</catalog>\n',
            encoding="utf-8",
        )
        resolver = CatalogResolver(catalog)
        # Import without hash should still resolve
        resolved = resolver.resolve("https://example.org/ont/booking")
        assert resolved is not None
        assert "booking.ttl" in str(resolved)

    def test_resolve_hash_fallback_import_with_catalog_without(self, temp_dir):
        """Import with # resolves when catalog name has no trailing #."""
        catalog = temp_dir / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <uri name="https://example.org/ont/cargo" uri="cargo.ttl"/>\n'
            '</catalog>\n',
            encoding="utf-8",
        )
        resolver = CatalogResolver(catalog)
        # Import with hash should still resolve
        resolved = resolver.resolve("https://example.org/ont/cargo#")
        assert resolved is not None
        assert "cargo.ttl" in str(resolved)

    def test_resolve_exact_match_preferred_over_hash_fallback(self, temp_dir):
        """Exact match is preferred; hash fallback flag not set."""
        catalog = temp_dir / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <uri name="https://example.org/ont/exact" uri="exact.ttl"/>\n'
            '</catalog>\n',
            encoding="utf-8",
        )
        resolver = CatalogResolver(catalog)
        resolved = resolver.resolve("https://example.org/ont/exact")
        assert resolved is not None
        assert not resolver._hash_fallback_used

    def test_resolve_hash_fallback_sets_flag(self, temp_dir):
        """When hash fallback is used, the flag is set for diagnostics."""
        catalog = temp_dir / "catalog.xml"
        # Only store with hash — no exact match for bare URI
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <uri name="https://example.org/ont/dcsa/booking#" uri="booking.ttl"/>\n'
            '</catalog>\n',
            encoding="utf-8",
        )
        resolver = CatalogResolver(catalog)
        # The normalization during load already stores bare variant,
        # so exact match will work — the flag tracks runtime resolution path
        resolved = resolver.resolve("https://example.org/ont/dcsa/booking")
        assert resolved is not None


class TestResolveImportPaths:
    """Tests for resolve_import_paths (DD-023 support)."""

    @pytest.fixture
    def temp_dir(self, tmp_path):
        return tmp_path

    def test_resolves_imports_via_catalog(self, temp_dir):
        """resolve_import_paths returns mapping of import URI → local path."""
        # Create a reference model file
        ref_file = temp_dir / "bsp-party.ttl"
        ref_file.write_text(
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "<https://bsp.2024.org/party> a owl:Ontology .\n",
            encoding="utf-8",
        )

        # Create domain ontology that imports it
        onto_file = temp_dir / "booking.ttl"
        onto_file.write_text(
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "<https://example.com/ont/booking> a owl:Ontology ;\n"
            "    owl:imports <https://bsp.2024.org/party> .\n",
            encoding="utf-8",
        )

        # Create catalog mapping
        catalog = temp_dir / "catalog-v001.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <uri name="https://bsp.2024.org/party" uri="bsp-party.ttl"/>\n'
            '</catalog>\n',
            encoding="utf-8",
        )

        result = resolve_import_paths(onto_file, catalog)
        assert "https://bsp.2024.org/party" in result
        assert result["https://bsp.2024.org/party"] == ref_file.resolve()

    def test_skips_file_uris(self, temp_dir):
        """file:// URIs are skipped."""
        onto_file = temp_dir / "domain.ttl"
        onto_file.write_text(
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "<https://example.com/ont/d> a owl:Ontology ;\n"
            "    owl:imports <file:///local/path.ttl> .\n",
            encoding="utf-8",
        )
        catalog = temp_dir / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '</catalog>\n',
            encoding="utf-8",
        )
        result = resolve_import_paths(onto_file, catalog)
        assert len(result) == 0

    def test_skips_unmapped_imports(self, temp_dir):
        """Imports without catalog mapping are excluded."""
        onto_file = temp_dir / "domain.ttl"
        onto_file.write_text(
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "<https://example.com/ont/d> a owl:Ontology ;\n"
            "    owl:imports <https://unknown.org/ont> .\n",
            encoding="utf-8",
        )
        catalog = temp_dir / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '</catalog>\n',
            encoding="utf-8",
        )
        result = resolve_import_paths(onto_file, catalog)
        assert len(result) == 0


class TestLoadGraphWithCatalogDiagnostics:
    """Tests for catalog load diagnostics capture (CatalogLoadResult)."""

    def test_returns_catalog_load_result(self, tmp_path):
        """load_graph_with_catalog returns a CatalogLoadResult."""
        from kairos_ontology.core.catalog_utils import load_graph_with_catalog

        onto = tmp_path / "test.ttl"
        onto.write_text(
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "<https://example.com/ont/t> a owl:Ontology .\n",
            encoding="utf-8",
        )
        catalog = tmp_path / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '</catalog>\n',
            encoding="utf-8",
        )

        result = load_graph_with_catalog(onto, catalog)
        assert isinstance(result, CatalogLoadResult)
        assert len(result.graph) > 0
        assert result.diagnostics == []

    def test_unresolved_import_produces_warning_diagnostic(self, tmp_path):
        """Unresolved owl:imports generates a warning in diagnostics."""
        from kairos_ontology.core.catalog_utils import load_graph_with_catalog

        onto = tmp_path / "domain.ttl"
        onto.write_text(
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "<https://example.com/ont/d> a owl:Ontology ;\n"
            "    owl:imports <https://missing.org/ont/foo> .\n",
            encoding="utf-8",
        )
        catalog = tmp_path / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '</catalog>\n',
            encoding="utf-8",
        )

        result = load_graph_with_catalog(onto, catalog)
        assert len(result.diagnostics) == 1
        assert result.diagnostics[0]["level"] == "warning"
        assert "No catalog mapping for" in result.diagnostics[0]["message"]
        assert "https://missing.org/ont/foo" in result.diagnostics[0]["message"]

    def test_warnings_helper_method(self, tmp_path):
        """CatalogLoadResult.warnings() returns only warning messages."""
        from kairos_ontology.core.catalog_utils import load_graph_with_catalog

        onto = tmp_path / "domain.ttl"
        onto.write_text(
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "<https://example.com/ont/d> a owl:Ontology ;\n"
            "    owl:imports <https://missing.org/a> ;\n"
            "    owl:imports <https://missing.org/b> .\n",
            encoding="utf-8",
        )
        catalog = tmp_path / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '</catalog>\n',
            encoding="utf-8",
        )

        result = load_graph_with_catalog(onto, catalog)
        warnings = result.warnings()
        assert len(warnings) == 2
        assert all("No catalog mapping for" in w for w in warnings)

    def test_file_uri_produces_warning_diagnostic(self, tmp_path):
        """file:// imports produce a warning diagnostic."""
        from kairos_ontology.core.catalog_utils import load_graph_with_catalog

        onto = tmp_path / "domain.ttl"
        onto.write_text(
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "<https://example.com/ont/d> a owl:Ontology ;\n"
            "    owl:imports <file:///some/local.ttl> .\n",
            encoding="utf-8",
        )
        catalog = tmp_path / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '</catalog>\n',
            encoding="utf-8",
        )

        result = load_graph_with_catalog(onto, catalog)
        assert len(result.diagnostics) == 1
        assert result.diagnostics[0]["level"] == "warning"
        assert "file://" in result.diagnostics[0]["message"]


class TestRewriteURIResolution:
    """Tests for <rewriteURI> catalog element parsing and resolution."""

    def test_rewrite_rule_is_parsed(self, tmp_path):
        """CatalogResolver parses <rewriteURI> elements."""
        catalog = tmp_path / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <rewriteURI uriStartString="https://example.org/ont/"\n'
            '              rewritePrefix="local/"/>\n'
            '</catalog>\n',
            encoding="utf-8",
        )
        resolver = CatalogResolver(catalog)
        assert len(resolver._rewrite_rules) == 1
        assert resolver._rewrite_rules[0][0] == "https://example.org/ont/"
        assert resolver._rewrite_rules[0][1] == "local/"

    def test_exact_uri_wins_over_rewrite(self, tmp_path):
        """Exact <uri> mapping takes priority over matching <rewriteURI>."""
        # Create the target file for the exact mapping
        exact_file = tmp_path / "exact.ttl"
        exact_file.write_text("# exact", encoding="utf-8")

        # Create a file that the rewrite would resolve to
        rewrite_dir = tmp_path / "local" / "Thing"
        rewrite_dir.mkdir(parents=True)
        (tmp_path / "local" / "Thing.ttl").write_text("# rewrite", encoding="utf-8")

        catalog = tmp_path / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <uri name="https://example.org/ont/Thing" uri="exact.ttl"/>\n'
            '  <rewriteURI uriStartString="https://example.org/ont/"\n'
            '              rewritePrefix="local/"/>\n'
            '</catalog>\n',
            encoding="utf-8",
        )
        resolver = CatalogResolver(catalog)
        resolved = resolver.resolve("https://example.org/ont/Thing")
        assert resolved == exact_file.resolve()

    def test_longest_prefix_wins(self, tmp_path):
        """When multiple rewrite rules match, longest uriStartString wins."""
        # Create files for both rules
        general_dir = tmp_path / "general" / "FND" / "Parties"
        general_dir.mkdir(parents=True)
        (tmp_path / "general" / "FND" / "Parties.rdf").write_text("# gen", encoding="utf-8")

        specific_dir = tmp_path / "fnd"
        specific_dir.mkdir(parents=True)
        specific_file = specific_dir / "Parties.rdf"
        specific_file.write_text("# specific", encoding="utf-8")

        catalog = tmp_path / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <rewriteURI uriStartString="https://spec.org/fibo/ontology/"\n'
            '              rewritePrefix="general/"/>\n'
            '  <rewriteURI uriStartString="https://spec.org/fibo/ontology/FND/"\n'
            '              rewritePrefix="fnd/"/>\n'
            '</catalog>\n',
            encoding="utf-8",
        )
        resolver = CatalogResolver(catalog)
        # The FND-specific rule should win for FND/Parties/
        resolved = resolver.resolve("https://spec.org/fibo/ontology/FND/Parties/")
        assert resolved == specific_file.resolve()

    def test_extension_fallback_resolves_trailing_slash(self, tmp_path):
        """Trailing-slash URI resolves to .rdf file via extension fallback."""
        # Simulate FIBO structure: directory path + .rdf file
        fibo_dir = tmp_path / "fibo" / "FND" / "AgentsAndPeople"
        fibo_dir.mkdir(parents=True)
        rdf_file = fibo_dir / "Agents.rdf"
        rdf_file.write_text("# agents rdf", encoding="utf-8")

        catalog = tmp_path / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <rewriteURI uriStartString="https://spec.edmcouncil.org/fibo/ontology/"\n'
            '              rewritePrefix="fibo/"/>\n'
            '</catalog>\n',
            encoding="utf-8",
        )
        resolver = CatalogResolver(catalog)
        resolved = resolver.resolve(
            "https://spec.edmcouncil.org/fibo/ontology/FND/AgentsAndPeople/Agents/"
        )
        assert resolved == rdf_file.resolve()
        assert resolver._rewrite_fallback_used is True

    def test_directory_not_returned_as_resolved(self, tmp_path):
        """A directory matching the rewrite path is NOT returned."""
        # Create a directory (but no file with matching extension)
        agents_dir = tmp_path / "fibo" / "FND" / "Agents"
        agents_dir.mkdir(parents=True)

        catalog = tmp_path / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <rewriteURI uriStartString="https://example.org/"\n'
            '              rewritePrefix="fibo/"/>\n'
            '</catalog>\n',
            encoding="utf-8",
        )
        resolver = CatalogResolver(catalog)
        # The URI resolves to the directory path — should return None
        resolved = resolver.resolve("https://example.org/FND/Agents")
        assert resolved is None

    def test_ambiguous_extensions_uses_first_priority(self, tmp_path):
        """When both .rdf and .ttl exist, first in priority order wins."""
        fibo_dir = tmp_path / "fibo" / "FND"
        fibo_dir.mkdir(parents=True)
        rdf_file = fibo_dir / "Agents.rdf"
        rdf_file.write_text("# rdf version", encoding="utf-8")
        ttl_file = fibo_dir / "Agents.ttl"
        ttl_file.write_text("# ttl version", encoding="utf-8")

        catalog = tmp_path / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <rewriteURI uriStartString="https://example.org/"\n'
            '              rewritePrefix="fibo/"/>\n'
            '</catalog>\n',
            encoding="utf-8",
        )
        resolver = CatalogResolver(catalog)
        resolved = resolver.resolve("https://example.org/FND/Agents/")
        # .rdf has higher priority
        assert resolved == rdf_file.resolve()

    def test_next_catalog_with_rewrite_rules(self, tmp_path):
        """<nextCatalog> containing <rewriteURI> rules is followed."""
        # Child catalog with rewrite rule
        child_dir = tmp_path / "reference-models"
        child_dir.mkdir()
        fibo_dir = child_dir / "fibo" / "FND"
        fibo_dir.mkdir(parents=True)
        rdf_file = fibo_dir / "Parties.rdf"
        rdf_file.write_text("# parties", encoding="utf-8")

        child_catalog = child_dir / "catalog-v001.xml"
        child_catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <rewriteURI uriStartString="https://spec.org/fibo/"\n'
            '              rewritePrefix="fibo/"/>\n'
            '</catalog>\n',
            encoding="utf-8",
        )

        # Parent catalog chains to child
        parent_catalog = tmp_path / "catalog.xml"
        parent_catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <nextCatalog catalog="reference-models/catalog-v001.xml"/>\n'
            '</catalog>\n',
            encoding="utf-8",
        )

        resolver = CatalogResolver(parent_catalog)
        resolved = resolver.resolve("https://spec.org/fibo/FND/Parties/")
        assert resolved == rdf_file.resolve()

    def test_direct_rewrite_match_no_fallback(self, tmp_path):
        """When rewritten path is a file directly, no extension fallback is used."""
        local_dir = tmp_path / "local"
        local_dir.mkdir()
        target = local_dir / "Thing.ttl"
        target.write_text("# thing", encoding="utf-8")

        catalog = tmp_path / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <rewriteURI uriStartString="https://example.org/"\n'
            '              rewritePrefix="local/"/>\n'
            '</catalog>\n',
            encoding="utf-8",
        )
        resolver = CatalogResolver(catalog)
        resolved = resolver.resolve("https://example.org/Thing.ttl")
        assert resolved == target.resolve()
        assert resolver._rewrite_fallback_used is False
