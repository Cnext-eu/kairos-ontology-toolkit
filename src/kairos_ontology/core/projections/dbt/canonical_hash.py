# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Canonical hash contract v1 reference codec and adapter SQL (DD-109)."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Final

from .policy_specs import CanonicalTypeKind, CanonicalTypeSpec


CANONICAL_HASH_VERSION: Final = "1"
CANONICAL_HASH_ALGORITHM: Final = "SHA-256"
CANONICAL_HASH_NULL_REPRESENTATION: Final = "typed-length-delimited-null"
_HEADER: Final = b"KAIROS-CANONICAL-HASH|v1|"
_DECIMAL = re.compile(r"^decimal\(\s*(\d+)\s*,\s*(\d+)\s*\)$", re.IGNORECASE)
_STRING = re.compile(r"^(?:n?varchar|string)\(\s*(\d+)\s*\)$", re.IGNORECASE)


class CanonicalHashError(ValueError):
    """A value or type cannot be represented without ambiguity under contract v1."""


@dataclass(frozen=True, slots=True)
class CanonicalValue:
    """One typed input to the canonical hash stream."""

    data_type: CanonicalTypeSpec
    value: object


@dataclass(frozen=True, slots=True)
class CanonicalHashSqlInput:
    """One validated physical column consumed by adapter hash SQL."""

    expression: str
    data_type: CanonicalTypeSpec


@dataclass(frozen=True, slots=True)
class CanonicalHashGoldenVector:
    """Frozen contract bytes and digest for cross-language conformance."""

    name: str
    canonical_bytes: bytes
    sha256: str


CANONICAL_HASH_V1_GOLDEN_VECTORS: Final = (
    CanonicalHashGoldenVector(
        "null-string",
        b"KAIROS-CANONICAL-HASH|v1|string:N:0:;",
        "30d2cd31ed1c356d7c860e921254a4799cccd1bacfbbbc5c163166c43720e7f6",
    ),
    CanonicalHashGoldenVector(
        "empty-string",
        b"KAIROS-CANONICAL-HASH|v1|string:V:0:;",
        "cce200aff6e79d7d558f859e45374f3a638a79ed41c010771877278f9f19b261",
    ),
    CanonicalHashGoldenVector(
        "unicode",
        b"KAIROS-CANONICAL-HASH|v1|string:V:10:436166c3a920f09f9982;",
        "2362cca5a039f405357b22ab089284be3ca57b85fbe20ae026b43bdb25d8a173",
    ),
    CanonicalHashGoldenVector(
        "decimal",
        b"KAIROS-CANONICAL-HASH|v1|decimal(18,4):V:8:3132332e34303030;",
        "5e8a389464353787e91193fc4915855743c493f4aa7fad8ae195ac971dfa85d6",
    ),
    CanonicalHashGoldenVector(
        "date",
        b"KAIROS-CANONICAL-HASH|v1|date:V:10:323032362d30372d3235;",
        "1fa55573517fc32036a83bdc47f12188b172bbcebbefd949191a0f6bf77adfc1",
    ),
    CanonicalHashGoldenVector(
        "time",
        b"KAIROS-CANONICAL-HASH|v1|time:V:15:31373a33353a33332e373532303030;",
        "584c7e68c3aab4e816801ec02d55d1ea378700b7fb4d9528957545155bf3d3e6",
    ),
    CanonicalHashGoldenVector(
        "timestamp",
        (
            b"KAIROS-CANONICAL-HASH|v1|timestamp:V:27:"
            b"323032362d30372d32355431373a33353a33332e3735323030305a;"
        ),
        "1a2270207ac8f926152262a1d427fc6b086023d4d4aadec7b95866f2665cd330",
    ),
    CanonicalHashGoldenVector(
        "binary",
        b"KAIROS-CANONICAL-HASH|v1|binary:V:6:303066663130;",
        "c7bd2f446e21e459974fd20c37dc3e6dcb2b3aada4b0c0eb671691f47c7e6581",
    ),
    CanonicalHashGoldenVector(
        "json",
        (
            b"KAIROS-CANONICAL-HASH|v1|json:V:28:"
            b"7b2261223a22c3a9222c227a223a5b747275652c6e756c6c2c325d7d;"
        ),
        "9fcbaa6059fce3e654464df2f2857a5a47a5d4766024ebf3d1d32bad0b9e4e17",
    ),
    CanonicalHashGoldenVector(
        "unicode-gt8k-bytes",
        (
            b"KAIROS-CANONICAL-HASH|v1|string:V:10000:"
            + ("\u00e9" * 5000).encode("utf-8").hex().encode("ascii")
            + b";"
        ),
        "df1ebd5135359afe2e578a6f87964cce5893b50ac5d9a97c3d85ba7881ae1ce9",
    ),
    CanonicalHashGoldenVector(
        "binary-gt8k-bytes",
        (
            b"KAIROS-CANONICAL-HASH|v1|binary:V:18432:"
            + (bytes(range(256)) * 36).hex().encode("ascii").hex().encode("ascii")
            + b";"
        ),
        "7269114cb521da54ec7a08ad78cf1ce892723cbea44f5e7e23dd9ab55d645849",
    ),
)


