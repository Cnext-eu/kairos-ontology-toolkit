# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the projection orchestrator."""

import pytest
from pathlib import Path
from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef, OWL


# ---------------------------------------------------------------------------
# extract_ontology_metadata tests
# We import via the installed package. If the function doesn't exist in the
# installed version, these tests are skipped gracefully.
# ---------------------------------------------------------------------------

try:
    from kairos_ontology.projector import extract_ontology_metadata
    _HAS_EXTRACT = True
except ImportError:
    _HAS_EXTRACT = False


@pytest.mark.skipif(not _HAS_EXTRACT, reason="extract_ontology_metadata not in installed package")
class TestExtractOntologyMetadata:
    """Tests for the metadata extraction helper."""

    def test_extracts_iri_version_label(self):
        g = Graph()
        ns = "http://example.com/customer#"
        onto_uri = URIRef("http://example.com/customer")
        g.add((onto_uri, RDF.type, OWL.Ontology))
        g.add((onto_uri, OWL.versionInfo, Literal("2.3.1")))
        g.add((onto_uri, RDFS.label, Literal("Customer Domain", lang="en")))

        meta = extract_ontology_metadata(g, ns)
        assert meta["iri"] == "http://example.com/customer"
        assert meta["version"] == "2.3.1"
        assert meta["label"] == "Customer Domain"
        assert meta["namespace"] == ns
        assert meta["toolkit_version"]
        assert meta["generated_at"]

    def test_missing_version_returns_empty_string(self):
        g = Graph()
        ns = "http://example.com/party#"
        g.add((URIRef("http://example.com/party"), RDF.type, OWL.Ontology))

        meta = extract_ontology_metadata(g, ns)
        assert meta["iri"] == "http://example.com/party"
        assert meta["version"] == ""
        assert meta["label"] == ""

    def test_no_ontology_declaration_uses_namespace_fallback(self):
        g = Graph()
        ns = "http://example.com/unknown#"
        meta = extract_ontology_metadata(g, ns)
        assert meta["iri"] == "http://example.com/unknown"
        assert meta["version"] == ""


from kairos_ontology.projector import run_projections


