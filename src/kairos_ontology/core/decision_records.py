# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""OKF v0.2 hub Decision Log: parser, Kairos-profile validator, and serializer.

This module implements the durable hub *Decision Log* introduced by DD-141. A
decision log is an `Open Knowledge Format`_ (OKF) v0.2 *bundle*: a directory of
Markdown files with YAML frontmatter. Each material modeling decision — a genuine
tension or real gap the team deliberately resolved — is one record
(``HUB-DD-*.md``), so the *why* survives an ontology refresh that only preserves
the *what* in Turtle.

Two diagnostic classes are reported and kept deliberately distinct:

* ``okf_conformance`` — the minimal OKF rules (well-formed frontmatter, a ``type``).
  OKF itself says consumers must tolerate unknown fields/types and must not reject
  documents, so this class is intentionally tiny.
* ``kairos_decision`` — the stricter *Kairos decision profile* (stable ``id``,
  workflow state, evidence, lifecycle consistency, supersession integrity). These
  are a hub-local lint, **not** OKF conformance, and are labelled as such.

The module is pure and has no side effects beyond reading the files it is asked to
validate. It lives in :mod:`kairos_ontology.core` and must never import
:mod:`kairos_ontology.mdm`.

.. _Open Knowledge Format: https://github.com/GoogleCloudPlatform/knowledge-catalog
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .hub_utils import body_is_unedited_template, find_hub_root, resolve_repo_root

# --- OKF bundle conventions -------------------------------------------------

#: Glob that selects decision *records*. README/index/log/templates are excluded.
RECORD_GLOB = "HUB-DD-*.md"

#: Reserved OKF filenames plus the managed README; never treated as records.
RESERVED_FILENAMES = frozenset({"index.md", "log.md", "README.md"})

#: The OKF ``type`` value used for Kairos decision records.
DECISION_TYPE = "Decision Record"

# --- Kairos decision profile vocabularies -----------------------------------

#: OKF lifecycle values (``status`` frontmatter field). Absent means ``stable``.
VALID_LIFECYCLE = frozenset({"draft", "stable", "deprecated"})
DEFAULT_LIFECYCLE = "stable"

#: Kairos decision workflow states (``decision_state`` extension field).
VALID_DECISION_STATES = frozenset({"Proposed", "Accepted", "Rejected", "Superseded"})

#: Structured materiality reasons; at least one is required for an Accepted record.
VALID_MATERIALITY = frozenset(
    {
        "evidence-conflict",
        "credible-alternatives",
        "intentional-standard-divergence",
        "persistent-consequence",
    }
)

#: Decision states whose lifecycle each maps to. Contradictions are errors.
_STATE_TO_LIFECYCLE = {
    "Proposed": "draft",
    "Accepted": "stable",
    "Rejected": "stable",
    "Superseded": "deprecated",
}

#: Decision states for which documentary evidence (``sources``) is mandatory.
_EVIDENCE_REQUIRED_STATES = frozenset({"Accepted", "Rejected"})

