"""Projection orchestrator - generates downstream artifacts."""

from pathlib import Path
from .catalog_utils import load_graph_with_catalog
from .projections.dbt_projector import DBTProjector
from .projections.neo4j_projector import Neo4jProjector
from .projections.azure_search_projector import AzureSearchProjector
from .projections.a2ui_projector import A2UIProjector
from .projections.prompt_projector import PromptProjector


def run_projections(ontologies_path: Path, catalog_path: Path, output_path: Path, target: str):
    """Run projection generation."""
    
    print("🚀 Kairos Ontology Projections")
    print("=" * 50)
    
    # Load all ontologies into merged graph
    print("\nLoading ontologies...")
    merged_graph = load_graph_with_catalog(ontologies_path, catalog_path) if catalog_path else None
    
    if not merged_graph:
        from rdflib import Graph
        merged_graph = Graph()
        for onto_file in ontologies_path.glob("**/*.ttl"):
            merged_graph.parse(onto_file, format='turtle')
    
    print(f"  Loaded {len(merged_graph)} triples\n")
    
    # Create output directories
    output_path.mkdir(parents=True, exist_ok=True)
    
    projectors = {
        'dbt': DBTProjector(),
        'neo4j': Neo4jProjector(),
        'azure-search': AzureSearchProjector(),
        'a2ui': A2UIProjector(),
        'prompt': PromptProjector()
    }
    
    if target == 'all':
        targets = projectors.keys()
    else:
        targets = [target]
    
    for target_name in targets:
        print(f"📦 Generating {target_name} projection...")
        projector = projectors[target_name]
        target_output = output_path / target_name
        target_output.mkdir(exist_ok=True)
        
        try:
            projector.project(merged_graph, target_output)
            print(f"  ✓ {target_name} projection completed\n")
        except Exception as e:
            print(f"  ✗ {target_name} projection failed: {e}\n")
    
    print("✅ Projection generation completed!")
