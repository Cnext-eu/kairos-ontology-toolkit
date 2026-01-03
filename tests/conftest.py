"""Test fixtures and configuration."""

import pytest
from pathlib import Path
import tempfile
import shutil


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    temp = Path(tempfile.mkdtemp())
    yield temp
    shutil.rmtree(temp, ignore_errors=True)


@pytest.fixture
def sample_ontology():
    """Sample ontology content in Turtle format."""
    return """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix kairos: <urn:kairos:ont:core:> .

kairos:Customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer entity" .

kairos:customerName a owl:DatatypeProperty ;
    rdfs:domain kairos:Customer ;
    rdfs:range xsd:string ;
    rdfs:label "Customer Name" ;
    rdfs:comment "The name of the customer" .

kairos:customerEmail a owl:DatatypeProperty ;
    rdfs:domain kairos:Customer ;
    rdfs:range xsd:string ;
    rdfs:label "Customer Email" ;
    rdfs:comment "Email address of the customer" .
"""


@pytest.fixture
def sample_ontology_with_subclass():
    """Sample ontology with inheritance."""
    return """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix kairos: <urn:kairos:ont:core:> .

kairos:Person a owl:Class ;
    rdfs:label "Person" ;
    rdfs:comment "A person entity" .

kairos:Employee a owl:Class ;
    rdfs:label "Employee" ;
    rdfs:comment "An employee entity" ;
    rdfs:subClassOf kairos:Person .

kairos:personName a owl:DatatypeProperty ;
    rdfs:domain kairos:Person ;
    rdfs:range xsd:string ;
    rdfs:label "Person Name" .

kairos:employeeId a owl:DatatypeProperty ;
    rdfs:domain kairos:Employee ;
    rdfs:range xsd:string ;
    rdfs:label "Employee ID" .
"""


@pytest.fixture
def ontology_files(temp_dir, sample_ontology, sample_ontology_with_subclass):
    """Create sample ontology files in a temporary directory."""
    ontologies_dir = temp_dir / "ontologies"
    ontologies_dir.mkdir()
    
    # Create multiple ontology files
    customer_file = ontologies_dir / "customer.ttl"
    customer_file.write_text(sample_ontology, encoding='utf-8')
    
    person_file = ontologies_dir / "person.ttl"
    person_file.write_text(sample_ontology_with_subclass, encoding='utf-8')
    
    return {
        'dir': ontologies_dir,
        'customer': customer_file,
        'person': person_file
    }


@pytest.fixture
def http_ontology():
    """Sample ontology using HTTP namespace (standard semantic web practice)."""
    return """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <http://example.org/ontology/> .

ex:Product a owl:Class ;
    rdfs:label "Product" ;
    rdfs:comment "A product in the catalog" .

ex:productName a owl:DatatypeProperty ;
    rdfs:domain ex:Product ;
    rdfs:range xsd:string ;
    rdfs:label "Product Name" .

ex:productPrice a owl:DatatypeProperty ;
    rdfs:domain ex:Product ;
    rdfs:range xsd:decimal ;
    rdfs:label "Product Price" .
"""


@pytest.fixture
def hash_ontology():
    """Sample ontology using hash-based HTTP namespace (common in FIBO, etc.)."""
    return """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix fibo: <https://spec.edmcouncil.org/fibo/ontology/FND/Relations/Relations#> .

fibo:Organization a owl:Class ;
    rdfs:label "Organization" ;
    rdfs:comment "A legal organization" .

fibo:orgName a owl:DatatypeProperty ;
    rdfs:domain fibo:Organization ;
    rdfs:range xsd:string ;
    rdfs:label "Organization Name" .
"""
