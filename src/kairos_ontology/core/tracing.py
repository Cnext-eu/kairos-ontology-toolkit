# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Langfuse tracing for the LLM-backed pipeline stages (DD-184).

Three stages call a model — affinity, alignment and judgment — and until now the
only record of what was sent was a progress line and, on failure, a sanitized
error. Diagnosing a bad mapping meant re-running the stage under a bespoke
instrumentation script. This wires those calls to Langfuse so the prompt, the
response, the model settings and the token cost of every call are recorded as
they happen.

**Off unless configured.** Every entry point degrades to a no-op when the
Langfuse credentials are absent or the package is not installed, so a hub that
has not opted in behaves exactly as before and never pays an import cost.

**Source values are masked by default.** The alignment prompt carries real
sample values from client tables. They already pass the ``source-privacy`` gate,
which strips what it classifies as personal — but "not personal" is not the same
as "safe to send to a third party", and Langfuse may be someone else's cloud.
The default mask removes the sample block and keeps everything else: column
names, types, the reference classes offered, the instructions and the model's
full response. That is nearly all of the diagnostic value at none of the egress
risk. Set ``KAIROS_LANGFUSE_SEND_SAMPLES=1`` to send them anyway — appropriate
for a self-hosted Langfuse, and a deliberate act either way.
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)

#: Credentials and switches. ``LANGFUSE_HOST`` must be set explicitly — there is
#: no default cloud, so an unconfigured hub cannot ship traces by accident.
ENV_PUBLIC_KEY = "LANGFUSE_PUBLIC_KEY"
ENV_SECRET_KEY = "LANGFUSE_SECRET_KEY"
ENV_HOST = "LANGFUSE_HOST"
ENV_BASE_URL = "LANGFUSE_BASE_URL"
ENV_SEND_SAMPLES = "KAIROS_LANGFUSE_SEND_SAMPLES"
ENV_ENVIRONMENT = "KAIROS_LANGFUSE_ENVIRONMENT"

LANGFUSE_ENV_VAR_NAMES: frozenset[str] = frozenset(
    {ENV_PUBLIC_KEY, ENV_SECRET_KEY, ENV_HOST, ENV_BASE_URL, ENV_SEND_SAMPLES, ENV_ENVIRONMENT}
)

#: Matches the rendered sample block on one source-column line:
#: ``  - billing_city (varchar(max)) | samples: Dusseldorf, Gent, Luxembourg``
#: Anchored on the exact separator ``_format_source_columns`` emits, so it cannot
#: silently stop matching if surrounding prose changes.
_SAMPLE_BLOCK_RE = re.compile(r"(\| samples: ).*?(?=\n|$)")

_MASKED = "<masked: source sample values — set KAIROS_LANGFUSE_SEND_SAMPLES=1 to include>"

_client: Any | None = None
_resolved = False


def _send_samples() -> bool:
    return os.environ.get(ENV_SEND_SAMPLES, "").strip().lower() in {"1", "true", "yes"}


def mask_source_samples(*, data: Any, **_kwargs: Any) -> Any:
    """Reduce anything sent to Langfuse: mask source values, summarise the schema.

    Applied to inputs, outputs and metadata alike. Walks lists and dicts because a
    chat payload arrives as a list of message dicts, not a bare string.

    Two independent reductions. Masking sample values is a *privacy* decision and
    honours ``KAIROS_LANGFUSE_SEND_SAMPLES``. Summarising ``response_format`` is a
    *volume* decision and always applies: opting into sample values is no reason
    to also ship a 900-entry enum on every call.
    """
    if isinstance(data, str):
        if _send_samples():
            return data
        return _SAMPLE_BLOCK_RE.sub(r"\1" + _MASKED, data)
    if isinstance(data, list):
        return [mask_source_samples(data=item) for item in data]
    if isinstance(data, dict):
        return {
            key: _summarise_response_format(value)
            if key == "response_format"
            else mask_source_samples(data=value)
            for key, value in data.items()
        }
    return data


