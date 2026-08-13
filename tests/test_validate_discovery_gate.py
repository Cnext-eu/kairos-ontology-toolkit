# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI-level tests for domain-scoped DD-148 discovery-gate checking on `validate` (#389/#390).

`validate --syntax --domain <active-domain>` is documented (kairos-design-domain/SKILL.md
Gate 5) as a narrower, discovery-gate-independent check. Before this fix, an unresolved
discovery-conformance judgment tagged to any domain (or untagged) hard-failed every
`validate` call regardless of `--domain`, contradicting `--syntax`'s own `--help` text
("Validate syntax only"). These tests exercise `check_discovery_gate()`'s domain scoping
through the actual CLI command, isolating the rest of `validate` (SHACL/consistency/GDPR/
accelerator resolution) via monkeypatching, the same way test_validate_format_alias.py does.
"""

from __future__ import annotations

from click.testing import CliRunner

from discovery_fixtures import write_discovery_artifact_with_unresolved_judgment
from kairos_ontology.cli import validation as validation_commands
from kairos_ontology.cli.validation import validate
from kairos_ontology.core import reference_modules
from kairos_ontology.core.reference_modules import AcceleratorResolution


def _prepare_hub(tmp_path, *, likely_domains=None):
    hub = tmp_path / "hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    (hub / "model" / "shapes").mkdir(parents=True)
    (hub / "model" / "ontologies" / "party.ttl").write_text("", encoding="utf-8")
    write_discovery_artifact_with_unresolved_judgment(hub, likely_domains=likely_domains)
    return hub


def _invoke(args, tmp_path=None, hub=None, monkeypatch=None):
    monkeypatch.setattr(validation_commands, "run_gdpr_validation", lambda **kw: None)
    monkeypatch.setattr(validation_commands, "run_validation", lambda **kw: None)
    monkeypatch.setattr(
        reference_modules,
        "resolve_hub_accelerator_detailed",
        lambda **kw: AcceleratorResolution(None, "none", None),
    )
    monkeypatch.chdir(hub)
    return CliRunner().invoke(validate, args)


def test_validate_syntax_succeeds_when_unresolved_judgment_tagged_to_other_domain(
    tmp_path, monkeypatch
):
    hub = _prepare_hub(tmp_path, likely_domains=["customs"])
    result = _invoke(["--syntax", "--domain", "party"], hub=hub, monkeypatch=monkeypatch)
    assert result.exit_code == 0, result.output


def test_validate_syntax_fails_when_unresolved_judgment_tagged_to_matching_domain(
    tmp_path, monkeypatch
):
    hub = _prepare_hub(tmp_path, likely_domains=["party"])
    result = _invoke(["--syntax", "--domain", "party"], hub=hub, monkeypatch=monkeypatch)
    assert result.exit_code != 0
    assert "Unresolved discovery item" in result.output


def test_validate_syntax_fails_when_unresolved_judgment_is_cross_cutting(tmp_path, monkeypatch):
    hub = _prepare_hub(tmp_path, likely_domains=None)
    result = _invoke(["--syntax", "--domain", "party"], hub=hub, monkeypatch=monkeypatch)
    assert result.exit_code != 0
    assert "Unresolved discovery item" in result.output


def test_validate_without_domain_flag_still_gates_on_everything(tmp_path, monkeypatch):
    # Omitting --domain entirely must not weaken whole-hub validation: an unresolved
    # judgment tagged to a domain unrelated to anything currently modeled must still block.
    hub = _prepare_hub(tmp_path, likely_domains=["customs"])
    result = _invoke(["--syntax"], hub=hub, monkeypatch=monkeypatch)
    assert result.exit_code != 0
    assert "Unresolved discovery item" in result.output
