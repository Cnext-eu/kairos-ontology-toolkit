#!/usr/bin/env python3
"""
Demo: Domain-Specific Output Generation

This demonstrates how each ontology file generates separate, 
independently deployable outputs per data domain.
"""

from pathlib import Path
import tempfile
import shutil

# Create temporary workspace
temp_dir = Path(tempfile.mkdtemp())
ontologies_dir = temp_dir / 'ontologies'
ontologies_dir.mkdir()

print("=" * 60)
print("Domain-Specific Projection Demo")
print("=" * 60)

# Create Customer domain ontology
customer_ontology = """
@prefix : <http://example.com/ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:CustomerOntology a owl:Ontology ;
    rdfs:label "Customer Domain Ontology" .

:Customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer entity" .

:customerName a owl:DatatypeProperty ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string ;
    rdfs:comment "Customer full name" .

:customerEmail a owl:DatatypeProperty ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string ;
    rdfs:comment "Customer email address" .
"""

# Create Order domain ontology
order_ontology = """
@prefix : <http://example.com/ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:OrderOntology a owl:Ontology ;
    rdfs:label "Order Domain Ontology" .

:Order a owl:Class ;
    rdfs:label "Order" ;
    rdfs:comment "An order placed by a customer" .

:orderDate a owl:DatatypeProperty ;
    rdfs:domain :Order ;
    rdfs:range xsd:dateTime ;
    rdfs:comment "Date when order was placed" .

:orderTotal a owl:DatatypeProperty ;
    rdfs:domain :Order ;
    rdfs:range xsd:decimal ;
    rdfs:comment "Total order amount" .
"""

# Write ontology files
(ontologies_dir / 'customer.ttl').write_text(customer_ontology)
(ontologies_dir / 'order.ttl').write_text(order_ontology)

print("\n📝 Created 2 domain ontologies:")
print("  • customer.ttl (Customer domain)")
print("  • order.ttl (Order domain)")

# Run projections
print("\n🔄 Running projections...\n")
from kairos_ontology.projector import run_projections

output_dir = temp_dir / 'output'
run_projections(ontologies_dir, None, output_dir, 'all')

# Display generated structure
print("\n" + "=" * 60)
print("📂 Generated File Structure (Domain-Separated)")
print("=" * 60)

import os

def print_tree(directory, prefix="", is_last=True):
    """Print directory tree structure"""
    items = sorted(directory.iterdir(), key=lambda x: (x.is_file(), x.name))
    
    for i, item in enumerate(items):
        is_last_item = i == len(items) - 1
        current_prefix = "└── " if is_last_item else "├── "
        print(f"{prefix}{current_prefix}{item.name}")
        
        if item.is_dir():
            extension = "    " if is_last_item else "│   "
            print_tree(item, prefix + extension, is_last_item)

print_tree(output_dir)

print("\n" + "=" * 60)
print("Key Observations:")
print("=" * 60)
print("""
✅ Each domain has separate outputs:
   • customer.ttl → customer-specific files
   • order.ttl → order-specific files

✅ Independent deployment:
   • Deploy customer domain without affecting orders
   • Version control per domain
   • Selective rollouts

✅ File naming convention:
   • DBT: {domain}/models/silver/{class}.sql
   • Neo4j: {domain}-schema.cypher
   • Prompt: {domain}-context.json
   • Azure Search: {domain}/indexes/{class}-index.json
   • A2UI: {domain}/schemas/{Class}.schema.json
""")

# Cleanup
print("\n🧹 Cleaning up temporary files...")
shutil.rmtree(temp_dir)
print("✅ Demo complete!")
