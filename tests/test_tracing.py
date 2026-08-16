# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Langfuse tracing: opt-in, masked, and incapable of failing a run (DD-184).

Three properties matter more than the tracing itself:

1. **Off unless configured.** A hub that has not opted in must behave exactly as
   before, with no import cost and no behaviour change.
2. **Source values masked by default.** Alignment prompts carry real sample data
   from client tables. It passes the ``source-privacy`` gate, but "not personal"
   is not "safe to send to a third party".
3. **Never fails a run.** Observability that can break a pipeline is worse than
   no observability.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from kairos_ontology.core.tracing import (
    ENV_HOST,
    ENV_PUBLIC_KEY,
    ENV_SECRET_KEY,
    ENV_SEND_SAMPLES,
    call_metadata,
    flush_tracing,
    get_tracing_client,
    mask_source_samples,
    new_session_id,
    reset_tracing_client,
    trace_span,
    tracing_configured,
)

CONFIGURED = {
    ENV_PUBLIC_KEY: "pk-lf-test",
    ENV_SECRET_KEY: "sk-lf-test",
    ENV_HOST: "https://langfuse.example.internal",
}

PROMPT = (
    "COLUMNS:\n"
    "  - billing_city (varchar(max)) | samples: Dusseldorf, Gent, Luxembourg\n"
    "  - credit_limit (bigint) | samples: 5000, 12500, 1\n"
    "  - active (bit)\n"
)


class TestOffUnlessConfigured:
    def test_not_configured_by_default(self):
        assert tracing_configured() is False
        assert get_tracing_client() is None

    @pytest.mark.parametrize("missing", sorted(CONFIGURED))
    def test_every_credential_is_required(self, missing):
        env = {k: v for k, v in CONFIGURED.items() if k != missing}
        with patch.dict(os.environ, env, clear=False):
            reset_tracing_client()
            assert tracing_configured() is False

    def test_host_has_no_default(self):
        """No implicit cloud endpoint: an unconfigured hub cannot ship by accident."""
        with patch.dict(os.environ, {ENV_PUBLIC_KEY: "pk", ENV_SECRET_KEY: "sk"}, clear=False):
            reset_tracing_client()
            assert tracing_configured() is False

    def test_session_id_is_empty_when_off(self):
        assert new_session_id("align") == ""

    def test_span_yields_none_when_off(self):
        with trace_span("align-table", table="companies") as span:
            assert span is None

    def test_flush_is_safe_when_off(self):
        flush_tracing()


class TestMasking:
    def test_sample_values_are_removed_by_default(self):
        masked = mask_source_samples(data=PROMPT)
        assert "Dusseldorf" not in masked
        assert "12500" not in masked
        assert "masked" in masked

    def test_everything_else_survives(self):
        """Column names, types and structure are the diagnostic value; keep them."""
        masked = mask_source_samples(data=PROMPT)
        for keep in ("COLUMNS:", "billing_city", "varchar(max)", "credit_limit", "active (bit)"):
            assert keep in masked, keep

    def test_line_structure_is_preserved(self):
        assert len(mask_source_samples(data=PROMPT).splitlines()) == len(PROMPT.splitlines())

    def test_opt_in_sends_the_real_values(self):
        with patch.dict(os.environ, {ENV_SEND_SAMPLES: "1"}, clear=False):
            assert "Dusseldorf" in mask_source_samples(data=PROMPT)

    def test_masks_inside_a_chat_payload(self):
        """The SDK hands over a list of message dicts, not a bare string."""
        messages = [{"role": "user", "content": PROMPT}]
        masked = mask_source_samples(data=messages)
        assert "Dusseldorf" not in masked[0]["content"]
        assert masked[0]["role"] == "user"

    def test_nested_structures_are_walked(self):
        masked = mask_source_samples(data={"a": [{"b": PROMPT}]})
        assert "Dusseldorf" not in masked["a"][0]["b"]

    @pytest.mark.parametrize("value", [None, 42, 3.5, True])
    def test_non_text_passes_through(self, value):
        assert mask_source_samples(data=value) == value


class TestCallMetadata:
    def test_carries_session_role_and_tags(self):
        meta = call_metadata("align-abc123", "alignment", table="companies")
        assert meta["langfuse_session_id"] == "align-abc123"
        assert meta["role"] == "alignment"
        assert meta["table"] == "companies"
        assert "role:alignment" in meta["langfuse_tags"]

    def test_omits_session_when_tracing_is_off(self):
        assert "langfuse_session_id" not in call_metadata("", "alignment")