class TestProjector:
    """Test the projection orchestrator."""
    
    def test_load_single_ontology_file(self, temp_dir, ontology_files, capsys):
        """Test loading a single ontology file."""
        output_dir = temp_dir / "output"
        
        # Run projections on the ontologies directory
        run_projections(
            ontologies_path=ontology_files['dir'],
            catalog_path=None,
            output_path=output_dir,
            target='dbt'
        )
        
        captured = capsys.readouterr()
        assert "customer.ttl" in captured.out or "person.ttl" in captured.out
        assert "triples" in captured.out.lower()
    
    def test_load_directory_with_multiple_files(self, temp_dir, ontology_files, capsys):
        """Test loading multiple ontology files from a directory."""
        output_dir = temp_dir / "output"
        
        run_projections(
            ontologies_path=ontology_files['dir'],
            catalog_path=None,
            output_path=output_dir,
            target='neo4j'
        )
        
        captured = capsys.readouterr()
        # Should load both files
        assert "customer.ttl" in captured.out or "✓ Loaded" in captured.out
        assert "person.ttl" in captured.out or "✓ Loaded" in captured.out
    
    def test_empty_directory(self, temp_dir, capsys):
        """Test handling of empty directory."""
        empty_dir = temp_dir / "empty"
        empty_dir.mkdir()
        output_dir = temp_dir / "output"
        
        run_projections(
            ontologies_path=empty_dir,
            catalog_path=None,
            output_path=output_dir,
            target='dbt'
        )
        
        captured = capsys.readouterr()
        assert "No ontology files found" in captured.out or "No Kairos classes" in captured.out
    
    def test_invalid_ontology_file(self, temp_dir, capsys):
        """Test handling of invalid ontology file."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        # Create invalid file
        invalid_file = ontologies_dir / "invalid.ttl"
        invalid_file.write_text("This is not valid Turtle syntax @#$%^&", encoding='utf-8')
        
        output_dir = temp_dir / "output"
        
        run_projections(
            ontologies_path=ontologies_dir,
            catalog_path=None,
            output_path=output_dir,
            target='dbt'
        )
        
        captured = capsys.readouterr()
        assert "Could not parse" in captured.out or "⚠️" in captured.out
    
    def test_dbt_projection_creates_files(self, temp_dir, ontology_files):
        """Test that DBT projection creates output files."""
        output_dir = temp_dir / "output"
        
        run_projections(
            ontologies_path=ontology_files['dir'],
            catalog_path=None,
            output_path=output_dir,
            target='dbt'
        )
        
        # Check if DBT output directory was created
        dbt_dir = output_dir / "dbt"
        assert dbt_dir.exists()
    
    def test_neo4j_projection_creates_files(self, temp_dir, ontology_files):
        """Test that Neo4j projection creates output files."""
        output_dir = temp_dir / "output"
        
        run_projections(
            ontologies_path=ontology_files['dir'],
            catalog_path=None,
            output_path=output_dir,
            target='neo4j'
        )
        
        # Check if Neo4j output directory was created
        neo4j_dir = output_dir / "neo4j"
        assert neo4j_dir.exists()
        
        # Check if schema file was created
        schema_file = neo4j_dir / "schema.cypher"
        if schema_file.exists():
            content = schema_file.read_text()
            assert "CREATE CONSTRAINT" in content or "Customer" in content
    
    def test_all_targets_projection(self, temp_dir, ontology_files):
        """Test running all projection targets."""
        output_dir = temp_dir / "output"
        
        run_projections(
            ontologies_path=ontology_files['dir'],
            catalog_path=None,
            output_path=output_dir,
            target='all'
        )
        
        # Check that all target directories were created
        assert (output_dir / "dbt").exists()
        assert (output_dir / "neo4j").exists()
        assert (output_dir / "azure-search").exists()
        assert (output_dir / "a2ui").exists()
        assert (output_dir / "prompt").exists()
    
    def test_graph_merging(self, temp_dir, ontology_files):
        """Test that multiple ontology files are merged into a single graph."""
        
        # Manually load and merge to test the concept
        merged_graph = Graph()
        
        for onto_file in [ontology_files['customer'], ontology_files['person']]:
            merged_graph.parse(onto_file, format='turtle')
        
        # Check that classes from both files are in the merged graph
        KAIROS = Namespace("http://kairos.example/ontology/")
        
        customer_exists = (KAIROS.Customer, RDF.type, OWL.Class) in merged_graph
        person_exists = (KAIROS.Person, RDF.type, OWL.Class) in merged_graph
        
        assert customer_exists or person_exists, "Classes should be loaded from ontology files"
    
    def test_urn_namespace_extraction(self, temp_dir, sample_ontology):
        """Test that HTTP namespace classes are correctly identified."""
        
        graph = Graph()
        ontology_file = temp_dir / "test.ttl"
        ontology_file.write_text(sample_ontology, encoding='utf-8')
        graph.parse(ontology_file, format='turtle')
        
        # Query for classes
        query = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        SELECT ?class WHERE {
            ?class a owl:Class .
        }
        """
        
        classes = []
        for row in graph.query(query):
            class_uri = str(row['class'])
            if class_uri.startswith('http://kairos.example/ontology/'):
                class_name = class_uri.split('/')[-1]
                classes.append(class_name)
        
        assert 'Customer' in classes, "Customer class should be extracted"
    
    def test_non_kairos_namespace_filtered(self, temp_dir):
        """Test that non-Kairos namespace classes are filtered out."""
        ontology_content = """
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix external: <http://example.com/external#> .
        @prefix kairos: <urn:kairos:ont:core:> .
        
        kairos:MyClass a owl:Class ;
            rdfs:label "My Class" .
        
        external:OtherClass a owl:Class ;
            rdfs:label "Other Class" .
        """
        
        ontology_file = temp_dir / "test.ttl"
        ontology_file.write_text(ontology_content, encoding='utf-8')
        
        graph = Graph()
        graph.parse(ontology_file, format='turtle')
        
        query = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        SELECT ?class WHERE {
            ?class a owl:Class .
        }
        """
        
        kairos_classes = []
        for row in graph.query(query):
            class_uri = str(row['class'])
            if class_uri.startswith('urn:kairos:ont:'):
                kairos_classes.append(class_uri.split(':')[-1])
        
        assert 'MyClass' in kairos_classes
        assert 'OtherClass' not in kairos_classes
    
    def test_http_namespace_slash_based(self, temp_dir, http_ontology):
        """Test that path-based HTTP namespaces are properly handled."""
        from kairos_ontology.projector import run_projections
        
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        # Create ontology with slash-based namespace
        onto_file = ontologies_dir / "products.ttl"
        onto_file.write_text(http_ontology, encoding='utf-8')
        
        output_dir = temp_dir / "output"
        
        # Run projection with explicit namespace
        run_projections(
            ontologies_path=ontologies_dir,
            catalog_path=None,
            output_path=output_dir,
            target='dbt',
            namespace='http://example.org/ontology/'
        )
        
        # Verify DBT files were created
        dbt_dir = output_dir / 'dbt'
        assert dbt_dir.exists()
        
        # Check that Product class was found (files may be in models/silver subdirectory)
        sql_files = list(dbt_dir.glob('**/*.sql'))
        assert len(sql_files) > 0
        
        # Verify content mentions Product
        product_found = any('product' in f.read_text().lower() for f in sql_files)
        assert product_found, "Product class should be in generated SQL"
    
    def test_http_namespace_hash_based(self, temp_dir, hash_ontology):
        """Test that fragment-based HTTP namespaces (with #) are properly handled."""
        from kairos_ontology.projector import run_projections
        
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        # Create ontology with hash-based namespace
        onto_file = ontologies_dir / "fibo.ttl"
        onto_file.write_text(hash_ontology, encoding='utf-8')
        
        output_dir = temp_dir / "output"
        
        # Run projection with explicit namespace
        run_projections(
            ontologies_path=ontologies_dir,
            catalog_path=None,
            output_path=output_dir,
            target='neo4j',
            namespace='https://spec.edmcouncil.org/fibo/ontology/FND/Relations/Relations#'
        )
        
        # Verify Neo4j files were created
        neo4j_dir = output_dir / 'neo4j'
        assert neo4j_dir.exists()
        
        cypher_files = list(neo4j_dir.glob('*.cypher'))
        assert len(cypher_files) > 0
        
        # Verify content mentions Organization
        org_found = any('organization' in f.read_text().lower() for f in cypher_files)
        assert org_found, "Organization class should be in generated Cypher"
    
    def test_namespace_auto_detection(self, temp_dir, http_ontology):
        """Test that namespace is auto-detected when not provided."""
        from kairos_ontology.projector import run_projections
        
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        onto_file = ontologies_dir / "products.ttl"
        onto_file.write_text(http_ontology, encoding='utf-8')
        
        output_dir = temp_dir / "output"
        
        # Run WITHOUT specifying namespace - should auto-detect
        run_projections(
            ontologies_path=ontologies_dir,
            catalog_path=None,
            output_path=output_dir,
            target='dbt',
            namespace=None  # Auto-detect
        )
        
        # Should still generate files
        dbt_dir = output_dir / 'dbt'
        assert dbt_dir.exists()
        sql_files = list(dbt_dir.glob('**/*.sql'))
        assert len(sql_files) > 0
    
    def test_windows_safe_filenames_from_http_uris(self, temp_dir, http_ontology):
        """Test that HTTP URIs generate Windows-safe filenames (no colons in paths)."""
        from kairos_ontology.projector import run_projections
        
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        onto_file = ontologies_dir / "products.ttl"
        onto_file.write_text(http_ontology, encoding='utf-8')
        
        output_dir = temp_dir / "output"
        
        # Run projection - should create files with safe names
        run_projections(
            ontologies_path=ontologies_dir,
            catalog_path=None,
            output_path=output_dir,
            target='all',
            namespace='http://example.org/ontology/'
        )
        
        # Check that NO files or directories contain colons (Windows-incompatible)
        for item in output_dir.rglob('*'):
            # File/directory names should not contain : (except drive letter on Windows)
            name = item.name
            assert ':' not in name, f"Found Windows-incompatible filename: {name}"
            
            # Specifically check SQL files use simple names
            if item.suffix == '.sql':
                # Should be like "product.sql" not "http://example.org/ontology/Product.sql"
                assert 'http' not in name.lower()
                assert '/' not in name
                assert name.replace('.', '').replace('_', '').replace('-', '').isalnum()
    
    def test_auto_detect_prefers_custom_namespace_over_fibo(self, temp_dir, ontology_with_fibo_imports):
        """Test that auto-detection picks custom namespace even when FIBO has more classes."""
        from kairos_ontology.projector import run_projections
        
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        # Create ontology with 5 FIBO classes and 3 custom classes
        onto_file = ontologies_dir / "mixed.ttl"
        onto_file.write_text(ontology_with_fibo_imports, encoding='utf-8')
        
        output_dir = temp_dir / "output"
        
        # Run WITHOUT specifying namespace - should auto-detect custom, not FIBO
        run_projections(
            ontologies_path=ontologies_dir,
            catalog_path=None,
            output_path=output_dir,
            target='dbt',
            namespace=None  # Auto-detect should pick custom namespace
        )
        
        # Check that custom classes were projected, not FIBO
        dbt_dir = output_dir / 'dbt'
        assert dbt_dir.exists()
        
        sql_files = list(dbt_dir.glob('**/*.sql'))
        assert len(sql_files) > 0
        
        # Check filenames - should have custom classes, not FIBO
        filenames = [f.stem for f in sql_files]
        
        # Should have custom classes
        custom_classes = ['customer', 'order', 'product']
        found_custom = [cls for cls in custom_classes if cls in filenames]
        assert len(found_custom) > 0, f"Should find custom classes, found: {filenames}"
        
        # Should NOT have FIBO classes
        fibo_classes = ['organization', 'person', 'legalentity', 'contract', 'agreement']
        found_fibo = [cls for cls in fibo_classes if cls in filenames]
        assert len(found_fibo) == 0, f"Should NOT project FIBO classes, but found: {found_fibo}"
    
    def test_owl_ontology_declaration_method(self, temp_dir, ontology_with_declaration):
        """Test that owl:Ontology declaration is used for namespace detection (semantic web standard)."""
        from kairos_ontology.projector import run_projections
        
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        onto_file = ontologies_dir / "myapp.ttl"
        onto_file.write_text(ontology_with_declaration, encoding='utf-8')
        
        output_dir = temp_dir / "output"
        
        # Run WITHOUT specifying namespace - should detect from owl:Ontology
        run_projections(
            ontologies_path=ontologies_dir,
            catalog_path=None,
            output_path=output_dir,
            target='dbt',
            namespace=None
        )
        
        # Should generate files for the custom namespace
        dbt_dir = output_dir / 'dbt'
        assert dbt_dir.exists()
        
        sql_files = list(dbt_dir.glob('**/*.sql'))
        assert len(sql_files) > 0
        
        # Should have customer.sql
        filenames = [f.stem for f in sql_files]
        assert 'customer' in filenames, f"Should find Customer class, found: {filenames}"
    
    def test_dbt_shacl_tests_extraction(self, temp_dir, sample_ontology, sample_shacl_shapes):
        """Test that SHACL constraints are properly extracted and converted to DBT tests."""
        import yaml
        
        # Setup directories
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()
        
        # Create ontology file
        onto_file = ontologies_dir / "customer.ttl"
        onto_file.write_text(sample_ontology, encoding='utf-8')
        
        # Create SHACL shapes file
        shapes_file = shapes_dir / "customer.shacl.ttl"
        shapes_file.write_text(sample_shacl_shapes, encoding='utf-8')
        
        output_dir = temp_dir / "output"
        
        # Manually call the DBT projector to avoid emoji encoding issues
        from kairos_ontology.projections.dbt_projector import generate_dbt_artifacts
        
        # Load ontology
        graph = Graph()
        graph.parse(onto_file, format='turtle')
        
        # Extract classes
        classes = [{
            'uri': 'http://kairos.example/ontology/Customer',
            'name': 'Customer',
            'label': 'Customer',
            'comment': 'A customer entity'
        }]
        
        # Generate artifacts
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=graph,
            template_dir=Path(__file__).parent.parent / 'src' / 'kairos_ontology' / 'templates' / 'dbt',
            namespace='http://kairos.example/ontology/',
            shapes_dir=shapes_dir
        )
        
        # Write artifacts
        dbt_dir = output_dir / 'dbt'
        for file_path, content in artifacts.items():
            output_file = dbt_dir / file_path
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(content, encoding='utf-8')
        
        # Check schema YAML was created
        schema_file = dbt_dir / 'models' / 'silver' / 'schema_customer.yml'
        assert schema_file.exists(), "Schema YAML file should be created"
        
        # Parse YAML and verify structure
        schema_content = yaml.safe_load(schema_file.read_text(encoding='utf-8'))
        
        # Verify top-level structure
        assert 'models' in schema_content, "Schema should have 'models' key"
        assert len(schema_content['models']) == 1, "Should have one model"
        
        model = schema_content['models'][0]
        
        # Verify model has correct name (lowercase)
        assert model.get('name') == 'customer', f"Model name should be 'customer', got {model.get('name')}"
        assert 'description' in model, "Model should have description"
        assert 'columns' in model, "Model should have columns"
        
        # Verify columns structure
        columns = {col['name']: col for col in model['columns']}
        
        # Check customer_name column
        assert 'customer_name' in columns, "Should have customer_name column"
        customer_name_col = columns['customer_name']
        assert 'description' in customer_name_col, "Column should have description"
        assert 'data_type' in customer_name_col, "Column should have data_type"
        assert customer_name_col['data_type'] == 'STRING', f"Should be STRING type, got {customer_name_col['data_type']}"
        
        # Verify SHACL tests were extracted
        assert 'tests' in customer_name_col, "Column should have tests"
        tests = customer_name_col['tests']
        assert len(tests) > 0, "Should have at least one test from SHACL"
        
        # Check for not_null test (from sh:minCount 1)
        test_str = str(tests)
        assert 'not_null' in test_str, f"Should have not_null test from minCount, got: {tests}"
        
        # Check for length constraints (from sh:minLength/maxLength)
        assert 'length' in test_str.lower() or 'expression_is_true' in test_str.lower(), \
            f"Should have length constraint tests, got: {tests}"
        
        # Check customer_email column
        assert 'customer_email' in columns, "Should have customer_email column"
        customer_email_col = columns['customer_email']
        assert 'tests' in customer_email_col, "Email column should have tests"
        
        # Check for not_null test (from sh:minCount 1)
        email_tests = customer_email_col['tests']
        email_test_str = str(email_tests)
        assert 'not_null' in email_test_str.lower(), "Email should have not_null test"    
    def test_azure_search_projection_creates_files(self, temp_dir, sample_ontology):
        """Test that Azure Search projection creates index definition files."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        onto_file = ontologies_dir / "customer.ttl"
        onto_file.write_text(sample_ontology, encoding='utf-8')
        
        output_dir = temp_dir / "output"
        
        run_projections(
            ontologies_path=ontologies_dir,
            catalog_path=None,
            output_path=output_dir,
            target='azure-search'
        )
        
        # Check that azure-search directory was created
        azure_dir = output_dir / "azure-search"
        assert azure_dir.exists(), "Azure Search output directory should exist"
        
        # Check for domain subdirectory with indexes
        customer_dir = azure_dir / "customer" / "indexes"
        assert customer_dir.exists(), "Customer indexes directory should exist"
        
        # Check for index JSON file
        index_files = list(customer_dir.glob("*.json"))
        assert len(index_files) > 0, "Should have at least one index JSON file"
        
        # Verify index file content
        import json
        index_file = index_files[0]
        index_data = json.loads(index_file.read_text(encoding='utf-8'))
        
        assert 'name' in index_data, "Index should have name"
        assert 'fields' in index_data, "Index should have fields"
        assert len(index_data['fields']) > 0, "Index should have at least one field"
        
        # Verify field structure
        first_field = index_data['fields'][0]
        assert 'name' in first_field, "Field should have name"
        assert 'type' in first_field, "Field should have type (Edm type)"
    
    def test_a2ui_projection_creates_files(self, temp_dir, sample_ontology):
        """Test that A2UI projection creates JSON Schema files."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        onto_file = ontologies_dir / "customer.ttl"
        onto_file.write_text(sample_ontology, encoding='utf-8')
        
        output_dir = temp_dir / "output"
        
        run_projections(
            ontologies_path=ontologies_dir,
            catalog_path=None,
            output_path=output_dir,
            target='a2ui'
        )
        
        # Check that a2ui directory was created
        a2ui_dir = output_dir / "a2ui"
        assert a2ui_dir.exists(), "A2UI output directory should exist"
        
        # Check for domain subdirectory with schemas
        customer_dir = a2ui_dir / "customer" / "schemas"
        assert customer_dir.exists(), "Customer schemas directory should exist"
        
        # Check for schema JSON files
        schema_files = list(customer_dir.glob("*.json"))
        assert len(schema_files) > 0, "Should have at least one schema JSON file"
        
        # Verify schema file content
        import json
        schema_file = schema_files[0]
        schema_data = json.loads(schema_file.read_text(encoding='utf-8'))
        
        assert '$schema' in schema_data, "Should have $schema declaration"
        assert 'type' in schema_data, "Schema should have type"
        assert schema_data['type'] == 'object', "Should be object type"
        assert 'properties' in schema_data, "Schema should have properties"
    
    def test_prompt_projection_creates_files(self, temp_dir, sample_ontology):
        """Test that Prompt projection creates context JSON files."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        onto_file = ontologies_dir / "customer.ttl"
        onto_file.write_text(sample_ontology, encoding='utf-8')
        
        output_dir = temp_dir / "output"
        
        run_projections(
            ontologies_path=ontologies_dir,
            catalog_path=None,
            output_path=output_dir,
            target='prompt'
        )
        
        # Check that prompt directory was created
        prompt_dir = output_dir / "prompt"
        assert prompt_dir.exists(), "Prompt output directory should exist"
        
        # Check for both compact and detailed files with domain name
        compact_file = prompt_dir / "customer-context.json"
        detailed_file = prompt_dir / "customer-context-detailed.json"
        
        assert compact_file.exists(), "Compact context file should exist"
        assert detailed_file.exists(), "Detailed context file should exist"
        
        # Verify compact file content (LLM-optimized structure)
        import json
        compact_data = json.loads(compact_file.read_text(encoding='utf-8'))
        
        assert 'domain' in compact_data, "Should have domain name"
        assert 'entities' in compact_data, "Should have entities object"
        # Relationships may be empty if no object properties exist
        if 'relationships' in compact_data:
            assert isinstance(compact_data['relationships'], list), "Relationships should be a list"
        assert len(compact_data['entities']) > 0, "Should have at least one entity"
        
        # Verify entity structure (first entity)
        first_entity_name = list(compact_data['entities'].keys())[0]
        first_entity = compact_data['entities'][first_entity_name]
        assert 'description' in first_entity or 'fields' in first_entity, "Entity should have description or fields"
        
        if 'fields' in first_entity:
            # Verify field structure
            first_field_name = list(first_entity['fields'].keys())[0]
            first_field = first_entity['fields'][first_field_name]
            assert 'type' in first_field, "Field should have type"
        
        # Verify detailed file is different and larger
        detailed_data = json.loads(detailed_file.read_text(encoding='utf-8'))
        assert 'ontology' in detailed_data, "Detailed format should have ontology metadata"
        assert 'entities' in detailed_data, "Detailed format should have entities array"
        
        # Verify detailed has more metadata
        detailed_size = detailed_file.stat().st_size
        compact_size = compact_file.stat().st_size
        assert detailed_size > compact_size, "Detailed format should be larger than compact"
    
    def test_prompt_projection_extracts_properties(self, temp_dir):
        """Test that prompt projection extracts all datatype properties."""
        import json
        
        # Create ontology with multiple property types
        ontology_content = """
