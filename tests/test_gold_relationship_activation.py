# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Only one filter path between any two tables may be active (issue #792).

Power BI refuses to load a model with an ambiguous path, reporting one offending pair per
attempt. The projector emitted every relationship active, including one per role-playing
date, so a product with four date roles on one fact shipped four active paths to
`dim_date`. On the hub that surfaced this, 21 of 50 relationships closed a cycle -- 21
round trips to find by publishing, one pass to compute offline.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import tests.test_gold_projector as harness
from kairos_ontology.core.projections.dbt.gold_shape import (
    CALENDAR_COLUMN,
    CALENDAR_TABLE,
    _calendar_relationships,
    _has_unique_key_evidence,
    _resolve_ambiguous_paths,
)
from kairos_ontology.core.projections.dbt.specs import SilverKeySpec
from kairos_ontology.core.projections.dbt.gold_specs import (
    GoldCalendarRoleSpec,
    GoldCalendarSpec,
    GoldContractError,
    GoldRelationshipSpec,
)


def _edge(
    source_table: str,
    source_column: str,
    target_table: str,
    target_column: str = "id",
    *,
    role_name: str = "",
) -> GoldRelationshipSpec:
    return GoldRelationshipSpec(
        name=f"{source_table}_{source_column}",
        source_table=source_table,
        source_column=source_column,
        target_table=target_table,
        target_column=target_column,
        cardinality="many-to-one",
        version_binding=None,
        role_name=role_name,
    )


def _active(relationships) -> list[str]:
    return [item.name for item in relationships if item.is_active]


def _inactive(relationships) -> list[str]:
    return [item.name for item in relationships if not item.is_active]


class TestSpanningForest:
    def test_an_unambiguous_star_keeps_every_relationship_active(self):
        """Non-vacuity, and the compatibility promise: ordinary models do not change."""
        edges = (
            _edge("fact_a", "dim_b_sk", "dim_b"),
            _edge("fact_a", "dim_c_sk", "dim_c"),
            _edge("fact_a", "dim_d_sk", "dim_d"),
        )
        resolved = _resolve_ambiguous_paths(edges, frozenset())
        assert _inactive(resolved) == []

    def test_a_second_edge_between_the_same_pair_is_deactivated(self):
        edges = (
            _edge("fact_a", "ship_to_sk", "dim_b"),
            _edge("fact_a", "bill_to_sk", "dim_b"),
        )
        resolved = _resolve_ambiguous_paths(edges, frozenset())
        assert len(_active(resolved)) == 1
        assert len(_inactive(resolved)) == 1

    def test_a_snowflake_shortcut_loses_to_the_multi_hop_path(self):
        """`dim_d -> dim_g` alongside `dim_d -> dim_h -> dim_g` is a three-cycle."""
        edges = (
            _edge("dim_d", "h_sk", "dim_h"),
            _edge("dim_h", "g_sk", "dim_g"),
            _edge("dim_d", "g_sk", "dim_g"),
        )
        resolved = _resolve_ambiguous_paths(edges, frozenset())
        assert len(_active(resolved)) == 2
        assert len(_inactive(resolved)) == 1

    def test_active_edges_never_exceed_nodes_minus_components(self):
        """The invariant the issue asks the emit gate to enforce."""
        edges = (
            _edge("fact_a", "d1", CALENDAR_TABLE, CALENDAR_COLUMN, role_name="Ordered"),
            _edge("fact_a", "d2", CALENDAR_TABLE, CALENDAR_COLUMN, role_name="Shipped"),
            _edge("fact_a", "d3", CALENDAR_TABLE, CALENDAR_COLUMN, role_name="Invoiced"),
            _edge("fact_a", "d4", CALENDAR_TABLE, CALENDAR_COLUMN, role_name="Paid"),
            _edge("fact_a", "b_sk", "dim_b"),
            _edge("fact_a", "b2_sk", "dim_b"),
            _edge("dim_b", "c_sk", "dim_c"),
        )
        resolved = _resolve_ambiguous_paths(edges, frozenset())
        active = [item for item in resolved if item.is_active]
        nodes = {item.source_table for item in resolved} | {item.target_table for item in resolved}
        assert len(active) == len(nodes) - 1, "one connected component, so a spanning tree"

    def test_a_business_relationship_outranks_a_date_role(self):
        """A role edge is never kept at the cost of deactivating a real foreign key."""
        edges = (
            _edge("fact_a", "d1", CALENDAR_TABLE, CALENDAR_COLUMN, role_name="Ordered"),
            _edge("dim_date_owner", "fact_sk", "fact_a"),
            _edge("dim_date_owner", "cal_sk", CALENDAR_TABLE, CALENDAR_COLUMN),
        )
        resolved = _resolve_ambiguous_paths(edges, frozenset())
        deactivated = _inactive(resolved)
        assert len(deactivated) == 1
        assert deactivated[0] == "fact_a_d1", "the role edge is the one that gives way"

    def test_the_result_is_deterministic(self):
        edges = (
            _edge("fact_a", "ship_to_sk", "dim_b"),
            _edge("fact_a", "bill_to_sk", "dim_b"),
            _edge("fact_a", "c_sk", "dim_c"),
        )
        first = _resolve_ambiguous_paths(edges, frozenset())
        second = _resolve_ambiguous_paths(edges, frozenset())
        assert _active(first) == _active(second)

    def test_input_order_does_not_change_the_outcome(self):
        edges = (
            _edge("fact_a", "ship_to_sk", "dim_b"),
            _edge("fact_a", "bill_to_sk", "dim_b"),
        )
        assert _active(_resolve_ambiguous_paths(edges, frozenset())) == _active(
            _resolve_ambiguous_paths(tuple(reversed(edges)), frozenset())
        )


