# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the ProjectionReport dataclass and its integration with projectors."""

import json

from pathlib import Path

from rdflib import Graph

from kairos_ontology.projector import ProjectionReport, project_graph, run_projections


# Minimal valid ontology with one class.
_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<http://example.org/ont/test> a owl:Ontology ;
    rdfs:label "Test"@en ;
    owl:versionInfo "1.0" .

<http://example.org/ont/test#Widget> a owl:Class ;
    rdfs:label "Widget"@en ;
    rdfs:comment "A test widget."@en .
"""


# ---------------------------------------------------------------------------
# Unit tests for ProjectionReport
# ---------------------------------------------------------------------------


class TestProjectionReport:

    def _make_report(self, **kwargs) -> ProjectionReport:
        defaults = dict(toolkit_version="0.0.0-test", generated_at="2025-01-01T00:00:00Z")
        defaults.update(kwargs)
        return ProjectionReport(**defaults)

    # -- to_dict / empty state --

    def test_empty_report_to_dict(self):
        rpt = self._make_report()
        d = rpt.to_dict()
        s = d["summary"]
        assert s["domains_found"] == 0
        assert s["domains_loaded"] == 0
        assert s["domains_failed_to_load"] == 0
        assert s["total_files_generated"] == 0
        assert s["errors"] == 0
        assert s["warnings"] == 0
        assert s["skipped"] == 0

    # -- record_domain_load --

    def test_record_domain_load_ok(self):
        rpt = self._make_report()
        rpt.record_domain_load("sales", file="sales.ttl", triples=42, namespace="http://ex.org/", status="ok")
        assert "sales" in rpt.domains
        assert rpt.domains["sales"]["status"] == "ok"
        assert rpt.domains["sales"]["triples"] == 42

    def test_record_domain_load_failed(self):
        rpt = self._make_report()
        rpt.record_domain_load("bad", file="bad.ttl", status="load_failed", error="Parse error")
        assert rpt.domains["bad"]["status"] == "load_failed"
        assert rpt.domains["bad"]["error"] == "Parse error"

    # -- record_projection --

    def test_record_projection_ok(self):
        rpt = self._make_report()
        rpt.record_projection("dbt", "sales", status="ok", files=["a.sql", "b.sql"])
        assert len(rpt.projections) == 1
        entry = rpt.projections[0]
        assert entry["files_generated"] == 2
        assert rpt._total_files == 2

    def test_record_projection_error(self):
        rpt = self._make_report()
        rpt.record_projection("neo4j", "sales", status="error", error="boom")
        assert rpt._errors == 1
        assert rpt.projections[0]["error"] == "boom"

    def test_record_projection_skipped(self):
        rpt = self._make_report()
        rpt.record_projection("a2ui", "sales", status="skipped", reason="No classes")
        assert rpt._skipped == 1
        assert rpt.projections[0]["reason"] == "No classes"

    # -- record_post_step --

    def test_record_post_step_ok(self):
        rpt = self._make_report()
        rpt.record_post_step("master_erd")
        assert len(rpt.post_steps) == 1
        assert rpt.post_steps[0]["status"] == "ok"

    def test_record_post_step_skipped(self):
        rpt = self._make_report()
        rpt.record_post_step("svg_export", status="skipped", reason="No graphviz")
        assert rpt._skipped == 1
        assert rpt.post_steps[0]["reason"] == "No graphviz"

    # -- record (events) --

    def test_record_events(self):
        rpt = self._make_report()
        rpt.record("info", "all good")
        rpt.record("warning", "hmm")
        rpt.record("error", "oops", domain="d", target="t")
        assert len(rpt.events) == 3
        assert rpt._errors == 1
        assert rpt._warnings == 1

    # -- summary aggregation --

    def test_summary_counts(self):
        rpt = self._make_report()
        rpt.record_domain_load("a", file="a.ttl", status="ok")
        rpt.record_domain_load("b", file="b.ttl", status="load_failed", error="bad")
        rpt.record_projection("dbt", "a", status="ok", files=["x.sql"])
        rpt.record_projection("neo4j", "a", status="error", error="fail")
        rpt.record_projection("a2ui", "a", status="skipped", reason="empty")
        s = rpt.to_dict()["summary"]
        assert s["domains_found"] == 2
        assert s["domains_loaded"] == 1
        assert s["domains_failed_to_load"] == 1
        assert s["total_files_generated"] == 1
        assert s["errors"] == 1
        assert s["skipped"] == 1

    # -- write --

    def test_write_creates_file(self, tmp_path):
        rpt = self._make_report()
        rpt.write(tmp_path)
        outfile = tmp_path / "projection-report.json"
        assert outfile.exists()
        data = json.loads(outfile.read_text(encoding="utf-8"))
        assert data["toolkit_version"] == "0.0.0-test"

    def test_write_returns_path(self, tmp_path):
        rpt = self._make_report()
        result = rpt.write(tmp_path)
        assert isinstance(result, Path)
        assert result.name == "projection-report.json"


# ---------------------------------------------------------------------------
# Integration: project_graph()
# ---------------------------------------------------------------------------


class TestProjectGraphReport:

    @staticmethod
    def _load_graph() -> Graph:
        g = Graph()
        g.parse(data=_TTL, format="turtle")
        return g

    def test_project_graph_returns_report(self):
        g = self._load_graph()
        results = project_graph(g, targets=["prompt"], ontology_name="test")
        assert "_report" in results
        rpt = results["_report"]
        assert isinstance(rpt, ProjectionReport)
        ok_entries = [p for p in rpt.projections if p["status"] == "ok"]
        assert len(ok_entries) >= 1

    def test_project_graph_report_captures_skipped_target(self):
        g = Graph()  # empty — no classes
        results = project_graph(g, targets=["prompt"], ontology_name="empty")
        rpt = results["_report"]
        skipped = [p for p in rpt.projections if p["status"] == "skipped"]
        assert len(skipped) >= 1


# ---------------------------------------------------------------------------
# Integration: run_projections()
# ---------------------------------------------------------------------------


class TestRunProjectionsReport:

    def test_report_file_written(self, tmp_path):
        ont_dir = tmp_path / "model" / "ontologies"
        ont_dir.mkdir(parents=True)
        (ont_dir / "test.ttl").write_text(_TTL, encoding="utf-8")

        output_dir = tmp_path / "output"
        catalog = tmp_path / "catalog.xml"

        run_projections(
            ontologies_path=ont_dir,
            output_path=output_dir,
            catalog_path=catalog,
            target="prompt",
        )

        report_file = output_dir / "projection-report.json"
        assert report_file.exists(), "projection-report.json was not written"
        data = json.loads(report_file.read_text(encoding="utf-8"))
        assert "test" in data["domains"]
        assert data["domains"]["test"]["status"] == "ok"

    def test_report_captures_parse_failure(self, tmp_path):
        ont_dir = tmp_path / "model" / "ontologies"
        ont_dir.mkdir(parents=True)
        (ont_dir / "broken.ttl").write_text("NOT VALID TURTLE !!!", encoding="utf-8")

        output_dir = tmp_path / "output"
        catalog = tmp_path / "catalog.xml"

        run_projections(
            ontologies_path=ont_dir,
            output_path=output_dir,
            catalog_path=catalog,
            target="prompt",
        )

        report_file = output_dir / "projection-report.json"
        assert report_file.exists(), "projection-report.json was not written"
        data = json.loads(report_file.read_text(encoding="utf-8"))
        assert "broken" in data["domains"]
        assert data["domains"]["broken"]["status"] == "load_failed"


# ---------------------------------------------------------------------------
# Markdown domain report
# ---------------------------------------------------------------------------


class TestProjectionReportMarkdown:

    def _make_report(self, **kwargs) -> ProjectionReport:
        defaults = dict(toolkit_version="0.0.0-test", generated_at="2025-01-01T00:00:00Z")
        defaults.update(kwargs)
        return ProjectionReport(**defaults)

    def test_write_domain_markdown_creates_file(self, tmp_path):
        rpt = self._make_report()
        rpt.targets_requested = ["silver"]
        rpt.record_domain_load("client", file="client.ttl", triples=50,
                               namespace="http://ex.org/ont/client#", status="ok")
        rpt.record_projection("silver", "client", status="ok", files=["ddl.sql"])

        md_path = rpt.write_domain_markdown("client", tmp_path)
        assert md_path is not None
        assert md_path.exists()
        assert md_path.name.startswith("projection-client-")
        assert md_path.suffix == ".md"

    def test_write_domain_markdown_contains_warnings(self, tmp_path):
        import logging

        rpt = self._make_report()
        rpt.targets_requested = ["silver"]
        rpt.record_domain_load("client", file="client.ttl", triples=50,
                               namespace="http://ex.org/ont/client#", status="ok")
        rpt.record_projection("silver", "client", status="ok", files=["ddl.sql"])

        rec = logging.LogRecord("test", logging.WARNING, "", 0,
                                "PII detected on Person.email", None, None)
        rpt.add_captured_warnings("client", "silver", [rec])

        md_path = rpt.write_domain_markdown("client", tmp_path)
        content = md_path.read_text(encoding="utf-8")
        assert "## ⚠️ Warnings" in content
        assert "PII detected on Person.email" in content
        assert "**[silver]**" in content

    def test_write_domain_markdown_no_issues_section(self, tmp_path):
        rpt = self._make_report()
        rpt.targets_requested = ["prompt"]
        rpt.record_domain_load("clean", file="clean.ttl", triples=10,
                               namespace="http://ex.org/", status="ok")
        rpt.record_projection("prompt", "clean", status="ok", files=["f.md"])

        md_path = rpt.write_domain_markdown("clean", tmp_path)
        content = md_path.read_text(encoding="utf-8")
        assert "## ✅ No issues" in content
        assert "## ⚠️ Warnings" not in content

    def test_write_domain_markdown_returns_none_without_dir(self):
        rpt = self._make_report()
        rpt.record_domain_load("x", file="x.ttl", status="ok")
        assert rpt.write_domain_markdown("x", None) is None

    def test_add_captured_warnings_feeds_events(self):
        import logging

        rpt = self._make_report()
        rec = logging.LogRecord("test", logging.WARNING, "", 0, "warn msg", None, None)
        rpt.add_captured_warnings("dom", "silver", [rec])

        # Should appear in events list
        assert any(e["message"] == "warn msg" and e["level"] == "warning"
                   for e in rpt.events)
        assert rpt._warnings == 1

    def test_run_projections_writes_markdown_to_modeling_sessions(self, tmp_path):
        """Integration: run_projections writes .md to .sessions-projection/."""
        hub = tmp_path
        ont_dir = hub / "model" / "ontologies"
        ont_dir.mkdir(parents=True)
        (ont_dir / "test.ttl").write_text(_TTL, encoding="utf-8")

        sessions_dir = hub / ".sessions-projection"
        sessions_dir.mkdir(parents=True)

        output_dir = hub / "output"
        catalog = tmp_path / "catalog.xml"

        run_projections(
            ontologies_path=ont_dir,
            output_path=output_dir,
            catalog_path=catalog,
            target="prompt",
        )

        md_files = list(sessions_dir.glob("projection-test-*.md"))
        assert len(md_files) == 1
        content = md_files[0].read_text(encoding="utf-8")
        assert "# Projection Report — test" in content


class TestCatalogWarningsInReport:
    """Verify that catalog resolution warnings are captured in projection-report.json."""

    _TTL_WITH_IMPORT = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<http://example.org/ont/test> a owl:Ontology ;
    rdfs:label "Test"@en ;
    owl:versionInfo "1.0" ;
    owl:imports <https://missing.org/reference-model> .

<http://example.org/ont/test#Widget> a owl:Class ;
    rdfs:label "Widget"@en ;
    rdfs:comment "A test widget."@en .
"""

    def test_unresolved_import_appears_in_report_events(self, tmp_path):
        """Unresolved owl:imports should produce a warning event in the report."""
        ont_dir = tmp_path / "model" / "ontologies"
        ont_dir.mkdir(parents=True)
        (ont_dir / "test.ttl").write_text(self._TTL_WITH_IMPORT, encoding="utf-8")

        # Create catalog without the imported URI
        catalog = tmp_path / "catalog-v001.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '</catalog>\n',
            encoding="utf-8",
        )

        output_dir = tmp_path / "output"

        run_projections(
            ontologies_path=ont_dir,
            output_path=output_dir,
            catalog_path=catalog,
            target="prompt",
        )

        report_file = output_dir / "projection-report.json"
        assert report_file.exists()
        data = json.loads(report_file.read_text(encoding="utf-8"))

        # There should be at least one warning event about the missing mapping
        warning_events = [
            e for e in data["events"]
            if e["level"] == "warning" and "No catalog mapping for" in e["message"]
        ]
        assert len(warning_events) >= 1
        assert "https://missing.org/reference-model" in warning_events[0]["message"]
        assert warning_events[0].get("domain") == "test"
        assert warning_events[0].get("target") == "load"

    def test_unresolved_import_appears_in_domain_markdown(self, tmp_path):
        """Unresolved owl:imports warning should appear in the per-domain .md report."""
        hub = tmp_path
        ont_dir = hub / "model" / "ontologies"
        ont_dir.mkdir(parents=True)
        (ont_dir / "test.ttl").write_text(self._TTL_WITH_IMPORT, encoding="utf-8")

        sessions_dir = hub / ".sessions-projection"
        sessions_dir.mkdir(parents=True)

        catalog = tmp_path / "catalog-v001.xml"
        catalog.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '</catalog>\n',
            encoding="utf-8",
        )

        output_dir = hub / "output"

        run_projections(
            ontologies_path=ont_dir,
            output_path=output_dir,
            catalog_path=catalog,
            target="prompt",
        )

        md_files = list(sessions_dir.glob("projection-test-*.md"))
        assert len(md_files) == 1
        content = md_files[0].read_text(encoding="utf-8")
        assert "No catalog mapping for" in content
        assert "https://missing.org/reference-model" in content
