# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""An overlay with no matching domain ontology is reported, not passed (#848).

`find_domain_ontology` returned `None` for a `*-ddd-ext.ttl` whose filename matches no
ontology, and `_load_domain_graph` turned that `None` into an **empty graph**. SHACL then
ran over `empty graph + overlay + vocabulary` and `run_ddd_validation` printed a green
tick.

So a typo in an overlay filename silently disabled validation for that overlay. The shapes
that would have caught it cannot fire: `AggregateRootTargetShape` confirms that a class
exists in the merged domain graph, and with an empty domain graph there is nothing to
confirm against.

Two behaviours followed, and the second is the more misleading of the two:

* a **strategic-only** overlay -- bounded contexts, context relationships -- passed
  completely clean, because nothing in it needs the domain graph;
* an overlay using `kairos-ddd:aggregateRoot` failed rule 4 with *"must point to an
  owl:Class present in the merged domain graph"*, which reads as a modelling error in the
  overlay when the real cause is that the file is orphaned. A maintainer chasing that
  message looks in entirely the wrong place.

Both are now one explicit failure naming the ontology that was looked for. SHACL is
deliberately skipped in that case rather than run against nothing, so the misleading
message is replaced rather than merely accompanied.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kairos_ontology.core import ddd

_ACME_HUB = Path(__file__).parent / "scenarios" / "acme-hub"
_ONTOLOGIES = _ACME_HUB / "model" / "ontologies"
_EXTENSIONS = _ACME_HUB / "model" / "extensions"

# Strategic-only: no class references, so nothing in it needs the domain graph. This is
# the overlay that passed completely clean before the fix.
_STRATEGIC = """@prefix acme-ddd: <https://acme.example/ddd/client#> .
@prefix kairos-ddd: <https://kairos.cnext.eu/ddd#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

acme-ddd:Sales a kairos-ddd:BoundedContext ;
    rdfs:label "Sales"@en .
"""


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    destination = tmp_path / "hub"
    shutil.copytree(_ACME_HUB, destination)
    return destination


def _dirs(hub: Path) -> tuple[Path, Path]:
    return hub / "model" / "extensions", hub / "model" / "ontologies"


class TestOrphanIsReported:
    def test_a_strategic_only_orphan_no_longer_passes(self, hub, capsys):
        """The silent case: nothing in this overlay needs the domain graph, so every
        check it ran genuinely passed -- against a graph that was not its domain."""
        extensions, ontologies = _dirs(hub)
        (extensions / "sales-ddd-ext.ttl").write_text(_STRATEGIC, encoding="utf-8")

        failures = ddd.run_ddd_validation(extensions, ontologies)

        assert failures == 1
        assert "sales-ddd-ext.ttl" in capsys.readouterr().out

    def test_the_message_names_the_ontology_it_looked_for(self, hub, capsys):
        """ "No matching domain ontology" is only actionable with the expected name."""
        extensions, ontologies = _dirs(hub)
        (extensions / "sales-ddd-ext.ttl").write_text(_STRATEGIC, encoding="utf-8")

        ddd.run_ddd_validation(extensions, ontologies)

        output = capsys.readouterr().out
        assert "sales.ttl" in output
        assert str(ontologies) in output

    def test_a_renamed_overlay_stops_reporting_a_modelling_error(self, hub, capsys):
        """The misleading case, reproduced exactly as the issue describes it: the overlay
        is unchanged and correct, and only its filename is wrong."""
        extensions, ontologies = _dirs(hub)
        (extensions / "client-ddd-ext.ttl").rename(extensions / "clint-ddd-ext.ttl")

        failures = ddd.run_ddd_validation(extensions, ontologies)

        output = capsys.readouterr().out
        assert failures == 1
        assert "clint.ttl" in output
        # The rule-4 message sent readers looking for a modelling error that is not there.
        assert "aggregateRoot must point to an owl:Class" not in output

    def test_the_result_carries_a_domain_section(self, hub):
        extensions, _ = _dirs(hub)
        overlay = extensions / "sales-ddd-ext.ttl"
        overlay.write_text(_STRATEGIC, encoding="utf-8")

        result = ddd.validate_ddd_overlay(overlay, None)

        assert not result["passed"]
        assert result["domain"] == {"passed": False, "expected": "sales.ttl"}
        # Not run, rather than run and passed: it would have run against an empty graph.
        assert result["shacl"]["passed"]

    def test_an_orphan_is_still_scanned_for_a_projection_leak(self, hub):
        """The leak scan reads the overlay alone, so it stays meaningful and is reported
        together with the orphan rather than deferred behind it."""
        extensions, _ = _dirs(hub)
        overlay = extensions / "sales-ddd-ext.ttl"
        overlay.write_text(
            _STRATEGIC + "acme-ddd:Sales <https://kairos.cnext.eu/ext#goldTableName> 'x' .\n",
            encoding="utf-8",
        )

        result = ddd.validate_ddd_overlay(overlay, None)

        assert not result["domain"]["passed"]
        assert result["ext_leak"]["predicates"] == ["kairos-ext:goldTableName"]

    def test_the_summary_no_longer_claims_an_orphan_was_validated(self, hub, capsys):
        extensions, ontologies = _dirs(hub)
        (extensions / "sales-ddd-ext.ttl").write_text(_STRATEGIC, encoding="utf-8")

        ddd.run_ddd_validation(extensions, ontologies)

        # The copied acme hub also carries the hub-wide strategic file (DD-229), which is
        # checked on its own and named in the summary rather than counted as an overlay.
        assert "Checked 3 DDD overlay(s) + strategic file, 1 failed" in capsys.readouterr().out


class TestMatchedOverlaysAreUnchanged:
    def test_the_shipped_overlays_still_pass(self, hub, capsys):
        extensions, ontologies = _dirs(hub)

        assert ddd.run_ddd_validation(extensions, ontologies) == 0
        assert "no domain ontology" not in capsys.readouterr().out

    def test_expected_domain_ontology_agrees_with_find(self):
        """The reporting helper must name exactly the path the lookup tried, or the
        message would send a reader to the wrong file."""
        overlay = _EXTENSIONS / "client-ddd-ext.ttl"
        assert ddd.expected_domain_ontology(overlay, _ONTOLOGIES) == ddd.find_domain_ontology(
            overlay, _ONTOLOGIES
        )

    def test_expected_domain_ontology_answers_even_when_nothing_is_there(self, tmp_path):
        overlay = tmp_path / "sales-ddd-ext.ttl"
        assert ddd.expected_domain_ontology(overlay, tmp_path).name == "sales.ttl"
        assert ddd.find_domain_ontology(overlay, tmp_path) is None
