# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Draft the gap-gate decisions a human would otherwise make row by row (DD-186).

The DD-169 gate is correct and it is expensive: on the live hub 1,286 source
columns carry real signal with no canonical home, and none of them may pass into
entity binding undecided. Reviewing 1,286 rows is not review — it is attrition,
and attrition is how a gate stops being read.

Two observations make it tractable. First, two of the reason codes are decidable
by rule and were never judgment calls: ``operational`` (audit/system columns) and
``vendor-slot`` (``Column1``, ``Field3``) are *already* classified by
``classify_unmapped`` before a human sees them. Second, the remainder collapses:
1,087 of the blocking columns share only 358 distinct names, because the same
``OrderNo`` appears in nineteen tables and is one decision, not nineteen.

So this module does the clerical part and refuses the judgment. It records the
rule-decidable dispositions itself, and for everything else drafts a *proposal*
per column name — with the evidence a reviewer needs — into a decision sheet that
must be edited and applied deliberately. Nothing here writes a
``blueprint-gap``/``deferred``/``registered-extension`` disposition on its own:
those are the answers that shape the model, and a drafting tool that quietly
chose them would recreate the silent-omission failure the gate exists to prevent.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .alignment_report import (
    REASON_OPERATIONAL,
    REASON_VENDOR_SLOT,
    GapGroup,
    build_alignment_report,
    group_gaps_by_column,
)
from .ai_provider import (
    ROLE_JUDGMENT,
    create_chat_completion,
    resolve_ai_seed,
    resolve_reasoning_effort,
)
from .source_disposition import DISPOSITIONS, load_dispositions, record_disposition
from .tracing import call_metadata, flush_tracing, new_session_id

logger = logging.getLogger(__name__)

#: Where the drafted sheet lands, beside the other analysis artifacts.
DECISION_SHEET_FILENAME = "gap-decisions.yaml"

#: Reason codes that are decidable by rule, and the disposition each implies.
#:
#: These are not judgments deferred to a human — ``classify_unmapped`` has already
#: proved the classification from the column's own name and evidence. An audit
#: timestamp is not business data whichever domain it sits in.
AUTO_DISPOSITIONS: dict[str, str] = {
    REASON_OPERATIONAL: "not-business-data",
    REASON_VENDOR_SLOT: "not-business-data",
}

_AUTO_RATIONALE = {
    REASON_OPERATIONAL: (
        "Audit/system column (created, updated, guid, hash, ingest metadata). Carries "
        "no business meaning to model; classified deterministically by reason code "
        "'{reason}' from the column name and evidence, not by a model."
    ),
    REASON_VENDOR_SLOT: (
        "Generic vendor placeholder (Column1, Field3 and similar). Nothing canonical "
        "to map; carry to Silver as a passthrough. Classified deterministically by "
        "reason code '{reason}'."
    ),
}

#: Framing appended to a recorded rationale, per disposition.
#:
#: ``blueprint-gap`` is defined as "a reference-model defect to file upstream".
#: Recorded from a drafted proposal it is weaker than that: nobody has confirmed
#: the reference model *ought* to have had the concept. The entry says so, so a
#: later reader does not mistake a candidate for a filed defect.
_DISPOSITION_FRAMING: dict[str, str] = {
    "blueprint-gap": (
        "POTENTIAL blueprint gap — real business data that is not mapped yet and has "
        "no reference-model property. Recorded as a candidate for upstream review, "
        "not as a confirmed reference-model defect: confirm the concept genuinely "
        "belongs in the accelerator before filing it."
    ),
    "deferred": (
        "Real business data, in scope, not mapped yet. Stays visible as a known gap "
        "for a later modelling pass."
    ),
}

#: Hints that shape a *proposed* disposition for a recurring name. Advisory only:
#: every proposal lands in the sheet for review, never in the ledger.
_IDENTIFIER_RE = re.compile(r"(?:^|_)(id|no|nr|code|key|ref|uuid|guid)$", re.I)
_FREETEXT_RE = re.compile(r"(?:^|_)(note|notes|comment|comments|remark|description|descr)$", re.I)
_JSON_BLOB_RE = re.compile(r"(?:^|_)(json|payload|fields|attributes|metadata|custom_fields)$", re.I)


