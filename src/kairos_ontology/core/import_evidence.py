# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Staged business evidence that never reached the hub (DD-233).

``.import/`` is where a human drops the things only they can supply: the client's own
documents, and the Power BI models that say what the business already measures. Every
other input the pipeline can re-derive; these two it cannot.

Until now nothing checked that any of it was used. ``discovery-status`` reported on
``.import/businessdiscovery/`` alone and said "nothing to check" for an empty directory,
which reads identically whether the client sent no documents or thirty documents filed
one directory across. On a real hub that is exactly what happened: roughly thirty client
documents sat in ``.import/Input/`` and eight Power BI models in ``.import/Powerbi_out/``,
invisible to every command, while the hub was modelled from source column names alone.

This module answers one question — *is there business evidence staged that nothing
downstream has consumed?* — in three forms:

``unextracted``
    A document in ``.import/businessdiscovery/`` with no ``*.extraction.yaml``. The
    convention is followed, the work simply has not been done.

``unimported``
    A Power BI / TMDL export under ``.import/`` with no artifact in
    ``integration/discovery/bi/``. ``import-tmdl`` was never pointed at it.

``misplaced``
    A business document under ``.import/`` but outside every directory any command
    reads. The most dangerous of the three: the operator has supplied the evidence and
    has no way to discover that nothing can see it.

Reporting is deterministic and reads no file contents — extensions, paths and the
presence of sibling artifacts only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Rule id for the gate, quoted in diagnostics the way DD-164/DD-169 are.
IMPORT_EVIDENCE_RULE_ID = "DD-233"

#: Directories under ``.import/`` that a command actually reads.
#:
#: ``businessdiscovery`` feeds kairos-design-discovery; ``powerbi`` feeds import-tmdl;
#: ``modeling`` holds the feedback ledger, which is hub output rather than client input.
KNOWN_IMPORT_DIRS = ("businessdiscovery", "powerbi", "modeling")

#: Document kinds that carry business context. Deliberately narrow: a stray .txt or .csv
#: is far more likely to be scratch than a briefing, and a false "you forgot this" is
#: how a gate gets disabled.
BUSINESS_DOC_SUFFIXES = frozenset(
    {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".md"}
)

#: Markers that identify a Power BI / TMDL export folder.
PBI_MARKERS = (".pbip", "model.tmdl", "database.tmdl")


@dataclass(slots=True)
class ImportFinding:
    """One piece of staged evidence nothing downstream has consumed."""

    kind: str  # unextracted | unimported | misplaced
    path: str  # repo-relative, POSIX
    detail: str
    remediation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "detail": self.detail,
            "remediation": self.remediation,
            "rule_id": IMPORT_EVIDENCE_RULE_ID,
        }


@dataclass(slots=True)
class ImportEvidenceReport:
    """What is staged, and what of it has been consumed."""

    documents_total: int = 0
    documents_extracted: int = 0
    powerbi_total: int = 0
    powerbi_imported: int = 0
    findings: list[ImportFinding] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)

    @property
    def unused(self) -> list[ImportFinding]:
        return list(self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "documents_total": self.documents_total,
            "documents_extracted": self.documents_extracted,
            "powerbi_total": self.powerbi_total,
            "powerbi_imported": self.powerbi_imported,
            "findings": [f.to_dict() for f in self.findings],
            "notices": list(self.notices),
        }


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_hidden(path: Path, root: Path) -> bool:
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def find_powerbi_exports(import_dir: Path) -> list[Path]:
    """Power BI / TMDL exports staged under ``.import/``.

    Matched on the marker files Power BI writes rather than on folder naming, because
    whoever exported it chose the folder name. Two shapes count, and they are not the
    same thing:

    * a directory holding ``model.tmdl``/``database.tmdl`` — the model itself;
    * a ``.pbip`` pointer file — a project pointer ``import-tmdl`` accepts directly.

    They must not be collapsed by nesting. A staging folder that happens to hold one
    loose ``.pbip`` beside three real export folders would otherwise report as a single
    export and hide all three, which is precisely the under-reporting this gate exists
    to prevent. A pointer is dropped only when the model folder it names is itself
    already reported.
    """
    if not import_dir.is_dir():
        return []

    model_dirs: set[Path] = set()
    for marker in ("model.tmdl", "database.tmdl"):
        for hit in import_dir.glob(f"**/{marker}"):
            if not _is_hidden(hit, import_dir):
                model_dirs.add(hit.parent)

    pointers: list[Path] = []
    for hit in sorted(import_dir.glob("**/*.pbip")):
        if _is_hidden(hit, import_dir):
            continue
        # The canonical layout puts the model at <name>.SemanticModel/definition/, so
        # the reported directory is the `definition` child rather than the folder the
        # pointer names -- compare on containment, not equality.
        named = hit.parent / f"{hit.stem}.SemanticModel"
        if any(d == named or named in d.parents for d in model_dirs):
            continue
        if hit.parent in model_dirs:
            continue
        pointers.append(hit)

    return sorted(model_dirs | set(pointers))


