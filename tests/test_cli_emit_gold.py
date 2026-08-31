# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``kairos-ontology emit-gold`` (issue #619 Bug 2): a real CLI entry point for Gold/PowerBI
projection, since previously the only way to reach ``project_downstream_compile_plan
('powerbi', plan)`` was the Python API.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.hub_utils import publish_root

_HAS_DOTNET = shutil.which("dotnet") is not None

_V5_FK_HUB = Path(__file__).parent / "scenarios" / "v5-hub"

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


def _copy_hub(tmp_path: Path, *, with_gold_ext: bool = True) -> Path:
    hub = tmp_path / "hub"
    shutil.copytree(_V5_FK_HUB, hub)
    if with_gold_ext:
        ext_dir = hub / "model" / "extensions"
        ext_dir.mkdir(parents=True, exist_ok=True)
        (ext_dir / "party-gold-ext.ttl").write_text(_PARTY_GOLD_EXT, encoding="utf-8")
    return hub


def test_dry_run_reports_and_writes_nothing(tmp_path, monkeypatch):
    hub = _copy_hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["emit-gold", "party"])

    assert result.exit_code == 0, result.output
    assert "Would emit" in result.output
    assert "--confirm-emit" in result.output
    assert not (publish_root(hub) / "powerbi").exists()


def test_confirm_emit_writes_tmdl_pbip_tree(tmp_path, monkeypatch):
    hub = _copy_hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["emit-gold", "party", "--confirm-emit"])

    assert result.exit_code == 0, result.output
    assert "Emitted" in result.output
    target = publish_root(hub) / "powerbi"
    assert (target / "party" / "Party.pbip").is_file()
    assert (target / "party" / "Party.SemanticModel" / "definition" / "model.tmdl").is_file()
    assert (target / ".kairos-compile-manifest.gold-party.json").is_file()


def test_confirm_emit_is_idempotent(tmp_path, monkeypatch):
    hub = _copy_hub(tmp_path)
    monkeypatch.chdir(hub)
    runner = CliRunner()

    first = runner.invoke(cli, ["emit-gold", "party", "--confirm-emit"])
    second = runner.invoke(cli, ["emit-gold", "party", "--confirm-emit"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output


def test_master_gold_erd_is_written_alongside_the_domain_erd(tmp_path, monkeypatch):
    """DD-011's hub-wide bound Gold ERD, ported from the retired ``run_projections``
    orchestrator to the real ``emit-gold`` CLI path. ``generate_master_gold_erd`` scans
    the whole shared publish root, so it accumulates across separate single-domain
    invocations without this command needing to know about other domains itself."""
    hub = _copy_hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["emit-gold", "party", "--confirm-emit"])

    assert result.exit_code == 0, result.output
    master_erd = publish_root(hub) / "powerbi" / "master-gold-erd.mmd"
    assert master_erd.is_file()
    content = master_erd.read_text(encoding="utf-8")
    assert "erDiagram" in content
    assert "party" in content


def test_domain_without_gold_profile_fails_clearly(tmp_path, monkeypatch):
    hub = _copy_hub(tmp_path, with_gold_ext=False)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["emit-gold", "party"])

    assert result.exit_code != 0
    assert "no authored Gold profile" in result.output


def test_missing_direct_lake_connection_surfaces_as_click_error(tmp_path, monkeypatch):
    hub = _copy_hub(tmp_path)
    config = hub / "kairos.yaml"
    config.write_text(
        "\n".join(
            line
            for line in config.read_text(encoding="utf-8").splitlines()
            if "gold" not in line and "direct_lake" not in line and "workspace_id" not in line
            and "lakehouse_id" not in line and "environments" not in line and "DEV" not in line
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["emit-gold", "party"])

    assert result.exit_code != 0
    assert "direct-lake-connection-missing" in result.output


@pytest.mark.skipif(not _HAS_DOTNET, reason="dotnet SDK not installed; TOM SDK validation is best-effort")
def test_confirm_emit_runs_real_tom_sdk_validation_by_default(tmp_path, monkeypatch):
    hub = _copy_hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["emit-gold", "party", "--confirm-emit"])

    assert result.exit_code == 0, result.output
    assert "TOM SDK validation unavailable" not in result.output
    assert "TOM SDK structural validation failed" not in result.output