@prefix : <http://kairos.example/ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:TestOntology a owl:Ontology ;
    rdfs:label "Test Ontology" .

:Product a owl:Class ;
    rdfs:label "Product" ;
    rdfs:comment "A product in the catalog" .

:productName a owl:DatatypeProperty ;
    rdfs:domain :Product ;
    rdfs:range xsd:string ;
    rdfs:label "Product Name" ;
    rdfs:comment "Name of the product" .

:productPrice a owl:DatatypeProperty ;
    rdfs:domain :Product ;
    rdfs:range xsd:decimal ;
    rdfs:label "Product Price" ;
    rdfs:comment "Price in USD" .

:productQuantity a owl:DatatypeProperty ;
    rdfs:domain :Product ;
    rdfs:range xsd:integer ;
    rdfs:label "Product Quantity" ;
    rdfs:comment "Quantity in stock" .

:productActive a owl:DatatypeProperty ;
    rdfs:domain :Product ;
    rdfs:range xsd:boolean ;
    rdfs:label "Product Active" ;
    rdfs:comment "Whether product is active" .

:productLaunchDate a owl:DatatypeProperty ;
    rdfs:domain :Product ;
    rdfs:range xsd:dateTime ;
    rdfs:label "Product Launch Date" ;
    rdfs:comment "When product was launched" .
