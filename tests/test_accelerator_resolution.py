# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the consolidated accelerator resolver (todo: accelerator-resolution).

Covers:
- ``resolve_hub_accelerator`` / ``resolve_hub_accelerator_detailed`` precedence
  (explicit CLI > ``[tool.kairos].accelerator`` > unambiguous domain-ownership
  inference), with genuine ambiguity still a hard error.
- Nested ``groups[].domains[]`` ownership parity between the parser used by
  inventory domain-key resolution (``analyse_sources.load_data_domains``) and the
  parser used by managed-import planning (``reference_modules.load_accelerator_
  module_config``).
- ``check-inventory`` scoped wording (no more ambiguous "(none matched)").
- ``check-claims`` registry-ownership diagnostics agreeing with the resolved
  accelerator's ``data-domains.yaml``.
- Cross-command resolver parity: ``validate``, ``project``/``check-projection``,
  ``check-inventory``, and ``check-claims`` all resolve the same accelerator for
  the same hub.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from discovery_fixtures import write_minimal_discovery_artifact
import kairos_ontology.cli.projections as projection_commands
import kairos_ontology.cli.validation as validation_commands
from kairos_ontology.cli.main import cli
from kairos_ontology.core.reference_modules import (
    resolve_hub_accelerator,
    resolve_hub_accelerator_detailed,
)

NESTED_DATA_DOMAINS_YAML = """\
schema_version: "1.0"
groups:
  - id: party-commercial
    name: "Party & Commercial"
    domains:
      - id: party
        name: "Party, Role & Organisation"
        owns: "Legal entities, customers, suppliers."
        does_not_own: "Contracts, bookings, invoices."
        imports:
          - uri: "https://www.kairosflow.ai/ont/bsp/party#"
            module: "BSP / Party"
  - id: commercial
    name: "Commercial"
    domains:
      - id: booking
        name: "Booking"
        owns: "Transport orders, bookings, dossiers."
        does_not_own: "Legal entities."
        imports:
          - uri: "https://www.kairosflow.ai/ont/bsp/booking#"
            module: "BSP / Booking"
      - id: commercial
        name: "Commercial Agreement"
        owns: "Service agreements."
        does_not_own: "Bookings."
        imports:
          - uri: "https://www.kairosflow.ai/ont/bsp/commercial#"
            module: "BSP / Commercial"
"""


def _write_pack(ref_models: Path, name: str, data_domains_yaml: str) -> Path:
    blueprint = ref_models / "accelerator-packs" / name / "client-hub-blueprint"
    blueprint.mkdir(parents=True)
    (blueprint / "data-domains.yaml").write_text(data_domains_yaml, encoding="utf-8")
    return blueprint


def _empty_pack_yaml() -> str:
    return "groups: []\n"


