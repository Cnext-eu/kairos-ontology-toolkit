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
from pathlib import Path

import pytest

from kairos_ontology.core import determinism

PROBE = Path(__file__).parent / "_determinism_probe.py"
FIXED_TS = "2026-01-02T03:04:05Z"


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
