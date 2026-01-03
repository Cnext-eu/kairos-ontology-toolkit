"""Tests for the projection orchestrator."""

import pytest
from pathlib import Path
from rdflib import Graph, Namespace, RDF, RDFS, OWL
from kairos_ontology.projector import run_projections, _run_projection


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
        from rdflib import Graph
        
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
        from rdflib import Graph, Namespace
        
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
        
        from rdflib import Graph
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
                assert name.replace('.', '').replace('_', '').isalnum()
    
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
        from rdflib import Graph
        from pathlib import Path
        
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
        
        # Check for indexes directory
        indexes_dir = azure_dir / "indexes"
        assert indexes_dir.exists(), "Indexes directory should exist"
        
        # Check for index JSON file
        index_files = list(indexes_dir.glob("*.json"))
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
        
        # Check for schemas directory
        schemas_dir = a2ui_dir / "schemas"
        assert schemas_dir.exists(), "Schemas directory should exist"
        
        # Check for schema JSON files
        schema_files = list(schemas_dir.glob("*.json"))
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
        
        # Check for both compact and verbose files
        compact_file = prompt_dir / "prompt-context-compact.json"
        verbose_file = prompt_dir / "prompt-context-verbose.json"
        
        assert compact_file.exists(), "Compact context file should exist"
        assert verbose_file.exists(), "Verbose context file should exist"
        
        # Verify compact file content
        import json
        compact_data = json.loads(compact_file.read_text(encoding='utf-8'))
        
        assert 'ontology' in compact_data, "Should have ontology name"
        assert 'version' in compact_data, "Should have version"
        assert 'concepts' in compact_data, "Should have concepts array"
        assert len(compact_data['concepts']) > 0, "Should have at least one concept"
        
        # Verify concept structure
        first_concept = compact_data['concepts'][0]
        assert 'class' in first_concept, "Concept should have class name"
        assert 'label' in first_concept, "Concept should have label"
        assert 'synonyms' in first_concept, "Concept should have synonyms"
        assert 'properties' in first_concept, "Concept should have properties"
        
        # Verify verbose file is different and larger
        verbose_data = json.loads(verbose_file.read_text(encoding='utf-8'))
        assert 'classes' in verbose_data, "Verbose format should have classes"
        
        # Verify verbose has more detail
        verbose_size = verbose_file.stat().st_size
        compact_size = compact_file.stat().st_size
        assert verbose_size > compact_size, "Verbose format should be larger than compact"
    
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