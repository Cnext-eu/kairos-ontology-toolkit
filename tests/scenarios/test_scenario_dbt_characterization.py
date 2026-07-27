# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Characterization coverage for the medallion dbt projector refactor.

These tests pin the *complete* generated artifact set (paths + byte content,
plus the non-file ``__coverage_data__`` / ``__release_data__`` facts) for the
``acme-hub`` client, invoice, and logistics scenarios against a frozen
baseline captured before ``_extract_silver_model_facts`` /
``_extract_schema_model_facts`` were decomposed into smaller helpers. The
baseline's ``artifact_keys`` is a single ordered sequence of *all* artifact
keys (file paths and ``__``-prefixed non-file facts together, in true
emission order) — file and non-file keys are intentionally not split into
separate lists, because ``generate_dbt_artifacts`` can interleave them
(e.g. metadata keys may be set before later schema/gold/silver
file artifacts are added), and splitting would silently discard that
relative interleaving.

Unlike the behavioural assertions elsewhere in ``test_scenario_dbt.py``
(which check individual columns, warnings, or SQL fragments), this module
exists specifically to catch *any* byte or ordering drift across the full
artifact map — the non-negotiable contract for the fact-extraction
refactor. If a change is intentional, regenerate the baseline deliberately
with ``regenerate_dbt_artifact_baseline.py --write`` (see that script's
module docstring) and review the diff.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

BASELINE_PATH = Path(__file__).parent / "fixtures" / "dbt_artifact_baseline.json"


def _hash_value(value: object) -> str:
    if isinstance(value, (str, bytes)):
        payload = value.encode("utf-8") if isinstance(value, str) else value
    else:
        # Non-file facts (``__coverage_data__``, ``__release_data__``) are
        # plain dict/list structures, not serialized artifact bytes. We hash
        # a canonical JSON encoding (``sort_keys=True``) purely to get a
        # *stable* content hash — sorting keys means this hash is NOT
        # sensitive to in-memory dict key order and therefore does not pin
        # it. List element order is preserved by ``json.dumps`` regardless
        # of ``sort_keys`` and so remains part of the pinned contract. Actual
        # file artifacts (SQL/YAML/etc. strings) do not go through this
        # branch — their exact byte content, including any embedded
        # ordering, is hashed directly and is fully pinned.
        payload = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _hash_artifacts(artifacts: dict) -> dict:
    # Preserve the actual dict insertion order (the order ``generate_dbt_artifacts``
    # produced) as ONE sequence — file artifacts and non-file facts (keys prefixed
    # ``__``, e.g. ``__coverage_data__``/``__release_data__``)
    # are interleaved in real emission (e.g. metadata can be set
    # before later schema/gold/silver file artifacts are added), so splitting them
    # into separate lists would silently discard that relative interleaving. A
    # single ``artifact_keys`` sequence is the byte-identity contract for order;
    # per-artifact hashes remain keyed by name for diagnostics.
    return {
        "artifact_keys": list(artifacts),
        "hashes": {k: _hash_value(v) for k, v in artifacts.items()},
    }


@pytest.fixture(scope="module")
def baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _assert_matches_baseline(label: str, artifacts: dict, baseline: dict) -> None:
    expected = baseline[label]
    actual = _hash_artifacts(artifacts)

    assert actual["artifact_keys"] == expected["artifact_keys"], (
        f"{label}: generated artifact set, emission order, or the relative "
        f"interleaving of file artifacts and non-file facts (``__``-prefixed "
        f"keys) changed.\n"
        f"Missing: {sorted(set(expected['artifact_keys']) - set(actual['artifact_keys']))}\n"
        f"Added:   {sorted(set(actual['artifact_keys']) - set(expected['artifact_keys']))}\n"
        f"(Set difference is empty when only relative order/interleaving changed.)"
    )
    drifted = sorted(
        key for key in expected["hashes"] if expected["hashes"][key] != actual["hashes"].get(key)
    )
    assert not drifted, f"{label}: byte-identical contract broken for: {drifted}"


class TestArtifactByteParity:
    """Full artifact map must remain byte-identical across the refactor."""

    def test_client_domain_artifacts_unchanged(self, client_dbt_artifacts, baseline):
        _assert_matches_baseline("client", client_dbt_artifacts, baseline)

    def test_invoice_domain_artifacts_unchanged(self, invoice_dbt_artifacts, baseline):
        _assert_matches_baseline("invoice", invoice_dbt_artifacts, baseline)

    def test_logistics_domain_artifacts_unchanged(self, logistics_dbt_artifacts, baseline):
        _assert_matches_baseline("logistics", logistics_dbt_artifacts, baseline)
