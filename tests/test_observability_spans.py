# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""A run is a tree of spans, and every way out of it leaves a run record (#1011, DD-242).

Diagnostics used to carry only a task and a gate string: no hierarchy, no durations, and a
failing run (the one whose findings matter most) wrote no summary, because Click's own
exits skipped the teardown. Each span now writes a ``kairos.span.completed`` record, each
diagnostic names the span it was reported in, and the summary is written on every exit.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.observability import events, spans

_PRODUCT_HUB = Path(__file__).parent / "scenarios" / "v5-product-hub"
_GOLD_HUB = Path(__file__).parent / "scenarios" / "v5-hub"
#: `billing` reports one info diagnostic on the product hub; `party` reports none.
_BILLING_CODE = "relationship.external-reference-key-unverified"

_PARTY_GOLD_EXT = """
@prefix party: <https://example.test/ontology/party#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

<https://example.test/ontology/party>
  kairos-ext:goldSchema "gold" ;
  kairos-ext:goldProductProfile "dimensional-powerbi-v1" .

party:Customer
  kairos-ext:goldTableType "dimension" ;
  kairos-ext:goldTableName "dim_customer" ;
  kairos-ext:goldSourceModel "customer" ;
  kairos-ext:goldSourceVersion "1.0.0" ;
  kairos-ext:dimensionExposure "current-only" ;
  kairos-ext:dimensionVersionBinding "current" .
"""


@pytest.fixture(autouse=True)
def _clean_spans():
    spans.reset_spans()
    events.reset_run_diagnostics()
    yield
    spans.reset_spans()
    events.reset_run_diagnostics()


