# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the validation module."""

import json

import pytest
from kairos_ontology.core.validator import run_validation, validate_gdpr, run_gdpr_validation


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

    def test_no_report_written_when_report_path_omitted(
        self, temp_dir, sample_ontology, capsys, monkeypatch
    ):
        """Direct library callers that omit report_path get no report file —
        an explicit, documented no-op rather than an ambiguous CWD guess."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        (ontologies_dir / "customer.ttl").write_text(sample_ontology, encoding="utf-8")

        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()

        cwd = temp_dir / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)

        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False,
        )

        captured = capsys.readouterr()
        assert "Results saved to" not in captured.out
        assert not (cwd / "validation-report.json").exists()

    def test_report_written_to_explicit_path(self, temp_dir, sample_ontology, capsys):
        """An explicit report_path is honored, including creating parents."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        (ontologies_dir / "customer.ttl").write_text(sample_ontology, encoding="utf-8")

        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()

        report_path = temp_dir / "output" / "validation-report.json"
        assert not report_path.parent.exists()

        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False,
            report_path=report_path,
        )

        captured = capsys.readouterr()
        assert f"Results saved to {report_path}" in captured.out
        assert report_path.exists()
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["syntax"]["passed"] == 1

    def test_no_markdown_written_when_markdown_report_path_omitted(
        self, temp_dir, sample_ontology, capsys
    ):
        """Additive Markdown output stays off by default (preserves JSON-only contract)."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        (ontologies_dir / "customer.ttl").write_text(sample_ontology, encoding="utf-8")

        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()

        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False,
        )

        captured = capsys.readouterr()
        assert "Markdown report saved to" not in captured.out

    def test_markdown_report_written_to_explicit_path(self, temp_dir, sample_ontology, capsys):
        """An explicit markdown_report_path writes a deterministic Markdown report
        containing toolkit version, effective options, catalog, accelerator,
        scope/files, and findings — additively, alongside (or instead of) JSON."""
        from kairos_ontology import __version__ as toolkit_version

        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        (ontologies_dir / "customer.ttl").write_text(sample_ontology, encoding="utf-8")

        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()

        markdown_report_path = temp_dir / "output" / "validation-report.md"

        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=True,
            do_shacl=True,
            do_consistency=False,
            accelerator="acme-core",
            markdown_report_path=markdown_report_path,
        )

        captured = capsys.readouterr()
        assert f"Markdown report saved to {markdown_report_path}" in captured.out
        assert markdown_report_path.exists()

        text = markdown_report_path.read_text(encoding="utf-8")
        assert f"Toolkit version:** {toolkit_version}" in text
        assert "## Effective command options" in text
        assert "Catalog:" in text
        assert "Accelerator:** acme-core" in text
        assert "## Scope / files" in text
        assert "customer.ttl" in text
        assert "## Findings" in text
        assert "| syntax |" in text
        assert "## Suggested lifecycle state (non-writing signal)" in text

    def test_markdown_report_is_deterministic(self, temp_dir, sample_ontology):
        """Two runs over identical input produce byte-identical Markdown."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        (ontologies_dir / "customer.ttl").write_text(sample_ontology, encoding="utf-8")

        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()

        path_a = temp_dir / "a.md"
        path_b = temp_dir / "b.md"

        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False,
            markdown_report_path=path_a,
        )
        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False,
            markdown_report_path=path_b,
        )

        assert path_a.read_text(encoding="utf-8") == path_b.read_text(encoding="utf-8")

    def test_json_report_includes_non_writing_state_proposal(
        self, temp_dir, sample_ontology
    ):
        """The JSON report additively carries a typed, non-writing lifecycle-state
        suggestion; run_validation itself must never touch .kairos-state/."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        (ontologies_dir / "customer.ttl").write_text(sample_ontology, encoding="utf-8")

        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()

        report_path = temp_dir / "output" / "validation-report.json"
        state_dir = temp_dir / ".kairos-state"

        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=True,
            do_shacl=True,
            do_consistency=False,
            report_path=report_path,
        )

        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert "state_proposal" in payload
        assert payload["state_proposal"]["suggested_state"] == "design-valid"
        assert isinstance(payload["state_proposal"]["achieved"], bool)
        assert "reason" in payload["state_proposal"]
        assert not state_dir.exists()  # non-writing: no lifecycle-state mutation


class TestLifecycleStateProposal:
    """Tests for the typed, non-writing DD-080 lifecycle-state suggestion."""

    def test_propose_achieved_when_focused_checks_pass(self):
        from kairos_ontology.core.validator import propose_lifecycle_state

        results = {
            "syntax": {"passed": 1, "failed": 0},
            "imports": {"passed": 0, "failed": 0},
            "shacl": {"passed": 1, "failed": 0},
            "consistency": {"passed": 0, "failed": 0},
        }
        proposal = propose_lifecycle_state(results, do_syntax=True, do_shacl=True)
        assert proposal.suggested_state == "design-valid"
        assert proposal.achieved is True

    def test_propose_not_achieved_on_failure(self):
        from kairos_ontology.core.validator import propose_lifecycle_state

        results = {
            "syntax": {"passed": 0, "failed": 1},
            "imports": {"passed": 0, "failed": 0},
            "shacl": {"passed": 0, "failed": 0},
            "consistency": {"passed": 0, "failed": 0},
        }
        proposal = propose_lifecycle_state(results, do_syntax=True, do_shacl=True)
        assert proposal.achieved is False
        assert "failed" in proposal.reason

    def test_propose_not_achieved_on_partial_scope(self):
        from kairos_ontology.core.validator import propose_lifecycle_state

        results = {
            "syntax": {"passed": 1, "failed": 0},
            "imports": {"passed": 0, "failed": 0},
            "shacl": {"passed": 0, "failed": 0},
            "consistency": {"passed": 0, "failed": 0},
        }
        proposal = propose_lifecycle_state(results, do_syntax=True, do_shacl=False)
        assert proposal.achieved is False

    def test_to_dict_is_json_serializable(self):
        from kairos_ontology.core.validator import propose_lifecycle_state

        results = {
            "syntax": {"passed": 1, "failed": 0},
            "imports": {"passed": 0, "failed": 0},
            "shacl": {"passed": 1, "failed": 0},
            "consistency": {"passed": 0, "failed": 0},
        }
        proposal = propose_lifecycle_state(results, do_syntax=True, do_shacl=True)
        # Must not raise — proves the value is a plain, JSON-serializable dict.
        json.dumps(proposal.to_dict())


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


# ---------------------------------------------------------------------------
# Tests: Whitelist / mapping mismatch validation (DD-044)
# ---------------------------------------------------------------------------


class TestWhitelistMappingValidation:

    def test_whitelisted_not_mapped_warning(self, tmp_path):
        from kairos_ontology.core.validator import validate_whitelist_mapping

        ext_dir = tmp_path / "extensions"
        ext_dir.mkdir()
        (ext_dir / "client-silver-ext.ttl").write_text("""\
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix ref: <https://ref.example/party#> .
ref:Person kairos-ext:silverInclude true .
""", encoding="utf-8")

        # No mappings directory
        warnings = validate_whitelist_mapping(
            ontology_path=tmp_path,
            extensions_dir=ext_dir,
        )

        assert len(warnings) == 1
        assert warnings[0]["warning_type"] == "whitelisted_not_mapped"
        assert "Person" in warnings[0]["message"]

    def test_no_warnings_when_both_empty(self, tmp_path):
        from kairos_ontology.core.validator import validate_whitelist_mapping

        ext_dir = tmp_path / "extensions"
        ext_dir.mkdir()

        warnings = validate_whitelist_mapping(
            ontology_path=tmp_path,
            extensions_dir=ext_dir,
        )
        assert warnings == []
