#!/usr/bin/env python3
"""
Azure Search Projector - Generate Azure AI Search index definitions

Generates:
1. JSON index definitions with field mappings
2. SKOS-based synonym maps in Solr format
"""

from pathlib import Path
from typing import Dict, List
from rdflib import Graph, Namespace, XSD
from jinja2 import Environment, FileSystemLoader
from .skos_utils import SKOSParser
from .uri_utils import extract_local_name


class AzureSearchProjector:
    """Generate Azure AI Search artifacts from OWL ontology"""
    
    # XSD to Edm (Entity Data Model) type mapping
    XSD_TO_EDM_TYPES = {
        XSD.string: "Edm.String",
        XSD.integer: "Edm.Int64",
        XSD.int: "Edm.Int32",
        XSD.decimal: "Edm.Double",
        XSD.float: "Edm.Single",
        XSD.double: "Edm.Double",
        XSD.boolean: "Edm.Boolean",
        XSD.date: "Edm.DateTimeOffset",
        XSD.dateTime: "Edm.DateTimeOffset",
    }
    
    def __init__(self, ontology_path: Path, output_dir: Path, template_dir: Path,
                 mappings_dir: Path = None):
        self.ontology_path = ontology_path
        self.output_dir = output_dir
        self.template_dir = template_dir
        
        # Load ontology
        self.graph = Graph()
        self.graph.parse(ontology_path, format='turtle')
        
        # Setup Jinja2
        self.jinja_env = Environment(loader=FileSystemLoader(template_dir))
        
        # Setup SKOS parser
        self.skos_parser = SKOSParser(mappings_dir)
        self.skos_graph = self.skos_parser.load_all_mappings()
        
        # Namespaces
        self.KAIROS = Namespace("urn:kairos:ont:core:")
    
    def extract_classes(self) -> List[Dict]:
        """Extract all OWL classes for index creation"""
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
                'comment': str(row.comment) if row.comment else f"{class_name} entity"
            })
        
        return classes
    
    def extract_fields(self, class_uri: str) -> List[Dict]:
        """Extract all properties for a class as search fields"""
        fields = []
        
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
            prop_name = extract_local_name(prop_uri)
            
            # Map XSD datatype to Edm type
            range_type = row.range if row.range else XSD.string
            edm_type = self.XSD_TO_EDM_TYPES.get(range_type, "Edm.String")
            
            # Determine field capabilities
            is_text_field = edm_type == "Edm.String"
            
            fields.append({
                'name': self._to_camel_case(prop_name),
                'edm_type': edm_type,
                'searchable': is_text_field,
                'filterable': True,
                'sortable': not is_text_field,  # Text fields can't be sorted in Azure Search
                'facetable': edm_type in ["Edm.String", "Edm.Int32", "Edm.Int64", "Edm.Boolean"]
            })
        
        return fields
    
    def generate_index_definition(self, class_info: Dict, fields: List[Dict],
                                  synonym_maps: List[str]) -> str:
        """Generate Azure Search index definition JSON"""
        template = self.jinja_env.get_template('index.json.jinja2')
        
        index_name = class_info['name'].lower()
        
        return template.render(
            index_name=index_name,
            service_name="kairos-search",  # Placeholder
            fields=fields,
            synonym_maps=synonym_maps
        )
    
    def generate_synonym_map(self, class_info: Dict, synonyms: List[str]) -> str:
        """Generate Azure Search synonym map JSON"""
        template = self.jinja_env.get_template('synonym-map.json.jinja2')
        
        synonym_map_name = f"{class_info['name'].lower()}-synonyms"
        
        # Generate Solr format synonyms
        solr_line = self.skos_parser.generate_solr_synonyms(
            class_info['name'],
            class_info['label'],
            synonyms
        )
        
        return template.render(
            synonym_map_name=synonym_map_name,
            service_name="kairos-search",  # Placeholder
            synonyms=[solr_line] if solr_line else []
        )
    
    def project(self) -> Dict[str, str]:
        """
        Execute projection: generate Azure Search artifacts
        
        Returns:
            Dictionary mapping output file paths to generated content
        """
        artifacts = {}
        classes = self.extract_classes()
        all_synonyms = self.skos_parser.get_all_synonyms(self.skos_graph)
        
        for class_info in classes:
            # Extract fields
            fields = self.extract_fields(class_info['uri'])
            
            # Get synonyms from SKOS
            synonyms = all_synonyms.get(class_info['name'], [])
            
            # Generate synonym map name for index reference
            synonym_map_names = []
            if synonyms:
                synonym_map_names.append(f"{class_info['name'].lower()}-synonyms")
            
            # Generate index definition
            index_content = self.generate_index_definition(class_info, fields, synonym_map_names)
            index_file = f"indexes/{class_info['name'].lower()}-index.json"
            artifacts[index_file] = index_content
            
            # Generate synonym map if synonyms exist
            if synonyms:
                synonym_content = self.generate_synonym_map(class_info, synonyms)
                synonym_file = f"synonym-maps/{class_info['name'].lower()}-synonyms.json"
                artifacts[synonym_file] = synonym_content
        
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
        # First convert to snake_case if needed
        import re
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        snake = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        
        # Then convert to camelCase
        parts = snake.split('_')
        return parts[0] + ''.join(word.capitalize() for word in parts[1:])


