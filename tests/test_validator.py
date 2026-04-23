# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the validation module."""

import pytest
from kairos_ontology.validator import run_validation, validate_gdpr, run_gdpr_validation


class TestValidator:
    """Test the validation pipeline."""
    
    def test_syntax_validation_valid_file(self, temp_dir, sample_ontology, capsys):
        """Test syntax validation with valid ontology."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        ontology_file = ontologies_dir / "customer.ttl"
        ontology_file.write_text(sample_ontology, encoding='utf-8')
        
        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()
        
        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False
        )
        
        captured = capsys.readouterr()
        assert "Syntax Validation" in captured.out
        assert "Passed:" in captured.out or "✓" in captured.out
    
    def test_syntax_validation_invalid_file(self, temp_dir, capsys):
        """Test syntax validation with invalid ontology."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        invalid_file = ontologies_dir / "invalid.ttl"
        invalid_file.write_text("Invalid Turtle @#$%", encoding='utf-8')
        
        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()
        
        with pytest.raises(SystemExit):
            run_validation(
                ontologies_path=ontologies_dir,
                shapes_path=shapes_dir,
                catalog_path=None,
                do_syntax=True,
                do_shacl=False,
                do_consistency=False
            )
        
        captured = capsys.readouterr()
        assert "Failed:" in captured.out or "✗" in captured.out
    
    def test_empty_ontologies_directory(self, temp_dir, capsys):
        """Test validation with empty ontologies directory."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()
        
        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False
        )
        
        captured = capsys.readouterr()
        assert "Found 0 ontology files" in captured.out


# -----------------------------------------------------------------------
# GDPR PII Validation Tests
# -----------------------------------------------------------------------

# Ontology with PII properties and NO GDPR satellite annotation
_ONTOLOGY_WITH_UNPROTECTED_PII = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <http://example.org/ont/party#> .

ex:PartyOntology a owl:Ontology ;
    rdfs:label "Party" ;
    owl:versionInfo "1.0" .

ex:NaturalPerson a owl:Class ;
    rdfs:label "Natural Person" ;
    rdfs:comment "A natural person" .

ex:firstName a owl:DatatypeProperty ;
    rdfs:domain ex:NaturalPerson ;
    rdfs:range xsd:string ;
    rdfs:label "First Name" .

ex:lastName a owl:DatatypeProperty ;
    rdfs:domain ex:NaturalPerson ;
    rdfs:range xsd:string ;
    rdfs:label "Last Name" .

ex:dateOfBirth a owl:DatatypeProperty ;
    rdfs:domain ex:NaturalPerson ;
    rdfs:range xsd:date ;
    rdfs:label "Date of Birth" .

ex:nationalIdNumber a owl:DatatypeProperty ;
    rdfs:domain ex:NaturalPerson ;
    rdfs:range xsd:string ;
    rdfs:label "National ID Number" .
"""

# Extension with GDPR satellite annotation protecting NaturalPerson
_GDPR_EXTENSION = """\
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <http://example.org/ont/party#> .

ex:NaturalPerson
    kairos-ext:gdprSatelliteOf ex:Party .
"""

# Ontology with NO PII (just business properties)
_ONTOLOGY_NO_PII = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <http://example.org/ont/service#> .

ex:ServiceOntology a owl:Ontology ;
    rdfs:label "Service" ;
    owl:versionInfo "1.0" .

ex:ProfessionalService a owl:Class ;
    rdfs:label "Professional Service" ;
    rdfs:comment "A professional service" .

ex:serviceName a owl:DatatypeProperty ;
    rdfs:domain ex:ProfessionalService ;
    rdfs:range xsd:string ;
    rdfs:label "Service Name" .

ex:serviceCode a owl:DatatypeProperty ;
    rdfs:domain ex:ProfessionalService ;
    rdfs:range xsd:string ;
    rdfs:label "Service Code" .
