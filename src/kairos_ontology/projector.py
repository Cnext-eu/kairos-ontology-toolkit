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
    """Auto-detect the ontology's base namespace using semantic web best practices.
    
    Method 1: Check owl:Ontology declaration (preferred - semantic web standard)
    Method 2: Exclude owl:imports and count classes in remaining namespaces
    Method 3: Fallback to URN format
    
    This approach scales to any external ontology without hardcoded exclusion lists.
    """
    
    # Method 1: Look for owl:Ontology declaration (BEST PRACTICE)
    # The namespace containing the owl:Ontology instance is the main ontology namespace
    ontology_query = """
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    
    SELECT ?ontology
    WHERE {
        ?ontology a owl:Ontology .
    }
    """
    
    # Standard W3C namespaces to always exclude
    standard_namespaces = {
        'http://www.w3.org/2002/07/owl#',
        'http://www.w3.org/2000/01/rdf-schema#',
        'http://www.w3.org/2004/02/skos/core#',
        'http://www.w3.org/2001/XMLSchema#',
        'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    }
    
    ontology_namespaces = []
    for row in graph.query(ontology_query):
        onto_uri = str(row['ontology'])
        
        # Extract namespace from ontology URI
        if '#' in onto_uri:
            namespace = onto_uri.rsplit('#', 1)[0] + '#'
        elif '/' in onto_uri:
            namespace = onto_uri.rsplit('/', 1)[0] + '/'
        else:
            namespace = onto_uri + ':'  # URN format
        
        # Skip standard W3C ontologies
        if namespace not in standard_namespaces:
            ontology_namespaces.append(namespace)
    
    # Method 2: Get imported ontology namespaces to exclude
    imports_query = """
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    
    SELECT ?imported
    WHERE {
        ?ontology owl:imports ?imported .
    }
    """
    
    imported_namespaces = set()
    for row in graph.query(imports_query):
        import_uri = str(row['imported'])
        
        # Extract namespace from import URI
        if '#' in import_uri:
            namespace = import_uri.rsplit('#', 1)[0] + '#'
        elif '/' in import_uri:
            namespace = import_uri.rsplit('/', 1)[0] + '/'
        else:
            namespace = import_uri + ':'
        
        imported_namespaces.add(namespace)
    
    # If we found owl:Ontology declarations, prefer the one that's NOT imported
    if ontology_namespaces:
        for onto_ns in ontology_namespaces:
            # Check if this ontology namespace is NOT in the imports
            if onto_ns not in imported_namespaces:
                return onto_ns
        
        # If all ontology namespaces are imported (rare), return the first one
        return ontology_namespaces[0]
    
    # Method 3: Fallback - count classes per namespace, excluding imports and standards
    class_query = """
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    
    SELECT ?class
    WHERE {
        ?class a owl:Class .
        FILTER(isIRI(?class))
    }
    """
    
    namespace_counts = {}
    for row in graph.query(class_query):
        class_uri = str(row['class'])
        
        # Extract namespace
        if '#' in class_uri:
            namespace = class_uri.rsplit('#', 1)[0] + '#'
        elif '/' in class_uri:
            namespace = class_uri.rsplit('/', 1)[0] + '/'
        else:
            namespace = class_uri.rsplit(':', 1)[0] + ':'
        
        # Skip standard W3C namespaces
        if namespace in standard_namespaces:
            continue
        
        # Skip imported namespaces
        if namespace in imported_namespaces:
            continue
        
        namespace_counts[namespace] = namespace_counts.get(namespace, 0) + 1
    
    if namespace_counts:
        # Return namespace with most classes
        return max(namespace_counts, key=namespace_counts.get)
    
    # Ultimate fallback
    return "urn:kairos:ont:core:"


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
    
    # Generate based on target using full-featured projector classes
    if target == 'dbt':
        from .projections.dbt_projector import generate_dbt_artifacts
        return generate_dbt_artifacts(classes, graph, template_base / "dbt", namespace)
    elif target == 'neo4j':
        from .projections.neo4j_projector import generate_neo4j_artifacts
        return generate_neo4j_artifacts(classes, graph, template_base / "neo4j", namespace)
    elif target == 'azure-search':
        from .projections.azure_search_projector import generate_azure_search_artifacts
        return generate_azure_search_artifacts(classes, graph, template_base / "azure-search", namespace)
    elif target == 'a2ui':
        from .projections.a2ui_projector import generate_a2ui_artifacts
        return generate_a2ui_artifacts(classes, graph, template_base / "a2ui", namespace)
    elif target == 'prompt':
        from .projections.prompt_projector import generate_prompt_artifacts
        return generate_prompt_artifacts(classes, graph, template_base / "prompt", namespace)
    
    return {}
