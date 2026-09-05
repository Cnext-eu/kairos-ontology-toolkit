# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the `scaffold-domain` CLI command (issue #469, todo E5-scaffold-domain)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from kairos_ontology.cli.main import cli

COMPANY = "contoso.com"
DOMAIN_IRI = f"https://{COMPANY}/ont/customer"


def _make_minimal_hub(root: Path, company_domain: str = COMPANY) -> Path:
    """Create a minimal but valid hub structure under ``root/ontology-hub/``.

    The hub needs:
    - model/ontologies/ directory
    - catalog-v001.xml with the company domain pattern
    - model/ontologies/_master.ttl with the master ontology declaration
    """
    hub = root / "ontology-hub"
    ont_dir = hub / "model" / "ontologies"
    ont_dir.mkdir(parents=True, exist_ok=True)

    # _master.ttl
    master_path = ont_dir / "_master.ttl"
    master_path.write_text(
        f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<https://{company_domain}/ont/master> a owl:Ontology ;
    rdfs:label "Contoso Master Ontology"@en ;
    rdfs:comment "Unified ontology that imports all domain ontologies"@en ;
    owl:versionInfo "0.1.0" .

## -- Add owl:imports for each domain ontology below --
""",
        encoding="utf-8",
    )

    # catalog-v001.xml
    catalog_path = hub / "catalog-v001.xml"
    catalog_path.write_text(
        """\
<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">

  <!-- ============================================================
       Domain ontologies — add one <uri> per domain
       ============================================================ -->

</catalog>
""",
        encoding="utf-8",
    )

    return hub


def _make_refmodels(root: Path, accelerator: str = "logistics") -> Path:
    """Create a minimal reference-models directory with a data-domains.yaml."""
    ref = root / "ontology-reference-models"
    bp_dir = ref / "accelerator-packs" / accelerator / "client-hub-blueprint"
    bp_dir.mkdir(parents=True, exist_ok=True)

    module_iri = "https://example.org/modules/orders"
    (bp_dir / "data-domains.yaml").write_text(
        f"""\
schema_version: "2.0"
groups:
  - id: operations
    domains:
      - id: customer
        name: Customer
        imports:
          - uri: {module_iri}
            module: orders
            profile: orders
            module_id: orders
      - id: inventory
        name: Inventory
        imports: []
""",
        encoding="utf-8",
    )
    return ref


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_scaffold_domain_happy_path(tmp_path):
    """Scaffold a domain in a minimal hub — verify .ttl creation and content."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."))

        result = runner.invoke(cli, ["scaffold-domain", "--domain", "customer"])
        assert result.exit_code == 0, result.output

        ttl_path = Path("ontology-hub/model/ontologies/customer.ttl")
        assert ttl_path.is_file()

        content = ttl_path.read_text(encoding="utf-8")
        assert "@prefix : <https://contoso.com/ont/customer#>" in content
        assert "@prefix owl: <http://www.w3.org/2002/07/owl#>" in content
        assert "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>" in content
        assert "@prefix xsd: <http://www.w3.org/2001/XMLSchema#>" in content
        assert "a owl:Ontology" in content
        assert "owl:versionInfo" in content
        assert f"<https://{COMPANY}/ont/customer> a owl:Ontology" in content
        assert "Customer" in content  # title-cased label


def test_scaffold_domain_refuse_overwrite(tmp_path):
    """Pre-create the .ttl — command refuses without --force."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."))

        # Pre-create the target file.
        ttl_path = Path("ontology-hub/model/ontologies/customer.ttl")
        ttl_path.write_text("# pre-existing content\n", encoding="utf-8")

        result = runner.invoke(cli, ["scaffold-domain", "--domain", "customer"])
        assert result.exit_code != 0, result.output
        assert "already exists" in result.output

        # File must be untouched.
        assert ttl_path.read_text(encoding="utf-8") == "# pre-existing content\n"


def test_scaffold_domain_force_overwrite(tmp_path):
    """Pre-create the .ttl — --force overwrites it."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."))

        ttl_path = Path("ontology-hub/model/ontologies/customer.ttl")
        ttl_path.write_text("# pre-existing content\n", encoding="utf-8")

        result = runner.invoke(cli, ["scaffold-domain", "--domain", "customer", "--force"])
        assert result.exit_code == 0, result.output

        content = ttl_path.read_text(encoding="utf-8")
        assert "owl:Ontology" in content
        assert "# pre-existing content" not in content


