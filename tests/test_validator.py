# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the validation module."""

import json

import pytest
from kairos_ontology.core.validator import (
    render_validation_markdown,
    run_validation,
    validate_gdpr,
    run_gdpr_validation,
    validate_naming_conventions,
)


class TestValidator:
    """Test the validation pipeline."""

    def test_syntax_validation_valid_file(self, temp_dir, sample_ontology, capsys):
        """Test syntax validation with valid ontology."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()

        ontology_file = ontologies_dir / "customer.ttl"
        ontology_file.write_text(sample_ontology, encoding="utf-8")

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
        assert "Syntax Validation" in captured.out
        assert "Passed:" in captured.out or "✓" in captured.out

    def test_syntax_validation_invalid_file(self, temp_dir, capsys):
        """Test syntax validation with invalid ontology."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()

        invalid_file = ontologies_dir / "invalid.ttl"
        invalid_file.write_text("Invalid Turtle @#$%", encoding="utf-8")

        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()

        with pytest.raises(SystemExit):
            run_validation(
                ontologies_path=ontologies_dir,
                shapes_path=shapes_dir,
                catalog_path=None,
                do_syntax=True,
                do_shacl=False,
                do_consistency=False,
            )

        captured = capsys.readouterr()
        assert "Failed:" in captured.out or "✗" in captured.out

    def test_empty_ontologies_directory(self, temp_dir, capsys):
        """Test validation with empty ontologies directory.

        Issue #309: a hub with zero authored ontologies must not print the
        same "all validations passed" success line as a hub with real,
        passing content -- that reads as a vacuous pass.
        """
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
            do_consistency=False,
        )

        captured = capsys.readouterr()
        assert "Found 0 ontology files" in captured.out
        assert "nothing was validated" in captured.out
        assert "✅ All validations passed!" not in captured.out

    def test_empty_ontologies_directory_report_marks_zero_files_found(
        self, temp_dir, capsys
    ):
        """Issue #309: the JSON report must be self-describing -- a consumer can
        check ``ontology_files_found == 0`` directly instead of inferring
        "vacuous" from all-zero counters."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()

        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()

        report_path = temp_dir / "validation-report.json"

        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False,
            report_path=report_path,
        )

        data = json.loads(report_path.read_text(encoding="utf-8"))
        assert data["ontology_files_found"] == 0

    def test_empty_ontologies_with_real_decisions_failure_still_fails(
        self, temp_dir, capsys
    ):
        """Issue #309: the new "nothing to validate" branch must never swallow an
        independent, real failure -- e.g. a malformed decision-log record -- that
        does not depend on ``ontology_files`` at all."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()

        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()

        decisions_dir = temp_dir / "decisions"
        decisions_dir.mkdir()
        (decisions_dir / "HUB-DD-001-broken.md").write_text(
            "no frontmatter here at all", encoding="utf-8"
        )

        with pytest.raises(SystemExit) as exc_info:
            run_validation(
                ontologies_path=ontologies_dir,
                shapes_path=shapes_dir,
                catalog_path=None,
                do_syntax=True,
                do_shacl=False,
                do_consistency=False,
                decisions_path=decisions_dir,
            )

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "❌ Validation failed" in captured.out
        assert "nothing was validated" not in captured.out

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

    def test_json_report_includes_non_writing_state_proposal(self, temp_dir, sample_ontology):
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
# Naming/annotation convention tests
# -----------------------------------------------------------------------


class TestNamingConventions:
    """Test the naming/annotation convention checks (validate_naming_conventions)."""

    def test_valid_ontology_passes(self, sample_ontology):
        result = validate_naming_conventions(sample_ontology)
        assert result["passed"] is True
        assert result["errors"] == []

    def test_missing_ontology_declaration_fails(self):
        content = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://kairos.example/ontology/> .

:Customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer entity" .
"""
        result = validate_naming_conventions(content)
        assert result["passed"] is False
        codes = {e["code"] for e in result["errors"]}
        assert "missing_ontology_declaration" in codes

    def test_multiple_ontology_declarations_fails(self):
        content = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://kairos.example/ontology/> .

:FirstOntology a owl:Ontology ;
    rdfs:label "First" ;
    owl:versionInfo "1.0" .

:SecondOntology a owl:Ontology ;
    rdfs:label "Second" ;
    owl:versionInfo "1.0" .
"""
        result = validate_naming_conventions(content)
        assert result["passed"] is False
        codes = {e["code"] for e in result["errors"]}
        assert "multiple_ontology_declarations" in codes

    def test_ontology_missing_label_and_version_fails(self):
        content = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix : <http://kairos.example/ontology/> .

:CustomerOntology a owl:Ontology .
"""
        result = validate_naming_conventions(content)
        assert result["passed"] is False
        codes = {e["code"] for e in result["errors"]}
        assert "ontology_missing_label" in codes
        assert "ontology_missing_version_info" in codes

    def test_class_missing_label_or_comment_fails(self):
        content = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://kairos.example/ontology/> .

:CustomerOntology a owl:Ontology ;
    rdfs:label "Customer Ontology" ;
    owl:versionInfo "1.0" .

:Customer a owl:Class .
"""
        result = validate_naming_conventions(content)
        assert result["passed"] is False
        codes = {e["code"] for e in result["errors"]}
        assert "class_missing_label" in codes
        assert "class_missing_comment" in codes

    def test_property_missing_label_domain_range_fails(self):
        content = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://kairos.example/ontology/> .

:CustomerOntology a owl:Ontology ;
    rdfs:label "Customer Ontology" ;
    owl:versionInfo "1.0" .

:Customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer entity" .

:customerName a owl:DatatypeProperty .
"""
        result = validate_naming_conventions(content)
        assert result["passed"] is False
        codes = {e["code"] for e in result["errors"]}
        assert "property_missing_label" in codes
        assert "property_missing_domain" in codes
        assert "property_missing_range" in codes

    def test_non_pascal_case_class_fails(self):
        content = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://kairos.example/ontology/> .

:CustomerOntology a owl:Ontology ;
    rdfs:label "Customer Ontology" ;
    owl:versionInfo "1.0" .

:customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer entity" .
"""
        result = validate_naming_conventions(content)
        assert result["passed"] is False
        codes = {e["code"] for e in result["errors"]}
        assert "class_name_not_pascal_case" in codes

    def test_non_camel_case_property_fails(self):
        content = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix : <http://kairos.example/ontology/> .

:CustomerOntology a owl:Ontology ;
    rdfs:label "Customer Ontology" ;
    owl:versionInfo "1.0" .

:Customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer entity" .

:CustomerName a owl:DatatypeProperty ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string ;
    rdfs:label "Customer Name" .
"""
        result = validate_naming_conventions(content)
        assert result["passed"] is False
        codes = {e["code"] for e in result["errors"]}
        assert "property_name_not_camel_case" in codes

    def test_term_declared_as_class_and_property_fails(self):
        content = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://kairos.example/ontology/> .

:CustomerOntology a owl:Ontology ;
    rdfs:label "Customer Ontology" ;
    owl:versionInfo "1.0" .

:Customer a owl:Class, owl:DatatypeProperty ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer entity" .
"""
        result = validate_naming_conventions(content)
        assert result["passed"] is False
        codes = {e["code"] for e in result["errors"]}
        assert "term_declared_as_multiple_types" in codes

    def test_naming_failure_propagates_through_run_validation(self, temp_dir, capsys):
        """Integration: a naming violation surfaces in results/exit code, distinct
        from syntax (the file still parses fine — only naming fails)."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        (ontologies_dir / "customer.ttl").write_text(
            """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://kairos.example/ontology/> .

