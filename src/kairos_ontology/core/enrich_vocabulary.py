# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Vocabulary Enrichment — infer enums, formats, and FK relationships from sample data.

This module augments a parsed source-schema dict (v1.1) with inference annotations
that inform the design-source skill and produce richer bronze vocabulary TTL.

All inferences are *suggestions* — they add metadata but never commit to modeling
decisions. The design-source skill uses them interactively for proposals.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Configuration defaults
# --------------------------------------------------------------------------- #

DEFAULT_ENUM_THRESHOLD = 25  # max distinct values to suggest as enum
DEFAULT_ENUM_MIN_ROWS = 100  # min row count before enum detection kicks in
DEFAULT_ENUM_RATIO = 0.1  # max distinct/row_count ratio for enum suggestion

# --------------------------------------------------------------------------- #
# Format detection patterns
# --------------------------------------------------------------------------- #

FORMAT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("uuid", re.compile(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )),
    ("email", re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")),
    ("date", re.compile(r"^\d{4}-\d{2}-\d{2}")),
    ("url", re.compile(r"^https?://")),
    ("phone", re.compile(r"^\+?\d[\d\s\-()]{6,}$")),
    ("numeric_code", re.compile(r"^\d{2,10}$")),
]

# FK column name suffixes (case-insensitive matching)
FK_SUFFIXES = ("_id", "id", "_key", "_fk")


# --------------------------------------------------------------------------- #
# Data classes for suggestions
# --------------------------------------------------------------------------- #


@dataclass
class EnumSuggestion:
    """A column detected as a likely enumeration."""

    table: str
    column: str
    distinct_count: int
    values: list[str] = field(default_factory=list)


@dataclass
class FormatSuggestion:
    """A detected format pattern for a column."""

    table: str
    column: str
    format_hint: str  # uuid, email, date, url, phone, numeric_code


@dataclass
class FKSuggestion:
    """A suggested foreign key relationship."""

    table: str
    column: str
    target_table: str
    confidence: str = "high"  # "high" (name match) or "medium" (cardinality match)


# --------------------------------------------------------------------------- #
# Detection Functions
# --------------------------------------------------------------------------- #


def detect_enums(
    table_name: str,
    columns: list[dict],
    row_count: int | None,
    enum_threshold: int = DEFAULT_ENUM_THRESHOLD,
    min_rows: int = DEFAULT_ENUM_MIN_ROWS,
    enum_ratio: float = DEFAULT_ENUM_RATIO,
) -> list[EnumSuggestion]:
    """Detect columns that are likely enumerations.

    Heuristic: distinct_count <= threshold AND row_count >= min_rows
    AND distinct_count / row_count < ratio.
    """
    if not row_count or row_count < min_rows:
        return []

    suggestions = []
    for col in columns:
        distinct = col.get("distinct_count")
        if distinct is None:
            continue

        # Skip boolean-like columns (always 2 values)
        if distinct <= 1:
            continue

        if distinct <= enum_threshold and distinct / row_count < enum_ratio:
            # Collect sample values as enum candidates
            samples = col.get("samples", [])
            suggestions.append(EnumSuggestion(
                table=table_name,
                column=col["name"],
                distinct_count=distinct,
                values=samples[:enum_threshold],
            ))

    return suggestions


def detect_formats(table_name: str, columns: list[dict]) -> list[FormatSuggestion]:
    """Detect format patterns from sample values.

    Checks first 3 non-null samples against known patterns.
    A format is suggested only if ALL checked samples match the same pattern.
    """
    suggestions = []
    for col in columns:
        samples = col.get("samples", [])
        if not samples:
            continue

        # Skip non-string-like columns
        dt = col.get("data_type", "").lower()
        if any(t in dt for t in ("int", "decimal", "numeric", "bit", "float", "bigint")):
            continue

        # Check up to 3 samples
        check_samples = [s for s in samples[:3] if s and s.strip()]
        if not check_samples:
            continue

        for fmt_name, pattern in FORMAT_PATTERNS:
            if all(pattern.match(s) for s in check_samples):
                suggestions.append(FormatSuggestion(
                    table=table_name,
                    column=col["name"],
                    format_hint=fmt_name,
                ))
                break  # First matching pattern wins

    return suggestions