def test_scaffold_domain_catalog_registration(tmp_path):
    """Verify the domain is registered in catalog-v001.xml."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."))

        result = runner.invoke(cli, ["scaffold-domain", "--domain", "customer"])
        assert result.exit_code == 0, result.output

        cat_content = Path("ontology-hub/catalog-v001.xml").read_text(encoding="utf-8")
        assert DOMAIN_IRI in cat_content
        assert "model/ontologies/customer.ttl" in cat_content


def test_scaffold_domain_master_import_sync(tmp_path):
    """Verify owl:imports is added to _master.ttl."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."))

        result = runner.invoke(cli, ["scaffold-domain", "--domain", "customer"])
        assert result.exit_code == 0, result.output

        master_content = Path("ontology-hub/model/ontologies/_master.ttl").read_text(
            encoding="utf-8"
        )
        assert f"owl:imports <{DOMAIN_IRI}>" in master_content


def test_scaffold_domain_company_domain_extraction(tmp_path):
    """Verify company domain is correctly extracted from existing hub files."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."), company_domain="mycompany.io")

        result = runner.invoke(cli, ["scaffold-domain", "--domain", "order"])
        assert result.exit_code == 0, result.output

        content = Path("ontology-hub/model/ontologies/order.ttl").read_text(encoding="utf-8")
        assert "https://mycompany.io/ont/order" in content
        assert "https://mycompany.io/ont/order#" in content


def test_scaffold_domain_company_domain_from_catalog(tmp_path):
    """Verify company domain falls back to catalog-v001.xml when no .ttl has it."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        hub = Path("ontology-hub")
        ont_dir = hub / "model" / "ontologies"
        ont_dir.mkdir(parents=True, exist_ok=True)

        # _master.ttl with no company-domain URI pattern in it.
        (ont_dir / "_master.ttl").write_text(
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "<https://example.org/master> a owl:Ontology ;\n"
            '    rdfs:label "Master"@en ;\n'
            '    owl:versionInfo "0.1.0" .\n',
            encoding="utf-8",
        )

        # catalog-v001.xml has the pattern.
        (hub / "catalog-v001.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <uri name="https://acme.corp/ont/existing"\n'
            '       uri="model/ontologies/existing.ttl"/>\n'
            "</catalog>\n",
            encoding="utf-8",
        )

        result = runner.invoke(cli, ["scaffold-domain", "--domain", "product"])
        assert result.exit_code == 0, result.output

        content = Path("ontology-hub/model/ontologies/product.ttl").read_text(encoding="utf-8")
        assert "https://acme.corp/ont/product" in content


def test_scaffold_domain_invalid_name_slugified(tmp_path):
    """Verify invalid characters are slugified from the domain name."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."))

        result = runner.invoke(cli, ["scaffold-domain", "--domain", "Customer Orders!"])
        assert result.exit_code == 0, result.output

        assert Path("ontology-hub/model/ontologies/customer-orders.ttl").is_file()


def test_scaffold_domain_custom_label(tmp_path):
    """Verify a custom --label is used in the ontology."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."))

        result = runner.invoke(
            cli, ["scaffold-domain", "--domain", "customer", "--label", "VIP Customer"]
        )
        assert result.exit_code == 0, result.output

        content = Path("ontology-hub/model/ontologies/customer.ttl").read_text(encoding="utf-8")
        assert "VIP Customer" in content


def test_scaffold_domain_no_hub(tmp_path):
    """Command fails when not inside a hub."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["scaffold-domain", "--domain", "customer"])
        assert result.exit_code != 0
        assert "Could not detect an ontology-hub" in result.output


def test_scaffold_domain_from_blueprint_with_imports(tmp_path, monkeypatch):
    """Verify --from-blueprint reads data-domains.yaml and injects owl:imports."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."))
        ref = _make_refmodels(Path("."))
        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref))

        result = runner.invoke(
            cli,
            ["scaffold-domain", "--domain", "customer", "--from-blueprint", "logistics"],
        )
        assert result.exit_code == 0, result.output

        content = Path("ontology-hub/model/ontologies/customer.ttl").read_text(encoding="utf-8")
        assert "owl:imports <https://example.org/modules/orders>" in content
        assert "Mandated imports" in content


def test_scaffold_domain_from_blueprint_domain_not_found(tmp_path, monkeypatch):
    """Verify error when the domain is not in the blueprint."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."))
        ref = _make_refmodels(Path("."))
        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref))

        result = runner.invoke(
            cli,
            ["scaffold-domain", "--domain", "shipping", "--from-blueprint", "logistics"],
        )
        assert result.exit_code != 0
        assert "not found in data-domains.yaml" in result.output


def test_scaffold_domain_from_blueprint_no_imports(tmp_path, monkeypatch):
    """A domain with empty imports in the blueprint produces a bare starter."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."))
        ref = _make_refmodels(Path("."))
        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref))

        result = runner.invoke(
            cli,
            ["scaffold-domain", "--domain", "inventory", "--from-blueprint", "logistics"],
        )
        assert result.exit_code == 0, result.output

        content = Path("ontology-hub/model/ontologies/inventory.ttl").read_text(
            encoding="utf-8"
        )
        assert "owl:imports" not in content or "##" in content
        # The starter comment should mention importing the foundation ontology.
        assert "## -- Domain classes below" in content