class TestTheAuthoredOverrideDecidesWhichPathSurvives:
    """The active date role is the one time intelligence follows, so it is semantics."""

    def test_the_declared_relationship_stays_active(self):
        edges = (
            _edge("fact_a", "ship_to_sk", "dim_b"),
            _edge("fact_a", "bill_to_sk", "dim_b"),
        )
        # Without an override, sort order keeps `bill_to_sk`.
        assert _active(_resolve_ambiguous_paths(edges, frozenset())) == ["fact_a_bill_to_sk"]

        declared = frozenset({("fact_a", "ship_to_sk", "dim_b", "id")})
        assert _active(_resolve_ambiguous_paths(edges, declared)) == ["fact_a_ship_to_sk"]


class TestCalendarRolesAreShapedNotInvented:
    """They used to be built in the renderer, so no graph could see them."""

    def _calendar(self, *roles: tuple[str, str, str]) -> GoldCalendarSpec:
        return GoldCalendarSpec(
            resource_uri="urn:test:calendar",
            start_date="2020-01-01",
            end_date="2035-12-31",
            fiscal_year_start_month=1,
            week_pattern="iso-8601-monday",
            locale="en-GB",
            holiday_source="none-approved",
            time_zone="Europe/Brussels",
            period_closure="none",
            roles=tuple(GoldCalendarRoleSpec(*role) for role in roles),
            approved=True,
        )

    def test_each_role_becomes_a_relationship_to_the_calendar(self):
        shaped = _calendar_relationships(
            self._calendar(
                ("Ordered", "fact_a", "ordered_date"),
                ("Shipped", "fact_a", "shipped_date"),
            )
        )
        assert len(shaped) == 2
        assert {item.target_table for item in shaped} == {CALENDAR_TABLE}
        assert {item.target_column for item in shaped} == {CALENDAR_COLUMN}

    def test_the_emitted_relationship_name_is_unchanged(self):
        """In Fabric a renamed relationship is a new object, not an edit.

        The renderer seeded these with `calendar.<role>`; moving them into the shaper
        must not silently re-identify every date relationship in every existing hub.
        """
        shaped = _calendar_relationships(self._calendar(("Ordered", "fact_a", "ordered_date")))
        assert shaped[0].guid_seed == "calendar.Ordered"

    def test_a_draft_calendar_contributes_no_edges(self):
        draft = replace(self._calendar(("Ordered", "fact_a", "ordered_date")), approved=False)
        assert _calendar_relationships(None) == ()
        assert _calendar_relationships(draft) == ()