"""
        
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        onto_file = ontologies_dir / "product.ttl"
        onto_file.write_text(ontology_content, encoding='utf-8')
        
        output_dir = temp_dir / "output"
        
        run_projections(
            ontologies_path=ontologies_dir,
            catalog_path=None,
            output_path=output_dir,
            target='prompt'
        )
        
        # Read compact file (domain-specific filename based on ontology file name)
        compact_file = output_dir / "prompt" / "product-context.json"
        compact_data = json.loads(compact_file.read_text(encoding='utf-8'))
        
        # Verify Product entity exists
        assert 'Product' in compact_data['entities'], "Product entity should exist"
        product = compact_data['entities']['Product']
        
        # Verify all properties are extracted
        assert 'fields' in product, "Product should have fields"
        fields = product['fields']
        
        assert 'productName' in fields, "Should have productName field"
        assert 'productPrice' in fields, "Should have productPrice field"
        assert 'productQuantity' in fields, "Should have productQuantity field"
        assert 'productActive' in fields, "Should have productActive field"
        assert 'productLaunchDate' in fields, "Should have productLaunchDate field"
        
        # Verify type mapping (XSD types to simplified types)
        assert fields['productName']['type'] == 'text', "String should map to text"
        assert fields['productPrice']['type'] == 'decimal', "Decimal should map to decimal"
        assert fields['productQuantity']['type'] == 'number', "Integer should map to number"
        assert fields['productActive']['type'] == 'boolean', "Boolean should map to boolean"
        assert fields['productLaunchDate']['type'] == 'datetime', "DateTime should map to datetime"
        
        # Verify descriptions are included
        assert 'desc' in fields['productName'], "Should have description"
        assert fields['productName']['desc'] == "Name of the product"
    
    def test_prompt_projection_extracts_relationships(self, temp_dir):
        """Test that prompt projection extracts object properties as relationships."""
        import json
        
        # Create ontology with relationships
        ontology_content = """
