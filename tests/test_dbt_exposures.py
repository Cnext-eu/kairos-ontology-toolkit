# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""dbt ``exposures:`` emission for Gold Power BI reports (issue #630).

Before this, no dbt ``exposures.yml``/``exposure:`` construct was ever emitted by
the toolkit (confirmed by grepping ``src/`` and ``templates/`` for both strings --
the only "exposure" hits are the unrelated ``dimension_exposure`` naming/policy
field). ``dbt docs generate``'s lineage graph therefore stopped at the last dbt
model and never showed the downstream Power BI reports/dashboards that actually
consume it.

:func:`kairos_ontology.core.projections.dbt.gold_render.render_gold_dbt_artifacts`
now emits one ``exposures.yml`` per Gold domain (mirroring the existing
``_<domain>__gold_models.yml`` per-domain convention), declaring the domain's one
Power BI report as a ``dashboard`` exposure that ``depends_on`` every actual Gold
dbt model it is built from.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from kairos_ontology.core.projections.dbt import (
    bind_sources,
    normalize_contract,
    plan_materialization,
    render_project,
    shape_project,
)
from kairos_ontology.core.projections.medallion_gold_projector import (
    generate_gold_artifacts,
)
from tests.scenarios.conftest import (
    EXTENSIONS_DIR,
    MAPPINGS_DIR,
    SHAPES_DIR,
    SOURCES_DIR,
    TEMPLATE_DIR,
    _load_ontology,
)
from tests.test_dbt_phases import _client_inputs

# #619 Bugs 4/6: every Direct Lake (fabric) Gold product requires
# gold.direct_lake_connection (mirrors the fixture in test_gold_projector.py).
_DIRECT_LAKE_HUB_ROOT = Path(tempfile.mkdtemp(prefix="kairos-exposures-hub-"))
(_DIRECT_LAKE_HUB_ROOT / "kairos.yaml").write_text(
    "gold:\n"
    "  direct_lake_connection:\n"
    "    environments:\n"
    "      DEV:\n"
    "        workspace_id: 11111111-1111-1111-1111-111111111111\n"
    "        lakehouse_id: 22222222-2222-2222-2222-222222222222\n",
    encoding="utf-8",
)

_EXPOSURES_PATH = "invoice/dbt/models/gold/invoice/_invoice__exposures.yml"


def _metadata(domain: str) -> dict[str, str]:
    return {
        "iri": f"https://acme.example/ontology/{domain}",
        "version": "1.0.0",
        "toolkit_version": "test",
    }


def _generate_gold(domain: str) -> dict[str, str]:
    graph, namespace, classes = _load_ontology(domain)
    peers = [EXTENSIONS_DIR / "client-silver-ext.ttl"] if domain == "invoice" else []
    return generate_gold_artifacts(
        classes=classes,
        graph=graph,
        template_dir=TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name=domain,
        ontology_metadata=_metadata(domain),
        sources_dir=SOURCES_DIR,
        mappings_dir=MAPPINGS_DIR,
        gold_ext_path=EXTENSIONS_DIR / f"{domain}-gold-ext.ttl",
        silver_ext_path=EXTENSIONS_DIR / f"{domain}-silver-ext.ttl",
        peer_ext_paths=peers,
        target_platform="fabric",
        hub_root=_DIRECT_LAKE_HUB_ROOT,
    )


def test_exposures_yaml_depends_on_real_gold_models() -> None:
    """Invoice (a real Gold domain, with an approved calendar) gets a valid exposures.yml."""
    artifacts = _generate_gold("invoice")
    assert _EXPOSURES_PATH in artifacts

    document = yaml.safe_load(artifacts[_EXPOSURES_PATH])
    assert document["version"] == 2
    assert len(document["exposures"]) == 1
    exposure = document["exposures"][0]

    assert exposure["type"] == "dashboard"
    assert exposure["name"] == "invoice_gold_powerbi_report"
    assert exposure["maturity"]
    assert exposure["url"]
    assert exposure["owner"]["name"]
    assert exposure["owner"]["email"]

    # depends_on must be dbt ref() expressions naming *actual* Gold dbt models --
    # not placeholders -- cross-checked against the projector's own Gold product
    # report (the same typed plan gold_render.py consumes to write the .sql files).
    gold_report = json.loads(artifacts["invoice/invoice-gold-product.json"])
    expected_models = {table["name"] for table in gold_report["tables"]}
    assert gold_report["calendar"] is not None and gold_report["calendar"]["approved"]
    expected_models.add("dim_date")

    depends_on = exposure["depends_on"]
    referenced = set()
    for entry in depends_on:
        match = re.fullmatch(r"ref\('([^']+)'\)", entry)
        assert match, f"not a ref() expression: {entry!r}"
        referenced.add(match.group(1))
    assert referenced == expected_models

    # Every referenced model must actually exist as an emitted Gold .sql file.
    emitted_models = {
        path.rsplit("/", 1)[-1].removesuffix(".sql")
        for path in artifacts
        if path.startswith("invoice/dbt/models/gold/") and path.endswith(".sql")
    }
    assert referenced <= emitted_models

    # Sorted/deterministic, not insertion order.
    assert depends_on == sorted(depends_on)