class TestEndToEnd:
    """Through the real projector, not hand-built specs."""

    def _emit(self, tmp_path: Path, roles: str):
        text = harness._gold_text("invoice").replace(
            '    kairos-ext:rolePlayingDate "InvoiceDate=Invoice.invoice_date" ;',
            roles,
            1,
        )
        return harness._generate(
            "invoice", gold_path=harness._write_gold(tmp_path, "invoice", text)
        )

    def _relationships(self, artifacts: dict[str, str]) -> str:
        return artifacts[next(path for path in artifacts if path.endswith("relationships.tmdl"))]

    def test_two_roles_on_disconnected_facts_both_stay_active(self, tmp_path):
        """Only a *cycle* is ambiguous, and deactivating an edge can remove one.

        `fact_invoice_line` reaches `dim_date` twice only while it also reaches
        `fact_invoice`. That edge is itself inactive (#794: its one side is
        `_source_system`, which no declared key backs), so the two calendar roles sit in
        different components and both are legitimately active. Asserting "exactly one
        active date edge" would be asserting an over-approximation rather than the rule.
        """
        artifacts = self._emit(
            tmp_path,
            '    kairos-ext:rolePlayingDate "InvoiceDate=Invoice.invoice_date" ;\n'
            '    kairos-ext:rolePlayingDate "LoadedDate=fact_invoice_line._loaded_at" ;',
        )
        tmdl = self._relationships(artifacts)
        blocks = [block for block in tmdl.split("relationship ") if "dim_date" in block]
        assert len(blocks) == 2, tmdl
        assert not any("isActive: false" in block for block in blocks), tmdl

    def test_every_deactivation_is_reported_with_its_reason(self, tmp_path):
        """A silent pick would change a report's meaning with nothing to review."""
        report = harness._report(harness._generate("invoice"), "invoice")
        deactivated = report["deactivated_relationships"]

        assert [item["reason"] for item in deactivated] == ["unproven-key"]
        assert deactivated[0]["to"] == "fact_invoice._source_system"

    def test_a_single_role_product_has_no_ambiguous_path(self, tmp_path):
        """Compatibility: nothing is deactivated for ambiguity when there is none.

        The fixture does carry one inactive relationship, but for the unrelated #794
        reason -- its one side is `fact_invoice._source_system`, which no declared
        key backs. The calendar edge, the only candidate for an ambiguous path here,
        stays active.
        """
        artifacts = harness._generate("invoice")
        report = harness._report(artifacts, "invoice")
        reasons = {item["reason"] for item in report.get("deactivated_relationships", ())}
        assert "ambiguous-path" not in reasons

        calendar_block = next(
            block
            for block in self._relationships(artifacts).split("relationship ")
            if "dim_date" in block
        )
        assert "isActive: false" not in calendar_block

    def test_an_override_naming_no_relationship_fails_closed(self, tmp_path):
        """Mirrors `goldExcludeColumn`: a stale value must not read as success."""
        text = harness._gold_text("invoice").replace(
            '    kairos-ext:goldSchema "gold" ;',
            '    kairos-ext:goldSchema "gold" ;\n'
            '    kairos-ext:goldPrimaryRelationship "fact_nowhere.x -> dim_date.full_date" ;',
            1,
        )
        with pytest.raises(GoldContractError) as excinfo:
            harness._generate("invoice", gold_path=harness._write_gold(tmp_path, "invoice", text))
        assert excinfo.value.code == "gold.unknown-primary-relationship"


