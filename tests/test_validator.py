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
            do_consistency=False,
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


class TestObjectPropertyDeferredRange:
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
  relation: hr.GlbStaff
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

src:GlbStaff a kb:SourceTable ; kb:sourceSystem src:hr ;
  kb:tableName "GlbStaff" ; kb:primaryKeyColumns "staff_id" .
src:staff_id a kb:SourceColumn ; kb:sourceTable src:GlbStaff ;
  kb:columnName "staff_id" ; kb:dataType "varchar(30)" ;
  kb:nullable "false"^^xsd:boolean .
src:staff_role a kb:SourceColumn ; kb:sourceTable src:GlbStaff ;
  kb:columnName "role" ; kb:dataType "varchar(50)" ;
  kb:nullable "true"^^xsd:boolean .
src:staff_dob a kb:SourceColumn ; kb:sourceTable src:GlbStaff ;
  kb:columnName "DateOfBirth" ; kb:dataType "date" ;
  kb:nullable "true"^^xsd:boolean .
src:staff_passport a kb:SourceColumn ; kb:sourceTable src:GlbStaff ;
  kb:columnName "PassportNumber" ; kb:dataType "varchar(30)" ;
  kb:nullable "true"^^xsd:boolean .
src:staff_kin a kb:SourceColumn ; kb:sourceTable src:GlbStaff ;
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
                ("hr.GlbStaff", "DateOfBirth", "date_of_birth"),
                ("hr.GlbStaff", "PassportNumber", "passport"),
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
        source_evidence = {"StaffMember": [("hr.GlbStaff", "PassportNumber", "passport")]}
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
        assert "hr.GlbStaff" in captured.out

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
