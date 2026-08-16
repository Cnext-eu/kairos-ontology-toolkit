# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Provider-backed archetype-conformance judgment (DD-167).

``discovery-conformance`` could scaffold a judgments file and validate a finished one,
but nothing filled it in. For ``unit-load-carrier`` that is 174 concepts, each needing
an outcome, a confidence and a rationale, so in practice the orchestrating agent judged
them inline -- which is what a real run did, and it is the wrong place for the work.
The hub's own issue log recorded it as an open enhancement:

    "The 174-concept conformance judgment pass should be offloaded through the hub's
    configured AI provider to a high-capability model, rather than being executed only
    by the Copilot orchestration agent."

This module is that offload. It is deliberately **retrieval-grounded**: the model never
recalls concepts or invents URIs. It is handed the archetype's own catalog entries plus
the source evidence :mod:`conformance_evidence` already collected, and asked only to
choose an outcome from a closed set and justify it against that evidence.

Three properties make the output reviewable rather than merely plentiful:

* **Every judgment is attributed.** ``decided_by: ai`` throughout, which is what makes
  DD-148's gate bite -- ``compile``/``validate`` block on unresolved AI judgments until
  a human confirms them. This command deliberately cannot produce a human-attributed
  judgment, and cannot confirm the archetype (DD-149).
* **Low confidence escalates, it does not guess.** Below
  :data:`NEEDS_CONFIRMATION_BELOW` a judgment is flagged ``needs_confirmation``, so the
  uncertain ones surface as work rather than blending into the certain ones.
* **A concept with no source evidence cannot be certified.** ``conforms`` asserts the
  business does this and the data shows it. With no evidence the outcome is downgraded
  and flagged, because the failure mode that matters here is a confident ``conforms``
  on a concept the hub never models -- a real run scored a domain "6 conforms /
  0 deviates" while its ontology contained none of the three classes it certified.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

#: Concepts per model call. Small enough that the model attends to each concept and the
#: response stays parseable; large enough that 174 concepts cost ~15 calls, not 174.
DEFAULT_BATCH_SIZE = 12

#: Below this confidence a judgment is marked ``needs_confirmation``.
NEEDS_CONFIRMATION_BELOW = 0.75

#: The closed outcome vocabulary. Mirrors the archetype schema's ``outcome-codes.yaml``;
#: anything else in a response is rejected rather than coerced.
VALID_OUTCOMES: frozenset[str] = frozenset(
    {"conforms", "conforms-with-rename", "partial", "deviates", "not-applicable"}
)

#: Outcomes that assert the hub genuinely realises the concept. Only these are held to
#: the evidence requirement.
_ASSERTIVE_OUTCOMES: frozenset[str] = frozenset({"conforms", "conforms-with-rename"})


@dataclass
class JudgmentResult:
    """One concept's judged outcome, in the shape ``build`` expects."""

    uri: str
    label: str
    tier: str
    outcome: str
    confidence: float | None
    rationale: str
    references: list[str] = field(default_factory=list)
    needs_confirmation: bool = False
    decided_by: str = "ai"
    likely_domains: list[str] = field(default_factory=list)
    deviation_reason: str | None = None
    rename_to: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "label": self.label,
            "tier": self.tier,
            "outcome": self.outcome,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "references": list(self.references),
            "needs_confirmation": self.needs_confirmation,
            "decided_by": self.decided_by,
            "likely_domains": list(self.likely_domains),
            "deviation_reason": self.deviation_reason,
            "rename_to": self.rename_to,
        }


