# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""How many domains `validate` SHACL-checks at once (#998).

The worker count used to be settable only through an undocumented environment variable,
so a hub on a larger runner could not ask for more, and CI printed "across 2 workers"
with no way to change it.
"""

from __future__ import annotations

from click.testing import CliRunner

from kairos_ontology.cli import validation as validation_commands
from kairos_ontology.cli.main import cli
from kairos_ontology.core import validator
from kairos_ontology.core.validator import ENV_VALIDATE_JOBS, _shacl_worker_count


def test_the_flag_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv(ENV_VALIDATE_JOBS, "2")
    assert _shacl_worker_count(10, 4) == 4


def test_the_environment_is_the_fallback(monkeypatch):
    monkeypatch.setenv(ENV_VALIDATE_JOBS, "3")
    assert _shacl_worker_count(10) == 3


def test_the_default_is_the_cores_capped(monkeypatch):
    monkeypatch.delenv(ENV_VALIDATE_JOBS, raising=False)
    monkeypatch.setattr(validator.os, "cpu_count", lambda: 64)
    assert _shacl_worker_count(20) == validator._MAX_SHACL_WORKERS


def test_never_more_workers_than_domains(monkeypatch):
    monkeypatch.delenv(ENV_VALIDATE_JOBS, raising=False)
    assert _shacl_worker_count(2, 8) == 2


def test_the_cli_passes_jobs_through(tmp_path, monkeypatch):
    hub = tmp_path / "ontology-hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    (hub / "model" / "shapes").mkdir()
    calls: dict = {}
    monkeypatch.setattr(validation_commands, "run_validation", lambda **kw: calls.update(kw))
    monkeypatch.setattr(validation_commands, "check_discovery_gate", lambda *a, **k: [])
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        cli, ["validate", "--syntax", "--jobs", "4", "--report-format", "none"]
    )
    assert result.exit_code == 0, result.output
    assert calls["shacl_jobs"] == 4


def test_zero_jobs_is_refused():
    result = CliRunner().invoke(cli, ["validate", "--jobs", "0"])
    assert result.exit_code == 2