def test_scaffold_domain_idempotent_master_sync(tmp_path):
    """Running twice on the same domain (with --force) should not duplicate imports."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."))

        result1 = runner.invoke(cli, ["scaffold-domain", "--domain", "customer"])
        assert result1.exit_code == 0, result1.output

        result2 = runner.invoke(
            cli, ["scaffold-domain", "--domain", "customer", "--force"]
        )
        assert result2.exit_code == 0, result2.output
        assert "already imports" in result2.output

        master_content = Path("ontology-hub/model/ontologies/_master.ttl").read_text(
            encoding="utf-8"
        )
        # Exactly one import line for the domain.
        count = master_content.count(f"owl:imports <{DOMAIN_IRI}>")
        assert count == 1


# ---------------------------------------------------------------------------
# --ai flag tests (issue #470, todo E6-ai-flag)
# ---------------------------------------------------------------------------

_AI_TTL_RESPONSE = """\
@prefix : <https://contoso.com/ont/customer#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://contoso.com/ont/customer> a owl:Ontology ;
    rdfs:label "Customer"@en ;
    rdfs:comment "AI-generated ontology for the Customer domain"@en ;
    owl:versionInfo "0.1.0" .

:Customer a owl:Class ;
    rdfs:label "Customer"@en ;
    rdfs:comment "A customer of the organisation."@en .

:customerName a owl:DatatypeProperty ;
    rdfs:label "customer name"@en ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string .
"""

_AI_GARBAGE_RESPONSE = "This is not valid Turtle at all!!! {{{{ broken }}}} >>>"


def _patch_ai_response(content: str, *, raise_exc: Exception | None = None):
    """Build a mock context-manager stack patching the AI path with *content*.

    When *raise_exc* is given, the client raises it instead of returning content.
    """
    from contextlib import ExitStack

    stack = ExitStack()

    # Patch require_ai_provider → returns a fake config object with .model
    config = mock.MagicMock()
    config.model = "test-model"
    stack.enter_context(
        mock.patch(
            "kairos_ontology.core.ai_preflight.require_ai_provider",
            return_value=config,
        )
    )

    # Patch get_ai_client → returns a mock client
    client = mock.MagicMock()
    if raise_exc is not None:
        client.chat.completions.create.side_effect = raise_exc
    else:
        client.chat.completions.create.return_value = mock.MagicMock(
            choices=[mock.MagicMock(message=mock.MagicMock(content=content))]
        )
    stack.enter_context(
        mock.patch(
            "kairos_ontology.core.ai_provider.get_ai_client",
            return_value=client,
        )
    )

    return stack


def _patch_ai_not_configured():
    """Patch require_ai_provider to raise NotConfigured."""
    from contextlib import ExitStack
    from kairos_ontology.core.ai_provider import NotConfigured

    stack = ExitStack()
    stack.enter_context(
        mock.patch(
            "kairos_ontology.core.ai_preflight.require_ai_provider",
            side_effect=NotConfigured("No AI provider configured."),
        )
    )
    return stack


def test_scaffold_domain_ai_generates_content(tmp_path):
    """--ai with a valid AI response writes AI-generated TTL containing class/property stubs."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."))

        with _patch_ai_response(_AI_TTL_RESPONSE):
            result = runner.invoke(cli, ["scaffold-domain", "--domain", "customer", "--ai"])
        assert result.exit_code == 0, result.output

        ttl_path = Path("ontology-hub/model/ontologies/customer.ttl")
        assert ttl_path.is_file()

        content = ttl_path.read_text(encoding="utf-8")
        # AI-generated class and property should be present.
        assert ":Customer a owl:Class" in content
        assert ":customerName a owl:DatatypeProperty" in content
        assert "AI-generated" in content
        # Should NOT fall back to the bare template.
        assert "## -- Domain classes below" not in content


