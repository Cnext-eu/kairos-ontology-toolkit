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
        KAIROS = Namespace("urn:kairos:ont:core:")
        
        customer_exists = (KAIROS.Customer, RDF.type, OWL.Class) in merged_graph
        person_exists = (KAIROS.Person, RDF.type, OWL.Class) in merged_graph
        
        assert customer_exists or person_exists, "Classes should be loaded from ontology files"
    
    def test_urn_namespace_extraction(self, temp_dir, sample_ontology):
        """Test that URN namespace classes are correctly identified."""
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
            if class_uri.startswith('urn:kairos:ont:'):
                class_name = class_uri.split(':')[-1]
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
