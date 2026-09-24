# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Plain text from a staged business-discovery document (#907).

DD-233 fails ``validate`` until every document under ``.import/businessdiscovery/`` has
an extraction, and the discovery step writes that extraction by reading the document. On
one hub 20 of 31 staged documents were ``.docx``/``.pptx``/``.xlsx``, formats nothing in
the toolkit could open: an obligation without a tool, which is how a gate gets cleared
with ``--degraded`` instead of satisfied. This module is the tool. ``read-document`` is
its CLI.

Deterministic and AI-free: it returns the document's own text, in reading order, with
light structure (``## Slide 3``, ``## Sheet: Rates``, tables as ``|``-rows) so the
reader can cite where a term came from. It does not summarise, and it does not guess at
images -- a slide that is only a picture says so.

The optional readers live in the ``documents`` extra; a missing one is reported with the
install command rather than raised as an import error.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path

#: Every suffix that counts as a business document wherever the toolkit looks for one:
#: the DD-233 "staged where nothing reads it" check and the discovery readers share it,
#: so the two can never disagree about what a document is (#907). ``.txt`` and ``.csv``
#: are readable but deliberately absent: staged loose, they are far more often scratch
#: than a briefing, and a false "you forgot this" is how a gate gets disabled (DD-233).
#: Inside ``businessdiscovery/`` every file counts regardless.
BUSINESS_DOCUMENT_SUFFIXES: frozenset[str] = frozenset(
    {
        ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".md",
        ".xml", ".htm", ".html", ".rtf",
    }
)

#: Suffixes :func:`read_document_text` can turn into text, and the extra each needs.
READERS: dict[str, str | None] = {
    ".pdf": None,
    ".docx": "documents",
    ".pptx": "documents",
    ".xlsx": "documents",
    ".md": None,
    ".txt": None,
    ".csv": None,
    ".xml": None,
    ".htm": None,
    ".html": None,
}

#: Legacy binary formats with no pure-Python reader. Named so the message says what to do.
_CONVERT_FIRST = {".doc": ".docx", ".ppt": ".pptx", ".xls": ".xlsx"}

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_BLOCK_RE = re.compile(r"</?(p|div|br|li|tr|h[1-6])\b[^>]*>", re.IGNORECASE)
_BLANKS_RE = re.compile(r"\n{3,}")


class DocumentReadError(Exception):
    """The document cannot be read as text: unsupported, missing reader, or broken."""


@dataclass(slots=True)
class DocumentText:
    """The text of one document, and what the reader could not include."""

    path: Path
    format: str
    text: str
    #: Pages, slides or sheets read.
    units: int = 0
    notes: list[str] = field(default_factory=list)


def _require(module: str, suffix: str):
    try:
        return __import__(module)
    except ImportError as exc:
        raise DocumentReadError(
            f"reading {suffix} needs the 'documents' extra: "
            "uv sync --extra documents (or pip install 'kairos-ontology-toolkit[documents]')."
        ) from exc


def _pdf(path: Path, doc: DocumentText) -> None:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts: list[str] = []
    empty = 0
    for number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            empty += 1
        parts.append(f"## Page {number}\n\n{text}")
    doc.units = len(reader.pages)
    doc.text = "\n\n".join(parts)
    if empty:
        doc.notes.append(
            f"{empty} of {doc.units} page(s) have no text layer (scanned or image-only); "
            "read those visually."
        )


def _docx(path: Path, doc: DocumentText) -> None:
    _require("docx", ".docx")
    import docx

    document = docx.Document(str(path))
    parts: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = (paragraph.style.name or "").lower() if paragraph.style is not None else ""
        if style.startswith("heading"):
            level = "".join(ch for ch in style if ch.isdigit()) or "1"
            parts.append(f"{'#' * min(int(level) + 1, 6)} {text}")
        else:
            parts.append(text)
    for number, table in enumerate(document.tables, start=1):
        rows = [
            "| " + " | ".join(cell.text.strip().replace("\n", " ") for cell in row.cells) + " |"
            for row in table.rows
        ]
        if rows:
            parts.append(f"## Table {number}\n\n" + "\n".join(rows))
    doc.units = len(document.paragraphs)
    doc.text = "\n\n".join(parts)
    if document.inline_shapes:
        doc.notes.append(
            f"{len(document.inline_shapes)} embedded image(s) are not included; open the "
            "document if a diagram carries meaning."
        )


def _pptx(path: Path, doc: DocumentText) -> None:
    _require("pptx", ".pptx")
    from pptx import Presentation

    presentation = Presentation(str(path))
    parts: list[str] = []
    image_only = 0
    for number, slide in enumerate(presentation.slides, start=1):
        lines: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                text = "\n".join(
                    p.text.strip() for p in shape.text_frame.paragraphs if p.text.strip()
                )
                if text:
                    lines.append(text)
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    lines.append(
                        "| " + " | ".join(c.text.strip().replace("\n", " ") for c in row.cells)
                        + " |"
                    )
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                lines.append(f"Speaker notes: {notes}")
        if not lines:
            image_only += 1
        parts.append(f"## Slide {number}\n\n" + "\n\n".join(lines))
    doc.units = len(presentation.slides)
    doc.text = "\n\n".join(parts)
    if image_only:
        doc.notes.append(
            f"{image_only} slide(s) carry no text (images or diagrams only); read those "
            "visually."
        )


def _xlsx(path: Path, doc: DocumentText) -> None:
    _require("openpyxl", ".xlsx")
    from openpyxl import load_workbook

    workbook = load_workbook(str(path), read_only=True, data_only=True)
    parts: list[str] = []
    try:
        for sheet in workbook.worksheets:
            rows = []
            for row in sheet.iter_rows(values_only=True):
                cells = ["" if v is None else str(v).strip() for v in row]
                if any(cells):
                    rows.append("| " + " | ".join(cells) + " |")
            parts.append(f"## Sheet: {sheet.title}\n\n" + ("\n".join(rows) or "(empty)"))
        doc.units = len(workbook.worksheets)
    finally:
        workbook.close()
    doc.text = "\n\n".join(parts)


def _plain(path: Path, doc: DocumentText) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in {".htm", ".html"}:
        text = _SCRIPT_RE.sub("", text)
        text = _BLOCK_RE.sub("\n", text)
        text = html.unescape(_TAG_RE.sub("", text))
        text = "\n".join(line.strip() for line in text.splitlines())
    doc.text = _BLANKS_RE.sub("\n\n", text).strip()
    doc.units = 1


_DISPATCH = {".pdf": _pdf, ".docx": _docx, ".pptx": _pptx, ".xlsx": _xlsx}


def read_document_text(path: Path) -> DocumentText:
    """Read *path* as text. Raises :class:`DocumentReadError` with an actionable message."""
    path = Path(path)
    if not path.is_file():
        raise DocumentReadError(f"{path} is not a file.")
    suffix = path.suffix.lower()
    if suffix in _CONVERT_FIRST:
        raise DocumentReadError(
            f"{suffix} is a legacy binary format with no text reader. Save it as "
            f"{_CONVERT_FIRST[suffix]} (or PDF) and stage that instead."
        )
    if suffix not in READERS:
        raise DocumentReadError(
            f"no text reader for {suffix or 'files without an extension'}. If it is an "
            "image or diagram, read it visually; if it should not be extracted at all, "
            "move it to .import/drafts/."
        )
    doc = DocumentText(path=path, format=suffix.lstrip("."), text="")
    try:
        _DISPATCH.get(suffix, _plain)(path, doc)
    except DocumentReadError:
        raise
    except Exception as exc:  # a corrupt file is the author's to fix; say which one
        raise DocumentReadError(f"could not read {path.name}: {exc}") from exc
    return doc
