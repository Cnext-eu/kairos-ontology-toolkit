# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""fit-report counts an object property a binding realizes through relationships: (#1070).

Before #1070 ``_binding_evidence`` read ``fields:`` only. An object property can never be
there (``binding.object-property-in-fields``), so every relationship a binding realized was
still reported unpopulated, and fit-report could not tell "the grammar cannot express it"
from "a relationship already covers it".
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.fit_report import run_fit_report
from tests.test_fit_report import _BINDING, _ONTOLOGY, _write_binding

_OBJECT_PROPERTIES = """
party:Address a owl:Class ; rdfs:label "Address" .
party:hasAddress a owl:ObjectProperty ;
  rdfs:domain party:Organisation ; rdfs:range party:Address .
party:hasParent a owl:ObjectProperty ;
  rdfs:domain party:Organisation ; rdfs:range party:Organisation .
"""

_RELATIONSHIP = """
relationships:
  - property: party:hasAddress
    target: party:Address
    join: [{ local: address_id, foreign: address_id }]
    cardinality: many-to-one
    mode: non-temporal
    missingParent: error
    ambiguousParent: error
"""


def _hub(tmp_path: Path, *, with_relationship: bool) -> tuple[Path, Path]:
    ontology_path = tmp_path / "party.ttl"
    ontology_path.write_text(_ONTOLOGY + "\n" + _OBJECT_PROPERTIES, encoding="utf-8")
    text = _BINDING + ("\n" + textwrap.dedent(_RELATIONSHIP).strip() if with_relationship else "")
    return ontology_path, _write_binding(tmp_path / "bindings", "organisation", text)


def test_a_realized_relationship_counts_as_populated(tmp_path: Path) -> None:
    ontology_path, binding_path = _hub(tmp_path, with_relationship=True)
    result = run_fit_report(ontology_path, "party:Organisation", binding_path=binding_path)
    populated = {item.name: item.source for item in result.populated}
    assert populated["hasAddress"] == "relationship -> party:Address on address_id"
    unpopulated = {item.name: item.property_type for item in result.unpopulated}
    assert "hasAddress" not in unpopulated
    # An object property no relationship realizes is still reported, typed as one.
    assert unpopulated["hasParent"] == "object"


def test_without_a_relationship_the_object_property_stays_unpopulated(tmp_path: Path) -> None:
    ontology_path, binding_path = _hub(tmp_path, with_relationship=False)
    result = run_fit_report(ontology_path, "party:Organisation", binding_path=binding_path)
    unpopulated = {item.name for item in result.unpopulated}
    assert {"hasAddress", "hasParent"} <= unpopulated
    assert {item.name for item in result.populated} == {"tradePartyId", "partyName"}


def test_the_text_output_marks_object_properties(tmp_path: Path) -> None:
    ontology_path, binding_path = _hub(tmp_path, with_relationship=True)
    result = CliRunner().invoke(
        cli,
        [
            "fit-report", "--ontology", str(ontology_path), "--class", "party:Organisation",
            "--binding", str(binding_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "hasAddress [direct] ← relationship -> party:Address on address_id" in result.output
    assert "Unpopulated (3: 2 datatype, 1 object)" in result.output
    parent_line = next(line for line in result.output.splitlines() if "hasParent" in line)
    assert "{object: bind the range class and add a relationships: entry}" in parent_line
    datatype_line = next(line for line in result.output.splitlines() if "localFlag" in line)
    assert "{object" not in datatype_line


def test_json_carries_the_relationship_source(tmp_path: Path) -> None:
    ontology_path, binding_path = _hub(tmp_path, with_relationship=True)
    result = CliRunner().invoke(
        cli,
        [
            "fit-report", "--ontology", str(ontology_path), "--class", "party:Organisation",
            "--binding", str(binding_path), "--format", "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    by_name = {item["name"]: item for item in payload["populated"]}
    assert by_name["hasAddress"]["source"].startswith("relationship -> ")