@dataclass
class JudgeReport:
    schema_version: int = SCHEMA_VERSION
    archetype_id: str = ""
    judgments: list[JudgmentResult] = field(default_factory=list)
    calls_made: int = 0
    notices: list[str] = field(default_factory=list)

    @property
    def needs_confirmation(self) -> list[JudgmentResult]:
        return [j for j in self.judgments if j.needs_confirmation]

    def outcome_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for judgment in self.judgments:
            counts[judgment.outcome] = counts.get(judgment.outcome, 0) + 1
        return dict(sorted(counts.items()))

    def to_judgments_document(self) -> dict[str, Any]:
        """Render the file ``discovery-conformance build --judgments`` consumes.

        ``archetype_confirmed_by`` keeps the template's sentinel: DD-149 requires a
        human to name the archetype, and a command that judges concepts must not be
        able to satisfy that gate as a side effect.
        """
        return {
            "mode": "fleet",
            "archetype_confirmed_by": f"<CONFIRM_HUMAN_ARCHETYPE:{self.archetype_id}>",
            "core_concepts": [j.to_dict() for j in self.judgments],
        }


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You judge whether a logistics business conforms to individual concepts from a reference \
archetype, using ONLY the evidence supplied.

Return STRICT JSON: {"judgments": [{"uri", "outcome", "confidence", "rationale", \
"likely_domains", "rename_to", "deviation_reason"}]}.