def test_the_vocabulary_declares_the_term():
    from kairos_ontology.cli.shared import _SCAFFOLD_DIR

    text = (_SCAFFOLD_DIR / "kairos-ext.ttl").read_text(encoding="utf-8")
    assert "kairos-ext:goldPrimaryRelationship a owl:AnnotationProperty" in text


class TestTheOneSideNeedsADeclaredUniqueKey:
    """#794: the engine enforces uniqueness when it builds the relationship index.

    Not at validation. A model with a non-unique "one" side publishes, refreshes green,
    answers single-table measures, and fails on the first query whose plan traverses the
    relationship -- so it can look entirely healthy and still be broken.

    `_primary_key` never consulted a declared key: it walks a role priority list and
    falls back to "first non-nullable column, else first column". On the `invoice`
    fixture that lands on `fact_invoice._source_system`, the same value on every row of a
    source. `_table_tmdl` already refused to mark such a column `isKey` for exactly this
    reason; nothing protected the relationship endpoint.
    """

    def _model(self, primary=None, unique=()):
        return SimpleNamespace(primary_key=primary, unique_keys=tuple(unique))

    def test_a_declared_single_column_primary_key_is_evidence(self):
        model = self._model(primary=SilverKeySpec(("customer_sk",)))
        assert _has_unique_key_evidence(model, "customer_sk", filtered=False)

    def test_a_declared_unique_key_is_evidence(self):
        model = self._model(unique=[SilverKeySpec(("customer_code",))])
        assert _has_unique_key_evidence(model, "customer_code", filtered=False)

    def test_an_undeclared_column_is_not(self):
        """The real failure: `_source_system` is not a key of anything."""
        model = self._model(primary=SilverKeySpec(("invoice_sk",)))
        assert not _has_unique_key_evidence(model, "_source_system", filtered=False)

    def test_a_composite_key_is_not_evidence_about_one_column(self):
        """`GoldTableSpec.primary_key` is a single column and cannot express a grain."""
        model = self._model(primary=SilverKeySpec(("source_system", "record_key")))
        assert not _has_unique_key_evidence(model, "source_system", filtered=False)

    def test_a_predicated_key_needs_the_table_to_apply_the_same_filter(self):
        """An SCD2 grain is unique only among current rows."""
        model = self._model(primary=SilverKeySpec(("customer_sk",), predicate="is_current = 1"))
        assert not _has_unique_key_evidence(model, "customer_sk", filtered=False)
        assert _has_unique_key_evidence(model, "customer_sk", filtered=True)

    def test_a_missing_model_is_not_evidence(self):
        assert not _has_unique_key_evidence(None, "customer_sk", filtered=False)


class TestTheUnprovenRelationshipIsEmittedInactive:
    """Inactive, not refused: failing closed would block hubs that publish today."""

    def test_the_fixture_relationship_is_deactivated_and_explained(self):
        artifacts = harness._generate("invoice")
        tmdl = artifacts[next(path for path in artifacts if path.endswith("relationships.tmdl"))]
        block = next(item for item in tmdl.split("relationship ") if "_source_system" in item)
        assert "isActive: false" in block

        report = harness._report(artifacts, "invoice")
        assert [item["reason"] for item in report["deactivated_relationships"]] == ["unproven-key"]

    def test_an_unproven_edge_never_displaces_a_sound_one(self):
        """It must not claim a place in the spanning forest and deactivate a real one."""
        unproven = replace(
            _edge("fact_b", "a_sk", "fact_a"), is_active=False, inactive_reason="unproven-key"
        )
        sound = _edge("fact_b", "a2_sk", "fact_a")
        resolved = _resolve_ambiguous_paths((unproven, sound), frozenset())

        assert _active(resolved) == ["fact_b_a2_sk"]
        reasons = {item.name: item.inactive_reason for item in resolved if not item.is_active}
        assert reasons == {"fact_b_a_sk": "unproven-key"}
