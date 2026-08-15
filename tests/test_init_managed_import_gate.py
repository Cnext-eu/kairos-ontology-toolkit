# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""`init --domain` refuses import-incomplete PRE-EXISTING domains (#426, DD-155).

The registration gate mirrors the validator's Managed Import Completeness
semantics but is scoped: it fires only for a domain TTL that pre-existed the
`init` run, on a hub whose reference models are resolvable. A TTL that `init`
itself just scaffolded is never gated (the starter template carries no
owl:imports by design), an ambiguous accelerator warns and skips the gate, and
`--degraded` is the only (explicit) bypass — identical in fleet mode (DD-088).
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from kairos_ontology.cli.main import cli

MODULE_IRI = "https://example.org/reference/orders"
TERM_NS = MODULE_IRI + "#"
COMPANY = "example.test"
DOMAIN = "orders"
DOMAIN_IRI = f"https://{COMPANY}/ont/{DOMAIN}"

_INIT_BOOTSTRAP = ["init", "--company-domain", COMPANY, "--skip-refmodels"]
_INIT_REGISTER = [
    "init",
    "--domain",
    DOMAIN,
    "--company-domain",
    COMPANY,
    "--skip-refmodels",
]


def _bootstrap_hub(runner: CliRunner) -> None:
    result = runner.invoke(cli, _INIT_BOOTSTRAP)
    assert result.exit_code == 0, result.output


def _install_refmodels(root: Path) -> Path:
    """A minimal-but-real reference-models checkout at the repo root.

    Satisfies `_looks_like_refmodels_root` (catalog + blueprints/archetypes/) and
    activates the `orders` domain with one required managed module, mirroring the
    pack shape used in tests/test_reference_modules.py.
    """
    ref_models = root / "ontology-reference-models"
    (ref_models / "blueprints" / "archetypes").mkdir(parents=True)
    module = ref_models / "modules" / "orders.ttl"
    module.parent.mkdir(parents=True)
    module.write_text(
        f"""\
@prefix ex: <{TERM_NS}> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<{MODULE_IRI}> a owl:Ontology ; owl:versionInfo "2.1.0" .
ex:Order a owl:Class .
""",
        encoding="utf-8",
    )
    blueprint = ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint"
    blueprint.mkdir(parents=True)
    (blueprint / "data-domains.yaml").write_text(
        f"""\
schema_version: "2.0"
module_profiles:
  - id: orders
    ontology_iri: {MODULE_IRI}
    catalog_uri: {TERM_NS}
    version_pin: 2.1.0
    term_namespaces: [{TERM_NS}]
groups:
  - id: operations
    domains:
      - id: {DOMAIN}
        imports:
          - profile: orders
""",
        encoding="utf-8",
    )
    (ref_models / "catalog-v001.xml").write_text(
        f"""\
<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <uri name="{TERM_NS}" uri="modules/orders.ttl"/>
  <uri name="{MODULE_IRI}" uri="modules/orders.ttl"/>
</catalog>
""",
        encoding="utf-8",
    )
    return ref_models


def _install_second_pack_owning_orders(ref_models: Path) -> None:
    """A second accelerator pack that also owns `orders` → genuine ambiguity."""
    blueprint = ref_models / "accelerator-packs" / "other" / "client-hub-blueprint"
    blueprint.mkdir(parents=True)
    (blueprint / "data-domains.yaml").write_text(
        f"""\
schema_version: "2.0"
module_profiles: []
groups:
  - id: operations
    domains:
      - id: {DOMAIN}
        imports: []
""",
        encoding="utf-8",
    )