_ID_RE = re.compile(r"^HUB-DD-[A-Za-z0-9][A-Za-z0-9-]*$")
_ACTOR_RE = re.compile(r"^(?:[\w.-]+/[\w.\-:+]+|human:[\w.-]+|process:[\w.-]+)$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LOCAL_PATH_PREFIXES = ("./", "../", "/")
#: Extensions (case-insensitive) that mark a bare citation as a followable local
#: path: hub text/config formats plus the binary evidence formats staged under
#: ``.import/`` (#420).
_LOCAL_PATH_SUFFIXES = (".ttl", ".yaml", ".yml", ".md", ".pdf", ".docx", ".xlsx", ".pptx")
#: First path segments that (a) mark a citation as local even without a ``./``
#: prefix and (b) are the *only* segments allowed to fall back to the repo root
#: on a nested hub — both live at the repo root, as siblings of the hub (#420).
_REPO_ROOT_FIRST_SEGMENTS = frozenset({".import", "ontology-reference-models"})
_URI_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecisionDiagnostic:
    """A single decision-log finding, tagged with its diagnostic class."""

    level: str  # "error" | "warning"
    category: str  # "okf_conformance" | "kairos_decision"
    code: str
    message: str
    file: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DecisionRecord:
    """A parsed OKF decision record (frontmatter + body), before/after validation."""

    path: Path
    frontmatter: dict[str, Any]
    body: str
    id: str | None = None
    title: str | None = None
    type: str | None = None
    domain: str | None = None
    status: str | None = None
    decision_state: str | None = None
    materiality: tuple[str, ...] = ()
    confidence: str | None = None
    generated: Any = None
    verified: Any = None
    sources: list[Any] = field(default_factory=list)
    supersedes: tuple[str, ...] = ()
    stale_after: str | None = None


@dataclass
class DecisionValidationResult:
    """The outcome of validating a decision bundle."""

    decisions_path: Path
    records: list[DecisionRecord] = field(default_factory=list)
    diagnostics: list[DecisionDiagnostic] = field(default_factory=list)

    @property
    def errors(self) -> list[DecisionDiagnostic]:
        return [d for d in self.diagnostics if d.level == "error"]

    @property
    def warnings(self) -> list[DecisionDiagnostic]:
        return [d for d in self.diagnostics if d.level == "warning"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decisions_path": str(self.decisions_path),
            "records": [str(r.path) for r in self.records],
            "errors": [d.to_dict() for d in self.errors],
            "warnings": [d.to_dict() for d in self.warnings],
        }


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


def split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str, str | None]:
    """Split OKF Markdown into (frontmatter, body, error).

    Tolerates a UTF-8 BOM and CRLF/CR line endings. Returns ``(None, "", msg)``
    when there is no well-formed frontmatter block, when the YAML fails to parse,
    or when the top-level YAML is not a mapping.
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---\n") and normalized != "---":
        return None, "", "missing YAML frontmatter block (must start with '---')"
    rest = normalized[len("---\n") :] if normalized.startswith("---\n") else ""
    end = rest.find("\n---")
    if end == -1:
        return None, "", "unterminated YAML frontmatter block (no closing '---')"
    fm_text = rest[:end]
    after = rest[end + len("\n---") :]
    body = after[1:] if after.startswith("\n") else after
    try:
        loaded = yaml.safe_load(fm_text) if fm_text.strip() else {}
    except yaml.YAMLError as exc:
        return None, "", f"invalid YAML frontmatter: {exc}"
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        return None, "", "YAML frontmatter must be a mapping"
    return loaded, body, None


def _coerce_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _coerce_date_str(value: Any) -> str | None:
    """Coerce a YAML scalar to an ISO date/datetime string.

    Unquoted ``2027-01-01`` / ``...T..Z`` scalars are parsed by PyYAML into
    :class:`datetime.date` / :class:`datetime.datetime`; normalize them back so
    validation and serialization see a stable string.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None


def _coerce_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _record_from_frontmatter(path: Path, fm: dict[str, Any], body: str) -> DecisionRecord:
    return DecisionRecord(
        path=path,
        frontmatter=fm,
        body=body,
        id=_coerce_str(fm.get("id")),
        title=_coerce_str(fm.get("title")),
        type=_coerce_str(fm.get("type")),
        domain=_coerce_str(fm.get("domain")),
        status=_coerce_str(fm.get("status")),
        decision_state=_coerce_str(fm.get("decision_state")),
        materiality=_coerce_str_tuple(fm.get("materiality")),
        confidence=_coerce_str(fm.get("confidence")),
        generated=fm.get("generated"),
        verified=fm.get("verified"),
        sources=fm.get("sources") if isinstance(fm.get("sources"), list) else [],
        supersedes=_coerce_str_tuple(fm.get("supersedes")),
        stale_after=_coerce_date_str(fm.get("stale_after")),
    )


# ---------------------------------------------------------------------------
# Bundle discovery
# ---------------------------------------------------------------------------


def iter_record_files(decisions_path: Path) -> list[Path]:
    """Return sorted decision-record files, excluding reserved and template files."""
    if not decisions_path.is_dir():
        return []
    files = [
        p
        for p in decisions_path.glob(RECORD_GLOB)
        if p.is_file() and p.name not in RESERVED_FILENAMES and not p.name.endswith(".template")
    ]
    return sorted(files, key=lambda p: p.name)


