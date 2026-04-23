# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Projection orchestrator - generates downstream artifacts."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS
from .projections.uri_utils import extract_local_name

VALID_TARGETS = ["dbt", "neo4j", "azure-search", "a2ui", "prompt", "silver"]

# Filename patterns that are NOT domain ontologies and should be skipped.
_NON_DOMAIN_SUFFIXES = ("-silver-ext", "-ext")
_NON_DOMAIN_PREFIXES = ("_",)


def _is_domain_ontology(path: Path) -> bool:
    """Return True if *path* looks like a domain ontology file.

    Excludes annotation/configuration files such as ``*-silver-ext.ttl``
    and metadata files whose name starts with ``_`` (e.g. ``_master.ttl``).
    """
    stem = path.stem
    if any(stem.startswith(p) for p in _NON_DOMAIN_PREFIXES):
        return False
    if any(stem.endswith(s) for s in _NON_DOMAIN_SUFFIXES):
        return False
    return True


def project_graph(
    graph: Graph,
    targets: Optional[List[str]] = None,
    namespace: Optional[str] = None,
    ontology_name: str = "ontology",
    shapes_dir: Optional[Path] = None,
) -> Dict[str, Dict[str, str]]:
    """Generate projection artifacts from an in-memory rdflib Graph.

    Args:
        graph: Loaded rdflib Graph.
        targets: List of projection targets (e.g. ``["dbt", "neo4j"]``).
                 Defaults to all targets.
        namespace: Base namespace to filter classes.  Auto-detected if ``None``.
        ontology_name: Name used in output filenames.
        shapes_dir: Optional path to SHACL shapes directory.

    Returns:
        ``{target: {filename: content}}`` mapping.
    """
    targets = targets or VALID_TARGETS
    template_base = Path(__file__).parent / "templates"
    ns = namespace or _auto_detect_namespace(graph)
    meta = extract_ontology_metadata(graph, ns)

    results: Dict[str, Dict[str, str]] = {}
    for target_name in targets:
        if target_name not in VALID_TARGETS:
            continue
        artifacts = _run_projection(
            target_name, graph, Path("."), template_base, ns, shapes_dir, ontology_name,
            ontology_metadata=meta,
        )
        if artifacts:
            results[target_name] = artifacts
    return results


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
    
    # Get all ontology files
    ontology_files = list(ontologies_path.glob("**/*.ttl")) + list(ontologies_path.glob("**/*.rdf"))
    # Skip non-domain files: silver-ext annotations, _master imports, etc.
    ontology_files = [f for f in ontology_files if _is_domain_ontology(f)]
    
    if not ontology_files:
        print(f"  ⚠️  No ontology files found in {ontologies_path}")
        return
    
    print(f"\nFound {len(ontology_files)} ontology file(s)")
    print("Each ontology will generate separate output files per domain\n")
    
    # Process each ontology file separately (each represents a data domain)
    print("Loading ontologies...")
    ontology_graphs = []
    
    for onto_file in ontology_files:
        try:
            file_graph = Graph()
            if catalog_path and catalog_path.exists():
                # Load with catalog support for imports
                from .catalog_utils import load_graph_with_catalog
                file_graph = load_graph_with_catalog(onto_file, catalog_path)
            else:
                # Load without catalog
                file_graph.parse(onto_file, format='turtle' if onto_file.suffix == '.ttl' else 'xml')
            
            # Store graph with its source file info
            ontology_graphs.append({
                'file': onto_file,
                'graph': file_graph,
                'name': onto_file.stem  # filename without extension (e.g., 'customer' from 'customer.ttl')
            })
            print(f"  ✓ Loaded {onto_file.name} ({len(file_graph)} triples)")
        except Exception as e:
            print(f"  ⚠️  Could not parse {onto_file.name}: {e}")
    
    if not ontology_graphs:
        print("  ⚠️  No ontologies loaded - check ontology files exist")
        return
    
    print()
    
    # Create output directories
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Determine template directory
    template_base = Path(__file__).parent / "templates"
    
    # Look for SHACL shapes directory
    shapes_dir = ontologies_path.parent / "shapes" if ontologies_path.parent else None
    if shapes_dir and shapes_dir.exists():
        print(f"  Found SHACL shapes directory: {shapes_dir}\n")

    targets_to_run = ['dbt', 'neo4j', 'azure-search', 'a2ui', 'prompt', 'silver'] if target == 'all' else [target]

    # Accumulate per-domain manifest data: {domain_name: {meta, targets: {target: [files]}}}
    manifests: dict[str, dict] = {}

    for target_name in targets_to_run:
        print(f"📦 Generating {target_name} projection...")
        target_output = output_path / target_name
        target_output.mkdir(exist_ok=True)
        
        total_files = 0
        
        for onto_info in ontology_graphs:
            onto_graph = onto_info['graph']
            onto_name = onto_info['name']
            
            # Auto-detect namespace for this ontology if not provided
            onto_namespace = namespace
            if onto_namespace is None:
                onto_namespace = _auto_detect_namespace(onto_graph)
                print(f"  [{onto_name}] Auto-detected namespace: {onto_namespace}")

            # Extract ontology provenance metadata
            onto_meta = extract_ontology_metadata(onto_graph, onto_namespace)
            
            try:
                # Generate artifacts for this specific ontology
                # For silver: auto-discover *-silver-ext.ttl alongside the ontology file
                ext_path: Optional[Path] = None
                if target_name == "silver":
                    src_file: Path = onto_info["file"]
                    candidates = list(src_file.parent.glob(f"{onto_name}-silver-ext.ttl"))
                    candidates += list(src_file.parent.glob("*-silver-ext.ttl"))
                    ext_path = candidates[0] if candidates else None
                    if ext_path:
                        print(f"  [{onto_name}] Using projection ext: {ext_path.name}")

                artifacts = _run_projection(target_name, onto_graph, target_output, template_base,
                                            onto_namespace, shapes_dir, onto_name,
                                            projection_ext_path=ext_path,
                                            ontology_metadata=onto_meta)
                if artifacts:
                    # Save artifacts
                    for file_path, content in artifacts.items():
                        output_file = target_output / file_path
                        output_file.parent.mkdir(parents=True, exist_ok=True)
                        output_file.write_text(content, encoding='utf-8')
                    
                    total_files += len(artifacts)
                    print(f"  [{onto_name}] ✓ Generated {len(artifacts)} file(s)")

                    # Track for manifest
                    if onto_name not in manifests:
                        manifests[onto_name] = {
                            "meta": onto_meta,
                            "targets": {},
                        }
                    manifests[onto_name]["targets"][target_name] = sorted(artifacts.keys())
            except Exception as e:
                import traceback
                print(f"  [{onto_name}] ✗ Failed: {e}")
                if '--verbose' in str(target):  # Simple verbose check
                    traceback.print_exc()

        # After all domains: generate master ERD for silver target
        if target_name == "silver" and total_files > 0:
            from .projections.silver_projector import generate_master_erd, render_mermaid_svg
            silver_output = output_path / "silver"
            hub_name = ontologies_path.parent.name  # e.g. "ontology-hub"
            master_mmd = generate_master_erd(silver_output, hub_name=hub_name)
            if master_mmd:
                master_path = silver_output / "master-erd.mmd"
                master_path.write_text(master_mmd, encoding="utf-8")
                # Also write to application-models/ for web UI display
                app_models = ontologies_path.parent / "application-models"
                app_models.mkdir(exist_ok=True)
                (app_models / "master-erd.mmd").write_text(master_mmd, encoding="utf-8")
                total_files += 2
                print(f"  ✓ Master ERD written: silver/master-erd.mmd + application-models/master-erd.mmd")

            # Render all .mmd files to SVG via Mermaid CLI (if available)
            svg_count = 0
            for mmd_file in sorted(silver_output.rglob("*.mmd")):
                svg = render_mermaid_svg(mmd_file)
                if svg:
                    svg_count += 1
            # Also render application-models copies
            app_models = ontologies_path.parent / "application-models"
            if app_models.exists():
                for mmd_file in sorted(app_models.glob("*.mmd")):
                    svg = render_mermaid_svg(mmd_file)
                    if svg:
                        svg_count += 1
            if svg_count:
                total_files += svg_count
                print(f"  ✓ Rendered {svg_count} SVG file(s) via Mermaid CLI")
            else:
                print("  ℹ Mermaid CLI (mmdc) not found — SVG export skipped."
                      " Install: npm install -D @mermaid-js/mermaid-cli")

        print(f"  ✓ {target_name} projection completed: {total_files} total files\n")
    
    print("✅ Projection generation completed!")
    print(f"   Generated artifacts for {len(ontology_graphs)} data domain(s)")

    # Write per-domain projection manifests
    for domain_name, mdata in manifests.items():
        manifest = {
            "domain": domain_name,
            "ontology_iri": mdata["meta"]["iri"],
            "ontology_version": mdata["meta"]["version"],
            "ontology_label": mdata["meta"]["label"],
            "namespace": mdata["meta"]["namespace"],
            "toolkit_version": mdata["meta"]["toolkit_version"],
            "generated_at": mdata["meta"]["generated_at"],
            "targets": mdata["targets"],
        }
        manifest_path = output_path / f"{domain_name}-projection-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"   📋 Manifest: {manifest_path.name}")


