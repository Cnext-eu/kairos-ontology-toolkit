# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
#!/usr/bin/env python3
"""
A2UI Protocol Projector - Generate JSON Schema for Agent-to-UI messages

Generates JSON Schema definitions for message types based on ontology classes.
"""

from pathlib import Path
from typing import Dict, List
from rdflib import Graph, Namespace, XSD
from jinja2 import Environment, FileSystemLoader
from .uri_utils import extract_local_name


class A2UIProjector:
    """Generate A2UI JSON Schema from OWL ontology"""
    
    # XSD to JSON Schema type mapping
    XSD_TO_JSON_TYPES = {
        XSD.string: "string",
        XSD.integer: "integer",
        XSD.int: "integer",
        XSD.decimal: "number",
        XSD.float: "number",
        XSD.double: "number",
        XSD.boolean: "boolean",
        XSD.date: "string",  # with format
        XSD.dateTime: "string",  # with format
    }
    
    def __init__(self, ontology_path: Path, output_dir: Path, template_dir: Path,
                 shapes_dir: Path = None):
        self.ontology_path = ontology_path
        self.output_dir = output_dir
        self.template_dir = template_dir
        self.shapes_dir = shapes_dir or (ontology_path.parent.parent / "shapes")
        
        # Load ontology
        self.graph = Graph()
        self.graph.parse(ontology_path, format='turtle')
        
        # Setup Jinja2
        self.jinja_env = Environment(loader=FileSystemLoader(template_dir))
        
        # Namespaces
        self.KAIROS = Namespace("urn:kairos:ont:core:")
    
    def extract_classes(self) -> List[Dict]:
        """Extract all OWL classes for message schema generation"""
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
            
            classes.append({
                'uri': class_uri,
                'name': class_name,
                'label': str(row.label) if row.label else class_name,
                'description': str(row.comment) if row.comment else f"{class_name} message payload"
            })
        
        return classes
    
    def extract_properties(self, class_uri: str) -> tuple[List[Dict], List[str]]:
        """
        Extract properties for JSON Schema
        
        Returns:
            Tuple of (properties list, required fields list)
        """
        properties = []
        required = []
        
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
        
        # Also check SHACL for required fields
        shapes_path = self.shapes_dir / (extract_local_name(class_uri).lower() + ".shacl.ttl")
        required_props = self._get_required_properties(class_uri, shapes_path)
        
        for row in self.graph.query(query):
            prop_uri = str(row.property)
            prop_name = extract_local_name(prop_uri)
            
            # Map XSD datatype to JSON Schema type
            range_type = row.range if row.range else XSD.string
            json_type = self.XSD_TO_JSON_TYPES.get(range_type, "string")
            
            # Determine if this is a date/time field for format annotation
            json_format = None
            if range_type == XSD.date:
                json_format = "date"
            elif range_type == XSD.dateTime:
                json_format = "date-time"
            
            # Get pattern from SHACL if exists
            pattern = None  # TODO: Extract from SHACL shapes
            
            prop_data = {
                'name': self._to_camel_case(prop_name),
                'json_type': json_type,
                'description': str(row.comment) if row.comment else "",
                'format': json_format,
                'pattern': pattern
            }
            
            properties.append(prop_data)
            
            # Check if required
            if prop_name in required_props:
                required.append(self._to_camel_case(prop_name))
        
        return properties, required
    
    def _get_required_properties(self, class_uri: str, shapes_path: Path) -> List[str]:
        """Extract required property names from SHACL shapes"""
        if not shapes_path.exists():
            return []
        
        try:
            shapes_graph = Graph()
            shapes_graph.parse(shapes_path, format='turtle')
            
            SH = Namespace("http://www.w3.org/ns/shacl#")
            required_props = []
            
            for property_shape in shapes_graph.objects(predicate=SH.property):
                path = shapes_graph.value(property_shape, SH.path)
                min_count = shapes_graph.value(property_shape, SH.minCount)
                
                if path and min_count and int(min_count) > 0:
                    prop_name = extract_local_name(str(path))
                    required_props.append(prop_name)
            
            return required_props
        except Exception:
            return []
    
    def generate_message_schema(self, class_info: Dict, properties: List[Dict],
                               required: List[str]) -> str:
        """Generate JSON Schema for a message type"""
        template = self.jinja_env.get_template('message-schema.json.jinja2')
        
        schema_id = f"https://kairos.ai/schemas/a2ui/{class_info['name']}.json"
        
        return template.render(
            schema_id=schema_id,
            title=f"{class_info['label']} Message",
            description=class_info['description'],
            properties=properties,
            required=required
        )
    
    def project(self) -> Dict[str, str]:
        """
        Execute projection: generate A2UI message schemas
        
        Returns:
            Dictionary mapping output file paths to generated content
        """
        artifacts = {}
        classes = self.extract_classes()
        
        for class_info in classes:
            # Extract properties
            properties, required = self.extract_properties(class_info['uri'])
            
            # Generate message schema
            schema_content = self.generate_message_schema(class_info, properties, required)
            schema_file = f"schemas/{class_info['name']}.schema.json"
            artifacts[schema_file] = schema_content
        
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
    def _to_camel_case(name: str) -> str:
        """Convert snake_case or PascalCase to camelCase"""
        import re
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        snake = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        
        parts = snake.split('_')
        return parts[0] + ''.join(word.capitalize() for word in parts[1:])