@dataclass
class GapProposal:
    """One drafted decision covering every occurrence of one column name."""

    column: str
    domain: str
    occurrences: int
    tables: list[str]
    data_types: list[str]
    proposed_disposition: str
    confidence: str
    reasoning: str
    suggested_properties: list[str] = field(default_factory=list)

    def to_entry(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "domain": self.domain,
            "decision": "",  # the reviewer fills this in
            "proposed_disposition": self.proposed_disposition,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "occurrences": self.occurrences,
            "tables": self.tables[:8],
            "data_types": self.data_types,
            **({"suggested_properties": self.suggested_properties}
               if self.suggested_properties else {}),
        }


def propose_for_group(group: GapGroup, domain: str = "") -> GapProposal:
    """Draft a disposition proposal for one column name, with its reasoning.

    The proposal is a starting point that states *why*, so a reviewer can agree or
    disagree in one read rather than re-deriving the column's nature. Confidence
    is deliberately coarse — ``low`` means "this needs you", and a name appearing
    across many unrelated tables is a shared business concept whose absence from
    the reference model is a blueprint question, not a per-table one.
    """
    name = group.column
    types = group.data_types
    suggested = sorted({p.get("suggested_property", "") for p in group.proposals if p.get("suggested_property")})

    if _JSON_BLOB_RE.search(name) or any("json" in t.lower() for t in types):
        return GapProposal(
            name, domain, group.count, group.tables, types, "deferred", "medium",
            "Semi-structured blob (JSON/custom fields). Its contents may carry real "
            "signal but the column itself is not one concept; defer until the blob is "
            "unpacked into columns that can be judged.",
            suggested,
        )
    if _FREETEXT_RE.search(name):
        return GapProposal(
            name, domain, group.count, group.tables, types, "not-business-data", "medium",
            "Free-text note/comment field. Real content, but unstructured prose has no "
            "canonical property; carry to Silver as passthrough unless the business "
            "reads it as governed data.",
            suggested,
        )
    if _IDENTIFIER_RE.search(name) and group.count >= 3:
        return GapProposal(
            name, domain, group.count, group.tables, types, "blueprint-gap", "medium",
            f"POTENTIAL blueprint gap: identifier-shaped name recurring across "
            f"{group.count} tables — real business data with no reference-model "
            "property, likely a governed identifier concept (scheme + value) rather "
            "than a bare string. Confirm before treating it as an upstream defect.",
            suggested,
        )
    if group.count >= 5:
        return GapProposal(
            name, domain, group.count, group.tables, types, "blueprint-gap", "low",
            f"POTENTIAL blueprint gap: appears in {group.count} tables with no "
            "reference property — real business data not mapped yet. Recurrence this "
            "wide suggests a shared concept the model lacks, but the concept needs "
            "naming by a human before it counts as an upstream defect.",
            suggested,
        )
    return GapProposal(
        name, domain, group.count, group.tables, types, "", "low",
        "No rule applies. Decide from the tables and sample evidence: model it, "
        "register it as an extension, or record why it is out of scope.",
        suggested,
    )


#: Smallest number of distinct column names sharing a leading token that is worth
#: presenting as one decision. Below this, the family is not a saving.
MIN_FAMILY_NAMES = 3

#: Leading tokens that share a prefix without sharing a concept.
#:
#: The DD-179 lesson, applied one level up: ``is_approved``, ``is_external_resource``
#: and ``is_delivery_stop`` all begin with ``is`` and are three unrelated booleans.
#: A family is a *decision unit*, so a false family makes one disposition cover
#: things that deserved different ones — quietly, which is the worst way.
_NON_FAMILY_TOKENS = frozenset(
    {
        "is", "has", "can", "should", "was", "no", "not", "id", "code", "name", "type",
        "date", "time", "created", "updated", "modified", "deleted", "archived",
        "total", "sum", "count", "min", "max", "avg", "num", "nr",
        "first", "last", "new", "old", "current", "previous", "next", "default",
        "temp", "tmp", "test", "aggregated", "calculated", "computed",
    }
)

_FAMILY_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def family_of(column_name: str) -> str:
    """Leading token of a column name (``pickup_location_city`` -> ``pickup``)."""
    tokens = _name_tokens(column_name)
    return tokens[0] if tokens else ""


