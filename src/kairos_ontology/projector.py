"""Projection orchestrator - generates downstream artifacts."""

from pathlib import Path
from rdflib import Graph, Namespace, RDF, RDFS, OWL, XSD, SKOS
from jinja2 import Environment, FileSystemLoader
import json
from datetime import datetime
from .projections.uri_utils import extract_local_name


def run_projections(ontologies_path: Path, catalog_path: Path, output_path: Path, target: str, namespace: str = None):
    """Run projection generation.
    
    Args:
        ontologies_path: Path to ontology files
        catalog_path: Path to XML catalog for imports
        output_path: Where to write generated files
        target: Projection target (dbt, neo4j, etc.) or 'all'
        namespace: Base namespace to project (e.g., 'http://example.org/ont/'). 
                   If None, auto-detects from ontology.
    """
    
    print("🚀 Kairos Ontology Projections")
    print("=" * 50)
    
    # Load all ontologies into merged graph
    print("\nLoading ontologies...")
    merged_graph = Graph()
    
    # Get all ontology files
    ontology_files = list(ontologies_path.glob("**/*.ttl")) + list(ontologies_path.glob("**/*.rdf"))
    
    if not ontology_files:
        print(f"  ⚠️  No ontology files found in {ontologies_path}")
        return
    
    # Load each ontology file
    for onto_file in ontology_files:
        try:
            if catalog_path and catalog_path.exists():
                # Load with catalog support for imports
                from .catalog_utils import load_graph_with_catalog
                file_graph = load_graph_with_catalog(onto_file, catalog_path)
                # Merge into main graph
                for s, p, o in file_graph:
                    merged_graph.add((s, p, o))
            else:
                # Load without catalog
                merged_graph.parse(onto_file, format='turtle' if onto_file.suffix == '.ttl' else 'xml')
            print(f"  ✓ Loaded {onto_file.name}")
        except Exception as e:
            print(f"  ⚠️  Could not parse {onto_file.name}: {e}")
    
    print(f"  Loaded {len(merged_graph)} triples\n")
    
    if len(merged_graph) == 0:
        print("  ⚠️  No triples loaded - check ontology files exist")
        return
    
    # Auto-detect namespace if not provided
    if namespace is None:
        namespace = _auto_detect_namespace(merged_graph)
        print(f"  Auto-detected namespace: {namespace}\n")
    else:
        print(f"  Using namespace: {namespace}\n")
    
    # Create output directories
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Determine template directory
    template_base = Path(__file__).parent / "templates"
    
    targets_to_run = ['dbt', 'neo4j', 'azure-search', 'a2ui', 'prompt'] if target == 'all' else [target]
    
    for target_name in targets_to_run:
        print(f"📦 Generating {target_name} projection...")
        target_output = output_path / target_name
        target_output.mkdir(exist_ok=True)
        
        try:
            artifacts = _run_projection(target_name, merged_graph, target_output, template_base, namespace)
            if artifacts:
                # Save artifacts
                for file_path, content in artifacts.items():
                    output_file = target_output / file_path
                    output_file.parent.mkdir(parents=True, exist_ok=True)
                    output_file.write_text(content, encoding='utf-8')
                
                print(f"  ✓ {target_name} projection completed: {len(artifacts)} files\n")
            else:
                print(f"  ℹ️  {target_name}: No files generated\n")
        except Exception as e:
            import traceback
            print(f"  ✗ {target_name} projection failed: {e}")
            traceback.print_exc()
            print()
    
    print("✅ Projection generation completed!")


