# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the shared sample-exposure & PII-masking policy (DD-075)."""

from kairos_ontology._samples import (
    PII_KEYWORDS,
    example_values,
    is_pii_column,
    mask_value,
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
    from kairos_ontology import validator

    assert validator.PII_KEYWORDS is PII_KEYWORDS