def _rfc3339_ok(value: Any) -> bool:
    if isinstance(value, (datetime, date)):
        return True
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return True


def _is_local_path(resource: Any) -> bool:
    """True when a source resource is a followable local path (not URL/scope).

    The URI-scheme check runs first and always wins (``https://...`` is never
    local; note this also skips Windows drive paths like ``C:\\...``). A
    citation is local when it has an explicit relative/absolute prefix, starts
    with a repo-root convention segment (``.import/`` evidence — either
    separator), or carries a known citation extension, case-insensitively
    (client evidence arrives as ``.PDF``/``.XLSX`` too) (#420).
    """
    if not isinstance(resource, str) or not resource:
        return False
    if _URI_SCHEME_RE.match(resource):
        return False  # a URL or other scheme
    if resource.startswith(_LOCAL_PATH_PREFIXES):
        return True
    first_segment = resource.replace("\\", "/").split("/", 1)[0]
    if first_segment in _REPO_ROOT_FIRST_SEGMENTS:
        return True
    return resource.lower().endswith(_LOCAL_PATH_SUFFIXES)


def _source_citation_resolves(resource: str, hub_root: Path) -> bool:
    """True when a local source citation resolves to an existing file.

    The base is the hub root, matching every other path-citation convention in
    a hub (issue #349). Backslash separators are normalized first —
    ``.import\\businessdiscovery\\x.pdf`` citations exist in the wild, and
    ``hub_root / "a\\b"`` is a single opaque filename on POSIX.

    On a *nested* hub (a hub inside a toolkit-managed repo root, see
    :func:`resolve_repo_root`) the repo-root siblings ``.import/`` and
    ``ontology-reference-models/`` can never be reached from the hub root, so
    citations whose first segment is one of those two conventions — and only
    those — fall back to the repo root (#420). Any other path never probes the
    repo root: a rotted hub citation must not be silently satisfied by the
    repo's own same-named file (e.g. its ``README.md``).

    A citation whose first segment is the hub directory name (e.g.
    ``ontology-hub/integration/...``) is treated as repo-root-relative and
    resolved from the repo root — this mirrors the path-doubling fix in
    ``sources.py`` (issue #466).
    """
    from .hub_utils import HUB_DIRNAME

    normalized = resource.replace("\\", "/")
    if (hub_root / normalized).resolve().exists():
        return True
    first_segment = normalized.split("/", 1)[0]

    # Repo-root-relative citations (.import/, ontology-reference-models/)
    if first_segment in _REPO_ROOT_FIRST_SEGMENTS:
        repo_root = resolve_repo_root(hub_root)
        if repo_root == hub_root.resolve():
            return False  # standalone/bare hub: the hub root is the only base
        return (repo_root / normalized).resolve().exists()

    # Repo-root-relative citation prefixed with the hub dir name (#466):
    # the user typed what they see on disk (ontology-hub/integration/...)
    # from the repo root — the hub-root-relative form omits that segment.
    if first_segment == HUB_DIRNAME:
        repo_root = resolve_repo_root(hub_root)
        if repo_root == hub_root.resolve():
            return False  # standalone hub: no repo root to try
        remainder = normalized.split("/", 1)[1] if "/" in normalized else ""
        if remainder and (repo_root / normalized).resolve().exists():
            return True
        # Also try stripping the hub-dir prefix (the canonical hub-relative form)
        if remainder and (hub_root / remainder).resolve().exists():
            return True

    return False


