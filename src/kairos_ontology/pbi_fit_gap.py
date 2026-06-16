# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Power BI / source fit-gap simulation + gold seed (Slice 5, DD-EL-7).

Deterministic, AI-free reconciliation of existing **reporting demand** (a parsed
Power BI TMDL/PBIP model) against approved **source supply** (the domain Claim
Registry).  Power BI is treated as *evidence, not authority* (methodology §3.5 /
§7): the fit-gap report **informs** claims, it never approves them, and the gold
seed it can emit is a human-confirmed candidate.

Two capabilities:

* :func:`run_fit_gap` classifies every PBI field / measure / relationship against
  the registry and renders a markdown report (methodology §7.3 taxonomy).
* :func:`seed_gold_ext` seeds a *candidate* gold-extension TTL (measure +
  hierarchy annotations) from the PBI model for the ``kairos-design-gold`` skill.

Deterministic linkage (no LLM):

* **claim ↔ PBI** — a claim is linked to a PBI table through its
  ``tmdl_concept_mapping`` evidence (``model`` / ``table``), produced upstream by
  ``import-tmdl`` + ``derive-claims``.
* **source-backed** — a claim carries at least one evidence source whose ``type``
  is in :data:`SOURCE_EVIDENCE_TYPES` with a non-empty ``system``.
