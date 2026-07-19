# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Extract-Schema — introspect live warehouse/lakehouse and produce per-table YAML.

This module provides direct database introspection (bypassing dbt macros) to capture
rich metadata: column types, nullability, row counts, sample values, and JSON structure
detection. Output is one YAML file per table in `extracted/<system>/`.

Supports:
  - Microsoft Fabric Warehouse/Lakehouse (pyodbc)
  - Databricks (databricks-sql-connector)
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ._samples import (
    SAMPLE_PRIVACY_POLICY,
    SAMPLE_PRIVACY_VERSION,
    assert_no_unredacted_sample_pii,
    redact_sample_rows,
    redact_sample_value,
)

def _az_cmd() -> str:
    """Return the correct az CLI executable name for the platform.

    On Windows, ``az`` is distributed as ``az.cmd`` which ``subprocess.run``
    cannot find without ``shell=True``.  We use ``shutil.which`` to resolve
    the actual path so it works cross-platform without ``shell=True``.
    """
    resolved = shutil.which("az")
    if resolved:
        return resolved
    # Fallback: let subprocess raise FileNotFoundError with a clear message
    return "az"

logger = logging.getLogger(__name__)

# Default number of sample rows per table
DEFAULT_SAMPLE_SIZE = 5


# --------------------------------------------------------------------------- #
# Data Classes
# --------------------------------------------------------------------------- #


@dataclass
class JsonKeyInfo:
    """Describes a single key discovered in a JSON column."""

    key: str
    type: str  # "string", "integer", "number", "boolean", "object", "array", "null"
    sample: Any = None


@dataclass
class ColumnInfo:
    """Metadata for a single column."""

    name: str
    data_type: str
    ordinal_position: int = 0
    nullable: bool = True
    character_maximum_length: int | None = None
    numeric_precision: int | None = None
    numeric_scale: int | None = None
    distinct_count: int | None = None
    samples: list[str] = field(default_factory=list)
    json_detected: bool = False
    json_classification: str | None = None  # flat, nested, array_object, array_primitive, polymorphic
    json_structure: list[JsonKeyInfo] = field(default_factory=list)


@dataclass
class TableInfo:
    """Metadata for a single table."""

    name: str
    schema: str
    row_count: int | None = None
    columns: list[ColumnInfo] = field(default_factory=list)
    sample_rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ExtractionManifest:
    """System-level metadata for the extraction run."""

    system: str
    platform: str
    database: str
    schema: str
    extracted_at: str
    tables: list[str] = field(default_factory=list)
    sample_size: int = DEFAULT_SAMPLE_SIZE
    version: str = "1.1"


# --------------------------------------------------------------------------- #
# JSON Classification
# --------------------------------------------------------------------------- #


def classify_json_column(samples: list[str]) -> str:
    """Classify JSON column structure from sample values.

    Returns: 'flat', 'nested', 'array_object', 'array_primitive', 'polymorphic'
    """
    parsed = []
    for s in samples:
        if not s or not s.strip():
            continue
        try:
            parsed.append(json.loads(s))
        except (json.JSONDecodeError, TypeError):
            continue

    if not parsed:
        return "polymorphic"

    if all(isinstance(p, dict) for p in parsed):
        keys_sets = [set(p.keys()) for p in parsed]
        all_keys = set.union(*keys_sets)
        common_keys = set.intersection(*keys_sets)
        if all_keys and len(all_keys - common_keys) / len(all_keys) > 0.5:
            return "polymorphic"
        # Check if any value is a nested dict/list
        for p in parsed:
            if any(isinstance(v, (dict, list)) for v in p.values()):
                return "nested"
        return "flat"
    elif all(isinstance(p, list) for p in parsed):
        flat_items = [item for p in parsed for item in p]
        if flat_items and all(isinstance(item, dict) for item in flat_items):
            return "array_object"
        return "array_primitive"

    return "polymorphic"