def _summarise_response_format(value: Any) -> Any:
    """Replace the strict JSON schema with a one-line summary (DD-184).

    The OpenAI wrapper records every request parameter, and ``response_format``
    carries the whole DD-177 schema — one enum entry per candidate class and per
    reference property. Measured on the smallest domain it was 78% of the
    observation's metadata; on a wide table with a 900-value property enum it
    would dwarf the prompt itself, once per call, for no diagnostic value: the
    classes offered are already legible in the prompt.

    Kept: the format name and the counts, which are what a reader would actually
    check ("was the schema strict, and how big was the vocabulary?").
    """
    if not isinstance(value, dict) or value.get("type") != "json_schema":
        return value
    schema = (value.get("json_schema") or {}).get("schema") or {}
    verdict = (schema.get("$defs") or {}).get("ColumnVerdict") or {}
    properties = verdict.get("properties") or {}

    def enum_size(field: str) -> int:
        return len((properties.get(field) or {}).get("enum") or [])

    return {
        "type": "json_schema",
        "strict": bool((value.get("json_schema") or {}).get("strict")),
        "summary": {
            "required_columns": len(
                ((schema.get("properties") or {}).get("column_alignments") or {}).get(
                    "required"
                )
                or []
            ),
            "ref_property_enum": enum_size("ref_property"),
            "ref_class_enum": enum_size("ref_class"),
        },
    }


def tracing_configured() -> bool:
    """True when both keys and a host are present. Host is required deliberately."""
    host = os.environ.get(ENV_HOST) or os.environ.get(ENV_BASE_URL)
    return bool(
        os.environ.get(ENV_PUBLIC_KEY, "").strip()
        and os.environ.get(ENV_SECRET_KEY, "").strip()
        and (host or "").strip()
    )


def get_tracing_client() -> Any | None:
    """Return a configured Langfuse client, or ``None`` when tracing is off.

    Resolved once per process. A missing package or a bad configuration logs at
    info level and disables tracing — observability must never fail a run.
    """
    global _client, _resolved
    if _resolved:
        return _client
    _resolved = True
    if not tracing_configured():
        return None
    try:
        from langfuse import Langfuse

        host = os.environ.get(ENV_HOST) or os.environ.get(ENV_BASE_URL)
        _client = Langfuse(
            public_key=os.environ[ENV_PUBLIC_KEY].strip(),
            secret_key=os.environ[ENV_SECRET_KEY].strip(),
            host=host.strip(),
            mask=mask_source_samples,
            environment=os.environ.get(ENV_ENVIRONMENT, "").strip() or None,
        )
        # Importing this instruments the `openai` module in place, so *every*
        # client is traced however it was built — including the one the Foundry
        # SDK returns from AIProjectClient.get_openai_client(), which this code
        # never constructs and so could not otherwise wrap.
        import langfuse.openai  # noqa: F401

        logger.info("Langfuse tracing enabled (host=%s)", host)
    except ImportError:
        logger.info(
            "Langfuse credentials are set but the package is not installed; "
            "tracing disabled. Install with: uv pip install langfuse"
        )
        _client = None
    except Exception as exc:  # noqa: BLE001 - observability must not fail a run
        logger.info("Langfuse tracing could not start (%s); continuing untraced.", exc)
        _client = None
    return _client


def reset_tracing_client() -> None:
    """Forget the resolved client (test seam)."""
    global _client, _resolved
    _client = None
    _resolved = False


@contextmanager
def trace_span(name: str, **attributes: Any) -> Iterator[Any]:
    """Open a named span, or yield ``None`` when tracing is off.

    Names are verb-first and free of dynamic values so they stay filterable;
    the table or domain goes in ``metadata``, not the name.
    """
    client = get_tracing_client()
    if client is None:
        yield None
        return
    try:
        with client.start_as_current_observation(
            as_type="span", name=name, metadata=attributes or None
        ) as span:
            yield span
    except Exception as exc:  # noqa: BLE001 - never fail a run on tracing
        logger.info("Langfuse span %r failed (%s); continuing untraced.", name, exc)
        yield None


def new_session_id(prefix: str) -> str:
    """Return a session id grouping every call of one CLI invocation.

    Alignment fans out across threads, where a context-manager span does not
    reliably parent concurrent calls. Sessions are the SDK's mechanism for
    grouping logically-connected traces, so they carry the run identity instead.

    Returns an empty string when tracing is off, so callers pay nothing.
    """
    if get_tracing_client() is None:
        return ""
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def call_metadata(
    session_id: str, role: str, **fields: Any
) -> dict[str, Any]:
    """Build the ``metadata`` payload for one traced completion.

    ``langfuse_session_id`` and ``langfuse_tags`` are the reserved keys the
    OpenAI integration reads; everything else is free-form context that shows on
    the observation. Tagging by role is what makes "show me every alignment call"
    a one-click filter.
    """
    payload: dict[str, Any] = {"role": role, **fields}
    if session_id:
        payload["langfuse_session_id"] = session_id
    payload["langfuse_tags"] = [f"role:{role}", "kairos-ontology-toolkit"]
    return payload


def flush_tracing() -> None:
    """Flush buffered events. Required: these are short-lived CLI processes."""
    client = get_tracing_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception as exc:  # noqa: BLE001
        logger.info("Langfuse flush failed (%s).", exc)
