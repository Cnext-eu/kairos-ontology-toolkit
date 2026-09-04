# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the raw (pre-redaction) sample-values channel (issue #562, DD-205).

This channel is separate from, and never changes, the committed vocabulary
TTL's permanently-redacted sample values -- it is a gitignored sidecar the
alignment LLM prompt can additionally read from.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from kairos_ontology.core.raw_samples import (
    ENV_SEND_RAW_SAMPLES,
    MAX_RAW_SAMPLES_PER_COLUMN,
    extract_raw_samples_from_schema,
    extract_raw_samples_from_tables,
    get_raw_columns,
    raw_samples_enabled,
    write_raw_samples,
)


class TestRawSamplesEnabled:
    def test_on_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ENV_SEND_RAW_SAMPLES, None)
            assert raw_samples_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "FALSE", "No"])
    def test_explicit_opt_out(self, value):
        with patch.dict(os.environ, {ENV_SEND_RAW_SAMPLES: value}, clear=False):
            assert raw_samples_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "yes"])
    def test_explicit_opt_in_is_also_on(self, value):
        with patch.dict(os.environ, {ENV_SEND_RAW_SAMPLES: value}, clear=False):
            assert raw_samples_enabled() is True


class TestExtractFromSchema:
    def test_pulls_samples_and_enum_values(self):
        data = {
            "tables": [
                {
                    "name": "tblParties",
                    "columns": [
                        {"name": "PartyName", "samples": ["Acme", "Globex"]},
                        {"name": "Status", "enum_values": ["active", "closed"]},
                        {"name": "Empty", "samples": []},
                    ],
                }
            ]
        }
        out = extract_raw_samples_from_schema(data)
        assert out == {
            "tblParties": {"PartyName": ["Acme", "Globex"], "Status": ["active", "closed"]}
        }

    def test_empty_schema_yields_empty_dict(self):
        assert extract_raw_samples_from_schema({}) == {}
        assert extract_raw_samples_from_schema({"tables": []}) == {}


class TestExtractFromTables:
    def test_pulls_column_samples(self):
        tables = [
            {
                "name": "orders",
                "columns": [
                    {"name": "customer_email", "samples": ["a@b.com", "c@d.com"]},
                    {"name": "no_samples", "samples": []},
                ],
            }
        ]
        out = extract_raw_samples_from_tables(tables)
        assert out == {"orders": {"customer_email": ["a@b.com", "c@d.com"]}}

    def test_empty_tables_yields_empty_dict(self):
        assert extract_raw_samples_from_tables([]) == {}


class TestWriteAndReadRoundTrip:
    def test_round_trip(self, tmp_path):
        written = write_raw_samples(
            tmp_path, "tms", {"OrderHeader": {"consignee": ["Acme NV", "Globex"]}}
        )
        assert written is not None
        assert written == tmp_path / ".import" / "raw-samples" / "tms.json"

        columns = get_raw_columns(tmp_path, "tms", "OrderHeader")
        assert columns == {"consignee": ["Acme NV", "Globex"]}

    def test_missing_table_returns_empty(self, tmp_path):
        write_raw_samples(tmp_path, "tms", {"OrderHeader": {"x": ["y"]}})
        assert get_raw_columns(tmp_path, "tms", "OtherTable") == {}

    def test_missing_file_returns_empty(self, tmp_path):
        assert get_raw_columns(tmp_path, "nosuchsystem", "table") == {}

    def test_caps_samples_per_column(self, tmp_path):
        many = [f"v{i}" for i in range(50)]
        write_raw_samples(tmp_path, "sys", {"t": {"c": many}})
        columns = get_raw_columns(tmp_path, "sys", "t")
        assert len(columns["c"]) == MAX_RAW_SAMPLES_PER_COLUMN

    def test_disabled_write_is_a_no_op(self, tmp_path):
        with patch.dict(os.environ, {ENV_SEND_RAW_SAMPLES: "0"}, clear=False):
            result = write_raw_samples(tmp_path, "sys", {"t": {"c": ["v"]}})
        assert result is None
        assert not (tmp_path / ".import").exists()

    def test_disabled_read_returns_empty_even_if_file_exists(self, tmp_path):
        write_raw_samples(tmp_path, "sys", {"t": {"c": ["v"]}})
        with patch.dict(os.environ, {ENV_SEND_RAW_SAMPLES: "0"}, clear=False):
            assert get_raw_columns(tmp_path, "sys", "t") == {}

    def test_no_hub_root_is_a_no_op(self):
        assert write_raw_samples(None, "sys", {"t": {"c": ["v"]}}) is None

    def test_empty_table_columns_writes_nothing(self, tmp_path):
        assert write_raw_samples(tmp_path, "sys", {}) is None
        assert not (tmp_path / ".import").exists()

    def test_malformed_sidecar_file_degrades_to_empty(self, tmp_path):
        path = tmp_path / ".import" / "raw-samples" / "sys.json"
        path.parent.mkdir(parents=True)
        path.write_text("not json{{{", encoding="utf-8")
        assert get_raw_columns(tmp_path, "sys", "t") == {}

    def test_sidecar_is_valid_json_with_schema_version(self, tmp_path):
        write_raw_samples(tmp_path, "sys", {"t": {"c": ["v"]}})
        path = tmp_path / ".import" / "raw-samples" / "sys.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["schema_version"] == 1
        assert doc["system"] == "sys"
