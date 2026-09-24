# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The Kairos-owned Power BI BPA profile (DD-238, issue #976).

The completeness tests are the refresh tripwire. Microsoft's ``BPARules.json`` is vendored
at a pinned commit and refreshed by hand; when it is, every rule that is new *or changed*
upstream fails here until someone has triaged it and recorded a disposition.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import tests.test_gold_projector as harness
from kairos_ontology.core.projections.dbt import bpa_profile
from kairos_ontology.core.projections.dbt.bpa_profile import (
    KAIROS_RULES,
    PROFILE,
    BpaIgnoreError,
    DispositionKind,
    Target,
    ignore_annotation,
    load_upstream_rules,
    parse_bpa_ignore,
    render_profile_markdown,
    rule_digest,
)
from kairos_ontology.core.projections.dbt.gold_shape import _shape_bpa_ignores
from kairos_ontology.core.projections.dbt.gold_specs import (
    GoldContractError,
    GoldRelationshipSpec,
)

REPO = Path(__file__).resolve().parent.parent
DECISIONS = REPO / "docs" / "dev" / "decisions"


class TestCompleteness:
    def test_every_upstream_rule_has_exactly_one_profile_entry(self):
        upstream = [rule["ID"] for rule in load_upstream_rules()]
        profiled = [item.rule_id for item in PROFILE]
        assert len(profiled) == len(set(profiled)), "a rule is profiled twice"
        missing = sorted(set(upstream) - set(profiled))
        assert not missing, (
            f"upstream rules with no disposition: {missing}. Triage each one in "
            "bpa_profile.PROFILE before refreshing the snapshot."
        )
        stale = sorted(set(profiled) - set(upstream))
        assert not stale, f"profile entries for rules no longer upstream: {stale}"

    def test_every_recorded_digest_matches_the_vendored_rule(self):
        """A rule Microsoft *changed* must be re-triaged, not only a rule it added."""
        upstream = {rule["ID"]: rule for rule in load_upstream_rules()}
        changed = sorted(
            item.rule_id
            for item in PROFILE
            if item.upstream_digest != rule_digest(upstream[item.rule_id])
        )
        assert not changed, (
            f"upstream definition changed for {changed}. Re-read each rule, confirm or "
            "change its disposition, then record the new digest."
        )

    def test_kairos_rules_never_shadow_an_upstream_id(self):
        upstream = {rule["ID"] for rule in load_upstream_rules()}
        for item, scopes in KAIROS_RULES:
            assert item.rule_id.startswith("KAIROS_")
            assert item.rule_id not in upstream
            assert item.upstream_digest == ""
            assert scopes

    def test_the_vendored_snapshot_is_the_recorded_size(self):
        """Non-vacuity: an empty or truncated vendored file would pass the tests above."""
        assert len(load_upstream_rules()) == 71


