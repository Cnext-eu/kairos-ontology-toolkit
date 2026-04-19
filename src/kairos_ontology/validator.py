"""Ontology validation module - syntax, SHACL, consistency."""

from pathlib import Path
from typing import Optional
from rdflib import Graph
from pyshacl import validate as shacl_validate
import json
from .catalog_utils import load_graph_with_catalog


def validate_content(
    ontology_content: str,
    shapes_content: Optional[str] = None,
    do_syntax: bool = True,
    do_shacl: bool = True,
) -> dict:
    """Validate ontology content (TTL string) programmatically.

    Args:
        ontology_content: Turtle-formatted ontology string.
        shapes_content: Optional SHACL shapes as a Turtle string.
        do_syntax: Run syntax validation.
        do_shacl: Run SHACL validation (requires shapes_content).

    Returns:
        Dict with ``syntax`` and ``shacl`` keys, each containing
        ``passed`` (bool), and ``errors`` (list of str).
    """
    result: dict = {
        "syntax": {"passed": True, "errors": []},
        "shacl": {"passed": True, "errors": []},
    }

    # Syntax
    graph = None
    if do_syntax:
        try:
            graph = Graph()
            graph.parse(data=ontology_content, format="turtle")
        except Exception as e:
            result["syntax"]["passed"] = False
            result["syntax"]["errors"].append(str(e))
            return result  # can't continue without a valid graph

    # SHACL
    if do_shacl and shapes_content:
        if graph is None:
            graph = Graph()
            graph.parse(data=ontology_content, format="turtle")
        shapes_graph = Graph()
        shapes_graph.parse(data=shapes_content, format="turtle")
        conforms, _, report_text = shacl_validate(
            graph,
            shacl_graph=shapes_graph,
            inference="rdfs",
            abort_on_first=False,
        )
        if not conforms:
            result["shacl"]["passed"] = False
            result["shacl"]["errors"].append(report_text)

    return result


def run_validation(ontologies_path: Path, shapes_path: Path, catalog_path: Path,
                   do_syntax: bool, do_shacl: bool, do_consistency: bool):
    """Run validation pipeline."""
    
    print("🔍 Kairos Ontology Validation")
    print("=" * 50)
    
    results = {
        "syntax": {"passed": 0, "failed": 0, "errors": []},
        "shacl": {"passed": 0, "failed": 0, "errors": []},
        "consistency": {"passed": 0, "failed": 0, "errors": []}
    }
    
    # Find all ontology files
    ontology_files = list(ontologies_path.glob("**/*.ttl")) + list(ontologies_path.glob("**/*.rdf"))
    
    print(f"\nFound {len(ontology_files)} ontology files\n")
    
    # Level 1: Syntax Validation
    if do_syntax:
        print("📋 Level 1: Syntax Validation")
        print("-" * 50)
        for ontology_file in ontology_files:
            try:
                g = Graph()
                g.parse(ontology_file, format='turtle' if ontology_file.suffix == '.ttl' else 'xml')
                results["syntax"]["passed"] += 1
                print(f"  ✓ {ontology_file.name}")
            except Exception as e:
                results["syntax"]["failed"] += 1
                results["syntax"]["errors"].append({"file": str(ontology_file), "error": str(e)})
                print(f"  ✗ {ontology_file.name}: {e}")
        
        print(f"\n  Passed: {results['syntax']['passed']}, Failed: {results['syntax']['failed']}\n")
    
    # Level 2: SHACL Validation
    if do_shacl and shapes_path.exists():
        print("📐 Level 2: SHACL Validation")
        print("-" * 50)
        
        # Load all shapes
        shapes_graph = Graph()
        for shape_file in shapes_path.glob("**/*.shacl.ttl"):
            shapes_graph.parse(shape_file, format='turtle')
        
        for ontology_file in ontology_files:
            try:
                data_graph = load_graph_with_catalog(ontology_file, catalog_path) if catalog_path else Graph()
                if not catalog_path:
                    data_graph.parse(ontology_file, format='turtle' if ontology_file.suffix == '.ttl' else 'xml')
                
                conforms, report_graph, report_text = shacl_validate(
                    data_graph,
                    shacl_graph=shapes_graph,
                    inference='rdfs',
                    abort_on_first=False
                )
                
                if conforms:
                    results["shacl"]["passed"] += 1
                    print(f"  ✓ {ontology_file.name}")
                else:
                    results["shacl"]["failed"] += 1
                    results["shacl"]["errors"].append({
                        "file": str(ontology_file),
                        "report": report_text
                    })
                    print(f"  ✗ {ontology_file.name}")
                    print(f"    {report_text}")
                    
            except Exception as e:
                results["shacl"]["failed"] += 1
                results["shacl"]["errors"].append({"file": str(ontology_file), "error": str(e)})
                print(f"  ✗ {ontology_file.name}: {e}")
        
        print(f"\n  Passed: {results['shacl']['passed']}, Failed: {results['shacl']['failed']}\n")
    
    # Level 3: Consistency Validation (SPARQL queries)
    if do_consistency:
        print("🔗 Level 3: Consistency Validation")
        print("-" * 50)
        print("  (Custom SPARQL queries for consistency checks)")
        print("  Not implemented yet - future enhancement\n")
    
    # Save results
    results_file = Path("validation-report.json")
    results_file.write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(f"📄 Results saved to {results_file}")
    
    # Exit code
    total_failed = results["syntax"]["failed"] + results["shacl"]["failed"] + results["consistency"]["failed"]
    if total_failed > 0:
        print(f"\n❌ Validation failed with {total_failed} errors")
        exit(1)
    else:
        print("\n✅ All validations passed!")
