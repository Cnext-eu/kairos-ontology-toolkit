# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``kairos-ext:goldExcludeRelationship`` leaves one Silver relationship out of a product (#1012).

The remedy ``gold.ambiguous-path`` suggests -- "remove the redundant route" -- had no Gold
term. ``goldExcludeColumn`` on the foreign key failed with
``gold.relationship-column-not-emitted``, so the only way to drop a detour was to delete a
true fact from the Silver binding. The new term removes the edge from the product only,
fails closed on a stale value, and is deferred per domain like ``goldPrimaryRelationship``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kairos_ontology.core.compiler.kernel import build_compile_plan
from kairos_ontology.core.projections.dbt.gold_connection import GoldProductConfig
from kairos_ontology.core.projections.dbt.gold_shape import (
    _check_excluded_relationships,
    _shape_relationships,
)
from kairos_ontology.core.projections.dbt.gold_specs import (
    GoldColumnSpec,
    GoldContractError,
    GoldTableSpec,
)
from kairos_ontology.core.projections.dbt.policy_specs import (
    CanonicalTypeKind,
    CanonicalTypeSpec,
    GoldTableRole,
)
from kairos_ontology.core.projections.dbt.specs import (
    ForeignKeyDescriptorSpec,
    SilverForeignKeySpec,
)
from kairos_ontology.core.projections.medallion_gold_projector import (
    generate_gold_from_compile_plans,
)

_NS = "https://example.test/ontology/tms#"
_STRING = CanonicalTypeSpec(CanonicalTypeKind.STRING)


def _column(name: str) -> GoldColumnSpec:
    return GoldColumnSpec(
        source_name=name,
        name=name,
        canonical_type=_STRING,
        nullable=False,
        role="foreign-key",
        comment="",
        provenance=(),
    )


def _table(name: str, role: GoldTableRole, key: str, *columns: str) -> GoldTableSpec:
    return GoldTableSpec(
        resource_uri=_NS + name,
        name=name,
        schema_name="gold",
        role=role,
        source_model=name,
        source_version="1.0.0",
        columns=tuple(_column(item) for item in (key, *columns)),
        primary_key=key,
    )


def _descriptor(prop: str, source: str, target: str) -> ForeignKeyDescriptorSpec:
    return ForeignKeyDescriptorSpec(
        property_uri=_NS + prop,
        domain_class=_NS + source,
        range_class=_NS + target,
        source_class=_NS + source,
        target_class=_NS + target,
        is_functional=True,
        max_cardinality_classes=frozenset(),
        silver_foreign_key=True,
        silver_column_name=None,
        redirected=False,
        reverse=False,
        junction_table_name=None,
        nullable=None,
        conditional_on_type="",
    )