:CustomerOntology a owl:Ontology ;
    rdfs:label "Customer Ontology" ;
    owl:versionInfo "1.0" .

:customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer entity" .
""",
            encoding="utf-8",
        )

        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()

        report_path = temp_dir / "output" / "validation-report.json"

        with pytest.raises(SystemExit):
            run_validation(
                ontologies_path=ontologies_dir,
                shapes_path=shapes_dir,
                catalog_path=None,
                do_syntax=True,
                do_shacl=False,
                do_consistency=False,
                report_path=report_path,
            )

        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["syntax"]["passed"] == 1
        assert payload["syntax"]["failed"] == 0
        assert payload["naming"]["failed"] == 1


class TestPhaseDAuthoringLints:
    """Phase D: authoring-quality warning lints (issues #474, #475 items 1–2).

    Three new warning-level checks added to ``validate_naming_conversations``:
    altLabel whitespace, ``#`` inside triple-quoted strings, and source-system
    name leakage in ``rdfs:comment``.
    """

    _BASE_TTL = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix : <http://kairos.example/ontology/> .

:CustomerOntology a owl:Ontology ;
    rdfs:label "Customer Ontology" ;
    owl:versionInfo "1.0" .

:Customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer entity" .
"""

    # ── D1: skos:altLabel whitespace (#475 item 2) ─────────────────────────

    def test_alt_label_whitespace_warns(self):
        """A skos:altLabel with leading/trailing whitespace produces a warning."""
        content = (
            self._BASE_TTL
            + """
:Customer skos:altLabel "  Spaced Customer  " .
"""
        )
        result = validate_naming_conventions(content)
        assert result["passed"] is True, result["errors"]
        ws_warnings = [w for w in result["warnings"] if w["code"] == "alt_label_whitespace"]
        assert len(ws_warnings) == 1, result["warnings"]
        assert ws_warnings[0]["level"] == "warning"
        assert "Spaced Customer" in ws_warnings[0]["message"]

    def test_alt_label_no_whitespace_does_not_warn(self):
        """A clean skos:altLabel produces no whitespace warning."""
        content = (
            self._BASE_TTL
            + """
:Customer skos:altLabel "Clean Customer" .
"""
        )
        result = validate_naming_conventions(content)
        ws_warnings = [w for w in result["warnings"] if w["code"] == "alt_label_whitespace"]
        assert ws_warnings == [], result["warnings"]

    # ── D2: # inside triple-quoted strings (#475 item 1) ───────────────────

    def test_hash_inside_triple_quoted_warns(self):
        """A line starting with # inside a triple-quoted string produces a warning."""
        content = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://kairos.example/ontology/> .

:CustomerOntology a owl:Ontology ;
    rdfs:label "Customer Ontology" ;
    rdfs:comment \"\"\"A customer entity.
# This looks like a comment but is part of the string.\"\"\" ;
    owl:versionInfo "1.0" .
"""
        result = validate_naming_conventions(content)
        assert result["passed"] is True, result["errors"]
        hash_warnings = [w for w in result["warnings"] if w["code"] == "hash_inside_triple_quoted_string"]
        assert len(hash_warnings) == 1, result["warnings"]
        assert hash_warnings[0]["level"] == "warning"

    def test_no_hash_in_triple_quoted_does_not_warn(self):
        """A triple-quoted string without # lines produces no hash warning."""
        content = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://kairos.example/ontology/> .

:CustomerOntology a owl:Ontology ;
    rdfs:label "Customer Ontology" ;
    rdfs:comment \"\"\"A customer entity. No hash lines here.\"\"\" ;
    owl:versionInfo "1.0" .
"""
        result = validate_naming_conventions(content)
        hash_warnings = [w for w in result["warnings"] if w["code"] == "hash_inside_triple_quoted_string"]
        assert hash_warnings == [], result["warnings"]

    # ── D3: Source-system name leakage (#474) ──────────────────────────────

    def test_source_system_name_in_comment_warns(self):
        """A known source-system name in rdfs:comment produces a warning."""
        content = (
            self._BASE_TTL
            + """
:customerName a owl:DatatypeProperty ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string ;
    rdfs:label "Customer Name" ;
    rdfs:comment "The customer name from SAP." .
"""
        )
        result = validate_naming_conventions(content)
        assert result["passed"] is True, result["errors"]
        leak_warnings = [w for w in result["warnings"] if w["code"] == "source_system_name_in_comment"]
        assert len(leak_warnings) == 1, result["warnings"]
        assert "SAP" in leak_warnings[0]["message"]

    def test_source_system_name_in_label_warns(self):
        """#501: labels leaked source-system names silently -- only comments were checked.

        A label is the *more* visible surface: it is what every downstream report, ERD and
        picker renders.
        """
        content = (
            self._BASE_TTL
            + """
:customerName a owl:DatatypeProperty ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string ;
    rdfs:label "SAP Customer Name" ;
    rdfs:comment "The name of the customer." .
"""
        )
        result = validate_naming_conventions(content)
        assert result["passed"] is True, result["errors"]
        leak = [w for w in result["warnings"] if w["code"] == "source_system_name_in_label"]
        assert len(leak) == 1, result["warnings"]
        assert "SAP" in leak[0]["message"]
        # The comment-scoped code must not fire for a label, so existing consumers
        # filtering on it keep their exact meaning.
        assert [w for w in result["warnings"] if w["code"] == "source_system_name_in_comment"] == []

    def test_source_system_name_in_alt_label_warns(self):
        content = (
            self._BASE_TTL
            + """
:customerName a owl:DatatypeProperty ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string ;
    rdfs:label "Customer Name" ;
    skos:altLabel "Workday Worker Name" ;
    rdfs:comment "The name of the customer." .
"""
        )
        result = validate_naming_conventions(content)
        leak = [w for w in result["warnings"] if w["code"] == "source_system_name_in_label"]
        assert len(leak) == 1, result["warnings"]
        assert "Workday" in leak[0]["message"]

    def test_no_source_system_name_does_not_warn(self):
        """A comment without source-system names produces no leakage warning."""
        content = (
            self._BASE_TTL
            + """
:customerName a owl:DatatypeProperty ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string ;
    rdfs:label "Customer Name" ;
    rdfs:comment "The name of the customer." .
"""
        )
        result = validate_naming_conventions(content)
        leak_warnings = [w for w in result["warnings"] if w["code"] == "source_system_name_in_comment"]
        assert leak_warnings == [], result["warnings"]

    def test_source_system_names_configurable(self):
        """Custom source_system_names parameter is used instead of defaults."""
        content = (
            self._BASE_TTL
            + """
:customerName a owl:DatatypeProperty ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string ;
    rdfs:label "Customer Name" ;
    rdfs:comment "Name from MyCustomERP." .
"""
        )
        # Default names won't match "MyCustomERP"; custom list will.
        result_default = validate_naming_conventions(content)
        assert [w for w in result_default["warnings"] if w["code"] == "source_system_name_in_comment"] == []

        result_custom = validate_naming_conventions(content, source_system_names=("MyCustomERP",))
        leak = [w for w in result_custom["warnings"] if w["code"] == "source_system_name_in_comment"]
        assert len(leak) == 1, result_custom["warnings"]
        assert "MyCustomERP" in leak[0]["message"]

    def test_source_system_names_empty_tuple_disables(self):
        """An empty tuple disables the check entirely."""
        content = (
            self._BASE_TTL
            + """
:customerName a owl:DatatypeProperty ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string ;
    rdfs:label "Customer Name" ;
    rdfs:comment "The customer name from SAP." .
"""
        )
        result = validate_naming_conventions(content, source_system_names=())
        leak = [w for w in result["warnings"] if w["code"] == "source_system_name_in_comment"]
        assert leak == [], result["warnings"]
    """DD-133 §7: an object property may defer its ``rdfs:range``.

    ``compile`` supports a ``relationships:`` entry whose object property declares no
    named ``rdfs:range`` — the reference-model ``deferred-relationship`` shape, validated
    on its authored ``target:``/``on:`` endpoint alone. ``validate`` used to hard-error
    exactly that shape, so the two halves of one package disagreed.
    """

    _HEADER = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix : <http://kairos.example/ontology/> .

:CustomerOntology a owl:Ontology ;
    rdfs:label "Customer Ontology" ;
    owl:versionInfo "1.0" .

:Customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer entity" .
"""

    def test_object_property_without_range_warns_and_passes(self):
        """A range-less object property is a warning, not an error, and does not fail."""
        content = (
            self._HEADER
            + """
:country a owl:ObjectProperty ;
    rdfs:label "Country" ;
    rdfs:domain :Customer .
"""
        )
        result = validate_naming_conventions(content)

        assert result["passed"] is True, result["errors"]
        assert not result["errors"]
        warnings = [w for w in result["warnings"] if w["code"] == "property_missing_range"]
        assert len(warnings) == 1, result["warnings"]
        assert warnings[0]["level"] == "warning"
        assert warnings[0]["term_uri"] == "http://kairos.example/ontology/country"
        assert "DD-133" in warnings[0]["message"]

    def test_datatype_property_without_range_still_errors_alongside_it(self):
        """The relaxation is scoped to object properties: a datatype sibling in the same
        file still hard-errors, so ``validate`` keeps demanding a scalar type."""
        content = (
            self._HEADER
            + """
:country a owl:ObjectProperty ;
    rdfs:label "Country" ;
    rdfs:domain :Customer .

:customerName a owl:DatatypeProperty ;
    rdfs:label "Customer Name" ;
    rdfs:domain :Customer .
"""
        )
        result = validate_naming_conventions(content)

        assert result["passed"] is False
        errors = [e for e in result["errors"] if e["code"] == "property_missing_range"]
        assert [e["term_uri"] for e in errors] == ["http://kairos.example/ontology/customerName"], (
            result["errors"]
        )
        warnings = [w for w in result["warnings"] if w["code"] == "property_missing_range"]
        assert [w["term_uri"] for w in warnings] == ["http://kairos.example/ontology/country"]

    def test_object_property_ranged_owl_thing_warns(self):
        """``rdfs:range owl:Thing`` is worse than omitting the range — the compiler's
        relationship guard rejects it while an omitted range compiles. Pinned end-to-end
        in ``tests/scenarios/test_scenario_object_property_fields.py``."""
        content = (
            self._HEADER
            + """
:country a owl:ObjectProperty ;
    rdfs:label "Country" ;
    rdfs:domain :Customer ;
    rdfs:range owl:Thing .
"""
        )
        result = validate_naming_conventions(content)

        assert result["passed"] is True, result["errors"]
        warnings = [w for w in result["warnings"] if w["code"] == "property_range_owl_thing"]
        assert len(warnings) == 1, result["warnings"]
        assert warnings[0]["level"] == "warning"
        assert warnings[0]["term_uri"] == "http://kairos.example/ontology/country"
        message = warnings[0]["message"]
        assert "worse than omitting" in message
        assert "safety.relationship-endpoint" in message
        assert "DD-133" in message
        # It is a *different* finding from the deferred-range one, not a relabelling.
        assert not [w for w in result["warnings"] if w["code"] == "property_missing_range"]

    def test_named_class_range_produces_no_range_finding(self):
        """Guard against the warning firing on every object property."""
        content = (
            self._HEADER
            + """
:Country a owl:Class ;
    rdfs:label "Country" ;
    rdfs:comment "A country" .

:country a owl:ObjectProperty ;
    rdfs:label "Country" ;
    rdfs:domain :Customer ;
    rdfs:range :Country .
"""
        )
        result = validate_naming_conventions(content)

        assert result["passed"] is True, result["errors"]
        assert result["warnings"] == []

    def test_property_domained_owl_thing_warns(self):
        """``rdfs:domain owl:Thing`` (issue #328, DD-204): a property whose domain
        resolves to owl:Thing attaches to no class in the semantic index, so it is
        invisible to the compiler and every projector -- the domain-side twin of
        ``property_range_owl_thing``. This catches it at author time for a hub's own
        domain files (reference-model files are never validated, DD-188)."""
        content = (
            self._HEADER
            + """
:preferredCarrierCode a owl:DatatypeProperty ;
    rdfs:label "Preferred Carrier Code" ;
    rdfs:domain owl:Thing ;
    rdfs:range xsd:string .
"""
        )
        result = validate_naming_conventions(content)

        assert result["passed"] is True, result["errors"]
        warnings = [w for w in result["warnings"] if w["code"] == "property_domain_owl_thing"]
        assert len(warnings) == 1, result["warnings"]
        assert warnings[0]["level"] == "warning"
        assert warnings[0]["term_uri"] == "http://kairos.example/ontology/preferredCarrierCode"
        message = warnings[0]["message"]
        assert "owl:Thing" in message
        assert "#328" in message
        # It is a *different* finding from the missing-domain error, not a relabelling.
        assert not [e for e in result["errors"] if e["code"] == "property_missing_domain"]

    def test_named_class_domain_produces_no_domain_finding(self):
        """Guard against the warning firing on every property."""
        content = (
            self._HEADER
            + """
:customerName a owl:DatatypeProperty ;
    rdfs:label "Customer Name" ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string .
"""
        )
        result = validate_naming_conventions(content)

        assert result["passed"] is True, result["errors"]
        assert not [w for w in result["warnings"] if w["code"] == "property_domain_owl_thing"]

    def test_deferred_range_does_not_fail_run_validation(self, temp_dir, capsys):
        """Integration: the shape ``compile`` supports no longer trips the exit code, and
        the warning is carried into the JSON report."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        (ontologies_dir / "customer.ttl").write_text(
            self._HEADER
            + """
:country a owl:ObjectProperty ;
    rdfs:label "Country" ;
    rdfs:domain :Customer .
""",
            encoding="utf-8",
        )
        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()
        report_path = temp_dir / "output" / "validation-report.json"

        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False,
            report_path=report_path,
        )

        assert "All validations passed" in capsys.readouterr().out
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["naming"]["failed"] == 0
        assert payload["naming"]["passed"] == 1
        codes = {w["code"] for w in payload["naming"]["warnings"]}
        assert codes == {"property_missing_range"}


class TestReusableDomainlessProperty:
    """Issue #367: a property whose ``rdfs:comment`` starts with the literal marker
    ``REUSABLE — no rdfs:domain by design`` is deliberately domainless (the reference
    models' escape from the subclass-identity-by-role anti-pattern for reusable
    properties like ``bsp/party#hasContact``/``#hasParty``) and must not trip
    ``property_missing_domain``."""

    _HEADER = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://kairos.example/ontology/> .

:CustomerOntology a owl:Ontology ;
    rdfs:label "Customer Ontology" ;
    owl:versionInfo "1.0" .
"""

    def test_marked_reusable_property_without_domain_passes(self):
        content = (
            self._HEADER
            + """
:hasContact a owl:ObjectProperty ;
    rdfs:label "has contact" ;
    rdfs:comment "REUSABLE — no rdfs:domain by design: typed specialisations attach to different subjects." ;
    rdfs:range :Contact .

:Contact a owl:Class ;
    rdfs:label "Contact" ;
    rdfs:comment "A contact" .
"""
        )
        result = validate_naming_conventions(content)

        assert result["passed"] is True, result["errors"]
        assert not [e for e in result["errors"] if e["code"] == "property_missing_domain"]
        assert not [w for w in result["warnings"] if w["code"] == "property_missing_domain"]

    def test_unmarked_property_without_domain_still_errors(self):
        content = (
            self._HEADER
            + """
:hasContact a owl:ObjectProperty ;
    rdfs:label "has contact" ;
    rdfs:comment "An ordinary, unrelated comment." ;
    rdfs:range :Contact .

:Contact a owl:Class ;
    rdfs:label "Contact" ;
    rdfs:comment "A contact" .
"""
        )
        result = validate_naming_conventions(content)

        errors = [e for e in result["errors"] if e["code"] == "property_missing_domain"]
        assert len(errors) == 1, result["errors"]

    def test_marker_as_substring_not_prefix_still_errors(self):
        """Pins prefix-only semantics: the marker must lead the comment, not merely
        appear somewhere inside it."""
        content = (
            self._HEADER
            + """
:hasContact a owl:ObjectProperty ;
    rdfs:label "has contact" ;
    rdfs:comment "See also: REUSABLE — no rdfs:domain by design." ;
    rdfs:range :Contact .

:Contact a owl:Class ;
    rdfs:label "Contact" ;
    rdfs:comment "A contact" .
"""
        )
        result = validate_naming_conventions(content)

        errors = [e for e in result["errors"] if e["code"] == "property_missing_domain"]
        assert len(errors) == 1, result["errors"]

    def test_marked_reusable_property_with_leading_whitespace_still_passes(self):
        """Proves the ``.strip()`` is load-bearing for a triple-quoted literal whose
        first line is blank before the marker starts."""
        content = (
            self._HEADER
            + """
:hasContact a owl:ObjectProperty ;
    rdfs:label "has contact" ;
    rdfs:comment \"\"\"
    REUSABLE — no rdfs:domain by design: leading blank line before the marker.\"\"\" ;
    rdfs:range :Contact .

:Contact a owl:Class ;
    rdfs:label "Contact" ;
    rdfs:comment "A contact" .
"""
        )
        result = validate_naming_conventions(content)

        assert not [e for e in result["errors"] if e["code"] == "property_missing_domain"]

    def test_marker_requires_exact_em_dash_not_hyphen(self):
        """Pins byte-exact matching: an ASCII hyphen lookalike does not satisfy the
        marker, guarding against a future 'helpful' dash normalization."""
        content = (
            self._HEADER
            + """
:hasContact a owl:ObjectProperty ;
    rdfs:label "has contact" ;
    rdfs:comment "REUSABLE - no rdfs:domain by design: ascii hyphen, not em-dash." ;
    rdfs:range :Contact .

:Contact a owl:Class ;
    rdfs:label "Contact" ;
    rdfs:comment "A contact" .
"""
        )
        result = validate_naming_conventions(content)

        errors = [e for e in result["errors"] if e["code"] == "property_missing_domain"]
        assert len(errors) == 1, result["errors"]


class TestTemporalQuartetSynonymBan:
    """Issue #364: the reference-models temporal-quartet pattern's
    ``synonym-for-estimated-or-requested`` anti-pattern, now enforceable since upstream
    closed its ``banned_name_tokens`` list and published exact matching semantics. Opt-in:
    only checked when a caller supplies the pattern's own anti_pattern dict."""

    _HEADER = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix : <http://kairos.example/ontology/> .
@prefix other: <http://other.example/ontology/> .

:CustomerOntology a owl:Ontology ;
    rdfs:label "Customer Ontology" ;
    owl:versionInfo "1.0" .

:Shipment a owl:Class ;
    rdfs:label "Shipment" ;
    rdfs:comment "A shipment" .
"""

    _RULE = {
        "banned_name_tokens": ["eta", "etd", "ata", "atd", "expected", "due"],
        "applies_to_ranges": ["xsd:dateTime", "xsd:date", "xsd:time"],
        "exemptions": [
            {"name": "dueDate", "reason": "BSP financial term of art."},
            {
                "name": "http://other.example/ontology/arrivalETA",
                "reason": "Source-fidelity exemption for this specific namespace only.",
            },
        ],
    }

    def _violations(self, result):
        return [w for w in result["warnings"] if w["code"] == "temporal_quartet_synonym_ban"]

    def test_requested_eta_on_datetime_property_violates(self):
        content = (
            self._HEADER
            + """
:requestedETA a owl:DatatypeProperty ;
    rdfs:label "requested ETA" ;
    rdfs:domain :Shipment ;
    rdfs:range xsd:dateTime .
"""
        )
        result = validate_naming_conventions(content, temporal_quartet_synonym_rule=self._RULE)

        violations = self._violations(result)
        assert len(violations) == 1, result["warnings"]
        assert violations[0]["term_uri"] == "http://kairos.example/ontology/requestedETA"
        assert "eta" in violations[0]["message"]

    def test_exempted_due_date_on_datetime_property_is_clean(self):
        content = (
            self._HEADER
            + """
:dueDate a owl:DatatypeProperty ;
    rdfs:label "due date" ;
    rdfs:domain :Shipment ;
    rdfs:range xsd:dateTime .
"""
        )
        result = validate_naming_conventions(content, temporal_quartet_synonym_rule=self._RULE)

        assert self._violations(result) == []

    def test_has_wagon_at_departure_is_clean(self):
        """Acronym-boundary regression guard: 'atd' spans the At/Departure boundary as
        letters but never as a whole token, so this must not violate."""
        content = (
            self._HEADER
            + """
:hasWagonAtDeparture a owl:DatatypeProperty ;
    rdfs:label "has wagon at departure" ;
    rdfs:domain :Shipment ;
    rdfs:range xsd:dateTime .
"""
        )
        result = validate_naming_conventions(content, temporal_quartet_synonym_rule=self._RULE)

        assert self._violations(result) == []

    def test_eta_named_property_out_of_scope_range_is_clean(self):
        content = (
            self._HEADER
            + """
:etaNote a owl:DatatypeProperty ;
    rdfs:label "eta note" ;
    rdfs:domain :Shipment ;
    rdfs:range xsd:string .
"""
        )
        result = validate_naming_conventions(content, temporal_quartet_synonym_rule=self._RULE)

        assert self._violations(result) == []

    def test_full_iri_exemption_matches_only_that_namespace(self):
        """Same local name (a genuine violation -- 'ETA' is a whole banned token) in two
        namespaces; only the one NOT named by its full IRI in exemptions[] violates."""
        content = (
            self._HEADER
            + """
:arrivalETA a owl:DatatypeProperty ;
    rdfs:label "arrival ETA" ;
    rdfs:domain :Shipment ;
    rdfs:range xsd:dateTime .

other:arrivalETA a owl:DatatypeProperty ;
    rdfs:label "arrival ETA" ;
    rdfs:domain :Shipment ;
    rdfs:range xsd:dateTime .
"""
        )
        result = validate_naming_conventions(content, temporal_quartet_synonym_rule=self._RULE)

        violations = self._violations(result)
        assert [v["term_uri"] for v in violations] == [
            "http://kairos.example/ontology/arrivalETA"
        ], result["warnings"]

    def test_due_date_snake_case_tokenizes_correctly(self):
        content = (
            self._HEADER
            + """
:due_date a owl:DatatypeProperty ;
    rdfs:label "due date" ;
    rdfs:domain :Shipment ;
    rdfs:range xsd:date .
"""
        )
        rule = {**self._RULE, "exemptions": []}
        result = validate_naming_conventions(content, temporal_quartet_synonym_rule=rule)

        assert len(self._violations(result)) == 1

    def test_no_reference_models_checkout_degrades_gracefully(self, temp_dir, capsys):
        """Integration: with no --ref-models resolvable, the check is skipped entirely --
        no crash, no finding -- even against an ontology that would otherwise violate."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        (ontologies_dir / "shipment.ttl").write_text(
            self._HEADER
            + """
:requestedETA a owl:DatatypeProperty ;
    rdfs:label "requested ETA" ;
    rdfs:domain :Shipment ;
    rdfs:range xsd:dateTime .
""",
            encoding="utf-8",
        )
        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()

        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False,
            ref_models_dir=None,
        )

        assert "All validations passed" in capsys.readouterr().out