@prefix : <http://kairos.example/ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:OrderOntology a owl:Ontology ;
    rdfs:label "Order Ontology" .

:Customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer" .

:Order a owl:Class ;
    rdfs:label "Order" ;
    rdfs:comment "An order" .

:Product a owl:Class ;
    rdfs:label "Product" ;
    rdfs:comment "A product" .

:placedOrder a owl:ObjectProperty ;
    rdfs:domain :Customer ;
    rdfs:range :Order ;
    rdfs:label "Placed Order" ;
    rdfs:comment "Customer placed an order" .

:orderedProduct a owl:ObjectProperty ;
    rdfs:domain :Order ;
    rdfs:range :Product ;
    rdfs:label "Ordered Product" ;
    rdfs:comment "Order contains a product" .

:customerName a owl:DatatypeProperty ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string ;
    rdfs:comment "Customer name" .
"""
        
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        onto_file = ontologies_dir / "order.ttl"
        onto_file.write_text(ontology_content, encoding='utf-8')
        
        output_dir = temp_dir / "output"
        
        run_projections(
            ontologies_path=ontologies_dir,
            catalog_path=None,
            output_path=output_dir,
            target='prompt'
        )
        
        # Read compact file (domain-specific filename based on ontology file name)
        compact_file = output_dir / "prompt" / "order-context.json"
        compact_data = json.loads(compact_file.read_text(encoding='utf-8'))
        
        # Verify relationships are extracted
        assert 'relationships' in compact_data, "Should have relationships"
        relationships = compact_data['relationships']
        
        assert len(relationships) == 2, "Should have 2 relationships"
        
        # Find relationships by name
        rel_names = [r['name'] for r in relationships]
        assert 'placedOrder' in rel_names, "Should have placedOrder relationship"
        assert 'orderedProduct' in rel_names, "Should have orderedProduct relationship"
        
        # Verify relationship structure
        placed_order = next(r for r in relationships if r['name'] == 'placedOrder')
        assert placed_order['from'] == 'Customer', "Should have correct domain"
        assert placed_order['to'] == 'Order', "Should have correct range"
        assert placed_order['desc'] == "Customer placed an order", "Should have description"
    
    def test_prompt_projection_compact_vs_detailed_structure(self, temp_dir, sample_ontology):
        """Test the structural differences between compact and detailed formats."""
        import json
        
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        onto_file = ontologies_dir / "customer.ttl"
        onto_file.write_text(sample_ontology, encoding='utf-8')
        
        output_dir = temp_dir / "output"
        
        run_projections(
            ontologies_path=ontologies_dir,
            catalog_path=None,
            output_path=output_dir,
            target='prompt'
        )
        
        # Read both files (domain-specific filenames)
        compact_file = output_dir / "prompt" / "customer-context.json"
        detailed_file = output_dir / "prompt" / "customer-context-detailed.json"
        
        compact_data = json.loads(compact_file.read_text(encoding='utf-8'))
        detailed_data = json.loads(detailed_file.read_text(encoding='utf-8'))
        
        # Verify compact structure (optimized for LLM)
        assert isinstance(compact_data['entities'], dict), "Compact entities should be object/dict"
        assert 'domain' in compact_data, "Compact should have domain"
        assert 'ontology' not in compact_data, "Compact should not have ontology metadata"
        
        # Verify detailed structure (full reference)
        assert isinstance(detailed_data['entities'], list), "Detailed entities should be array/list"
        assert 'ontology' in detailed_data, "Detailed should have ontology metadata"
        assert 'name' in detailed_data['ontology'], "Detailed should have ontology name"
        assert 'version' in detailed_data['ontology'], "Detailed should have version"
        assert 'generated' in detailed_data['ontology'], "Detailed should have timestamp"
        
        # Verify detailed entities have full structure
        first_entity = detailed_data['entities'][0]
        assert 'class' in first_entity, "Detailed entity should have class name"
        assert 'label' in first_entity, "Detailed entity should have label"
        assert 'description' in first_entity, "Detailed entity should have description"
        assert 'properties' in first_entity, "Detailed entity should have properties array"
    
    def test_prompt_projection_handles_class_without_properties(self, temp_dir):
        """Test that classes without datatype properties are handled correctly."""
        import json
        
        # Create ontology with class but no properties
        ontology_content = """
