# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the shared sample-exposure & PII-masking policy (DD-075)."""

import pytest

from kairos_ontology.core._samples import (
    PII_KEYWORDS,
    SamplePrivacyError,
    assert_no_unredacted_sample_pii,
    detect_sample_pii_kind,
    example_values,
    find_unredacted_sample_pii,
    is_pii_column,
    is_redaction_token,
    mask_value,
    redact_sample_rows,
    redact_sample_value,
    redaction_token,
    value_is_pii_shaped,
)


class TestPiiColumnDetection:
    def test_name_keyword_match(self):
        assert is_pii_column("customer_email")
        assert is_pii_column("EmailAddress")  # camelCase normalised
        assert is_pii_column("national_id")

    def test_non_pii_name(self):
        assert not is_pii_column("order_total")
        assert not is_pii_column("status_code")

    def test_target_property_keyword(self):
        assert is_pii_column("col1", target_property="phone")
        assert is_pii_column("col1", target_label="Home Address")

    def test_gdpr_protected_flag(self):
        assert is_pii_column("anything", gdpr_protected=True)

    def test_value_shape_promotes_to_pii(self):
        assert is_pii_column("contact", sample_values=["jane@acme.com"])
        assert not is_pii_column("contact", sample_values=["active", "closed"])


class TestValueShape:
    def test_email(self):
        assert value_is_pii_shaped("john.doe@acme.com")

    def test_iban(self):
        assert value_is_pii_shaped("BE68539007547034")

    def test_phone(self):
        assert value_is_pii_shaped("+32 470 12 34 56")

    def test_long_id(self):
        assert value_is_pii_shaped("1234567890123")

    def test_plain_text_not_pii(self):
        assert not value_is_pii_shaped("active")
        assert not value_is_pii_shaped("42")
        assert not value_is_pii_shaped("2026-07-18")
        assert detect_sample_pii_kind("event_date", "Occurs on 2026-07-18") is None


class TestMasking:
    def test_email_masked(self):
        masked = mask_value("john.doe@acme.com")
        assert masked == "jo***@***.com"
        assert "john.doe" not in masked

    def test_iban_masked_keeps_last_two(self):
        masked = mask_value("BE68539007547034")
        assert masked.endswith("34")
        assert masked.startswith("*")
        assert "539007" not in masked

    def test_generic_pii_masked(self):
        assert mask_value("Johnson") == "J***"

    def test_empty(self):
        assert mask_value("") == ""


class TestExampleValues:
    def test_non_pii_raw(self):
        out = example_values(["active", "closed", "pending"], is_pii=False)
        assert out == ["active", "closed", "pending"]

    def test_pii_masked(self):
        out = example_values(["a@b.com", "c@d.org"], is_pii=True)
        assert all("@" in v and "***" in v for v in out)
        assert "a@b.com" not in out

    def test_typed_redaction_token_is_preserved(self):
        token = "<redacted kind=email source=contacts.email datatype=varchar(255)>"
        assert example_values([token], is_pii=True) == [token]

    def test_include_false_returns_empty(self):
        assert example_values(["x", "y"], is_pii=False, include=False) == []

    def test_caps_count(self):
        out = example_values([str(i) for i in range(10)], is_pii=False, max_count=3)
        assert len(out) == 3

    def test_dedup(self):
        out = example_values(["x", "x", "y"], is_pii=False)
        assert out == ["x", "y"]

    def test_empty_samples(self):
        assert example_values([], is_pii=False) == []
        assert example_values(None, is_pii=True) == []


def test_pii_keywords_are_shared_with_validator():
    from kairos_ontology.core import validator

    assert validator.PII_KEYWORDS is PII_KEYWORDS


class TestPersistenceRedaction:
    def test_token_retains_only_source_context(self):
        token = redaction_token(
            kind="email",
            table="contacts",
            column="email",
            data_type="varchar(255)",
        )
        assert token == (
            "<redacted kind=email source=contacts.email datatype=varchar(255)>"
        )
        assert is_redaction_token(token)

    def test_redacts_complete_free_text_cell_with_embedded_email(self):
        value = "Please contact Jane at jane.doe@example.com about invoice 42"
        redacted, finding = redact_sample_value(
            value,
            table="comments",
            column="body",
            data_type="text",
        )
        assert redacted == (
            "<redacted kind=email source=comments.body datatype=text>"
        )
        assert finding is not None and finding.kind == "email"
        assert "Jane" not in redacted
        assert "example.com" not in redacted

    def test_column_name_redacts_non_shaped_value(self):
        redacted, finding = redact_sample_value(
            "Jane Doe",
            table="contacts",
            column="first_name",
            data_type="nvarchar(100)",
        )
        assert redacted == (
            "<redacted kind=name source=contacts.first_name datatype=nvarchar(100)>"
        )
        assert finding is not None

    def test_nested_pii_redacts_complete_cell(self):
        redacted, finding = redact_sample_value(
            {"status": "open", "owner_email": "owner@example.com"},
            table="events",
            column="payload",
            data_type="json",
        )
        assert redacted == (
            "<redacted kind=email source=events.payload datatype=json>"
        )
        assert finding is not None

    def test_non_pii_value_is_preserved(self):
        value, finding = redact_sample_value(
            "active",
            table="orders",
            column="status",
            data_type="varchar(20)",
        )
        assert value == "active"
        assert finding is None

    def test_redaction_is_idempotent(self):
        token = (
            "<redacted kind=email source=contacts.email datatype=varchar(255)>"
        )
        value, finding = redact_sample_value(
            token,
            table="contacts",
            column="email",
            data_type="varchar(255)",
        )
        assert value == token
        assert finding is None

    def test_rows_use_declared_column_types(self):
        rows, findings = redact_sample_rows(
            [{"email": "person@example.com", "status": "active"}],
            table="contacts",
            column_types={"email": "varchar(255)", "status": "varchar(20)"},
        )
        assert rows == [
            {
                "email": (
                    "<redacted kind=email source=contacts.email "
                    "datatype=varchar(255)>"
                ),
                "status": "active",
            }
        ]
        assert len(findings) == 1

    def test_residual_gate_reports_location_without_value(self):
        rows = [{"body": "email person@example.com"}]
        findings = find_unredacted_sample_pii(rows, table="comments")
        assert findings[0].table == "comments"
        assert findings[0].column == "body"
        with pytest.raises(SamplePrivacyError) as exc:
            assert_no_unredacted_sample_pii(rows, table="comments")
        assert "comments.body:email" in str(exc.value)
        assert "person@example.com" not in str(exc.value)

    def test_detects_embedded_phone_and_identifier(self):
        assert detect_sample_pii_kind("notes", "Call +32 470 12 34 56") == "phone"
        assert detect_sample_pii_kind("notes", "Reference 1234567890123") == "identifier"
