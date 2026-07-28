# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for conservative token-aware sample PII column detection."""

import pytest

from kairos_ontology.core._samples import detect_sample_pii_kind, redact_sample_value


@pytest.mark.parametrize(
    ("column", "expected_kind"),
    [
        ("DriverDescription", "name"),
        ("DriverNo", "identifier"),
        ("DriverId", "identifier"),
        ("contact_name", "name"),
        ("DebtorFirstName", "name"),
    ],
)
def test_person_and_driver_column_tokens_are_redactable(column: str, expected_kind: str):
    assert detect_sample_pii_kind(column, "Dominik") == expected_kind


def test_name_column_is_redactable_with_contact_context():
    redacted, finding = redact_sample_value(
        "Dominik",
        table="contacts",
        column="name",
        data_type="nvarchar(100)",
    )

    assert redacted == "<redacted kind=name source=contacts.name datatype=nvarchar(100)>"
    assert finding is not None
    assert finding.kind == "name"


@pytest.mark.parametrize(
    "column",
    [
        "HaulierCode",
        "CompanyName",
        "VesselName",
        "ProductName",
        "CustomerAccount",
        "carrier_code",
    ],
)
def test_organizational_and_asset_column_tokens_are_not_redactable(column: str):
    assert detect_sample_pii_kind(column, "Acme") is None


def test_company_name_column_is_not_redactable_from_table_context():
    value, finding = redact_sample_value(
        "Acme",
        table="company",
        column="name",
        data_type="nvarchar(100)",
    )

    assert value == "Acme"
    assert finding is None
