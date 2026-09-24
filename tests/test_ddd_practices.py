# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""DDD architecture practices (DD-240, issue #996): reported, never Silver (DD-091)."""

from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import Graph

from kairos_ontology.core import ddd
from kairos_ontology.core.ddd_practices import authored_exceptions, check_ddd_practices
from kairos_ontology.core.projections.ddd_context_projector import (
    ContextDomain,
    collect_context_model,
    generate_context_artifacts,
)
from kairos_ontology.practices.exceptions import PracticeExceptionError, parse_ddd_exception

_PREFIXES = """
@prefix ex: <https://example.test/ontology/shop#> .
@prefix ctx: <https://example.test/ddd/shop#> .
@prefix kairos-ddd: <https://kairos.cnext.eu/ddd#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
"""

_DOMAIN = (
    _PREFIXES
    + """
<https://example.test/ontology/shop> a owl:Ontology .
ex:Order a owl:Class . ex:OrderLine a owl:Class . ex:Customer a owl:Class .
ex:Invoice a owl:Class .
ex:placedBy a owl:ObjectProperty ; rdfs:domain ex:Order ; rdfs:range ex:Customer .
ex:bills a owl:ObjectProperty ; rdfs:domain ex:Invoice ; rdfs:range ex:OrderLine .
ex:lineOf a owl:ObjectProperty ; rdfs:domain ex:OrderLine ; rdfs:range ex:Order .
"""
)

_STRATEGIC = (
    _PREFIXES
    + """
ctx:Sales a kairos-ddd:BoundedContext ; rdfs:label "Sales" .
ctx:Party a kairos-ddd:BoundedContext ; rdfs:label "Party" .
"""
)

_OVERLAY = (
    _PREFIXES
    + """
<https://example.test/ddd/shop-overlay> a owl:Ontology {exceptions} .
ex:Order kairos-ddd:boundedContext ctx:Sales ;
    kairos-ddd:tacticalPattern kairos-ddd:AggregateRoot .
ex:OrderLine kairos-ddd:tacticalPattern kairos-ddd:AggregateMember ;
    kairos-ddd:aggregateRoot ex:Order .
ex:Invoice kairos-ddd:boundedContext ctx:Sales ;
    kairos-ddd:tacticalPattern kairos-ddd:AggregateRoot .
ex:Customer kairos-ddd:boundedContext ctx:Party .
"""
)


def _model(tmp_path: Path, exceptions: str = ""):
    strategic = tmp_path / ddd.STRATEGIC_FILE_NAME
    strategic.write_text(_STRATEGIC, encoding="utf-8")
    overlay = tmp_path / "shop-ddd-ext.ttl"
    overlay.write_text(_OVERLAY.format(exceptions=exceptions), encoding="utf-8")
    graph = Graph().parse(data=_DOMAIN, format="turtle")
    domain = ContextDomain(name="shop", graph=graph, overlay_path=overlay)
    return collect_context_model([domain], strategic), domain, strategic


def _codes(findings):
    return sorted((item.code, item.target.rsplit("#", 1)[-1]) for item in findings)


def test_the_three_rules_find_what_they_describe(tmp_path):
    model, _, _ = _model(tmp_path)
    findings, excused, unused = check_ddd_practices(model, [])
    assert _codes(findings) == [
        # Invoice (a separate aggregate) points at a line inside the Order aggregate.
        ("ddd.aggregate-reference-by-identity", "bills"),
        # Order (Sales) -> Customer (Party) with no context-map relationship.
        ("ddd.cross-context-relationship-on-map", "placedBy"),
    ]
    assert excused == [] and unused == []


def test_a_reference_inside_the_aggregate_is_fine(tmp_path):
    """lineOf goes from a member to its own root: not a finding."""
    model, _, _ = _model(tmp_path)
    findings, _, _ = check_ddd_practices(model, [])
    assert "lineOf" not in {item.target.rsplit("#", 1)[-1] for item in findings}


def test_a_mapped_relationship_is_clean(tmp_path):
    model, _, _ = _model(tmp_path)
    model.relationships.append((None, *sorted(model.contexts, key=str), None))
    findings, _, _ = check_ddd_practices(model, [])
    assert "ddd.cross-context-relationship-on-map" not in {item.code for item in findings}