def _write_domain_ttl(*, imports_module: bool) -> None:
    import_line = f"    owl:imports <{MODULE_IRI}> ;\n" if imports_module else ""
    Path("ontology-hub/model/ontologies", f"{DOMAIN}.ttl").write_text(
        f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<{DOMAIN_IRI}> a owl:Ontology ;
{import_line}    rdfs:label "Orders"@en ;
    rdfs:comment "Pre-existing authored domain for the registration gate."@en ;
    owl:versionInfo "0.1.0" .
""",
        encoding="utf-8",
    )


def _catalog_text() -> str:
    return Path("ontology-hub/catalog-v001.xml").read_text(encoding="utf-8")


def _master_text() -> str:
    return Path("ontology-hub/model/ontologies/_master.ttl").read_text(encoding="utf-8")


def test_refuses_preexisting_import_incomplete_domain(tmp_path):
    """(a) Missing required managed import → exit 1, catalog and _master untouched."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            _bootstrap_hub(runner)
            _install_refmodels(Path(td))
            _write_domain_ttl(imports_module=False)

            result = runner.invoke(cli, _INIT_REGISTER)

            assert result.exit_code == 1, result.output
            assert "❌" in result.output
            assert "registration refused" in result.output
            assert f"{DOMAIN}.ttl" not in _catalog_text()
            assert DOMAIN_IRI not in _master_text()


def test_degraded_registers_import_incomplete_domain_with_warning(tmp_path):
    """(b) --degraded is the explicit bypass: warnings, registration proceeds."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            _bootstrap_hub(runner)
            _install_refmodels(Path(td))
            _write_domain_ttl(imports_module=False)

            result = runner.invoke(cli, _INIT_REGISTER + ["--degraded"])

            assert result.exit_code == 0, result.output
            assert "registration refused" not in result.output
            assert "⚠" in result.output
            assert "registration proceeds" in result.output
            assert f"{DOMAIN}.ttl" in _catalog_text()
            assert DOMAIN_IRI in _master_text()


def test_registers_preexisting_domain_with_complete_imports(tmp_path):
    """A pre-existing domain that authored its required import passes the gate."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            _bootstrap_hub(runner)
            _install_refmodels(Path(td))
            _write_domain_ttl(imports_module=True)

            result = runner.invoke(cli, _INIT_REGISTER)

            assert result.exit_code == 0, result.output
            assert "registration refused" not in result.output
            assert f"{DOMAIN}.ttl" in _catalog_text()


def test_fresh_scaffold_is_never_gated(tmp_path):
    """(c) A TTL init itself scaffolds registers ungated — advisory only.

    The starter template has no owl:imports; gating it would refuse init's own
    output on every refmodels-present hub (the (B) blocking finding in DD-155).
    """
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            _bootstrap_hub(runner)
            _install_refmodels(Path(td))
            # Deliberately NOT writing the domain TTL: init scaffolds the starter.

            result = runner.invoke(cli, _INIT_REGISTER)

            assert result.exit_code == 0, result.output
            assert "registration refused" not in result.output
            assert "without the managed-import gate" in result.output
            assert f"{DOMAIN}.ttl" in _catalog_text()


def test_skip_refmodels_without_refmodels_present_is_ungated(tmp_path):
    """(d) No reference models on disk → no gate, no crash (vacuous pass)."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _bootstrap_hub(runner)
            _write_domain_ttl(imports_module=False)

            result = runner.invoke(cli, _INIT_REGISTER)

            assert result.exit_code == 0, result.output
            assert "registration refused" not in result.output
            assert f"{DOMAIN}.ttl" in _catalog_text()


def test_ambiguous_accelerator_warns_and_skips_the_gate(tmp_path):
    """(e) Two packs own the domain → the gate must not guess: warn + register."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            _bootstrap_hub(runner)
            ref_models = _install_refmodels(Path(td))
            _install_second_pack_owning_orders(ref_models)
            _write_domain_ttl(imports_module=False)

            result = runner.invoke(cli, _INIT_REGISTER)

            assert result.exit_code == 0, result.output
            assert "gate skipped" in result.output
            assert "--accelerator <pack>" in result.output
            assert f"{DOMAIN}.ttl" in _catalog_text()