class TestConsoleWarningsVisibility:
    """Issue #332: `validate` rendered warnings in the Markdown/JSON report but not on
    the console, so a run with an open warning printed an unqualified
    ``Passed: N, Failed: 0`` per-section line and an unqualified
    ``All validations passed!`` summary -- exactly as if no warning existed."""

    _HEADER = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix : <http://kairos.example/ontology/> .

:CustomerOntology a owl:Ontology ;
    rdfs:label "Customer Ontology" ;
    owl:versionInfo "1.0" .

:Customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer entity" .
"""

    def _write_hub_with_owl_thing_warning(self, temp_dir):
        """A hub with a real ``property_range_owl_thing`` warning: an object property
        whose ``rdfs:range`` is ``owl:Thing`` -- the exact scenario from issue #332."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        (ontologies_dir / "customer.ttl").write_text(
            self._HEADER
            + """
:hasMasterWaybill a owl:ObjectProperty ;
    rdfs:label "Has Master Waybill" ;
    rdfs:domain :Customer ;
    rdfs:range owl:Thing .
""",
            encoding="utf-8",
        )
        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()
        return ontologies_dir, shapes_dir

    def test_section_line_shows_warning_count_when_open(self, temp_dir, capsys):
        """(a) The naming section's console summary line must show ``Warnings: 1``
        when one warning is open in that section -- mirroring the existing
        ``Passed: N, Failed: N`` pattern."""
        ontologies_dir, shapes_dir = self._write_hub_with_owl_thing_warning(temp_dir)

        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False,
        )

        out = capsys.readouterr().out
        assert "Naming/annotation — Passed: 1, Failed: 0, Warnings: 1" in out
        # The warning itself is also printed under its section (mirroring
        # render_validation_markdown's per-section warning rendering).
        assert "property_range_owl_thing" in out or "owl:Thing" in out

    def test_final_summary_not_unqualified_when_warning_open(self, temp_dir, capsys):
        """(b) The final console summary must not be an unqualified
        "All validations passed!" when a warning is open -- it must name the
        warning count (or the warning text) instead."""
        ontologies_dir, shapes_dir = self._write_hub_with_owl_thing_warning(temp_dir)

        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False,
        )

        out = capsys.readouterr().out
        assert "All validations passed!" not in out
        assert "All validations passed" in out
        assert "1 warning(s)" in out or "warning" in out.lower()

    def test_clean_hub_still_prints_unqualified_pass(self, temp_dir, sample_ontology, capsys):
        """(c) No regression for the clean case: zero warnings and zero errors still
        print the original unqualified "All validations passed!" line.

        Issue #393's `_master.ttl` import-sync check is unconditional, so a "clean"
        hub here must also carry a `_master.ttl` that actually imports the one
        authored domain -- otherwise that check's own advisory warning would open,
        which is exactly what a sibling test class covers on its own.
        """
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        (ontologies_dir / "customer.ttl").write_text(sample_ontology, encoding="utf-8")
        (ontologies_dir / "_master.ttl").write_text(
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n\n"
            "<http://kairos.example/ontology/master> a owl:Ontology ;\n"
            '    rdfs:label "Master"@en ;\n'
            '    owl:versionInfo "1.0.0" .\n\n'
            "<http://kairos.example/ontology/master> owl:imports "
            "<http://kairos.example/ontology/CustomerOntology> .\n",
            encoding="utf-8",
        )
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

        out = capsys.readouterr().out
        assert "All validations passed!" in out
        assert "Warnings:" not in out

    def test_exit_code_unaffected_by_open_warning(self, temp_dir):
        """(d) Exit code remains 0 when only warnings (no errors) are present --
        this is purely a console-visibility fix, not an exit-code change."""
        ontologies_dir, shapes_dir = self._write_hub_with_owl_thing_warning(temp_dir)

        # run_validation() only calls exit() on failure; it must return normally
        # (no SystemExit) when the sole finding is a warning.
        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False,
        )