def _auto_detect_namespace(graph: Graph) -> str:
    """Auto-detect the ontology's base namespace.
    
    Looks for the most common namespace prefix used in owl:Class definitions,
    excluding standard ontologies (OWL, RDFS, SKOS, etc.).
    """
    query = """
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    
    SELECT ?class
    WHERE {
        ?class a owl:Class .
        FILTER(isIRI(?class))
    }
    """
    
    # Count namespace prefixes
    namespace_counts = {}
    standard_namespaces = {
        'http://www.w3.org/2002/07/owl#',
        'http://www.w3.org/2000/01/rdf-schema#',
        'http://www.w3.org/2004/02/skos/core#',
        'http://www.w3.org/2001/XMLSchema#',
        'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    }
    
    for row in graph.query(query):
        class_uri = str(row['class'])
        
        # Extract namespace (everything up to last # or /)
        if '#' in class_uri:
            namespace = class_uri.rsplit('#', 1)[0] + '#'
        elif '/' in class_uri:
            namespace = class_uri.rsplit('/', 1)[0] + '/'
        else:
            continue
        
        # Skip standard ontologies
        if namespace in standard_namespaces:
            continue
        
        namespace_counts[namespace] = namespace_counts.get(namespace, 0) + 1
    
    if not namespace_counts:
        # Fallback to URN format if no HTTP namespaces found
        return "urn:kairos:ont:core:"
    
    # Return most common namespace
    return max(namespace_counts, key=namespace_counts.get)


def _run_projection(target: str, graph: Graph, output_path: Path, template_base: Path, namespace: str) -> dict:
    """Run a specific projection type using simplified logic."""
    
    query = """
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    
    SELECT ?class ?label ?comment
    WHERE {
        ?class a owl:Class .
        OPTIONAL { ?class rdfs:label ?label }
        OPTIONAL { ?class rdfs:comment ?comment }
        FILTER(isIRI(?class))
    }
    """
    
    classes = []
    for row in graph.query(query):
        class_uri = str(row['class'])
        if not class_uri.startswith(namespace):
            continue
        
        class_name = extract_local_name(class_uri)
        classes.append({
            'uri': class_uri,
            'name': class_name,
            'label': str(row.label) if row.label else class_name,
            'comment': str(row.comment) if row.comment else f"{class_name} entity"
        })
    
    if not classes:
        print(f"  ℹ️  No classes found with namespace: {namespace}")
        return {}
    
    print(f"  Found {len(classes)} classes")
    
    # Generate based on target
    if target == 'dbt':
        return _generate_dbt(classes, graph, template_base / "dbt")
    elif target == 'neo4j':
        return _generate_neo4j(classes, graph, template_base / "neo4j")
    elif target == 'azure-search':
        return _generate_azure_search(classes, graph, template_base / "azure-search")
    elif target == 'a2ui':
        return _generate_a2ui(classes, graph, template_base / "a2ui")
    elif target == 'prompt':
        return _generate_prompt(classes, graph, template_base / "prompt")
    
    return {}


def _generate_dbt(classes, graph, template_dir):
    """Simple DBT generation."""
    artifacts = {}
    env = Environment(loader=FileSystemLoader(template_dir))
    
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
            column_name = _to_snake_case(prop_name)
            sql_type = "STRING"  # Default
            
            properties.append({
                'name': prop_name,
                'column_name': column_name,
                'sql_type': sql_type,
                'sql_cast': f"CAST({column_name}_raw AS {sql_type})",
                'label': str(row.label) if row.label else prop_name,
                'comment': str(row.comment) if row.comment else ""
            })
        
        if not properties:
            continue
        
        # Generate SQL
        template = env.get_template('model.sql.jinja2')
        sql_content = template.render(
            class_name=class_info['name'],
            ontology_uri="ontology",
            description=class_info['comment'],
            properties=properties
        )
        artifacts[f"models/silver/{class_info['name'].lower()}.sql"] = sql_content
    
    return artifacts


def _generate_neo4j(classes, graph, template_dir):
    """Simple Neo4j generation."""
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template('schema.cypher.jinja2')
    
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


def _generate_azure_search(classes, graph, template_dir):
    """Simple Azure Search generation."""
    return {}  # Simplified for now


def _generate_a2ui(classes, graph, template_dir):
    """Simple A2UI generation."""
    return {}  # Simplified for now


def _generate_prompt(classes, graph, template_dir):
    """Simple Prompt generation."""
    return {}  # Simplified for now


def _to_snake_case(name: str) -> str:
    """Convert camelCase to snake_case."""
    import re
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
