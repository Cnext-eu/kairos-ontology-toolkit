# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for hub-authored domain ontology catalog wiring."""

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.catalog_utils import sync_domain_catalog_entry


CATALOG_NS = "urn:oasis:names:tc:entity:xmlns:xml:catalog"

_SCAFFOLD_CATALOG_TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "kairos_ontology"
    / "scaffold"
    / "ontology-hub"
    / "catalog-v001.xml.template"
)


def _catalog_root(catalog_path: Path) -> ET.Element:
    return ET.parse(catalog_path).getroot()


def _uri_entries(catalog_path: Path) -> list[ET.Element]:
    return _catalog_root(catalog_path).findall(f"{{{CATALOG_NS}}}uri")


def test_init_registers_created_domain_ontology_iri_in_catalog(tmp_path):
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["init", "--company-domain", "contoso.example", "--domain", "customer"],
            )

            assert result.exit_code == 0, result.output
            catalog = Path("ontology-hub/catalog-v001.xml")
            entries = {entry.get("name"): entry.get("uri") for entry in _uri_entries(catalog)}

    assert entries["https://contoso.example/ont/customer"] == ("model/ontologies/customer.ttl")
    assert "https://contoso.example/ont/customer/" not in entries


def test_sync_domain_catalog_entry_is_idempotent(tmp_path):
    catalog = tmp_path / "catalog-v001.xml"
    ontology = tmp_path / "model" / "ontologies" / "sales.ttl"
    ontology.parent.mkdir(parents=True)
    catalog.write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<catalog xmlns="{CATALOG_NS}">\n</catalog>\n',
        encoding="utf-8",
    )
    ontology.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "<https://contoso.example/ont/sales> a owl:Ontology .\n",
        encoding="utf-8",
    )

    sync_domain_catalog_entry(catalog, ontology)
    sync_domain_catalog_entry(catalog, ontology)

    entries = [
        entry
        for entry in _uri_entries(catalog)
        if entry.get("name") == "https://contoso.example/ont/sales"
    ]
    assert len(entries) == 1
    assert entries[0].get("uri") == "model/ontologies/sales.ttl"


def test_sync_preserves_reference_model_uri_and_next_catalog(tmp_path):
    catalog = tmp_path / "catalog-v001.xml"
    ontology = tmp_path / "model" / "ontologies" / "policy.ttl"
    ontology.parent.mkdir(parents=True)
    catalog.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<catalog xmlns="{CATALOG_NS}">\n'
        '  <uri name="https://spec.example/ref" uri="../reference/ref.ttl"/>\n'
        '  <nextCatalog catalog="../ontology-reference-models/catalog-v001.xml"/>\n'
        "</catalog>\n",
        encoding="utf-8",
    )
    ontology.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "<https://contoso.example/ont/policy> a owl:Ontology .\n",
        encoding="utf-8",
    )

    sync_domain_catalog_entry(catalog, ontology)
    root = _catalog_root(catalog)

    assert root.find(f"{{{CATALOG_NS}}}uri[@name='https://spec.example/ref']") is not None
    assert root.find(f"{{{CATALOG_NS}}}nextCatalog") is not None
    assert root.find(f"{{{CATALOG_NS}}}uri[@name='https://contoso.example/ont/policy']") is not None


# ---------------------------------------------------------------------------
# Regression coverage for issue #327 sub-findings 3 & 4: the textual (non-
# ElementTree-round-tripping) catalog editor.
# ---------------------------------------------------------------------------


def _write_ttl(path: Path, iri: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n" f"<{iri}> a owl:Ontology .\n",
        encoding="utf-8",
    )


