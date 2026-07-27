# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Fresh-hub acceptance scenario for the v5 compiler."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from kairos_ontology.core.compiler import CompileMode, compile_domain
from kairos_ontology.core.compiler.emit import emit_artifacts

_HUB = Path(__file__).parent / "v5-hub"


def test_v5_scenario_check_explain_and_deterministic_plan():
    checked = compile_domain(_HUB, "party", CompileMode.CHECK)
    explained = compile_domain(_HUB, "party", CompileMode.EXPLAIN)
    repeated = compile_domain(_HUB, "party", CompileMode.EXPLAIN)
    assert checked.succeeded, [item.render() for item in checked.diagnostics.items]
    assert explained.succeeded
    assert len(explained.explain.entities) == 2
    assert explained.artifacts == repeated.artifacts
    artifacts = explained.artifact_dict()
    assert "models/silver/party/customer.sql" in artifacts
    assert "models/silver/party/country.sql" in artifacts
    assert "upper(" in artifacts["models/silver/party/customer.sql"].lower()
    assert "left join {{ ref('country') }}" in artifacts["models/silver/party/customer.sql"].lower()
    assert "_match_count" in artifacts["models/silver/party/customer.sql"]
    assert "tests/party/customer__reconcile_rowcount.sql" in artifacts
    assert "contracts/dq-runtime-result-contract.schema.json" not in artifacts
    assert not any("release" in path for path in artifacts)
    schema = yaml.safe_load(artifacts["models/silver/party/_party__models.yml"])
    customer = next(model for model in schema["models"] if model["name"] == "customer")
    customer_name = next(
        column for column in customer["columns"] if column["name"] == "customer_name"
    )
    assert "not_null" in customer_name["tests"]


def test_v5_scenario_is_stateless_and_layered():
    before = {path.relative_to(_HUB) for path in _HUB.rglob("*")}
    compile_domain(_HUB, "party")
    after = {path.relative_to(_HUB) for path in _HUB.rglob("*")}
    assert before == after
    forbidden = (
        ".kairos-state",
        "readiness",
        "proposal",
        "virtual-source",
        "preparation",
        "mapping.ttl",
        "silver-ext",
        "release",
    )
    assert not any(any(token in str(path).lower() for token in forbidden) for path in after)
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import kairos_ontology.core.compiler; "
                "assert 'kairos_ontology.mdm' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr


def test_v5_scenario_emit_is_byte_deterministic_and_manifest_owned(tmp_path):
    plan = compile_domain(_HUB, "party", CompileMode.EMIT)
    first = emit_artifacts(plan.artifact_dict(), tmp_path, owned_subtree="party")
    first_bytes = {
        path.relative_to(first.target_dir): path.read_bytes()
        for path in first.target_dir.rglob("*")
        if path.is_file()
    }
    second = emit_artifacts(plan.artifact_dict(), tmp_path, owned_subtree="party")
    second_bytes = {
        path.relative_to(second.target_dir): path.read_bytes()
        for path in second.target_dir.rglob("*")
        if path.is_file()
    }
    assert first_bytes == second_bytes
    assert (second.target_dir / "models/silver/party/customer.sql").is_file()
