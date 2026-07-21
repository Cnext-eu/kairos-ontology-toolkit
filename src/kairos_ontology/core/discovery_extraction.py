# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Per-document extraction tracking for business discovery (DD-060).

During business discovery the ``kairos-design-discovery`` skill reads raw
artifacts (PDFs, decks, notes) dropped in ``.import/businessdiscovery/`` and
extracts company-specific terminology.  To record **what was extracted from
which document** and to detect **which documents are new or changed** on a
rerun, the skill writes one *extraction YAML* per source document into
``ontology-hub/businessdiscovery/_extractions/``.

This module provides the deterministic, AI-free bookkeeping around those files:
a stable filename mapping, read/write helpers, and a hash-based freshness check
(``check_discovery_docs``) that mirrors the inventory freshness pattern used by
``check_inventories`` (DD-047).  Documents are discovered **recursively** so
artifacts organised into subfolders are tracked too; a document's normalized
source-relative path is its canonical identity and is matched against the stored
``source_path`` provenance, so a valid nested extraction is recognised instead of
being reported as orphaned.  The AI extraction itself stays in the skill; only
the tracking is implemented here so it can be unit-tested and surfaced via the
``discovery-status`` CLI command.

Extraction files live in ``ontology-hub/businessdiscovery/_extractions/`` and are
committed to git so the provenance travels with the hub.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .inventory import compute_source_hash

# Marker used to reduce a stored ``source_path`` to a key relative to the
# business-discovery import root.  Both the documented relative form
# (``.import/businessdiscovery/<nested/path>``) and absolute paths that still
# contain the import folder normalize through this marker.
_IMPORT_MARKER = "businessdiscovery/"

logger = logging.getLogger(__name__)

EXTRACTION_VERSION = "1.0"

EXTRACTION_SUFFIX = ".extraction.yaml"

# Files in the import folder that are never treated as discovery documents.
_IGNORED_NAMES = {"readme.md"}


def slugify_source_name(name: str) -> str:
    """Return a filesystem-safe slug for a source document filename.

    The file extension is folded into the slug so that same-stem documents with
    different extensions (e.g. ``report.pdf`` vs ``report.docx``) map to distinct
    extraction files instead of colliding.  Example: ``"Cargo Glossary.PDF"`` ->
    ``"cargo-glossary-pdf"``.
    """
    lowered = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "document"


def extraction_filename(doc_path: Path | str, *, relative_path: Path | str | None = None) -> str:
    """Return the deterministic extraction filename for a source document.

    For a **top-level** document the filename is derived from its basename, so
    historical extraction files keep their names (backward compatible).

    For a **nested** document (``relative_path`` contains a directory separator)
    the filename is derived from the full source-relative path and suffixed with
    a short digest of that normalized path.  This keeps extraction files flat
    under ``_extractions/`` while preventing collisions between:

      - identical filenames living in different subfolders; and
      - different paths whose slugs would otherwise coincide.
    """
    rel = None
    if relative_path is not None:
        rel = str(relative_path).replace("\\", "/").strip("/")

    if rel and "/" in rel:
        digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:8]  # noqa: S324 - non-crypto id
        slug = slugify_source_name(rel)
        max_slug_length = 255 - len(digest) - len(EXTRACTION_SUFFIX) - 1
        slug = slug[:max_slug_length].rstrip("-") or "document"
        return f"{slug}-{digest}{EXTRACTION_SUFFIX}"

    name = Path(rel).name if rel else Path(doc_path).name
    return f"{slugify_source_name(name)}{EXTRACTION_SUFFIX}"


def source_relative_path(doc_path: Path, import_dir: Path) -> str:
    """Return *doc_path* as a normalized POSIX path relative to *import_dir*.

    Falls back to the basename when *doc_path* is not located under *import_dir*.
    This relative path is the **canonical identity** of a discovery document and
    is what should be stored as ``source_path`` (prefixed with the import root).
    """
    try:
        return doc_path.relative_to(import_dir).as_posix()
    except ValueError:
        return doc_path.name


def normalize_source_key(source_path: Any, import_dir: Path) -> str | None:
    """Reduce a stored ``source_path`` to a comparison key relative to the root.

    Handles the documented relative form
    (``.import/businessdiscovery/<nested/path>``), absolute paths that still
    contain the import folder, and paths that can be made relative to
    *import_dir*.  Returns ``None`` for empty input.
    """
    if not source_path:
        return None
    s = str(source_path).replace("\\", "/").strip()
    if not s:
        return None

    idx = s.rfind(_IMPORT_MARKER)
    if idx != -1:
        return s[idx + len(_IMPORT_MARKER):].strip("/")

    try:
        return Path(s).resolve().relative_to(Path(import_dir).resolve()).as_posix()
    except (ValueError, OSError):
        pass

    return Path(s).name


def is_discovery_document(path: Path) -> bool:
    """Return True if *path* is a source document (not a README, dotfile or dir)."""
    if not path.is_file():
        return False
    if path.name.startswith("."):
        return False
    if path.name.lower() in _IGNORED_NAMES:
        return False
    return True