def extract_ontology_metadata(graph: Graph, namespace: str) -> dict:
    """Extract provenance metadata from the owl:Ontology declaration.

    Returns a dict with keys: ``iri``, ``version``, ``label``, ``namespace``,
    ``toolkit_version``, and ``generated_at``.  Missing values default to
    sensible placeholders so callers can always rely on the keys being present.
    """
    from kairos_ontology import __version__ as toolkit_version

    iri: str = namespace.rstrip("#/")
    version: str = ""
    label: str = ""

    # Find the owl:Ontology that lives in the given namespace
    for subj in graph.subjects(predicate=None, object=OWL.Ontology):
        subj_str = str(subj)
        if subj_str.startswith(namespace.rstrip("#/")):
            iri = subj_str
            ver = graph.value(subj, OWL.versionInfo)
            if ver:
                version = str(ver)
            lbl = graph.value(subj, RDFS.label)
            if lbl:
                label = str(lbl)
            break

    return {
        "iri": iri,
        "version": version,
        "label": label,
        "namespace": namespace,
        "toolkit_version": toolkit_version,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


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
        
        # Extract namespace from ontology URI.
        # Key insight: many ontologies declare URI without '#' (e.g.
        # https://example.com/ont/client) but their classes use '#' fragments
        # (e.g. https://example.com/ont/client#Client).  In that case the
        # namespace is '{onto_uri}#', NOT the parent path.
        if '#' in onto_uri:
            namespace = onto_uri.rsplit('#', 1)[0] + '#'
        else:
            # Probe: do any owl:Class URIs start with '{onto_uri}#'?
            hash_ns = onto_uri + '#'
            has_hash_classes = any(
                str(cls).startswith(hash_ns)
                for cls in graph.subjects(RDF.type, OWL.Class)
                if isinstance(cls, URIRef)
            )
            if has_hash_classes:
                namespace = hash_ns
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


def _run_projection(target: str, graph: Graph, output_path: Path, template_base: Path,
                    namespace: str, shapes_dir: Path = None, ontology_name: str = None,
                    projection_ext_path: Optional[Path] = None,
                    ontology_metadata: Optional[dict] = None) -> dict:
    """Run a specific projection type using simplified logic.
    
    Args:
        target: Projection type (dbt, neo4j, azure-search, a2ui, prompt, silver)
        graph: RDFLib graph for this specific ontology
        output_path: Base output path for this target
        template_base: Path to templates
        namespace: Namespace to filter classes
        shapes_dir: Optional SHACL shapes directory
        ontology_name: Name of the ontology file (without extension)
        projection_ext_path: Optional path to *-silver-ext.ttl (silver target only)
        ontology_metadata: Provenance metadata from extract_ontology_metadata()
    """
    
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
        return {}
    
    meta = ontology_metadata or {}

    # Generate based on target using full-featured projector classes
    # Pass ontology_name so each projector can create domain-specific filenames
    if target == 'dbt':
        from .projections.dbt_projector import generate_dbt_artifacts
        return generate_dbt_artifacts(
            classes, graph, template_base / "dbt", namespace, shapes_dir,
            ontology_name, ontology_metadata=meta,
        )
    elif target == 'neo4j':
        from .projections.neo4j_projector import generate_neo4j_artifacts
        return generate_neo4j_artifacts(
            classes, graph, template_base / "neo4j", namespace,
            ontology_name, ontology_metadata=meta,
        )
    elif target == 'azure-search':
        from .projections.azure_search_projector import generate_azure_search_artifacts
        return generate_azure_search_artifacts(
            classes, graph, template_base / "azure-search", namespace,
            ontology_name, ontology_metadata=meta,
        )
    elif target == 'a2ui':
        from .projections.a2ui_projector import generate_a2ui_artifacts
        return generate_a2ui_artifacts(
            classes, graph, template_base / "a2ui", namespace,
            ontology_name, ontology_metadata=meta,
        )
    elif target == 'prompt':
        from .projections.prompt_projector import generate_prompt_artifacts
        return generate_prompt_artifacts(
            classes, graph, template_base / "prompt", namespace,
            ontology_name, ontology_metadata=meta,
        )
    elif target == 'silver':
        from .projections.silver_projector import generate_silver_artifacts
        return generate_silver_artifacts(
            classes=classes,
            graph=graph,
            namespace=namespace,
            shapes_dir=shapes_dir,
            ontology_name=ontology_name or "domain",
            projection_ext_path=projection_ext_path,
            ontology_metadata=meta,
        )
    
    return {}
