# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""`read_reference_terms` carries the class-to-property link it already had (#524).

The loader flattened classes and properties into one list and dropped the relationship
between them, so any caller needing "which properties does this class carry" had to
resolve the closure a second time. `build_class_catalog` did exactly that for #519's
anchor tie-break, costing ~13s on a 109-module hub, and `propose_alignment` independently
built its own indices for #517/#520 — the same relationship derived three times from two
loaders.

It is carried on `ReferenceTerm` now, which is where it was already known.
"""

from __future__ import annotations

from pathlib import Path

from kairos_ontology.core.anchor_tables import build_class_catalog
from kairos_ontology.core.class_anchoring import ReferenceTerm, read_reference_terms

from .test_class_anchoring import _write_reference_model


def test_a_class_term_carries_its_property_names(tmp_path: Path) -> None:
    classes = {
        term.name: term
        for term in read_reference_terms(_write_reference_model(tmp_path))
        if term.kind == "class"
    }
    assert classes, "fixture produced no classes; the test proves nothing"
    carrying = {name: term for name, term in classes.items() if term.property_names}
    assert carrying, "no class carried any property"
    # Sorted and deduplicated, so a caller can compare two copies of a name directly --
    # which is what #519's tie-break does.
    for term in carrying.values():
        assert list(term.property_names) == sorted(set(term.property_names))


def test_a_property_term_carries_none(tmp_path: Path) -> None:
    """The field is about what a *class* carries; a property is not a container."""
    properties = [
        term
        for term in read_reference_terms(_write_reference_model(tmp_path))
        if term.kind == "property"
    ]
    assert properties
    assert all(term.property_names == () for term in properties)


def test_the_field_is_optional_for_direct_construction() -> None:
    """Callers and tests build `ReferenceTerm` positionally; a defaulted trailing field
    keeps every one of them working."""
    term = ReferenceTerm(
        uri="https://example.test/ref#Thing",
        name="Thing",
        label="Thing",
        comment="",
        module="ref",
        kind="class",
    )
    assert term.property_names == ()


def test_the_class_catalog_still_carries_per_copy_properties(tmp_path: Path) -> None:
    """The consumer #519 added. It used to come from a second full resolution of the
    closure; it now comes off the loader, and must be no worse."""
    catalog = build_class_catalog(_write_reference_model(tmp_path), None, None)
    copies = [copy for group in catalog.index.values() for copy in group]

    assert copies
    assert all("properties" in copy for copy in copies)
    assert any(copy["properties"] for copy in copies)


def test_the_catalog_and_the_loader_agree(tmp_path: Path) -> None:
    """One derivation, so the two cannot drift -- which is the point of the issue."""
    path = _write_reference_model(tmp_path)
    by_uri = {
        term.uri: set(term.property_names)
        for term in read_reference_terms(path)
        if term.kind == "class"
    }
    for group in build_class_catalog(path, None, None).index.values():
        for copy in group:
            assert set(copy["properties"]) == by_uri.get(copy["uri"], set()), copy["uri"]