class TestDispositions:
    @pytest.mark.parametrize("target", list(Target))
    def test_every_disposition_has_a_reason(self, target):
        for item in bpa_profile.all_rules():
            assert item.disposition(target).reason.strip(), item.rule_id

    @pytest.mark.parametrize("target", list(Target))
    def test_a_rejection_names_a_recorded_decision(self, target):
        recorded = {path.name.split("-")[1] for path in DECISIONS.glob("dd-*.md")}
        for item in bpa_profile.all_rules():
            disposition = item.disposition(target)
            if disposition.kind is not DispositionKind.REJECTED:
                assert not disposition.decision, item.rule_id
                continue
            assert disposition.decision.startswith("DD-"), item.rule_id
            assert disposition.decision.removeprefix("DD-") in recorded, item.rule_id

    @pytest.mark.parametrize("target", list(Target))
    def test_only_checks_that_run_in_the_toolkit_may_block(self, target):
        """DD-163: a post-deploy or rejected rule can never gate a hub."""
        for item in bpa_profile.all_rules():
            disposition = item.disposition(target)
            if disposition.blocking:
                assert disposition.kind in {
                    DispositionKind.COMPILE_DIAGNOSTIC,
                    DispositionKind.RENDER_ASSERT,
                }, item.rule_id
                assert disposition.enforced_by, item.rule_id

    def test_the_issue_table_per_target_is_honoured(self):
        """The two rules #976 names as target-specific."""
        direct_query = "MODEL_USING_DIRECT_QUERY_AND_NO_AGGREGATIONS"
        assert bpa_profile.disposition(direct_query, Target.FABRIC).kind is DispositionKind.NOT_APPLICABLE
        assert (
            bpa_profile.disposition(direct_query, Target.DATABRICKS).kind
            is DispositionKind.POST_DEPLOY_ADVISORY
        )
        guardrails = "KAIROS_DIRECT_LAKE_GUARDRAILS"
        assert bpa_profile.disposition(guardrails, Target.DATABRICKS).kind is DispositionKind.NOT_APPLICABLE

    def test_labels_carry_the_target_or_the_decision(self):
        rejected = bpa_profile.disposition("MARK_PRIMARY_KEYS", Target.FABRIC)
        assert rejected.label(Target.FABRIC) == "rejected:DD-221"
        partitioned = bpa_profile.disposition("LARGE_TABLES_SHOULD_BE_PARTITIONED", Target.DATABRICKS)
        assert partitioned.label(Target.DATABRICKS) == "not-applicable:databricks"


class TestGuide:
    def test_the_generated_guide_is_current(self):
        guide = REPO / "docs" / "guide" / "BPA_PROFILE.md"
        assert guide.read_text(encoding="utf-8").replace("\r\n", "\n") == render_profile_markdown(), (
            "docs/guide/BPA_PROFILE.md is stale; run `python scripts/generate_bpa_profile.py`"
        )

    def test_the_guide_records_the_snapshot(self):
        text = render_profile_markdown()
        assert bpa_profile.UPSTREAM_COMMIT in text
        assert bpa_profile.UPSTREAM_REFRESHED in text
        for item in bpa_profile.all_rules():
            assert f"`{item.rule_id}`" in text

    def test_the_generator_script_check_mode_agrees(self):
        result = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "generate_bpa_profile.py"), "--check"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr


class TestParseIgnore:
    def test_a_measure_exception_parses(self):
        item = parse_bpa_ignore(
            "DAX_COLUMNS_FULLY_QUALIFIED on measure sales.margin: a SUMX row context"
        )
        assert (item.rule_id, item.kind, item.target) == (
            "DAX_COLUMNS_FULLY_QUALIFIED",
            "measure",
            "sales.margin",
        )
        assert item.reason == "a SUMX row context"

    def test_a_relationship_target_keeps_its_arrow(self):
        item = parse_bpa_ignore(
            "CHECK_IF_BI-DIRECTIONAL_AND_MANY-TO-MANY_RELATIONSHIPS_ARE_VALID on relationship "
            "bridge_x.a_sk -> dim_a.a_sk: reviewed with finance"
        )
        assert item.target == "bridge_x.a_sk -> dim_a.a_sk"

    def test_a_model_exception_takes_no_target(self):
        item = parse_bpa_ignore(
            "AVOID_EXCESSIVE_BI-DIRECTIONAL_OR_MANY-TO-MANY_RELATIONSHIPS on model: one bridge"
        )
        assert (item.kind, item.target) == ("model", "")

    @pytest.mark.parametrize(
        ("value", "code"),
        [
            ("DAX_COLUMNS_FULLY_QUALIFIED on measure sales.margin", "gold.bpa-ignore-malformed"),
            ("DAX_COLUMNS_FULLY_QUALIFIED on measure sales.margin:   ", "gold.bpa-ignore-malformed"),
            ("NOT_A_RULE on measure sales.margin: because", "gold.bpa-unknown-rule"),
            ("DAX_COLUMNS_FULLY_QUALIFIED on column t.c: because", "gold.bpa-ignore-wrong-scope"),
            ("DAX_COLUMNS_FULLY_QUALIFIED on measure: because", "gold.bpa-ignore-malformed"),
            (
                "AVOID_EXCESSIVE_BI-DIRECTIONAL_OR_MANY-TO-MANY_RELATIONSHIPS on model x: y",
                "gold.bpa-ignore-malformed",
            ),
        ],
    )
    def test_malformed_or_unknown_values_fail_closed(self, value, code):
        with pytest.raises(BpaIgnoreError) as excinfo:
            parse_bpa_ignore(value)
        assert excinfo.value.code == code

    def test_the_annotation_is_sorted_json(self):
        assert ignore_annotation(("B_RULE", "A_RULE", "B_RULE"), indent="\t") == [
            '\tannotation BestPracticeAnalyzer_IgnoreRules = {"RuleIDs":["A_RULE","B_RULE"]}'
        ]
        assert ignore_annotation((), indent="\t") == []