class TestMarkdownReportWarnings:
    """``render_validation_markdown`` used to key off ``errors`` only and ``continue`` on
    an empty list, so a warning could never reach the report at all."""

    _RENDER_KWARGS = dict(
        toolkit_version="9.9.9",
        catalog_path=None,
        ref_models_dir=None,
        accelerator=None,
        do_syntax=True,
        do_shacl=False,
        do_consistency=False,
        degraded=False,
        ontology_files=[],
    )

    def _render(self, results, tmp_path):
        return render_validation_markdown(
            results,
            ontologies_path=tmp_path / "ontologies",
            shapes_path=tmp_path / "shapes",
            **self._RENDER_KWARGS,
        )

    def test_naming_warnings_are_rendered_and_counted(self, tmp_path):
        markdown = self._render(
            {
                "naming": {
                    "passed": 1,
                    "failed": 0,
                    "errors": [],
                    "warnings": [
                        {
                            "level": "warning",
                            "code": "property_missing_range",
                            "message": "Object property :country is missing rdfs:range.",
                            "term_uri": "http://kairos.example/ontology/country",
                            "file": "customer.ttl",
                        }
                    ],
                },
            },
            tmp_path,
        )

        assert "| Check | Passed | Failed | Warnings |" in markdown
        assert "| naming | 1 | 0 | 1 |" in markdown
        assert "### Naming warnings" in markdown
        assert "- `customer.ttl`: Object property :country is missing rdfs:range." in markdown
        # Warnings must not be re-reported as errors.
        assert "### Naming errors" not in markdown

    def test_errors_precede_warnings_and_rendering_is_deterministic(self, tmp_path):
        results = {
            "naming": {
                "passed": 0,
                "failed": 1,
                "errors": [
                    {"code": "b_error", "message": "beta error", "file": "b.ttl"},
                    {"code": "a_error", "message": "alpha error", "file": "a.ttl"},
                ],
                "warnings": [
                    {"code": "b_warn", "message": "beta warning", "file": "b.ttl"},
                    {"code": "a_warn", "message": "alpha warning", "file": "a.ttl"},
                ],
            },
        }

        markdown = self._render(results, tmp_path)

        assert markdown == self._render(results, tmp_path)
        assert markdown.index("### Naming errors") < markdown.index("### Naming warnings")
        # Sorted by _finding_sort_key (DD-120), not by authored order.
        assert markdown.index("alpha error") < markdown.index("beta error")
        assert markdown.index("alpha warning") < markdown.index("beta warning")

    def test_sections_without_warnings_key_are_not_mandatory(self, tmp_path):
        """Callers build partial ``results`` dicts; every section stays optional."""
        markdown = self._render({"syntax": {"passed": 2, "failed": 0, "errors": []}}, tmp_path)

        assert "| syntax | 2 | 0 | 0 |" in markdown
        assert "| decisions | 0 | 0 | 0 |" in markdown
        assert "warnings" not in markdown.split("## Findings")[1].replace("| Warnings |", "")


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


