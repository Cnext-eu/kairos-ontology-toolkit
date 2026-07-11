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
``check_inventories`` (DD-047).  The AI extraction itself stays in the skill;
only the tracking is implemented here so it can be unit-tested and surfaced via
the ``discovery-status`` CLI command.

Extraction files live in ``ontology-hub/businessdiscovery/_extractions/`` and are
committed to git so the provenance travels with the hub.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .inventory import compute_source_hash

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


def extraction_filename(doc_path: Path | str) -> str:
    """Return the deterministic extraction filename for a source document."""
    name = Path(doc_path).name
    return f"{slugify_source_name(name)}{EXTRACTION_SUFFIX}"


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
    """Return the sorted list of source documents under *import_dir*.

    Only the top level of ``.import/businessdiscovery/`` is scanned; the
    ``_extractions/`` outputs live elsewhere (under ``ontology-hub/``) so there is
    no nesting to exclude here.  READMEs and dotfiles are ignored.
    """
    if not import_dir.is_dir():
        return []
    return sorted(p for p in import_dir.iterdir() if is_discovery_document(p))


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

    Each list holds the source document filename (as dropped in
    ``.import/businessdiscovery/``); *orphan* holds extraction file names that no
    longer have a matching source document.
    """

    unprocessed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unverifiable: list[str] = field(default_factory=list)
    ok: list[str] = field(default_factory=list)
    orphan: list[str] = field(default_factory=list)

    @property
    def has_work(self) -> bool:
        """True when a document is new (unprocessed) or has changed since extraction."""
        return bool(self.unprocessed or self.changed)

    @property
    def has_warnings(self) -> bool:
        """True when an extraction has no stored hash, or is orphaned."""
        return bool(self.unverifiable or self.orphan)


def check_discovery_docs(
    *,
    import_dir: Path,
    extraction_dir: Path,
) -> DiscoveryStatusReport:
    """Deterministically classify discovery documents against their extractions.

    For every source document under *import_dir*, checks that a matching
    extraction file (named via :func:`extraction_filename`) exists under
    *extraction_dir* and that its stored ``source_sha256`` matches the current
    document content.

    Classification (mirrors :class:`~kairos_ontology.core.inventory.InventoryCheckReport`):
      - **unprocessed**  — document has no extraction file yet.
      - **changed**      — extraction exists but its stored hash differs.
      - **unverifiable** — extraction exists but has no stored hash → warn.
      - **ok**           — extraction exists and hash matches.
      - **orphan**       — extraction file with no corresponding source document.
    """
    report = DiscoveryStatusReport()
    seen_files: set[str] = set()

    for doc in iter_discovery_documents(import_dir):
        fname = extraction_filename(doc)
        seen_files.add(fname)
        yaml_path = extraction_dir / fname

        if not yaml_path.exists():
            report.unprocessed.append(doc.name)
            continue

        try:
            extraction = load_extraction(yaml_path)
        except Exception:
            report.changed.append(doc.name)
            continue

        stored = extraction.get("source_sha256")
        if not stored:
            report.unverifiable.append(doc.name)
            continue

        if stored != compute_source_hash(doc):
            report.changed.append(doc.name)
        else:
            report.ok.append(doc.name)

    if extraction_dir.is_dir():
        for ext_file in sorted(extraction_dir.glob(f"*{EXTRACTION_SUFFIX}")):
            if ext_file.name not in seen_files:
                report.orphan.append(ext_file.name)

    return report