def _member(*values: str):
    return SimpleNamespace(
        policy=SimpleNamespace(
            gold=SimpleNamespace(bpa_ignore_rules=values, ontology_uri="urn:test")
        )
    )


def _table(name: str, *columns: str):
    return SimpleNamespace(
        name=name, columns=tuple(SimpleNamespace(name=column) for column in columns)
    )


class TestResolveIgnores:
    _tables = (_table("fact_sale", "amount", "customer_sk"), _table("dim_customer", "customer_sk"))
    _measures = (SimpleNamespace(measure_id="sales.total", emitted=True),)
    _relationships = (
        GoldRelationshipSpec(
            name="customer",
            source_table="fact_sale",
            source_column="customer_sk",
            target_table="dim_customer",
            target_column="customer_sk",
            cardinality="many-to-one",
            version_binding=None,
        ),
    )

    def _resolve(self, *values: str, defer: bool = False, has_calendar: bool = False):
        return _shape_bpa_ignores(
            (_member(*values),),
            self._tables,
            self._measures,
            self._relationships,
            has_calendar=has_calendar,
            defer=defer,
        )

    def test_targets_resolve_to_emitted_spelling(self):
        resolved = self._resolve(
            "AVOID_FLOATING_POINT_DATA_TYPES on column FACT_SALE.Amount: source is IEEE",
            "OBJECTS_WITH_NO_DESCRIPTION on measure SALES.TOTAL: self-explanatory",
            "HIDE_FOREIGN_KEYS on column fact_sale.customer_sk: shown for audit",
            "CHECK_IF_BI-DIRECTIONAL_AND_MANY-TO-MANY_RELATIONSHIPS_ARE_VALID on relationship "
            "fact_sale.customer_sk -> dim_customer.customer_sk: checked",
        )
        assert {(item.kind, item.target) for item in resolved} == {
            ("column", "fact_sale.amount"),
            ("measure", "sales.total"),
            ("column", "fact_sale.customer_sk"),
            ("relationship", "fact_sale.customer_sk -> dim_customer.customer_sk"),
        }

    def test_an_unknown_target_fails_at_product_level(self):
        with pytest.raises(GoldContractError) as excinfo:
            self._resolve("OBJECTS_WITH_NO_DESCRIPTION on measure sales.nope: x")
        assert excinfo.value.code == "gold.bpa-ignore-unknown-target"

    def test_an_unknown_target_is_deferred_on_a_single_domain_compile(self):
        """Another domain of the product may own it, exactly as for a bridge (#763)."""
        assert self._resolve("OBJECTS_WITH_NO_DESCRIPTION on table dim_other: x", defer=True) == ()

    def test_a_calendar_column_is_a_valid_target_only_with_a_calendar(self):
        value = "MONTH_(AS_A_STRING)_MUST_BE_SORTED on column dim_date.month_name: x"
        assert self._resolve(value, has_calendar=True)[0].target == "dim_date.month_name"
        with pytest.raises(GoldContractError):
            self._resolve(value)

    def test_a_parse_failure_keeps_its_code(self):
        with pytest.raises(GoldContractError) as excinfo:
            self._resolve("NOT_A_RULE on model: x")
        assert excinfo.value.code == "gold.bpa-unknown-rule"