@prefix : <http://kairos.example/ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

:SimpleOntology a owl:Ontology ;
    rdfs:label "Simple Ontology" .

:Entity a owl:Class ;
    rdfs:label "Entity" ;
    rdfs:comment "An entity with no properties" .
"""
        
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        onto_file = ontologies_dir / "simple.ttl"
        onto_file.write_text(ontology_content, encoding='utf-8')
        
        output_dir = temp_dir / "output"
        
        run_projections(
            ontologies_path=ontologies_dir,
            catalog_path=None,
            output_path=output_dir,
            target='prompt'
        )
        
        # Read compact file (domain-specific filename based on ontology file name)
        compact_file = output_dir / "prompt" / "simple-context.json"
        compact_data = json.loads(compact_file.read_text(encoding='utf-8'))
        
        # Verify entity exists even without properties
        assert 'Entity' in compact_data['entities'], "Entity should exist"
        entity = compact_data['entities']['Entity']
        
        assert 'description' in entity, "Should have description"
        # Fields may or may not be present when empty - both are acceptable
        if 'fields' in entity:
            assert len(entity['fields']) == 0, "Fields should be empty"
    
    def test_prompt_projection_json_valid_and_parseable(self, temp_dir, sample_ontology):
        """Test that generated JSON is valid and parseable."""
        import json
        
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        onto_file = ontologies_dir / "customer.ttl"
        onto_file.write_text(sample_ontology, encoding='utf-8')
        
        output_dir = temp_dir / "output"
        
        run_projections(
            ontologies_path=ontologies_dir,
            catalog_path=None,
            output_path=output_dir,
            target='prompt'
        )
        
        # Test compact file (domain-specific filename)
        compact_file = output_dir / "prompt" / "customer-context.json"
        compact_content = compact_file.read_text(encoding='utf-8')
        
        # Should parse without errors
        try:
            compact_data = json.loads(compact_content)
        except json.JSONDecodeError as e:
            pytest.fail(f"Compact JSON is invalid: {e}")
        
        # Should be non-empty
        assert len(compact_data) > 0, "Compact JSON should not be empty"
        
        # Test detailed file (domain-specific filename)
        detailed_file = output_dir / "prompt" / "customer-context-detailed.json"
        detailed_content = detailed_file.read_text(encoding='utf-8')
        
        try:
            detailed_data = json.loads(detailed_content)
        except json.JSONDecodeError as e:
            pytest.fail(f"Detailed JSON is invalid: {e}")
        
        assert len(detailed_data) > 0, "Detailed JSON should not be empty"
    
    def test_all_projections_generate_artifacts(self, temp_dir, sample_ontology):
        """Test that all projection types generate artifacts."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        onto_file = ontologies_dir / "customer.ttl"
        onto_file.write_text(sample_ontology, encoding='utf-8')
        
        output_dir = temp_dir / "output"
        
        # Test each projection type
        for target in ['dbt', 'neo4j', 'azure-search', 'a2ui', 'prompt']:
            run_projections(
                ontologies_path=ontologies_dir,
                catalog_path=None,
                output_path=output_dir,
                target=target
            )
            
            target_dir = output_dir / target
            assert target_dir.exists(), f"{target} output directory should exist"
            
            # Count files (recursively)
            files = list(target_dir.rglob("*"))
            file_count = sum(1 for f in files if f.is_file())
            assert file_count > 0, f"{target} should generate at least one file"


