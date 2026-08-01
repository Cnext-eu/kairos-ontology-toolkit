# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the DD-115 DataQualityRule graph reader (`_data_quality_rules`)."""

from __future__ import annotations

import pytest
from rdflib import Graph

from kairos_ontology.core.projections.dbt.policy_bind import (
    EXT,
    DataQualityRuleBindingError,
    _data_quality_rules,
)

CLIENT = "https://acme.example/ontology/client#Client"
ORDER = "https://acme.example/ontology/client#Order"

_BASE = """
@prefix acme: <https://acme.example/ontology/client#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .

acme:Client a owl:Class ; kairos-ext:dataQualityRule acme:Rule .
acme:Order a owl:Class .

acme:Rule a kairos-ext:DataQualityRule ;
    kairos-ext:dqRuleId "client.timeline-order" ;
    kairos-ext:dqRuleVersion "1" ;
    kairos-ext:dqCategory "business" ;
    kairos-ext:dqScope acme:Client ;
    kairos-ext:dqCheckType "cross-field" ;
    kairos-ext:dqCheckExpression "left=created_at;operator=lte;right=last_modified_at" ;
    kairos-ext:dqSeverity "error" ;
    kairos-ext:dqTolerance "0" ;
    kairos-ext:dqAction "quarantine" ;
    kairos-ext:dqOwnerRole "Domain Data Owner" ;
    kairos-ext:dqEvidence "client lifecycle policy" ;
    kairos-ext:dqTestRef "kairos.dq.cross-field.v1" .
"""


def _graph(turtle: str) -> Graph:
    graph = Graph()
    graph.parse(data=turtle, format="turtle")
    return graph


def test_reads_governed_rule() -> None:
    rules = _data_quality_rules(_graph(_BASE), EXT, frozenset({CLIENT}))
    assert len(rules) == 1
    rule = rules[0]
    assert rule.governing_entity_uri == CLIENT
    assert rule.rule_id.values == ("client.timeline-order",)
    assert rule.check_kind.values == ("cross-field",)
    # dqTestRef is read unchanged (never synthesized).
    assert rule.test_refs.values == ("kairos.dq.cross-field.v1",)


def test_skips_rule_governed_by_out_of_scope_entity() -> None:
    rules = _data_quality_rules(_graph(_BASE), EXT, frozenset({ORDER}))
    assert rules == ()


def test_rejects_multiple_governing_entities() -> None:
    turtle = _BASE + "\nacme:Order kairos-ext:dataQualityRule acme:Rule .\n"
    with pytest.raises(DataQualityRuleBindingError) as excinfo:
        _data_quality_rules(_graph(turtle), EXT, frozenset({CLIENT, ORDER}))
    assert "multiple entities" in str(excinfo.value)


def test_missing_required_slot_yields_empty_values() -> None:
    # The reader is not the fail-closed authority: a missing slot produces an empty-values
    # fact that the normalizer later rejects. The reader itself must not raise here.
    turtle = _BASE.replace(
        '    kairos-ext:dqTestRef "kairos.dq.cross-field.v1" .', "    ."
    )
    rules = _data_quality_rules(_graph(turtle), EXT, frozenset({CLIENT}))
    assert len(rules) == 1
    assert rules[0].test_refs.values == ()


def test_none_scope_reads_all_governed_rules() -> None:
    rules = _data_quality_rules(_graph(_BASE), EXT, None)
    assert len(rules) == 1
    assert rules[0].governing_entity_uri == CLIENT
