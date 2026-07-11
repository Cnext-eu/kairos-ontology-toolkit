# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
#!/usr/bin/env python3
"""
Prompt Context Projector - Generate LLM prompt context from ontology

Generates JSON packages containing ontology concepts with synonyms
for use in AI agent prompts. Supports multiple output templates.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from rdflib import Graph, Namespace
from jinja2 import Environment, FileSystemLoader
from .skos_utils import SKOSParser
from .uri_utils import extract_local_name


class PromptProjector:
    """Generate prompt context packages from OWL ontology"""
    
    AVAILABLE_TEMPLATES = ['compact', 'verbose']
    
    def __init__(self, ontology_path: Path, output_dir: Path, template_dir: Path,
                 mappings_dir: Path = None, templates: List[str] = None):
        self.ontology_path = ontology_path
        self.output_dir = output_dir
        self.template_dir = template_dir
        self.templates_to_use = templates or ['compact']
        
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
    
    def extract_concepts(self) -> List[Dict]:
        """Extract all OWL classes as concepts with metadata"""
        concepts = []
        all_synonyms = self.skos_parser.get_all_synonyms(self.skos_graph)
        
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
            
            # Get properties for this class
            properties = self._extract_properties(class_uri)
            
            # Get SKOS synonyms
            synonyms = all_synonyms.get(class_name, [])
            
            # Get examples from SKOS
            examples = self._get_examples_from_skos(class_name)
            
            concepts.append({
                'name': class_name,
                'label': str(row.label) if row.label else class_name,
                'description': str(row.comment) if row.comment else f"{class_name} concept",
                'synonyms': synonyms,
                'properties': properties,
                'examples': examples
            })
        
        return concepts
    
    def extract_relationships(self) -> List[Dict]:
        """Extract all object properties as relationships"""
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
            
            domain_name = extract_local_name(str(row.domain)) if row.domain else "Any"
            range_name = extract_local_name(str(row.range)) if row.range else "Any"
            
            relationships.append({
                'name': prop_name,
                'label': str(row.label) if row.label else prop_name,
                'description': str(row.comment) if row.comment else f"{prop_name} relationship",
                'domain': domain_name,
                'range': range_name
            })
        
        return relationships
    
    def _extract_properties(self, class_uri: str) -> List[Dict]:
        """Extract datatype properties for a class"""
        properties = []
        
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
            
            range_type = extract_local_name(str(row.range)) if row.range else "string"
            
            properties.append({
                'name': prop_name,
                'type': range_type,
                'description': str(row.comment) if row.comment else "",
                'range': range_type
            })
        
        return properties
    
    def _get_examples_from_skos(self, class_name: str) -> List[str]:
        """Extract SKOS examples for a class"""
        SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
        
        concept_uri = self.KAIROS[f"{class_name}Concept"]
        examples = []
        
        for example in self.skos_graph.objects(subject=concept_uri, predicate=SKOS.example):
            examples.append(str(example))
        
        return examples
    
    def generate_context(self, template_name: str, concepts: List[Dict],
                        relationships: List[Dict]) -> str:
        """Generate prompt context using specified template"""
        template = self.jinja_env.get_template(f'{template_name}.json.jinja2')
        
        ontology_name = "Kairos Core Ontology"
        version = "1.0.0"  # TODO: Extract from ontology metadata
        description = "Core business entities for the Kairos platform"
        
        return template.render(
            ontology_name=ontology_name,
            version=version,
            timestamp=datetime.now().isoformat(),
            description=description,
            concepts=concepts,
            relationships=relationships
        )
    
    def project(self) -> Dict[str, str]:
        """
        Execute projection: generate prompt context packages
        
        Returns:
            Dictionary mapping output file paths to generated content
        """
        artifacts = {}
        
        # Extract concepts and relationships once
        concepts = self.extract_concepts()
        relationships = self.extract_relationships()
        
        # Generate for each requested template
        for template_name in self.templates_to_use:
            if template_name not in self.AVAILABLE_TEMPLATES:
                print(f"Warning: Unknown template '{template_name}', skipping")
                continue
            
            context_content = self.generate_context(template_name, concepts, relationships)
            context_file = f"prompt-context-{template_name}.json"
            artifacts[context_file] = context_content
        
        return artifacts
    
    def save_artifacts(self, artifacts: Dict[str, str]):
        """Save generated artifacts to output directory"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        for file_path, content in artifacts.items():
            output_file = self.output_dir / file_path
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"✅ Generated: {file_path}")


