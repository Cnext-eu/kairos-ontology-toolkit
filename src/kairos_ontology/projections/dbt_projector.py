#!/usr/bin/env python3
"""
DBT Projector - Generate DBT models from ontology classes

Generates:
1. SQL model files (.sql) - CREATE TABLE statements
2. Schema YAML files - Column descriptions and metadata
3. DBT tests - Data quality tests from SHACL constraints

This module provides the generate_dbt_artifacts() function which is called
by the main projector orchestrator to create DBT artifacts from ontology classes.
"""

import re
from pathlib import Path
from typing import Dict, List
from rdflib import Graph, Namespace, XSD
from jinja2 import Environment, FileSystemLoader
from .uri_utils import extract_local_name


def generate_dbt_artifacts(classes: list, graph, template_dir, namespace: str, shapes_dir: Path = None) -> dict:
    """Generate DBT artifacts from pre-extracted classes and graph.
    
    This is the entry point called by the main projector orchestrator.
    
    Args:
        classes: List of class dictionaries with 'uri', 'name', 'label', 'comment'
        graph: RDFLib graph with the ontology
        template_dir: Path to Jinja2 templates
        namespace: Base namespace for filtering (already used to extract classes)
        shapes_dir: Optional path to SHACL shapes directory
        
    Returns:
        Dictionary of {file_path: content} for generated artifacts
    """
    from jinja2 import Environment, FileSystemLoader
    import re
    
    artifacts = {}
    env = Environment(loader=FileSystemLoader(template_dir))
    skipped_classes = []
    
    # XSD to SQL type mapping
    XSD_TO_SQL_TYPES = {
        str(XSD.string): "STRING",
        str(XSD.integer): "INT64",
        str(XSD.int): "INT64",
        str(XSD.decimal): "NUMERIC",
        str(XSD.float): "FLOAT64",
        str(XSD.double): "FLOAT64",
        str(XSD.boolean): "BOOL",
        str(XSD.date): "DATE",
        str(XSD.dateTime): "TIMESTAMP",
        str(XSD.time): "TIME",
    }
    
    def to_snake_case(name: str) -> str:
        """Convert camelCase to snake_case."""
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
    
    def extract_shacl_tests(class_uri: str, properties: list, shapes_dir: Path) -> dict:
        """Extract DBT tests from SHACL shapes."""
        if not shapes_dir or not shapes_dir.exists():
            return {}
        
        class_name = extract_local_name(class_uri)
        shape_file = shapes_dir / f"{class_name.lower()}.shacl.ttl"
        
        if not shape_file.exists():
            return {}
        
        try:
            shapes_graph = Graph()
            shapes_graph.parse(shape_file, format='turtle')
            
            SH = Namespace("http://www.w3.org/ns/shacl#")
            tests_by_property = {}
            
            # Query for all property shapes
            property_shapes_query = """
            PREFIX sh: <http://www.w3.org/ns/shacl#>
            
            SELECT ?propertyShape ?path ?minCount ?maxCount ?pattern ?minLength ?maxLength ?inList
            WHERE {
                ?shape sh:property ?propertyShape .
                ?propertyShape sh:path ?path .
                OPTIONAL { ?propertyShape sh:minCount ?minCount }
                OPTIONAL { ?propertyShape sh:maxCount ?maxCount }
                OPTIONAL { ?propertyShape sh:pattern ?pattern }
                OPTIONAL { ?propertyShape sh:minLength ?minLength }
                OPTIONAL { ?propertyShape sh:maxLength ?maxLength }
                OPTIONAL { ?propertyShape sh:in ?inList }
            }
            """
            
            for row in shapes_graph.query(property_shapes_query):
                if not row.path:
                    continue
                
                prop_name = extract_local_name(str(row.path))
                column_name = to_snake_case(prop_name)
                tests = []
                
                # sh:minCount 1 → not_null test
                if row.minCount and int(row.minCount) > 0:
                    tests.append("not_null")
                
                # sh:pattern → custom regex test (DBT doesn't have built-in regex)
                if row.pattern:
                    pattern_val = str(row.pattern).replace("\\", "\\\\").replace("'", "\\'")
                    tests.append(f"dbt_utils.expression_is_true:\n            expression: 'regexp_contains({column_name}, r\"{pattern_val}\")'")
                
                # sh:in → accepted_values test
                if row.inList:
                    # Parse the RDF list
                    values = []
                    for item in shapes_graph.items(row.inList):
                        values.append(f"'{str(item)}'")
                    if values:
                        tests.append(f"accepted_values:\n            values: [{', '.join(values)}]")
                
                # sh:minLength / sh:maxLength → custom length tests
                if row.minLength:
                    min_len = int(row.minLength)
                    tests.append(f"dbt_utils.expression_is_true:\n            expression: 'length({column_name}) >= {min_len}'")
                
                if row.maxLength:
                    max_len = int(row.maxLength)
                    tests.append(f"dbt_utils.expression_is_true:\n            expression: 'length({column_name}) <= {max_len}'")
                
                if tests:
                    tests_by_property[column_name] = tests
            
            return tests_by_property
        except Exception as e:
            print(f"    WARNING: Could not parse SHACL shapes for {class_name}: {e}")
            return {}
    
    for class_info in classes:
        # Extract properties
        props_query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?property ?label ?comment ?range
        WHERE {{
            ?property a owl:DatatypeProperty .
            ?property rdfs:domain <{class_info['uri']}> .
            OPTIONAL {{ ?property rdfs:label ?label }}
            OPTIONAL {{ ?property rdfs:comment ?comment }}
            OPTIONAL {{ ?property rdfs:range ?range }}
        }}
        """
        
        properties = []
        for row in graph.query(props_query):
            prop_name = extract_local_name(str(row.property))
            column_name = to_snake_case(prop_name)
            
            # Map XSD type to SQL type
            sql_type = "STRING"  # Default
            if row.range:
                sql_type = XSD_TO_SQL_TYPES.get(str(row.range), "STRING")
            
            properties.append({
                'name': prop_name,
                'column_name': column_name,
                'sql_type': sql_type,
                'sql_cast': f"CAST({column_name}_raw AS {sql_type})",
                'label': str(row.label) if row.label else prop_name,
                'comment': str(row.comment) if row.comment else ""
            })
        
        if not properties:
            print(f"  ⚠️  Skipping {class_info['name']}: No datatype properties defined")
            print(f"      (DBT requires datatype properties to generate table columns)")
            print(f"      Tip: Add owl:DatatypeProperty with rdfs:domain <{class_info['uri']}>")
            skipped_classes.append(class_info['name'])
            continue
        
        # Extract SHACL tests if shapes directory provided
        tests = extract_shacl_tests(class_info['uri'], properties, shapes_dir) if shapes_dir else {}
        
        if tests:
            print(f"    Found {sum(len(t) for t in tests.values())} SHACL tests for {class_info['name']}")
        
        # Generate SQL model
        template = env.get_template('model.sql.jinja2')
        sql_content = template.render(
            class_name=class_info['name'],
            ontology_uri="ontology",
            description=class_info['comment'],
            properties=properties
        )
        artifacts[f"models/silver/{class_info['name'].lower()}.sql"] = sql_content
        
        # Generate schema YAML with proper column structure
        columns = []
        for prop in properties:
            column_tests = tests.get(prop['column_name'], [])
            columns.append({
                'name': prop['column_name'],
                'description': prop['comment'] or prop['label'],
                'data_type': prop['sql_type'],
                'tests': column_tests
            })
        
        yaml_template = env.get_template('schema.yml.jinja2')
        yaml_content = yaml_template.render(
            model_name=class_info['name'].lower(),
            description=class_info['comment'],
            columns=columns
        )
        artifacts[f"models/silver/schema_{class_info['name'].lower()}.yml"] = yaml_content
    
    # Print summary
    if skipped_classes:
        print(f"\n  ⚠️  Skipped {len(skipped_classes)} class(es) with no datatype properties:")
        for class_name in skipped_classes:
            print(f"      - {class_name}")
        print(f"      These classes only have object properties or no properties defined.")
    
    return artifacts