Rules:
- "uri" MUST be copied verbatim from the input. Never invent, complete or correct a URI.
- "outcome" MUST be exactly one of: conforms, conforms-with-rename, partial, deviates, \
not-applicable.
- "confidence" is a float 0.0-1.0 reflecting the evidence, not your fluency.
- "rationale" is one or two sentences citing the specific evidence. If the evidence is \
absent, say so plainly rather than reasoning from general logistics knowledge.
- Use "conforms" ONLY when the supplied source evidence shows the business actually \
does this. Absent evidence is NOT weak support for conforms; it is grounds for \
"partial" (plausible, unproven) or "not-applicable" (structurally inapplicable).
- "conforms-with-rename" requires "rename_to": the business's own term for the concept.
- "deviates" requires "deviation_reason".
- "likely_domains" lists the blueprint domain ids this concept informs, when known.
- "pattern_library_caution", when present, is a normative warning from the reference pattern library about this exact concept (e.g. it is a role-bearing parent, not a durable identity). Weigh it: it usually means the honest answer is "partial", and it must be reflected in the rationale.
- "downstream_bi_demand", when present, means the business reports on this concept. It is demand evidence, never business authority on its own: it supports "partial" and can corroborate CONCEPT-LEVEL source evidence, but it cannot by itself justify "conforms".
- A confident wrong answer is worse than an honest low-confidence one. An unproven \
concept marked conforms silently certifies something the hub will never model.
Judge every concept given. Return one entry per input concept, no extras."""


def build_batch_prompt(
    concepts: Sequence[dict[str, Any]],
    business_context: str = "",
) -> str:
    """Render one batch of concepts, with their evidence, as a user prompt."""
    lines: list[str] = []
    if business_context.strip():
        lines.append("BUSINESS CONTEXT")
        lines.append(business_context.strip())
        lines.append("")
    lines.append(f"CONCEPTS TO JUDGE ({len(concepts)}):")
    for concept in concepts:
        lines.append("")
        lines.append(f"- uri: {concept['uri']}")
        lines.append(f"  label: {concept.get('label', '')}")
        lines.append(f"  tier: {concept.get('tier', '')}")
        evidence = concept.get("evidence")
        lines.append(f"  source_evidence: {evidence or 'NONE FOUND'}")
        strength = concept.get("evidence_strength")
        if strength:
            lines.append(f"  evidence_strength: {strength}")
        if concept.get("bi_demand"):
            lines.append(f"  downstream_bi_demand: {concept['bi_demand']}")
        if concept.get("caution"):
            lines.append(f"  pattern_library_caution: {concept['caution']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Response handling
# ---------------------------------------------------------------------------


def _coerce_confidence(value: Any) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    return min(1.0, max(0.0, confidence))


def normalize_judgment(
    payload: dict[str, Any],
    catalog_entry: dict[str, Any],
    *,
    has_evidence: bool,
    concept_level_evidence: bool = True,
    pattern_caution: str = "",
) -> JudgmentResult:
    """Turn one model response entry into a validated :class:`JudgmentResult`.

    Applies the guardrails the prompt asks for but cannot enforce: an unknown outcome
    becomes ``partial`` rather than being trusted, a confident ``conforms`` that the
    evidence cannot support is downgraded, and anything uncertain is flagged.

    *concept_level_evidence* is the distinction that matters most. Alignment evidence
    ("this table maps to **this concept**") and an affinity ``likely_entity`` match both
    speak to the concept itself. Bare domain affinity ("some table is in this concept's
    domain") does not, and treating the two alike reproduces the exact error this
    command exists to prevent: on first run the model marked
    ``TransportPartyRoleAssignment`` *conforms* at 0.91 because "16 party-related tables
    ... is consistent with assigning roles", and ``TransportPartyRoleCode`` *conforms*
    at 0.86 while its own rationale said "no specific code list is shown". Sixteen
    tables in the party domain is not evidence that a role-assignment link entity
    exists — the business in question models roles as boolean flags.
    """
    outcome = str(payload.get("outcome") or "").strip()
    confidence = _coerce_confidence(payload.get("confidence"))
    rationale = str(payload.get("rationale") or "").strip()
    needs_confirmation = False

    if outcome not in VALID_OUTCOMES:
        rationale = (
            f"Model returned unrecognised outcome {outcome!r}; recorded as 'partial' for "
            f"human review. Original rationale: {rationale}"
        ).strip()
        outcome, confidence, needs_confirmation = "partial", None, True

    elif outcome in _ASSERTIVE_OUTCOMES and not has_evidence:
        # "conforms" is a claim that the business does this and the data shows it.
        # Without evidence the second half is unsupported, so the claim is downgraded
        # rather than recorded -- this is the exact shape of the previous run's
        # "6 conforms / 0 deviates" on a domain whose ontology modelled none of it.
        rationale = (
            f"Downgraded from '{outcome}': no source evidence was found for this "
            f"concept, so conformance is unproven. Model rationale: {rationale}"
        ).strip()
        outcome, needs_confirmation = "partial", True

    elif outcome in _ASSERTIVE_OUTCOMES and not concept_level_evidence:
        rationale = (
            f"Downgraded from '{outcome}': the only evidence is domain-level affinity — "
            "tables sit in this concept's domain, but none is identified as this concept. "
            f"That cannot certify the concept itself. Model rationale: {rationale}"
        ).strip()
        outcome, needs_confirmation = "partial", True

    if outcome in _ASSERTIVE_OUTCOMES and pattern_caution:
        # Coded guard, not a prompt line: the pattern library keys its warnings to
        # concept IRIs, so whether one applies is a lookup, and leaving it to the model
        # to honour makes enforcement depend on the thing being checked.
        #
        # It escalates rather than downgrades, deliberately. A grain collision says "do
        # not subclass or merge this" -- that governs how the concept is modelled, not
        # whether the business has it. Forcing mmt:TransportParty to 'partial' would be
        # wrong; the business demonstrably has transport parties. What is warranted is
        # that a flagged concept never gets certified without someone looking.
        needs_confirmation = True
        rationale = f"{rationale} [pattern-library caution: {pattern_caution}]".strip()

    if outcome == "conforms-with-rename" and not str(payload.get("rename_to") or "").strip():
        needs_confirmation = True
        rationale = f"{rationale} (rename target missing; needs a human term.)".strip()

    if confidence is None or confidence < NEEDS_CONFIRMATION_BELOW:
        needs_confirmation = True

    return JudgmentResult(
        uri=str(catalog_entry["uri"]),
        label=str(catalog_entry.get("label") or ""),
        tier=str(catalog_entry.get("tier") or ""),
        outcome=outcome,
        confidence=confidence,
        rationale=rationale or "No rationale supplied by the model.",
        references=list(catalog_entry.get("references") or []),
        needs_confirmation=needs_confirmation,
        decided_by="ai",
        likely_domains=[str(d) for d in (payload.get("likely_domains") or [])],
        deviation_reason=(str(payload.get("deviation_reason")).strip() or None)
        if payload.get("deviation_reason")
        else None,
        rename_to=(str(payload.get("rename_to")).strip() or None)
        if payload.get("rename_to")
        else None,
    )


def unjudged_result(catalog_entry: dict[str, Any], reason: str) -> JudgmentResult:
    """A concept the model did not return. Recorded, never silently dropped."""
    return JudgmentResult(
        uri=str(catalog_entry["uri"]),
        label=str(catalog_entry.get("label") or ""),
        tier=str(catalog_entry.get("tier") or ""),
        outcome="partial",
        confidence=None,
        rationale=f"Not judged: {reason}. Requires human assessment.",
        needs_confirmation=True,
        decided_by="ai",
    )


def parse_batch_response(text: str) -> list[dict[str, Any]]:
    """Extract the judgment list from a model response.

    Tolerates a fenced code block, which models add despite being asked for raw JSON.
    Raises ``ValueError`` when nothing parseable is present -- the caller records the
    whole batch as unjudged rather than inventing outcomes for it.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.lstrip().lower().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
        cleaned = cleaned.strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in model response")
    payload = json.loads(cleaned[start : end + 1])
    judgments = payload.get("judgments")
    if not isinstance(judgments, list):
        raise ValueError("response has no 'judgments' list")
    return [item for item in judgments if isinstance(item, dict)]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def blueprint_concept_domains(
    concept_uris: Iterable[str], data_domains: dict[str, Any]
) -> dict[str, tuple[str, ...]]:
    """Map each concept URI to the blueprint domains whose modules declare it.

    ``collect_concept_source_evidence`` can only produce affinity evidence for a concept
    it can place in a domain, and it takes that placement from the concept's authored
    ``likely_domains`` — which do not exist yet at judgment time. That is circular: the
    judgment needs evidence, the evidence needs the judgment.

    The blueprint breaks the cycle without guessing. ``data-domains.yaml`` already lists
    every domain's ``imports[].uri``, and a concept's URI names its module, so
    concept → module → domain is a lookup over data the hub already has. Deriving it here
    is what turns "0 of 174 concepts have evidence" into a usable pass.
    """
    module_domains: dict[str, set[str]] = {}
    for domain_id, meta in (data_domains or {}).items():
        if not isinstance(meta, dict):
            continue
        for entry in meta.get("imports") or ():
            if not isinstance(entry, dict):
                continue
            uri = str(entry.get("uri") or "").strip().rstrip("#/")
            if uri:
                module_domains.setdefault(uri, set()).add(str(domain_id))

    mapped: dict[str, tuple[str, ...]] = {}
    for uri in concept_uris:
        text = str(uri)
        module = text.rsplit("#", 1)[0] if "#" in text else text.rsplit("/", 1)[0]
        domains = module_domains.get(module.rstrip("#/"))
        if domains:
            mapped[text] = tuple(sorted(domains))
    return mapped


def pattern_cautions(concept_uris: Iterable[str], refmodels_dir: Path | None) -> dict[str, str]:
    """Map concept URI -> the pattern library's warning about modelling it, if any.

    The library's ``grain_collisions`` and ``anti_patterns`` name concept IRIs outright
    — ``qualified-role-assignment`` lists five party parents that are "not the durable
    identity on its own" — so they line up one-to-one with concepts being judged. Not
    passing them left the model to decide, unaided, whether "16 tables in the party
    domain" certifies a role-assignment entity. It decided yes.

    Best-effort: an unresolvable or malformed library yields ``{}`` and the judgment
    proceeds without the extra context.
    """
    if refmodels_dir is None:
        return {}
    try:
        from .pattern_loader import load_patterns

        patterns, _ = load_patterns(Path(refmodels_dir))
    except Exception:  # noqa: BLE001 - advisory prompt context only
        return {}

    cautions: dict[str, list[str]] = {}
    wanted = {str(uri) for uri in concept_uris}

    def _note(iri: str, text: str) -> None:
        if iri in wanted and text:
            cautions.setdefault(iri, []).append(text)

    for pattern in patterns:
        for collision in getattr(pattern, "grain_collisions", None) or ():
            if isinstance(collision, dict):
                _note(
                    str(collision.get("against") or ""),
                    f"{pattern.id}: grain collision — {collision.get('reason', '')}",
                )
        for anti in getattr(pattern, "anti_patterns", None) or ():
            if not isinstance(anti, dict):
                continue
            summary = f"{pattern.id}/{anti.get('id', '')}: {anti.get('rejection_reason', '')}"
            for iri in anti.get("exemptions") or ():
                _note(str(iri), summary)
    return {uri: " | ".join(notes) for uri, notes in cautions.items()}


def bi_demand_terms(hub_root: Path) -> set[str]:
    """Return normalised table/measure names the BI models actually report on.

    Downstream demand is real evidence for "does the business do this?" — a Power BI
    model with a demurrage measure is a business that tracks demurrage. It is never
    business *authority* (the design skills are explicit about that), so it is passed as
    a distinct, clearly-labelled signal rather than folded into source evidence.
    """
    import yaml

    bi_dir = Path(hub_root) / "integration" / "discovery" / "bi"
    if not bi_dir.is_dir():
        return set()

    def _norm(text: str) -> str:
        return "".join(ch for ch in str(text).lower() if ch.isalnum())

    terms: set[str] = set()
    for path in sorted(bi_dir.glob("*-concept-mapping.yaml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:  # defensive: a broken worksheet must not fail the judgment
            continue
        if not isinstance(document, dict):
            continue
        for table in document.get("tables") or ():
            if not isinstance(table, dict):
                continue
            # Strip Power BI's d_/f_ dimension/fact prefixes before matching.
            name = str(table.get("tmdl_name") or "")
            for candidate in (name, name[2:] if name[:2].lower() in ("d_", "f_") else name):
                if candidate:
                    terms.add(_norm(candidate))
            for measure in table.get("measures") or ():
                terms.add(_norm(measure))
    return terms


def concepts_named_by_affinity(
    concept_uris: Iterable[str], analysis_dir: Path
) -> set[str]:
    """Return concept URIs a source table is actually *identified as*.

    The affinity pass records a ``likely_entity`` per table — "this table is a Booking",
    "this table is a Consignment". That is concept-level evidence, unlike the domain tag
    beside it, and it is the difference between "the party domain has 16 tables" and
    "a table here is a role assignment". Matched on the concept's local name, normalised
    for case and separators, because ``likely_entity`` is free text from the model.
    """
    import yaml

    if not Path(analysis_dir).is_dir():
        return set()

    def _norm(text: str) -> str:
        return "".join(ch for ch in str(text).lower() if ch.isalnum())

    named: set[str] = set()
    for path in sorted(Path(analysis_dir).glob("*-affinity.yaml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:  # defensive: a broken report must not fail the judgment
            continue
        if not isinstance(document, dict):
            continue
        for table in document.get("tables") or ():
            if not isinstance(table, dict):
                continue
            entity = table.get("likely_entity")
            if not entity:
                continue
            # "Company / Trade Party" -- the model sometimes offers alternatives.
            for part in str(entity).replace("/", "|").split("|"):
                named.add(_norm(part))

    matched: set[str] = set()
    for uri in concept_uris:
        local = str(uri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        if _norm(local) in named:
            matched.add(str(uri))
    return matched


def _bi_signal(concept_uri: str, bi_terms: set[str]) -> str:
    """Return a demand note when a BI model reports on this concept, else ``""``."""
    if not bi_terms:
        return ""
    local = concept_uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    normalised = "".join(ch for ch in local.lower() if ch.isalnum())
    if normalised and normalised in bi_terms:
        return f"a Power BI model reports on '{local}'"
    return ""


def _batched(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def judge_concepts(
    *,
    catalog: Sequence[dict[str, Any]],
    evidence: dict[str, Any],
    archetype_id: str,
    concept_level_uris: set[str] | None = None,
    cautions: dict[str, str] | None = None,
    bi_terms: set[str] | None = None,
    business_context: str = "",
    batch_size: int = DEFAULT_BATCH_SIZE,
    client: Any = None,
    model: str | None = None,
    progress: Any = None,
) -> JudgeReport:
    """Judge every concept in *catalog*, batching calls to the configured provider.

    *evidence* maps concept URI to a :class:`ConceptSourceEvidence` (or anything with a
    ``describe()``); a URI absent from it has no source evidence.

    A batch that fails outright is recorded as unjudged and flagged, never dropped and
    never guessed: a missing concept fails ``validate``'s completeness check loudly,
    which is the correct outcome, whereas a fabricated one passes silently.
    """
    from .ai_provider import ROLE_JUDGMENT, get_ai_client, resolve_role_model

    # Alignment evidence is concept-level by construction; affinity is only
    # concept-level where a table was identified AS this concept.
    strong = set(concept_level_uris or ())
    for uri, found in (evidence or {}).items():
        if getattr(found, "kind", "") == "alignment":
            strong.add(str(uri))

    report = JudgeReport(archetype_id=archetype_id)
    if not catalog:
        report.notices.append("Archetype catalog is empty; nothing to judge.")
        return report

    resolved_model = model or resolve_role_model(ROLE_JUDGMENT)
    active_client = client or get_ai_client(model=resolved_model, role=ROLE_JUDGMENT)
    by_uri = {str(entry["uri"]): entry for entry in catalog}

    for batch in _batched(list(catalog), max(1, batch_size)):
        prompt_concepts = []
        for entry in batch:
            found = evidence.get(str(entry["uri"]))
            prompt_concepts.append(
                {
                    "uri": entry["uri"],
                    "label": entry.get("label", ""),
                    "tier": entry.get("tier", ""),
                    "evidence": found.describe() if found is not None else "",
                    "caution": (cautions or {}).get(str(entry["uri"]), ""),
                    "bi_demand": _bi_signal(str(entry["uri"]), bi_terms or set()),
                    "evidence_strength": (
                        "CONCEPT-LEVEL (a source table is identified as this concept)"
                        if str(entry["uri"]) in strong
                        else "DOMAIN-LEVEL ONLY (tables sit in this concept's domain; "
                        "none is identified as this concept)"
                    ),
                }
            )

        try:
            response = active_client.chat.completions.create(
                model=resolved_model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": build_batch_prompt(prompt_concepts, business_context)},
                ],
                response_format={"type": "json_object"},
            )
            report.calls_made += 1
            entries = parse_batch_response(response.choices[0].message.content or "")
        except Exception as exc:  # noqa: BLE001 - one bad batch must not lose the rest
            logger.warning("Judgment batch failed: %s", exc)
            report.notices.append(f"Batch of {len(batch)} concept(s) failed: {exc}")
            for entry in batch:
                report.judgments.append(unjudged_result(entry, f"model call failed ({exc})"))
            if progress is not None:
                progress(len(batch))
            continue

        returned = {str(item.get("uri")): item for item in entries}
        for entry in batch:
            uri = str(entry["uri"])
            payload = returned.get(uri)
            if payload is None:
                report.judgments.append(
                    unjudged_result(entry, "model returned no judgment for this concept")
                )
                continue
            report.judgments.append(
                normalize_judgment(
                    payload,
                    by_uri[uri],
                    has_evidence=evidence.get(uri) is not None,
                    concept_level_evidence=uri in strong,
                    pattern_caution=(cautions or {}).get(uri, ""),
                )
            )
        if progress is not None:
            progress(len(batch))

    return report


def write_judgments(report: JudgeReport, path: Path) -> Path:
    """Write the judgments document for ``discovery-conformance build --judgments``."""
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(report.to_judgments_document(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path

# ---------------------------------------------------------------------------
# Grouped review (AP-022)
# ---------------------------------------------------------------------------


@dataclass
class ReviewGroup:
    """One themed block of unresolved judgments, sized for a single decision."""

    theme: str
    concepts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.concepts)

    def outcome_mix(self) -> dict[str, int]:
        mix: dict[str, int] = {}
        for concept in self.concepts:
            outcome = str(concept.get("outcome") or "?")
            mix[outcome] = mix.get(outcome, 0) + 1
        return dict(sorted(mix.items()))

    def confidence_range(self) -> tuple[float | None, float | None]:
        values = [
            c["confidence"] for c in self.concepts if isinstance(c.get("confidence"), (int, float))
        ]
        return (min(values), max(values)) if values else (None, None)

    def representatives(self, limit: int = 3) -> list[dict[str, Any]]:
        """The least-confident concepts: where a reviewer's attention is worth most."""
        return sorted(
            self.concepts,
            key=lambda c: (
                c.get("confidence") if isinstance(c.get("confidence"), (int, float)) else -1.0
            ),
        )[:limit]

    def to_dict(self) -> dict[str, Any]:
        low, high = self.confidence_range()
        return {
            "theme": self.theme,
            "size": self.size,
            "outcome_mix": self.outcome_mix(),
            "confidence_range": [low, high],
            "representatives": [
                {
                    "label": r.get("label"),
                    "uri": r.get("uri"),
                    "outcome": r.get("outcome"),
                    "confidence": r.get("confidence"),
                    "rationale": r.get("rationale"),
                }
                for r in self.representatives()
            ],
            "all_concepts": [c.get("label") or c.get("uri") for c in self.concepts],
        }


def group_unresolved(core_concepts: Iterable[dict[str, Any]]) -> list[ReviewGroup]:
    """Group unresolved AI judgments by business theme, largest block first.

    A flat list of 147 concepts is not reviewable, and the practical consequence is that
    nobody reviews it — the previous run's human approved the lot after seeing a handful
    of grouped examples, which is the right instinct with no tool support. Grouping by
    ``likely_domains`` uses the tag the judgment already carries; concepts with no tag
    are genuinely cross-cutting and get their own block rather than being hidden in one.
    """
    groups: dict[str, ReviewGroup] = {}
    for concept in core_concepts:
        if not isinstance(concept, dict):
            continue
        if not concept.get("needs_confirmation"):
            continue
        domains = [str(d) for d in (concept.get("likely_domains") or []) if str(d).strip()]
        theme = ", ".join(sorted(domains)) if domains else "(cross-cutting)"
        groups.setdefault(theme, ReviewGroup(theme=theme)).concepts.append(concept)
    return sorted(groups.values(), key=lambda g: (-g.size, g.theme))


def apply_human_decision(
    core_concepts: list[dict[str, Any]],
    *,
    outcome: str,
    rationale: str,
    theme: str | None = None,
    match: str | None = None,
    uris: Iterable[str] = (),
    decided_by: str = "user",
) -> list[dict[str, Any]]:
    """Record a human's block decision over selected unresolved concepts.

    Returns the entries changed. Selection is by theme (``likely_domains``), a substring
    of the label, an explicit URI list, or any combination — all of which must match.

    This is the one path that can clear ``needs_confirmation``, and it exists precisely
    so that clearing it is an explicit human act with a written reason attached, rather
    than a side effect of re-running a judge. It refuses an outcome outside the closed
    vocabulary and refuses an empty rationale: a block marked ``not-applicable`` with no
    reason is indistinguishable later from one nobody looked at.
    """
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"Unknown outcome {outcome!r}; expected one of {sorted(VALID_OUTCOMES)}.")
    if not rationale.strip():
        raise ValueError("A human decision requires a rationale.")

    wanted_uris = {str(u) for u in uris}
    changed: list[dict[str, Any]] = []
    for concept in core_concepts:
        if not isinstance(concept, dict) or not concept.get("needs_confirmation"):
            continue
        if theme is not None:
            domains = [str(d) for d in (concept.get("likely_domains") or []) if str(d).strip()]
            actual = ", ".join(sorted(domains)) if domains else "(cross-cutting)"
            if actual != theme:
                continue
        if match and match.casefold() not in str(concept.get("label") or "").casefold():
            continue
        if wanted_uris and str(concept.get("uri")) not in wanted_uris:
            continue

        prior = str(concept.get("outcome") or "?")
        concept["outcome"] = outcome
        concept["needs_confirmation"] = False
        concept["decided_by"] = decided_by
        concept["confidence"] = 1.0
        concept["rationale"] = (
            f"{rationale.strip()} [human decision; AI had proposed '{prior}': "
            f"{str(concept.get('rationale') or '').strip()}]"
        )
        if outcome == "deviates" and not concept.get("deviation_reason"):
            concept["deviation_reason"] = rationale.strip()
        changed.append(concept)
    return changed