def extract_json_structure(samples: list[str], classification: str) -> list[JsonKeyInfo]:
    """Extract key structure from JSON samples."""
    parsed = []
    for s in samples:
        if not s or not s.strip():
            continue
        try:
            parsed.append(json.loads(s))
        except (json.JSONDecodeError, TypeError):
            continue

    if not parsed:
        return []

    if classification in ("flat", "nested"):
        # Collect all keys and infer types from first non-null value
        key_types: dict[str, tuple[str, Any]] = {}
        for obj in parsed:
            if not isinstance(obj, dict):
                continue
            for k, v in obj.items():
                if k not in key_types and v is not None:
                    key_types[k] = (_json_value_type(v), v)
                elif k not in key_types:
                    key_types[k] = ("null", None)
        return [
            JsonKeyInfo(key=k, type=t, sample=_sample_repr(s))
            for k, (t, s) in key_types.items()
        ]

    elif classification == "array_object":
        # Infer structure from first array's objects
        for obj in parsed:
            if isinstance(obj, list) and obj and isinstance(obj[0], dict):
                first_item = obj[0]
                return [
                    JsonKeyInfo(key=k, type=_json_value_type(v), sample=_sample_repr(v))
                    for k, v in first_item.items()
                ]

    return []


def _json_value_type(value: Any) -> str:
    """Infer JSON type string from a Python value."""
    if isinstance(value, bool):
        return "boolean"
    elif isinstance(value, int):
        return "integer"
    elif isinstance(value, float):
        return "number"
    elif isinstance(value, str):
        return "string"
    elif isinstance(value, dict):
        return "object"
    elif isinstance(value, list):
        return "array"
    return "null"


def _sample_repr(value: Any) -> Any:
    """Convert a value to a YAML-safe sample representation."""
    if isinstance(value, (dict, list)):
        return None  # Don't embed complex objects as samples
    return value


# --------------------------------------------------------------------------- #
# Database Introspection (Fabric/pyodbc)
# --------------------------------------------------------------------------- #


def _connect_fabric(profile: dict) -> Any:
    """Connect to Fabric Warehouse/Lakehouse using profile credentials.

    Requires pyodbc to be installed.
    """
    try:
        import pyodbc
    except ImportError:
        raise ImportError(
            "pyodbc is required for Fabric connections. "
            "Install with: uv add pyodbc  (or pip install pyodbc)"
        )

    server = profile.get("server", "")
    database = profile.get("database", "")
    auth = profile.get("authentication", "CLI")
    driver = profile.get("driver", "ODBC Driver 18 for SQL Server")

    if auth.upper() == "CLI":
        # Azure CLI authentication
        try:
            import subprocess as _sp
            result = _sp.run(
                [_az_cmd(), "account", "get-access-token",
                 "--resource", "https://database.windows.net/"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                raise RuntimeError(f"az CLI token failed: {result.stderr}")
            token_data = json.loads(result.stdout)
            access_token = token_data["accessToken"]
        except FileNotFoundError:
            raise RuntimeError("Azure CLI (az) not found. Install or use ServicePrincipal auth.")

        # pyodbc token-based auth for Fabric
        import struct
        token_bytes = access_token.encode("utf-16-le")
        token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"Encrypt=Yes;"
            f"TrustServerCertificate=No;"
        )
        conn = pyodbc.connect(conn_str, attrs_before={1256: token_struct})

    elif auth.upper() == "SERVICEPRINCIPAL":
        tenant_id = profile.get("tenant_id", "")
        client_id = profile.get("client_id", "")
        client_secret = profile.get("client_secret", "")

        # Get token via client credentials
        import urllib.request
        import urllib.parse
        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        data = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://database.windows.net/.default",
        }).encode()
        req = urllib.request.Request(token_url, data=data)
        with urllib.request.urlopen(req, timeout=30) as resp:
            token_data = json.loads(resp.read())
        access_token = token_data["access_token"]

        import struct
        token_bytes = access_token.encode("utf-16-le")
        token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"Encrypt=Yes;"
            f"TrustServerCertificate=No;"
        )
        conn = pyodbc.connect(conn_str, attrs_before={1256: token_struct})

    else:
        raise ValueError(f"Unsupported authentication method: {auth}")

    return conn


# --------------------------------------------------------------------------- #
# Database Introspection (Databricks)
# --------------------------------------------------------------------------- #