# Issue #325: false positives on a governed code (xsd:string, name ends in "Code")
# and a boolean flag, both matching the "address" keyword as a bare substring.
_ONTOLOGY_FALSE_POSITIVES = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <http://example.org/ont/reference-data#> .

ex:ReferenceDataOntology a owl:Ontology ;
    rdfs:label "Reference Data" ;
    owl:versionInfo "1.0" .

ex:Address a owl:Class ;
    rdfs:label "Address" ;
    rdfs:comment "A governed address record" .

ex:addressCode a owl:DatatypeProperty ;
    rdfs:domain ex:Address ;
    rdfs:range xsd:string ;
    rdfs:label "Address Code" .

ex:AddressRoleAssignment a owl:Class ;
    rdfs:label "Address Role Assignment" ;
    rdfs:comment "Marks an address as playing a role for a party" .

ex:isMainAddressRole a owl:DatatypeProperty ;
    rdfs:domain ex:AddressRoleAssignment ;
    rdfs:range xsd:boolean ;
    rdfs:label "Is Main Address Role" .
"""

# Regression: numeric/temporal properties must keep being name-matched (#302 caveat) --
# a datetime named for a PII keyword is genuinely sensitive.
_ONTOLOGY_TEMPORAL_KEYWORD_MATCH = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <http://example.org/ont/party#> .

ex:PartyOntology a owl:Ontology ;
    rdfs:label "Party" ;
    owl:versionInfo "1.0" .

ex:Employee a owl:Class ;
    rdfs:label "Employee" ;
    rdfs:comment "An employee" .

ex:dateOfBirth a owl:DatatypeProperty ;
    rdfs:domain ex:Employee ;
    rdfs:range xsd:dateTime ;
    rdfs:label "Date Of Birth" .
"""

