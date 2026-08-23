# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Modeling-feedback knowledge-snippet records: parser, validator, and serializer.

A lighter-weight, OKF-style sibling of the hub Decision Log (`core/decision_records.py`,
DD-141): a running design/business observation, captured before it becomes (or instead
of) a `kairos-ontology decision`. Where a Decision Record documents a genuine tension
resolved between alternatives, a feedback record is just an observation worth keeping —
so there is no materiality/lifecycle state machine, no supersession graph, and evidence
is never mandatory.

Records live under ``.import/modeling/feedback/`` (a sibling of ``ontology-hub/``, not
inside it) — a toolkit-managed, git-tracked location for OKF-style structured records
distinct from raw client evidence under ``.import/businessdiscovery/`` (#591). Originally
placed at ``.import/businessdiscovery/insights/`` (#608); relocated because that path
both misdescribed the content (these are ontology-modeling observations, not
business-discovery evidence) and sat inside a blanket-gitignored tree with no tracking
carve-out.

Source-path resolution (``_is_local_path``/``_source_citation_resolves``) and the
provenance/timestamp helpers (``rfc3339_now``, ``producer_actor``) are reused directly
from :mod:`kairos_ontology.core.decision_records` rather than duplicated — the citation
convention is identical, and the two modules should never diverge on it.

The module is pure and has no side effects beyond reading/writing the files it is asked
to touch. It lives in :mod:`kairos_ontology.core` and must never import
:mod:`kairos_ontology.mdm`.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .decision_records import (
    _is_local_path,
    _rfc3339_ok,
    _source_citation_resolves,
    producer_actor,
    rfc3339_now,
    split_frontmatter,
)
from .hub_utils import find_hub_root

# --- bundle conventions ------------------------------------------------------

#: Glob that selects feedback *records*. README/index/templates are excluded.
RECORD_GLOB = "HUB-FB-*.md"

#: Reserved filenames plus the managed README; never treated as records.
RESERVED_FILENAMES = frozenset({"index.md", "README.md"})

#: The OKF ``type`` value used for feedback records.
FEEDBACK_TYPE = "Modeling Feedback"

#: Feedback workflow states. No lifecycle/materiality state machine -- this is the
#: one deliberate simplification versus the Decision Log.
VALID_STATUS = frozenset({"open", "resolved"})

_ID_RE = re.compile(r"^HUB-FB-[A-Za-z0-9][A-Za-z0-9-]*$")
_ACTOR_RE = re.compile(r"^(?:[\w.-]+/[\w.\-:+]+|human:[\w.-]+|process:[\w.-]+)$")


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackDiagnostic:
    """A single feedback-bundle finding, tagged with its diagnostic class."""

    level: str  # "error" | "warning"
    category: str  # "okf_conformance" | "kairos_feedback"
    code: str
    message: str
    file: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FeedbackRecord:
    """A parsed OKF feedback record (frontmatter + body), before/after validation."""

    path: Path
    frontmatter: dict[str, Any]
    body: str
    id: str | None = None
    title: str | None = None
    type: str | None = None
    area: str | None = None
    status: str | None = None
    generated: Any = None
    sources: list[Any] = field(default_factory=list)


@dataclass
class FeedbackValidationResult:
    """The outcome of validating a feedback bundle."""

    feedback_path: Path
    records: list[FeedbackRecord] = field(default_factory=list)
    diagnostics: list[FeedbackDiagnostic] = field(default_factory=list)

    @property
    def errors(self) -> list[FeedbackDiagnostic]:
        return [d for d in self.diagnostics if d.level == "error"]

    @property
    def warnings(self) -> list[FeedbackDiagnostic]:
        return [d for d in self.diagnostics if d.level == "warning"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "feedback_path": str(self.feedback_path),
            "records": [str(r.path) for r in self.records],
            "errors": [d.to_dict() for d in self.errors],
            "warnings": [d.to_dict() for d in self.warnings],
        }


def _coerce_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _record_from_frontmatter(path: Path, fm: dict[str, Any], body: str) -> FeedbackRecord:
    return FeedbackRecord(
        path=path,
        frontmatter=fm,
        body=body,
        id=_coerce_str(fm.get("id")),
        title=_coerce_str(fm.get("title")),
        type=_coerce_str(fm.get("type")),
        area=_coerce_str(fm.get("area")),
        status=_coerce_str(fm.get("status")),
        generated=fm.get("generated"),
        sources=fm.get("sources") if isinstance(fm.get("sources"), list) else [],
    )


# ---------------------------------------------------------------------------
# Bundle discovery
# ---------------------------------------------------------------------------


def iter_record_files(feedback_path: Path) -> list[Path]:
    """Return sorted feedback-record files, excluding reserved and template files."""
    if not feedback_path.is_dir():
        return []
    files = [
        p
        for p in feedback_path.glob(RECORD_GLOB)
        if p.is_file() and p.name not in RESERVED_FILENAMES and not p.name.endswith(".template")
    ]
    return sorted(files, key=lambda p: p.name)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_feedback_bundle(
    feedback_path: Path, *, hub_root: Path | None = None
) -> FeedbackValidationResult:
    """Validate a modeling-feedback bundle at *feedback_path*.

    An absent bundle directory yields an empty, passing result (the capability is
    opt-in). *hub_root* is used only to resolve local ``sources[].resource`` paths
    (feedback records live under ``.import/modeling/feedback/``, a repo-root sibling
    of the hub, not inside it, so it cannot be derived from *feedback_path* itself
    the way the Decision Log derives it from ``<hub_root>/decisions``) -- callers
    that already know the hub root should pass it explicitly; a best-effort lookup
    is attempted otherwise, only affecting the accuracy of source-resolution
    warnings.
    """
    result = FeedbackValidationResult(feedback_path=feedback_path)
    files = iter_record_files(feedback_path)
    seen_ids: dict[str, Path] = {}
    resolved_hub_root = hub_root or find_hub_root(feedback_path, require_model=False) or feedback_path

    for path in files:
        rel = path.name
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            result.diagnostics.append(
                FeedbackDiagnostic(
                    "error", "okf_conformance", "unreadable", f"cannot read record: {exc}", rel
                )
            )
            continue

        fm, body, err = split_frontmatter(text)
        if err is not None or fm is None:
            result.diagnostics.append(
                FeedbackDiagnostic(
                    "error",
                    "okf_conformance",
                    "malformed_frontmatter",
                    err or "malformed frontmatter",
                    rel,
                )
            )
            continue

        record = _record_from_frontmatter(path, fm, body)
        result.records.append(record)
        _validate_record(record, rel, result.diagnostics, seen_ids, resolved_hub_root)

    return result


def _err(diags: list[FeedbackDiagnostic], code: str, msg: str, rel: str, *, category: str) -> None:
    diags.append(FeedbackDiagnostic("error", category, code, msg, rel))


def _warn(diags: list[FeedbackDiagnostic], code: str, msg: str, rel: str, *, category: str) -> None:
    diags.append(FeedbackDiagnostic("warning", category, code, msg, rel))


def _validate_record(
    record: FeedbackRecord,
    rel: str,
    diags: list[FeedbackDiagnostic],
    seen_ids: dict[str, Path],
    hub_root: Path,
) -> None:
    # --- OKF conformance ---------------------------------------------------
    if record.type is None:
        _err(
            diags,
            "missing_type",
            "OKF requires a 'type' field",
            rel,
            category="okf_conformance",
        )
    elif record.type != FEEDBACK_TYPE:
        _warn(
            diags,
            "unexpected_type",
            f"type is '{record.type}', expected '{FEEDBACK_TYPE}'",
            rel,
            category="okf_conformance",
        )

    # --- id ----------------------------------------------------------------
    stem = record.path.stem
    if record.id is None:
        _err(diags, "missing_id", "record requires an 'id'", rel, category="kairos_feedback")
    else:
        if not _ID_RE.match(record.id):
            _err(
                diags,
                "invalid_id",
                f"id '{record.id}' must match HUB-FB-<token>",
                rel,
                category="kairos_feedback",
            )
        if record.id != stem:
            _err(
                diags,
                "id_filename_mismatch",
                f"id '{record.id}' must equal filename stem '{stem}'",
                rel,
                category="kairos_feedback",
            )
        prior = seen_ids.get(record.id)
        if prior is not None:
            _err(
                diags,
                "duplicate_id",
                f"id '{record.id}' already used by {prior.name}",
                rel,
                category="kairos_feedback",
            )
        else:
            seen_ids[record.id] = record.path

    # --- title -------------------------------------------------------------
    if not record.title or not record.title.strip():
        _err(
            diags,
            "missing_title",
            "record requires a non-empty 'title'",
            rel,
            category="kairos_feedback",
        )

    # --- status --------------------------------------------------------------
    if record.status is None:
        _err(diags, "missing_status", "record requires a 'status'", rel, category="kairos_feedback")
    elif record.status not in VALID_STATUS:
        _err(
            diags,
            "invalid_status",
            f"status '{record.status}' not in {sorted(VALID_STATUS)}",
            rel,
            category="kairos_feedback",
        )

    # --- evidence (sources, never mandatory) --------------------------------
    sources = record.sources or []
    if not sources:
        _warn(diags, "no_sources", "record has no evidence 'sources'", rel, category="kairos_feedback")
    else:
        for idx, entry in enumerate(sources):
            if not isinstance(entry, dict) or not entry.get("resource"):
                _err(
                    diags,
                    "invalid_source",
                    f"sources[{idx}] must be a mapping with a 'resource'",
                    rel,
                    category="kairos_feedback",
                )
                continue
            resource = entry["resource"]
            if _is_local_path(resource) and not _source_citation_resolves(resource, hub_root):
                _warn(
                    diags,
                    "unresolved_source",
                    f"local source path does not resolve: {resource} (base: {hub_root})",
                    rel,
                    category="kairos_feedback",
                )

    # --- provenance (generated) ---------------------------------------------
    generated = record.generated
    if not isinstance(generated, dict) or not generated.get("by"):
        _err(
            diags,
            "missing_generated_by",
            "record requires 'generated.by' (a producer actor)",
            rel,
            category="kairos_feedback",
        )
    else:
        by = generated.get("by")
        if not isinstance(by, str) or not _ACTOR_RE.match(by):
            _warn(
                diags,
                "actor_convention",
                f"generated.by '{by}' does not follow the OKF actor convention",
                rel,
                category="kairos_feedback",
            )
        at = generated.get("at")
        if at is not None and not _rfc3339_ok(at):
            _warn(
                diags,
                "invalid_datetime",
                f"generated.at '{at}' is not an RFC3339 datetime",
                rel,
                category="kairos_feedback",
            )


# ---------------------------------------------------------------------------
# Authoring helpers (used by the `feedback` CLI; format authority lives here)
# ---------------------------------------------------------------------------

#: Deterministic frontmatter key order for serialized records.
_FRONTMATTER_ORDER = ("type", "id", "title", "area", "status", "generated", "sources")


def generate_feedback_id(when: date, token: str) -> str:
    """Return a collision-safe feedback id: ``HUB-FB-<YYYYMMDD>-<token>``."""
    return f"HUB-FB-{when:%Y%m%d}-{token}"


def new_record_frontmatter(
    *,
    record_id: str,
    title: str,
    version: str,
    area: str | None = None,
    sources: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    """Build frontmatter for a fresh, always-``open`` feedback record."""
    frontmatter: dict[str, Any] = {
        "type": FEEDBACK_TYPE,
        "id": record_id,
        "title": title,
        "area": area,
        "status": "open",
        "generated": {"by": producer_actor(version), "at": rfc3339_now()},
    }
    if sources:
        frontmatter["sources"] = [{"resource": src} for src in sources]
    return frontmatter


def render_body(
    *,
    observation: str,
    implication: str | None = None,
    resolution: str | None = None,
    follow_ups: str | None = None,
) -> str:
    """Render the fixed-section feedback body from authored content."""
    implication_text = implication.strip() if implication and implication.strip() else "<None recorded.>"
    resolution_text = resolution.strip() if resolution and resolution.strip() else "<Not yet resolved.>"
    follow_ups_text = (
        follow_ups.strip() if follow_ups and follow_ups.strip() else "<None recorded.>"
    )
    return (
        "# Observation\n\n"
        f"{observation.strip()}\n\n"
        "# Design implication\n\n"
        f"{implication_text}\n\n"
        "# Resolution\n\n"
        f"{resolution_text}\n\n"
        "# Open follow-ups\n\n"
        f"{follow_ups_text}\n"
    )


def render_new_record(
    *,
    record_id: str,
    title: str,
    version: str,
    observation: str,
    area: str | None = None,
    implication: str | None = None,
    sources: tuple[str, ...] | list[str] = (),
) -> str:
    """Render a complete, ready-to-read OKF feedback record as Markdown."""
    frontmatter = new_record_frontmatter(
        record_id=record_id, title=title, version=version, area=area, sources=sources
    )
    body = render_body(observation=observation, implication=implication)
    return serialize_record(frontmatter, body)


def serialize_record(frontmatter: dict[str, Any], body: str) -> str:
    """Serialize a record to OKF Markdown with deterministic frontmatter ordering."""
    ordered: dict[str, Any] = {}
    for key in _FRONTMATTER_ORDER:
        if key in frontmatter and frontmatter[key] is not None:
            ordered[key] = frontmatter[key]
    for key, value in frontmatter.items():
        if key not in ordered and value is not None:
            ordered[key] = value
    dumped = yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, default_flow_style=False)
    body_text = body if body.endswith("\n") else body + "\n"
    return f"---\n{dumped}---\n\n{body_text}"


_SECTION_RE = r"(^#\s+{heading}\s*\n)(.*?)(?=^#\s+\S|\Z)"


def _set_section(body: str, heading: str, content: str) -> str:
    """Replace *heading*'s section content in *body*, preserving other sections."""
    pattern = re.compile(_SECTION_RE.format(heading=re.escape(heading)), re.MULTILINE | re.DOTALL)
    replacement = f"\\1{content.strip()}\n\n"
    new_body, count = pattern.subn(replacement, body, count=1)
    if count == 0:
        raise ValueError(f"record body has no '# {heading}' section to update")
    return new_body


def resolve_record(text: str, *, note: str, resolved_at: str) -> str:
    """Return *text* with status set to ``resolved`` and the note recorded.

    Raises :class:`ValueError` if the record is malformed or already resolved --
    callers should surface this as a user-facing error rather than silently
    overwriting a prior resolution note.
    """
    fm, body, err = split_frontmatter(text)
    if err is not None or fm is None:
        raise ValueError(err or "malformed frontmatter")
    if fm.get("status") == "resolved":
        raise ValueError("record is already resolved")
    fm = dict(fm)
    fm["status"] = "resolved"
    # split_frontmatter/serialize_record are asymmetric by one newline (the
    # blank line serialize_record inserts after the closing "---" survives
    # into the parsed body rather than being consumed as frontmatter-block
    # delimiter) -- invisible everywhere else in this area of the codebase
    # today because nothing else re-serializes an already-written record, but
    # this is the first place that does. Strip it here rather than change the
    # shared parse/serialize pair, which decision_records.py also depends on.
    body = body.lstrip("\n")
    new_body = _set_section(body, "Resolution", f"{note.strip()}\n\n_Resolved {resolved_at}._")
    return serialize_record(fm, new_body)


def build_index_markdown(records: list[FeedbackRecord]) -> str:
    """Render a deterministic ``index.md`` listing for a feedback bundle."""
    lines = [
        "---",
        "type: Reference",
        "title: Modeling Feedback",
        "description: Index of modeling-feedback knowledge snippets for this hub.",
        "---",
        "",
        "# Modeling Feedback",
        "",
        "Running design/business observations captured before they become (or instead",
        "of) a `kairos-ontology decision`. Generated by `kairos-ontology feedback`; do",
        "not edit by hand.",
        "",
        "| ID | Title | Area | Status |",
        "|----|-------|------|--------|",
    ]
    for record in sorted(records, key=lambda r: r.id or ""):
        rid = record.id or record.path.stem
        title = (record.title or "").replace("|", "\\|")
        area = record.area or ""
        status = record.status or ""
        lines.append(f"| [{rid}](./{record.path.name}) | {title} | {area} | {status} |")
    lines.append("")
    return "\n".join(lines) + "\n"