def canonical_type_label(data_type: CanonicalTypeSpec) -> str:
    """Return the stable v1 type tag."""
    if data_type.kind is CanonicalTypeKind.DECIMAL:
        if data_type.precision is None or data_type.scale is None:
            raise CanonicalHashError("decimal hash inputs require precision and scale")
        return f"decimal({data_type.precision},{data_type.scale})"
    return data_type.kind.value


def parse_canonical_type(value: str) -> CanonicalTypeSpec:
    """Parse an adapter-neutral or projected SQL type without guessing."""
    raw = value.strip()
    decimal_match = _DECIMAL.fullmatch(raw)
    if decimal_match:
        return CanonicalTypeSpec(
            CanonicalTypeKind.DECIMAL,
            precision=int(decimal_match.group(1)),
            scale=int(decimal_match.group(2)),
        )
    string_match = _STRING.fullmatch(raw)
    if string_match:
        return CanonicalTypeSpec(
            CanonicalTypeKind.STRING,
            length=int(string_match.group(1)),
        )
    aliases = {
        "string": CanonicalTypeKind.STRING,
        "varchar": CanonicalTypeKind.STRING,
        "nvarchar": CanonicalTypeKind.STRING,
        "boolean": CanonicalTypeKind.BOOLEAN,
        "bool": CanonicalTypeKind.BOOLEAN,
        "bit": CanonicalTypeKind.BOOLEAN,
        "smallint": CanonicalTypeKind.INT16,
        "int16": CanonicalTypeKind.INT16,
        "int": CanonicalTypeKind.INT32,
        "integer": CanonicalTypeKind.INT32,
        "int32": CanonicalTypeKind.INT32,
        "bigint": CanonicalTypeKind.INT64,
        "int64": CanonicalTypeKind.INT64,
        "date": CanonicalTypeKind.DATE,
        "time": CanonicalTypeKind.TIME,
        "timestamp": CanonicalTypeKind.TIMESTAMP,
        "datetime": CanonicalTypeKind.TIMESTAMP,
        "datetime2": CanonicalTypeKind.TIMESTAMP,
        "binary": CanonicalTypeKind.BINARY,
        "varbinary": CanonicalTypeKind.BINARY,
        "json": CanonicalTypeKind.JSON,
        "variant": CanonicalTypeKind.JSON,
    }
    kind = aliases.get(raw.lower())
    if kind is None:
        raise CanonicalHashError(
            f"unsupported or ambiguous canonical hash type {value!r}"
        )
    return CanonicalTypeSpec(kind)


def _require_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CanonicalHashError(f"{label} requires an integer value")
    return value


def _decimal_text(value: object, data_type: CanonicalTypeSpec) -> str:
    if data_type.precision is None or data_type.scale is None:
        raise CanonicalHashError("decimal hash inputs require precision and scale")
    if isinstance(value, bool) or isinstance(value, float):
        raise CanonicalHashError("decimal values must not be supplied as binary floats")
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
        quantum = Decimal(1).scaleb(-data_type.scale)
        quantized = decimal_value.quantize(quantum)
    except (InvalidOperation, ValueError) as exc:
        raise CanonicalHashError(f"invalid decimal value {value!r}") from exc
    if not decimal_value.is_finite() or quantized != decimal_value:
        raise CanonicalHashError(
            f"decimal value {value!r} cannot be represented exactly at "
            f"scale {data_type.scale}"
        )
    if quantized == 0:
        quantized = abs(quantized)
    digits = len(quantized.as_tuple().digits)
    integer_digits = max(digits - data_type.scale, 0)
    if integer_digits + data_type.scale > data_type.precision:
        raise CanonicalHashError(
            f"decimal value {value!r} exceeds precision {data_type.precision}"
        )
    return format(quantized, f".{data_type.scale}f")


