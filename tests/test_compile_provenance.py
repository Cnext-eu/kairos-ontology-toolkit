# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Provenance document construction (DD-218).

Pure-document tests. Emission against the synthetic hub lives in
``tests/scenarios/test_scenario_provenance.py``.
"""

from __future__ import annotations

import hashlib
import json

from kairos_ontology.core.compiler.provenance import (
    PROVENANCE_SCHEMA,
    build_provenance_document,
    provenance_artifact,
    provenance_artifact_path,
)
from kairos_ontology.core.compiler.scope import BuildScope, ProvenanceInput


def _scope(**overrides) -> BuildScope:
    defaults = dict(
        domain="party",
        hub_root="/hub",
        api_version="v5",
        adapter="fabric-warehouse",
        namespace="https://example.invalid/party#",
        toolkit_version="9.9.9",
        inputs=(
            ProvenanceInput(name="model/ontologies/party.ttl", content="ontology bytes"),
            ProvenanceInput(name="bindings/customer.binding.yaml", content="binding bytes"),
        ),
    )
    defaults.update(overrides)
    return BuildScope(**defaults)


class TestDocument:
    def test_is_byte_deterministic(self):
        assert build_provenance_document(_scope()) == build_provenance_document(_scope())

    def test_carries_no_wall_clock_value(self):
        """DD-133 validation requirement 10: no wall-clock in artifact content."""
        document = build_provenance_document(_scope())
        for forbidden in ("generated_at", "generatedAt", "timestamp", "emittedAt"):
            assert forbidden not in document

    def test_names_the_scope_and_the_hash(self):
        document = json.loads(build_provenance_document(_scope()))
        assert document["schema"] == PROVENANCE_SCHEMA
        assert document["domain"] == "party"
        assert document["adapter"] == "fabric-warehouse"
        assert document["toolkit"] == "9.9.9"
        assert document["provenanceHash"] == _scope().provenance_hash()

    def test_every_input_digest_matches_its_content(self):
        scope = _scope()
        digests = {item.name: item.sha256 for item in _inputs(scope)}
        for item in scope.inputs:
            expected = hashlib.sha256(item.content.encode("utf-8")).hexdigest()
            assert digests[item.name] == expected

    def test_inputs_are_ordered_like_the_hash(self):
        """Same total order as BuildScope.provenance_hash -- see #600."""
        scope = _scope(
            inputs=(
                ProvenanceInput(name="b.ttl", content="2"),
                ProvenanceInput(name="a.ttl", content="2"),
                ProvenanceInput(name="a.ttl", content="1"),
            )
        )
        names = [(item.name, item.sha256) for item in _inputs(scope)]
        assert [name for name, _ in names] == ["a.ttl", "a.ttl", "b.ttl"]

    def test_editing_one_input_moves_that_digest_and_the_hash(self):
        before = json.loads(build_provenance_document(_scope()))
        after = json.loads(
            build_provenance_document(
                _scope(
                    inputs=(
                        ProvenanceInput(
                            name="model/ontologies/party.ttl", content="ontology bytes"
                        ),
                        ProvenanceInput(
                            name="bindings/customer.binding.yaml", content="EDITED"
                        ),
                    )
                )
            )
        )
        assert before["provenanceHash"] != after["provenanceHash"]
        changed = [
            b["name"]
            for b, a in zip(before["inputs"], after["inputs"], strict=True)
            if b["sha256"] != a["sha256"]
        ]
        assert changed == ["bindings/customer.binding.yaml"]

    def test_reordering_the_same_inputs_changes_nothing(self):
        forward = _scope()
        reversed_scope = _scope(inputs=tuple(reversed(forward.inputs)))
        assert build_provenance_document(forward) == build_provenance_document(reversed_scope)


class TestArtifactPath:
    def test_silver_lane_path(self):
        assert provenance_artifact_path("party") == "metadata/party.provenance.json"

    def test_gold_lane_is_a_distinct_path(self):
        assert provenance_artifact_path("party", lane="gold") == (
            "metadata/party-gold.provenance.json"
        )

    def test_artifact_returns_path_and_content(self):
        path, content = provenance_artifact(_scope())
        assert path == "metadata/party.provenance.json"
        assert json.loads(content)["domain"] == "party"


class _Input:
    __slots__ = ("name", "sha256")

    def __init__(self, name: str, sha256: str) -> None:
        self.name = name
        self.sha256 = sha256


def _inputs(scope: BuildScope) -> list[_Input]:
    document = json.loads(build_provenance_document(scope))
    return [_Input(item["name"], item["sha256"]) for item in document["inputs"]]
