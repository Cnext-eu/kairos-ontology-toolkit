# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""SHACL enforcement of the DD-115 class-attached DataQualityRuleShape."""

from __future__ import annotations

from pathlib import Path

from pyshacl import validate as shacl_validate
from rdflib import Graph

_SHAPES = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "kairos_ontology"
    / "scaffold"
    / "kairos-ext-shapes.shacl.ttl"
)

_PREFIX = """@prefix party: <https://example.test/ontology/party#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
"""

_RULE_TEMPLATE = """
party:Customer kairos-ext:dataQualityRule party:Rule .

party:Rule a kairos-ext:DataQualityRule ;
    kairos-ext:dqRuleId "customer.country-distribution" ;
    kairos-ext:dqRuleVersion "1" ;
    kairos-ext:dqCategory "business" ;
    kairos-ext:dqScope party:Customer ;
    kairos-ext:dqCheckType "distribution" ;
    kairos-ext:dqCheckExpression "column=country_code;allowed=BE|NL" ;
    kairos-ext:dqSeverity "warning" ;
    kairos-ext:dqTolerance "0" ;
    kairos-ext:dqAction "warn" ;
    kairos-ext:dqOwnerRole "Domain Data Owner" ;
    kairos-ext:dqEvidence "distribution policy" ;
    kairos-ext:dqTestRef {test_ref} .
"""


def _validate(test_ref: str) -> bool:
    data = Graph().parse(data=_PREFIX + _RULE_TEMPLATE.format(test_ref=test_ref), format="turtle")
    shapes = Graph().parse(_SHAPES, format="turtle")
    conforms, _report_graph, _report_text = shacl_validate(
        data_graph=data, shacl_graph=shapes, inference="none"
    )
    return conforms


def test_valid_dq_rule_conforms_to_shape() -> None:
    assert _validate('"kairos.dq.distribution.v1"') is True


def test_unknown_test_reference_violates_shape() -> None:
    assert _validate('"kairos.dq.bogus.v1"') is False


def test_duplicate_test_reference_violates_max_count() -> None:
    assert _validate('"kairos.dq.distribution.v1" , "kairos.dq.range.v1"') is False
