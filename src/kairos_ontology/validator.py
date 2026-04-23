# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Ontology validation module - syntax, SHACL, consistency, GDPR PII scanning."""

import logging
from pathlib import Path
from typing import Optional
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS
from pyshacl import validate as shacl_validate
import json
from .catalog_utils import load_graph_with_catalog

logger = logging.getLogger(__name__)

KAIROS_EXT = Namespace("https://kairos.cnext.eu/ext#")

# PII indicator keywords — if a property local name or label contains any of these
# substrings, it is flagged as potentially containing personal data.
PII_KEYWORDS: list[str] = [
    "first_name", "last_name", "date_of_birth", "national_id", "iban",
    "phone", "email", "address", "ssn", "passport", "tax_id", "gender",
    "ethnicity", "religion", "health", "maiden_name", "birth_place",
    "nationality", "marital_status",
]

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


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case for PII matching."""
    import re
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def validate_gdpr(
    ontology_content: str,
    extension_content: Optional[str] = None,
) -> dict:
    """Scan an ontology for PII-like properties that lack GDPR satellite protection.

    For each ``owl:DatatypeProperty``, checks whether the property local name or
    ``rdfs:label`` contains any PII keyword.  Then verifies whether the property's
    ``rdfs:domain`` class (or a parent class) is protected by
    ``kairos-ext:gdprSatelliteOf``.

    Args:
        ontology_content: Turtle-formatted domain ontology.
        extension_content: Optional silver-ext TTL with ``kairos-ext:`` annotations.

    Returns:
        Dict with ``passed`` (bool — True if no unprotected PII found),
        ``warnings`` (list of dicts with class, property, keyword), and
        ``protected_classes`` (list of class URIs that have gdprSatelliteOf).
    """
    graph = Graph()
    graph.parse(data=ontology_content, format="turtle")

    if extension_content:
        graph.parse(data=extension_content, format="turtle")

    # Collect classes protected by gdprSatelliteOf (the satellite class itself)
    protected_classes: set[str] = set()
    for subj in graph.subjects(KAIROS_EXT.gdprSatelliteOf, None):
        protected_classes.add(str(subj))

    # Also collect the parent classes that HAVE a GDPR satellite
    # (i.e. the parent is indirectly protected — its PII is in the satellite)
    parents_with_satellite: set[str] = set()
    for subj, obj in graph.subject_objects(KAIROS_EXT.gdprSatelliteOf):
        parents_with_satellite.add(str(obj))

    warnings: list[dict] = []

    for prop in graph.subjects(RDF.type, OWL.DatatypeProperty):
        prop_uri = str(prop)
        local = prop_uri.rsplit("#", 1)[-1] if "#" in prop_uri else prop_uri.rsplit("/", 1)[-1]
        snake_local = _camel_to_snake(local)

        # Check label too
        label = str(graph.value(prop, RDFS.label) or "")
        label_lower = label.lower().replace(" ", "_")

        # Find matching PII keyword
        matched_keyword = None
        for kw in PII_KEYWORDS:
            if kw in snake_local or kw in label_lower:
                matched_keyword = kw
                break

        if not matched_keyword:
            continue

        # Find domain class(es) for this property
        for domain_cls in graph.objects(prop, RDFS.domain):
            cls_uri = str(domain_cls)
            # Skip if this class IS a GDPR satellite (it's already protected)
            if cls_uri in protected_classes:
                continue
            # Skip if this class HAS a GDPR satellite (PII should be there)
            if cls_uri in parents_with_satellite:
                continue
            # Unprotected PII
            cls_local = (
                cls_uri.rsplit("#", 1)[-1] if "#" in cls_uri
                else cls_uri.rsplit("/", 1)[-1]
            )
            warnings.append({
                "class": cls_local,
                "class_uri": cls_uri,
                "property": local,
                "property_uri": prop_uri,
                "keyword": matched_keyword,
            })

    return {
        "passed": len(warnings) == 0,
        "warnings": warnings,
        "protected_classes": list(protected_classes),
    }


def run_gdpr_validation(ontologies_path: Path, catalog_path: Optional[Path] = None):
    """Run GDPR PII scan across all domain ontologies.

    Prints warnings for classes with PII-like properties that lack
    ``kairos-ext:gdprSatelliteOf`` annotations.
    """
    print("\U0001f512 Kairos GDPR PII Scan")
    print("=" * 50)

    ontology_files = list(ontologies_path.glob("**/*.ttl"))
    ontology_files = [f for f in ontology_files if _is_domain_ontology(f)]

    # Pair each domain with its extension (if any)
    ext_map: dict[str, Path] = {}
    for f in ontologies_path.glob("**/*-silver-ext.ttl"):
        domain_name = f.stem.replace("-silver-ext", "")
        ext_map[domain_name] = f

    total_warnings = 0
    total_domains = 0

    for ontology_file in ontology_files:
        domain_name = ontology_file.stem
        ext_file = ext_map.get(domain_name)
        ext_content = ext_file.read_text(encoding="utf-8") if ext_file else None

        ontology_content = ontology_file.read_text(encoding="utf-8")
        result = validate_gdpr(ontology_content, ext_content)
        total_domains += 1

        if result["warnings"]:
            total_warnings += len(result["warnings"])
            print(f"\n  \u26a0\ufe0f  {ontology_file.name}:")
            for w in result["warnings"]:
                print(f"     {w['class']}.{w['property']} \u2014 "
                      f"PII keyword '{w['keyword']}' without gdprSatelliteOf")

    print(f"\n  Scanned {total_domains} domains")
    if total_warnings:
        print(f"  \u26a0\ufe0f  {total_warnings} unprotected PII warning(s)")
        print("  Consider adding kairos-ext:gdprSatelliteOf annotations.")
    else:
        print("  \u2705 No unprotected PII detected")

    return total_warnings


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
    # Skip non-domain files: silver-ext annotations, _master imports, etc.
    ontology_files = [f for f in ontology_files if _is_domain_ontology(f)]
    
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