def infer_foreign_keys(tables: list[dict]) -> list[FKSuggestion]:
    """Infer FK relationships from column naming patterns and cardinality.

    Strategy:
    1. Name-based: columns ending in _id/_key → look for matching table name
    2. Cardinality-based: distinct_count of column ≈ row_count of another table
    """
    # Build table index: name → row_count
    table_index: dict[str, int] = {}
    table_names_lower: dict[str, str] = {}  # lower → original
    for tbl in tables:
        name = tbl.get("name", "")
        if name:
            table_index[name] = tbl.get("row_count") or 0
            table_names_lower[name.lower()] = name

    suggestions = []
    for tbl in tables:
        tbl_name = tbl.get("name", "")
        for col in tbl.get("columns", []):
            col_name = col.get("name", "")
            col_lower = col_name.lower()

            # Check FK suffixes
            matched_target = None
            for suffix in FK_SUFFIXES:
                if col_lower.endswith(suffix):
                    # Strip suffix to get candidate table name
                    base = col_lower[: -len(suffix)].rstrip("_")
                    if not base:
                        continue

                    # Try matching table names (case-insensitive)
                    # Try: exact, plural (base + s), with prefix (tbl + base)
                    candidates = [
                        base,
                        base + "s",
                        "tbl" + base,
                        "tbl" + base + "s",
                    ]
                    for candidate in candidates:
                        if candidate in table_names_lower and \
                                table_names_lower[candidate] != tbl_name:
                            matched_target = table_names_lower[candidate]
                            break

                    if matched_target:
                        break

            if matched_target:
                suggestions.append(FKSuggestion(
                    table=tbl_name,
                    column=col_name,
                    target_table=matched_target,
                    confidence="high",
                ))
            else:
                # Cardinality-based inference (looser)
                distinct = col.get("distinct_count")
                if distinct and distinct > 1:
                    for other_name, other_count in table_index.items():
                        if other_name == tbl_name or not other_count:
                            continue
                        # Within 5% tolerance
                        if abs(distinct - other_count) / max(other_count, 1) <= 0.05:
                            # Only if column name has some FK-like pattern
                            if any(col_lower.endswith(s) for s in FK_SUFFIXES):
                                suggestions.append(FKSuggestion(
                                    table=tbl_name,
                                    column=col_name,
                                    target_table=other_name,
                                    confidence="medium",
                                ))
                                break

    return suggestions


# --------------------------------------------------------------------------- #
# Main Enrichment Function
# --------------------------------------------------------------------------- #


def enrich_source_schema(
    data: dict,
    enum_threshold: int = DEFAULT_ENUM_THRESHOLD,
) -> dict:
    """Augment a parsed source-schema dict with inference annotations.

    Mutates `data` in-place by adding enrichment fields to columns and tables:
    - Column-level: `suggested_enum`, `enum_values`, `format_hint`, `suggested_fk`
    - Table-level: (row_count already present from extraction)

    Args:
        data: Parsed source-schema dict (v1.1 expected but safe for v1.0).
        enum_threshold: Max distinct values for enum detection.

    Returns:
        The same dict reference (mutated in place).
    """
    tables = data.get("tables", [])

    # Pass 1: Enum + Format detection (per-table)
    all_enum_suggestions: list[EnumSuggestion] = []
    all_format_suggestions: list[FormatSuggestion] = []
    for tbl in tables:
        tbl_name = tbl.get("name", "")
        row_count = tbl.get("row_count")
        columns = tbl.get("columns", [])

        # Enum detection
        enum_suggestions = detect_enums(
            tbl_name, columns, row_count, enum_threshold=enum_threshold
        )
        all_enum_suggestions.extend(enum_suggestions)
        enum_cols = {s.column: s for s in enum_suggestions}

        # Format detection
        format_suggestions = detect_formats(tbl_name, columns)
        all_format_suggestions.extend(format_suggestions)
        format_cols = {s.column: s for s in format_suggestions}

        # Annotate columns
        for col in columns:
            col_name = col.get("name", "")
            if col_name in enum_cols:
                col["suggested_enum"] = True
                col["enum_values"] = enum_cols[col_name].values
            if col_name in format_cols:
                col["format_hint"] = format_cols[col_name].format_hint

    # Pass 2: FK inference (cross-table)
    fk_suggestions = infer_foreign_keys(tables)
    fk_by_table_col: dict[tuple[str, str], FKSuggestion] = {
        (s.table, s.column): s for s in fk_suggestions
    }

    for tbl in tables:
        tbl_name = tbl.get("name", "")
        for col in tbl.get("columns", []):
            col_name = col.get("name", "")
            key = (tbl_name, col_name)
            if key in fk_by_table_col:
                fk = fk_by_table_col[key]
                col["suggested_fk"] = fk.target_table
                col["fk_confidence"] = fk.confidence

    logger.info(
        f"Enrichment complete: {len(all_enum_suggestions)} enum suggestions, "
        f"{len(all_format_suggestions)} format hints, {len(fk_suggestions)} FK suggestions"
    )

    return data