class TestEmission:
    """End to end over the acme scenario: authored in TTL, emitted in TMDL."""

    _EXCEPTIONS = (
        '\n<https://acme.example/ontology/invoice> kairos-ext:bpaIgnoreRule '
        '"OBJECTS_WITH_NO_DESCRIPTION on measure invoice.total-amount: defined in the glossary" , '
        '"AVOID_EXCESSIVE_BI-DIRECTIONAL_OR_MANY-TO-MANY_RELATIONSHIPS on model: reviewed" , '
        '"ENSURE_TABLES_HAVE_RELATIONSHIPS on table fact_invoice: standalone by design" .\n'
    )

    @pytest.fixture(scope="class")
    @classmethod
    def artifacts(cls, tmp_path_factory):
        path = harness._write_gold(
            tmp_path_factory.mktemp("bpa"), "invoice", harness._gold_text("invoice") + cls._EXCEPTIONS
        )
        return harness._generate("invoice", gold_path=path)

    @staticmethod
    def _file(artifacts, suffix):
        return next(content for path, content in artifacts.items() if path.endswith(suffix))

    def test_each_object_carries_its_annotation(self, artifacts):
        model = self._file(artifacts, "/definition/model.tmdl")
        assert (
            'annotation BestPracticeAnalyzer_IgnoreRules = '
            '{"RuleIDs":["AVOID_EXCESSIVE_BI-DIRECTIONAL_OR_MANY-TO-MANY_RELATIONSHIPS"]}'
        ) in model
        fact = self._file(artifacts, "/tables/fact_invoice.tmdl")
        assert '\tannotation BestPracticeAnalyzer_IgnoreRules = {"RuleIDs":["ENSURE_TABLES_HAVE_RELATIONSHIPS"]}' in fact
        assert '\t\tannotation BestPracticeAnalyzer_IgnoreRules = {"RuleIDs":["OBJECTS_WITH_NO_DESCRIPTION"]}' in fact

    def test_the_report_lists_each_exception_with_its_reason(self, artifacts):
        report = harness._report(artifacts, "invoice")
        assert {item["rule"]: item["reason"] for item in report["bpa_exceptions"]} == {
            "OBJECTS_WITH_NO_DESCRIPTION": "defined in the glossary",
            "AVOID_EXCESSIVE_BI-DIRECTIONAL_OR_MANY-TO-MANY_RELATIONSHIPS": "reviewed",
            "ENSURE_TABLES_HAVE_RELATIONSHIPS": "standalone by design",
        }

    def test_a_hub_with_no_exceptions_keeps_its_bytes(self, invoice_gold):
        assert all("BestPracticeAnalyzer_IgnoreRules" not in content for content in invoice_gold.values())
        assert "bpa_exceptions" not in harness._report(invoice_gold, "invoice")


@pytest.fixture(scope="module")
def invoice_gold():
    return harness._generate("invoice")


def test_the_provenance_sidecar_can_record_the_profile():
    from kairos_ontology.core.compiler.provenance import build_provenance_document
    from tests.test_compile_provenance import _scope

    document = json.loads(
        build_provenance_document(_scope(), extra={"bpaProfile": bpa_profile.profile_stamp()})
    )
    assert document["bpaProfile"] == {
        "version": bpa_profile.PROFILE_VERSION,
        "upstreamCommit": bpa_profile.UPSTREAM_COMMIT,
    }
    assert "bpaProfile" not in json.loads(build_provenance_document(_scope()))