def group_into_families(
    proposals: list[GapProposal],
) -> tuple[list[dict[str, Any]], list[GapProposal]]:
    """Split proposals into decidable families and the loose remainder (DD-186).

    A family is a *decision unit*, and two constraints follow from that.

    **It cannot cross a domain boundary.** A disposition is domain-scoped: the
    same column name can be a modelled fact in one domain and a genuine gap in
    another, so one decision must not silently span both. Families are therefore
    keyed on ``(domain, leading token)``.

    **A shared prefix is not a shared concept.** ``is_approved``,
    ``is_external_resource`` and ``is_delivery_stop`` share ``is`` and are three
    unrelated booleans — the same trap DD-179 hit one level down. Structural and
    temporal prefixes are excluded, and members must be semantically coherent:
    they must share more than the leading token alone, which for real families
    (``pickup_location_city`` / ``pickup_location_country``) they always do.

    Families are presented, never auto-decided. The saving is in *how many
    questions get asked* — the part that made the gate unreadable — not in who
    answers them.
    """
    buckets: dict[tuple[str, str], list[GapProposal]] = {}
    for proposal in proposals:
        buckets.setdefault((proposal.domain, family_of(proposal.column)), []).append(proposal)

    families: list[dict[str, Any]] = []
    loose: list[GapProposal] = []
    for (domain, token), members in buckets.items():
        coherent, rejected = _semantically_coherent(token, members)
        loose.extend(rejected)
        if not token or token in _NON_FAMILY_TOKENS or len(coherent) < MIN_FAMILY_NAMES:
            loose.extend(coherent)
            continue
        families.append(
            {
                "family": token,
                "domain": domain,
                "decision": "",  # applies to every member name below
                "distinct_names": len(coherent),
                "source_columns": sum(m.occurrences for m in coherent),
                "members": sorted(m.column for m in coherent),
                "data_types": sorted({t for m in coherent for t in m.data_types}),
            }
        )
    families.sort(key=lambda f: (-f["source_columns"], f["domain"], f["family"]))
    loose.sort(key=lambda p: (-p.occurrences, p.column))
    return families, loose


def _semantically_coherent(
    token: str, members: list[GapProposal]
) -> tuple[list[GapProposal], list[GapProposal]]:
    """Split a candidate family into coherent members and the ones to release.

    A member belongs when it is a *qualified* form of the family token — the
    token plus at least one further token (``pickup`` + ``location`` + ``city``).
    A bare ``pickup`` column, or one whose remainder is purely structural, is
    released to be decided on its own: it is plausibly the entity itself rather
    than one of its attributes, and that is a different decision.
    """
    coherent: list[GapProposal] = []
    rejected: list[GapProposal] = []
    for member in members:
        rest = _name_tokens(member.column)[1:]
        meaningful = [t for t in rest if t not in _NON_FAMILY_TOKENS]
        (coherent if rest and meaningful else rejected).append(member)
    return coherent, rejected


def _name_tokens(column_name: str) -> list[str]:
    text = _CAMEL_BOUNDARY_RE.sub(" ", _FAMILY_SPLIT_RE.sub(" ", str(column_name or "")))
    return text.lower().split()