def main() -> None:
    """CLI entry point for A2UI projector"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate A2UI message schemas from ontology")
    parser.add_argument("--ontology", type=Path, required=True, help="Path to ontology file")
    parser.add_argument("--output", type=Path, default=Path("output/a2ui"),
                       help="Output directory")
    parser.add_argument("--templates", type=Path, default=Path("scripts/templates/a2ui"),
                       help="Template directory")
    
    args = parser.parse_args()
    
    projector = A2UIProjector(args.ontology, args.output, args.templates)
    artifacts = projector.project()
    projector.save_artifacts(artifacts)
    
    print(f"\n✅ A2UI projection complete: {len(artifacts)} files generated")


if __name__ == "__main__":
    main()


def generate_a2ui_artifacts(classes: list, graph, template_dir, namespace: str, ontology_name: str = None, ontology_metadata: dict = None) -> dict:
    """Generate A2UI artifacts from pre-extracted classes and graph.
    
    Args:
        classes: List of class dictionaries
        graph: RDFLib graph
        template_dir: Path to Jinja2 templates
        namespace: Base namespace
        ontology_name: Name of the ontology file (domain name) for organizing outputs
        
    Returns:
        Dictionary of {file_path: content}
    """
    from jinja2 import Environment, FileSystemLoader
    from pathlib import Path
    from .uri_utils import extract_local_name
    
    # Setup Jinja2 environment
    meta = ontology_metadata or {}
    template_dir_path = Path(template_dir) if not isinstance(template_dir, Path) else template_dir
    jinja_env = Environment(loader=FileSystemLoader(str(template_dir_path)))
    
    # XSD to JSON Schema type mapping
    XSD_TO_JSON_TYPES = {
        str(XSD.string): "string",
        str(XSD.integer): "integer",
        str(XSD.int): "integer",
        str(XSD.decimal): "number",
        str(XSD.float): "number",
        str(XSD.double): "number",
        str(XSD.boolean): "boolean",
        str(XSD.date): "string",
        str(XSD.dateTime): "string",
    }
    
    def to_camel_case(name: str) -> str:
        """Convert snake_case or PascalCase to camelCase"""
        import re
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        snake = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        parts = snake.split('_')
        return parts[0] + ''.join(word.capitalize() for word in parts[1:])
    
    artifacts = {}
    
    for cls in classes:
        # Extract properties for this class
        properties = []
        required = []
        
        query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?property ?label ?comment ?range
        WHERE {{
            ?property a owl:DatatypeProperty .
            ?property rdfs:domain <{cls['uri']}> .
            OPTIONAL {{ ?property rdfs:label ?label }}
            OPTIONAL {{ ?property rdfs:comment ?comment }}
            OPTIONAL {{ ?property rdfs:range ?range }}
        }}
        """
        
        for row in graph.query(query):
            prop_uri = str(row.property)
            prop_name = extract_local_name(prop_uri)
            
            # Map XSD datatype to JSON Schema type
            range_type = str(row.range) if row.range else str(XSD.string)
            json_type = XSD_TO_JSON_TYPES.get(range_type, "string")
            
            # Determine format for date/time fields
            json_format = None
            if range_type == str(XSD.date):
                json_format = "date"
            elif range_type == str(XSD.dateTime):
                json_format = "date-time"
            
            properties.append({
                'name': to_camel_case(prop_name),
                'json_type': json_type,
                'description': str(row.comment) if row.comment else "",
                'format': json_format,
                'pattern': None
            })
        
        # Generate message schema
        schema_template = jinja_env.get_template('message-schema.json.jinja2')
        schema_id = f"https://kairos.ai/schemas/a2ui/{cls['name']}.json"
        
        schema_content = schema_template.render(
            schema_id=schema_id,
            title=f"{cls.get('label', cls['name'])} Message",
            description=cls.get('comment', f"{cls['name']} message payload"),
            properties=properties,
            required=required,
            ontology_metadata=meta,
        )
        
        # Use domain-specific directory if ontology_name provided
        schema_dir = f"{ontology_name}/schemas" if ontology_name else "schemas"
        
        artifacts[f"{schema_dir}/{cls['name']}.schema.json"] = schema_content
    
    return artifacts
