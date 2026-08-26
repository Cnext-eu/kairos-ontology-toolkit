# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""#619 Bug 12: relationship joins must prefer the FK surrogate key over a same-property
natural-key column when both are materialized on the source table.
"""

from __future__ import annotations

from kairos_ontology.core.projections.dbt.gold_shape import _relationship_column
from kairos_ontology.core.projections.dbt.gold_specs import GoldColumnSpec, GoldTableSpec
from kairos_ontology.core.projections.dbt.policy_specs import CanonicalTypeKind, CanonicalTypeSpec, GoldTableRole

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


def test_prefers_relationship_tagged_surrogate_key_over_natural_key():
    table = _table(
        (
            _column("country_code", (f"property:{_PROPERTY_URI}",)),
            _column("country_sk", (f"relationship:{_PROPERTY_URI}", "rule:DD-133")),
        )
    )

    assert _relationship_column(table, _PROPERTY_URI, "") == "country_sk"


def test_falls_back_to_property_tagged_column_when_no_relationship_column_exists():
    table = _table((_column("country_code", (f"property:{_PROPERTY_URI}",)),))

    assert _relationship_column(table, _PROPERTY_URI, "") == "country_code"


def test_falls_back_to_explicit_override_when_no_tagged_column_exists():
    table = _table((_column("country_override", ()),))

    assert _relationship_column(table, _PROPERTY_URI, "country_override") == "country_override"


def test_ambiguous_relationship_tagged_columns_still_fail_closed():
    table = _table(
        (
            _column("country_sk_a", (f"relationship:{_PROPERTY_URI}",)),
            _column("country_sk_b", (f"relationship:{_PROPERTY_URI}",)),
        )
    )

    assert _relationship_column(table, _PROPERTY_URI, "") == ""
