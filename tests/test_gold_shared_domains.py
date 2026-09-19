# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""A conformed dimension can be shared across Gold products (#829, DD-228).

`parse_gold_products` failed closed when two products claimed one domain:

    domain 'party' is claimed by both 'invoicing' and 'crm'; a domain belongs to
    exactly one Gold product

DD-222's reasoning for that rule was sound -- two products over one domain would emit its
tables twice under two model names, with no way for a report author to tell which is
authoritative. **But the rule was enforced on _domains_, while the thing that must not be
duplicated is a _table_.** Those coincide for a fact-bearing domain and diverge for a
dimension-only one, which is exactly what a conformed dimension is.

One correction worth recording, because the issue assumed otherwise and so did the first
draft of this work: a Gold dbt model is emitted per **domain**, to
`models/gold/<domain>/<table>.sql`, by that domain's own `compile --emit`. Products exist
only in the Power BI lane. So a conformed dimension was always materialized exactly once,
and what sharing changes is only which semantic models may read it -- which is why the
change is as small as it is, and why the tests below assert on *reading* rather than on
any de-duplication of output.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.core.hub_utils import publish_root
from kairos_ontology.cli.main import cli
from kairos_ontology.core.projections.dbt.gold_connection import (
    GoldContractError,
    parse_gold_products,
    resolve_gold_product,
)

_PRODUCT_HUB = Path(__file__).parent / "scenarios" / "v5-product-hub"

_PARTY_GOLD = """
@prefix party: <https://example.test/ontology/party#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

<https://example.test/ontology/party>
  kairos-ext:goldSchema "gold_party" ;
  kairos-ext:goldProductProfile "dimensional-powerbi-v1" .

party:Customer
  kairos-ext:goldTableType "dimension" ;
  kairos-ext:goldTableName "dim_customer" ;
  kairos-ext:goldSourceModel "customer" ;
  kairos-ext:goldSourceVersion "1.0.0" ;
  kairos-ext:dimensionExposure "current-only" ;
  kairos-ext:dimensionVersionBinding "current" .
"""

_BILLING_GOLD = """
@prefix billing: <https://example.test/ontology/billing#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

<https://example.test/ontology/billing>
  kairos-ext:goldSchema "gold_billing" ;
  kairos-ext:goldProductProfile "dimensional-powerbi-v1" .

billing:Invoice
  kairos-ext:goldTableType "fact" ;
  kairos-ext:goldTableName "fact_invoice" ;
  kairos-ext:goldSourceModel "invoice" ;
  kairos-ext:goldSourceVersion "1.0.0" ;
  kairos-ext:factGrain "one row per invoice" ;
  kairos-ext:factType "transaction" ;
  kairos-ext:dimensionVersionBinding "current" .
"""

_SHARED_PRODUCTS = """
  shared_domains: [party]
  products:
    - name: invoicing
      domains: [billing, party]
    - name: crm
      domains: [party]
"""


def _hub(tmp_path: Path, products_yaml: str = _SHARED_PRODUCTS) -> Path:
    hub = tmp_path / "hub"
    shutil.copytree(_PRODUCT_HUB, hub)
    extensions = hub / "model" / "extensions"
    extensions.mkdir(parents=True, exist_ok=True)
    (extensions / "party-gold-ext.ttl").write_text(_PARTY_GOLD, encoding="utf-8")
    (extensions / "billing-gold-ext.ttl").write_text(_BILLING_GOLD, encoding="utf-8")
    config = hub / "kairos.yaml"
    config.write_text(config.read_text(encoding="utf-8") + products_yaml, encoding="utf-8")
    return hub


def _emit(hub: Path, name: str, monkeypatch, *args: str):
    monkeypatch.chdir(hub)
    return CliRunner().invoke(cli, ["emit-gold", name, *args])


def _gold_dir(hub: Path) -> Path:
    return publish_root(hub) / "powerbi"


def _report(hub: Path, product: str) -> dict:
    path = _gold_dir(hub) / product / f"{product}-gold-product.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _config(shared_domains: str, products: str) -> dict:
    import yaml

    return yaml.safe_load(f"gold:\n  shared_domains: {shared_domains}\n  products:\n{products}")


_TWO_PRODUCTS_OVER_PARTY = """    - name: invoicing
      domains: [billing, party]
    - name: crm
      domains: [party]
"""

_ONE_PRODUCT = """    - name: invoicing
      domains: [billing]
"""


