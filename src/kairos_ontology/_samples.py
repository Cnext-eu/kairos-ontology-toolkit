# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Shared sample-value exposure & PII-masking policy (DD-075).

Single source of truth for how real source sample values are surfaced to a human
during mapping and shape design.  Raw values are clipped and capped; values from
columns classified as **PII** are always masked, regardless of any override.

Sample values are produced **by default** (they are high-value evidence during
mapping); callers may pass ``include=False`` (wired to a ``--no-sample-values``
opt-out) for highly sensitive hubs.

This module is pure and deterministic (no I/O) so it can be reused by
``propose_alignment`` and ``suggest_shapes`` with an identical privacy posture.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Canonical PII keyword list (single source of truth; re-used by validator).
# If a column name OR its mapped domain property name/label contains one of
# these substrings, the column is treated as personal data.
# ---------------------------------------------------------------------------
PII_KEYWORDS: list[str] = [
    "first_name", "last_name", "date_of_birth", "national_id", "iban",
    "phone", "email", "address", "ssn", "passport", "tax_id", "gender",
    "ethnicity", "religion", "health", "maiden_name", "birth_place",
    "nationality", "marital_status",
]

#: Bounds for human-facing example rendering.
MAX_SAMPLE_CHARS = 48
MAX_SAMPLES_PER_COLUMN = 3

# Value-shape detectors — a column whose sampled values look like any of these
# is treated as PII even if its name carries no keyword.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Za-z0-9]{8,30}$")
_PHONE_RE = re.compile(r"^\+?[\d][\d\s().-]{6,}$")
_LONG_DIGITS_RE = re.compile(r"^\d{9,}$")


def _normalize(name: str) -> str:
    """Lowercase + snake-ish form for keyword matching (camelCase aware)."""
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", str(name or ""))
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower().replace(" ", "_").replace("-", "_")


def _name_is_pii(name: str | None) -> bool:
    if not name:
        return False
    norm = _normalize(name)
    return any(kw in norm for kw in PII_KEYWORDS)


def value_is_pii_shaped(value: str) -> bool:
    """True when a raw value looks like an email, IBAN, phone, or long id."""
    text = str(value or "").strip()
    if not text:
        return False
    return bool(
        _EMAIL_RE.match(text)
        or _IBAN_RE.match(text.replace(" ", ""))
        or _PHONE_RE.match(text)
        or _LONG_DIGITS_RE.match(text)
    )


def is_pii_column(
    column_name: str | None,
    *,
    target_property: str | None = None,
    target_label: str | None = None,
    gdpr_protected: bool = False,
    sample_values: list[Any] | None = None,
) -> bool:
    """Classify a column as PII.

    A column is PII when ANY of:
      1. its (bronze) column name matches a PII keyword;
      2. it is mapped to a domain property whose local name/label matches a PII
         keyword, or whose class is protected by ``kairos-ext:gdprSatelliteOf``;
      3. any sampled value has a PII value-shape (email/IBAN/phone/long id).
    """
    if gdpr_protected:
        return True
    if _name_is_pii(column_name) or _name_is_pii(target_property) or _name_is_pii(target_label):
        return True
    for v in sample_values or []:
        if value_is_pii_shaped(str(v)):
            return True
    return False


def clip(value: str, max_chars: int = MAX_SAMPLE_CHARS) -> str:
    """Clip a value to a bounded display size."""
    text = str(value)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def mask_value(value: str) -> str:
    """Mask a single value according to its shape (length-aware, irreversible)."""
    text = str(value or "").strip()
    if not text:
        return text

    # Email → keep up to 2 leading local chars + domain TLD only.
    m = _EMAIL_RE.match(text)
    if m:
        local, _, domain = text.partition("@")
        tld = domain.rsplit(".", 1)[-1] if "." in domain else "***"
        return f"{local[:2]}***@***.{tld}"

    # IBAN / phone / long digits → keep last 2 chars, mask the rest.
    compact = text.replace(" ", "")
    if _IBAN_RE.match(compact) or _PHONE_RE.match(text) or _LONG_DIGITS_RE.match(text):
        keep = text[-2:] if len(text) > 2 else ""
        return ("*" * max(len(text) - 2, 1)) + keep

    # Generic PII string → first char + bounded mask.
    return text[0] + "***"


def example_values(
    samples: list[Any] | None,
    *,
    is_pii: bool,
    include: bool = True,
    max_count: int = MAX_SAMPLES_PER_COLUMN,
    max_chars: int = MAX_SAMPLE_CHARS,
) -> list[str]:
    """Render up to ``max_count`` human-facing example values.

    PII columns are always masked. Non-PII columns are shown raw (clipped).
    Returns an empty list when ``include`` is False or there are no samples.
    """
    if not include or not samples:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in samples:
        text = str(raw).strip()
        if not text:
            continue
        rendered = mask_value(text) if is_pii else clip(text, max_chars)
        if rendered in seen:
            continue
        seen.add(rendered)
        out.append(rendered)
        if len(out) >= max_count:
            break
    return out
