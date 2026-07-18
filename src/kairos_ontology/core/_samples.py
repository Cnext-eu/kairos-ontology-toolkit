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
from dataclasses import dataclass
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

# Persistence-time detectors intentionally match inside free text. Human-facing
# masking above keeps limited shape hints; committed source artifacts use opaque
# typed tokens and therefore need broader detection.
_EMBEDDED_EMAIL_RE = re.compile(
    r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])"
)
_EMBEDDED_IBAN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}[A-Za-z0-9 ]{8,30}")
_EMBEDDED_PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")
_EMBEDDED_LONG_ID_RE = re.compile(r"(?<!\d)\d{9,}(?!\d)")
_ISO_DATE_OR_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?$"
)
_REDACTION_TOKEN_RE = re.compile(
    r"^<redacted kind=[a-z0-9-]+ source=[^<>\r\n]+ datatype=[^<>\r\n]+>$"
)

SAMPLE_PRIVACY_POLICY = "redact-detected-pii"
SAMPLE_PRIVACY_VERSION = "1"


@dataclass(frozen=True)
class SamplePrivacyFinding:
    """Value-free description of a detected source-sample privacy issue."""

    table: str
    column: str
    kind: str


class SamplePrivacyError(ValueError):
    """Raised when unredacted supported PII remains before persistence."""

    def __init__(self, findings: list[SamplePrivacyFinding]):
        self.findings = findings
        locations = sorted({f"{item.table}.{item.column}:{item.kind}" for item in findings})
        preview = ", ".join(locations[:8])
        suffix = f" (+{len(locations) - 8} more)" if len(locations) > 8 else ""
        super().__init__(
            f"Unredacted source sample PII remains in {len(findings)} value(s): "
            f"{preview}{suffix}"
        )


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
        or (_PHONE_RE.match(text) and not _ISO_DATE_OR_DATETIME_RE.match(text))
        or _LONG_DIGITS_RE.match(text)
    )


def is_redaction_token(value: Any) -> bool:
    """Return whether *value* is an opaque persistence-safe redaction token."""
    return bool(_REDACTION_TOKEN_RE.fullmatch(str(value or "").strip()))


def _component(value: str | None, fallback: str) -> str:
    """Render a bounded, token-safe source metadata component."""
    rendered = re.sub(r"[\s<>|=\r\n]+", "_", str(value or "").strip()).strip("_")
    return (rendered or fallback)[:120]


def redaction_token(
    *,
    kind: str,
    table: str,
    column: str,
    data_type: str | None,
) -> str:
    """Build an opaque token retaining source element and datatype context only."""
    safe_kind = _component(kind, "pii").lower()
    safe_table = _component(table, "unknown-table")
    safe_column = _component(column, "unknown-column")
    safe_type = _component(data_type, "unknown")
    return (
        f"<redacted kind={safe_kind} source={safe_table}.{safe_column} "
        f"datatype={safe_type}>"
    )


def _kind_from_name(name: str | None) -> str | None:
    norm = _normalize(name or "")
    named_kinds = (
        ("email", "email"),
        ("phone", "phone"),
        ("iban", "iban"),
        ("address", "address"),
        ("passport", "passport"),
        ("national_id", "identifier"),
        ("tax_id", "identifier"),
        ("ssn", "identifier"),
        ("date_of_birth", "birth-date"),
        ("birth_place", "birth-place"),
        ("first_name", "name"),
        ("last_name", "name"),
        ("maiden_name", "name"),
        ("gender", "demographic"),
        ("ethnicity", "demographic"),
        ("religion", "demographic"),
        ("health", "health"),
        ("nationality", "demographic"),
        ("marital_status", "demographic"),
    )
    for keyword, kind in named_kinds:
        if keyword in norm:
            return kind
    return "pii-column" if _name_is_pii(name) else None


def _kind_from_text(value: Any) -> str | None:
    if is_redaction_token(value):
        return None
    text = str(value or "").strip()
    if not text:
        return None
    detectors = (
        ("email", _EMBEDDED_EMAIL_RE),
        ("iban", _EMBEDDED_IBAN_RE),
        ("identifier", _EMBEDDED_LONG_ID_RE),
    )
    for kind, pattern in detectors:
        if pattern.search(text):
            return kind
    if any(
        not _ISO_DATE_OR_DATETIME_RE.fullmatch(match.group().strip())
        for match in _EMBEDDED_PHONE_RE.finditer(text)
    ):
        return "phone"
    return None


def _kind_from_nested(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            kind = _kind_from_name(str(key)) or _kind_from_nested(nested)
            if kind:
                return kind
        return None
    if isinstance(value, (list, tuple, set)):
        for nested in value:
            kind = _kind_from_nested(nested)
            if kind:
                return kind
        return None
    return _kind_from_text(value)


def detect_sample_pii_kind(column_name: str | None, value: Any) -> str | None:
    """Classify supported PII in one source value without returning the value."""
    return _kind_from_name(column_name) or _kind_from_nested(value)


def redact_sample_value(
    value: Any,
    *,
    table: str,
    column: str,
    data_type: str | None,
) -> tuple[Any, SamplePrivacyFinding | None]:
    """Replace detected PII with an opaque source-aware token.

    If supported PII appears anywhere in free text or a nested value, the complete
    cell is replaced so surrounding personal context cannot leak.
    """
    if value is None or is_redaction_token(value):
        return value, None
    kind = detect_sample_pii_kind(column, value)
    if not kind:
        return value, None
    finding = SamplePrivacyFinding(table=table, column=column, kind=kind)
    return (
        redaction_token(
            kind=kind,
            table=table,
            column=column,
            data_type=data_type,
        ),
        finding,
    )


def redact_sample_rows(
    rows: list[dict[str, Any]] | None,
    *,
    table: str,
    column_types: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[SamplePrivacyFinding]]:
    """Return source rows with detected PII replaced before persistence."""
    safe_rows: list[dict[str, Any]] = []
    findings: list[SamplePrivacyFinding] = []
    types = column_types or {}
    for row in rows or []:
        safe_row: dict[str, Any] = {}
        for column, value in row.items():
            safe_value, finding = redact_sample_value(
                value,
                table=table,
                column=str(column),
                data_type=types.get(str(column)),
            )
            safe_row[column] = safe_value
            if finding:
                findings.append(finding)
        safe_rows.append(safe_row)
    return safe_rows, findings


def find_unredacted_sample_pii(
    rows: list[dict[str, Any]] | None,
    *,
    table: str,
) -> list[SamplePrivacyFinding]:
    """Find supported PII that remains in rows, without exposing values."""
    findings: list[SamplePrivacyFinding] = []
    for row in rows or []:
        for column, value in row.items():
            if is_redaction_token(value):
                continue
            kind = detect_sample_pii_kind(str(column), value)
            if kind:
                findings.append(
                    SamplePrivacyFinding(table=table, column=str(column), kind=kind)
                )
    return findings


def assert_no_unredacted_sample_pii(
    rows: list[dict[str, Any]] | None,
    *,
    table: str,
) -> None:
    """Block persistence when a supported raw PII pattern remains."""
    findings = find_unredacted_sample_pii(rows, table=table)
    if findings:
        raise SamplePrivacyError(findings)


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
        if is_redaction_token(text):
            rendered = text
        else:
            rendered = mask_value(text) if is_pii else clip(text, max_chars)
        if rendered in seen:
            continue
        seen.add(rendered)
        out.append(rendered)
        if len(out) >= max_count:
            break
    return out
