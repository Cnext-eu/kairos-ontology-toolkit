# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Fresh-hub scenario coverage for #280 — object properties and ``fields:``.

Two halves of one root cause, both exercised here end-to-end through
``compile_domain`` on a copy of the ``v5-hub`` acceptance fixture:

1. an ``owl:ObjectProperty`` authored under ``fields:`` must be **rejected**, never
   materialized as a scalar column holding the raw reference value (no surrogate key,
   no join, no orphan-detection window, no ERD edge); and
2. the same object property authored **correctly** under ``relationships:`` must
   compile even when its ``rdfs:range`` is absent or a class expression — the shape the
   reference-model ``deferred-relationship`` pattern prescribes.

Both are parametrized over the two independently-silent range shapes. ``ranges`` in the
DD-103 semantic index keeps only ``URIRef`` objects, so it is empty for a missing
``rdfs:range`` *and* for a blank-node class expression (``owl:unionOf`` /
``owl:Restriction`` / ``owl:oneOf``); a fix that special-cased only the first would leave
the second live.

``tests/scenarios/v5-hub`` itself already demonstrates the correct split and is never
modified in place — every case copies it and edits the copy.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from kairos_ontology.core.compiler import CompileMode, compile_domain

_HUB = Path(__file__).parent / "v5-hub"

_CUSTOMER_SQL = "models/silver/party/customer.sql"
_MODELS_YML = "models/silver/party/_party__models.yml"
_ERD = "docs/diagrams/party/party-erd.mmd"

# The declaration of the object property in the fixture ontology, verbatim.
_CLASS_RANGE = """party:country a owl:ObjectProperty ;
  rdfs:domain party:Customer ; rdfs:range party:Country .
"""

_SILENT_RANGE_SHAPES = {
    # No ``rdfs:range`` at all.
    "no-range": """party:country a owl:ObjectProperty ;
  rdfs:domain party:Customer .
""",
    # A blank-node class expression, which the semantic index never surfaces as a URIRef.
    "union-range": """party:country a owl:ObjectProperty ;
  rdfs:domain party:Customer ;
  rdfs:range [ owl:unionOf ( party:Country party:Customer ) ] .
""",
}


# ``owl:Thing`` is NOT a silent shape: it is a resolvable named range, so the compiler's
# guard sees it and rejects it. Kept next to the silent shapes because the whole point is
# that the two behave oppositely.
_OWL_THING_RANGE = """party:country a owl:ObjectProperty ;
  rdfs:domain party:Customer ; rdfs:range owl:Thing .
"""


def _hub_with_range_declaration(tmp_path: Path, name: str, declaration: str) -> Path:
    """Copy the v5 acceptance hub, rewriting ``party:country``'s declared range."""
    hub = tmp_path / name
    shutil.copytree(_HUB, hub)
    (hub / "kairos.yaml").write_text("adapter: fabric\n", encoding="utf-8")
    ontology = hub / "model" / "ontologies" / "party.ttl"
    text = ontology.read_text(encoding="utf-8")
    assert _CLASS_RANGE in text, (
        "v5-hub no longer declares party:country as expected; this fixture edit is stale"
    )
    ontology.write_text(text.replace(_CLASS_RANGE, declaration), "utf-8")
    return hub


def _hub_with_range_shape(tmp_path: Path, range_shape: str) -> Path:
    return _hub_with_range_declaration(tmp_path, range_shape, _SILENT_RANGE_SHAPES[range_shape])


def _author_object_property_under_fields(hub: Path) -> None:
    """Rewrite the customer binding into the buggy shape: ``party:country`` in ``fields:``."""
    path = hub / "integration" / "bindings" / "customer.binding.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document.pop("relationships")
    document["fields"].append({"property": "party:country", "expression": "country_code"})
    # The referential check exists for the relationship that this shape deletes.
    document["quality"] = [item for item in document["quality"] if item["kind"] != "referential"]
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _customer_columns(artifacts: dict[str, str]) -> dict[str, str]:
    """Return ``column name -> silver_role`` for the emitted customer model contract."""
    document = artifacts.get(_MODELS_YML)
    if document is None:
        return {}
    schema = yaml.safe_load(document)
    customer = next((item for item in schema["models"] if item["name"] == "customer"), None)
    if customer is None:
        return {}
    return {
        column["name"]: column.get("meta", {}).get("silver_role", "")
        for column in customer["columns"]
    }