def _model(key: str, *fks: tuple[str, str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        primary_key=SimpleNamespace(columns=(key,), predicate=None),
        unique_keys=(),
        foreign_keys=tuple(
            SilverForeignKeySpec(
                property_uri=_NS + prop,
                columns=(column,),
                referenced_model=target,
                referenced_columns=(column,),
                label=prop,
                temporal_mode="none",
            )
            for prop, column, target in fks
        ),
    )


def _snowflake(*, consignment_emits_branch: bool = True):
    """A shipment with a direct branch key and a branch reached through its job."""
    consignment_columns = ("job_sk", "branch_sk") if consignment_emits_branch else ("job_sk",)
    tables = (
        _table("fact_consignment", GoldTableRole.FACT, "consignment_sk", *consignment_columns),
        _table("dim_job", GoldTableRole.DIMENSION, "job_sk", "branch_sk"),
        _table("dim_branch", GoldTableRole.DIMENSION, "branch_sk"),
    )
    descriptors = (
        _descriptor("job", "fact_consignment", "dim_job"),
        _descriptor("controllingBranch", "fact_consignment", "dim_branch"),
        _descriptor("branch", "dim_job", "dim_branch"),
    )
    models = {
        "fact_consignment": _model(
            "consignment_sk",
            ("job", "job_sk", "dim_job"),
            ("controllingBranch", "branch_sk", "dim_branch"),
        ),
        "dim_job": _model("job_sk", ("branch", "branch_sk", "dim_branch")),
        "dim_branch": _model("branch_sk"),
    }
    return tables, descriptors, models


_DIRECT = ("fact_consignment", "branch_sk", "dim_branch", "branch_sk")


def _edges(relationships) -> set[str]:
    return {
        f"{item.source_table}.{item.source_column} -> {item.target_table}.{item.target_column}"
        for item in relationships
    }


class TestShaping:
    def test_the_excluded_edge_is_gone_and_the_others_stay(self):
        matched: set = set()
        relationships, _, _ = _shape_relationships(
            *_snowflake(), excluded=frozenset({_DIRECT}), matched=matched
        )
        assert _edges(relationships) == {
            "fact_consignment.job_sk -> dim_job.job_sk",
            "dim_job.branch_sk -> dim_branch.branch_sk",
        }
        assert matched == {_DIRECT}

    def test_without_the_term_the_detour_is_emitted(self):
        relationships, _, _ = _shape_relationships(*_snowflake())
        assert "fact_consignment.branch_sk -> dim_branch.branch_sk" in _edges(relationships)

    def test_it_composes_with_excluding_the_column(self):
        """The column may go too; that used to fail with relationship-column-not-emitted."""
        tables, descriptors, models = _snowflake(consignment_emits_branch=False)
        with pytest.raises(GoldContractError) as excinfo:
            _shape_relationships(tables, descriptors, models)
        assert excinfo.value.code == "gold.relationship-column-not-emitted"

        relationships, _, _ = _shape_relationships(
            tables, descriptors, models, excluded=frozenset({_DIRECT}), matched=set()
        )
        assert len(relationships) == 2


class TestStaleValues:
    _TABLES = frozenset({"fact_consignment", "dim_job", "dim_branch", "dim_date"})

    def _check(self, key, *, deferred=None):
        _check_excluded_relationships(
            {key: ("as authored", "https://example.test/ontology/tms")},
            set(),
            table_names=self._TABLES,
            deferred=deferred,
        )

    def test_a_value_between_tables_in_scope_fails_closed(self):
        with pytest.raises(GoldContractError) as excinfo:
            self._check(("fact_consignment", "nope", "dim_branch", "branch_sk"), deferred=[])
        assert excinfo.value.code == "gold.unknown-excluded-relationship"

    def test_a_value_naming_another_domains_table_is_deferred(self):
        deferred: list = []
        self._check(("fact_consignment", "party_sk", "dim_party", "party_sk"), deferred=deferred)
        assert deferred == [("goldExcludeRelationship", "as authored")]

    def test_at_product_level_nothing_is_deferred(self):
        with pytest.raises(GoldContractError):
            self._check(("fact_consignment", "party_sk", "dim_party", "party_sk"))

    def test_a_calendar_edge_points_at_the_calendar_term(self):
        with pytest.raises(GoldContractError, match="rolePlayingDate"):
            self._check(("fact_consignment", "shipped_on", "dim_date", "full_date"))


# End to end over the two-domain product hub, on the bridge edges of #763.
_PRODUCT_HUB = Path(__file__).parent / "scenarios" / "v5-product-hub"
_PRODUCT = GoldProductConfig(name="invoicing", domains=("party", "billing"))


def _hub(tmp_path: Path, excluded: str) -> Path:
    from tests.test_gold_cross_domain_bridge import _cross_domain_hub

    hub = _cross_domain_hub(tmp_path)
    path = hub / "model" / "extensions" / "party-gold-ext.ttl"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n<https://example.test/ontology/party> "
        + f'kairos-ext:goldExcludeRelationship "{excluded}" .\n',
        encoding="utf-8",
    )
    return hub


def _product(hub: Path) -> dict[str, str]:
    return generate_gold_from_compile_plans(
        [build_compile_plan(hub, domain) for domain in _PRODUCT.domains], _PRODUCT
    )


def _report(artifacts: dict[str, str]) -> dict:
    path = next(name for name in artifacts if name.endswith("-gold-product.json"))
    return json.loads(artifacts[path])


_RELATIONSHIPS = "invoicing/Invoicing.SemanticModel/definition/relationships.tmdl"


class TestEndToEnd:
    def test_a_bridge_edge_in_scope_is_excluded_per_domain_and_in_the_product(self, tmp_path):
        value = "bridge_customer_invoice.code -> dim_customer.customer_sk"
        hub = _hub(tmp_path, value)
        plan = build_compile_plan(hub, "party")
        assert not plan.blocked, [item.render() for item in plan.diagnostics.items]
        assert plan.shaped_project.gold_product.excluded_relationships == (value,)

        artifacts = _product(hub)
        assert "fromColumn: bridge_customer_invoice.code" not in artifacts[_RELATIONSHIPS]
        assert "fromColumn: bridge_customer_invoice.country_name" in artifacts[_RELATIONSHIPS]
        assert _report(artifacts)["excluded_relationships"] == [value]

    def test_an_edge_to_another_domain_is_deferred_then_applied(self, tmp_path):
        value = "bridge_customer_invoice.country_name -> fact_invoice.invoice_sk"
        hub = _hub(tmp_path, value)
        product = build_compile_plan(hub, "party").shaped_project.gold_product
        assert ("goldExcludeRelationship", value) in product.deferred_references

        artifacts = _product(hub)
        assert "fromColumn: bridge_customer_invoice.country_name" not in artifacts[_RELATIONSHIPS]
        assert not _report(artifacts).get("deferred_references")

    def test_a_malformed_value_fails_the_domain_compile(self, tmp_path):
        plan = build_compile_plan(_hub(tmp_path, "bridge_customer_invoice.code"), "party")
        assert "gold.unknown-excluded-relationship" in {
            item.code for item in plan.diagnostics.items
        }

    def test_a_stale_value_fails_the_product(self, tmp_path):
        hub = _hub(tmp_path, "bridge_customer_invoice.code -> fact_invoice.nope")
        with pytest.raises(GoldContractError) as excinfo:
            _product(hub)
        assert excinfo.value.code == "gold.unknown-excluded-relationship"