def test_exposures_yaml_is_deterministic() -> None:
    """Re-projecting the same compiled inputs produces byte-identical exposures.yml."""
    first = _generate_gold("invoice")
    second = _generate_gold("invoice")
    assert first[_EXPOSURES_PATH] == second[_EXPOSURES_PATH]


def test_domain_without_gold_output_emits_no_exposures_file() -> None:
    """A domain with no registered Gold profile must not emit a dangling exposures.yml."""
    inputs = replace(_client_inputs(), gold_extension=None)
    bound = bind_sources(inputs)
    contract = normalize_contract(bound)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    assert shaped.gold_product is None
    assert plan.gold is None

    artifacts = render_project(shaped, plan)

    assert not any(
        "exposures" in path for path in artifacts if not path.startswith("__")
    )


def test_domain_with_gold_output_emits_exposures_file_via_full_project_render() -> None:
    """The general project renderer (not just the Gold-only path) wires exposures.yml too."""
    inputs = _client_inputs()  # client-gold-ext.ttl registers a Gold profile
    bound = bind_sources(inputs)
    contract = normalize_contract(bound)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    assert shaped.gold_product is not None
    assert plan.gold is not None

    artifacts = render_project(shaped, plan)

    assert plan.gold.exposures_artifact_path in artifacts
    document = yaml.safe_load(artifacts[plan.gold.exposures_artifact_path])
    assert document["exposures"][0]["type"] == "dashboard"


def _adapter_available(adapter: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(f"dbt.adapters.{adapter}") is not None


def test_real_dbt_parse_accepts_exposures_yaml(tmp_path: Path) -> None:
    """Best-effort real ``dbt parse`` of the whole emitted client project (skipped w/o dbt).

    Mirrors ``tests/test_dbt_seeds_parse.py``'s fixture pattern: render a full,
    real project tree (client domain, fabric adapter, Gold profile registered) and
    hand it to dbt itself rather than only asserting the YAML shape statically --
    the one check that would catch dbt actually rejecting the ``exposures:`` schema.
    """
    pytest.importorskip("dbt")
    dbt_command = shutil.which("dbt")
    if dbt_command is None:
        pytest.skip("dbt command is not installed; exposures.yml is covered statically")
    if not _adapter_available("fabric"):
        pytest.skip("dbt-fabric adapter is not installed; exposures.yml is covered statically")

    inputs = _client_inputs()
    bound = bind_sources(inputs)
    contract = normalize_contract(bound)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    assert shaped.gold_product is not None and plan.gold is not None
    artifacts = render_project(shaped, plan)
    assert plan.gold.exposures_artifact_path in artifacts

    project = tmp_path / "exposures_probe"
    for path, content in artifacts.items():
        if path.startswith("__"):
            continue
        target = project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    for sub in ("analyses", "tests", "seeds", "snapshots", "docs"):
        (project / sub).mkdir(parents=True, exist_ok=True)

    profiles_dir = project / ".dbt"
    profiles_dir.mkdir()
    (profiles_dir / "profiles.yml").write_text(
        "client_project:\n"
        "  target: dev\n"
        "  outputs:\n"
        "    dev:\n"
        "      type: fabric\n"
        "      driver: ODBC Driver 18 for SQL Server\n"
        "      server: example.datawarehouse.fabric.microsoft.com\n"
        "      database: example\n"
        "      schema: dbo\n"
        "      authentication: CLI\n",
        encoding="utf-8",
    )

    deps = subprocess.run(
        [dbt_command, "deps", "--no-version-check"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert deps.returncode == 0, deps.stdout + deps.stderr

    parse = subprocess.run(
        [dbt_command, "parse", "--no-version-check", "--profiles-dir", ".dbt"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert parse.returncode == 0, parse.stdout + parse.stderr