def _real_catalog_from_template(
    dest_dir: Path, *, company_domain: str = "contoso.example", company_name: str = "Contoso"
) -> Path:
    """Materialize the real scaffold catalog template byte-for-byte (CRLF intact).

    This mirrors exactly what `init` does when it copies
    ``catalog-v001.xml.template`` -> ``ontology-hub/catalog-v001.xml``, so tests
    exercise the real template shape (prolog comment, marker comment, commented
    example, nextCatalog) rather than a hand-built fixture.
    """
    with open(_SCAFFOLD_CATALOG_TEMPLATE, "r", encoding="utf-8", newline="") as fh:
        content = fh.read()
    content = content.replace("{company_name}", company_name).replace(
        "{company_domain}", company_domain
    )
    catalog = dest_dir / "catalog-v001.xml"
    with open(catalog, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    return catalog


def _read_raw(path: Path) -> str:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _template_eol() -> str:
    """The scaffold template's own line-ending sequence, whatever it is.

    Deliberately NOT hardcoded as "\\r\\n": `core.autocrlf` can make a Windows
    working-tree checkout of this file CRLF while the git-committed blob (and a
    Linux CI checkout) is LF-only. Tests must assert "preserved as-is," not "is
    always CRLF" -- detecting it here keeps the assertions correct on every
    platform instead of only the one they happened to be written on.
    """
    raw = _read_raw(_SCAFFOLD_CATALOG_TEMPLATE)
    return "\r\n" if "\r\n" in raw else "\n"


def test_sync_against_real_template_preserves_everything_but_the_new_entry(tmp_path):
    """Full scaffold round-trip (issue #327 sub-finding 3).

    Registering a domain against the real template must leave the prolog
    comment, blank lines, XML declaration style, and trailing newline
    completely untouched, and land the new <uri> between the "Domain
    ontologies" marker comment and the commented-out example — not after the
    "Chain to shared reference-models catalog" comment (the old bug).
    """
    eol = _template_eol()
    catalog = _real_catalog_from_template(tmp_path)
    ontology = tmp_path / "model" / "ontologies" / "party.ttl"
    _write_ttl(ontology, "https://contoso.example/ont/party")

    sync_domain_catalog_entry(catalog, ontology, company_domain="contoso.example")
    new_content = _read_raw(catalog)

    # Prolog comment preserved verbatim (this is exactly what ElementTree used
    # to drop, since it never re-emits comments preceding the root element).
    assert f"<!--{eol}  Local catalog for Contoso domain ontologies." in new_content
    # Blank lines between comment blocks preserved (ET.indent used to strip these).
    assert f"{eol}{eol}  <!-- ============" in new_content
    # XML declaration untouched: double quotes, uppercase encoding.
    assert new_content.startswith(f'<?xml version="1.0" encoding="UTF-8"?>{eol}')
    assert "encoding='utf-8'" not in new_content
    # Trailing newline preserved.
    assert new_content.endswith(f"</catalog>{eol}")
    # The template's own line-ending convention preserved throughout (never
    # silently normalized to a different style -- this is platform-dependent:
    # on a CRLF checkout every line must stay CRLF; on an LF checkout, LF).
    if eol == "\r\n":
        assert new_content.count("\n") == new_content.count("\r\n")
    else:
        assert "\r\n" not in new_content

    marker_end = new_content.index("add one <uri> per domain")
    marker_close = new_content.index("-->", marker_end)
    example_start = new_content.index('<uri name="https://contoso.example/ont/customer"')
    chain_comment_pos = new_content.index("Chain to shared reference-models catalog")
    new_uri_pos = new_content.index('<uri name="https://contoso.example/ont/party"')

    # New entry lands between the marker comment and the commented-out example —
    # NOT after "Chain to shared reference-models catalog" (the old bug).
    assert marker_close < new_uri_pos < example_start
    assert new_uri_pos < chain_comment_pos


def test_sync_idempotent_against_real_template_marker_comment(tmp_path):
    """Idempotency (issue #327): calling sync twice for the same domain against
    a catalog that HAS the marker comment yields a single entry, with every
    other byte unchanged between the two runs.
    """
    catalog = _real_catalog_from_template(tmp_path)
    ontology = tmp_path / "model" / "ontologies" / "party.ttl"
    _write_ttl(ontology, "https://contoso.example/ont/party")

    sync_domain_catalog_entry(catalog, ontology, company_domain="contoso.example")
    after_first = _read_raw(catalog)

    sync_domain_catalog_entry(catalog, ontology, company_domain="contoso.example")
    after_second = _read_raw(catalog)

    assert after_first == after_second
    assert after_second.count('name="https://contoso.example/ont/party"') == 1


def test_sync_multi_domain_both_entries_placed_correctly(tmp_path):
    """Registering two different domains must place both entries correctly,
    leaving the prolog, commented example, and nextCatalog untouched.
    """
    catalog = _real_catalog_from_template(tmp_path)
    party = tmp_path / "model" / "ontologies" / "party.ttl"
    sales = tmp_path / "model" / "ontologies" / "sales.ttl"
    _write_ttl(party, "https://contoso.example/ont/party")
    _write_ttl(sales, "https://contoso.example/ont/sales")

    sync_domain_catalog_entry(catalog, party, company_domain="contoso.example")
    sync_domain_catalog_entry(catalog, sales, company_domain="contoso.example")
    content = _read_raw(catalog)

    marker_end = content.index("add one <uri> per domain")
    marker_close = content.index("-->", marker_end)
    example_start = content.index('<uri name="https://contoso.example/ont/customer"')
    chain_comment_pos = content.index("Chain to shared reference-models catalog")
    # NOTE: the prolog's own prose mentions "<nextCatalog>" descriptively, so
    # search for the live element's opening attribute, not just the tag name.
    next_catalog_pos = content.index("<nextCatalog catalog=")

    party_pos = content.index('<uri name="https://contoso.example/ont/party"')
    sales_pos = content.index('<uri name="https://contoso.example/ont/sales"')

    for pos in (party_pos, sales_pos):
        assert marker_close < pos < example_start
        assert pos < chain_comment_pos < next_catalog_pos

    # Prolog / commented example / nextCatalog untouched.
    assert "Local catalog for Contoso domain ontologies." in content
    eol = _template_eol()
    assert (
        f'<uri name="https://contoso.example/ont/customer"{eol}'
        '       uri="model/ontologies/customer.ttl"/>' in content
    )
    assert "<nextCatalog" in content


def test_sync_raises_on_namespace_prefixed_catalog_dialect(tmp_path):
    """A namespace-prefixed dialect (<c:uri> with xmlns:c=...) must raise, not
    be silently (and incorrectly) edited by a regex written for bare <uri>.
    """
    catalog = tmp_path / "catalog-v001.xml"
    ontology = tmp_path / "model" / "ontologies" / "party.ttl"
    _write_ttl(ontology, "https://contoso.example/ont/party")
    catalog.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<c:catalog xmlns:c="{CATALOG_NS}">\n'
        '  <c:uri name="https://spec.example/ref" uri="../reference/ref.ttl"/>\n'
        "</c:catalog>\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="namespace-prefixed"):
        sync_domain_catalog_entry(catalog, ontology, company_domain="contoso.example")


def test_template_commented_example_has_no_trailing_slash():
    """Golden-file check (issue #327 sub-finding 4).

    The commented-out example must match what `init` actually registers:
    `_declared_ontology_iri` strips the trailing slash, so `init --domain
    customer` maps `https://<company_domain>/ont/customer` — not the old
    `.../customer/` shape the example used to show.
    """
    content = _read_raw(_SCAFFOLD_CATALOG_TEMPLATE)
    assert 'name="https://{company_domain}/ont/customer"' in content
    assert 'name="https://{company_domain}/ont/customer/"' not in content