class TestIsDomainOntology:
    """Tests for the _is_domain_ontology file filter."""

    def test_regular_domain_file_accepted(self):
        from kairos_ontology.projector import _is_domain_ontology
        assert _is_domain_ontology(Path("ontologies/customer.ttl")) is True
        assert _is_domain_ontology(Path("ontologies/order.ttl")) is True

    def test_silver_ext_file_skipped(self):
        from kairos_ontology.projector import _is_domain_ontology
        assert _is_domain_ontology(Path("ontologies/client-silver-ext.ttl")) is False
        assert _is_domain_ontology(Path("ontologies/party-silver-ext.ttl")) is False

    def test_generic_ext_file_skipped(self):
        from kairos_ontology.projector import _is_domain_ontology
        assert _is_domain_ontology(Path("ontologies/common-ext.ttl")) is False

    def test_underscore_prefix_skipped(self):
        from kairos_ontology.projector import _is_domain_ontology
        assert _is_domain_ontology(Path("ontologies/_master.ttl")) is False
        assert _is_domain_ontology(Path("ontologies/_imports.ttl")) is False

    def test_validator_has_same_filter(self):
        from kairos_ontology.validator import _is_domain_ontology
        assert _is_domain_ontology(Path("ontologies/customer.ttl")) is True
        assert _is_domain_ontology(Path("ontologies/client-silver-ext.ttl")) is False
        assert _is_domain_ontology(Path("ontologies/_master.ttl")) is False

    def test_non_domain_files_excluded_from_projection(self, tmp_path, capsys):
        """Integration test: silver-ext and _master files should not be loaded."""
        ontologies_dir = tmp_path / "ontologies"
        ontologies_dir.mkdir()

        domain_ttl = """
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix ex: <http://example.org/test#> .

        <http://example.org/test> a owl:Ontology ;
            rdfs:label "Test" ;
            owl:versionInfo "1.0" .

        ex:Widget a owl:Class ;
            rdfs:label "Widget" ;
            rdfs:comment "A test widget" .

        ex:widgetName a owl:DatatypeProperty ;
            rdfs:domain ex:Widget ;
            rdfs:range xsd:string ;
            rdfs:label "widget name" .
        """
        (ontologies_dir / "widgets.ttl").write_text(domain_ttl, encoding="utf-8")
        (ontologies_dir / "widgets-silver-ext.ttl").write_text(domain_ttl, encoding="utf-8")
        (ontologies_dir / "_master.ttl").write_text(domain_ttl, encoding="utf-8")

        output_dir = tmp_path / "output"
        run_projections(
            ontologies_path=ontologies_dir,
            catalog_path=None,
            output_path=output_dir,
            target="prompt",
        )

        captured = capsys.readouterr()
        assert "Found 1 ontology file" in captured.out
        assert "widgets.ttl" in captured.out
        assert "silver-ext" not in captured.out
        assert "_master" not in captured.out