def test_confirm_emit_reports_when_dotnet_unavailable(tmp_path, monkeypatch):
    hub = _copy_hub(tmp_path)
    monkeypatch.chdir(hub)
    monkeypatch.setattr(
        "kairos_ontology.core.projections.dbt.tmdl_validate.shutil.which", lambda _: None
    )

    result = CliRunner().invoke(cli, ["emit-gold", "party", "--confirm-emit"])

    assert result.exit_code == 0, result.output
    assert "TOM SDK validation unavailable" in result.output
    assert (publish_root(hub) / "powerbi" / "party" / "Party.pbip").is_file()


def test_skip_tmdl_validation_flag_bypasses_it(tmp_path, monkeypatch):
    hub = _copy_hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(
        cli, ["emit-gold", "party", "--confirm-emit", "--skip-tmdl-validation"]
    )

    assert result.exit_code == 0, result.output
    assert "TOM SDK" not in result.output


def test_blocked_compile_plan_fails_before_projecting(tmp_path, monkeypatch):
    hub = _copy_hub(tmp_path)
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace(
            "expression: customer_id", "expression: missing_customer_id"
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["emit-gold", "party"])

    assert result.exit_code != 0
    assert "compile plan is blocked" in result.output


def test_two_domains_share_one_parameter_yml_without_colliding(tmp_path):
    """Sequential per-domain Gold emits must merge on the shared root artifact (issue #664).

    ``parameter.yml`` is hub-wide: fabric-cicd reads exactly one from the root of
    ``repository_directory``, so every domain's Gold emit writes the same path into the
    same shared directory. Each domain owns only its own
    ``.kairos-compile-manifest.gold-<domain>.json``, so the second domain's emit saw an
    unowned file already on disk and failed closed with ``ArtifactCollisionError`` --
    which made the recommended one-Gold-extension-per-owning-domain pattern (#661)
    impossible to actually run.

    Exercised at the emit layer because both v5 hub fixtures are single-domain; this is
    the exact call ``cli/emit_gold.py`` makes, with the same shared path and per-domain
    manifest names.
    """
    from kairos_ontology.core.compiler.emit import emit_artifacts
    from kairos_ontology.core.projections.dbt.gold_render import PARAMETER_ARTIFACT_PATH

    target = tmp_path / "powerbi"
    shared = (PARAMETER_ARTIFACT_PATH,)

    emit_artifacts(
        {PARAMETER_ARTIFACT_PATH: "find_replace: [booking]\n", "booking/model.tmdl": "b\n"},
        target,
        manifest_name=".kairos-compile-manifest.gold-booking.json",
        replace_unowned_paths=shared,
    )
    emit_artifacts(
        {PARAMETER_ARTIFACT_PATH: "find_replace: [party]\n", "party/model.tmdl": "p\n"},
        target,
        manifest_name=".kairos-compile-manifest.gold-party.json",
        replace_unowned_paths=shared,
    )

    # The second domain wins the shared file; neither domain's own artifacts are lost.
    assert (target / PARAMETER_ARTIFACT_PATH).read_text(
        encoding="utf-8"
    ) == "find_replace: [party]\n"
    assert (target / "booking" / "model.tmdl").is_file()
    assert (target / "party" / "model.tmdl").is_file()


def test_repeated_emit_for_one_domain_is_idempotent(tmp_path, monkeypatch):
    """Re-emitting the same domain must not trip the shared-artifact collision check."""
    hub = _copy_hub(tmp_path)
    monkeypatch.chdir(hub)

    for _ in range(2):
        result = CliRunner().invoke(cli, ["emit-gold", "party", "--confirm-emit"])
        assert result.exit_code == 0, result.output

    assert (publish_root(hub) / "powerbi" / "parameter.yml").is_file()


def test_gold_dbt_models_are_not_written_beside_the_powerbi_artifacts(tmp_path, monkeypatch):
    """Gold dbt models ship in the medallion package, not the Power BI bundle (issue #665).

    ``powerbi/<domain>/dbt/`` has no ``dbt_project.yml``, so dbt's ``packages.yml``
    ``subdirectory:`` mechanism could never install it -- those files could only be
    hand-copied downstream, and went stale silently on the next emit.
    """
    hub = _copy_hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["emit-gold", "party", "--confirm-emit"])
    assert result.exit_code == 0, result.output

    powerbi = publish_root(hub) / "powerbi"
    assert not list(powerbi.rglob("dbt"))
    assert not list(powerbi.rglob("models"))
    # `<domain>-gold-ddl.sql` is a Power BI-side artifact and legitimately stays here;
    # only the dbt *models* moved.
    assert not [path for path in powerbi.rglob("*.sql") if not path.name.endswith("-gold-ddl.sql")]