# Binding-sourced false negative: StaffMember's own canonical property ("role") carries
# no PII keyword, but its bound source table has birthdate/passport columns.
_ONTOLOGY_STAFF_MEMBER = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix party: <http://example.org/ont/party#> .

party:PartyOntology a owl:Ontology ;
    rdfs:label "Party" ;
    owl:versionInfo "1.0" .

party:StaffMember a owl:Class ;
    rdfs:label "Staff Member" ;
    rdfs:comment "A staff member" .

party:role a owl:DatatypeProperty ;
    rdfs:domain party:StaffMember ;
    rdfs:range xsd:string ;
    rdfs:label "Role" .
"""

_STAFF_BINDING_YAML = """\
apiVersion: kairos.eu/v5
kind: EntityBinding
metadata:
  name: hr-staff-to-party
  domain: party
source:
  relation: hr.StaffMember
target:
  class: party:StaffMember
grain:
  columns: [staff_id]
identity:
  strategy: source-natural
  sourceKey: [staff_id]
load:
  mode: full-refresh
fields:
  - property: party:role
    expression: role
"""

_STAFF_SOURCE_VOCAB_TTL = """\
@prefix src: <https://example.test/source/hr#> .
@prefix kb: <https://kairos.cnext.eu/bronze#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

src:hr a kb:SourceSystem ; rdfs:label "hr" ;
  kb:database "hr_raw" ; kb:schema "dbo" ; kb:connectionType "jdbc" .

src:StaffMember a kb:SourceTable ; kb:sourceSystem src:hr ;
  kb:tableName "StaffMember" ; kb:primaryKeyColumns "staff_id" .
src:staff_id a kb:SourceColumn ; kb:sourceTable src:StaffMember ;
  kb:columnName "staff_id" ; kb:dataType "varchar(30)" ;
  kb:nullable "false"^^xsd:boolean .
src:staff_role a kb:SourceColumn ; kb:sourceTable src:StaffMember ;
  kb:columnName "role" ; kb:dataType "varchar(50)" ;
  kb:nullable "true"^^xsd:boolean .
src:staff_dob a kb:SourceColumn ; kb:sourceTable src:StaffMember ;
  kb:columnName "DateOfBirth" ; kb:dataType "date" ;
  kb:nullable "true"^^xsd:boolean .
src:staff_passport a kb:SourceColumn ; kb:sourceTable src:StaffMember ;
  kb:columnName "PassportNumber" ; kb:dataType "varchar(30)" ;
  kb:nullable "true"^^xsd:boolean .
src:staff_kin a kb:SourceColumn ; kb:sourceTable src:StaffMember ;
  kb:columnName "NextOfKinName" ; kb:dataType "varchar(200)" ;
  kb:nullable "true"^^xsd:boolean .