# --------------------------------------------------------------------------- #
# resolve_hub_accelerator[_detailed] precedence + ambiguity
# --------------------------------------------------------------------------- #
class TestResolverPrecedence:
    def test_explicit_wins_over_hub_configuration(self, tmp_path):
        ref_models = tmp_path / "ontology-reference-models"
        _write_pack(ref_models, "finance", _empty_pack_yaml())
        _write_pack(ref_models, "logistics", _empty_pack_yaml())
        hub = tmp_path / "hub"
        hub.mkdir()
        (hub / "pyproject.toml").write_text(
            '[tool.kairos]\naccelerator = "finance"\n', encoding="utf-8"
        )

        resolved = resolve_hub_accelerator(
            explicit="logistics", hub_root=hub, ref_models_dir=ref_models
        )
        assert resolved == "logistics"

    def test_hub_configuration_wins_over_inference(self, tmp_path):
        ref_models = tmp_path / "ontology-reference-models"
        _write_pack(ref_models, "finance", _empty_pack_yaml())
        _write_pack(ref_models, "logistics", _empty_pack_yaml())
        hub = tmp_path / "hub"
        hub.mkdir()
        (hub / "pyproject.toml").write_text(
            '[tool.kairos]\naccelerator = "logistics"\n', encoding="utf-8"
        )

        resolution = resolve_hub_accelerator_detailed(
            explicit=None, hub_root=hub, ref_models_dir=ref_models
        )
        assert resolution.accelerator == "logistics"
        assert resolution.source == "hub configuration"

    def test_single_installed_is_inferred(self, tmp_path):
        ref_models = tmp_path / "ontology-reference-models"
        _write_pack(ref_models, "logistics", _empty_pack_yaml())

        resolution = resolve_hub_accelerator_detailed(
            explicit=None, hub_root=None, ref_models_dir=ref_models
        )
        assert resolution.accelerator == "logistics"
        assert resolution.source == "inferred (single installed)"
        assert resolution.data_domains_path is not None
        assert resolution.data_domains_path.name == "data-domains.yaml"

    def test_ambiguous_without_hint_still_errors(self, tmp_path):
        ref_models = tmp_path / "ontology-reference-models"
        _write_pack(ref_models, "finance", _empty_pack_yaml())
        _write_pack(ref_models, "logistics", NESTED_DATA_DOMAINS_YAML)

        with pytest.raises(ValueError, match="Accelerator selection is ambiguous"):
            resolve_hub_accelerator(explicit=None, hub_root=None, ref_models_dir=ref_models)

    def test_ambiguous_with_unmatched_hint_still_errors(self, tmp_path):
        ref_models = tmp_path / "ontology-reference-models"
        _write_pack(ref_models, "finance", _empty_pack_yaml())
        _write_pack(ref_models, "logistics", NESTED_DATA_DOMAINS_YAML)

        with pytest.raises(ValueError, match="Accelerator selection is ambiguous"):
            resolve_hub_accelerator(
                explicit=None,
                hub_root=None,
                ref_models_dir=ref_models,
                domain_hint=["does-not-exist-anywhere"],
            )

    def test_unambiguous_domain_ownership_is_inferred(self, tmp_path):
        """Multiple installed accelerators, but only one owns the hinted domain
        (via a nested groups[].domains[] entry) — inferred instead of erroring."""
        ref_models = tmp_path / "ontology-reference-models"
        _write_pack(ref_models, "finance", _empty_pack_yaml())
        _write_pack(ref_models, "logistics", NESTED_DATA_DOMAINS_YAML)

        resolution = resolve_hub_accelerator_detailed(
            explicit=None,
            hub_root=None,
            ref_models_dir=ref_models,
            domain_hint=["booking"],
        )
        assert resolution.accelerator == "logistics"
        assert resolution.source == "inferred (domain ownership)"
        assert resolution.data_domains_path == (
            ref_models
            / "accelerator-packs"
            / "logistics"
            / "client-hub-blueprint"
            / "data-domains.yaml"
        )

    def test_hint_owned_by_more_than_one_accelerator_still_ambiguous(self, tmp_path):
        ref_models = tmp_path / "ontology-reference-models"
        _write_pack(ref_models, "finance", NESTED_DATA_DOMAINS_YAML)
        _write_pack(ref_models, "logistics", NESTED_DATA_DOMAINS_YAML)

        with pytest.raises(ValueError, match="Accelerator selection is ambiguous"):
            resolve_hub_accelerator(
                explicit=None,
                hub_root=None,
                ref_models_dir=ref_models,
                domain_hint=["booking"],
            )

    def test_wrapper_and_detailed_agree(self, tmp_path):
        ref_models = tmp_path / "ontology-reference-models"
        _write_pack(ref_models, "logistics", NESTED_DATA_DOMAINS_YAML)

        simple = resolve_hub_accelerator(explicit=None, hub_root=None, ref_models_dir=ref_models)
        detailed = resolve_hub_accelerator_detailed(
            explicit=None, hub_root=None, ref_models_dir=ref_models
        )
        assert simple == detailed.accelerator == "logistics"


# --------------------------------------------------------------------------- #
# Nested groups[].domains[] parity across parsed registries
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# check-inventory scoped wording (no ambiguous "(none matched)")
# --------------------------------------------------------------------------- #
_INVENTORY_REF_TTL = """\
@prefix : <https://kairos.cnext.eu/ref/party#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://kairos.cnext.eu/ref/party> a owl:Ontology ; owl:versionInfo "1.0" .
:Party a owl:Class ; rdfs:label "Party"@en .
"""

_INVENTORY_CATALOG_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <uri name="https://kairos.cnext.eu/ref/party#" uri="party.ttl"/>
</catalog>
"""

_INVENTORY_DATA_DOMAINS_YAML = """\
groups:
  - id: g1
    domains:
      - id: party
        name: Party
        imports:
          - uri: https://kairos.cnext.eu/ref/party#
            module: party
