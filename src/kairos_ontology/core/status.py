# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic lifecycle-status scanner (DD-080).

Produces the *objective* layer of the hub lifecycle state: a per-phase,
per-instance view derived purely from committed hub artifacts (no LLM, no
network).  This is the authoritative source for "what exists" — the
``kairos-flow`` orchestrator and the ``kairos-diagnose-status`` skill consume
it and layer human/agent *continuation context* (open questions, decisions,
intent) on top in ``ontology-hub/.kairos-state/``.

Design split (see DD-080):

  - **scan (this module)** decides ``not-started | in-progress | done`` from
    artifact presence/coverage.  It never emits ``open-questions`` or
    ``blocked`` — those are continuation states owned by the markdown layer.
  - **markdown layer** (``.kairos-state/``) owns intent and resume context.

The scan is intentionally heuristic-but-deterministic: given the same hub on
disk it always returns the same result, which makes it unit-testable and safe
to regenerate on demand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Scan-derived state values (the markdown layer adds open-questions / blocked).
STATE_NOT_STARTED = "not-started"
STATE_IN_PROGRESS = "in-progress"
STATE_DONE = "done"

# Lifecycle phase order (methodology section 4 / kairos-help section 2).
PHASE_ORDER = (
    "discovery",
    "source",
    "domain",
    "mapping",
    "claims",
    "silver",
    "gold",
    "validate",
    "project",
)

_PHASE_TITLES = {
    "discovery": "Business discovery",
    "source": "Source onboarding",
    "domain": "Domain modeling",
    "mapping": "Source-to-domain mapping",
    "claims": "Claim registry",
    "silver": "Silver design",
    "gold": "Gold / Power BI design",
    "validate": "Validation",
    "project": "Projection",
}

# Output sub-paths that indicate a projection target has been generated.
_PROJECT_OUTPUT_DIRS = (
    "medallion/dbt",
    "medallion/powerbi",
    "neo4j",
    "azure-search",
    "a2ui",
    "prompt",
    "report",
)


@dataclass
class InstanceStatus:
    """Objective state of a single instance within a phase.

    An *instance* is a source system, a domain ontology, a mapping pair, etc.
    ``evidence`` lists hub-relative paths that justify the state.
    """

    name: str
    state: str
    evidence: list[str] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "evidence": self.evidence,
            "detail": self.detail,
        }


@dataclass
class PhaseStatus:
    """Objective state of one lifecycle phase, aggregated from its instances."""

    phase: str
    title: str
    state: str
    instances: list[InstanceStatus] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "title": self.title,
            "state": self.state,
            "instances": [i.to_dict() for i in self.instances],
            "detail": self.detail,
        }


@dataclass
class HubStatus:
    """Deterministic objective status of an ontology hub.

    Deliberately excludes any timestamp so the scan is reproducible; callers
    that persist the result stamp ``last_scanned_at`` themselves.
    """

    hub_root: str
    toolkit_version: str
    phases: list[PhaseStatus] = field(default_factory=list)

    def phase(self, name: str) -> PhaseStatus | None:
        for p in self.phases:
            if p.phase == name:
                return p
        return None

    @property
    def next_phase(self) -> str | None:
        """First phase that is not yet ``done`` (the clean-start suggestion)."""
        for p in self.phases:
            if p.state != STATE_DONE:
                return p.phase
        return None

    def to_dict(self) -> dict:
        return {
            "hub_root": self.hub_root,
            "toolkit_version": self.toolkit_version,
            "next_phase": self.next_phase,
            "phases": [p.to_dict() for p in self.phases],
        }


def _rel(path: Path, hub_root: Path) -> str:
    """Return *path* relative to *hub_root* using forward slashes."""
    try:
        return path.relative_to(hub_root).as_posix()
    except ValueError:
        return path.as_posix()


def _aggregate(instances: list[InstanceStatus]) -> str:
    """Aggregate per-instance states into a phase state."""
    if not instances:
        return STATE_NOT_STARTED
    states = {i.state for i in instances}
    if states == {STATE_DONE}:
        return STATE_DONE
    if states == {STATE_NOT_STARTED}:
        return STATE_NOT_STARTED
    return STATE_IN_PROGRESS


def _ttl_files(directory: Path) -> list[Path]:
    """Domain-relevant ``*.ttl`` files (excludes ``_``-prefixed internals)."""
    if not directory.is_dir():
        return []
    return sorted(
        p for p in directory.glob("*.ttl") if not p.name.startswith("_")
    )