"""


def _write_staff_hub(hub_root):
    """Build a minimal hub with a StaffMember binding sourced from person-shaped columns."""
    bindings_dir = hub_root / "integration" / "bindings"
    bindings_dir.mkdir(parents=True)
    (bindings_dir / "hr-staff.binding.yaml").write_text(_STAFF_BINDING_YAML, encoding="utf-8")

    sources_dir = hub_root / "integration" / "sources" / "hr"
    sources_dir.mkdir(parents=True)
    (sources_dir / "hr.vocabulary.ttl").write_text(_STAFF_SOURCE_VOCAB_TTL, encoding="utf-8")

    ontologies_dir = hub_root / "model" / "ontologies"
    ontologies_dir.mkdir(parents=True)
    (ontologies_dir / "party.ttl").write_text(_ONTOLOGY_STAFF_MEMBER, encoding="utf-8")
    return ontologies_dir


class TestGdprDatatypeAndBindingEvidence:
    """Issue #325: datatype/name-shape gates on false positives, binding-sourced evidence
    on the false negative, and the non-blocking-but-honest summary line."""

    def test_boolean_property_not_flagged(self):
        """A boolean flag can't carry an address -- isMainAddressRole must not warn."""
        result = validate_gdpr(_ONTOLOGY_FALSE_POSITIVES)
        flagged_properties = {w["property"] for w in result["warnings"]}
        assert "isMainAddressRole" not in flagged_properties

    def test_governed_code_property_not_flagged(self):
        """A short reference code can't carry an address -- addressCode must not warn."""
        result = validate_gdpr(_ONTOLOGY_FALSE_POSITIVES)
        flagged_properties = {w["property"] for w in result["warnings"]}
        assert "addressCode" not in flagged_properties

    def test_false_positive_ontology_now_passes_clean(self):
        """Both known real-hub false positives are gone; nothing else in the fixture
        should spuriously trip either gate."""
        result = validate_gdpr(_ONTOLOGY_FALSE_POSITIVES)
        assert result["passed"] is True
        assert result["warnings"] == []

    def test_temporal_property_keyword_match_still_flagged(self):
        """#302 caveat: a non-string (here xsd:dateTime) property named for a PII
        keyword is still genuinely sensitive and must still be flagged."""
        result = validate_gdpr(_ONTOLOGY_TEMPORAL_KEYWORD_MATCH)
        assert result["passed"] is False
        keywords_found = {w["keyword"] for w in result["warnings"]}
        assert "date_of_birth" in keywords_found

    def test_source_evidence_flags_class_with_non_pii_named_property(self):
        """A class bound to a source relation with person-shaped columns (birthdate,
        passport) must be flagged even though its own canonical property ("role")
        carries no PII keyword."""
        source_evidence = {
            "StaffMember": [
                ("hr.StaffMember", "DateOfBirth", "date_of_birth"),
                ("hr.StaffMember", "PassportNumber", "passport"),
            ]
        }
        result = validate_gdpr(_ONTOLOGY_STAFF_MEMBER, source_evidence=source_evidence)
        assert result["passed"] is False
        assert any(w["class"] == "StaffMember" for w in result["warnings"])
        assert all(w.get("evidence") == "source-binding" for w in result["warnings"])

    def test_source_evidence_respects_gdpr_satellite_protection(self):
        """A class already protected by gdprSatelliteOf must not gain a new warning
        just because binding-sourced evidence exists."""
        extension = """\
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix party: <http://example.org/ont/party#> .

party:StaffMemberPII
    kairos-ext:gdprSatelliteOf party:StaffMember .
"""
        source_evidence = {"StaffMember": [("hr.StaffMember", "PassportNumber", "passport")]}
        result = validate_gdpr(
            _ONTOLOGY_STAFF_MEMBER, extension, source_evidence=source_evidence
        )
        assert result["passed"] is True
        assert result["warnings"] == []

    def test_source_evidence_ignored_for_unbound_class(self):
        """Evidence keyed by a class local name absent from the ontology is a no-op,
        not a crash."""
        result = validate_gdpr(
            _ONTOLOGY_STAFF_MEMBER,
            source_evidence={"SomeOtherClass": [("x.y", "Passport", "passport")]},
        )
        assert result["passed"] is True

    def test_binding_source_evidence_end_to_end(self, tmp_path, capsys):
        """Integration: run_gdpr_validation resolves the real binding + source vocabulary
        TTL from disk and flags StaffMember via its source columns."""
        from kairos_ontology.core.validator import run_gdpr_validation

        hub_root = tmp_path / "hub"
        ontologies_dir = _write_staff_hub(hub_root)

        total = run_gdpr_validation(ontologies_path=ontologies_dir, hub_root=hub_root)
        captured = capsys.readouterr()
        assert total > 0
        assert "StaffMember" in captured.out
        assert "hr.StaffMember" in captured.out

    def test_binding_source_evidence_defaults_hub_root_from_ontologies_path(self, tmp_path):
        """When hub_root is omitted, the <hub>/model/ontologies convention is assumed."""
        from kairos_ontology.core.validator import run_gdpr_validation

        hub_root = tmp_path / "hub"
        ontologies_dir = _write_staff_hub(hub_root)

        total = run_gdpr_validation(ontologies_path=ontologies_dir)
        assert total > 0

    def test_no_bindings_directory_is_a_no_op(self, temp_dir, capsys):
        """A hub with no integration/bindings at all must not crash the scan."""
        from kairos_ontology.core.validator import run_gdpr_validation

        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        (ontologies_dir / "service.ttl").write_text(_ONTOLOGY_NO_PII, encoding="utf-8")

        total = run_gdpr_validation(ontologies_path=ontologies_dir)
        assert total == 0


class TestGdprWarningsSummaryLine:
    """Issue #325: `validate` must not print an unqualified "All validations passed!"
    while GDPR warnings are open, even though the scan stays non-blocking (exit 0)."""

    def test_default_message_unchanged_when_no_gdpr_warnings(self, temp_dir, sample_ontology):
        """gdpr_warnings defaults to 0, so existing callers/messages are unaffected."""
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

    def test_summary_qualified_when_gdpr_warnings_open(self, temp_dir, sample_ontology, capsys):
        """With unresolved GDPR warnings, the summary must not claim a clean bill of
        health, but must still not raise SystemExit (non-blocking, per issue #325)."""
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
            gdpr_warnings=2,
        )

        captured = capsys.readouterr()
        assert "All validations passed" in captured.out
        assert "2 unprotected PII warning" in captured.out


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
        (ext_dir / "client-silver-ext.ttl").write_text(
            """\
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix ref: <https://ref.example/party#> .
ref:Person kairos-ext:silverInclude true .
""",
            encoding="utf-8",
        )

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


def _master_import_domain_ttl(iri: str, name: str) -> str:
    return (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n\n"
        f"<{iri}> a owl:Ontology ;\n"
        f'    rdfs:label "{name}"@en ;\n'
        f'    owl:versionInfo "1.0.0" .\n'
    )


class TestMasterImportSyncWarning:
    """The `_master.ttl` owl:imports advisory check (issue #393)."""

    def _run(self, ontologies_dir, tmp_path, report_path=None):
        shapes_dir = tmp_path / "shapes"
        shapes_dir.mkdir(exist_ok=True)
        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=False,
            do_shacl=False,
            do_consistency=False,
            report_path=report_path,
        )

    def test_out_of_sync_domain_produces_warning(self, tmp_path):
        ontologies_dir = tmp_path / "ontologies"
        ontologies_dir.mkdir()
        (ontologies_dir / "party.ttl").write_text(
            _master_import_domain_ttl("https://acme.test/ont/party", "Party"),
            encoding="utf-8",
        )
        (ontologies_dir / "_master.ttl").write_text(
            _master_import_domain_ttl("https://acme.test/ont/master", "Master"),
            encoding="utf-8",
        )

        report_path = tmp_path / "validation-report.json"
        self._run(ontologies_dir, tmp_path, report_path=report_path)

        payload = json.loads(report_path.read_text(encoding="utf-8"))
        warnings = payload["imports"]["warnings"]
        assert len(warnings) == 1
        assert "party" in warnings[0]["message"]
        assert "does not import" in warnings[0]["message"]
        assert "https://acme.test/ont/party" in warnings[0]["message"]
        assert "init --domain party" in warnings[0]["message"]

    def test_fully_in_sync_produces_no_warning(self, tmp_path):
        ontologies_dir = tmp_path / "ontologies"
        ontologies_dir.mkdir()
        (ontologies_dir / "party.ttl").write_text(
            _master_import_domain_ttl("https://acme.test/ont/party", "Party"),
            encoding="utf-8",
        )
        (ontologies_dir / "_master.ttl").write_text(
            _master_import_domain_ttl("https://acme.test/ont/master", "Master")
            + "\n<https://acme.test/ont/master> owl:imports <https://acme.test/ont/party> .\n",
            encoding="utf-8",
        )

        report_path = tmp_path / "validation-report.json"
        self._run(ontologies_dir, tmp_path, report_path=report_path)

        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["imports"]["warnings"] == []

    def test_missing_master_ttl_produces_one_warning_not_a_crash(self, tmp_path):
        ontologies_dir = tmp_path / "ontologies"
        ontologies_dir.mkdir()
        (ontologies_dir / "party.ttl").write_text(
            _master_import_domain_ttl("https://acme.test/ont/party", "Party"),
            encoding="utf-8",
        )
        # No _master.ttl at all.

        report_path = tmp_path / "validation-report.json"
        self._run(ontologies_dir, tmp_path, report_path=report_path)

        payload = json.loads(report_path.read_text(encoding="utf-8"))
        warnings = payload["imports"]["warnings"]
        assert len(warnings) == 1
        assert "_master.ttl not found" in warnings[0]["message"]

    def test_malformed_master_ttl_warns_instead_of_crashing(self, tmp_path):
        ontologies_dir = tmp_path / "ontologies"
        ontologies_dir.mkdir()
        (ontologies_dir / "party.ttl").write_text(
            _master_import_domain_ttl("https://acme.test/ont/party", "Party"),
            encoding="utf-8",
        )
        (ontologies_dir / "_master.ttl").write_text(
            "this is not valid turtle {{{ owl:imports <><><", encoding="utf-8"
        )

        report_path = tmp_path / "validation-report.json"
        self._run(ontologies_dir, tmp_path, report_path=report_path)

        payload = json.loads(report_path.read_text(encoding="utf-8"))
        warnings = payload["imports"]["warnings"]
        assert len(warnings) == 1
        assert "_master.ttl" in warnings[0]["message"]

    def test_markdown_report_renders_the_warning_via_existing_imports_section(self, tmp_path):
        ontologies_dir = tmp_path / "ontologies"
        ontologies_dir.mkdir()
        (ontologies_dir / "party.ttl").write_text(
            _master_import_domain_ttl("https://acme.test/ont/party", "Party"),
            encoding="utf-8",
        )
        (ontologies_dir / "_master.ttl").write_text(
            _master_import_domain_ttl("https://acme.test/ont/master", "Master"),
            encoding="utf-8",
        )
        shapes_dir = tmp_path / "shapes"
        shapes_dir.mkdir()
        markdown_report_path = tmp_path / "validation-report.md"

        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=False,
            do_shacl=False,
            do_consistency=False,
            markdown_report_path=markdown_report_path,
        )

        markdown = markdown_report_path.read_text(encoding="utf-8")
        assert "Imports warnings" in markdown
        assert "does not import" in markdown