* **passthrough** — the claim's ``disposition`` is ``passthrough``.
"""

from __future__ import annotations

import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .claim_registry import Claim, ClaimRegistry
from .tmdl_parser import (
    TmdlModel,
    TmdlTable,
    parse_model_folder,
    parse_tmdl_content,
)

logger = logging.getLogger(__name__)

# --- Classification vocabulary (methodology §7.3) --------------------------
FIT = "fit"
GAP = "gap"
DEFER = "defer"
REJECT = "reject"
PASSTHROUGH_DEPENDENCY = "passthrough-dependency"
SOURCE_UNUSED = "source-unused"

#: Evidence ``type`` values that establish a source (supply) link for a claim.
SOURCE_EVIDENCE_TYPES = frozenset(
    {"source_table", "source_column", "affinity", "skos_mapping", "sample_signal"}
)

#: ``Table[Column]`` / ``'Table Name'[Column]`` / ``[Measure]`` references in DAX.
_DAX_REF = re.compile(r"(?:'([^']+)'|([A-Za-z_][\w]*))?\[([^\]]+)\]")


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class FitGapFinding:
    """A single fit-gap classification for one PBI artifact."""

    kind: str  # "field" | "measure" | "relationship" | "source-unused"
    name: str
    classification: str
    reason: str
    claim_ids: list[str] = field(default_factory=list)


@dataclass
class FitGapReport:
    """The full fit-gap result for one domain across one or more PBI models."""

    domain: str
    models: list[str]
    findings: list[FitGapFinding] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """Return classification → count across all findings."""
        out: dict[str, int] = {}
        for f in self.findings:
            out[f.classification] = out.get(f.classification, 0) + 1
        return out

    def by_kind(self, kind: str) -> list[FitGapFinding]:
        return [f for f in self.findings if f.kind == kind]


# ---------------------------------------------------------------------------
# Registry helpers (deterministic linkage)
# ---------------------------------------------------------------------------


def is_source_backed(claim: Claim) -> bool:
    """True if the claim has any source-supply evidence (§7.1)."""
    return any(
        ev.type in SOURCE_EVIDENCE_TYPES and ev.system for ev in claim.evidence_sources
    )


def _pbi_table_claims(
    registry: ClaimRegistry, model_name: str | None, table_name: str
) -> list[Claim]:
    """Claims linked to a PBI table via ``tmdl_concept_mapping`` evidence."""
    target = table_name.lower()
    out: list[Claim] = []
    for claim in registry.claims:
        for ev in claim.evidence_sources:
            if ev.type != "tmdl_concept_mapping" or not ev.table:
                continue
            if ev.table.lower() != target:
                continue
            if model_name and ev.model and ev.model.lower() != model_name.lower():
                continue
            out.append(claim)
            break
    return out


@dataclass
class _TableVerdict:
    classification: str | None  # None = no claim at all
    passthrough: bool
    claim_ids: list[str]


def _classify_table(linked: list[Claim]) -> _TableVerdict:
    """Resolve the best verdict for a PBI table from its linked claims."""
    approved = [c for c in linked if c.status == "approved"]
    materializing = [
        c for c in approved if c.disposition in ("claim", "specialize") and is_source_backed(c)
    ]
    if materializing:
        return _TableVerdict(FIT, False, [c.id for c in materializing])
    passthrough = [
        c for c in approved if c.disposition == "passthrough" and is_source_backed(c)
    ]
    if passthrough:
        return _TableVerdict(FIT, True, [c.id for c in passthrough])
    if linked:
        return _TableVerdict(GAP, False, [c.id for c in linked])
    return _TableVerdict(None, False, [])


# ---------------------------------------------------------------------------
# Fit-gap simulation
# ---------------------------------------------------------------------------


@dataclass
class _FieldState:
    classification: str
    passthrough: bool
    claim_ids: list[str]


def _classify_field(verdict: _TableVerdict, *, hidden: bool) -> _FieldState:
    if verdict.classification is None:
        # No claim links to this table → legacy / unused report artifact.
        return _FieldState(REJECT if hidden else DEFER, False, [])
    return _FieldState(verdict.classification, verdict.passthrough, verdict.claim_ids)


def _dax_references(expression: str) -> list[tuple[str | None, str]]:
    """Extract ``(table_or_None, name)`` references from a DAX expression."""
    refs: list[tuple[str | None, str]] = []
    for quoted, bare, inner in _DAX_REF.findall(expression or ""):
        table = quoted or bare or None
        refs.append((table.strip() if table else None, inner.strip()))
    return refs


def run_fit_gap(
    model: TmdlModel, registry: ClaimRegistry, *, model_name: str | None = None
) -> FitGapReport:
    """Classify every PBI field / measure / relationship against the registry."""
    name = model_name or model.name
    report = FitGapReport(domain=registry.domain, models=[name] if name else [])

    table_verdict: dict[str, _TableVerdict] = {}
    # (table_lower, column_lower) -> field state ; table_lower -> field states
    field_state: dict[tuple[str, str], _FieldState] = {}

    for table in model.tables:
        verdict = _classify_table(_pbi_table_claims(registry, name, table.name))
        table_verdict[table.name.lower()] = verdict
        for col in table.columns:
            state = _classify_field(verdict, hidden=col.is_hidden or table.is_hidden)
            field_state[(table.name.lower(), col.name.lower())] = state
            report.findings.append(
                FitGapFinding(
                    kind="field",
                    name=f"{table.name}[{col.name}]",
                    classification=state.classification,
                    reason=_field_reason(state, verdict),
                    claim_ids=list(state.claim_ids),
                )
            )

    # Measures depend on fields — classify by the worst dependency.
    for table in model.tables:
        for measure in table.measures:
            report.findings.append(
                _classify_measure(table, measure, field_state, table_verdict)
            )

    # Relationships — fit only when both endpoints are fit.
    for rel in model.relationships:
        report.findings.append(_classify_relationship(rel, field_state, table_verdict))

    # Source supply without reporting demand — approved source-backed claims that
    # carry no PBI (tmdl) evidence at all (§7.3 row 7).
    for claim in registry.claims:
        if claim.status != "approved" or not is_source_backed(claim):
            continue
        has_pbi = any(ev.type == "tmdl_concept_mapping" for ev in claim.evidence_sources)
        if has_pbi:
            continue
        systems = sorted(
            {ev.system for ev in claim.evidence_sources if ev.system and ev.type in SOURCE_EVIDENCE_TYPES}
        )
        report.findings.append(
            FitGapFinding(
                kind="source-unused",
                name=claim.identifying_uri() or claim.id,
                classification=SOURCE_UNUSED,
                reason=(
                    "approved source-backed claim with no Power BI usage "
                    f"(source: {', '.join(systems) or 'unknown'}) — passthrough/model on business value"
                ),
                claim_ids=[claim.id],
            )
        )

    return report


def _field_reason(state: _FieldState, verdict: _TableVerdict) -> str:
    if state.classification == FIT and state.passthrough:
        return "covered by an approved passthrough claim (source-backed)"
    if state.classification == FIT:
        return "covered by an approved source-backed claim"
    if state.classification == GAP:
        return "linked claim has no source supply (or is not approved) — investigate source or reject"
    if state.classification == REJECT:
        return "hidden PBI field with no claim — legacy/technical artifact"
    return "visible PBI field with no claim — approve, defer, or reject"


def _classify_measure(
    table: TmdlTable,
    measure,
    field_state: dict[tuple[str, str], _FieldState],
    table_verdict: dict[str, _TableVerdict],
) -> FitGapFinding:
    refs = _dax_references(measure.expression)
    resolved: list[_FieldState] = []
    own = table.name.lower()
    for ref_table, ref_name in refs:
        key = (ref_table.lower(), ref_name.lower()) if ref_table else (own, ref_name.lower())
        state = field_state.get(key)
        if state is None and not ref_table:
            # Bare ``[Name]`` that is not a column in this table → likely a
            # measure reference; skip (handled by its own classification).
            continue
        if state is None and ref_table:
            # References a field of a table with no governed claim.
            verdict = table_verdict.get(ref_table.lower())
            cls = verdict.classification if verdict else None
            state = _FieldState(cls or DEFER, False, [])
        if state is not None:
            resolved.append(state)

    name = f"{table.name}[{measure.name}]"
    if any(s.passthrough for s in resolved):
        return FitGapFinding(
            "measure", name, PASSTHROUGH_DEPENDENCY,
            "depends on a passthrough field — review for promotion to a modeled property",
            sorted({cid for s in resolved for cid in s.claim_ids}),
        )
    if any(s.classification in (GAP, DEFER, REJECT) for s in resolved):
        return FitGapFinding(
            "measure", name, GAP,
            "depends on an ungoverned/unsourced field — investigate source or reject",
            sorted({cid for s in resolved for cid in s.claim_ids}),
        )
    if resolved:
        return FitGapFinding(
            "measure", name, FIT,
            "all referenced fields are covered by approved source-backed claims",
            sorted({cid for s in resolved for cid in s.claim_ids}),
        )
    return FitGapFinding(
        "measure", name, DEFER,
        "PBI-only calculated measure — model as a gold measure if still needed",
        [],
    )


def _classify_relationship(
    rel,
    field_state: dict[tuple[str, str], _FieldState],
    table_verdict: dict[str, _TableVerdict],
) -> FitGapFinding:
    from_state = field_state.get((rel.from_table.lower(), rel.from_column.lower()))
    to_state = field_state.get((rel.to_table.lower(), rel.to_column.lower()))
    name = (
        f"{rel.from_table}[{rel.from_column}] → {rel.to_table}[{rel.to_column}]"
    )
    inactive = "" if rel.is_active else " (inactive)"
    claim_ids = sorted(
        {cid for s in (from_state, to_state) if s for cid in s.claim_ids}
    )
    if from_state and to_state and from_state.classification == FIT and to_state.classification == FIT:
        return FitGapFinding(
            "relationship", name, FIT,
            f"both endpoints covered by approved source-backed claims{inactive}",
            claim_ids,
        )
    return FitGapFinding(
        "relationship", name, GAP,
        f"endpoint(s) not covered by an approved source-backed claim — "
        f"review FK/grain, do not copy blindly{inactive}",
        claim_ids,
    )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

_ORDER = [FIT, GAP, PASSTHROUGH_DEPENDENCY, DEFER, REJECT, SOURCE_UNUSED]


def render_report(report: FitGapReport) -> str:
    """Render a fit-gap :class:`FitGapReport` to markdown (methodology §7.3)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    counts = report.counts()
    lines = [
        f"# Power BI / source fit-gap — {report.domain}",
        "",
        f"Generated: {now}",
        f"Models: {', '.join(report.models) or '(none)'}",
        "",
        "> Power BI is **evidence, not authority**. This report *informs* claim "
        "decisions; it does not approve them.",
        "",
        "## Summary",
        "",
        "| Classification | Count |",
        "|---|---:|",
    ]
    for cls in _ORDER:
        if cls in counts:
            lines.append(f"| {cls} | {counts[cls]} |")
    lines.append("")

    def _section(title: str, kind: str) -> None:
        rows = report.by_kind(kind)
        if not rows:
            return
        lines.extend([f"## {title}", "", "| Artifact | Classification | Claims | Notes |", "|---|---|---|---|"])
        for f in rows:
            claims = ", ".join(f.claim_ids) if f.claim_ids else "—"
            lines.append(f"| `{f.name}` | {f.classification} | {claims} | {f.reason} |")
        lines.append("")

    _section("Fields", "field")
    _section("Measures", "measure")
    _section("Relationships", "relationship")
    _section("Source supply without reporting demand", "source-unused")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gold-extension seed (candidate, human-confirmed)