def test_a_member_with_two_roots_and_an_untagged_root_are_reported(tmp_path):
    model, _, _ = _model(tmp_path)
    graph = model.graph
    graph.parse(
        data=_PREFIXES
        + "ex:OrderLine kairos-ddd:aggregateRoot ex:Invoice .\n"
        + "ex:Customer kairos-ddd:aggregateRoot ex:Party .\n",
        format="turtle",
    )
    findings, _, _ = check_ddd_practices(model, [])
    assert ("ddd.one-root-per-aggregate", "OrderLine") in _codes(findings)
    assert ("ddd.one-root-per-aggregate", "Party") in _codes(findings)


def test_an_exception_excuses_and_is_listed(tmp_path):
    exceptions = (
        '; kairos-ddd:practiceException "ddd.cross-context-relationship-on-map on property '
        'placedBy: the customer is read from the published party list"'
    )
    model, domain, strategic = _model(tmp_path, exceptions)
    parsed, errors = authored_exceptions(model.graph)
    assert errors == []
    findings, excused, unused = check_ddd_practices(model, parsed)
    assert [item.code for item in excused] == ["ddd.cross-context-relationship-on-map"]
    assert unused == []
    notes = generate_context_artifacts([domain], strategic_path=strategic)[
        "contexts/design-notes.md"
    ]
    assert "## Recorded exceptions" in notes
    assert "published party list" in notes
    assert "## Practice findings" in notes  # bills is still open


def test_an_exception_that_excuses_nothing_is_unused(tmp_path):
    exceptions = (
        '; kairos-ddd:practiceException "ddd.aggregate-reference-by-identity on property '
        'lineOf: stale"'
    )
    model, _, _ = _model(tmp_path, exceptions)
    parsed, _ = authored_exceptions(model.graph)
    _, _, unused = check_ddd_practices(model, parsed)
    assert [item.target for item in unused] == ["lineOf"]


def test_the_target_may_be_a_full_iri():
    item = parse_ddd_exception(
        "ddd.cross-context-relationship-on-map on property "
        "https://example.test/ontology/shop#placedBy: reason"
    )
    assert item.target == "https://example.test/ontology/shop#placedBy"
    assert item.matches(
        "ddd.cross-context-relationship-on-map",
        "property",
        "https://example.test/ontology/shop#placedBy",
    )


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("ddd.one-root-per-aggregate on class Order:", "ddd.practice-exception-malformed"),
        ("ddd.no-such-rule on class Order: why", "ddd.practice-exception-unknown-rule"),
        ("ddd.class-in-two-contexts on class Order: why", "ddd.practice-exception-not-excusable"),
        ("ddd.one-root-per-aggregate on property x: why", "ddd.practice-exception-wrong-object"),
    ],
)
def test_exceptions_fail_closed(text, code):
    with pytest.raises(PracticeExceptionError) as raised:
        parse_ddd_exception(text)
    assert raised.value.code == code


def test_validate_reports_findings_as_warnings_and_unused_exceptions_as_errors(tmp_path):
    extensions = tmp_path / "extensions"
    ontologies = tmp_path / "ontologies"
    extensions.mkdir()
    ontologies.mkdir()
    (ontologies / "shop.ttl").write_text(_DOMAIN, encoding="utf-8")
    (extensions / ddd.STRATEGIC_FILE_NAME).write_text(_STRATEGIC, encoding="utf-8")
    overlay = extensions / "shop-ddd-ext.ttl"
    overlay.write_text(_OVERLAY.format(exceptions=""), encoding="utf-8")
    diagnostics = ddd.audit_ddd_practices(
        [overlay], extensions / ddd.STRATEGIC_FILE_NAME, ontologies
    )
    assert {item.level for item in diagnostics} == {"warning"}

    overlay.write_text(
        _OVERLAY.format(
            exceptions='; kairos-ddd:practiceException "ddd.one-root-per-aggregate on class '
            'Order: stale"'
        ),
        encoding="utf-8",
    )
    diagnostics = ddd.audit_ddd_practices(
        [overlay], extensions / ddd.STRATEGIC_FILE_NAME, ontologies
    )
    assert [item.code for item in diagnostics if item.level == "error"] == [
        ddd.CODE_PRACTICE_EXCEPTION_UNUSED
    ]