# ---------------------------------------------------------------------------
# Issue #471 (E7-modes-served): modes_served filtering through run_validation
# ---------------------------------------------------------------------------

def test_validate_managed_imports_with_modes_served_skips_mode_specific(tmp_path):
    """validate_managed_imports honors modes_served and skips mode-specific
    imports whose mode is not served."""
    from kairos_ontology.core.reference_modules import (
        build_reference_module_context,
    )
    from kairos_ontology.core.validator import validate_managed_imports

    ref_models = tmp_path / "reference-models"
    blueprint = ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint"
    blueprint.mkdir(parents=True)

    config_path = blueprint / "data-domains.yaml"
    module_iri = "https://example.org/reference/orders"
    term_ns = module_iri + "#"

    (ref_models / "modules").mkdir()
    (ref_models / "modules" / "orders.ttl").write_text(
        f"""\
@prefix ex: <{term_ns}> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<{module_iri}> a owl:Ontology ; owl:versionInfo "2.1.0" .
ex:Order a owl:Class .
ex:SpecialOrder a owl:Class ; rdfs:subClassOf ex:Order .
""",
        encoding="utf-8",
    )
    config_path.write_text(
        f"""\
schema_version: "2.0"
module_profiles:
  - id: orders
    ontology_iri: {module_iri}
    catalog_uri: {term_ns}
    version_pin: 2.1.0
    term_namespaces: [{term_ns}]
    root_classes: [{term_ns}Order]
groups:
  - id: operations
    domains:
      - id: orders
        mode: interactive
        imports:
          - profile: orders
""",
        encoding="utf-8",
    )
    catalog = ref_models / "catalog-v001.xml"
    catalog.write_text(
        f"""\
<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <uri name="{term_ns}" uri="modules/orders.ttl"/>
  <uri name="{module_iri}" uri="modules/orders.ttl"/>
</catalog>
""",
        encoding="utf-8",
    )

    context = build_reference_module_context(
        ref_models, catalog_path=catalog, accelerator="generic"
    )

    ontologies_dir = tmp_path / "ontologies"
    ontologies_dir.mkdir()
    ontology_file = ontologies_dir / "orders.ttl"
    ontology_file.write_text(
        """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://example.org/hub/orders> a owl:Ontology ;
    rdfs:label "Orders"@en .
""",
        encoding="utf-8",
    )

    # modes_served=None (default): import IS required and missing → error
    diagnostics_all = validate_managed_imports(
        ontology_file, module_context=context, modes_served=None
    )
    missing_all = [d for d in diagnostics_all if d.code == "missing_managed_import"]
    assert missing_all

    # modes_served=["dataplatform"]: import is skipped → no missing_managed_import
    diagnostics_filtered = validate_managed_imports(
        ontology_file, module_context=context, modes_served=["dataplatform"]
    )
    missing_filtered = [d for d in diagnostics_filtered if d.code == "missing_managed_import"]
    assert missing_filtered == []

    # modes_served=["interactive"]: import IS included → missing_managed_import present
    diagnostics_match = validate_managed_imports(
        ontology_file, module_context=context, modes_served=["interactive"]
    )
    missing_match = [d for d in diagnostics_match if d.code == "missing_managed_import"]
    assert missing_match


def test_run_validation_modes_served_filters_mode_specific(tmp_path):
    """run_validation with modes_served skips mode-specific managed imports."""

    ref_models = tmp_path / "reference-models"
    blueprint = ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint"
    blueprint.mkdir(parents=True)

    config_path = blueprint / "data-domains.yaml"
    module_iri = "https://example.org/reference/orders"
    term_ns = module_iri + "#"

    (ref_models / "modules").mkdir()
    (ref_models / "modules" / "orders.ttl").write_text(
        f"""\
@prefix ex: <{term_ns}> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<{module_iri}> a owl:Ontology ; owl:versionInfo "2.1.0" .
ex:Order a owl:Class .
""",
        encoding="utf-8",
    )
    config_path.write_text(
        f"""\
module_profiles:
  - id: orders
    ontology_iri: {module_iri}
    catalog_uri: {term_ns}
    version_pin: 2.1.0
    term_namespaces: [{term_ns}]
    root_classes: [{term_ns}Order]
groups:
  - id: operations
    domains:
      - id: orders
        mode: interactive
        imports:
          - profile: orders
""",
        encoding="utf-8",
    )
    catalog = ref_models / "catalog-v001.xml"
    catalog.write_text(
        f"""\
<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <uri name="{term_ns}" uri="modules/orders.ttl"/>
  <uri name="{module_iri}" uri="modules/orders.ttl"/>
</catalog>
""",
        encoding="utf-8",
    )

    ontologies_dir = tmp_path / "ontologies"
    ontologies_dir.mkdir()
    (ontologies_dir / "orders.ttl").write_text(
        """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://example.org/hub/orders> a owl:Ontology ;
    rdfs:label "Orders"@en ;
    rdfs:comment "Orders domain."@en ;
    owl:versionInfo "0.1.0" .
""",
        encoding="utf-8",
    )

    # Without modes_served: the import is required and missing → validation fails
    with pytest.raises(SystemExit):
        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=tmp_path / "shapes",
            catalog_path=catalog,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False,
            ref_models_dir=ref_models,
            accelerator="generic",
            modes_served=None,
        )

    # With modes_served=["dataplatform"]: the import is skipped → validation passes
    run_validation(
        ontologies_path=ontologies_dir,
        shapes_path=tmp_path / "shapes",
        catalog_path=catalog,
        do_syntax=True,
        do_shacl=False,
        do_consistency=False,
        ref_models_dir=ref_models,
        accelerator="generic",
        modes_served=["dataplatform"],
    )