def _has_rejected_alternative(body: str) -> bool:
    """Heuristically confirm the body documents at least one rejected alternative."""
    in_section = False
    for raw in body.splitlines():
        heading = re.match(r"^#{1,6}\s+(.*)$", raw)
        if heading:
            in_section = bool(re.search(r"alternativ", heading.group(1), re.IGNORECASE))
            continue
        if not in_section:
            continue
        stripped = raw.strip()
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if any(cells) and not all(set(c) <= set("-:") for c in cells):
                return True
        elif re.match(r"^[-*]\s+\S", stripped):
            return True
    return False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_decision_bundle(decisions_path: Path) -> DecisionValidationResult:
    """Validate an OKF decision bundle at *decisions_path*.

    An absent bundle directory yields an empty, passing result (the capability is
    opt-in). Diagnostics are tagged ``okf_conformance`` or ``kairos_decision``.
    """
    result = DecisionValidationResult(decisions_path=decisions_path)
    files = iter_record_files(decisions_path)
    seen_ids: dict[str, Path] = {}
    hub_root = _resolve_hub_root(decisions_path)

    for path in files:
        rel = path.name
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            result.diagnostics.append(
                DecisionDiagnostic(
                    "error", "okf_conformance", "unreadable", f"cannot read record: {exc}", rel
                )
            )
            continue

        fm, body, err = split_frontmatter(text)
        if err is not None or fm is None:
            result.diagnostics.append(
                DecisionDiagnostic(
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
        _validate_record(record, rel, result.diagnostics, seen_ids, hub_root)

    _validate_supersession_graph(result.records, result.diagnostics)
    return result


def _resolve_hub_root(decisions_path: Path) -> Path:
    """Resolve the hub root that owns *decisions_path*.

    Decision records live at ``<hub_root>/decisions/HUB-DD-*.md`` — the sole
    layout produced by ``decision new`` (see ``cli/decisions.py::_decisions_dir``)
    and assumed by ``validate`` when it passes ``decisions_path`` down to
    :func:`run_validation`. Reuses :func:`find_hub_root` (the codebase's single
    hub-root-discovery helper — see ``core/hub_utils.py``) for the authoritative
    answer when the hub already has real content (``model/ontologies``), and
    falls back to the structural parent of *decisions_path* for a hub that has
    decisions but no ``model/`` yet. This is what ``sources[].resource`` local
    paths must be resolved against — not ``decisions_path`` itself — so a
    citation like ``integration/sources/cargowise/GlbStaff.sample.yaml`` (relative
    to the hub root, the convention every other path citation in a hub follows)
    resolves without an unmotivated ``../`` (issue #349).
    """
    hub_root = find_hub_root(decisions_path.parent, require_model=False)
    return hub_root if hub_root is not None else decisions_path.parent


def _err(
    diags: list[DecisionDiagnostic],
    code: str,
    msg: str,
    rel: str,
    *,
    category: str = "kairos_decision",
) -> None:
    diags.append(DecisionDiagnostic("error", category, code, msg, rel))


def _warn(
    diags: list[DecisionDiagnostic],
    code: str,
    msg: str,
    rel: str,
    *,
    category: str = "kairos_decision",
) -> None:
    diags.append(DecisionDiagnostic("warning", category, code, msg, rel))


def _validate_record(
    record: DecisionRecord,
    rel: str,
    diags: list[DecisionDiagnostic],
    seen_ids: dict[str, Path],
    hub_root: Path,
) -> None:
    # --- OKF conformance ---------------------------------------------------
    if record.type is None:
        _err(diags, "missing_type", "OKF requires a 'type' field", rel, category="okf_conformance")
    elif record.type != DECISION_TYPE:
        _warn(
            diags,
            "unexpected_type",
            f"type is '{record.type}', expected '{DECISION_TYPE}'",
            rel,
            category="okf_conformance",
        )

    # --- id ----------------------------------------------------------------
    stem = record.path.stem
    if record.id is None:
        _err(diags, "missing_id", "record requires an 'id'", rel)
    else:
        if not _ID_RE.match(record.id):
            _err(diags, "invalid_id", f"id '{record.id}' must match HUB-DD-<token>", rel)
        if record.id != stem:
            _err(
                diags,
                "id_filename_mismatch",
                f"id '{record.id}' must equal filename stem '{stem}'",
                rel,
            )
        prior = seen_ids.get(record.id)
        if prior is not None:
            _err(diags, "duplicate_id", f"id '{record.id}' already used by {prior.name}", rel)
        else:
            seen_ids[record.id] = record.path

    # --- title -------------------------------------------------------------
    if not record.title or not record.title.strip():
        _err(diags, "missing_title", "record requires a non-empty 'title'", rel)

    # --- lifecycle / decision_state ---------------------------------------
    lifecycle = record.status
    if lifecycle is not None and lifecycle not in VALID_LIFECYCLE:
        _err(diags, "invalid_status", f"status '{lifecycle}' not in {sorted(VALID_LIFECYCLE)}", rel)
    effective_lifecycle = lifecycle if lifecycle in VALID_LIFECYCLE else DEFAULT_LIFECYCLE

    state = record.decision_state
    if state is None:
        _err(diags, "missing_decision_state", "record requires a 'decision_state'", rel)
    elif state not in VALID_DECISION_STATES:
        _err(
            diags,
            "invalid_decision_state",
            f"decision_state '{state}' not in {sorted(VALID_DECISION_STATES)}",
            rel,
        )
    else:
        expected = _STATE_TO_LIFECYCLE[state]
        if lifecycle is not None and effective_lifecycle != expected:
            _err(
                diags,
                "lifecycle_contradiction",
                (
                    f"decision_state '{state}' implies status '{expected}', "
                    f"not '{effective_lifecycle}'"
                ),
                rel,
            )

    # --- materiality (required for Accepted) ------------------------------
    valid_materiality = [m for m in record.materiality if m in VALID_MATERIALITY]
    for m in record.materiality:
        if m not in VALID_MATERIALITY:
            _warn(diags, "unknown_materiality", f"unknown materiality '{m}'", rel)
    if state == "Accepted" and not valid_materiality:
        _err(
            diags,
            "missing_materiality",
            "an Accepted decision requires >=1 structured 'materiality' reason",
            rel,
        )

    # --- evidence (sources) ------------------------------------------------
    sources = record.sources or []
    if not sources:
        if state in _EVIDENCE_REQUIRED_STATES:
            _err(
                diags,
                "missing_sources",
                f"a {state} decision requires >=1 evidence 'sources' entry",
                rel,
            )
        else:
            _warn(diags, "no_sources", "record has no evidence 'sources'", rel)
    else:
        for idx, entry in enumerate(sources):
            if not isinstance(entry, dict) or not entry.get("resource"):
                _err(
                    diags,
                    "invalid_source",
                    f"sources[{idx}] must be a mapping with a 'resource'",
                    rel,
                )
                continue
            resource = entry["resource"]
            if _is_local_path(resource):
                # Resolved against the hub root (issue #349); on nested hubs,
                # `.import/` and `ontology-reference-models/` citations also
                # try the repo root (#420) — see _source_citation_resolves.
                if not _source_citation_resolves(resource, hub_root):
                    _warn(
                        diags,
                        "unresolved_source",
                                    f"local source path does not resolve: {resource} "
                                    f"(base: {hub_root})",
                                    rel,
                                )

    # --- rejected alternative (required for Accepted) ---------------------
    if state == "Accepted" and not _has_rejected_alternative(record.body):
        _err(
            diags,
            "missing_rejected_alternative",
            "an Accepted decision must document >=1 rejected alternative",
            rel,
        )

    # --- unedited template body (D4, #416c) --------------------------------
    # _has_rejected_alternative above is fooled by the template's own
    # `| <option> | <why it was not chosen> |` placeholder row -- that table
    # row is exactly how an unedited stub currently slips past the Accepted
    # gate. Keying this lint off exact identity with TEMPLATE_BODY catches
    # that stub directly. Severity follows D1's decision (validate is not
    # skill-gate-exempt and folds these errors into `exit(1)`, and a fresh
    # `decision new` record is Proposed *by construction* -- see
    # cli/decisions.py::new_decision's default): a still-unedited Proposed or
    # Rejected record is only a warning (the intended, in-progress workflow
    # must not turn `validate` red); Accepted or Superseded is unambiguously
    # wrong and is an error.
    if body_is_unedited_template(record.body, TEMPLATE_BODY):
        if state in ("Accepted", "Superseded"):
            _err(
                diags,
                "unedited_template_body",
                f"record body is still the unedited scaffold template but decision_state "
                f"is '{state}' -- replace every placeholder section before accepting",
                rel,
            )
        else:
            _warn(
                diags,
                "unedited_template_body",
                "record body still matches the unedited scaffold template",
                rel,
            )

    # --- provenance (generated) -------------------------------------------
    generated = record.generated
    if not isinstance(generated, dict) or not generated.get("by"):
        _err(
            diags, "missing_generated_by", "record requires 'generated.by' (a producer actor)", rel
        )
    else:
        by = generated.get("by")
        if not isinstance(by, str) or not _ACTOR_RE.match(by):
            _warn(
                diags,
                "actor_convention",
                f"generated.by '{by}' does not follow the OKF actor convention",
                rel,
            )
        at = generated.get("at")
        if at is not None and not _rfc3339_ok(at):
            _warn(diags, "invalid_datetime", f"generated.at '{at}' is not an RFC3339 datetime", rel)

    # --- verification (never required, validated when present) -------------
    if record.verified is not None:
        events = record.verified if isinstance(record.verified, list) else [record.verified]
        for ev in events:
            if not isinstance(ev, dict) or not ev.get("by"):
                _warn(diags, "invalid_verified", "each 'verified' entry needs a 'by' actor", rel)

    # --- supersession (this record's side) --------------------------------
    if record.supersedes:
        if record.id in record.supersedes:
            _err(diags, "self_supersede", "record cannot supersede itself", rel)
        if state != "Accepted":
            _err(
                diags,
                "supersede_requires_accept",
                "only an Accepted record may supersede another",
                rel,
            )

    # --- freshness ---------------------------------------------------------
    if record.stale_after is not None:
        if not _DATE_RE.match(record.stale_after):
            _err(
                diags,
                "invalid_stale_after",
                f"stale_after '{record.stale_after}' must be YYYY-MM-DD",
                rel,
            )
        else:
            try:
                when = date.fromisoformat(record.stale_after)
            except ValueError:
                _err(
                    diags,
                    "invalid_stale_after",
                    f"stale_after '{record.stale_after}' is not a valid date",
                    rel,
                )
            else:
                if date.today() >= when:
                    _warn(
                        diags, "stale", f"record is stale (stale_after {record.stale_after})", rel
                    )


def _validate_supersession_graph(
    records: list[DecisionRecord], diags: list[DecisionDiagnostic]
) -> None:
    by_id = {r.id: r for r in records if r.id}
    edges: dict[str, tuple[str, ...]] = {r.id: r.supersedes for r in records if r.id}

    for record in records:
        if not record.id:
            continue
        for target_id in record.supersedes:
            target = by_id.get(target_id)
            if target is None:
                _warn(
                    diags,
                    "dangling_supersedes",
                    f"supersedes unknown record '{target_id}'",
                    record.path.name,
                )
            elif target.decision_state != "Superseded":
                _warn(
                    diags,
                    "target_not_superseded",
                    (
                        f"'{target_id}' is superseded here but its decision_state "
                        f"is '{target.decision_state}'"
                    ),
                    record.path.name,
                )

    # cycle detection over the supersedes graph
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {rid: WHITE for rid in edges}

    def visit(node: str, stack: list[str]) -> None:
        color[node] = GRAY
        for nxt in edges.get(node, ()):
            if nxt not in color:
                continue
            if color[nxt] == GRAY:
                cycle = " -> ".join(stack + [nxt])
                rel = by_id[node].path.name if node in by_id else node
                _err(diags, "supersede_cycle", f"supersedes cycle detected: {cycle}", rel)
            elif color[nxt] == WHITE:
                visit(nxt, stack + [nxt])
        color[node] = BLACK

    for rid in edges:
        if color.get(rid) == WHITE:
            visit(rid, [rid])


# ---------------------------------------------------------------------------
# Authoring helpers (used by the `decision` CLI; format authority lives here)
# ---------------------------------------------------------------------------

#: Deterministic frontmatter key order for serialized records.
_FRONTMATTER_ORDER = (
    "type",
    "id",
    "title",
    "description",
    "domain",
    "status",
    "decision_state",
    "materiality",
    "confidence",
    "tags",
    "generated",
    "verified",
    "sources",
    "supersedes",
    "stale_after",
)


def producer_actor(version: str) -> str:
    """Return the deterministic toolkit producer actor for ``generated.by``."""
    return f"kairos-ontology-toolkit/{version}"


#: The canonical body scaffold for a new decision record (single source of truth
#: shared by the ``decision`` CLI and the hub scaffold template).
TEMPLATE_BODY = """# Context / Finding

<What tension or real gap forced a decision? Cite PII-safe evidence: source
relations/columns, reference-model terms, confirmed business context.>

# Decision

<What we chose, stated plainly.>

# Alternatives rejected

| Option | Why rejected |
|--------|--------------|
| <option> | <why it was not chosen> |

# Consequences

<Downstream effects, required follow-ups, validation caveats.>

# Why future maintainers need this

<Why this rationale must survive an ontology refresh that keeps only the TTL.>
"""


def new_record_frontmatter(
    *,
    record_id: str,
    title: str,
    version: str,
    domain: str | None = None,
    decision_state: str = "Proposed",
    materiality: tuple[str, ...] | list[str] = (),
    sources: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    """Build frontmatter for a fresh record with a consistent lifecycle/provenance."""
    frontmatter: dict[str, Any] = {
        "type": DECISION_TYPE,
        "id": record_id,
        "title": title,
        "domain": domain,
        "status": _STATE_TO_LIFECYCLE.get(decision_state, DEFAULT_LIFECYCLE),
        "decision_state": decision_state,
        "generated": {"by": producer_actor(version), "at": rfc3339_now()},
    }
    if materiality:
        frontmatter["materiality"] = list(materiality)
    if sources:
        frontmatter["sources"] = [{"resource": src} for src in sources]
    return frontmatter


def render_new_record(
    *,
    record_id: str,
    title: str,
    version: str,
    domain: str | None = None,
    decision_state: str = "Proposed",
    materiality: tuple[str, ...] | list[str] = (),
    sources: tuple[str, ...] | list[str] = (),
) -> str:
    """Render a complete, ready-to-edit OKF decision record as Markdown."""
    frontmatter = new_record_frontmatter(
        record_id=record_id,
        title=title,
        version=version,
        domain=domain,
        decision_state=decision_state,
        materiality=materiality,
        sources=sources,
    )
    return serialize_record(frontmatter, TEMPLATE_BODY)


def rfc3339_now() -> str:
    """Return the current UTC time as an RFC3339 datetime (seconds precision)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def generate_decision_id(when: date, token: str) -> str:
    """Return a collision-safe decision id: ``HUB-DD-<YYYYMMDD>-<token>``."""
    return f"HUB-DD-{when:%Y%m%d}-{token}"


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


def build_index_markdown(records: list[DecisionRecord]) -> str:
    """Render a deterministic OKF ``index.md`` listing for a decision bundle.

    Includes a derived ``Superseded by`` column so the reverse of each
    ``supersedes`` edge is visible without storing it redundantly.
    """
    superseded_by: dict[str, list[str]] = {}
    for record in records:
        for target in record.supersedes:
            if record.id:
                superseded_by.setdefault(target, []).append(record.id)

    lines = [
        "---",
        "type: Reference",
        "title: Decision Log",
        "description: Index of material canonical modeling decisions for this hub.",
        "---",
        "",
        "# Decision Log",
        "",
        "Material modeling decisions (tensions and real gaps we resolved). Generated by",
        "`kairos-ontology decision`; do not edit by hand.",
        "",
        "| ID | Title | Domain | State | Superseded by |",
        "|----|-------|--------|-------|---------------|",
    ]
    for record in sorted(records, key=lambda r: r.id or ""):
        rid = record.id or record.path.stem
        title = (record.title or "").replace("|", "\\|")
        domain = record.domain or ""
        state = record.decision_state or ""
        sb = ", ".join(sorted(superseded_by.get(rid, []))) or "—"
        lines.append(f"| [{rid}](./{record.path.name}) | {title} | {domain} | {state} | {sb} |")
    lines.append("")
    return "\n".join(lines) + "\n"