def main():
    """CLI entry point for Azure Search projector"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate Azure Search artifacts from ontology")
    parser.add_argument("--ontology", type=Path, required=True, help="Path to ontology file")
    parser.add_argument("--mappings", type=Path, default=Path("ontology-hub/mappings"),
                       help="Path to SKOS mappings directory")
    parser.add_argument("--output", type=Path, default=Path("output/azure-search"),
                       help="Output directory")
    parser.add_argument("--templates", type=Path, default=Path("scripts/templates/azure-search"),
                       help="Template directory")
    
    args = parser.parse_args()
    
    projector = AzureSearchProjector(args.ontology, args.output, args.templates, args.mappings)
    artifacts = projector.project()
    projector.save_artifacts(artifacts)
    
    print(f"\n✅ Azure Search projection complete: {len(artifacts)} files generated")


if __name__ == "__main__":
    main()


def generate_azure_search_artifacts(classes: list, graph, template_dir, namespace: str, ontology_name: str = None) -> dict:
    """Generate Azure Search artifacts from pre-extracted classes and graph.
    
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
    template_dir_path = Path(template_dir) if not isinstance(template_dir, Path) else template_dir
    jinja_env = Environment(loader=FileSystemLoader(str(template_dir_path)))
    
    # XSD to Edm type mapping
    XSD_TO_EDM_TYPES = {
        str(XSD.string): "Edm.String",
        str(XSD.integer): "Edm.Int64",
        str(XSD.int): "Edm.Int32",
        str(XSD.decimal): "Edm.Double",
        str(XSD.float): "Edm.Single",
        str(XSD.double): "Edm.Double",
        str(XSD.boolean): "Edm.Boolean",
        str(XSD.date): "Edm.DateTimeOffset",
        str(XSD.dateTime): "Edm.DateTimeOffset",
    }
    
    def to_camel_case(name: str) -> str:
        """Convert snake_case or PascalCase to camelCase"""
        import re
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        snake = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        parts = snake.split('_')
        return parts[0] + ''.join(word.capitalize() for word in parts[1:])
    
    artifacts = {}
    
    # Use domain-specific directory if ontology_name provided
    index_dir = f"{ontology_name}/indexes" if ontology_name else "indexes"
    
    for cls in classes:
        # Extract fields for this class
        fields = []
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
            
            # Map XSD datatype to Edm type
            range_type = str(row.range) if row.range else str(XSD.string)
            edm_type = XSD_TO_EDM_TYPES.get(range_type, "Edm.String")
            
            # Determine field capabilities
            is_text_field = edm_type == "Edm.String"
            
            fields.append({
                'name': to_camel_case(prop_name),
                'edm_type': edm_type,
                'searchable': is_text_field,
                'filterable': True,
                'sortable': not is_text_field,
                'facetable': edm_type in ["Edm.String", "Edm.Int32", "Edm.Int64", "Edm.Boolean"]
            })
        
        # Generate index definition
        index_template = jinja_env.get_template('index.json.jinja2')
        index_name = cls['name'].lower()
        
        index_content = index_template.render(
            index_name=index_name,
            service_name="kairos-search",
            fields=fields,
            synonym_maps=[]
        )
        
        artifacts[f"{index_dir}/{index_name}-index.json"] = index_content
    
    return artifacts