def _scan_discovery(hub_root: Path) -> PhaseStatus:
    title = _PHASE_TITLES["discovery"]
    glossary_dir = hub_root / "businessdiscovery"
    extractions = glossary_dir / "_extractions"
    glossaries = list(glossary_dir.glob("*-glossary.ttl")) if glossary_dir.is_dir() else []
    has_extractions = extractions.is_dir() and any(extractions.glob("*.yaml"))
    pending_imports = (hub_root / ".import" / "businessdiscovery")

    evidence: list[str] = []
    if glossaries:
        evidence.extend(_rel(g, hub_root) for g in sorted(glossaries))
    if has_extractions:
        evidence.append(_rel(extractions, hub_root))

    if glossaries:
        state = STATE_DONE
        detail = f"{len(glossaries)} glossary overlay(s) built"
    elif has_extractions:
        state = STATE_IN_PROGRESS
        detail = "extractions present, glossary not yet built"
    elif pending_imports.is_dir() and any(pending_imports.iterdir()):
        state = STATE_IN_PROGRESS
        detail = "discovery documents imported, not yet processed"
    else:
        state = STATE_NOT_STARTED
        detail = "no discovery artifacts"
    return PhaseStatus("discovery", title, state, detail=detail,
                       instances=[InstanceStatus("company", state, evidence, detail)]
                       if state != STATE_NOT_STARTED else [])


def _affinity_for(sources_dir: Path, system_dir: Path, system: str) -> Path | None:
    """Locate an affinity report for *system*, if any."""
    candidates = [
        sources_dir / "_analysis" / f"{system}-affinity.yaml",
        system_dir / "_analysis" / f"{system}-affinity.yaml",
    ]
    for c in candidates:
        if c.is_file():
            return c
    analysis_dir = system_dir / "_analysis"
    if analysis_dir.is_dir():
        found = sorted(analysis_dir.glob("*-affinity.yaml"))
        if found:
            return found[0]
    return None


def _scan_source(hub_root: Path) -> PhaseStatus:
    title = _PHASE_TITLES["source"]
    sources_dir = hub_root / "integration" / "sources"
    instances: list[InstanceStatus] = []
    if sources_dir.is_dir():
        for system_dir in sorted(p for p in sources_dir.iterdir() if p.is_dir()):
            system = system_dir.name
            if system.startswith("_"):
                continue
            vocab = sorted(system_dir.glob("*.vocabulary.ttl"))
            affinity = _affinity_for(sources_dir, system_dir, system)
            evidence: list[str] = []
            if vocab:
                evidence.append(_rel(vocab[0], hub_root))
            if affinity:
                evidence.append(_rel(affinity, hub_root))
            if vocab and affinity:
                state, detail = STATE_DONE, "vocabulary + affinity analysis"
            elif vocab:
                state, detail = STATE_IN_PROGRESS, "vocabulary present, not analysed"
            else:
                state, detail = STATE_NOT_STARTED, "no vocabulary"
            instances.append(InstanceStatus(system, state, evidence, detail))
    return PhaseStatus("source", title, _aggregate(instances), instances=instances,
                       detail=f"{len(instances)} source system(s)")


def _scan_simple_ttl_phase(
    hub_root: Path, phase: str, directory: Path, *, suffix: str | None = None
) -> PhaseStatus:
    """Phase whose instances are TTL files (domain / mapping / silver / gold)."""
    title = _PHASE_TITLES[phase]
    instances: list[InstanceStatus] = []
    if directory.is_dir():
        if suffix:
            files = sorted(directory.glob(f"*{suffix}"))
        else:
            files = _ttl_files(directory)
        for f in files:
            name = f.name[: -len(suffix)] if suffix and f.name.endswith(suffix) else f.stem
            instances.append(
                InstanceStatus(name, STATE_DONE, [_rel(f, hub_root)], "present")
            )
    return PhaseStatus(phase, title, _aggregate(instances), instances=instances,
                       detail=f"{len(instances)} file(s)")


def _scan_claims(hub_root: Path) -> PhaseStatus:
    title = _PHASE_TITLES["claims"]
    claims_dir = hub_root / "model" / "claims"
    instances: list[InstanceStatus] = []
    if claims_dir.is_dir():
        for f in sorted([*claims_dir.glob("*.yaml"), *claims_dir.glob("*.ttl")]):
            instances.append(
                InstanceStatus(f.stem, STATE_DONE, [_rel(f, hub_root)], "claim registry")
            )
    return PhaseStatus("claims", title, _aggregate(instances), instances=instances,
                       detail=f"{len(instances)} claim file(s)")