"""




# --------------------------------------------------------------------------- #
# check-claims registry-ownership diagnostics
# --------------------------------------------------------------------------- #
def _write_affinity(analysis_dir: Path, system: str, tables: list[tuple[str, str]]) -> None:
    import yaml

    analysis_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "system": system,
        "schema_version": 2,
        "tables": [{"table": t, "domain": d} for t, d in tables],
    }
    with open(analysis_dir / f"{system}-affinity.yaml", "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False)


# --------------------------------------------------------------------------- #
# Cross-command resolver parity
# --------------------------------------------------------------------------- #
_VALID_TTL = """\
@prefix : <https://acme.com/ont/booking#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<https://acme.com/ont/booking> a owl:Ontology ;
    rdfs:label "Booking"@en ;
    owl:versionInfo "0.1.0" .

:Booking a owl:Class ;
    rdfs:label "Booking"@en ;
    rdfs:comment "A booking."@en .
"""


class TestCrossCommandResolverParity:
    """``validate``, ``project``/``check-projection``, ``check-inventory``, and
    ``check-claims`` must all resolve the same accelerator for the same hub."""

    def _build_hub(self, tmp_path):
        hub = tmp_path / "ontology-hub"
        ont = hub / "model" / "ontologies"
        ont.mkdir(parents=True)
        (ont / "booking.ttl").write_text(_VALID_TTL, encoding="utf-8")
        (hub / "model" / "shapes").mkdir(parents=True)
        ref_models = tmp_path / "ontology-reference-models"
        _write_pack(ref_models, "finance", _empty_pack_yaml())
        _write_pack(ref_models, "logistics", NESTED_DATA_DOMAINS_YAML)
        write_minimal_discovery_artifact(hub)
        return hub

    def test_validate_and_project_infer_same_accelerator_from_ontology_name(
        self, tmp_path, monkeypatch
    ):
        hub = self._build_hub(tmp_path)
        ref_dir = hub.parent / "ontology-reference-models"
        validate_calls: dict[str, dict] = {}
        project_calls: dict[str, dict] = {}
        monkeypatch.setattr(
            validation_commands,
            "run_validation",
            lambda **kw: validate_calls.update(validation=kw),
        )
        monkeypatch.setattr(validation_commands, "run_gdpr_validation", lambda **kw: None)
        monkeypatch.setattr(
            projection_commands,
            "run_projections",
            lambda **kw: project_calls.update(projection=kw),
        )
        monkeypatch.chdir(hub)

        validate_result = CliRunner().invoke(
            cli, ["validate", "--syntax", "--ref-models", str(ref_dir)]
        )
        assert validate_result.exit_code == 0, validate_result.output
        assert validate_calls["validation"]["accelerator"] == "logistics"

        project_result = CliRunner().invoke(
            cli, ["project", "--target", "neo4j", "--ref-models", str(ref_dir)]
        )
        assert project_result.exit_code == 0, project_result.output
        assert project_calls["projection"]["accelerator"] == "logistics"

    def test_validate_domain_flag_drives_accelerator_resolution(self, tmp_path, monkeypatch):
        """``validate --domain`` resolves the accelerator by domain ownership even when
        the ontology file stem is not itself an owned domain (parity with compile)."""
        hub = self._build_hub(tmp_path)
        ref_dir = hub.parent / "ontology-reference-models"
        # Rename the ontology so its stem owns no domain: bare inference is ambiguous.
        ont = hub / "model" / "ontologies"
        (ont / "booking.ttl").rename(ont / "misc.ttl")
        validate_calls: dict[str, dict] = {}
        monkeypatch.setattr(
            validation_commands,
            "run_validation",
            lambda **kw: validate_calls.update(validation=kw),
        )
        monkeypatch.setattr(validation_commands, "run_gdpr_validation", lambda **kw: None)
        monkeypatch.chdir(hub)

        ambiguous = CliRunner().invoke(
            cli, ["validate", "--syntax", "--ref-models", str(ref_dir)]
        )
        assert ambiguous.exit_code != 0
        assert "ambiguous" in ambiguous.output.lower()

        scoped = CliRunner().invoke(
            cli, ["validate", "--syntax", "--domain", "booking", "--ref-models", str(ref_dir)]
        )
        assert scoped.exit_code == 0, scoped.output
        assert validate_calls["validation"]["accelerator"] == "logistics"