def main() -> None:
    """CLI entry point for Prompt projector"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate prompt context from ontology")
    parser.add_argument("--ontology", type=Path, required=True, help="Path to ontology file")
    parser.add_argument("--mappings", type=Path, default=Path("ontology-hub/model/mappings"),
                       help="Path to SKOS mappings directory")
    parser.add_argument("--output", type=Path, default=Path("output/prompt"),
                       help="Output directory")
    parser.add_argument("--templates", type=Path, default=Path("scripts/templates/prompt"),
                       help="Template directory")
    parser.add_argument("--template-types", type=str, default="compact,verbose",
                       help="Comma-separated list of template types (compact, verbose)")
    
    args = parser.parse_args()
    
    template_types = [t.strip() for t in args.template_types.split(',')]
    
    projector = PromptProjector(args.ontology, args.output, args.templates,
                               args.mappings, template_types)
    artifacts = projector.project()
    projector.save_artifacts(artifacts)
    
    print(f"\n✅ Prompt projection complete: {len(artifacts)} files generated")


if __name__ == "__main__":
    main()


def generate_prompt_artifacts(classes: list, graph, template_dir, namespace: str, ontology_name: str = None, ontology_metadata: dict = None) -> dict:
    """Generate Prompt artifacts from pre-extracted classes and graph.
    
    Args:
        classes: List of class dictionaries
        graph: RDFLib graph
        template_dir: Path to Jinja2 templates
        namespace: Base namespace
        ontology_name: Name of the ontology file (domain name) for organizing outputs
        
    Returns:
        Dictionary of {file_path: content}
    """
    from datetime import datetime
    from .uri_utils import extract_local_name
    
    # Extract datatype properties for each class
    def get_properties(class_uri: str) -> list:
        """Extract datatype properties for a class"""
        props = []
        prop_query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        
        SELECT ?property ?label ?comment ?range
        WHERE {{
            ?property a owl:DatatypeProperty .
            ?property rdfs:domain <{class_uri}> .
            OPTIONAL {{ ?property rdfs:label ?label }}
            OPTIONAL {{ ?property rdfs:comment ?comment }}
            OPTIONAL {{ ?property rdfs:range ?range }}
        }}
        """
        
        for row in graph.query(prop_query):
            prop_name = extract_local_name(str(row.property))
            range_type = extract_local_name(str(row.range)) if row.range else "string"
            
            # Simplify XSD types for LLM context
            type_map = {
                'string': 'text',
                'integer': 'number',
                'int': 'number',
                'decimal': 'decimal',
                'float': 'decimal',
                'double': 'decimal',
                'boolean': 'boolean',
                'date': 'date',
                'dateTime': 'datetime',
                'time': 'time'
            }
            simple_type = type_map.get(range_type, range_type)
            
            prop_info = {
                'name': prop_name,
                'type': simple_type,
                'description': str(row.comment) if row.comment else str(row.label) if row.label else ""
            }
            props.append(prop_info)
        
        return props
    
    # Build rich concept data
    concepts = []
    for cls in classes:
        # Get properties
        properties = get_properties(cls['uri'])
        
        concept = {
            'name': cls['name'],
            'label': cls.get('label', cls['name']),
            'description': cls.get('comment', ''),
            'properties': properties
        }
        concepts.append(concept)
    
    # Extract relationships (object properties) filtered by namespace
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
    
    for row in graph.query(query):
        prop_uri = str(row.property)
        
        # Only include relationships in our namespace
        if not prop_uri.startswith(namespace):
            continue
        
        prop_name = extract_local_name(prop_uri)
        domain_name = extract_local_name(str(row.domain)) if row.domain else None
        range_name = extract_local_name(str(row.range)) if row.range else None
        
        rel_info = {
            'name': prop_name,
            'from': domain_name,
            'to': range_name,
            'description': str(row.comment) if row.comment else str(row.label) if row.label else ""
        }
        relationships.append(rel_info)
    
    # Create optimized LLM-friendly structure
    
    # Compact format optimized for LLM token efficiency
    llm_context = {
        "domain": "Business Domain Model",
        "entities": {}
    }
    
    # Add entities with properties
    for concept in concepts:
        entity = {
            "description": concept['description'] or concept['label']
        }
        
        # Add properties in compact format
        if concept['properties']:
            entity["fields"] = {
                prop['name']: {
                    "type": prop['type'],
                    "desc": prop['description']
                } if prop['description'] else prop['type']
                for prop in concept['properties']
            }
        
        llm_context["entities"][concept['name']] = entity
    
    # Add relationships in compact format
    if relationships:
        llm_context["relationships"] = [
            {
                "name": rel['name'],
                "from": rel['from'],
                "to": rel['to'],
                "desc": rel['description']
            } if rel['description'] else {
                "name": rel['name'],
                "from": rel['from'],
                "to": rel['to']
            }
            for rel in relationships
        ]
    
    # Generate compact JSON (optimized for LLM context)
    compact_content = json.dumps(llm_context, indent=2, ensure_ascii=False)
    
    # Generate detailed format (for reference/debugging)
    meta = ontology_metadata or {}
    detailed_context = {
        "ontology": {
            "name": meta.get("label") or ontology_name or "Business Domain Ontology",
            "iri": meta.get("iri", ""),
            "version": meta.get("version") or "1.0.0",
            "toolkit_version": meta.get("toolkit_version", ""),
            "generated": meta.get("generated_at") or datetime.now().isoformat(),
        },
        "entities": [
            {
                "class": concept['name'],
                "label": concept['label'],
                "description": concept['description'],
                "properties": concept['properties']
            }
            for concept in concepts
        ],
        "relationships": relationships
    }
    
    detailed_content = json.dumps(detailed_context, indent=2, ensure_ascii=False)
    
    # Use domain-specific filenames if ontology_name provided
    if ontology_name:
        return {
            f'{ontology_name}-context.json': compact_content,
            f'{ontology_name}-context-detailed.json': detailed_content
        }
    else:
        return {
            'ontology-context.json': compact_content,
            'ontology-context-detailed.json': detailed_content
        }