def iter_discovery_documents(import_dir: Path) -> list[Path]:
    """Return the sorted list of source documents under *import_dir* (recursive).

    The full tree of ``.import/businessdiscovery/`` is scanned so documents in
    subfolders are processed too.  READMEs and dotfiles are ignored at every
    depth, and any file living under a dot-prefixed directory is skipped.  The
    ``_extractions/`` outputs live elsewhere (under ``ontology-hub/``) so there
    is no nesting to exclude here.  Results are ordered by their normalized
    source-relative POSIX path for deterministic, cross-platform output.
    """
    if not import_dir.is_dir():
        return []

    docs: list[Path] = []
    for p in import_dir.rglob("*"):
        if not is_discovery_document(p):
            continue
        rel = p.relative_to(import_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        docs.append(p)
    return sorted(docs, key=lambda p: source_relative_path(p, import_dir))


def write_extraction(extraction: dict[str, Any], output_path: Path) -> Path:
    """Write a per-document extraction dict to a YAML file.

    Creates parent directories if needed.  Returns the written path.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(
            extraction,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=120,
        )
    logger.info("Wrote extraction to %s", output_path)
    return output_path


def load_extraction(path: Path) -> dict[str, Any]:
    """Load a previously written extraction YAML.

    Raises:
        FileNotFoundError: If the path does not exist.
        ValueError: If the file does not contain a YAML mapping.
    """
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Extraction file {path} does not contain a YAML mapping")
    return data


@dataclass
class DiscoveryStatusReport:
    """Result of a deterministic discovery-document freshness check (DD-060).

    Each list holds the source document's normalized source-relative path (as
    dropped under ``.import/businessdiscovery/``, e.g. ``sub/report.pdf``);
    *orphan* holds extraction file names that no longer have a matching source
    document, and *conflict* holds source paths claimed by more than one
    extraction record.
    """

    unprocessed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unverifiable: list[str] = field(default_factory=list)
    ok: list[str] = field(default_factory=list)
    orphan: list[str] = field(default_factory=list)
    conflict: list[str] = field(default_factory=list)

    @property
    def has_work(self) -> bool:
        """True when a document is new (unprocessed) or has changed since extraction."""
        return bool(self.unprocessed or self.changed)

    @property
    def has_warnings(self) -> bool:
        """True when an extraction has no stored hash, is orphaned, or conflicts."""
        return bool(self.unverifiable or self.orphan or self.conflict)


def _index_extractions(
    extraction_dir: Path,
    import_dir: Path,
) -> tuple[dict[str, dict[str, Any] | None], dict[str, list[str]]]:
    """Load every extraction file once, indexed by filename and source key.

    Returns ``(by_name, by_source_key)`` where *by_name* maps each extraction
    filename to its parsed data (``None`` when unreadable) and *by_source_key*
    maps a normalized ``source_path`` key to the extraction filenames claiming
    it (a list, so duplicate provenance can be surfaced as a conflict).
    """
    by_name: dict[str, dict[str, Any] | None] = {}
    by_source_key: dict[str, list[str]] = {}
    if not extraction_dir.is_dir():
        return by_name, by_source_key

    for ext_file in sorted(extraction_dir.glob(f"*{EXTRACTION_SUFFIX}")):
        try:
            data: dict[str, Any] | None = load_extraction(ext_file)
        except Exception:  # noqa: BLE001 - unreadable extraction, record and continue
            data = None
        by_name[ext_file.name] = data
        if data is not None:
            key = normalize_source_key(data.get("source_path"), import_dir)
            if key:
                by_source_key.setdefault(key, []).append(ext_file.name)
    return by_name, by_source_key


def check_discovery_docs(
    *,
    import_dir: Path,
    extraction_dir: Path,
) -> DiscoveryStatusReport:
    """Deterministically classify discovery documents against their extractions.

    For every source document under *import_dir* (scanned recursively), resolves
    the matching extraction file under *extraction_dir* and checks that its
    stored ``source_sha256`` matches the current document content.

    An extraction is matched to a document by, in order:

      1. normalized ``source_path`` provenance (the authoritative match — this is
         what lets a valid **nested** record be recognised instead of orphaned);
      2. the legacy basename-derived extraction filename (top-level records); or
      3. the path-derived nested extraction filename.

    Classification (mirrors :class:`~kairos_ontology.core.inventory.InventoryCheckReport`):
      - **unprocessed**  — document has no extraction file yet.
      - **changed**      — extraction exists but its stored hash differs (or is unreadable).
      - **unverifiable** — extraction exists but has no stored hash → warn.
      - **ok**           — extraction exists and hash matches.
      - **conflict**     — more than one extraction claims the document's source path.
      - **orphan**       — extraction file with no corresponding source document.
    """
    report = DiscoveryStatusReport()
    by_name, by_source_key = _index_extractions(extraction_dir, import_dir)
    consumed: set[str] = set()

    for doc in iter_discovery_documents(import_dir):
        rel = source_relative_path(doc, import_dir)

        match: str | None = None
        candidates = by_source_key.get(rel)
        if candidates:
            match = candidates[0]
            consumed.update(candidates)
            if len(candidates) > 1:
                report.conflict.append(rel)

        if match is None:
            legacy = extraction_filename(doc)
            if "/" not in rel and legacy in by_name:
                match = legacy

        if match is None:
            nested = extraction_filename(doc, relative_path=rel)
            if nested in by_name:
                match = nested

        if match is None:
            report.unprocessed.append(rel)
            continue

        consumed.add(match)
        data = by_name.get(match)
        if data is None:
            report.changed.append(rel)
            continue

        stored = data.get("source_sha256")
        if not stored:
            report.unverifiable.append(rel)
            continue

        if stored != compute_source_hash(doc):
            report.changed.append(rel)
        else:
            report.ok.append(rel)

    for name in sorted(by_name):
        if name not in consumed:
            report.orphan.append(name)

    return report
