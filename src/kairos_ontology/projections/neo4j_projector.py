#!/usr/bin/env python3
"""
Neo4j Projector - Generate Neo4j schema from ontology

Generates:
1. Cypher schema script - Node labels, constraints, indexes
2. Relationship type definitions
3. Sample data model documentation
"""

from pathlib import Path
from typing import Dict, List
from datetime import datetime
from rdflib import Graph, Namespace, RDF, RDFS, OWL
from jinja2 import Environment, FileSystemLoader
from .uri_utils import extract_local_name


class Neo4jProjector:
    """Generate Neo4j Cypher schema from OWL ontology"""
    
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
        """Extract all OWL classes for Neo4j node labels"""
        classes = []
        
        query = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?class ?label ?comment
        WHERE {
            ?class a owl:Class .
            OPTIONAL { ?class rdfs:label ?label }
            OPTIONAL { ?class rdfs:comment ?comment }
        }
        """
        
        for row in self.graph.query(query):
            class_uri = str(row['class'])
            class_name = extract_local_name(class_uri)
            
            # Find ID property (first datatype property with "id" in name)
            id_property = self._find_id_property(class_uri)
            
            classes.append({
                'uri': class_uri,
                'name': class_name,
                'label': str(row.label) if row.label else class_name,
                'description': str(row.comment) if row.comment else f"{class_name} node",
                'constraint_name': f"constraint_{class_name.lower()}_id",
                'id_property': id_property
            })
        
        return classes
    
    def extract_relationships(self) -> List[Dict]:
        """Extract all object properties as Neo4j relationships"""
        relationships = []
        
        query = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?property ?label ?comment ?domain ?range
        WHERE {
            ?property a owl:ObjectProperty .
            OPTIONAL { ?property rdfs:label ?label }
            OPTIONAL { ?property rdfs:comment ?comment }
            OPTIONAL { ?property rdfs:domain ?domain }
            OPTIONAL { ?property rdfs:range ?range }
        }
        """
        
        for row in self.graph.query(query):
            prop_uri = str(row.property)
            prop_name = extract_local_name(prop_uri)
            
            # Convert to SCREAMING_SNAKE_CASE for Neo4j relationship types
            rel_type = self._to_screaming_snake_case(prop_name)
            
            domain_name = extract_local_name(str(row.domain)) if row.domain else "Node"
            range_name = extract_local_name(str(row.range)) if row.range else "Node"
            
            relationships.append({
                'uri': prop_uri,
                'name': rel_type,
                'original_name': prop_name,
                'label': str(row.label) if row.label else prop_name,
                'description': str(row.comment) if row.comment else f"{prop_name} relationship",
                'domain': domain_name,
                'range': range_name
            })
        
        return relationships
    
    def generate_schema(self, classes: List[Dict], relationships: List[Dict]) -> str:
        """Generate Cypher schema script"""
        template = self.jinja_env.get_template('schema.cypher.jinja2')
        
        return template.render(
            ontology_uri=str(self.ontology_path.absolute()),
            timestamp=datetime.now().isoformat(),
            classes=classes,
            relationships=relationships
        )
    
    def project(self) -> Dict[str, str]:
        """
        Execute projection: generate Neo4j schema
        
        Returns:
            Dictionary mapping output file paths to generated content
        """
        classes = self.extract_classes()
        relationships = self.extract_relationships()
        
        schema_content = self.generate_schema(classes, relationships)
        
        return {
            'schema.cypher': schema_content
        }
    
    def save_artifacts(self, artifacts: Dict[str, str]):
        """Save generated artifacts to output directory"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        for file_path, content in artifacts.items():
            output_file = self.output_dir / file_path
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"✅ Generated: {file_path}")
    
    def _find_id_property(self, class_uri: str) -> str:
        """Find the ID property for a class (property name containing 'id')"""
        query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?property
        WHERE {{
            ?property a owl:DatatypeProperty .
            ?property rdfs:domain <{class_uri}> .
        }}
        """
        
        for row in self.graph.query(query):
            prop_name = extract_local_name(str(row.property))
            if 'id' in prop_name.lower():
                return self._to_snake_case(prop_name)
        
        # Default to generic 'id' if no ID property found
        return 'id'
    
    @staticmethod
    def _to_snake_case(name: str) -> str:
        """Convert camelCase to snake_case"""
        import re
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
    
    @staticmethod
    def _to_screaming_snake_case(name: str) -> str:
        """Convert camelCase to SCREAMING_SNAKE_CASE for Neo4j relationships"""
        import re
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        s2 = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1)
        return s2.upper()


def main():
    """CLI entry point for Neo4j projector"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate Neo4j schema from ontology")
    parser.add_argument("--ontology", type=Path, required=True, help="Path to ontology file")
    parser.add_argument("--output", type=Path, default=Path("output/neo4j"), help="Output directory")
    parser.add_argument("--templates", type=Path, default=Path("scripts/templates/neo4j"),
                       help="Template directory")
    
    args = parser.parse_args()
    
    projector = Neo4jProjector(args.ontology, args.output, args.templates)
    artifacts = projector.project()
    projector.save_artifacts(artifacts)
    
    print(f"\n✅ Neo4j projection complete: {len(artifacts)} files generated")


if __name__ == "__main__":
    main()


def generate_neo4j_artifacts(classes: list, graph, template_dir, namespace: str) -> dict:
    """Generate Neo4j artifacts from pre-extracted classes and graph.
    
    Args:
        classes: List of class dictionaries
        graph: RDFLib graph
        template_dir: Path to Jinja2 templates
        namespace: Base namespace
        
    Returns:
        Dictionary of {file_path: content}
    """
    from jinja2 import Environment, FileSystemLoader
    from datetime import datetime
    
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template('schema.cypher.jinja2')
    
    # Add constraint info to classes
    for cls in classes:
        cls['constraint_name'] = f"constraint_{cls['name'].lower()}_id"
        cls['id_property'] = 'id'
    
    content = template.render(
        ontology_uri="ontology",
        timestamp=datetime.now().isoformat(),
        classes=classes,
        relationships=[]
    )
    
    return {'schema.cypher': content}