def apply_auto_dispositions(hub_root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Record the rule-decidable dispositions, skipping anything already decided.

    Idempotent and never overwrites: a column a human has already dispositioned is
    left exactly as it is, whatever this would have proposed.
    """
    report = build_alignment_report(
        Path(hub_root) / "integration" / "sources" / "_analysis", hub_root=Path(hub_root)
    )
    already = load_dispositions(Path(hub_root))
    decided_keys = {(k[0], k[1], k[2]) for k in already}
    table_level = {(k[0], k[1]) for k in already if not k[2]}

    written = 0
    skipped = 0
    by_reason: dict[str, int] = {}
    for domain in report.domains:
        for column in domain.unmapped:
            disposition = AUTO_DISPOSITIONS.get(column.reason)
            if not disposition:
                continue
            key = (column.system, column.table, column.column)
            if key in decided_keys or (column.system, column.table) in table_level:
                skipped += 1
                continue
            by_reason[column.reason] = by_reason.get(column.reason, 0) + 1
            written += 1
            if dry_run:
                continue
            record_disposition(
                hub_root=Path(hub_root),
                system=column.system,
                table=column.table,
                column=column.column,
                disposition=disposition,
                rationale=_AUTO_RATIONALE[column.reason].format(reason=column.reason),
                decided_by="autopilot",
                evidence=(f"reason-code:{column.reason}", f"data-type:{column.data_type}"),
            )
    return {"written": written, "skipped_already_decided": skipped, "by_reason": by_reason}


def build_decision_sheet(hub_root: Path, *, min_occurrences: int = 1) -> dict[str, Any]:
    """Draft the reviewable sheet for gap columns that still need a human."""
    analysis = Path(hub_root) / "integration" / "sources" / "_analysis"
    report = build_alignment_report(analysis, hub_root=Path(hub_root))
    already = load_dispositions(Path(hub_root))
    decided_columns = {(k[0], k[1], k[2]) for k in already}
    table_level = {(k[0], k[1]) for k in already if not k[2]}

    groups = [
        g
        for g in group_gaps_by_column(report)
        if any(
            (o.system, o.table, o.column) not in decided_columns
            and (o.system, o.table) not in table_level
            for o in g.occurrences
        )
    ]
    # Split each name's occurrences by domain: a disposition is domain-scoped, so
    # `OrderNo` in booking and `OrderNo` in financial are two decisions, not one.
    per_domain: dict[tuple[str, str], GapGroup] = {}
    for g in groups:
        for occurrence in g.occurrences:
            key = (occurrence.domain, g.column)
            per_domain.setdefault(key, GapGroup(column=g.column)).occurrences.append(occurrence)

    proposals = [
        propose_for_group(group, domain)
        for (domain, _name), group in sorted(
            per_domain.items(), key=lambda kv: (-kv[1].count, kv[0][0], kv[0][1])
        )
        if group.count >= min_occurrences
    ]
    families, loose = group_into_families(proposals)

    covered = sum(p.occurrences for p in proposals)
    return {
        "schema_version": 1,
        "generated_by": "draft-gap-decisions",
        "summary": {
            "source_columns_covered": covered,
            "column_names": len(proposals),
            "decisions_to_make": len(families) + len(loose),
            "families": len(families),
            "loose_names": len(loose),
            "with_a_proposal": sum(1 for p in loose if p.proposed_disposition),
        },
        "how_to_use": (
            "Set 'decision' to one of "
            f"{sorted(DISPOSITIONS)} on a family (applies to every member name) or on "
            "a single name, then apply with "
            "'kairos-ontology draft-gap-decisions --apply'. Leave blank to decide "
            "later. 'proposed_disposition' is a draft and is never applied on its own; "
            "note that 'blueprint-gap' asserts a reference-model defect to file "
            "upstream, so it is proposed sparingly and never assumed."
        ),
        "families": families,
        "decisions": [p.to_entry() for p in loose],
    }


def suggest_family_dispositions(
    sheet: dict[str, Any],
    *,
    client: Any,
    model: str,
    anchors: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Characterise each family in one model call, in place (DD-186).

    The deterministic pass forms the families and refuses to guess what they
    *mean*. That refusal is right for the disposition and wrong for the
    reasoning: the reviewer's real question about ``pickup`` (20 names, 33
    columns) is not "which token do these share" — grouping already answered
    that — but "what concept is this, and does the model already have a home for
    it?". Naming the concept is a judgement, and judgement is what the model is
    for.

    So this fills ``proposed_disposition`` and ``reasoning`` only, leaving
    ``decision`` untouched. It also returns each family's ``coherent`` verdict:
    the model sees member names the token-level guard cannot semantically check,
    and an incoherent family is one the reviewer should split rather than rule on.

    Anchors are passed as context because "which class do these tables resolve
    to" is usually the deciding fact — a family whose tables anchor to a class
    that *already exists* is a mapping gap, not a blueprint gap.
    """
    families = sheet.get("families") or []
    if not families:
        return {"families_described": 0}

    # Families are domain-scoped (the same token is a different decision in a
    # different domain), so the response key must carry the domain too. Keying on
    # the bare token produced duplicate schema properties and a provider 400.
    def key_of(family: dict[str, Any]) -> str:
        return f"{family.get('domain') or '_'}::{family['family']}"

    lines = []
    for family in families:
        anchor_names = sorted(
            {
                str(entry.get("anchor") or "")
                for (_system, _table), entry in (anchors or {}).items()
                if str(entry.get("domain") or "") == str(family.get("domain") or "")
            }
            - {""}
        )[:6]
        lines.append(
            f"- {key_of(family)}  (family '{family['family']}' in domain "
            f"'{family.get('domain') or '(none)'}'): "
            f"{family['distinct_names']} names / {family['source_columns']} columns; "
            f"members: {', '.join(family['members'][:14])}"
            + (f"; anchors: {', '.join(anchor_names)}" if anchor_names else "")
        )

    prompt = f"""These groups of source columns share a leading token and have no reference-model
property. For EACH family decide two things.

1. coherent: do these names really describe ONE concept, or is the shared token a
   coincidence (e.g. several unrelated booleans)? An incoherent family must be split
   by the reviewer, not ruled on as a unit.
2. proposed_disposition, from exactly this closed set:
   - blueprint-gap: real business data the accelerator blueprint has no domain for.
     This asserts a REFERENCE-MODEL DEFECT to file upstream — use it sparingly.
   - registered-extension: real business data outside the archetype catalog, to be
     registered as an in-scope client concept.
   - deferred: in scope, to be modelled later; stays visible as a known gap.
   - not-business-data: metadata, workflow or scratch with no canonical meaning.
   Leave it empty when the family genuinely needs a human to look at the data.

Give a one-sentence 'reasoning' naming the concept you think the family represents.
Prefer 'registered-extension' or 'deferred' over 'blueprint-gap' unless the concept is
clearly one the reference model ought to have had.

Answer under the exact key shown at the start of each line (domain::family).

FAMILIES ({len(families)}):
{chr(10).join(lines)}"""

    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "family_suggestions",
            "strict": True,
            "schema": {
                "$defs": {
                    "S": {
                        "type": "object",
                        "properties": {
                            "coherent": {"type": "boolean"},
                            "proposed_disposition": {
                                "type": ["string", "null"],
                                "enum": [*sorted(DISPOSITIONS), None],
                            },
                            "reasoning": {"type": "string"},
                        },
                        "required": ["coherent", "proposed_disposition", "reasoning"],
                        "additionalProperties": False,
                    }
                },
                "type": "object",
                "properties": {
                    "families": {
                        "type": "object",
                        "properties": {key_of(f): {"$ref": "#/$defs/S"} for f in families},
                        "required": [key_of(f) for f in families],
                        "additionalProperties": False,
                    }
                },
                "required": ["families"],
                "additionalProperties": False,
            },
        },
    }

    response = create_chat_completion(
        client,
        model=model,
        messages=[{"role": "user", "content": prompt}],
        seed=resolve_ai_seed(ROLE_JUDGMENT),
        reasoning_effort=resolve_reasoning_effort(ROLE_JUDGMENT),
        response_format=schema,
        param_fallbacks={"response_format": {"type": "json_object"}},
        trace_name="suggest-gap-families",
        trace_metadata=call_metadata(
            new_session_id("gapsuggest"), "judgment", families=len(families)
        ),
    )
    suggestions = json.loads(response.choices[0].message.content or "{}").get("families") or {}

    described = incoherent = 0
    for family in families:
        s = suggestions.get(key_of(family)) or {}
        if not s:
            continue
        described += 1
        family["coherent"] = bool(s.get("coherent", True))
        if not family["coherent"]:
            incoherent += 1
        family["proposed_disposition"] = s.get("proposed_disposition") or ""
        family["reasoning"] = str(s.get("reasoning") or "")
    flush_tracing()
    return {"families_described": described, "flagged_incoherent": incoherent}