def _connect_databricks(profile: dict) -> Any:
    """Connect to Databricks using profile credentials.

    Requires databricks-sql-connector to be installed.
    Supports token auth (PAT) and Azure CLI auth (OAuth M2M / U2M).
    """
    try:
        from databricks import sql as dbsql
    except ImportError:
        raise ImportError(
            "databricks-sql-connector is required for Databricks connections. "
            "Install with: uv add databricks-sql-connector"
        )

    host = profile.get("host", "")
    http_path = profile.get("http_path", "")
    token = profile.get("token", "")
    catalog = profile.get("catalog", profile.get("database", ""))

    if not host:
        raise ValueError("Databricks profile requires 'host' (workspace URL).")
    if not http_path:
        raise ValueError("Databricks profile requires 'http_path' (SQL warehouse path).")

    conn_kwargs: dict[str, Any] = {
        "server_hostname": host,
        "http_path": http_path,
    }

    if token:
        conn_kwargs["access_token"] = token
    else:
        # Try Azure CLI token for Databricks
        try:
            import subprocess as _sp
            result = _sp.run(
                [_az_cmd(), "account", "get-access-token",
                 "--resource", "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                raise RuntimeError(f"az CLI token failed: {result.stderr}")
            token_data = json.loads(result.stdout)
            conn_kwargs["access_token"] = token_data["accessToken"]
        except FileNotFoundError:
            raise RuntimeError(
                "Databricks profile needs 'token' or Azure CLI (az). "
                "Set token in profiles.yml or install Azure CLI."
            )

    conn = dbsql.connect(**conn_kwargs)

    # Set catalog if specified
    if catalog:
        cursor = conn.cursor()
        cursor.execute(f"USE CATALOG `{catalog}`")
        cursor.close()

    return conn


def _introspect_tables_databricks(
    conn: Any,
    schema: str,
    tables: list[str] | None = None,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
) -> list[TableInfo]:
    """Introspect tables from a Databricks connection using Unity Catalog.

    Databricks uses INFORMATION_SCHEMA (Unity Catalog) or DESCRIBE for Hive.
    This uses information_schema which is available in Unity Catalog mode.
    """
    cursor = conn.cursor()

    # Discover tables if not specified
    if tables is None:
        cursor.execute(
            f"SELECT table_name FROM information_schema.tables "
            f"WHERE table_schema = '{schema}' AND table_type = 'MANAGED' "
            f"OR (table_schema = '{schema}' AND table_type = 'EXTERNAL') "
            f"ORDER BY table_name"
        )
        tables = [row[0] for row in cursor.fetchall()]

    result = []
    for table_name in tables:
        logger.info(f"Introspecting {schema}.{table_name}...")
        table_info = _introspect_single_table_databricks(
            cursor, schema, table_name, sample_size
        )
        result.append(table_info)

    cursor.close()
    return result


def _introspect_single_table_databricks(
    cursor: Any, schema: str, table_name: str, sample_size: int
) -> TableInfo:
    """Introspect a single Databricks table."""
    # Get column metadata from information_schema
    cursor.execute(
        f"SELECT column_name, data_type, ordinal_position, is_nullable "
        f"FROM information_schema.columns "
        f"WHERE table_schema = '{schema}' AND table_name = '{table_name}' "
        f"ORDER BY ordinal_position"
    )
    columns_meta = cursor.fetchall()

    # Get row count
    cursor.execute(f"SELECT COUNT(*) FROM `{schema}`.`{table_name}`")
    row_count = cursor.fetchone()[0]

    columns: list[ColumnInfo] = []
    for col_row in columns_meta:
        col_name, data_type, ordinal, is_nullable = col_row

        col = ColumnInfo(
            name=col_name,
            data_type=data_type.lower(),
            ordinal_position=ordinal,
            nullable=(is_nullable == "YES"),
        )
        columns.append(col)

    # Sample rows and compute distinct counts
    sample_rows: list[dict[str, Any]] = []
    if row_count > 0 and columns:
        sample_rows = _enrich_with_samples_databricks(
            cursor, schema, table_name, columns, sample_size
        )
        _detect_json_columns_databricks(columns)

    return TableInfo(
        name=table_name,
        schema=schema,
        row_count=row_count,
        columns=columns,
        sample_rows=sample_rows,
    )


def _enrich_with_samples_databricks(
    cursor: Any,
    schema: str,
    table_name: str,
    columns: list[ColumnInfo],
    sample_size: int,
) -> list[dict[str, Any]]:
    """Fetch sample rows and distinct counts for Databricks columns.

    Returns the raw sample rows as list of dicts (column_name → value) for
    row-level sample output.
    """
    col_names = ", ".join(f"`{c.name}`" for c in columns)

    # Get samples (LIMIT N)
    try:
        cursor.execute(
            f"SELECT {col_names} FROM `{schema}`.`{table_name}` LIMIT {sample_size}"
        )
        rows = cursor.fetchall()
    except Exception as e:
        logger.warning(f"Could not sample {schema}.{table_name}: {e}")
        return []

    # Build raw row dicts (preserves row context)
    raw_rows: list[dict[str, Any]] = []
    for row in rows:
        row_dict: dict[str, Any] = {}
        for col_idx, col in enumerate(columns):
            val = row[col_idx]
            row_dict[col.name] = str(val) if val is not None else None
        raw_rows.append(row_dict)

    # Collect samples per column (deduplicated for format/enum detection)
    for col_idx, col in enumerate(columns):
        col.samples = []
        for row in rows:
            val = row[col_idx]
            if val is not None:
                col.samples.append(str(val))
        col.samples = list(dict.fromkeys(col.samples))[:sample_size]

    # Get distinct counts
    distinct_parts = ", ".join(
        f"COUNT(DISTINCT `{c.name}`)" for c in columns
    )
    try:
        cursor.execute(
            f"SELECT {distinct_parts} FROM `{schema}`.`{table_name}`"
        )
        distinct_row = cursor.fetchone()
        for col_idx, col in enumerate(columns):
            col.distinct_count = distinct_row[col_idx]
    except Exception as e:
        logger.warning(f"Could not get distinct counts for {schema}.{table_name}: {e}")

    return raw_rows


def _detect_json_columns_databricks(columns: list[ColumnInfo]) -> None:
    """Detect and classify JSON content in STRING columns (Databricks).

    Databricks stores JSON as STRING type. Detection uses the same
    heuristic: check if sample values start with { or [.
    """
    for col in columns:
        # JSON candidates in Databricks: STRING type columns
        if col.data_type not in ("string", "varchar", "binary"):
            continue
        if not col.samples:
            continue

        json_samples = [
            s for s in col.samples
            if s.strip().startswith(("{", "["))
        ]
        if len(json_samples) < len(col.samples) * 0.5:
            continue

        col.json_detected = True
        col.json_classification = classify_json_column(json_samples)
        col.json_structure = extract_json_structure(
            json_samples, col.json_classification
        )


def introspect_tables(
    conn: Any,
    schema: str,
    tables: list[str] | None = None,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
) -> list[TableInfo]:
    """Introspect tables from a live database connection.

    Args:
        conn: Active database connection (pyodbc).
        schema: Schema name to introspect.
        tables: Optional list of table names to introspect (None = all).
        sample_size: Number of sample rows per table.

    Returns:
        List of TableInfo with full metadata.
    """
    cursor = conn.cursor()

    # Discover tables if not specified
    if tables is None:
        cursor.execute(
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = ? AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME",
            (schema,),
        )
        tables = [row[0] for row in cursor.fetchall()]

    result = []
    for table_name in tables:
        logger.info(f"Introspecting {schema}.{table_name}...")
        table_info = _introspect_single_table(cursor, schema, table_name, sample_size)
        result.append(table_info)

    return result


def _introspect_single_table(
    cursor: Any, schema: str, table_name: str, sample_size: int
) -> TableInfo:
    """Introspect a single table: columns, row count, samples, JSON detection."""
    # Get column metadata
    cursor.execute(
        "SELECT COLUMN_NAME, DATA_TYPE, ORDINAL_POSITION, IS_NULLABLE, "
        "CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE "
        "FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
        "ORDER BY ORDINAL_POSITION",
        (schema, table_name),
    )
    columns_meta = cursor.fetchall()

    # Get row count
    cursor.execute(f"SELECT COUNT(*) FROM [{schema}].[{table_name}]")
    row_count = cursor.fetchone()[0]

    # Build column info with samples
    columns: list[ColumnInfo] = []
    for col_row in columns_meta:
        col_name, data_type, ordinal, is_nullable, char_max_len, num_prec, num_scale = col_row

        col = ColumnInfo(
            name=col_name,
            data_type=_format_data_type(data_type, char_max_len, num_prec, num_scale),
            ordinal_position=ordinal,
            nullable=(is_nullable == "YES"),
            character_maximum_length=char_max_len if char_max_len and char_max_len > 0 else None,
            numeric_precision=num_prec,
            numeric_scale=num_scale,
        )
        columns.append(col)

    # Sample rows and compute distinct counts
    sample_rows: list[dict[str, Any]] = []
    if row_count > 0 and columns:
        sample_rows = _enrich_with_samples(cursor, schema, table_name, columns, sample_size)
        _detect_json_columns(columns)

    return TableInfo(
        name=table_name,
        schema=schema,
        row_count=row_count,
        columns=columns,
        sample_rows=sample_rows,
    )


def _format_data_type(
    data_type: str,
    char_max_len: int | None,
    num_prec: int | None,
    num_scale: int | None,
) -> str:
    """Format a data type with precision/scale/length."""
    dt = data_type.lower()
    if char_max_len is not None and char_max_len > 0:
        return f"{dt}({char_max_len})"
    elif char_max_len == -1:
        return f"{dt}(max)"
    elif num_prec is not None and num_scale is not None and num_scale > 0:
        return f"{dt}({num_prec},{num_scale})"
    elif num_prec is not None and dt in ("decimal", "numeric"):
        return f"{dt}({num_prec})"
    return dt


def _enrich_with_samples(
    cursor: Any,
    schema: str,
    table_name: str,
    columns: list[ColumnInfo],
    sample_size: int,
) -> list[dict[str, Any]]:
    """Fetch sample rows and distinct counts for columns.

    Returns the raw sample rows as list of dicts (column_name → value) for
    row-level sample output.
    """
    col_names = ", ".join(f"[{c.name}]" for c in columns)

    # Get samples (TOP N)
    try:
        cursor.execute(
            f"SELECT TOP {sample_size} {col_names} FROM [{schema}].[{table_name}]"
        )
        rows = cursor.fetchall()
    except Exception as e:
        logger.warning(f"Could not sample {schema}.{table_name}: {e}")
        return []

    # Build raw row dicts (preserves row context)
    raw_rows: list[dict[str, Any]] = []
    for row in rows:
        row_dict: dict[str, Any] = {}
        for col_idx, col in enumerate(columns):
            val = row[col_idx]
            row_dict[col.name] = str(val) if val is not None else None
        raw_rows.append(row_dict)

    # Collect samples per column (deduplicated for format/enum detection)
    for col_idx, col in enumerate(columns):
        col.samples = []
        for row in rows:
            val = row[col_idx]
            if val is not None:
                col.samples.append(str(val))
        # Trim to unique non-empty samples (max sample_size)
        col.samples = list(dict.fromkeys(col.samples))[:sample_size]

    # Get distinct counts (batch query)
    distinct_parts = ", ".join(
        f"COUNT(DISTINCT [{c.name}])" for c in columns
    )
    try:
        cursor.execute(
            f"SELECT {distinct_parts} FROM [{schema}].[{table_name}]"
        )
        distinct_row = cursor.fetchone()
        for col_idx, col in enumerate(columns):
            col.distinct_count = distinct_row[col_idx]
    except Exception as e:
        logger.warning(f"Could not get distinct counts for {schema}.{table_name}: {e}")

    return raw_rows


def _detect_json_columns(columns: list[ColumnInfo]) -> None:
    """Detect and classify JSON content in varchar(max) columns."""
    for col in columns:
        # JSON candidates: varchar(max) or nvarchar(max)
        if col.character_maximum_length != -1 and "(max)" not in col.data_type:
            continue
        if not col.samples:
            continue

        # Check if samples look like JSON
        json_samples = [
            s for s in col.samples
            if s.strip().startswith(("{", "["))
        ]
        if len(json_samples) < len(col.samples) * 0.5:
            continue  # Less than half look like JSON

        col.json_detected = True
        col.json_classification = classify_json_column(json_samples)
        col.json_structure = extract_json_structure(
            json_samples, col.json_classification
        )


# --------------------------------------------------------------------------- #
# Profile Parsing (reads dbt profiles.yml)
# --------------------------------------------------------------------------- #


def parse_dbt_profile(profiles_dir: Path, profile_name: str, target: str = "dev") -> dict:
    """Parse dbt profiles.yml and return connection parameters for the given target.

    Args:
        profiles_dir: Directory containing profiles.yml.
        profile_name: Name of the dbt profile.
        target: Target name (default: "dev").

    Returns:
        Dict with connection params (server, database, schema, authentication, etc.)
    """
    profiles_path = profiles_dir / "profiles.yml"
    if not profiles_path.is_file():
        raise FileNotFoundError(f"profiles.yml not found at: {profiles_path}")

    with open(profiles_path, encoding="utf-8") as f:
        profiles = yaml.safe_load(f)

    if profile_name not in profiles:
        available = list(profiles.keys())
        raise ValueError(
            f"Profile '{profile_name}' not found. Available: {available}"
        )

    profile = profiles[profile_name]
    target_name = target or profile.get("target", "dev")
    outputs = profile.get("outputs", {})

    if target_name not in outputs:
        available = list(outputs.keys())
        raise ValueError(
            f"Target '{target_name}' not found in profile '{profile_name}'. "
            f"Available: {available}"
        )

    return outputs[target_name]


# --------------------------------------------------------------------------- #
# YAML Output
# --------------------------------------------------------------------------- #


def write_extraction_output(
    output_dir: Path,
    system_name: str,
    platform: str,
    database: str,
    schema: str,
    tables: list[TableInfo],
    sample_size: int = DEFAULT_SAMPLE_SIZE,
) -> Path:
    """Write extraction results as per-table YAML files.

    Creates:
      output_dir/<system_name>/
        _manifest.yaml
        <table1>.yaml
        <table2>.yaml

    Returns:
        Path to the output directory.
    """
    # Prepare and validate all output before publishing any artifact.
    manifest = ExtractionManifest(
        system=system_name,
        platform=platform,
        database=database,
        schema=schema,
        extracted_at=datetime.now(timezone.utc).isoformat(),
        tables=[t.name for t in tables],
        sample_size=sample_size,
    )
    manifest_data = {
        "version": manifest.version,
        "system": manifest.system,
        "platform": manifest.platform,
        "extracted_at": manifest.extracted_at,
        "sample_size": manifest.sample_size,
        "connection": {
            "database": manifest.database,
            "schema": manifest.schema,
        },
        "tables": manifest.tables,
        "sample_privacy": {
            "policy": SAMPLE_PRIVACY_POLICY,
            "version": SAMPLE_PRIVACY_VERSION,
        },
    }
    prepared_tables: list[tuple[TableInfo, dict, list[dict[str, Any]]]] = []
    for table in tables:
        column_types = {col.name: col.data_type for col in table.columns}
        safe_rows, _ = redact_sample_rows(
            table.sample_rows,
            table=table.name,
            column_types=column_types,
        )
        assert_no_unredacted_sample_pii(safe_rows, table=table.name)
        prepared_tables.append((table, _table_to_yaml_dict(table), safe_rows))

    system_dir = output_dir / system_name
    system_dir.mkdir(parents=True, exist_ok=True)

    # Write manifest
    manifest_path = system_dir / "_manifest.yaml"
    with open(manifest_path, "w", encoding="utf-8") as f:
        yaml.dump(manifest_data, f, default_flow_style=False, sort_keys=False)

    # Write per-table YAML
    for table, table_data, safe_rows in prepared_tables:
        table_path = system_dir / f"{table.name}.yaml"
        with open(table_path, "w", encoding="utf-8") as f:
            yaml.dump(table_data, f, default_flow_style=False, sort_keys=False)

        # Write per-table samples YAML with row context and opaque PII tokens.
        if safe_rows:
            samples_data = {
                "extracted_at": manifest.extracted_at,
                "table": table.name,
                "schema": table.schema,
                "sample_privacy": manifest_data["sample_privacy"],
                "rows": safe_rows,
            }
            samples_path = system_dir / f"{table.name}.samples.yaml"
            with open(samples_path, "w", encoding="utf-8") as f:
                yaml.dump(samples_data, f, default_flow_style=False, sort_keys=False)
        else:
            stale_samples = system_dir / f"{table.name}.samples.yaml"
            if stale_samples.exists():
                stale_samples.unlink()

    return system_dir


def _table_to_yaml_dict(table: TableInfo) -> dict:
    """Convert a TableInfo to a YAML-serializable dict."""
    columns_data = []
    for col in table.columns:
        col_dict: dict[str, Any] = {
            "name": col.name,
            "data_type": col.data_type,
            "ordinal_position": col.ordinal_position,
            "nullable": col.nullable,
        }
        if col.distinct_count is not None:
            col_dict["distinct_count"] = col.distinct_count
        # Samples are written to separate .samples.yaml files (not inline)
        if col.json_detected:
            col_dict["json_detected"] = True
            col_dict["json_classification"] = col.json_classification
            if col.json_structure:
                structures = []
                for js in col.json_structure:
                    structure = {"key": js.key, "type": js.type}
                    if js.sample is not None:
                        safe_sample, _ = redact_sample_value(
                            js.sample,
                            table=table.name,
                            column=f"{col.name}.{js.key}",
                            data_type=js.type,
                        )
                        assert_no_unredacted_sample_pii(
                            [{f"{col.name}.{js.key}": safe_sample}],
                            table=table.name,
                        )
                        structure["sample"] = safe_sample
                    structures.append(structure)
                col_dict["json_structure"] = structures
        columns_data.append(col_dict)

    return {
        "name": table.name,
        "schema": table.schema,
        "row_count": table.row_count,
        "columns": columns_data,
    }


# --------------------------------------------------------------------------- #
# High-level orchestration
# --------------------------------------------------------------------------- #


def run_extract_schema(
    profiles_dir: Path,
    profile_name: str,
    target: str,
    schema: str,
    system_name: str,
    output_dir: Path,
    tables: list[str] | None = None,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
) -> Path:
    """Run full schema extraction pipeline.

    Args:
        profiles_dir: Path to directory containing profiles.yml.
        profile_name: dbt profile name.
        target: dbt target (e.g., "dev").
        schema: Database schema to introspect.
        system_name: Logical source system name.
        output_dir: Base output directory (e.g., "extracted/").
        tables: Optional list of specific tables to introspect.
        sample_size: Number of sample rows per table.

    Returns:
        Path to the output directory with YAML files.
    """
    # Parse profile
    profile = parse_dbt_profile(profiles_dir, profile_name, target)

    # Determine platform
    adapter_type = profile.get("type", "fabric")
    platform_map = {
        "fabric": "fabric-warehouse",
        "spark": "fabric-lakehouse",
        "databricks": "databricks",
        "snowflake": "snowflake",
        "postgres": "postgres",
    }
    platform = platform_map.get(adapter_type, "unknown")

    database = profile.get("database", "")

    # Connect and introspect
    if adapter_type in ("fabric", "spark"):
        conn = _connect_fabric(profile)
        try:
            table_infos = introspect_tables(conn, schema, tables, sample_size)
        finally:
            conn.close()
    elif adapter_type == "databricks":
        conn = _connect_databricks(profile)
        try:
            table_infos = _introspect_tables_databricks(conn, schema, tables, sample_size)
        finally:
            conn.close()
    else:
        raise NotImplementedError(
            f"Platform '{adapter_type}' not yet supported. "
            f"Currently supported: fabric, spark (Fabric Warehouse/Lakehouse), "
            f"databricks"
        )

    # Write output
    result_dir = write_extraction_output(
        output_dir=output_dir,
        system_name=system_name,
        platform=platform,
        database=database,
        schema=schema,
        tables=table_infos,
        sample_size=sample_size,
    )

    return result_dir
