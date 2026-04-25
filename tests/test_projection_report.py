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
