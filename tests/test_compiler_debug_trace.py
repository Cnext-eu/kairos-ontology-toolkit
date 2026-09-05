# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for compiler debug trace points (DD-151).

The compiler's stable contract is ``CompileDiagnostic`` (not log events). These tests
verify the targeted ``logger.debug`` trace points in ``core/compiler/kernel.py`` and
``core/compiler/emit.py`` emit under DEBUG level and stay silent above it. They assert on
stable substrings, not exact format.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from kairos_ontology.core.compiler.emit import emit_artifacts
from kairos_ontology.core.compiler.kernel import build_compile_plan

kernel_logger = logging.getLogger("kairos_ontology.core.compiler.kernel")
emit_logger = logging.getLogger("kairos_ontology.core.compiler.emit")


@pytest.fixture(autouse=True)
def _capture_kernel_emit_logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.DEBUG, logger="kairos_ontology.core.compiler.kernel")
    caplog.set_level(logging.DEBUG, logger="kairos_ontology.core.compiler.emit")
    return caplog


def _hub_with_binding(tmp_path: Path) -> Path:
    """Create a minimal hub root with one entity binding for trace-point coverage."""
    ontologies = tmp_path / "model" / "ontologies"
    ontologies.mkdir(parents=True)
    (ontologies / "sample.ttl").write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "<https://kairos.cnext.eu/ontologies/sample>\n"
        "  a owl:Ontology ;\n"
        "  rdfs:label \"Sample\" ;\n"
        "  owl:versionInfo \"1\" .\n"
        "<https://kairos.cnext.eu/ontologies/sample/Thing>\n"
        "  a owl:Class ;\n"
        "  rdfs:label \"Thing\" .\n",
        encoding="utf-8",
    )
    shapes = tmp_path / "model" / "shapes"
    shapes.mkdir(parents=True, exist_ok=True)
    (shapes / "sample-shapes.ttl").write_text(
        "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
        "<https://kairos.cnext.eu/ontologies/sample/ThingShape>\n"
        "  a sh:NodeShape ;\n"
        "  sh:targetClass <https://kairos.cnext.eu/ontologies/sample/Thing> .\n",
        encoding="utf-8",
    )
    bindings = tmp_path / "integration" / "bindings"
    bindings.mkdir(parents=True)
    sources = tmp_path / "integration" / "sources" / "sample"
    sources.mkdir(parents=True)
    (sources / "source.ttl").write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix kairos: <https://kairos.cnext.eu/ontology/> .\n"
        "<https://kairos.cnext.eu/sources/sample>\n"
        "  a owl:Ontology ;\n"
        "  rdfs:label \"Sample source\" ;\n"
        "  owl:versionInfo \"1\" .\n"
        "kairos:sample_things a owl:Class ; rdfs:label \"sample things\" .\n",
        encoding="utf-8",
    )
    (bindings / "sample-to-sample.binding.yaml").write_text(
        "domain: sample\n"
        "entity:\n"
        "  canonicalClass: https://kairos.cnext.eu/ontologies/sample/Thing\n"
        "  name: thing\n"
        "source:\n"
        "  relation: kairos:sample_things\n"
        "  sourceModel: integration/sources/sample/source.ttl\n"
        "  fields:\n"
        "    - field: id\n"
        "      property: kairos:hasId\n"
        "      type: string\n"
        "    - field: label\n"
        "      property: kairos:hasLabel\n"
        "      type: string\n"
        "features:\n"
        "  identity:\n"
        "    - field: id\n"
        "    - field: label\n"
        "  technical:\n"
        "    - field: id\n"
        "      property: kairos:hasId\n"
        "      type: string\n",
        encoding="utf-8",
    )
    (tmp_path / "kairos.yaml").write_text(
        "schema_version: '1'\n"
        "version: 5\n"
        "name: trace-hub\n"
        "default_domain: sample\n"
        "adapter: fabric\n"
        "domains:\n"
        "  - name: sample\n"
        "    ontology: model/ontologies/sample.ttl\n"
        "    shapes:\n"
        "      - model/shapes/sample-shapes.ttl\n"
        "    bindings:\n"
        "      - integration/bindings/sample-to-sample.binding.yaml\n",
        encoding="utf-8",
    )
    return tmp_path


def test_build_compile_plan_emits_scope_resolution_trace(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    hub = _hub_with_binding(tmp_path)
    with caplog.at_level(logging.DEBUG, logger="kairos_ontology.core.compiler.kernel"):
        build_compile_plan(hub, "sample")
    messages = "\n".join(r.getMessage() for r in caplog.records if r.name == kernel_logger.name)
    assert "compile scope resolved" in messages
    assert "domain=sample" in messages


def test_compile_domain_emits_entry_trace(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    from kairos_ontology.core.compiler.kernel import compile_domain

    hub = _hub_with_binding(tmp_path)
    with caplog.at_level(logging.DEBUG, logger="kairos_ontology.core.compiler.kernel"):
        compile_domain(hub, "sample", "check")
    messages = "\n".join(r.getMessage() for r in caplog.records if r.name == kernel_logger.name)
    assert "compile domain:" in messages
    assert "mode=check" in messages


def test_emit_artifacts_emits_plan_and_commit_trace(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    target = tmp_path / "out"
    target.mkdir()
    rendered = {"artifact.sql": "SELECT 1\n"}
    with caplog.at_level(logging.DEBUG, logger="kairos_ontology.core.compiler.emit"):
        result = emit_artifacts(rendered, target)
    messages = "\n".join(r.getMessage() for r in caplog.records if r.name == emit_logger.name)
    assert "emit plan:" in messages
    assert "emit commit:" in messages
    assert "artifact.sql" not in messages or "artifacts=1" in messages
    assert result.written == ("artifact.sql",)


def test_trace_points_silent_above_debug(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    hub = _hub_with_binding(tmp_path)
    caplog.set_level(logging.INFO)
    build_compile_plan(hub, "sample")
    kernel_records = [r for r in caplog.records if r.name == kernel_logger.name]
    assert all(r.levelno >= logging.INFO for r in kernel_records)
    debug_records = [r for r in kernel_records if r.levelno == logging.DEBUG]
    assert debug_records == []