class TestConfig:
    def test_two_products_may_share_a_declared_domain(self):
        products = parse_gold_products(_config("[party]", _TWO_PRODUCTS_OVER_PARTY))

        assert [item.name for item in products] == ["invoicing", "crm"]
        assert products[0].shared_domains == ("party",)
        assert products[1].shared_domains == ("party",)

    def test_a_product_only_marks_the_shared_domains_it_lists(self):
        """`shared_domains` is hub-wide; `GoldProductConfig.shared_domains` is this
        product's slice of it, so shaping need not re-read the config."""
        products = parse_gold_products(
            _config("[party, reference-data]", _TWO_PRODUCTS_OVER_PARTY)
        )
        assert products[0].shared_domains == ("party",)
        assert products[0].owns("billing")
        assert not products[0].owns("party")

    def test_an_undeclared_shared_domain_still_fails(self):
        """DD-222's rule is unchanged wherever sharing was not declared -- only the
        remedy is new."""
        with pytest.raises(GoldContractError) as excinfo:
            parse_gold_products(_config("[]", _TWO_PRODUCTS_OVER_PARTY))

        message = str(excinfo.value)
        assert "belongs to exactly one Gold product" in message
        assert "gold.shared_domains" in message

    def test_declaring_no_shared_domains_at_all_is_unchanged(self):
        import yaml

        config = yaml.safe_load(f"gold:\n  products:\n{_TWO_PRODUCTS_OVER_PARTY}")
        with pytest.raises(GoldContractError) as excinfo:
            parse_gold_products(config)
        assert "belongs to exactly one Gold product" in str(excinfo.value)

    def test_a_shared_domain_nothing_references_yet_is_accepted(self):
        """Declaring the conformed dimension before adding the second product is the
        natural authoring order, and this function raises rather than warns."""
        products = parse_gold_products(_config("[reference-data]", _ONE_PRODUCT))
        assert products[0].shared_domains == ()

    def test_a_shared_domain_may_not_be_a_product_name(self):
        with pytest.raises(GoldContractError) as excinfo:
            parse_gold_products(_config("[party, crm]", _TWO_PRODUCTS_OVER_PARTY))
        assert "not one itself" in str(excinfo.value)

    @pytest.mark.parametrize(
        ("value", "detail"),
        [
            ("party", "expected a list"),
            ("[party, party]", "listed twice"),
            ('[""]', "expected a list"),
            ("[1]", "expected a list"),
        ],
    )
    def test_malformed_shared_domains_fail_closed(self, value, detail):
        with pytest.raises(GoldContractError) as excinfo:
            parse_gold_products(_config(value, _TWO_PRODUCTS_OVER_PARTY))
        assert detail in str(excinfo.value)


class TestResolution:
    def test_a_shared_domain_does_not_resolve_to_one_product(self, tmp_path):
        """Picking one of several would emit a model whose name says nothing about
        which it is."""
        hub = _hub(tmp_path)

        with pytest.raises(GoldContractError) as excinfo:
            resolve_gold_product(hub, "party", hub_domains=("party", "billing"))

        message = str(excinfo.value)
        assert "'invoicing'" in message and "'crm'" in message
        assert "emit-gold invoicing" in message and "emit-gold crm" in message

    def test_a_domain_in_exactly_one_product_still_points_at_it(self, tmp_path):
        """The single-owner message is the more useful one where it applies, and is
        unchanged."""
        hub = _hub(tmp_path)

        with pytest.raises(GoldContractError) as excinfo:
            resolve_gold_product(hub, "billing", hub_domains=("party", "billing"))

        assert "is part of the Gold product 'invoicing'" in str(excinfo.value)