def test_scaffold_domain_ai_falls_back_on_invalid_ttl(tmp_path):
    """--ai with an invalid TTL response falls back to the bare starter template with a warning."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."))

        with _patch_ai_response(_AI_GARBAGE_RESPONSE):
            result = runner.invoke(cli, ["scaffold-domain", "--domain", "customer", "--ai"])
        assert result.exit_code == 0, result.output

        ttl_path = Path("ontology-hub/model/ontologies/customer.ttl")
        assert ttl_path.is_file()

        content = ttl_path.read_text(encoding="utf-8")
        # Falls back to the bare template.
        assert "a owl:Ontology" in content
        assert "owl:versionInfo" in content
        assert "## -- Domain classes below" in content
        # Should have a warning about the fallback.
        assert "Falling back" in result.output or "failed Turtle parsing" in result.output


def test_scaffold_domain_ai_falls_back_on_ai_error(tmp_path):
    """--ai when the AI provider call raises an exception falls back to the bare template."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."))

        with _patch_ai_response("", raise_exc=RuntimeError("provider outage")):
            result = runner.invoke(cli, ["scaffold-domain", "--domain", "customer", "--ai"])
        assert result.exit_code == 0, result.output

        ttl_path = Path("ontology-hub/model/ontologies/customer.ttl")
        assert ttl_path.is_file()

        content = ttl_path.read_text(encoding="utf-8")
        # Falls back to the bare template.
        assert "a owl:Ontology" in content
        assert "owl:versionInfo" in content
        assert "## -- Domain classes below" in content
        assert "Falling back" in result.output or "AI provider call failed" in result.output


def test_scaffold_domain_ai_without_config_errors(tmp_path):
    """--ai when no AI config is present exits with an error."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."))

        with _patch_ai_not_configured():
            result = runner.invoke(cli, ["scaffold-domain", "--domain", "customer", "--ai"])
        assert result.exit_code != 0, result.output
        assert "AI provider" in result.output or "not configured" in result.output

        # No file should have been written.
        assert not Path("ontology-hub/model/ontologies/customer.ttl").exists()


def _make_refmodels_with_boundary(root: Path, accelerator: str = "logistics") -> Path:
    """Reference models whose blueprint declares ownership boundaries and a bridge."""
    ref = root / "ontology-reference-models"
    bp_dir = ref / "accelerator-packs" / accelerator / "client-hub-blueprint"
    bp_dir.mkdir(parents=True, exist_ok=True)
    (bp_dir / "data-domains.yaml").write_text(
        """\
schema_version: "2.0"
groups:
  - id: operations
    domains:
      - id: party
        name: Party
        owns: "Legal entities, customers, suppliers, contacts, and roles."
        does_not_own: "Contracts, bookings, invoices, or operational events."
        imports: []
cross_domain_relationships:
  - id: party-to-booking
    source_domain: party
    target_domain: booking
    property_uri: "https://example.org/ont#participatesInBooking"
    description: "Links a Party to the Booking it participates in."
""",
        encoding="utf-8",
    )
    return ref


def test_scaffold_domain_writes_blueprint_boundary_into_the_header(tmp_path, monkeypatch):
    """DD-163: the boundary must land in the artifact the author actually edits.

    Previously only ``imports[].uri`` was copied, so the domain file never stated what
    it owns -- and a full run produced eight domains declaring ``Booking``.
    """
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."))
        ref = _make_refmodels_with_boundary(Path("."))
        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref))

        result = runner.invoke(
            cli, ["scaffold-domain", "--domain", "party", "--from-blueprint", "logistics"]
        )
        assert result.exit_code == 0, result.output

        content = Path("ontology-hub/model/ontologies/party.ttl").read_text(encoding="utf-8")
        assert "OWNS (accelerator blueprint):" in content
        assert "Legal entities, customers, suppliers" in content
        # Heading text is parsed by core/ontology_integrity.py.
        assert "Deliberate exclusions (with reasons):" in content
        assert "Contracts, bookings, invoices" in content
        # The declared bridge is named so "reference it, don't re-mint it" has a target.
        assert "participatesInBooking" in content
        assert "booking" in content


def test_scaffolded_header_is_readable_by_the_integrity_checker(tmp_path, monkeypatch):
    """The scaffold and the validator must agree on the header contract."""
    from kairos_ontology.core.ontology_integrity import audit_ontology_integrity

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_minimal_hub(Path("."))
        ref = _make_refmodels_with_boundary(Path("."))
        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(ref))
        runner.invoke(
            cli, ["scaffold-domain", "--domain", "party", "--from-blueprint", "logistics"]
        )

        ontologies = Path("ontology-hub/model/ontologies")
        clean = audit_ontology_integrity(ontologies_dir=ontologies, data_domains={})
        assert clean.is_blocking is False, "a freshly scaffolded domain must validate"

        path = ontologies / "party.ttl"
        path.write_text(
            path.read_text(encoding="utf-8")
            + '\n:Booking a owl:Class ;\n    rdfs:label "Booking"@en ;\n'
            '    rdfs:comment "A booking."@en .\n',
            encoding="utf-8",
        )
        blocked = audit_ontology_integrity(
            ontologies_dir=ontologies,
            data_domains={"party": {"does_not_own": "Contracts, bookings, invoices."}},
        )
        assert blocked.is_blocking
        assert any(
            d.code == "integrity.class-outside-blueprint-boundary" for d in blocked.errors
        )
