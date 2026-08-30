# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""#625: relationship joins must resolve to the typed Silver foreign-key spec, never a
provenance-tagged column search -- the generated surrogate FK column and its
``_kairos_fk_*_match_count`` sibling both carry the exact same
``relationship:{property_uri}`` provenance tag on the same table, so a provenance search
can no longer disambiguate them once both exist (#619 Bug 12 regressed).
"""

from __future__ import annotations

import pytest

from kairos_ontology.core.projections.dbt.gold_shape import _relationship_column
from kairos_ontology.core.projections.dbt.gold_specs import (
    GoldColumnSpec,
    GoldContractError,
    GoldTableSpec,
)
from kairos_ontology.core.projections.dbt.policy_specs import CanonicalTypeKind, CanonicalTypeSpec, GoldTableRole
from kairos_ontology.core.projections.dbt.specs import SilverForeignKeySpec

_STRING = CanonicalTypeSpec(CanonicalTypeKind.STRING)
_PROPERTY_URI = "https://example.test/ontology/party#country"


def _column(name: str, provenance: tuple[str, ...]) -> GoldColumnSpec:
    return GoldColumnSpec(
        source_name=name,
        name=name,
        canonical_type=_STRING,
        nullable=False,
        role="foreign-key",
        comment="",
        provenance=provenance,
    )


def _table(columns: tuple[GoldColumnSpec, ...]) -> GoldTableSpec:
    return GoldTableSpec(
        resource_uri="https://example.test/ontology/party#Customer",
        name="customer",
        schema_name="gold",
        role=GoldTableRole.DIMENSION,
        source_model="customer",
        source_version="1.0.0",
        columns=columns,
        primary_key="customer_sk",
    )


def _fk(
    *,
    property_uri: str = _PROPERTY_URI,
    columns: tuple[str, ...] = ("country_sk",),
    referenced_columns: tuple[str, ...] = ("country_sk",),
    referenced_model: str = "country",
) -> SilverForeignKeySpec:
    return SilverForeignKeySpec(
        property_uri=property_uri,
        columns=columns,
        referenced_model=referenced_model,
        referenced_columns=referenced_columns,
        label="country",
        temporal_mode="none",
    )


def test_typed_foreign_key_spec_resolves_the_surrogate_column():
    """#625 regression: the exact real-world collision -- a generated surrogate FK
    column *and* a `_kairos_fk_*_match_count` column both tagged
    `relationship:{property_uri}` on the same table. The typed `SilverForeignKeySpec`
    (never populated with a match-count column by kernel.py) must be the sole
    authority, so the ambiguous provenance tag on the columns is irrelevant.
    """
    table = _table(
        (
            _column("country_sk", (f"relationship:{_PROPERTY_URI}", "rule:DD-133")),
            _column(
                "_kairos_fk_country_match_count",
                (f"relationship:{_PROPERTY_URI}", "rule:DD-109-temporal-fk"),
            ),
        )
    )

    assert (
        _relationship_column(table, _PROPERTY_URI, "", (_fk(),))
        == "country_sk"
    )


def test_falls_back_to_property_tagged_column_when_no_typed_foreign_key_exists():
    table = _table((_column("country_code", (f"property:{_PROPERTY_URI}",)),))

    assert _relationship_column(table, _PROPERTY_URI, "", ()) == "country_code"


def test_falls_back_to_explicit_override_when_no_typed_foreign_key_or_tag_exists():
    table = _table((_column("country_override", ()),))

    assert _relationship_column(table, _PROPERTY_URI, "country_override", ()) == "country_override"


def test_ambiguous_property_tagged_columns_still_fail_closed_without_a_typed_spec():
    table = _table(
        (
            _column("country_sk_a", (f"property:{_PROPERTY_URI}",)),
            _column("country_sk_b", (f"property:{_PROPERTY_URI}",)),
        )
    )

    assert _relationship_column(table, _PROPERTY_URI, "", ()) == ""


def test_multiple_typed_foreign_key_specs_for_the_same_property_fail_closed():
    table = _table((_column("country_sk", (f"relationship:{_PROPERTY_URI}",)),))

    with pytest.raises(GoldContractError, match="relationship-fk-ambiguous"):
        _relationship_column(table, _PROPERTY_URI, "", (_fk(), _fk()))


def test_composite_key_foreign_key_spec_fails_closed():
    table = _table(
        (
            _column("country_sk", (f"relationship:{_PROPERTY_URI}",)),
            _column("country_region_sk", (f"relationship:{_PROPERTY_URI}",)),
        )
    )
    composite = _fk(
        columns=("country_sk", "country_region_sk"),
        referenced_columns=("country_sk", "country_region_sk"),
    )

    with pytest.raises(GoldContractError, match="relationship-composite-key-unsupported"):
        _relationship_column(table, _PROPERTY_URI, "", (composite,))


def test_typed_foreign_key_spec_naming_an_unemitted_column_fails_closed():
    table = _table((_column("country_code", (f"property:{_PROPERTY_URI}",)),))
    dangling = _fk(columns=("country_sk",), referenced_columns=("country_sk",))

    with pytest.raises(GoldContractError, match="relationship-column-not-emitted"):
        _relationship_column(table, _PROPERTY_URI, "", (dangling,))