@pytest.fixture
def hub(tmp_path, monkeypatch):
    root = tmp_path / "hub"
    shutil.copytree(_PRODUCT_HUB, root)
    monkeypatch.chdir(root)
    monkeypatch.delenv("KAIROS_RUN_LOG", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    return root


@pytest.fixture
def gold_hub(tmp_path, monkeypatch):
    root = tmp_path / "hub"
    shutil.copytree(_GOLD_HUB, root)
    ext_dir = root / "model" / "extensions"
    ext_dir.mkdir(parents=True, exist_ok=True)
    (ext_dir / "party-gold-ext.ttl").write_text(_PARTY_GOLD_EXT, encoding="utf-8")
    monkeypatch.chdir(root)
    monkeypatch.delenv("KAIROS_RUN_LOG", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    return root


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _of(records: list[dict], event: str) -> list[dict]:
    return [record for record in records if record.get("event") == event]


def _spans(records: list[dict]) -> dict[tuple[str, str], dict]:
    return {(r["span.kind"], r["span.name"]): r for r in _of(records, spans.SPAN_COMPLETED)}


def _invoke(log: Path, *args: str):
    return CliRunner().invoke(
        cli,
        ["--log-file", str(log), "--log-format", "json", *args],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )


class TestSpanHelper:
    def _completed(self, caplog) -> list[logging.LogRecord]:
        return [r for r in caplog.records if getattr(r, "event", None) == spans.SPAN_COMPLETED]

    def test_spans_nest_and_record_their_parent(self, caplog):
        with caplog.at_level(logging.INFO, logger="kairos_ontology"):
            with spans.task_span("domain", "billing") as outer:
                with spans.task_span("gate", "compile") as inner:
                    assert spans.current_span() is inner
                assert spans.current_span() is outer
            assert spans.current_span() is None
        gate, domain = self._completed(caplog)
        assert getattr(gate, "span.parent_id") == outer.span_id
        assert getattr(domain, "span.parent_id") == ""
        assert getattr(gate, "span.status") == "ok"
        assert isinstance(getattr(gate, "duration_ms"), int)
        assert getattr(gate, "kairos.console") is False

    def test_an_exception_marks_the_span_error_and_propagates(self, caplog):
        with caplog.at_level(logging.INFO, logger="kairos_ontology"):
            with pytest.raises(RuntimeError):
                with spans.task_span("stage", "emit"):
                    raise RuntimeError("boom")
        (record,) = self._completed(caplog)
        assert getattr(record, "span.status") == "error"

    def test_a_refusal_that_raises_stays_a_refusal(self, caplog):
        with caplog.at_level(logging.INFO, logger="kairos_ontology"):
            with pytest.raises(ValueError):
                with spans.task_span("product", "gold:sales"):
                    with spans.task_span("gate", "package-validation"):
                        spans.mark_refused()
                        raise ValueError("refused")
        gate, product = self._completed(caplog)
        assert getattr(gate, "span.status") == "refused"
        assert getattr(product, "span.status") == "refused"

    def test_a_diagnostic_names_its_span_and_counts_in_every_ancestor(self, caplog):
        diagnostic = SimpleNamespace(code="x.y", message="m", severity="warning")
        with caplog.at_level(logging.INFO, logger="kairos_ontology"):
            with spans.task_span("domain", "billing"):
                with spans.task_span("gate", "compile") as gate:
                    events.log_diagnostic(diagnostic, command="compile", domain="billing")
        (reported,) = [
            r for r in caplog.records if getattr(r, "event", None) == "kairos.diagnostic.reported"
        ]
        assert getattr(reported, "kairos.span.id") == gate.span_id
        gate_record, domain_record = self._completed(caplog)
        assert getattr(gate_record, "span.diagnostics") == {"warning": 1}
        assert getattr(domain_record, "span.diagnostics") == {"warning": 1}

    def test_the_run_span_ends_with_the_exit_code(self, caplog):
        with caplog.at_level(logging.INFO, logger="kairos_ontology"):
            spans.open_run_span("compile")
            with spans.task_span("domain", "billing") as domain:
                pass
            spans.close_run_span(exit_code=2)
            spans.close_run_span(exit_code=0)  # a second close is a no-op
        domain_record, run_record = self._completed(caplog)
        assert getattr(run_record, "span.kind") == "run"
        assert getattr(run_record, "span.status") == "error"
        assert getattr(run_record, "kairos.exit_code") == 2
        assert getattr(domain_record, "span.parent_id") == getattr(run_record, "span.id")
        assert domain.parent_id == getattr(run_record, "span.id")


class TestCompileSpans:
    def test_a_check_run_is_a_tree_of_run_domain_gate(self, hub, tmp_path):
        log = tmp_path / "run.jsonl"
        result = _invoke(log, "compile", "billing", "--check")
        assert result.exit_code == 0, result.output
        records = _records(log)
        by_name = _spans(records)
        run = by_name[("run", "compile")]
        domain = by_name[("domain", "billing")]
        compile_gate = by_name[("gate", "compile")]
        assert domain["span.parent_id"] == run["span.id"]
        assert compile_gate["span.parent_id"] == domain["span.id"]
        for gate in (
            "discovery.unresolved-judgment",
            "alignment.evidence-missing",
            "alignment.table-unanchored",
            "alignment.gap-column-undecided",
            "ontology.integrity",
        ):
            assert by_name[("gate", gate)]["span.parent_id"] == domain["span.id"]
        (diagnostic,) = _of(records, "kairos.diagnostic.reported")
        assert diagnostic["kairos.span.id"] == compile_gate["span.id"]
        assert compile_gate["span.diagnostics"] == {"info": 1}
        assert run["span.diagnostics"] == {"info": 1}

    def test_a_gate_refusal_reaches_the_log_under_its_gate(self, hub, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "kairos_ontology.cli.compile.check_discovery_gate",
            lambda hub, domains: ["an unresolved judgment blocks billing"],
        )
        log = tmp_path / "run.jsonl"
        result = _invoke(log, "compile", "billing", "--check")
        assert result.exit_code == 1
        records = _records(log)
        (diagnostic,) = _of(records, "kairos.diagnostic.reported")
        assert diagnostic["diagnostic.code"] == "discovery.unresolved-judgment"
        assert diagnostic["kairos.gate"] == "discovery.unresolved-judgment"
        by_name = _spans(records)
        gate = by_name[("gate", "discovery.unresolved-judgment")]
        assert diagnostic["kairos.span.id"] == gate["span.id"]
        assert gate["span.status"] == "refused"
        assert by_name[("domain", "billing")]["span.status"] == "refused"

    def test_a_crashed_gate_is_logged_as_evaluation_failed(self, hub, tmp_path, monkeypatch):
        def broken(hub):
            raise OSError("unreadable")

        monkeypatch.setattr("kairos_ontology.core.alignment_report.alignment_evidence_gaps", broken)
        log = tmp_path / "run.jsonl"
        assert _invoke(log, "compile", "billing", "--check").exit_code == 1
        (diagnostic,) = _of(_records(log), "kairos.diagnostic.reported")
        assert diagnostic["diagnostic.code"] == "gate.evaluation-failed"
        assert diagnostic["kairos.gate"] == "alignment.evidence-missing"

    def test_an_emit_has_emit_and_erd_stages(self, hub, tmp_path):
        log = tmp_path / "run.jsonl"
        result = _invoke(log, "compile", "--all", "--emit", "--confirm-emit")
        assert result.exit_code == 0, result.output
        by_name = _spans(_records(log))
        assert (
            by_name[("stage", "emit")]["span.parent_id"] == by_name[("domain", "party")]["span.id"]
        )
        assert by_name[("stage", "erd")]["span.parent_id"] == by_name[("run", "compile")]["span.id"]


class TestRunRecordOnEveryExit:
    def test_a_failing_compile_writes_its_summary(self, hub, tmp_path):
        log = tmp_path / "run.jsonl"
        result = _invoke(log, "compile", "nosuchdomain", "--check")
        assert result.exit_code == 1
        records = _records(log)
        (summary,) = _of(records, "kairos.run.summary")
        assert summary["kairos.outcome"] == "failed"
        assert summary["kairos.exit_code"] == 1
        assert _spans(records)[("run", "compile")]["span.status"] == "error"

    def test_logging_is_reset_after_a_click_exit(self, hub, tmp_path):
        _invoke(tmp_path / "run.jsonl", "compile", "nosuchdomain", "--check")
        logger = logging.getLogger("kairos_ontology")
        assert logger.propagate is True
        assert not [h for h in logger.handlers if getattr(h, "_kairos_observability", False)]

    def test_a_clean_run_writes_a_summary_with_no_diagnostics(self, hub, tmp_path):
        log = tmp_path / "run.jsonl"
        assert _invoke(log, "compile", "party", "--check").exit_code == 0
        (summary,) = _of(_records(log), "kairos.run.summary")
        assert summary["kairos.outcome"] == "ok"
        assert summary["kairos.exit_code"] == 0
        assert summary["kairos.summary"] == {}

    def test_a_system_exit_writes_its_exit_code(self, hub, tmp_path, monkeypatch):
        def exits(*_args, **_kwargs):
            raise SystemExit(3)

        monkeypatch.setattr("kairos_ontology.cli.compile.compile_domain", exits)
        log = tmp_path / "run.jsonl"
        assert _invoke(log, "compile", "billing", "--check").exit_code == 3
        (summary,) = _of(_records(log), "kairos.run.summary")
        assert summary["kairos.exit_code"] == 3

    def test_help_writes_no_summary(self, hub, tmp_path):
        log = tmp_path / "run.jsonl"
        assert _invoke(log, "compile", "--help").exit_code == 0
        records = _records(log) if log.exists() else []
        assert _of(records, "kairos.run.summary") == []

    def test_a_contract_refusal_writes_a_summary(self, hub, tmp_path):
        """billing has no Gold profile: emit-gold refuses before any compile diagnostic."""
        log = tmp_path / "run.jsonl"
        result = _invoke(log, "emit-gold", "billing")
        assert result.exit_code == 1
        records = _records(log)
        (summary,) = _of(records, "kairos.run.summary")
        assert summary["kairos.exit_code"] == 1
        (diagnostic,) = _of(records, "kairos.diagnostic.reported")
        assert diagnostic["diagnostic.code"] == "gold.profile-missing"
        assert _spans(records)[("product", "gold:billing")]["span.status"] == "refused"


class TestEmitGoldCoverage:
    def test_a_package_failure_is_logged_before_the_refusal(self, gold_hub, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "kairos_ontology.cli.emit_gold.validate_package_artifacts",
            lambda artifacts: [
                SimpleNamespace(
                    status="fail", artifact_path="party/Party.pbip", message="bad $schema"
                )
            ],
        )
        log = tmp_path / "run.jsonl"
        result = _invoke(log, "emit-gold", "party", "--skip-tmdl-validation")
        assert result.exit_code == 1
        assert "Fabric package validation failed" in result.output
        records = _records(log)
        (diagnostic,) = [
            r
            for r in _of(records, "kairos.diagnostic.reported")
            if r["diagnostic.code"] == "gold.package-invalid"
        ]
        assert diagnostic["diagnostic.location"] == "party/Party.pbip"
        assert diagnostic["kairos.task"] == "gold:party"
        by_name = _spans(records)
        assert diagnostic["kairos.span.id"] == by_name[("gate", "package-validation")]["span.id"]
        assert by_name[("gate", "package-validation")]["span.status"] == "refused"

    def test_an_unavailable_tom_sdk_is_logged_as_info(self, gold_hub, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "kairos_ontology.core.projections.dbt.tmdl_validate.shutil.which", lambda _: None
        )
        log = tmp_path / "run.jsonl"
        result = _invoke(log, "emit-gold", "party")
        assert result.exit_code == 0, result.output
        records = _records(log)
        codes = {r["diagnostic.code"]: r for r in _of(records, "kairos.diagnostic.reported")}
        assert codes["gold.tmdl-unavailable"]["diagnostic.severity"] == "info"
        by_name = _spans(records)
        product = by_name[("product", "gold:party")]
        for gate in (
            "compile",
            "gold-shape",
            "package-validation",
            "gold.tmdl-structural-validation",
        ):
            assert by_name[("gate", gate)]["span.parent_id"] == product["span.id"]

    def test_a_confirmed_emit_has_emit_and_erd_stages(self, gold_hub, tmp_path):
        log = tmp_path / "run.jsonl"
        result = _invoke(log, "emit-gold", "party", "--confirm-emit", "--skip-tmdl-validation")
        assert result.exit_code == 0, result.output
        by_name = _spans(_records(log))
        product = by_name[("product", "gold:party")]
        assert by_name[("stage", "emit")]["span.parent_id"] == product["span.id"]
        assert by_name[("stage", "erd")]["span.parent_id"] == product["span.id"]
