# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Determinism tests for the projection pipeline.

Silver (and every other target) must be a *reproducible* projection of the encoded
inputs.  These tests pin the generation timestamp via ``KAIROS_GENERATED_AT`` and
assert byte-identical output, both in-process and — critically — across separate
processes with differing ``PYTHONHASHSEED`` (which perturbs set/dict iteration).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kairos_ontology.core import determinism

PROBE = Path(__file__).parent / "_determinism_probe.py"
HUB_ROOT = Path(__file__).parent / "scenarios" / "acme-hub"
FIXED_TS = "2026-01-02T03:04:05Z"

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


def _snapshot(root: Path) -> dict[str, bytes]:
    """Map every file under *root* to its bytes, keyed by POSIX-relative path."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_resolve_generated_at_precedence():
    env = {"KAIROS_GENERATED_AT": FIXED_TS, "SOURCE_DATE_EPOCH": "1700000000"}
    # Explicit KAIROS_GENERATED_AT wins over SOURCE_DATE_EPOCH.
    assert determinism.generated_at_iso(determinism.resolve_generated_at(env)) == FIXED_TS

    env2 = {"SOURCE_DATE_EPOCH": "1700000000"}
    assert (
        determinism.generated_at_iso(determinism.resolve_generated_at(env2))
        == "2023-11-14T22:13:20Z"
    )


def test_in_process_artifacts_are_stable(monkeypatch):
    monkeypatch.setenv("KAIROS_GENERATED_AT", FIXED_TS)
    from tests import _determinism_probe as probe

    first = probe.build_artifacts()
    second = probe.build_artifacts()
    assert first == second, "Re-projection produced different artifacts in-process"


def test_generated_at_flows_into_ontology_metadata(monkeypatch):
    """The pinned timestamp must land in provenance metadata used by templates."""
    monkeypatch.setenv("KAIROS_GENERATED_AT", FIXED_TS)
    from rdflib import Graph

    from kairos_ontology.core.projector import extract_ontology_metadata

    meta = extract_ontology_metadata(Graph(), "https://acme.example/client#")
    assert meta["generated_at"] == FIXED_TS


def test_cross_process_byte_identical():
    """Two fresh processes with different hash seeds must produce the same hash."""

    def run(seed: str) -> str:
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["KAIROS_GENERATED_AT"] = FIXED_TS
        env["PYTHONUTF8"] = "1"
        # Ensure `import tests._determinism_probe`-free direct execution works.
        result = subprocess.run(
            [sys.executable, str(PROBE)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    hash_a = run("0")
    hash_b = run("1")
    assert hash_a == hash_b, (
        "Projection output differs across processes with different PYTHONHASHSEED — "
        "non-deterministic iteration order remains."
    )


# ---------------------------------------------------------------------------
# Malformed pins must be rejected explicitly (no silent now() fallback)
# ---------------------------------------------------------------------------


def test_resolve_generated_at_rejects_malformed_iso():
    """A set-but-unparsable KAIROS_GENERATED_AT fails loudly instead of defaulting
    to the current time (which would silently break reproducible builds)."""
    with pytest.raises(ValueError, match="KAIROS_GENERATED_AT"):
        determinism.resolve_generated_at({"KAIROS_GENERATED_AT": "not-a-timestamp"})
    with pytest.raises(ValueError, match="KAIROS_GENERATED_AT"):
        determinism.resolve_generated_at({"KAIROS_GENERATED_AT": "2026-13-99T99:99:99Z"})


def test_resolve_generated_at_rejects_malformed_epoch():
    """A non-integer or out-of-range SOURCE_DATE_EPOCH raises rather than silently
    falling through to now()."""
    with pytest.raises(ValueError, match="SOURCE_DATE_EPOCH"):
        determinism.resolve_generated_at({"SOURCE_DATE_EPOCH": "not-a-number"})
    with pytest.raises(ValueError, match="SOURCE_DATE_EPOCH"):
        determinism.resolve_generated_at({"SOURCE_DATE_EPOCH": "99999999999999999999999"})


def test_blank_pins_are_treated_as_unset():
    """Whitespace-only pins defer to the next precedence source instead of raising."""
    # Blank KAIROS_GENERATED_AT → fall through to SOURCE_DATE_EPOCH.
    dt = determinism.resolve_generated_at(
        {"KAIROS_GENERATED_AT": "   ", "SOURCE_DATE_EPOCH": "1700000000"}
    )
    assert determinism.generated_at_iso(dt) == "2023-11-14T22:13:20Z"
    # Blank both → fall back to now() (a tz-aware UTC datetime), no error.
    dt2 = determinism.resolve_generated_at({"KAIROS_GENERATED_AT": "", "SOURCE_DATE_EPOCH": " "})
    assert dt2.tzinfo is not None


# ---------------------------------------------------------------------------
# One generation timestamp resolved once per run and threaded everywhere
# ---------------------------------------------------------------------------


def test_single_timestamp_resolved_once_per_run(monkeypatch):
    """project_graph resolves the generation time once at the run boundary.

    A counter stub returns a *different* datetime on each call; if any downstream
    site re-resolved instead of reusing the threaded value the count would exceed
    one and the report/metadata stamps could disagree.
    """
    from rdflib import Graph

    from kairos_ontology.core import projector

    calls = {"n": 0}
    base = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def fake_resolve(env=None):
        calls["n"] += 1
        return base + timedelta(minutes=calls["n"])

    monkeypatch.setattr(projector, "resolve_generated_at", fake_resolve)

    graph = Graph()
    graph.parse(data=_TTL, format="turtle")
    results = projector.project_graph(graph, targets=["prompt"], ontology_name="test")

    assert calls["n"] == 1, "generation timestamp must be resolved exactly once per run"
    report = results["_report"]
    assert report.generated_at == determinism.generated_at_iso(base + timedelta(minutes=1))


def test_metadata_threads_explicit_datetime():
    """extract_ontology_metadata stamps the exact datetime it is handed."""
    from rdflib import Graph

    from kairos_ontology.core.projector import extract_ontology_metadata

    dt = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
    meta = extract_ontology_metadata(Graph(), "https://acme.example/client#", generated_at=dt)
    assert meta["generated_at"] == determinism.generated_at_iso(dt) == "2026-03-04T05:06:07Z"


# ---------------------------------------------------------------------------
# Stable, non-accumulating report/session paths
# ---------------------------------------------------------------------------


def test_write_domain_markdown_uses_stable_filename(tmp_path):
    """The per-domain session log filename must be stable (no embedded timestamp)."""
    from kairos_ontology.core.projector import ProjectionReport

    rpt = ProjectionReport(toolkit_version="9.9.9", generated_at=FIXED_TS)
    rpt.targets_requested = ["silver", "dbt"]
    rpt.record_domain_load("client", file="client.ttl", status="ok")

    path = rpt.write_domain_markdown("client", tmp_path)
    # Targets are sorted; the filename carries no YYYY-MM-DD timestamp.
    assert path.name == "projection-client-dbt+silver.md"
    assert not re.search(r"\d{4}-\d{2}-\d{2}", path.name)


def test_reprojection_output_is_path_and_byte_stable(tmp_path, monkeypatch):
    """A second run over unchanged inputs converges: identical output tree (no
    accumulating files) that is byte-for-byte reproducible under a pin, and the
    per-domain session log keeps a single stable filename."""
    from kairos_ontology.core.projector import run_projections

    monkeypatch.setenv("KAIROS_GENERATED_AT", FIXED_TS)
    hub = tmp_path
    ont_dir = hub / "model" / "ontologies"
    ont_dir.mkdir(parents=True)
    (ont_dir / "test.ttl").write_text(_TTL, encoding="utf-8")
    (hub / ".sessions-projection").mkdir()
    output_dir = hub / "output"
    catalog = hub / "catalog.xml"

    def _run():
        run_projections(
            ontologies_path=ont_dir,
            output_path=output_dir,
            catalog_path=catalog,
            target="prompt",
        )

    _run()
    first = _snapshot(output_dir)
    _run()
    second = _snapshot(output_dir)

    assert set(first) == set(second), "output file set changed on re-projection"
    assert first == second, "re-projection produced byte-different output"

    # The session log keeps one stable, timestamp-free filename across both runs.
    logs = list((hub / ".sessions-projection").glob("projection-test-*.md"))
    assert [p.name for p in logs] == ["projection-test-prompt.md"]


def test_prune_legacy_report_files_only_removes_timestamped(tmp_path):
    """The legacy-report prune removes only exact timestamp-shaped filenames,
    leaving stable and hand-authored files untouched."""
    from kairos_ontology.core.projector import (
        _LEGACY_REPORT_TS,
        _prune_legacy_report_files,
    )

    legacy = tmp_path / "coverage-silver-2026-07-21-194330.json"
    legacy.write_text("{}", encoding="utf-8")
    stable = tmp_path / "coverage-silver.json"
    stable.write_text("{}", encoding="utf-8")
    authored = tmp_path / "my-notes.json"
    authored.write_text("{}", encoding="utf-8")

    removed = _prune_legacy_report_files(tmp_path, (f"coverage-silver-{_LEGACY_REPORT_TS}.json",))

    assert removed == 1
    assert not legacy.exists()
    assert stable.exists()
    assert authored.exists()
    # A missing directory is a no-op.
    assert _prune_legacy_report_files(tmp_path / "nope", ("*.json",)) == 0


@pytest.mark.slow
def test_reprojection_all_targets_stable_and_reports_untimestamped(tmp_path, monkeypatch):
    """Full acme-hub projection is byte-identical on re-run under a pin; coverage and
    detail reports use stable (timestamp-free) filenames and nothing accumulates."""
    from kairos_ontology.core.projector import run_projections

    monkeypatch.setenv("KAIROS_GENERATED_AT", FIXED_TS)
    monkeypatch.setenv("PYTHONUTF8", "1")
    hub = tmp_path / "acme-hub"
    shutil.copytree(HUB_ROOT, hub)

    def _run():
        run_projections(
            ontologies_path=hub / "model" / "ontologies",
            catalog_path=hub / "catalog-v001.xml",  # absent → graceful fallback
            output_path=hub / "output",
            target="all",
        )

    _run()
    first = _snapshot(hub / "output")
    _run()
    second = _snapshot(hub / "output")

    assert set(first) == set(second), (
        "output file set changed on re-projection — timestamped filenames still "
        f"accumulate: +{sorted(set(second) - set(first))} "
        f"-{sorted(set(first) - set(second))}"
    )
    # External Mermaid SVG rendering (mmdc) is out of the toolkit's determinism
    # scope; compare every other artifact byte-for-byte.
    byte_diffs = [p for p in first if not p.endswith(".svg") and first[p] != second[p]]
    assert not byte_diffs, f"re-projection produced byte-different files: {byte_diffs}"

    rels = set(first)
    assert "reports/coverage-silver.json" in rels
    assert "reports/coverage-silver.md" in rels
    ts = re.compile(r"\d{4}-\d{2}-\d{2}-\d{6}")
    leftover = [p for p in rels if p.startswith("reports/") and ts.search(p)]
    assert not leftover, "timestamped report filenames must be replaced by stable paths"
