# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for `kairos-ontology catalog-test` (issue #289).

Covers the failure modes the command must detect on a real hub catalog:

- Dangling `<uri>` entries DECLARED IN THE CATALOG UNDER TEST — these fail the
  command, because the hub author owns that file and can fix it.
- Dangling entries declared in a *chained* catalog (reached via `<nextCatalog>`,
  e.g. the vendored `ontology-reference-models` catalog every hub chains to) —
  these only warn, since the hub author cannot edit that file.
- Unmapped domain ontologies (`model/ontologies/*.ttl` with no catalog entry) —
  advisory only, since nothing but `init --domain` ever registers a domain.
- A malformed/unparseable catalog — fails cleanly, no traceback.
- Absolute-URI `uri=` targets — informational, never reported as dangling.

Also covers the advisory `<nextCatalog>`/cycle warnings and the exclusion of
commented-out example entries and of `_`-prefixed files (e.g. `_master.ttl`).
"""

from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from kairos_ontology.cli.main import cli

# Aliased on import: a bare `test_catalog_resolution` name would make pytest collect
# the imported function itself as a test case in this module.
from kairos_ontology.core.catalog_test import test_catalog_resolution as run_catalog_test


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _catalog(hub: Path, body: str) -> Path:
    return _write(
        hub / "catalog-v001.xml",
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
        f"{body}\n"
        "</catalog>\n",
    )


class TestCleanCatalog:
    def test_clean_catalog_passes(self, tmp_path, capsys):
        hub = tmp_path
        _write(hub / "model" / "ontologies" / "client.ttl", "# client\n")
        catalog = _catalog(
            hub,
            '<uri name="https://example.com/ont/client" uri="model/ontologies/client.ttl"/>',
        )

        passed = run_catalog_test(catalog)

        assert passed is True
        out = capsys.readouterr().out
        assert "resolve" in out
        assert "are mapped in the catalog" in out
        assert "✅ Catalog test completed" in out

    def test_clean_catalog_cli_exits_zero(self, tmp_path):
        hub = tmp_path
        _write(hub / "model" / "ontologies" / "client.ttl", "# client\n")
        catalog = _catalog(
            hub,
            '<uri name="https://example.com/ont/client" uri="model/ontologies/client.ttl"/>',
        )

        result = CliRunner().invoke(cli, ["catalog-test", "--catalog", str(catalog)])

        assert result.exit_code == 0


class TestDanglingEntry:
    def test_dangling_entry_in_own_catalog_fails_and_is_named(self, tmp_path, capsys):
        hub = tmp_path
        # No file created at model/ontologies/logistics.ttl.
        catalog = _catalog(
            hub,
            '<uri name="https://example.com/ont/logistics" uri="model/ontologies/logistics.ttl"/>',
        )

        passed = run_catalog_test(catalog)

        assert passed is False
        out = capsys.readouterr().out
        assert "dangling" in out.lower()
        assert "https://example.com/ont/logistics" in out
        assert "logistics.ttl" in out
        assert catalog.name in out  # the catalog under test is named as the owner
        assert "❌ Catalog test failed" in out

    def test_dangling_entry_in_own_catalog_cli_exits_nonzero(self, tmp_path):
        hub = tmp_path
        catalog = _catalog(
            hub,
            '<uri name="https://example.com/ont/logistics" uri="model/ontologies/logistics.ttl"/>',
        )

        result = CliRunner().invoke(cli, ["catalog-test", "--catalog", str(catalog)])

        assert result.exit_code != 0


class TestChainedCatalogDanglingEntry:
    """A dangling entry declared in a *chained* catalog (e.g. the vendored
    ontology-reference-models catalog reached via <nextCatalog>) must only warn —
    the hub author does not own that file and cannot fix it (review finding #1).
    """

    def test_dangling_entry_in_chained_catalog_only_warns_and_names_owner(self, tmp_path, capsys):
        hub = tmp_path
        _write(hub / "model" / "ontologies" / "client.ttl", "# client\n")
        chained_catalog = _write(
            hub / "ontology-reference-models" / "catalog-v001.xml",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            # No file exists at fibo/master.rdf — dangling, but owned upstream.
            '<uri name="https://spec.edmcouncil.org/fibo/master" uri="fibo/master.rdf"/>\n'
            "</catalog>\n",
        )
        catalog = _catalog(
            hub,
            '<uri name="https://example.com/ont/client" uri="model/ontologies/client.ttl"/>\n'
            '<nextCatalog catalog="ontology-reference-models/catalog-v001.xml"/>',
        )

        passed = run_catalog_test(catalog)

        assert passed is True
        out = capsys.readouterr().out
        assert "⚠️" in out
        assert "https://spec.edmcouncil.org/fibo/master" in out
        assert str(chained_catalog.resolve()) in out
        assert "❌" not in out
        assert "✅ Catalog test completed" in out

    def test_dangling_entry_in_chained_catalog_cli_exits_zero(self, tmp_path):
        hub = tmp_path
        _write(hub / "model" / "ontologies" / "client.ttl", "# client\n")
        _write(
            hub / "ontology-reference-models" / "catalog-v001.xml",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '<uri name="https://spec.edmcouncil.org/fibo/master" uri="fibo/master.rdf"/>\n'
            "</catalog>\n",
        )
        catalog = _catalog(
            hub,
            '<uri name="https://example.com/ont/client" uri="model/ontologies/client.ttl"/>\n'
            '<nextCatalog catalog="ontology-reference-models/catalog-v001.xml"/>',
        )

        result = CliRunner().invoke(cli, ["catalog-test", "--catalog", str(catalog)])

        assert result.exit_code == 0


class TestUnmappedDomain:
    """Unmapped domains are advisory-only (review finding #2): nothing but
    `init --domain` registers a domain, so a hub grown via the design-discovery
    skill legitimately has unmapped domains with no automated remedy.
    """

    def test_unmapped_domain_warns_and_is_named_but_does_not_fail(self, tmp_path, capsys):
        hub = tmp_path
        _write(hub / "model" / "ontologies" / "client.ttl", "# client\n")
        _write(hub / "model" / "ontologies" / "invoice.ttl", "# invoice\n")
        # Only "client" is mapped; "invoice" is not.
        catalog = _catalog(
            hub,
            '<uri name="https://example.com/ont/client" uri="model/ontologies/client.ttl"/>',
        )

        passed = run_catalog_test(catalog)

        assert passed is True
        out = capsys.readouterr().out
        assert "not mapped" in out.lower()
        assert "invoice.ttl" in out
        assert "client.ttl" not in out.split("not mapped")[1]
        assert "⚠️" in out
        assert "❌" not in out

    def test_unmapped_domain_cli_exits_zero(self, tmp_path):
        hub = tmp_path
        _write(hub / "model" / "ontologies" / "client.ttl", "# client\n")
        _write(hub / "model" / "ontologies" / "invoice.ttl", "# invoice\n")
        catalog = _catalog(
            hub,
            '<uri name="https://example.com/ont/client" uri="model/ontologies/client.ttl"/>',
        )

        result = CliRunner().invoke(cli, ["catalog-test", "--catalog", str(catalog)])

        assert result.exit_code == 0

    def test_underscore_prefixed_files_are_not_reported_as_unmapped(self, tmp_path, capsys):
        hub = tmp_path
        _write(hub / "model" / "ontologies" / "client.ttl", "# client\n")
        _write(hub / "model" / "ontologies" / "_master.ttl", "# master\n")
        _write(hub / "model" / "ontologies" / "_foundation.ttl", "# foundation\n")
        catalog = _catalog(
            hub,
            '<uri name="https://example.com/ont/client" uri="model/ontologies/client.ttl"/>',
        )

        passed = run_catalog_test(catalog)

        assert passed is True
        out = capsys.readouterr().out
        assert "_master.ttl" not in out
        assert "_foundation.ttl" not in out


class TestCommentedOutEntries:
    def test_commented_out_entry_does_not_count_as_active(self, tmp_path, capsys):
        hub = tmp_path
        # The file for the commented entry doesn't even exist — it must not be
        # treated as a dangling entry, and the on-disk domain files below must
        # still be reported as unmapped since the commented entry maps nothing.
        _write(hub / "model" / "ontologies" / "customer.ttl", "# customer\n")
        catalog = _catalog(
            hub,
            "<!--\n"
            '<uri name="https://example.com/ont/customer" '
            'uri="model/ontologies/customer.ttl"/>\n'
            "-->",
        )

        passed = run_catalog_test(catalog)

        assert passed is True  # unmapped domain is advisory-only, not a failure
        out = capsys.readouterr().out
        assert "dangling" not in out.lower()
        assert "customer.ttl" in out  # reported as unmapped, not as dangling


class TestMissingNextCatalog:
    def test_missing_next_catalog_warns_but_does_not_fail(self, tmp_path, capsys):
        hub = tmp_path
        _write(hub / "model" / "ontologies" / "client.ttl", "# client\n")
        catalog = _catalog(
            hub,
            '<uri name="https://example.com/ont/client" uri="model/ontologies/client.ttl"/>\n'
            '<nextCatalog catalog="../ontology-reference-models/catalog-v001.xml"/>',
        )

        passed = run_catalog_test(catalog)

        assert passed is True
        out = capsys.readouterr().out
        assert "⚠️" in out
        assert "nextCatalog" in out or "ontology-reference-models" in out

    def test_missing_next_catalog_cli_exits_zero(self, tmp_path):
        hub = tmp_path
        _write(hub / "model" / "ontologies" / "client.ttl", "# client\n")
        catalog = _catalog(
            hub,
            '<uri name="https://example.com/ont/client" uri="model/ontologies/client.ttl"/>\n'
            '<nextCatalog catalog="../ontology-reference-models/catalog-v001.xml"/>',
        )

        result = CliRunner().invoke(cli, ["catalog-test", "--catalog", str(catalog)])

        assert result.exit_code == 0


class TestCatalogCycle:
    def test_catalog_cycle_warns_but_does_not_fail(self, tmp_path, capsys):
        hub = tmp_path
        _write(hub / "model" / "ontologies" / "client.ttl", "# client\n")
        # The catalog chains to itself, forming a cycle.
        catalog = _catalog(
            hub,
            '<uri name="https://example.com/ont/client" uri="model/ontologies/client.ttl"/>\n'
            '<nextCatalog catalog="catalog-v001.xml"/>',
        )

        passed = run_catalog_test(catalog)

        assert passed is True
        out = capsys.readouterr().out
        assert "⚠️" in out
        assert "cycle" in out.lower()


class TestMalformedCatalog:
    """A malformed catalog must fail cleanly (review finding #3) — not raise an
    uncaught ET.ParseError/OSError traceback out of the command.
    """

    def test_malformed_xml_fails_cleanly_without_raising(self, tmp_path, capsys):
        hub = tmp_path
        catalog = _write(hub / "catalog-v001.xml", "<catalog><uri name='x' uri='y.ttl'")

        passed = run_catalog_test(catalog)

        assert passed is False
        out = capsys.readouterr().out
        assert "not parseable" in out.lower()
        assert "❌" in out

    def test_malformed_xml_cli_exits_nonzero_without_traceback(self, tmp_path):
        hub = tmp_path
        catalog = _write(hub / "catalog-v001.xml", "<catalog><uri name='x' uri='y.ttl'")

        result = CliRunner().invoke(cli, ["catalog-test", "--catalog", str(catalog)])

        assert result.exit_code != 0
        assert "Traceback" not in result.output
        assert "not parseable" in result.output.lower()

    def test_unreadable_catalog_fails_cleanly_without_raising(self, tmp_path, capsys):
        hub = tmp_path
        catalog = _write(hub / "catalog-v001.xml", "<catalog></catalog>")

        with mock.patch("kairos_ontology.core.catalog_utils.ET.parse", side_effect=OSError("boom")):
            passed = run_catalog_test(catalog)

        assert passed is False
        out = capsys.readouterr().out
        assert "not parseable" in out.lower()


class TestAbsoluteUriEntries:
    """OASIS catalogs permit an absolute-URI uri= target; it must be treated as
    informational, never reported as dangling with a mangled local path
    (review finding #4).
    """

    def test_absolute_uri_entry_not_reported_as_dangling(self, tmp_path, capsys):
        hub = tmp_path
        _write(hub / "model" / "ontologies" / "client.ttl", "# client\n")
        catalog = _catalog(
            hub,
            '<uri name="https://example.com/ont/client" uri="model/ontologies/client.ttl"/>\n'
            '<uri name="https://spec.edmcouncil.org/fibo/master" '
            'uri="https://spec.edmcouncil.org/fibo/master.rdf"/>',
        )

        passed = run_catalog_test(catalog)

        assert passed is True
        out = capsys.readouterr().out
        # Not flagged as a dangling/failing entry, and not mangled onto the hub dir.
        assert "❌" not in out
        assert str(hub) + "\\https:" not in out
        assert str(hub) + "/https:" not in out
        # Still surfaced, informationally.
        assert "https://spec.edmcouncil.org/fibo/master" in out


class TestFreshlyInitedHub:
    """Blast-radius regression: a freshly-`init`ed hub must pass catalog-test with
    exit 0. Uses the same offline `init` infrastructure as tests/test_init.py.
    """

    def test_freshly_inited_hub_passes_catalog_test(self, tmp_path):
        runner = CliRunner()
        with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)
            with runner.isolated_filesystem(temp_dir=tmp_path):
                init_result = runner.invoke(
                    cli, ["init", "--company-domain", "test.com", "--domain", "order"]
                )
                assert init_result.exit_code == 0

                catalog = Path("ontology-hub/catalog-v001.xml")
                assert catalog.is_file()

                result = runner.invoke(cli, ["catalog-test", "--catalog", str(catalog)])

                assert result.exit_code == 0, result.output