class TestNeverFailsARun:
    def test_missing_package_disables_tracing(self):
        with patch.dict(os.environ, CONFIGURED, clear=False):
            reset_tracing_client()
            with patch.dict("sys.modules", {"langfuse": None}):
                assert get_tracing_client() is None

    def test_constructor_failure_disables_tracing(self):
        with patch.dict(os.environ, CONFIGURED, clear=False):
            reset_tracing_client()
            broken = MagicMock(side_effect=RuntimeError("bad host"))
            with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=broken)}):
                assert get_tracing_client() is None

    def test_span_failure_does_not_propagate(self):
        client = MagicMock()
        client.start_as_current_observation.side_effect = RuntimeError("collector down")
        with patch("kairos_ontology.core.tracing.get_tracing_client", return_value=client):
            with trace_span("align-table") as span:
                assert span is None

    def test_flush_failure_does_not_propagate(self):
        client = MagicMock()
        client.flush.side_effect = RuntimeError("collector down")
        with patch("kairos_ontology.core.tracing.get_tracing_client", return_value=client):
            flush_tracing()


class TestProviderIntegration:
    def test_plain_client_when_tracing_is_off(self):
        """The traced wrapper must not be imported, let alone used, when off."""
        from kairos_ontology.core.ai_provider import _openai_class
        from openai import OpenAI

        assert _openai_class() is OpenAI

    def test_trace_kwargs_are_not_sent_to_an_untraced_client(self):
        """`name`/`metadata` are Langfuse-only; a plain client would reject them."""
        from kairos_ontology.core.ai_provider import create_chat_completion

        client = MagicMock()
        client.chat.completions.create.return_value = "ok"
        create_chat_completion(
            client,
            model="m",
            messages=[],
            trace_name="align-table",
            trace_metadata={"table": "companies"},
        )
        kwargs = client.chat.completions.create.call_args.kwargs
        assert "name" not in kwargs
        assert "metadata" not in kwargs

    def test_trace_kwargs_are_sent_when_tracing_is_on(self):
        from kairos_ontology.core.ai_provider import create_chat_completion

        client = MagicMock()
        client.chat.completions.create.return_value = "ok"
        with patch("kairos_ontology.core.tracing.get_tracing_client", return_value=MagicMock()):
            create_chat_completion(
                client,
                model="m",
                messages=[],
                trace_name="align-table",
                trace_metadata={"table": "companies"},
            )
        kwargs = client.chat.completions.create.call_args.kwargs
        assert kwargs["name"] == "align-table"
        assert kwargs["metadata"]["table"] == "companies"


class TestResponseFormatSummary:
    """The strict schema is recorded as counts, not verbatim (DD-184)."""

    SCHEMA = {
        "type": "json_schema",
        "json_schema": {
            "name": "column_alignment",
            "strict": True,
            "schema": {
                "$defs": {
                    "ColumnVerdict": {
                        "properties": {
                            "ref_property": {"enum": [f"p{i}" for i in range(900)] + [None]},
                            "ref_class": {"enum": ["A", "B", None]},
                        }
                    }
                },
                "properties": {"column_alignments": {"required": ["a", "b", "c"]}},
            },
        },
    }

    def test_schema_is_replaced_by_counts(self):
        out = mask_source_samples(data={"response_format": self.SCHEMA})["response_format"]
        assert out["strict"] is True
        assert out["summary"] == {
            "required_columns": 3,
            "ref_property_enum": 901,
            "ref_class_enum": 3,
        }

    def test_the_enum_values_are_gone(self):
        import json

        out = json.dumps(mask_source_samples(data={"response_format": self.SCHEMA}))
        assert "p899" not in out
        assert len(out) < 300, "summary must be far smaller than the schema it replaces"

    def test_plain_json_mode_is_left_alone(self):
        """The JSON-mode fallback carries no schema and needs no summarising."""
        fmt = {"type": "json_object"}
        assert mask_source_samples(data={"response_format": fmt})["response_format"] == fmt

    def test_summary_applies_even_when_samples_are_opted_in(self):
        """Sending samples is a privacy choice; it is not a reason to ship the enum."""
        with patch.dict(os.environ, {ENV_SEND_SAMPLES: "1"}, clear=False):
            out = mask_source_samples(data={"response_format": self.SCHEMA})["response_format"]
        assert "summary" in out