class TestEmit:
    def test_both_products_emit_and_carry_the_shared_dimension(self, tmp_path, monkeypatch):
        hub = _hub(tmp_path)

        first = _emit(hub, "invoicing", monkeypatch, "--confirm-emit")
        second = _emit(hub, "crm", monkeypatch, "--confirm-emit")

        assert first.exit_code == 0, first.output
        assert second.exit_code == 0, second.output
        for product, model in (("invoicing", "Invoicing"), ("crm", "Crm")):
            tables = _gold_dir(hub) / product / f"{model}.SemanticModel" / "definition" / "tables"
            assert (tables / "dim_customer.tmdl").is_file(), product

    def test_the_shared_table_keeps_its_owning_domain_s_schema(self, tmp_path, monkeypatch):
        """Both semantic models must point at the one physical relation. `schema_name` is
        already per-table, so this needed no change -- but it is the assumption that would
        otherwise produce a model silently reading the wrong schema."""
        hub = _hub(tmp_path)
        _emit(hub, "invoicing", monkeypatch, "--confirm-emit")
        _emit(hub, "crm", monkeypatch, "--confirm-emit")

        for product, model in (("invoicing", "Invoicing"), ("crm", "Crm")):
            tmdl = (
                _gold_dir(hub)
                / product
                / f"{model}.SemanticModel"
                / "definition"
                / "tables"
                / "dim_customer.tmdl"
            ).read_text(encoding="utf-8")
            assert 'schemaName: "gold_party"' in tmdl, product

    def test_the_product_report_says_which_tables_are_read_not_built(self, tmp_path, monkeypatch):
        hub = _hub(tmp_path)
        _emit(hub, "invoicing", monkeypatch, "--confirm-emit")

        tables = {item["name"]: item for item in _report(hub, "invoicing")["tables"]}
        assert tables["dim_customer"]["materialized_by"] == {"domain": "party", "shared": True}
        # An owned table gains no key: every hub shipping today owns all of its tables.
        assert "materialized_by" not in tables["fact_invoice"]

    def test_the_emit_output_names_the_owned_shared_split(self, tmp_path, monkeypatch):
        hub = _hub(tmp_path)

        result = _emit(hub, "invoicing", monkeypatch, "--confirm-emit")

        assert "1 table(s) built by this product, 1 read as shared" in result.output
        assert "dim_customer (owned by party)" in result.output

    def test_the_ddl_says_where_a_shared_table_is_built(self, tmp_path, monkeypatch):
        """The issue's explicit ask: a reader of the emitted DDL must be able to tell."""
        hub = _hub(tmp_path)
        _emit(hub, "crm", monkeypatch, "--confirm-emit")

        ddl = (_gold_dir(hub) / "crm" / "crm-gold-ddl.sql").read_text(encoding="utf-8")
        assert "Conformed dimension owned by domain 'party'" in ddl

    def test_a_product_of_only_shared_domains_builds_nothing_and_says_so(
        self, tmp_path, monkeypatch
    ):
        """A legitimate shape for a model that only slices conformed dimensions, and an
        authoring stage on the way to one with its own fact."""
        hub = _hub(tmp_path)

        result = _emit(hub, "crm", monkeypatch, "--confirm-emit")

        assert result.exit_code == 0, result.output
        assert "0 table(s) built by this product, 1 read as shared" in result.output

    def test_the_second_product_does_not_collide_on_shared_provenance(
        self, tmp_path, monkeypatch
    ):
        """A provenance sidecar is emitted per participating domain, so a shared domain
        writes one from every product. Both write byte-identical content -- the document
        is a pure function of the domain's build scope -- but the second emit still failed
        closed until the path was declared mergeable."""
        hub = _hub(tmp_path)
        _emit(hub, "invoicing", monkeypatch, "--confirm-emit")

        result = _emit(hub, "crm", monkeypatch, "--confirm-emit")

        assert result.exit_code == 0, result.output
        assert (_gold_dir(hub) / "metadata" / "party-gold.provenance.json").is_file()

    def test_re_emitting_one_product_leaves_the_other_intact(self, tmp_path, monkeypatch):
        hub = _hub(tmp_path)
        _emit(hub, "invoicing", monkeypatch, "--confirm-emit")
        _emit(hub, "crm", monkeypatch, "--confirm-emit")

        assert _emit(hub, "invoicing", monkeypatch, "--confirm-emit").exit_code == 0

        crm_tables = _gold_dir(hub) / "crm" / "Crm.SemanticModel" / "definition" / "tables"
        assert (crm_tables / "dim_customer.tmdl").is_file()
        assert (_gold_dir(hub) / "metadata" / "party-gold.provenance.json").is_file()

    def test_emitting_a_shared_domain_by_name_points_at_both_products(
        self, tmp_path, monkeypatch
    ):
        hub = _hub(tmp_path)

        result = _emit(hub, "party", monkeypatch)

        assert result.exit_code != 0
        assert "invoicing" in result.output and "crm" in result.output


class TestMaterialization:
    def test_the_shared_dimension_is_built_once_by_its_own_domain(self, tmp_path, monkeypatch):
        """The premise the whole design rests on: products are a Power BI concern, and a
        Gold dbt model is emitted per domain. Two products reading `party` must not
        produce two `dim_customer` models."""
        hub = _hub(tmp_path)
        monkeypatch.chdir(hub)
        runner = CliRunner()
        for domain in ("party", "billing"):
            result = runner.invoke(cli, ["compile", domain, "--emit", "--confirm-emit"])
            assert result.exit_code == 0, result.output

        models = publish_root(hub) / "medallion" / "dbt" / "models" / "gold"
        built = sorted(path.relative_to(models).as_posix() for path in models.rglob("*.sql"))
        assert built == ["billing/fact_invoice.sql", "party/dim_customer.sql"]


class TestUndeclaredHubIsUnchanged:
    def test_a_hub_declaring_no_shared_domain_emits_what_it_always_did(
        self, tmp_path, monkeypatch
    ):
        hub = _hub(
            tmp_path,
            "\n  products:\n    - name: invoicing\n      domains: [billing, party]\n",
        )

        result = _emit(hub, "invoicing", monkeypatch, "--confirm-emit")

        assert result.exit_code == 0, result.output
        assert "read as shared" not in result.output
        tables = {item["name"] for item in _report(hub, "invoicing")["tables"]}
        assert tables == {"dim_customer", "fact_invoice"}
        assert all(
            "materialized_by" not in item for item in _report(hub, "invoicing")["tables"]
        )
