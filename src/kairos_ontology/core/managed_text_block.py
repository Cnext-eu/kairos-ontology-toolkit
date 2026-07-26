# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Generic sentinel-delimited managed-block text splicing.

Several scaffolding workflows regenerate a small, tool-owned region of an
otherwise hand-authored file (DD-083's ``# >>> kairos-managed ... # <<< kairos-managed``
pattern, first introduced for ``claims-to-silver-ext``). This module factors the
splice mechanics out so any workflow can reuse the same, already-hardened
algorithm with its own sentinel text: the managed region is regenerated
wholesale as plain text, and everything outside it — comments, prefix layout,
triple/row ordering, provenance headers — is preserved byte-for-byte.

Generic and domain-agnostic: callers supply their own begin/end marker strings
and managed-line content; this module has no knowledge of Turtle, Markdown, or
any specific vocabulary.
"""

from __future__ import annotations

import re


class ManagedBlockError(ValueError):
    """Raised when a file's managed-block markers are missing, duplicated, or malformed."""


def _line_ending(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _end_after(text: str, end: int, end_marker: str) -> int:
    """Include the managed block's terminating newline in its owned span."""
    end_after = end + len(end_marker)
    if text.startswith("\r\n", end_after):
        return end_after + 2
    if text.startswith("\n", end_after):
        return end_after + 1
    return end_after


def split_managed_block(
    text: str,
    *,
    begin_marker: str,
    end_marker: str,
    label: str = "<managed file>",
) -> tuple[str, bool]:
    """Return ``(authored_text, has_block)`` for *text*.

    Raises :class:`ManagedBlockError` when the markers are present but do not
    form exactly one well-formed ``begin ... end`` pair.
    """
    begins = [match.start() for match in re.finditer(re.escape(begin_marker), text)]
    ends = [match.start() for match in re.finditer(re.escape(end_marker), text)]
    if not begins and not ends:
        return text, False
    if len(begins) != 1 or len(ends) != 1 or ends[0] < begins[0]:
        raise ManagedBlockError(
            f"{label}: malformed managed-block markers — expected exactly one "
            f"{begin_marker!r} ... {end_marker!r} pair."
        )
    end_after = _end_after(text, ends[0], end_marker)
    return text[: begins[0]] + text[end_after:], True


def compose_managed_file(
    authored_text: str,
    managed_lines: list[str],
    *,
    begin_marker: str,
    end_marker: str,
) -> str:
    """Append a deterministic managed block without reformatting authored text."""
    if not managed_lines:
        return authored_text

    newline = _line_ending(authored_text)
    block = (
        begin_marker
        + newline
        + newline.join(managed_lines)
        + newline
        + end_marker
        + newline
    )
    if not authored_text:
        return block

    separator = "" if authored_text.endswith(("\n", "\r")) else newline
    return authored_text + separator + block


def replace_managed_block(
    text: str,
    managed_lines: list[str],
    *,
    begin_marker: str,
    end_marker: str,
    label: str = "<managed file>",
) -> str:
    """Replace only the managed span, preserving authored bytes on both sides.

    Raises :class:`ManagedBlockError` via :func:`split_managed_block` when the
    existing markers are malformed (never silently guesses at a repair).
    """
    begins = [match.start() for match in re.finditer(re.escape(begin_marker), text)]
    ends = [match.start() for match in re.finditer(re.escape(end_marker), text)]
    if not begins and not ends:
        return compose_managed_file(
            text, managed_lines, begin_marker=begin_marker, end_marker=end_marker
        )

    # Reuse the canonical validation and keep the original prefix/suffix byte-for-byte.
    split_managed_block(text, begin_marker=begin_marker, end_marker=end_marker, label=label)
    begin = begins[0]
    end_after = _end_after(text, ends[0], end_marker)
    if not managed_lines:
        return text[:begin] + text[end_after:]

    newline = _line_ending(text)
    block = (
        begin_marker
        + newline
        + newline.join(managed_lines)
        + newline
        + end_marker
        + newline
    )
    return text[:begin] + block + text[end_after:]