# ---------------------------------------------------------------------------


def _camel(name: str) -> str:
    """Sanitize a PBI artifact name into a camelCase local name."""
    parts = re.split(r"[^0-9A-Za-z]+", name.strip())
    parts = [p for p in parts if p]
    if not parts:
        return "unnamed"
    first = parts[0]
    head = first if first[:1].islower() else first[:1].lower() + first[1:]
    return head + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def _derive_namespace(registry: ClaimRegistry | None) -> str | None:
    """Best-effort domain namespace from the registry's class/property URIs."""
    if registry is None:
        return None
    for claim in registry.claims:
        uri = claim.identifying_uri()
        if uri and "#" in uri:
            return uri.rsplit("#", 1)[0] + "#"
    return None


def seed_gold_ext(
    model: TmdlModel,
    domain: str,
    *,
    namespace: str | None = None,
    registry: ClaimRegistry | None = None,
    model_name: str | None = None,
) -> str:
    """Seed a *candidate* gold-ext TTL (measure + hierarchy annotations).

    The output is a human-confirm candidate for ``kairos-design-gold`` — it is
    never auto-applied.  Measures become ``kairos-ext:measureExpression`` /
    ``measureFormatString`` annotations; hierarchy levels become
    ``kairos-ext:hierarchyName`` / ``hierarchyLevel`` annotations.
    """
    from rdflib import Graph, Literal, Namespace, URIRef

    ns_uri = namespace or _derive_namespace(registry) or f"https://example.invalid/ontology/{domain}#"
    if not ns_uri.endswith(("#", "/")):
        ns_uri += "#"
    DOMAIN = Namespace(ns_uri)
    EXT = Namespace("https://kairos.cnext.eu/ext#")

    graph = Graph()
    graph.bind(domain, DOMAIN)
    graph.bind("kairos-ext", EXT)

    name = model_name or model.name
    seen: set[str] = set()
    for table in model.tables:
        for measure in table.measures:
            local = _camel(measure.name)
            if local in seen:
                local = _camel(f"{table.name} {measure.name}")
            seen.add(local)
            subj = URIRef(str(DOMAIN) + local)
            if measure.expression:
                graph.add((subj, EXT.measureExpression, Literal(measure.expression)))
            if measure.format_string:
                graph.add((subj, EXT.measureFormatString, Literal(measure.format_string)))
        for hierarchy in table.hierarchies:
            for level in hierarchy.levels:
                local = _camel(level.column or level.name)
                subj = URIRef(str(DOMAIN) + local)
                graph.add((subj, EXT.hierarchyName, Literal(hierarchy.name)))
                graph.add((subj, EXT.hierarchyLevel, Literal(level.ordinal + 1)))

    body = graph.serialize(format="turtle")
    banner = (
        f"# CANDIDATE gold-extension seed for domain '{domain}' (Slice 5 / DD-EL-7).\n"
        f"# Generated from Power BI model: {name or '(unnamed)'}.\n"
        "# Power BI is evidence, not authority — review every annotation and map\n"
        "# each subject URI onto a real domain property before use. The local names\n"
        "# below are derived from PBI artifact names and are placeholders.\n"
        "# Not consumed by projections until confirmed via kairos-design-gold.\n\n"
    )
    return banner + body


