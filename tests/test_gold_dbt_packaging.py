# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Gold dbt models ship inside the installable medallion dbt package (issue #665).

They used to be written only under ``ontology-hub-publish/powerbi/<domain>/dbt/``, a
directory with no ``dbt_project.yml`` -- so dbt's ``packages.yml`` ``subdirectory:``
mechanism could not install it and the only way to consume a working Gold model was to
hand-copy three files into the downstream dataplatform, where they then went stale
silently on every re-emit.

The medallion side was already wired for them: the ``dbt_project.yml`` template has
carried a ``models/gold/<domain>`` config block, and ``_existing_gold_domains()`` has
scanned for it. Only ``_planned_artifact_paths()`` never listed the Gold paths, so the
compile result filtered them out before anything reached disk.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.compiler import CompileMode, compile_domain

_HUB = Path(__file__).parent / "scenarios" / "v5-hub"
_GOVERNED_HUB = Path(__file__).parent / "scenarios" / "v5-governed-hub"

# Same shape as tests/test_cli_emit_gold.py: v5-hub carries no Gold profile of its own,
# so a domain that produces Gold dbt models has to declare one.
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


def _copy_hub(tmp_path: Path) -> Path:
    hub = tmp_path / "hub"
    shutil.copytree(_HUB, hub)
    ext_dir = hub / "model" / "extensions"
    ext_dir.mkdir(parents=True, exist_ok=True)
    (ext_dir / "party-gold-ext.ttl").write_text(_PARTY_GOLD_EXT, encoding="utf-8")
    return hub


def test_compile_plans_and_renders_the_gold_dbt_models():
    """Planned and rendered sets must agree, or emit silently drops the Gold models."""
    result = compile_domain(_GOVERNED_HUB, "party", CompileMode.EXPLAIN)
    artifacts = result.artifact_dict()

    gold = sorted(path for path in artifacts if path.startswith("models/gold/"))
    assert gold, "no Gold dbt models were rendered for a Gold-bearing domain"
    assert any(path.endswith(".sql") for path in gold)
    assert "models/gold/party/_party__gold_models.yml" in artifacts
    assert "models/gold/party/_party__exposures.yml" in artifacts

    # The bug: rendered but not planned, so `compile --emit` filtered them back out.
    assert set(result.plan.artifact_paths) == set(artifacts)


def test_emit_writes_gold_into_the_installable_medallion_package(tmp_path, monkeypatch):
    """One `compile --emit` must produce both the models and a matching dbt_project.yml.

    `_existing_gold_domains()` scans the target directory, which runs *before* this run
    writes its own `models/gold/**` -- so without unioning in the plan's own gold
    domains, a first emit produced the models next to a `dbt_project.yml` that did not
    configure them, and only converged on a second run.
    """
    hub = _copy_hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(
        cli,
        ["compile", "party", "--emit", "--confirm-emit"],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )
    assert result.exit_code == 0, result.output

    target = hub.parent / "ontology-hub-publish" / "medallion" / "dbt"

    # Installable as a dbt package, exactly like Silver.
    assert (target / "dbt_project.yml").is_file()
    assert (target / "packages.yml").is_file()

    models = sorted(path.name for path in (target / "models" / "gold" / "party").glob("*"))
    assert models, "Gold dbt models did not reach the emitted package"
    assert "_party__gold_models.yml" in models
    assert "_party__exposures.yml" in models

    # ...and configured on the FIRST emit, not only after a second converging run.
    project = yaml.safe_load((target / "dbt_project.yml").read_text(encoding="utf-8"))
    gold_config = project["models"]["kairos_medallion_project"]["gold"]
    assert "party" in gold_config
    assert gold_config["party"]["+schema"] == "gold_party"


def test_second_emit_is_stable(tmp_path, monkeypatch):
    """Re-emitting must not add, drop, or churn Gold artifacts."""
    hub = _copy_hub(tmp_path)
    monkeypatch.chdir(hub)
    target = hub.parent / "ontology-hub-publish" / "medallion" / "dbt"

    def emit() -> dict[str, str]:
        outcome = CliRunner().invoke(
            cli,
            ["compile", "party", "--emit", "--confirm-emit"],
            env={"KAIROS_SKILL_CONTEXT": "1"},
        )
        assert outcome.exit_code == 0, outcome.output
        return {
            path.relative_to(target).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(target.rglob("*"))
            if path.is_file() and "gold" in path.as_posix()
        }

    first = emit()
    assert first == emit()