def _date_value(value: object) -> date:
    if isinstance(value, datetime):
        raise CanonicalHashError("date values must not contain a time component")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise CanonicalHashError(f"invalid ISO date {value!r}") from exc
    raise CanonicalHashError("date values require date or ISO date text")


def _time_value(value: object) -> time:
    if isinstance(value, time):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = time.fromisoformat(value)
        except ValueError as exc:
            raise CanonicalHashError(f"invalid ISO time {value!r}") from exc
    else:
        raise CanonicalHashError("time values require time or ISO time text")
    if parsed.tzinfo is not None:
        raise CanonicalHashError("time-only hash inputs must not carry a time zone")
    return parsed


def _timestamp_value(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise CanonicalHashError(f"invalid ISO timestamp {value!r}") from exc
    else:
        raise CanonicalHashError(
            "timestamp values require timezone-aware datetime or ISO timestamp text"
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CanonicalHashError("timestamp hash inputs require an explicit time zone")
    return parsed.astimezone(timezone.utc)


def _normalize_json(value: object) -> object:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        if normalized != value:
            raise CanonicalHashError("JSON strings and keys must already be NFC")
        return value
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise CanonicalHashError("JSON object keys must be strings")
        if any(unicodedata.normalize("NFC", key) != key for key in value):
            raise CanonicalHashError("JSON strings and keys must already be NFC")
        return {key: _normalize_json(item) for key, item in value.items()}
    raise CanonicalHashError(
        "JSON hash inputs support null, booleans, integers, strings, arrays, and "
        "objects; binary-float formatting is intentionally rejected"
    )


def _json_text(value: object) -> str:
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise CanonicalHashError("invalid JSON hash input") from exc
    return json.dumps(
        _normalize_json(parsed),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_lexical_v1(value: object, data_type: CanonicalTypeSpec) -> str:
    """Return the unambiguous canonical lexical value for one supported type."""
    kind = data_type.kind
    if value is None:
        raise CanonicalHashError("null has no lexical value; use canonical_field_v1")
    if kind is CanonicalTypeKind.STRING:
        if not isinstance(value, str):
            raise CanonicalHashError("string hash inputs require a string value")
        normalized = unicodedata.normalize("NFC", value)
        if normalized != value:
            raise CanonicalHashError("string hash inputs must already be NFC")
        if data_type.length is not None and len(normalized) > data_type.length:
            raise CanonicalHashError(
                f"string exceeds declared length {data_type.length}"
            )
        return normalized
    if kind is CanonicalTypeKind.BOOLEAN:
        if not isinstance(value, bool):
            raise CanonicalHashError("boolean hash inputs require bool")
        return "true" if value else "false"
    if kind in {
        CanonicalTypeKind.INT16,
        CanonicalTypeKind.INT32,
        CanonicalTypeKind.INT64,
    }:
        integer = _require_int(value, kind.value)
        bounds = {
            CanonicalTypeKind.INT16: (-32768, 32767),
            CanonicalTypeKind.INT32: (-2147483648, 2147483647),
            CanonicalTypeKind.INT64: (-9223372036854775808, 9223372036854775807),
        }
        lower, upper = bounds[kind]
        if not lower <= integer <= upper:
            raise CanonicalHashError(f"{integer} is outside {kind.value} range")
        return str(integer)
    if kind is CanonicalTypeKind.DECIMAL:
        return _decimal_text(value, data_type)
    if kind is CanonicalTypeKind.FLOAT64:
        raise CanonicalHashError(
            "float64 is unsupported by canonical hash v1; map to an exact decimal"
        )
    if kind is CanonicalTypeKind.DATE:
        return _date_value(value).isoformat()
    if kind is CanonicalTypeKind.TIME:
        return _time_value(value).isoformat(timespec="microseconds")
    if kind is CanonicalTypeKind.TIMESTAMP:
        timestamp = _timestamp_value(value)
        return timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if kind is CanonicalTypeKind.BINARY:
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise CanonicalHashError("binary hash inputs require bytes")
        return bytes(value).hex()
    if kind is CanonicalTypeKind.JSON:
        return _json_text(value)
    raise CanonicalHashError(f"unsupported canonical hash type {kind.value!r}")


def canonical_field_v1(value: CanonicalValue) -> bytes:
    """Serialize one typed field with an explicit null marker and byte length."""
    type_label = canonical_type_label(value.data_type).encode("ascii")
    if value.value is None:
        return type_label + b":N:0:;"
    payload = canonical_lexical_v1(value.value, value.data_type).encode("utf-8")
    return (
        type_label
        + b":V:"
        + str(len(payload)).encode("ascii")
        + b":"
        + payload.hex().encode("ascii")
        + b";"
    )


def canonical_serialize_v1(values: tuple[CanonicalValue, ...]) -> bytes:
    """Serialize ordered values exactly as hashed by DD-109 contract v1."""
    if not values:
        raise CanonicalHashError("canonical hash v1 requires at least one typed input")
    return _HEADER + b"".join(canonical_field_v1(value) for value in values)


def canonical_hash_v1(values: tuple[CanonicalValue, ...]) -> str:
    """Return lowercase SHA-256 hex over the canonical v1 byte stream."""
    return hashlib.sha256(canonical_serialize_v1(values)).hexdigest()


def temporal_match_count_column(property_uri: str) -> str:
    """Return the stable diagnostic column for one temporal relationship."""
    digest = hashlib.sha256(property_uri.encode("utf-8")).hexdigest()[:12]
    return f"_kairos_fk_{digest}_match_count"


def _sql_type_label(data_type: CanonicalTypeSpec) -> str:
    label = canonical_type_label(data_type)
    if data_type.kind in {CanonicalTypeKind.FLOAT64, CanonicalTypeKind.JSON}:
        raise CanonicalHashError(
            f"{label} cannot be canonicalized equivalently by both v1 SQL adapters"
        )
    return label


def canonical_hash_macro_call(inputs: tuple[CanonicalHashSqlInput, ...]) -> str:
    """Render a dbt macro call whose values and type tags remain paired and ordered."""
    if not inputs:
        raise CanonicalHashError("canonical hash v1 requires at least one SQL input")
    expressions = ", ".join(repr(item.expression) for item in inputs)
    types = ", ".join(repr(_sql_type_label(item.data_type)) for item in inputs)
    return (
        "{{ kairos_canonical_hash_v1(["
        f"{expressions}], [{types}]) "
        "}}"
    )


def _canonical_lexical_sql(
    value: CanonicalHashSqlInput,
    adapter: str,
) -> str:
    expression = value.expression
    label = _sql_type_label(value.data_type)
    kind = value.data_type.kind
    if adapter == "fabric":
        if kind is CanonicalTypeKind.STRING:
            return f"CAST({expression} AS VARCHAR(MAX))"
        if kind is CanonicalTypeKind.BOOLEAN:
            return f"CASE WHEN {expression} = 1 THEN 'true' ELSE 'false' END"
        if kind in {
            CanonicalTypeKind.INT16,
            CanonicalTypeKind.INT32,
            CanonicalTypeKind.INT64,
        }:
            return f"CAST({expression} AS VARCHAR(40))"
        if kind is CanonicalTypeKind.DECIMAL:
            return f"CAST(CAST({expression} AS {label.upper()}) AS VARCHAR(80))"
        if kind is CanonicalTypeKind.DATE:
            return f"CONVERT(CHAR(10), CAST({expression} AS DATE), 23)"
        if kind is CanonicalTypeKind.TIME:
            return f"CONVERT(VARCHAR(16), CAST({expression} AS TIME(6)), 126)"
        if kind is CanonicalTypeKind.TIMESTAMP:
            return (
                "CONCAT(CONVERT(VARCHAR(26), "
                f"CAST({expression} AS DATETIME2(6)), 126), 'Z')"
            )
        if kind is CanonicalTypeKind.BINARY:
            return (
                "LOWER(CONVERT(VARCHAR(MAX), "
                f"CAST({expression} AS VARBINARY(MAX)), 2))"
            )
    elif adapter == "databricks":
        if kind in {
            CanonicalTypeKind.STRING,
            CanonicalTypeKind.INT16,
            CanonicalTypeKind.INT32,
            CanonicalTypeKind.INT64,
            CanonicalTypeKind.TIME,
        }:
            return f"CAST({expression} AS STRING)"
        if kind is CanonicalTypeKind.BOOLEAN:
            return f"CASE WHEN {expression} THEN 'true' ELSE 'false' END"
        if kind is CanonicalTypeKind.DECIMAL:
            return f"CAST(CAST({expression} AS {label.upper()}) AS STRING)"
        if kind is CanonicalTypeKind.DATE:
            return f"DATE_FORMAT(CAST({expression} AS DATE), 'yyyy-MM-dd')"
        if kind is CanonicalTypeKind.TIMESTAMP:
            return (
                "DATE_FORMAT(CAST("
                f"{expression} AS TIMESTAMP), "
                "'yyyy-MM-dd''T''HH:mm:ss.SSSSSS''Z''')"
            )
        if kind is CanonicalTypeKind.BINARY:
            return f"LOWER(HEX(CAST({expression} AS BINARY)))"
    else:
        raise CanonicalHashError(f"unknown adapter {adapter!r}")
    raise CanonicalHashError(
        f"{label} cannot be canonicalized by adapter {adapter!r}"
    )


def render_canonical_hash_sql_v1(
    inputs: tuple[CanonicalHashSqlInput, ...],
    adapter: str,
) -> str:
    """Render standalone dialect SQL equivalent to the packaged dbt macro."""
    if not inputs:
        raise CanonicalHashError("canonical hash v1 requires at least one SQL input")
    fields: list[str] = []
    for item in inputs:
        label = _sql_type_label(item.data_type)
        lexical = _canonical_lexical_sql(item, adapter)
        if adapter == "fabric":
            encoded = (
                "CONVERT(VARBINARY(MAX), "
                f"CAST({lexical} AS VARCHAR(MAX)) "
                "COLLATE Latin1_General_100_BIN2_UTF8)"
            )
            field = (
                f"CASE WHEN {item.expression} IS NULL THEN '{label}:N:0:;' "
                f"ELSE CONCAT('{label}:V:', CAST(DATALENGTH({encoded}) AS VARCHAR(20)), "
                f"':', LOWER(CONVERT(VARCHAR(MAX), {encoded}, 2)), ';') END"
            )
        else:
            encoded = f"ENCODE(CAST({lexical} AS STRING), 'UTF-8')"
            field = (
                f"CASE WHEN {item.expression} IS NULL THEN '{label}:N:0:;' "
                f"ELSE CONCAT('{label}:V:', CAST(LENGTH({encoded}) AS STRING), ':', "
                f"LOWER(HEX({encoded})), ';') END"
            )
        fields.append(field)
    stream = "CONCAT('KAIROS-CANONICAL-HASH|v1|', " + ", ".join(fields) + ")"
    if adapter == "fabric":
        return (
            "LOWER(CONVERT(VARCHAR(64), HASHBYTES('SHA2_256', "
            f"CONVERT(VARBINARY(MAX), {stream})), 2))"
        )
    return f"SHA2(ENCODE({stream}, 'UTF-8'), 256)"


def validate_runtime_sql_static(sql: str, adapter: str) -> None:
    """Reject obvious cross-dialect leakage in generated DD-109 SQL."""
    common_forbidden = (
        r"\bmd5\s*\(",
        r"\bconcat_ws\s*\(",
        r"\bkairos_row_hash\b",
    )
    if adapter == "fabric":
        forbidden = (
            r"\bsha2\s*\(",
            r"\bencode\s*\(",
            r"\bto_utc_timestamp\s*\(",
            r"\bnulls\s+(?:first|last)\b",
            r"<=>",
            r"`",
        )
    elif adapter == "databricks":
        forbidden = (
            r"\bhashbytes\s*\(",
            r"\bconvert\s*\(",
            r"\bdatetime2\s*\(",
            r"\bvarbinary\s*\(",
            r"\bcollate\b",
            r"\[[a-z_][a-z0-9_]*\]",
        )
    else:
        raise CanonicalHashError(f"unknown adapter {adapter!r}")
    lowered = sql.lower()
    leaked = next(
        (
            pattern
            for pattern in (*common_forbidden, *forbidden)
            if re.search(pattern, lowered)
        ),
        None,
    )
    if leaked is not None:
        raise CanonicalHashError(
            f"{adapter} runtime SQL contains forbidden token matching {leaked!r}"
        )