"""

# Ontology where the PARENT class has PII but a satellite exists
_ONTOLOGY_PARENT_WITH_SATELLITE = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix ex: <http://example.org/ont/party#> .

ex:PartyOntology a owl:Ontology ;
    rdfs:label "Party" ;
    owl:versionInfo "1.0" .

ex:Party a owl:Class ;
    rdfs:label "Party" ;
    rdfs:comment "A party" .

ex:NaturalPerson a owl:Class ;
    rdfs:label "Natural Person" ;
    rdfs:comment "GDPR satellite for Party" ;
    kairos-ext:gdprSatelliteOf ex:Party .

ex:firstName a owl:DatatypeProperty ;
    rdfs:domain ex:NaturalPerson ;
    rdfs:range xsd:string ;
    rdfs:label "First Name" .

ex:email a owl:DatatypeProperty ;
    rdfs:domain ex:NaturalPerson ;
    rdfs:range xsd:string ;
    rdfs:label "Email" .
"""


class TestGdprValidation:
    """Test GDPR PII scanning."""

    def test_unprotected_pii_detected(self):
        """PII properties without gdprSatelliteOf should be flagged."""
        result = validate_gdpr(_ONTOLOGY_WITH_UNPROTECTED_PII)
        assert result["passed"] is False
        assert len(result["warnings"]) >= 3
        keywords_found = {w["keyword"] for w in result["warnings"]}
        assert "first_name" in keywords_found
        assert "last_name" in keywords_found
        assert "date_of_birth" in keywords_found

    def test_no_pii_passes(self):
        """Ontology with no PII should pass."""
        result = validate_gdpr(_ONTOLOGY_NO_PII)
        assert result["passed"] is True
        assert len(result["warnings"]) == 0

    def test_gdpr_satellite_protects_class(self):
        """PII in a class WITH gdprSatelliteOf should NOT be flagged."""
        result = validate_gdpr(_ONTOLOGY_PARENT_WITH_SATELLITE)
        assert result["passed"] is True
        assert len(result["warnings"]) == 0

    def test_extension_provides_protection(self):
        """PII should be suppressed when extension adds gdprSatelliteOf."""
        result = validate_gdpr(_ONTOLOGY_WITH_UNPROTECTED_PII, _GDPR_EXTENSION)
        assert result["passed"] is True
        assert len(result["warnings"]) == 0

    def test_unprotected_pii_reports_class_and_property(self):
        """Each warning should include class, property, and keyword."""
        result = validate_gdpr(_ONTOLOGY_WITH_UNPROTECTED_PII)
        for w in result["warnings"]:
            assert "class" in w
            assert "property" in w
            assert "keyword" in w
            assert w["class"] == "NaturalPerson"

    def test_protected_classes_list(self):
        """Protected classes should be reported."""
        result = validate_gdpr(_ONTOLOGY_PARENT_WITH_SATELLITE)
        assert len(result["protected_classes"]) == 1

    def test_run_gdpr_validation_with_files(self, temp_dir, capsys):
        """Integration test: run_gdpr_validation with actual files."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()

        ont_file = ontologies_dir / "party.ttl"
        ont_file.write_text(_ONTOLOGY_WITH_UNPROTECTED_PII, encoding="utf-8")

        result = run_gdpr_validation(ontologies_path=ontologies_dir)
        captured = capsys.readouterr()
        assert result > 0
        assert "GDPR PII Scan" in captured.out
        assert "unprotected PII" in captured.out

    def test_run_gdpr_validation_clean(self, temp_dir, capsys):
        """Integration test: no warnings for clean ontology."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()

        ont_file = ontologies_dir / "service.ttl"
        ont_file.write_text(_ONTOLOGY_NO_PII, encoding="utf-8")

        result = run_gdpr_validation(ontologies_path=ontologies_dir)
        captured = capsys.readouterr()
        assert result == 0
        assert "No unprotected PII detected" in captured.out
