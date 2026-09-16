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

import pytest

import tests.test_gold_projector as harness
from kairos_ontology.core.projections.dbt.gold_shape import (
    CALENDAR_COLUMN,
    CALENDAR_TABLE,
    _calendar_relationships,
    _resolve_ambiguous_paths,
)
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

    def test_one_role_stays_active_and_the_rest_do_not(self, tmp_path):
        artifacts = self._emit(
            tmp_path,
            '    kairos-ext:rolePlayingDate "InvoiceDate=Invoice.invoice_date" ;\n'
            '    kairos-ext:rolePlayingDate "LoadedDate=fact_invoice_line._loaded_at" ;',
        )
        tmdl = self._relationships(artifacts)
        blocks = [block for block in tmdl.split("relationship ") if "dim_date" in block]
        assert len(blocks) == 2, tmdl
        assert sum("isActive: false" in block for block in blocks) == 1, tmdl

    def test_the_single_role_product_is_unchanged(self, tmp_path):
        """Compatibility: a model that never had an ambiguity keeps its exact bytes."""
        baseline = self._relationships(harness._generate("invoice"))
        assert "isActive" not in baseline

    def test_the_deactivation_is_reported(self, tmp_path):
        """A silent pick would change a report's meaning with nothing to review."""
        artifacts = self._emit(
            tmp_path,
            '    kairos-ext:rolePlayingDate "InvoiceDate=Invoice.invoice_date" ;\n'
            '    kairos-ext:rolePlayingDate "LoadedDate=fact_invoice_line._loaded_at" ;',
        )
        report = harness._report(artifacts, "invoice")
        assert len(report["deactivated_relationships"]) == 1
        assert report["deactivated_relationships"][0]["to"] == "dim_date.full_date"

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