def _scan_validate(hub_root: Path) -> PhaseStatus:
    title = _PHASE_TITLES["validate"]
    output_dir = hub_root / "output"
    evidence: list[str] = []
    for candidate in (
        output_dir / "validation",
        output_dir / "validation-report.json",
        output_dir / "reports",
    ):
        if candidate.exists():
            evidence.append(_rel(candidate, hub_root))
    state = STATE_DONE if evidence else STATE_NOT_STARTED
    detail = "validation report present" if evidence else "no validation report"
    return PhaseStatus("validate", title, state, detail=detail,
                       instances=[InstanceStatus("hub", state, evidence, detail)]
                       if evidence else [])


def _scan_project(hub_root: Path) -> PhaseStatus:
    title = _PHASE_TITLES["project"]
    output_dir = hub_root / "output"
    instances: list[InstanceStatus] = []
    for sub in _PROJECT_OUTPUT_DIRS:
        target_dir = output_dir / Path(sub)
        if target_dir.is_dir() and any(target_dir.iterdir()):
            instances.append(
                InstanceStatus(sub, STATE_DONE, [_rel(target_dir, hub_root)], "generated")
            )
    report = output_dir / "projection-report.json"
    if report.is_file() and not instances:
        instances.append(
            InstanceStatus("projection-report", STATE_DONE, [_rel(report, hub_root)], "report only")
        )
    return PhaseStatus("project", title, _aggregate(instances), instances=instances,
                       detail=f"{len(instances)} target(s) generated")


def scan_hub_status(hub_root: Path, *, toolkit_version: str = "") -> HubStatus:
    """Deterministically scan *hub_root* and return its objective lifecycle status.

    Args:
        hub_root: The ontology-hub root directory.
        toolkit_version: Optional toolkit version to record (informational).

    Returns:
        A :class:`HubStatus` with one :class:`PhaseStatus` per lifecycle phase.
    """
    hub_root = Path(hub_root)
    model = hub_root / "model"
    phases = [
        _scan_discovery(hub_root),
        _scan_source(hub_root),
        _scan_simple_ttl_phase(hub_root, "domain", model / "ontologies"),
        _scan_simple_ttl_phase(hub_root, "mapping", model / "mappings"),
        _scan_claims(hub_root),
        _scan_simple_ttl_phase(hub_root, "silver", model / "extensions",
                               suffix="-silver-ext.ttl"),
        _scan_simple_ttl_phase(hub_root, "gold", model / "extensions",
                               suffix="-gold-ext.ttl"),
        _scan_validate(hub_root),
        _scan_project(hub_root),
    ]
    return HubStatus(str(hub_root), toolkit_version, phases)


_STATE_ICON = {
    STATE_DONE: "✅",
    STATE_IN_PROGRESS: "🟡",
    STATE_NOT_STARTED: "⬜",
}


def render_markdown(status: HubStatus, *, last_scanned_at: str = "") -> str:
    """Render the *scan-derived* region of ``.kairos-state/status.md``.

    This is the do-not-edit objective block; ``kairos-flow`` wraps it with the
    continuation-state and phase-index regions.
    """
    lines: list[str] = []
    lines.append("<!-- AUTO-GENERATED by `kairos-ontology status` — do not edit by hand. -->")
    lines.append("")
    lines.append("| Phase | State | Instances | Evidence |")
    lines.append("|-------|-------|-----------|----------|")
    for p in status.phases:
        icon = _STATE_ICON.get(p.state, "")
        done = sum(1 for i in p.instances if i.state == STATE_DONE)
        total = len(p.instances)
        inst = f"{done}/{total}" if total else "—"
        ev = ", ".join(
            e for i in p.instances for e in i.evidence
        ) or "—"
        if len(ev) > 80:
            ev = ev[:77] + "…"
        lines.append(f"| {p.phase} | {icon} {p.state} | {inst} | {ev} |")
    lines.append("")
    nxt = status.next_phase
    lines.append(f"**Next phase:** `{nxt}`" if nxt else "**All phases complete.**")
    if last_scanned_at:
        lines.append("")
        lines.append(f"_Scanned at {last_scanned_at} · toolkit {status.toolkit_version}_")
    return "\n".join(lines) + "\n"
