# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the shared sample-exposure & PII-masking policy (DD-075)."""

import pytest

from kairos_ontology.core._samples import (
    DETECTED_PII_KINDS,
    PII_KEYWORDS,
    SAMPLE_PRIVACY_VERSION,
    SamplePrivacyError,
    _kind_from_text,
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
        assert token == ("<redacted kind=email source=contacts.email datatype=varchar(255)>")
        assert is_redaction_token(token)

    def test_redacts_complete_free_text_cell_with_embedded_email(self):
        value = "Please contact Jane at jane.doe@example.com about invoice 42"
        redacted, finding = redact_sample_value(
            value,
            table="comments",
            column="body",
            data_type="text",
        )
        assert redacted == ("<redacted kind=email source=comments.body datatype=text>")
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
        assert redacted == ("<redacted kind=email source=events.payload datatype=json>")
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
        token = "<redacted kind=email source=contacts.email datatype=varchar(255)>"
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
                "email": ("<redacted kind=email source=contacts.email datatype=varchar(255)>"),
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


class TestTimestampAndNumberExemptions:
    """Value shapes that cannot be PII must survive persistence (#302).

    Every assertion goes through a classifier or the redactor. Asserting
    ``_ISO_DATE_OR_DATETIME_RE.fullmatch(value)`` alone proves nothing: the whole
    defect was that the fullmatch succeeded on the complete value while the code
    only ever tested it against a truncated substring.
    """

    @pytest.mark.parametrize(
        "value",
        [
            "2026-07-29",
            "2026-07-29 14:19",
            "2026-07-29 14:19:00",
            "2026-07-29 14:19:00.123456",
            "2026-07-29 14:19:00+00:00",
            "2026-07-29T14:19:00",
            "2026-07-29T14:19:00Z",
        ],
    )
    def test_whole_value_timestamp_is_not_pii(self, value: str):
        # Space-separated forms were classified "phone": _EMBEDDED_PHONE_RE's
        # character class has no ":", so it matched only the "2026-07-29 14" prefix.
        assert _kind_from_text(value) is None
        assert detect_sample_pii_kind("created_at", value) is None

    @pytest.mark.parametrize(
        "value",
        ["1234-56-78", "0470-12-34", "9999-99-99 99:99", "2026-13-01"],
    )
    def test_timestamp_lookalikes_are_not_exempted(self, value: str):
        # The exemption is now a load-bearing whole-value gate, so digit groupings
        # that only resemble a date must not slip through it.
        assert _kind_from_text(value) == "phone"

    @pytest.mark.parametrize(
        "value",
        [
            "1234567.89",
            "12345.678",
            "-1234567.8",
            "0.123456789",
            "3.14159265358979",
            "1234.56",
            "12345678",
        ],
    )
    def test_plain_numbers_are_not_pii(self, value: str):
        assert _kind_from_text(value) is None
        assert detect_sample_pii_kind("amount", value) is None
        assert not value_is_pii_shaped(value)

    @pytest.mark.parametrize("value", ["123456789", "1234567890123", "0612345678"])
    def test_long_bare_digit_runs_remain_identifiers(self, value: str):
        # National registry numbers (BE INSZ, NL BSN, DK CPR) are 9-11 digits and
        # routinely live in numeric columns: the numeric exemption must not reach them.
        assert _kind_from_text(value) == "identifier"
        assert value_is_pii_shaped(value)

    def test_leading_zero_keeps_a_bare_phone_number_detected(self):
        assert _kind_from_text("06123456") == "phone"

    def test_datetime_column_value_survives_redaction(self):
        rows, findings = redact_sample_rows(
            [{"created_at": "2026-07-29 14:19:00"}],
            table="events",
            column_types={"created_at": "datetime"},
        )
        assert rows == [{"created_at": "2026-07-29 14:19:00"}]
        assert findings == []

    def test_long_decimal_survives_redaction(self):
        rows, findings = redact_sample_rows(
            [{"amount": "1234567.89"}],
            table="invoices",
            column_types={"amount": "decimal(18,4)"},
        )
        assert rows == [{"amount": "1234567.89"}]
        assert findings == []

    def test_redacted_rows_pass_the_persistence_gate(self):
        """The redactor and the datatype-blind gate must never disagree.

        ``assert_no_unredacted_sample_pii`` receives no ``column_types``, so any
        exemption keyed on the declared datatype would make the gate flag exactly
        what the redactor just left alone and abort persistence.
        """
        rows = [
            {
                "created_at": "2026-07-29 14:19:00",
                "amount": "1234567.89",
                "ratio": "0.123456789",
                "flag": "True",
                "email": "person@example.com",
                "note": "Call +32 470 12 34 56",
            }
        ]
        safe_rows, _ = redact_sample_rows(
            rows,
            table="events",
            column_types={
                "created_at": "datetime",
                "amount": "decimal(18,4)",
                "ratio": "decimal(18,9)",
                "flag": "bit",
                "email": "varchar(255)",
                "note": "varchar(max)",
            },
        )
        assert_no_unredacted_sample_pii(safe_rows, table="events")
        assert safe_rows[0]["created_at"] == "2026-07-29 14:19:00"
        assert safe_rows[0]["amount"] == "1234567.89"
        assert safe_rows[0]["ratio"] == "0.123456789"
        assert safe_rows[0]["flag"] == "True"
        assert is_redaction_token(safe_rows[0]["email"])
        assert is_redaction_token(safe_rows[0]["note"])


class TestExemptionsDoNotWeakenDetection:
    """Negative controls: everything here must STILL be redacted."""

    @pytest.mark.parametrize(
        ("value", "expected_kind"),
        [
            ("+32 470 12 34 56", "phone"),
            ("(02) 123 45 67", "phone"),
            ("jane.doe@acme.com", "email"),
            ("BE68 5390 0754 7034", "iban"),
            ("1234567890123", "identifier"),
            ("123456789", "identifier"),
        ],
    )
    def test_shaped_value_in_text_column_is_redacted(self, value: str, expected_kind: str):
        redacted, finding = redact_sample_value(
            value,
            table="contacts",
            column="detail",
            data_type="varchar(255)",
        )
        assert is_redaction_token(redacted)
        assert finding is not None and finding.kind == expected_kind

    @pytest.mark.parametrize(
        ("value", "expected_kind"),
        [
            ("2024-01-15 10:30 signed off by jane.doe@acme.com", "email"),
            ("2024-01-15 10:30 call +32 470 12 34 56", "phone"),
            ("Signed 2024-01-15 10:30, IBAN BE68539007547034", "iban"),
        ],
    )
    def test_free_text_beginning_with_a_timestamp_is_still_scanned(
        self, value: str, expected_kind: str
    ):
        # A leading timestamp must not exempt the rest of the cell: the value does
        # not fullmatch, so every detector still runs over it.
        assert _kind_from_text(value) == expected_kind

    @pytest.mark.parametrize("data_type", [None, "", "unknown", "some-future-type"])
    def test_unknown_datatype_is_still_scanned(self, data_type: str | None):
        redacted, finding = redact_sample_value(
            "jane.doe@acme.com",
            table="contacts",
            column="detail",
            data_type=data_type,
        )
        assert is_redaction_token(redacted)
        assert finding is not None and finding.kind == "email"

    @pytest.mark.parametrize(
        ("column", "data_type", "value", "expected_kind"),
        [
            ("first_name", "varchar(100)", "Jane Doe", "name"),
            ("national_id", "bigint", "12345678", "identifier"),
            ("DateOfBirth", "datetime", "1980-01-15 00:00:00", "birth-date"),
            # A single bit still discloses a special category (GDPR art. 9), so a
            # boolean column must never be exempted on the strength of its datatype.
            ("Religion_Christian", "bit", "True", "demographic"),
            ("HasHealthFlag", "bit", "False", "health"),
            ("HasAddressOnFile", "bit", "True", "address"),
        ],
    )
    def test_column_name_detection_survives_every_datatype(
        self, column: str, data_type: str, value: str, expected_kind: str
    ):
        redacted, finding = redact_sample_value(
            value,
            table="people",
            column=column,
            data_type=data_type,
        )
        assert is_redaction_token(redacted)
        assert finding is not None and finding.kind == expected_kind


class TestLocationDetector:
    """#423: a coordinate pair beside a redacted address must not stay in the clear."""

    def test_sample_privacy_version_bumped(self):
        # Artifacts stamped "1" were sanitised under a policy without location (#423);
        # only `policy` (unchanged) is test-asserted elsewhere, so bumping this is safe.
        assert SAMPLE_PRIVACY_VERSION == "2"
        assert "location" in DETECTED_PII_KINDS

    @pytest.mark.parametrize(
        ("column", "value"),
        [
            ("CoordinateLatitude", "51.219448"),
            ("CoordinateLongitude", "3.224739"),
            ("Latitude", "51.219448"),
            ("Longitude", "3.224739"),
            ("lat", "51.219448"),
            ("lon", "3.224739"),
            ("lng", "3.224739"),
            ("geo_location", "3.224739"),
        ],
    )
    def test_coordinate_pair_is_detected_and_redacted(self, column: str, value: str):
        assert detect_sample_pii_kind(column, value) == "location"
        redacted, finding = redact_sample_value(
            value,
            table="addresses",
            column=column,
            data_type="decimal(9,6)",
        )
        assert is_redaction_token(redacted)
        assert finding is not None and finding.kind == "location"
        assert redacted == (
            f"<redacted kind=location source=addresses.{column} datatype=decimal(9,6)>"
        )

    def test_out_of_range_geo_value_is_not_flagged(self):
        # Range plausibility is a secondary filter: values outside a lat/lon's
        # physical range are not coordinates, even in a geo-named column.
        assert detect_sample_pii_kind("Latitude", "123.456789") is None
        assert detect_sample_pii_kind("Longitude", "200.123456") is None

    @pytest.mark.parametrize(
        ("column", "value"),
        [
            # False-positive guards for the whole-token matching rule: none of these
            # column names carry a whole geo token, only a substring lookalike.
            ("TranslationKey", "3.14159265358979"),
            ("LongName", "3.14159265358979"),
            ("RelationId", "0.123456789"),
            ("LicensePlate", "51.219448"),
            ("NetworkLatency", "51.219448"),
        ],
    )
    def test_geo_name_lookalikes_are_not_flagged(self, column: str, value: str):
        assert detect_sample_pii_kind(column, value) is None
        redacted, finding = redact_sample_value(
            value,
            table="events",
            column=column,
            data_type="decimal(18,9)",
        )
        assert redacted == value
        assert finding is None

    @pytest.mark.parametrize("value", ["3.14159265358979", "0.123456789"])
    def test_302_fixtures_stay_green_in_non_geo_columns(self, value: str):
        # The #302 regression fixtures: both are valid latitudes, so a range-only
        # rule would misclassify them. They must remain untouched here too.
        assert detect_sample_pii_kind("amount", value) is None
        redacted, finding = redact_sample_value(
            value,
            table="invoices",
            column="amount",
            data_type="decimal(18,9)",
        )
        assert redacted == value
        assert finding is None

    def test_has_address_on_file_bit_column_unaffected(self):
        # A boolean address flag must keep yielding "address", not be reinterpreted
        # by the new geo detector.
        redacted, finding = redact_sample_value(
            "True",
            table="people",
            column="HasAddressOnFile",
            data_type="bit",
        )
        assert is_redaction_token(redacted)
        assert finding is not None and finding.kind == "address"

    def test_is_pii_column_does_not_report_geo_columns(self):
        # Containment property (#423): the geo detector must be reachable ONLY from
        # the persistence path, never from `_kind_from_name`/`is_pii_column` — which
        # `propose_alignment` and `suggest_shapes` consume for alignment/shape
        # suggestion. A future refactor that folds it into `_kind_from_name` must
        # fail this test loudly.
        assert not is_pii_column("CoordinateLatitude")
        assert not is_pii_column("CoordinateLongitude")
        assert not is_pii_column("Latitude", sample_values=["51.219448"])
        assert not is_pii_column("Longitude", sample_values=["3.224739"])
        assert not is_pii_column("lat")
        assert not is_pii_column("lon")

    def test_address_and_coordinates_redacted_together_in_one_row(self):
        # The reported scenario: a redacted address beside a coordinate pair that
        # used to persist unredacted in the clear (~0.1 m precision) in the same row.
        row = {
            "StreetAddress": "Kerkstraat 12",
            "PostalCode": "9000",
            "CoordinateLatitude": "51.219448",
            "CoordinateLongitude": "3.224739",
        }
        safe_rows, findings = redact_sample_rows([row], table="addresses")
        kinds = {finding.column: finding.kind for finding in findings}
        assert kinds["StreetAddress"] == "address"
        assert kinds["CoordinateLatitude"] == "location"
        assert kinds["CoordinateLongitude"] == "location"
        assert is_redaction_token(safe_rows[0]["StreetAddress"])
        assert is_redaction_token(safe_rows[0]["CoordinateLatitude"])
        assert is_redaction_token(safe_rows[0]["CoordinateLongitude"])
        # PostalCode carries no PII keyword and no geo token: left untouched.
        assert safe_rows[0]["PostalCode"] == "9000"

    def test_idempotent_redaction_gate_agrees_with_redactor(self):
        """The trap that aborts persistence: a non-token residual re-fires the gate.

        Precision reduction (e.g. writing back ``51.33``) would not be an opaque
        token, so `find_unredacted_sample_pii` would re-detect it and
        `SamplePrivacyError` would abort persistence. The opaque `kind=location`
        token must be idempotent by construction.
        """
        row = {
            "CoordinateLatitude": "51.219448",
            "CoordinateLongitude": "3.224739",
        }
        safe_rows, findings = redact_sample_rows([row], table="addresses")
        assert len(findings) == 2

        # First pass leaves nothing detectable.
        assert find_unredacted_sample_pii(safe_rows, table="addresses") == []

        # Running the redactor again on the already-redacted rows is a no-op.
        safe_rows_again, findings_again = redact_sample_rows(safe_rows, table="addresses")
        assert safe_rows_again == safe_rows
        assert findings_again == []
        assert find_unredacted_sample_pii(safe_rows_again, table="addresses") == []