def _rendered(result) -> str:
    """Everything an author would inspect, for a regression message that explains itself."""
    artifacts = result.artifact_dict()
    return "\n\n".join(
        f"--- {path} ---\n{artifacts[path]}"
        for path in (_CUSTOMER_SQL, _MODELS_YML, _ERD)
        if path in artifacts
    )


@pytest.mark.parametrize("range_shape", sorted(_SILENT_RANGE_SHAPES))
def test_object_property_in_fields_is_rejected(tmp_path, range_shape):
    hub = _hub_with_range_shape(tmp_path, range_shape)
    _author_object_property_under_fields(hub)

    result = compile_domain(hub, "party", CompileMode.EMIT)

    codes = {item.code for item in result.diagnostics.items}
    rendered = [item.render() for item in result.diagnostics.items]
    assert not result.succeeded, (
        f"compile passed with an object property in fields:\n{_rendered(result)}"
    )
    assert "safety.relationship-endpoint" in codes, rendered
    message = next(
        item.message
        for item in result.diagnostics.items
        if item.code.endswith("relationship-endpoint")
    )
    # Actionable in both directions (DD-133 §7 / DD-139).
    assert "party:country" in message
    assert "relationships:" in message
    assert "technicalFields:" in message
    _assert_remediation_names_only_real_schema_keys(message)