def accept_proposals(sheet: dict[str, Any], *, fallback: str = "deferred") -> dict[str, int]:
    """Fill every empty ``decision`` from its drafted proposal (DD-186).

    The escape hatch for a hub owner who has read the drafts and wants them taken
    as decided, rather than typing 526 answers. Only ever called on explicit
    instruction, and the resulting ledger entries are attributed to ``autopilot``,
    never to a human.

    Entries with no proposal fall back to *deferred*: "in scope and modelled
    later; carries a reason and stays visible as a known gap". That is the only
    defensible blanket answer — it neither dismisses the column as worthless
    (``not-business-data``) nor asserts a reference-model defect to file upstream
    (``blueprint-gap``), and it leaves the column visible for a later pass.

    A decision a human already typed is never overwritten.
    """
    counts: dict[str, int] = {}
    for entry in list(sheet.get("families") or []) + list(sheet.get("decisions") or []):
        if str(entry.get("decision") or "").strip():
            continue
        decision = str(entry.get("proposed_disposition") or "").strip() or fallback
        entry["decision"] = decision
        entry["decided_by"] = "autopilot"
        counts[decision] = counts.get(decision, 0) + 1
    return counts


def write_decision_sheet(hub_root: Path, sheet: dict[str, Any]) -> Path:
    """Write the sheet, preserving any 'decision' values already filled in."""
    path = Path(hub_root) / "integration" / "sources" / "_analysis" / DECISION_SHEET_FILENAME
    if path.is_file():
        try:
            previous = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            kept_names = {
                (str(e.get("domain") or ""), str(e.get("column"))): str(e.get("decision") or "")
                for e in previous.get("decisions") or []
                if e.get("decision")
            }
            kept_families = {
                (str(f.get("domain") or ""), str(f.get("family"))): str(f.get("decision") or "")
                for f in previous.get("families") or []
                if f.get("decision")
            }
            for entry in sheet["decisions"]:
                key = (entry.get("domain", ""), entry["column"])
                if key in kept_names:
                    entry["decision"] = kept_names[key]
            for entry in sheet["families"]:
                key = (entry.get("domain", ""), entry["family"])
                if key in kept_families:
                    entry["decision"] = kept_families[key]
        except Exception:  # noqa: BLE001 - a broken previous sheet must not lose work
            logger.warning("Could not merge previous decisions from %s", path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(sheet, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return path


def apply_decision_sheet(
    hub_root: Path, *, dry_run: bool = False, decided_by: str = "user"
) -> dict[str, Any]:
    """Apply every filled-in ``decision`` to the ledger, for all its occurrences.

    One name-level decision fans out to each column it covers, which is the whole
    point: the reviewer decided ``OrderNo`` once, not nineteen times.

    *decided_by* must describe who actually decided. ``user`` means a human filled
    the sheet in; an agent accepting drafted proposals on a human's instruction is
    ``autopilot``, and recording that as ``user`` would put a false attribution in
    a ledger whose whole value is being auditable.
    """
    path = Path(hub_root) / "integration" / "sources" / "_analysis" / DECISION_SHEET_FILENAME
    if not path.is_file():
        raise FileNotFoundError(f"No decision sheet at {path}. Draft one first.")
    sheet = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    filled: dict[tuple[str, str], str] = {}
    why: dict[tuple[str, str], str] = {}
    for e in sheet.get("decisions") or []:
        if not (isinstance(e, dict) and str(e.get("decision") or "").strip()):
            continue
        key = (str(e.get("domain") or ""), str(e["column"]))
        filled[key] = str(e["decision"]).strip()
        why[key] = str(e.get("reasoning") or "")
    # A family decision expands to each of its member names. An explicit
    # per-name decision wins over its family's, so a reviewer can rule on the
    # family and carve out one exception without unpicking the family.
    families_applied = 0
    for family in sheet.get("families") or []:
        decision = str((family or {}).get("decision") or "").strip()
        if not decision:
            continue
        families_applied += 1
        for member in family.get("members") or []:
            key = (str(family.get("domain") or ""), str(member))
            if filled.setdefault(key, decision) is decision:
                why.setdefault(
                    key,
                    f"Family '{family.get('family')}': {family.get('reasoning') or ''}".strip(),
                )

    invalid = {k: d for k, d in filled.items() if d not in DISPOSITIONS}
    if invalid:
        raise ValueError(
            f"Unknown disposition(s) in the sheet: {invalid}. "
            f"Valid values: {sorted(DISPOSITIONS)}"
        )

    report = build_alignment_report(
        Path(hub_root) / "integration" / "sources" / "_analysis", hub_root=Path(hub_root)
    )
    applied = 0
    for group in group_gaps_by_column(report):
        for occurrence in group.occurrences:
            decision = filled.get((occurrence.domain, group.column))
            if not decision:
                continue
            applied += 1
            if dry_run:
                continue
            record_disposition(
                hub_root=Path(hub_root),
                system=occurrence.system,
                table=occurrence.table,
                column=occurrence.column,
                disposition=decision,
                rationale=" ".join(
                    part
                    for part in (
                        _DISPOSITION_FRAMING.get(decision, ""),
                        why.get((occurrence.domain, group.column), ""),
                        f"Decision recorded for column name '{group.column}' and applied "
                        f"to all {group.count} occurrence(s) via the gap decision sheet.",
                    )
                    if part
                ),
                decided_by=decided_by,
                evidence=(f"gap-reason:{occurrence.reason}", f"occurrences:{group.count}"),
            )
    return {
        "names_applied": len(filled),
        "families_applied": families_applied,
        "columns_written": applied,
    }
