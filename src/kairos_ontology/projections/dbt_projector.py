#!/usr/bin/env python3
"""
DBT Projector - Generate DBT models from ontology classes

Generates:
1. SQL model files (.sql) - CREATE TABLE statements
2. Schema YAML files - Column descriptions and metadata
3. DBT tests - Data quality tests from SHACL constraints

INHERITANCE PATTERN (Single Table Inheritance):
----------------------------------------------
When a class has subclasses with NO unique properties, we generate a SINGLE table
for the parent class with a discriminator column instead of separate tables.

Why?
- Avoids table proliferation in the data warehouse
- Simplifies querying (no UNION needed across tables)
- Standard data warehouse pattern for type hierarchies
- Ontology preserves semantic hierarchy; DBT gets practical structure

Example:
  Service (parent) -> ConsultingService, TechnicalService (subclasses)
  
  Instead of 3 tables, generate 1 table with:
    service_id, service_name, service_type (discriminator), ...
    
Subclasses are only materialized as separate tables if they have:
  1. Unique properties not in parent class
  2. Significantly different structure requiring separate schema
"""

from pathlib import Path
from typing import Dict, List, Set, Tuple
from rdflib import Graph, Namespace, RDF, RDFS, OWL, XSD
from jinja2 import Environment, FileSystemLoader


