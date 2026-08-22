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
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kairos_ontology.core import determinism

PROBE = Path(__file__).parent / "_determinism_probe.py"
HUB_ROOT = Path(__file__).parent / "scenarios" / "v5-governed-hub"
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
    one and artifact metadata stamps could disagree.
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
    projector.project_graph(graph, targets=["prompt"], ontology_name="test")

    assert calls["n"] == 1, "generation timestamp must be resolved exactly once per run"


def test_metadata_threads_explicit_datetime():
    """extract_ontology_metadata stamps the exact datetime it is handed."""
    from rdflib import Graph

    from kairos_ontology.core.projector import extract_ontology_metadata

    dt = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
    meta = extract_ontology_metadata(Graph(), "https://acme.example/client#", generated_at=dt)
    assert meta["generated_at"] == determinism.generated_at_iso(dt) == "2026-03-04T05:06:07Z"


def test_reprojection_output_is_path_and_byte_stable(tmp_path, monkeypatch):
    """A second run over unchanged inputs converges to an identical output tree."""
    from kairos_ontology.core.projector import run_projections

    monkeypatch.setenv("KAIROS_GENERATED_AT", FIXED_TS)
    hub = tmp_path
    ont_dir = hub / "model" / "ontologies"
    ont_dir.mkdir(parents=True)
    (ont_dir / "test.ttl").write_text(_TTL, encoding="utf-8")
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


@pytest.mark.slow
def test_reprojection_all_targets_stable_and_reports_untimestamped(tmp_path, monkeypatch):
    """The v5 governed hub produces an identical immutable plan and artifact map."""
    from kairos_ontology.core.compiler import build_compile_plan, render_compile_plan

    monkeypatch.setenv("KAIROS_GENERATED_AT", FIXED_TS)
    monkeypatch.setenv("PYTHONUTF8", "1")
    first = build_compile_plan(HUB_ROOT, "party")
    second = build_compile_plan(HUB_ROOT, "party")

    assert first == second
    assert first.provenance_hash == second.provenance_hash
    assert render_compile_plan(first) == render_compile_plan(second)


# ---------------------------------------------------------------------------
# provenance_hash is order-independent (#600)
# ---------------------------------------------------------------------------


def _scope(inputs):
    from kairos_ontology.core.compiler.scope import BuildScope

    return BuildScope(
        domain="party",
        hub_root="/hub",
        api_version="kairos.eu/v5",
        adapter="fabric",
        namespace="https://example.test/",
        toolkit_version="0.0.0",
        inputs=tuple(inputs),
    )


def test_provenance_hash_ignores_input_order_when_names_collide():
    """Two ontologies can share a provenance *name* and still differ in content.

    An ontology outside the hub root is recorded under its bare filename, and
    reference-model modules from different families share basenames. Sorting on the
    name alone left those colliding entries in insertion order — which follows the
    closure's set iteration, so the same hub hashed differently from one process to
    the next depending on PYTHONHASHSEED.
    """
    from kairos_ontology.core.compiler.scope import ProvenanceInput

    a = ProvenanceInput("consignment.ttl", "# RAIL consignment\n")
    b = ProvenanceInput("consignment.ttl", "# ROAD consignment\n")
    c = ProvenanceInput("party.ttl", "# party\n")

    assert _scope([a, b, c]).provenance_hash() == _scope([b, a, c]).provenance_hash()
    assert _scope([c, b, a]).provenance_hash() == _scope([a, b, c]).provenance_hash()


def test_provenance_hash_still_separates_different_content():
    """Order-independence must not blunt the hash into ignoring a real edit."""
    from kairos_ontology.core.compiler.scope import ProvenanceInput

    before = [ProvenanceInput("x.ttl", "one"), ProvenanceInput("x.ttl", "two")]
    after = [ProvenanceInput("x.ttl", "one"), ProvenanceInput("x.ttl", "CHANGED")]

    assert _scope(before).provenance_hash() != _scope(after).provenance_hash()


def test_provenance_hash_is_stable_across_hash_seeds():
    """The reported symptom: same inputs, different process, different hash.

    Builds the scope from a *set* (whose iteration order PYTHONHASHSEED perturbs) in
    two subprocesses with different seeds. An in-process assertion cannot catch this —
    one process has one seed.
    """
    program = (
        "from kairos_ontology.core.compiler.scope import BuildScope, ProvenanceInput\n"
        "names = {'a.ttl', 'b.ttl', 'c.ttl', 'd.ttl', 'e.ttl', 'f.ttl'}\n"
        # One shared name with distinct content is what makes order observable.
        "items = [ProvenanceInput('dup.ttl', n) for n in names]\n"
        "print(BuildScope(domain='d', hub_root='/h', api_version='v5', adapter='fabric',\n"
        "                 namespace='ns', toolkit_version='0', inputs=tuple(items))\n"
        "      .provenance_hash())\n"
    )
    digests = set()
    for seed in ("0", "1", "42", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run(
            [sys.executable, "-c", program], capture_output=True, text=True, env=env, check=True
        )
        digests.add(out.stdout.strip())
    assert len(digests) == 1, f"provenance_hash varied across hash seeds: {digests}"