def _assert_remediation_names_only_real_schema_keys(message: str) -> None:
    """Every ``key:`` the remediation names must exist in the binding schema.

    The first version of this message said "with an on: clause". There is no ``on``
    key — the schema requires ``join`` — and ``additionalProperties`` is false, so
    following the advice failed. Worse, ``on`` is a YAML 1.1 boolean, so the author
    got ``Additional properties are not allowed (True was unexpected)``, naming no
    key at all. Asserting the wording alone would not have caught it; this checks
    the named keys against the shipped schema.
    """
    import json
    import re
    from pathlib import Path

    schema_path = (
        Path(__file__).resolve().parents[1].parent
        / "src"
        / "kairos_ontology"
        / "core"
        / "compiler"
        / "schema"
        / "entity-binding.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    definitions = schema.get("definitions", {})

    known: set[str] = set(schema.get("properties", {}))
    for definition in definitions.values():
        known |= set(definition.get("properties", {}))
        for branch in definition.get("oneOf", []) or []:
            known |= set(branch.get("properties", {}))

    # A key mentioned in prose is followed by whitespace ("join: clause"). A CURIE is
    # not ("party:country"), so the lookahead keeps prefixed names out of the set.
    named = set(re.findall(r"\b([a-zA-Z][a-zA-Z]*):(?=\s|$)", message))

    unknown = {key for key in named if key not in known}
    assert not unknown, (
        f"remediation names schema key(s) that do not exist: {sorted(unknown)}; "
        f"schema accepts {sorted(known)}"
    )


@pytest.mark.parametrize("range_shape", sorted(_SILENT_RANGE_SHAPES))
def test_object_property_in_fields_never_emits_a_scalar_column(tmp_path, range_shape):
    """The load-bearing assertion: on the rendered artifact, not on a diagnostic.

    A diagnostic-only test would also be satisfied by a mere warning, which is the wrong
    resolution — the emitted artifact is what is broken.
    """
    hub = _hub_with_range_shape(tmp_path, range_shape)
    _author_object_property_under_fields(hub)

    result = compile_domain(hub, "party", CompileMode.EMIT)

    artifacts = result.artifact_dict()
    sql = artifacts.get(_CUSTOMER_SQL, "")
    assert "as country," not in sql.lower(), f"raw reference emitted as a scalar column:\n{sql}"
    assert '"country"' not in sql, f"'country' appears in the DD-110 column contract:\n{sql}"
    columns = _customer_columns(artifacts)
    assert "country" not in columns, (
        "the object property was classified as an ordinary silver column "
        f"(role {columns.get('country')!r}):\n{_rendered(result)}"
    )
    # …and nothing was smuggled in under the property's own URI either.
    assert "https://example.test/ontology/party#country" not in sql, sql


@pytest.mark.parametrize("range_shape", sorted(_SILENT_RANGE_SHAPES))
def test_range_less_object_property_is_authorable_as_a_relationship(tmp_path, range_shape):
    """The correct authoring must SUCCEED — otherwise the fix only moves the wall.

    ``v5-hub``'s customer binding already authors ``party:country`` under
    ``relationships:``; the only edit here is the ontology's range shape. Before #280 this
    compiled to ``safety.relationship-endpoint``, leaving an author with no legal way at all
    to express the relationship.
    """
    hub = _hub_with_range_shape(tmp_path, range_shape)

    result = compile_domain(hub, "party", CompileMode.EMIT)

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    artifacts = result.artifact_dict()
    sql = artifacts[_CUSTOMER_SQL]
    assert "left join {{ ref('country') }} as country" in sql.lower(), sql
    assert "[src].[country_code] = [country].[code]" in sql, sql
    assert "[country].[country_sk] as country_sk" in sql, sql
    assert "_match_count" in sql, f"orphan-detection window missing:\n{sql}"
    # The relationship is a foreign key in the contract, not a business attribute.
    columns = _customer_columns(artifacts)
    assert columns.get("country_sk") == "surrogate-join-key", columns
    assert columns.get("country_code") == "foreign-key", columns
    assert "country" not in columns, columns
    # …and the ERD still carries the edge.
    erd = artifacts[_ERD]
    assert "COUNTRY ||--o{ CUSTOMER" in erd, erd
    assert "https://example.test/ontology/party#country" in erd, erd


def test_owl_thing_range_is_worse_than_omitting_the_range(tmp_path):
    """Pins the asymmetry the ``property_range_owl_thing`` validator warning asserts.

    The compiler's relationship guard is ``prop.range_uri and prop.range_uri !=
    target_class.uri``. ``owl:Thing`` is a plain ``URIRef``, so the DD-103 semantic index
    surfaces it as a named range: the guard does *not* short-circuit and, since it can
    never equal the authored ``target:`` class, it always fails as
    ``safety.relationship-endpoint``. Omitting ``rdfs:range`` leaves ``range_uri`` empty,
    the guard short-circuits, and the identical binding compiles.

    Both halves are asserted in one test on purpose: either alone would still pass if the
    mechanism were something else, and the validator warning's message — which tells the
    author owl:Thing is *worse* than omission — would then be wrong.
    """
    omitted = compile_domain(
        _hub_with_range_declaration(tmp_path, "omitted", _SILENT_RANGE_SHAPES["no-range"]),
        "party",
        CompileMode.EMIT,
    )
    owl_thing = compile_domain(
        _hub_with_range_declaration(tmp_path, "owl-thing", _OWL_THING_RANGE),
        "party",
        CompileMode.EMIT,
    )

    omitted_codes = {item.code for item in omitted.diagnostics.items}
    owl_thing_codes = {item.code for item in owl_thing.diagnostics.items}

    assert "safety.relationship-endpoint" not in omitted_codes, [
        item.render() for item in omitted.diagnostics.items
    ]
    assert omitted.succeeded, [item.render() for item in omitted.diagnostics.items]

    assert "safety.relationship-endpoint" in owl_thing_codes, [
        item.render() for item in owl_thing.diagnostics.items
    ]
    assert not owl_thing.succeeded, (
        "rdfs:range owl:Thing compiled; the validator's property_range_owl_thing warning "
        f"now misstates the mechanism:\n{_rendered(owl_thing)}"
    )
    message = next(
        item.message
        for item in owl_thing.diagnostics.items
        if item.code == "safety.relationship-endpoint"
    )
    assert "party:country" in message