def find_misplaced_documents(import_dir: Path) -> list[Path]:
    """Business documents staged under ``.import/`` where no command will look."""
    if not import_dir.is_dir():
        return []
    misplaced: list[Path] = []
    for path in import_dir.rglob("*"):
        if not path.is_file() or _is_hidden(path, import_dir):
            continue
        if path.suffix.lower() not in BUSINESS_DOC_SUFFIXES:
            continue
        rel = path.relative_to(import_dir)
        if rel.parts and rel.parts[0] in KNOWN_IMPORT_DIRS:
            continue
        if path.name.upper().startswith("README"):
            continue
        misplaced.append(path)
    return sorted(misplaced)


def audit_import_evidence(repo_root: Path, hub_root: Path) -> ImportEvidenceReport:
    """Report every piece of staged business evidence nothing downstream consumed.

    *repo_root* holds ``.import/``; *hub_root* is the ``ontology-hub/`` directory that
    holds the artifacts proving consumption.
    """
    repo_root = Path(repo_root)
    hub_root = Path(hub_root)
    report = ImportEvidenceReport()
    import_dir = repo_root / ".import"
    if not import_dir.is_dir():
        report.notices.append("no .import/ directory; nothing is staged.")
        return report

    # 1. Discovery documents versus their extractions.
    from .discovery_extraction import extraction_filename, iter_discovery_documents

    discovery_dir = import_dir / "businessdiscovery"
    extraction_dir = hub_root / "businessdiscovery" / "_extractions"
    documents = iter_discovery_documents(discovery_dir)
    report.documents_total = len(documents)
    for doc in documents:
        rel_name = doc.relative_to(discovery_dir).as_posix()
        if (extraction_dir / extraction_filename(doc, relative_path=rel_name)).is_file():
            report.documents_extracted += 1
            continue
        report.findings.append(
            ImportFinding(
                kind="unextracted",
                path=_rel(doc, repo_root),
                detail="staged for business discovery but never extracted",
                remediation=(
                    "Run the kairos-design-discovery skill, or "
                    "'kairos-ontology discovery-status' to see the full list."
                ),
            )
        )

    # 2. Power BI exports versus import-tmdl's output.
    bi_dir = hub_root / "integration" / "discovery" / "bi"
    imported_stems = {
        p.name.removesuffix("-engineering-pack.md")
        for p in bi_dir.glob("*-engineering-pack.md")
    } if bi_dir.is_dir() else set()
    for export in find_powerbi_exports(import_dir):
        report.powerbi_total += 1
        stem = export.name.removesuffix(".SemanticModel").removesuffix(".Report")
        if stem in imported_stems:
            report.powerbi_imported += 1
            continue
        report.findings.append(
            ImportFinding(
                kind="unimported",
                path=_rel(export, repo_root),
                detail=(
                    "a Power BI / TMDL export with no engineering pack in "
                    "integration/discovery/bi/"
                ),
                remediation=f"Run: kairos-ontology import-tmdl {_rel(export, repo_root)}",
            )
        )

    # 3. Documents filed where nothing looks.
    for doc in find_misplaced_documents(import_dir):
        report.findings.append(
            ImportFinding(
                kind="misplaced",
                path=_rel(doc, repo_root),
                detail=(
                    "a business document under .import/ but outside every directory a "
                    "command reads, so nothing can see it"
                ),
                remediation=(
                    "Move it under .import/businessdiscovery/ (subfolders are scanned "
                    "recursively), or under .import/powerbi/ if it is a report export."
                ),
            )
        )

    return report