class DBTProjector:
    """Generate DBT models, schemas, and tests from OWL ontology"""
    
    # XSD to SQL datatype mapping
    XSD_TO_SQL_TYPES = {
        XSD.string: "STRING",
        XSD.integer: "INT64",
        XSD.int: "INT64",
        XSD.decimal: "NUMERIC",
        XSD.float: "FLOAT64",
        XSD.double: "FLOAT64",
        XSD.boolean: "BOOL",
        XSD.date: "DATE",
        XSD.dateTime: "TIMESTAMP",
        XSD.time: "TIME",
    }
    
    def __init__(self, ontology_path: Path, output_dir: Path, template_dir: Path):
        self.ontology_path = ontology_path
        self.output_dir = output_dir
        self.template_dir = template_dir
        
        # Load ontology
        self.graph = Graph()
        self.graph.parse(ontology_path, format='turtle')
        
        # Setup Jinja2
        self.jinja_env = Environment(loader=FileSystemLoader(template_dir))
        
        # Namespaces
        self.KAIROS = Namespace("urn:kairos:ont:core:")
        
    def extract_classes(self) -> List[Dict]:
        """
        Extract all OWL classes from ontology.
        
        Filters out:
        - Anonymous/blank node classes (used in unionOf, intersectionOf, etc.)
        - External ontology classes (not from the Kairos namespace)
        """
        classes = []
        
        query = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?class ?label ?comment ?parent
        WHERE {
            ?class a owl:Class .
            OPTIONAL { ?class rdfs:label ?label }
            OPTIONAL { ?class rdfs:comment ?comment }
            OPTIONAL { ?class rdfs:subClassOf ?parent . FILTER(isIRI(?parent)) }
            # Exclude blank nodes (anonymous classes from unionOf, intersectionOf, etc.)
            FILTER(isIRI(?class))
        }
        """
        
        for row in self.graph.query(query):
            class_uri = str(row['class'])
            
            # Skip classes from external ontologies (FIBO, etc.)
            if not class_uri.startswith('urn:kairos:ont:'):
                continue
            
            class_name = class_uri.split('#')[-1]
            
            classes.append({
                'uri': class_uri,
                'name': class_name,
                'label': str(row.label) if row.label else class_name,
                'comment': str(row.comment) if row.comment else f"{class_name} entity",
                'parent_uri': str(row.parent) if row.parent else None
            })
        
        return classes
    
    def get_subclasses(self, class_uri: str) -> List[str]:
        """Get all direct subclasses of a class"""
        query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        
        SELECT ?subclass ?label
        WHERE {{
            ?subclass a owl:Class .
            ?subclass rdfs:subClassOf <{class_uri}> .
            OPTIONAL {{ ?subclass rdfs:label ?label }}
        }}
        """
        
        subclasses = []
        for row in self.graph.query(query):
            subclass_uri = str(row.subclass)
            subclass_name = subclass_uri.split('#')[-1]
            subclasses.append({
                'uri': subclass_uri,
                'name': subclass_name,
                'label': str(row.label) if row.label else subclass_name
            })
        
        return subclasses
    
    def has_unique_properties(self, class_uri: str, parent_uri: str = None) -> bool:
        """Check if a class has properties not defined on its parent"""
        class_props = self.extract_properties(class_uri)
        
        if not parent_uri:
            # No parent, so all properties are "unique"
            return len(class_props) > 0
        
        parent_props = self.extract_properties(parent_uri)
        parent_prop_uris = {p['uri'] for p in parent_props}
        
        # Check if any properties are not in parent
        for prop in class_props:
            if prop['uri'] not in parent_prop_uris:
                return True
        
        return False
    
    def extract_properties(self, class_uri: str) -> List[Dict]:
        """Extract all properties for a given class"""
        properties = []
        
        # Query for datatype properties with this class as domain
        query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?property ?label ?comment ?range
        WHERE {{
            ?property a owl:DatatypeProperty .
            ?property rdfs:domain <{class_uri}> .
            OPTIONAL {{ ?property rdfs:label ?label }}
            OPTIONAL {{ ?property rdfs:comment ?comment }}
            OPTIONAL {{ ?property rdfs:range ?range }}
        }}
        """
        
        for row in self.graph.query(query):
            prop_uri = str(row.property)
            prop_name = prop_uri.split('#')[-1]
            
            # Map XSD datatype to SQL type
            range_type = row.range if row.range else XSD.string
            sql_type = self.XSD_TO_SQL_TYPES.get(range_type, "STRING")
            
            # Convert property name to snake_case column name
            column_name = self._to_snake_case(prop_name)
            
            properties.append({
                'uri': prop_uri,
                'name': prop_name,
                'column_name': column_name,
                'label': str(row.label) if row.label else prop_name,
                'comment': str(row.comment) if row.comment else "",
                'range': str(range_type),
                'sql_type': sql_type,
                'sql_cast': f"CAST({column_name}_raw AS {sql_type})"
            })
        
        return properties
    
    def extract_shacl_tests(self, class_uri: str, shapes_path: Path) -> Dict[str, List[str]]:
        """Extract DBT tests from SHACL shapes"""
        if not shapes_path.exists():
            return {}
        
        shapes_graph = Graph()
        shapes_graph.parse(shapes_path, format='turtle')
        
        SH = Namespace("http://www.w3.org/ns/shacl#")
        tests_by_property = {}
        
        # Find shape for this class
        class_name = class_uri.split('#')[-1]
        shape_uri = f"http://kairos.ai/ont/core#{class_name}Shape"
        
        # Query for property shapes
        for property_shape in shapes_graph.objects(predicate=SH.property):
            path = shapes_graph.value(property_shape, SH.path)
            if not path:
                continue
            
            prop_name = str(path).split('#')[-1]
            column_name = self._to_snake_case(prop_name)
            tests = []
            
            # Check for minCount (not_null)
            min_count = shapes_graph.value(property_shape, SH.minCount)
            if min_count and int(min_count) > 0:
                tests.append("not_null")
            
            # Check for pattern (regex)
            pattern = shapes_graph.value(property_shape, SH.pattern)
            if pattern:
                tests.append(f"dbt_utils.accepted_values")
            
            # Check for uniqueness
            # (SHACL doesn't have direct unique, but we can infer from maxCount=1 on inverse)
            
            if tests:
                tests_by_property[column_name] = tests
        
        return tests_by_property
    
    def generate_sql_model(self, class_info: Dict, properties: List[Dict], 
                           subclasses: List[Dict] = None, discriminator: Dict = None) -> str:
        """Generate SQL model file for a class"""
        template = self.jinja_env.get_template('model.sql.jinja2')
        
        return template.render(
            class_name=class_info['name'],
            ontology_uri=str(self.ontology_path.absolute()),
            description=class_info['comment'],
            properties=properties,
            subclasses=subclasses,
            discriminator=discriminator
        )
    
    def generate_schema_yaml(self, class_info: Dict, properties: List[Dict], tests: Dict) -> str:
        """Generate schema.yml for a class"""
        template = self.jinja_env.get_template('schema.yml.jinja2')
        
        # Add tests to columns
        columns = []
        for prop in properties:
            column_tests = tests.get(prop['column_name'], [])
            columns.append({
                'name': prop['column_name'],
                'description': prop['comment'] or prop['label'],
                'data_type': prop['sql_type'],
                'tests': column_tests
            })
        
        return template.render(
            model_name=class_info['name'].lower(),
            description=class_info['comment'],
            columns=columns
        )
    
    def project(self, shapes_path: Path = None) -> Dict[str, str]:
        """
        Execute projection: generate all DBT artifacts
        
        Implements SINGLE TABLE INHERITANCE pattern:
        - Parent classes with subclasses that have no unique properties get ONE table
        - Discriminator column added to indicate the specific subtype
        - Only materializes subclasses as separate tables if they have unique properties
        
        Returns:
            Dictionary mapping output file paths to generated content
        """
        artifacts = {}
        classes = self.extract_classes()
        
        # Build class hierarchy map
        classes_by_uri = {c['uri']: c for c in classes}
        processed_classes = set()
        
        for class_info in classes:
            class_uri = class_info['uri']
            
            # Skip if already processed as part of hierarchy
            if class_uri in processed_classes:
                continue
            
            # Check if this class has subclasses
            subclasses = self.get_subclasses(class_uri)
            
            if subclasses:
                # Check if ANY subclass has unique properties
                has_specialized_subclass = any(
                    self.has_unique_properties(sub['uri'], class_uri) 
                    for sub in subclasses
                )
                
                if not has_specialized_subclass:
                    # SINGLE TABLE INHERITANCE: Generate one table for parent with discriminator
                    print(f"ℹ️  Single-table inheritance: {class_info['name']} includes {len(subclasses)} subclasses")
                    
                    # Extract properties from parent
                    properties = self.extract_properties(class_uri)
                    
                    # Extract SHACL tests if shapes file provided
                    tests = {}
                    if shapes_path:
                        tests = self.extract_shacl_tests(class_uri, shapes_path)
                    
                    # Add discriminator column
                    discriminator_column = {
                        'column_name': f"{self._to_snake_case(class_info['name'])}_type",
                        'label': f"{class_info['label']} Type",
                        'comment': f"Discriminator column for {class_info['name']} subclasses",
                        'sql_type': 'STRING',
                        'sql_cast': None  # Will be handled in template
                    }
                    
                    # Generate SQL model with subclasses info
                    sql_content = self.generate_sql_model(
                        class_info, 
                        properties,
                        subclasses=subclasses,
                        discriminator=discriminator_column
                    )
                    sql_file = f"models/silver/{class_info['name'].lower()}.sql"
                    artifacts[sql_file] = sql_content
                    
                    # Generate schema YAML with discriminator
                    properties_with_discriminator = properties + [discriminator_column]
                    yaml_content = self.generate_schema_yaml(class_info, properties_with_discriminator, tests)
                    yaml_file = f"models/silver/schema_{class_info['name'].lower()}.yml"
                    artifacts[yaml_file] = yaml_content
                    
                    # Mark parent and all subclasses as processed
                    processed_classes.add(class_uri)
                    for sub in subclasses:
                        processed_classes.add(sub['uri'])
                    
                    continue
            
            # Check if this is a subclass without unique properties
            parent_uri = class_info.get('parent_uri')
            if parent_uri and parent_uri in classes_by_uri:
                if not self.has_unique_properties(class_uri, parent_uri):
                    # Skip - will be handled by parent's single-table inheritance
                    print(f"ℹ️  Skipping {class_info['name']} (no unique properties, included in parent table)")
                    processed_classes.add(class_uri)
                    continue
            
            # STANDARD CASE: Generate separate table
            properties = self.extract_properties(class_uri)
            
            # Extract SHACL tests if shapes file provided
            tests = {}
            if shapes_path:
                tests = self.extract_shacl_tests(class_uri, shapes_path)
            
            # Generate SQL model
            sql_content = self.generate_sql_model(class_info, properties)
            sql_file = f"models/silver/{class_info['name'].lower()}.sql"
            artifacts[sql_file] = sql_content
            
            # Generate schema YAML
            yaml_content = self.generate_schema_yaml(class_info, properties, tests)
            yaml_file = f"models/silver/schema_{class_info['name'].lower()}.yml"
            artifacts[yaml_file] = yaml_content
            
            processed_classes.add(class_uri)
        
        return artifacts
    
    def save_artifacts(self, artifacts: Dict[str, str]):
        """Save generated artifacts to output directory"""
        for file_path, content in artifacts.items():
            output_file = self.output_dir / file_path
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"✅ Generated: {file_path}")
    
    @staticmethod
    def _to_snake_case(name: str) -> str:
        """Convert camelCase or PascalCase to snake_case"""
        import re
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


def main():
    """CLI entry point for DBT projector"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate DBT models from ontology")
    parser.add_argument("--ontology", type=Path, required=True, help="Path to ontology file")
    parser.add_argument("--shapes", type=Path, help="Path to SHACL shapes file (optional)")
    parser.add_argument("--output", type=Path, default=Path("output/dbt"), help="Output directory")
    parser.add_argument("--templates", type=Path, default=Path("scripts/templates/dbt"), 
                       help="Template directory")
    
    args = parser.parse_args()
    
    projector = DBTProjector(args.ontology, args.output, args.templates)
    artifacts = projector.project(args.shapes)
    projector.save_artifacts(artifacts)
    
    print(f"\n✅ DBT projection complete: {len(artifacts)} files generated")


if __name__ == "__main__":
    main()