# ---------------------------------------------------------------------------
# Source loading (zip / folder / standalone .tmdl)
# ---------------------------------------------------------------------------


def load_models(source: Path) -> list[TmdlModel]:
    """Parse a TMDL/PBIP SOURCE (zip, folder, or .tmdl file) into models."""
    from .import_tmdl import detect_input_type, extract_pbip_zip, find_definition_dirs

    input_type = detect_input_type(source)
    models: list[TmdlModel] = []

    if input_type == "zip":
        import tempfile

        dest = Path(tempfile.mkdtemp(prefix="kairos-tmdl-"))
        try:
            for def_dir in extract_pbip_zip(source, dest):
                models.append(parse_model_folder(def_dir))
        except zipfile.BadZipFile as exc:  # pragma: no cover - defensive
            logger.warning("Bad PBIP zip %s: %s", source, exc)
    elif input_type == "folder":
        for def_dir in find_definition_dirs(source):
            models.append(parse_model_folder(def_dir))
    else:  # standalone .tmdl
        content = source.read_text(encoding="utf-8")
        model = TmdlModel(name=source.stem)
        for item in parse_tmdl_content(content):
            if isinstance(item, TmdlTable):
                model.tables.append(item)
            else:
                model.relationships.append(item)
        models.append(model)

    return models
