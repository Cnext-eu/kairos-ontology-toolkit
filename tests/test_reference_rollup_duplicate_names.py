# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The reference rollup keys on the class URI, not its local name (#523).

Two imported modules may each declare a class with the same local name and different
property sets. Keying the rollup on the name collapsed them, so a property carried by only
one copy was reported as `hallucinated_properties` — a **false accusation of model error**,
which is close to the worst kind of bad signal: it directs review at a working mapping and
away from real defects. On the reported hub the finding was investigated as a strict-schema
gap before the duplicate name was found.

It also under-reported coverage, scoring a legitimately mapped column as unmapped.

Alignments name a class by its local name, so an ambiguous name is resolved the way the
aligner already resolves it — to whichever same-named class actually declares the property.
The two components previously disagreed about the same data: the aligner kept the pair,
the rollup called it hallucinated.
"""

from __future__ import annotations

from kairos_ontology.core.propose_alignment import (
    ColumnAlignment,
    DomainAlignment,
    TableAlignment,
    _build_reference_rollup,
)

# The reported shape: `tic/terminal-infrastructure#Terminal` carries `terminalName`,
# `tic/locations#Terminal` does not.
_REF_CLASSES = [
    {
        "name": "Terminal",
        "label": "Terminal",
        "module": "tic/terminal-infrastructure",
        "ref_class_id": "tic/terminal-infrastructure:Terminal",
        "source_uri": "https://example.test/tic/terminal-infrastructure#Terminal",
        "properties": [{"name": "terminalName"}, {"name": "terminalCode"}],
    },
    {
        "name": "Terminal",
        "label": "Terminal",
        "module": "tic/locations",
        "ref_class_id": "tic/locations:Terminal",
        "source_uri": "https://example.test/tic/locations#Terminal",
        "properties": [{"name": "latitude"}],
    },
    {
        "name": "Vessel",
        "label": "Vessel",
        "module": "imo/vessel-registry",
        "ref_class_id": "imo/vessel-registry:Vessel",
        "source_uri": "https://example.test/imo/vessel-registry#Vessel",
        "properties": [{"name": "imoNumber"}],
    },
]


def _alignment(*columns: ColumnAlignment, ref_class: str = "Terminal") -> DomainAlignment:
    return DomainAlignment(
        domain="terminal-operations",
        domain_uris=[],
        generated_at="2026-09-19T00:00:00Z",
        model_used="test",
        tables=[
            TableAlignment(
                system="tic",
                table="terminals",
                ref_class=ref_class,
                ref_class_confidence=0.9,
                columns=list(columns),
            )
        ],
    )


def _by_class(rollup: list[dict]) -> dict[str, dict]:
    return {entry["ref_class"]: entry for entry in rollup}


def _column(name: str, prop: str, ref_class: str = "Terminal") -> ColumnAlignment:
    return ColumnAlignment(
        column=name,
        data_type="varchar",
        ref_class=ref_class,
        ref_property=prop,
        alignment="exact",
        confidence=0.9,
    )


def test_same_named_classes_are_not_collapsed():
    rollup = _build_reference_rollup(_alignment(), _REF_CLASSES)
    assert len(rollup) == 3, [entry["ref_class"] for entry in rollup]


def test_an_ambiguous_name_is_qualified_by_module():
    """Merged before; qualified now, so a reader can tell the two apart."""
    classes = set(_by_class(_build_reference_rollup(_alignment(), _REF_CLASSES)))
    assert "tic/terminal-infrastructure:Terminal" in classes
    assert "tic/locations:Terminal" in classes
    # An unambiguous name stays bare -- qualifying everything would be noise.
    assert "Vessel" in classes


def test_a_property_carried_by_one_copy_is_not_a_hallucination():
    """The reported defect, exactly: `terminalName` is real and the mapping is correct."""
    rollup = _by_class(
        _build_reference_rollup(_alignment(_column("name", "terminalName")), _REF_CLASSES)
    )

    owner = rollup["tic/terminal-infrastructure:Terminal"]
    assert owner["matched_properties"] == 1
    assert "hallucinated_properties" not in owner

    # The copy that does not declare it is not accused either -- the property resolved.
    other = rollup["tic/locations:Terminal"]
    assert "hallucinated_properties" not in other
    assert other["matched_properties"] == 0


def test_coverage_is_no_longer_under_reported():
    rollup = _by_class(
        _build_reference_rollup(_alignment(_column("name", "terminalName")), _REF_CLASSES)
    )
    assert rollup["tic/terminal-infrastructure:Terminal"]["coverage_pct"] == 50.0


def test_a_property_that_exists_elsewhere_is_reported_as_foreign_not_invented():
    """The second half of the issue: "no such property anywhere" and "exists, but on
    another class" call for different responses, and only the first is a hallucination."""
    rollup = _by_class(
        _build_reference_rollup(
            _alignment(_column("imo", "imoNumber")), _REF_CLASSES
        )
    )
    terminal = rollup["tic/terminal-infrastructure:Terminal"]
    assert terminal.get("foreign_properties") == ["imoNumber"]
    assert "hallucinated_properties" not in terminal


def test_a_property_in_no_class_at_all_is_still_a_hallucination():
    """Splitting the signal must not soften it: an invented name is still called out."""
    rollup = _by_class(
        _build_reference_rollup(
            _alignment(_column("junk", "notAPropertyAnywhere")), _REF_CLASSES
        )
    )
    terminal = rollup["tic/terminal-infrastructure:Terminal"]
    assert terminal.get("hallucinated_properties") == ["notAPropertyAnywhere"]
    assert "foreign_properties" not in terminal


def test_the_rollup_is_deterministic():
    """Two same-named classes previously tied on coverage and sorted arbitrarily."""
    first = _build_reference_rollup(_alignment(), _REF_CLASSES)
    second = _build_reference_rollup(_alignment(), list(reversed(_REF_CLASSES)))
    assert [entry["ref_class"] for entry in first] == [
        entry["ref_class"] for entry in second
    ]


def test_an_ambiguous_anchor_is_credited_to_the_copy_its_columns_align_to():
    """`tic.terminals` anchored to the bare name `Terminal` was listed under both copies,
    and every custom column with it, so the hub-wide extension count doubled."""
    rollup = _build_reference_rollup(
        _alignment(_column("terminal_name", "terminalName")), _REF_CLASSES
    )
    by_class = _by_class(rollup)

    assert by_class["tic/terminal-infrastructure:Terminal"]["source_tables"] == ["tic.terminals"]
    assert by_class["tic/locations:Terminal"]["source_tables"] == []


def test_an_ambiguous_anchor_with_nothing_to_go_on_stays_ambiguous():
    """No aligned property points at either copy: naming both is the honest answer."""
    rollup = _build_reference_rollup(_alignment(), _REF_CLASSES)
    by_class = _by_class(rollup)

    assert by_class["tic/terminal-infrastructure:Terminal"]["source_tables"] == ["tic.terminals"]
    assert by_class["tic/locations:Terminal"]["source_tables"] == ["tic.terminals"]
