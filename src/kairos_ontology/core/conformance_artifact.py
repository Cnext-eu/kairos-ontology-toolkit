# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Core Concepts Conformance artifact: schema, builder, writer, reader (DD-090).

The conformance artifact (``ontology-hub/integration/discovery/core-concepts-conformance.yaml``)
is the **machine** output of the Core Concepts Conformance phase of ``kairos-design-discovery``.
``kairos-design-domain`` reads it at reference-model selection to pre-seed imports and
pre-justify known deviations. ``derive-claims`` may also consume a committed, validated
artifact to create proposed-only candidates; it never grants approval authority.

The artifact intentionally carries:

* the session ``mode`` (``interactive``/``fleet``, DD-088) the run was produced under,
* the selected archetype id + label + ``confirmed_by`` (always ``"human"``, DD-149 —
  archetype selection is never fleet-eligible),
* ``ref_model_modules`` (iri + tier) so design-domain can pre-seed ``owl:imports``,
* the resolved reference-models version,
* ``catalog_hash`` + ``concept_set_hash`` for stale detection,
* per-concept outcomes (validated against the shared ``outcome-codes.yaml`` enum) plus
  judgment provenance (``confidence``, ``rationale``, ``references``, ``needs_confirmation``,
  ``decided_by``) so fleet-mode (DD-088) AI-approved choices can be told apart from
  user-confirmed ones and flagged via ``open_questions()`` (DD-148),
* an optional per-concept ``likely_domains`` (issue #389/#390) — a list of lowercase
  domain-id strings a concept informs; absent/empty means **cross-cutting** (always in
  scope), letting ``open_questions()``/``check_discovery_gate()`` narrow unresolved-judgment
  gating to an active ``--domain`` without ever silently un-gating older artifacts,
* topology confirmations + cardinality answers,
* a coverage scorecard.

It does **not** invent ``business_area`` as structured data — that grouping lives in the
discovery markdown and catalog comments, not the machine catalog, so it is optional and
non-authoritative here.

``kairos-ontology compile``/``validate`` call ``check_discovery_gate()`` and hard-fail when
discovery is missing or has unresolved fleet-mode judgments (DD-148) — see those CLI modules.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import yaml

from .archetype_loader import Archetype, VALID_TIERS
from .hub_utils import is_authored_discovery_ttl

#: Schema version of the conformance artifact itself.
#: v2 (DD-148) added ``mode``, ``archetype.confirmed_by``, and per-concept
#: ``confidence``/``rationale``/``references``/``needs_confirmation``/``decided_by`` —
#: a deliberate breaking change (no hub was in production when it landed).
ARTIFACT_SCHEMA_VERSION = 2

#: Default location of the artifact relative to the hub root.
ARTIFACT_RELPATH = Path("integration/discovery/core-concepts-conformance.yaml")

#: Valid values for the artifact-level ``mode`` field (DD-088 fleet-mode marker).
VALID_MODES = {"interactive", "fleet"}

#: Valid values for the per-concept ``decided_by`` field.
VALID_DECIDED_BY = {"user", "ai"}


class ConformanceArtifactError(Exception):
    """Raised when a conformance artifact is malformed or fails validation."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_scorecard(
    outcomes: list[dict[str, Any]], valid_tiers: tuple[str, ...] | None = None
) -> dict[str, Any]:
    """Return counts of outcomes overall and grouped by tier.

    The tier buckets are seeded from *valid_tiers* (default :data:`VALID_TIERS`, the offline
    fallback) **union the tiers actually present in outcomes**, so the scorecard is
    self-describing: no concept is ever dropped for carrying a tier this toolkit predates.
    That matters because reference-models owns the tier enum and may add to it — before this,
    a concept with an unseeded tier was counted in ``total`` but silently omitted from every
    bucket, leaving ``total`` != sum of ``by_tier`` with no warning.

    Seeding still includes the canonical tiers even when they have no concepts, so artifacts
    keep their historical shape. :func:`validate_artifact` normalises empty buckets away before
    comparing, which is what keeps the recomputed scorecard independent of which checkout
    (and therefore which tier list) happened to be resolvable.

    Args:
        outcomes: list of per-concept dicts, each with at least ``outcome`` and ``tier``.
        valid_tiers: tier enum to seed buckets with; resolve it via
            :func:`~kairos_ontology.core.archetype_loader.load_valid_tiers` when a checkout is
            available. ``None`` uses the offline fallback.
    """
    by_outcome = Counter(o.get("outcome", "unknown") for o in outcomes)
    seeded = tuple(valid_tiers) if valid_tiers else VALID_TIERS
    present = [o.get("tier") for o in outcomes if isinstance(o.get("tier"), str) and o.get("tier")]
    by_tier: dict[str, Counter] = {tier: Counter() for tier in (*seeded, *present)}
    for o in outcomes:
        tier = o.get("tier")
        if isinstance(tier, str) and tier:
            by_tier[tier][o.get("outcome", "unknown")] += 1
    return {
        "total": len(outcomes),
        "by_outcome": dict(sorted(by_outcome.items())),
        "by_tier": {tier: dict(sorted(by_tier[tier].items())) for tier in sorted(by_tier)},
    }


def _scorecard_comparable_form(scorecard: dict[str, Any]) -> dict[str, Any]:
    """Return *scorecard* with empty tier buckets removed, for equality comparison.

    Two scorecards computed over the same outcomes can differ only in which *empty* tier
    buckets they seeded, since a bucket with concepts in it is driven by the outcomes alone.
    Normalising empties away is what lets an artifact built against a checkout with a newer
    tier enum validate against one without it (and vice versa) instead of failing with a
    misleading "scorecard contradicts core_concepts" error the user cannot act on.
    """
    normalized = dict(scorecard)
    by_tier = normalized.get("by_tier")
    if isinstance(by_tier, dict):
        normalized["by_tier"] = {tier: counts for tier, counts in by_tier.items() if counts}
    return normalized


def build_artifact(
    *,
    archetype: Archetype,
    refmodels_version: str | None,
    outcomes: list[dict[str, Any]],
    mode: str,
    archetype_confirmed_by: str = "human",
    topology_confirmations: list[dict[str, Any]] | None = None,
    cardinality_answers: list[dict[str, Any]] | None = None,
    discovery_doc: str | None = None,
    generated_by: str = "kairos-design-discovery",
    valid_tiers: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Assemble the conformance artifact mapping.

    Args:
        archetype: the loaded archetype catalog.
        refmodels_version: resolved reference-models repo version (or None).
        outcomes: per-concept outcome dicts (``uri``, ``label``, ``tier``, ``outcome``,
            optional ``rename_to`` / ``deviation_reason`` / ``business_area``, and the
            per-concept judgment-provenance fields ``confidence``, ``rationale``,
            ``references``, ``needs_confirmation``, ``decided_by`` — see DD-148).
        mode: ``"interactive"`` or ``"fleet"`` (DD-088) — the session mode this
            conformance run was produced under. Durable, since the session itself
            isn't persisted; ``open_questions()`` only inspects fleet-mode artifacts.
        archetype_confirmed_by: who confirmed the archetype id (DD-149). Archetype
            selection is never fleet-eligible, so this is always ``"human"`` in
            practice; callers must not stamp anything else.
        topology_confirmations: yes/no confirmation entries for derived relationship edges.
        cardinality_answers: answers to the genuinely-undeclared cardinality questions.
        discovery_doc: relative path/name of the paired discovery markdown, if any.
        generated_by: provenance tag.
        valid_tiers: tier enum used to seed the scorecard buckets — resolve it with
            :func:`~kairos_ontology.core.archetype_loader.load_valid_tiers`. Which tiers are
            seeded never affects validity: :func:`validate_artifact` compares scorecards with
            empty buckets normalised away.
    """
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "generated_by": generated_by,
        "generated_at": _utc_now_iso(),
        "mode": mode,
        "archetype": {
            "id": archetype.id,
            "label": archetype.label,
            "source": archetype.source_path.name,
            "catalog_hash": archetype.catalog_hash,
            "concept_set_hash": archetype.concept_set_hash(),
            "confirmed_by": archetype_confirmed_by,
        },
        "refmodels_version": refmodels_version,
        "discovery_doc": discovery_doc,
        "ref_model_modules": [{"iri": m.iri, "tier": m.tier} for m in archetype.ref_model_modules],
        "core_concepts": outcomes,
        "topology_confirmations": topology_confirmations or [],
        "cardinality_answers": cardinality_answers or [],
        "scorecard": compute_scorecard(outcomes, valid_tiers),
    }


def validate_artifact(
    artifact: dict[str, Any],
    outcome_codes: list[str],
    valid_tiers: tuple[str, ...] | None = None,
    archetype: Archetype | None = None,
) -> list[str]:
    """Return a list of validation error strings (empty when valid).

    Validates structural shape, concept URI/label/tier identity, that every outcome
    is one of *outcome_codes* (loaded from the contract — not hardcoded), conditional
    rename/deviation fields, duplicate concepts, and scorecard consistency.

    When *archetype* is supplied, this additionally checks (issue #308):

    * **coverage/identity** — every concept in *archetype*'s catalog has a corresponding
      ``core_concepts`` entry, and every ``core_concepts`` entry's uri/label/tier matches a
      real concept in *archetype*'s catalog (not merely well-formed) — this is what catches
      an artifact whose ``archetype.id`` names a *different* archetype than the one the
      recorded concepts actually came from, or that only covers a subset of concepts.
    * **staleness** — :func:`is_stale` against *archetype*; a stale artifact (its
      ``catalog_hash``/``concept_set_hash`` no longer match) fails validation instead of
      silently validating clean.

    Without *archetype* (the default), these two checks are skipped — callers that cannot
    resolve a reference-models checkout (e.g. offline unit tests) still get the rest of the
    shape/enum validation. The ``discovery-conformance validate`` CLI always resolves and
    passes an archetype (via ``--archetype`` or the artifact's own ``archetype.id``).

    Note: ``topology_confirmations``/``cardinality_answers`` shape validation (#308 hole 3)
    is intentionally not implemented here — it needs a reference-models-side change (giving
    ``topology.edges`` entries a machine-readable identifier instead of free prose) that is
    out of scope for this toolkit change; tracked separately in issue #308.

    Args:
        artifact: the parsed artifact mapping.
        outcome_codes: the published outcome enum (see
            :func:`~kairos_ontology.core.archetype_loader.load_outcome_codes`).
        valid_tiers: the published tier enum (see
            :func:`~kairos_ontology.core.archetype_loader.load_valid_tiers`). ``None`` uses the
            offline fallback :data:`~kairos_ontology.core.archetype_loader.VALID_TIERS`.
        archetype: the resolved archetype catalog to check identity/coverage/staleness
            against (see :func:`~kairos_ontology.core.archetype_loader.load_archetype`).
            ``None`` skips those checks.

    Note:
        The tier ``not_applicable`` (an archetype-side *obligation* level, "deliberately out of
        scope for this archetype") is a different thing from the outcome code ``not-applicable``
        (a hub-side *finding*, "the SME confirmed this does not apply"). Underscore vs. hyphen,
        catalog side vs. hub side — do not conflate them.
    """
    errors: list[str] = []
    if not isinstance(artifact, dict):
        return ["Artifact is not a mapping."]

    if artifact.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        errors.append(
            f"Unsupported artifact schema_version {artifact.get('schema_version')!r} "
            f"(expected {ARTIFACT_SCHEMA_VERSION})."
        )

    mode = artifact.get("mode")
    if mode not in VALID_MODES:
        errors.append(f"'mode' must be one of {sorted(VALID_MODES)}, got {mode!r}.")

    archetype_block = artifact.get("archetype")
    if (
        not isinstance(archetype_block, dict)
        or not isinstance(archetype_block.get("id"), str)
        or not archetype_block["id"].strip()
    ):
        errors.append("Missing or malformed 'archetype' block (needs an 'id').")
    elif archetype_block.get("confirmed_by") != "human":
        errors.append(
            "'archetype.confirmed_by' must be 'human' (DD-149): archetype selection "
            "is never fleet-eligible and must be explicitly confirmed by a person."
        )

    discovery_doc = artifact.get("discovery_doc")
    if discovery_doc is not None:
        if not isinstance(discovery_doc, str) or not discovery_doc.strip():
            errors.append("'discovery_doc' must be a non-empty string when present.")
        # 'discovery_doc' is always POSIX-style (forward slashes, contract row —
        # see build_artifact's docstring), so absoluteness is checked with
        # PurePosixPath rather than the platform Path: on Windows, plain Path is
        # WindowsPath, whose is_absolute() does not flag a leading-'/' POSIX-absolute
        # path (#313). The "\\" check is separate defense-in-depth: it catches a
        # Windows drive-letter-absolute path like 'C:\...' (which PurePosixPath alone
        # would not flag, since it has no leading '/') and any non-portable
        # backslash-separated path.
        elif PurePosixPath(discovery_doc).is_absolute() or "\\" in discovery_doc:
            errors.append(
                "'discovery_doc' must be a path relative to the reference-models root "
                f"(e.g. 'accelerator-packs/<pack>/discovery/<id>.md'), got: {discovery_doc!r}."
            )

    concepts = artifact.get("core_concepts")
    if not isinstance(concepts, list):
        errors.append("'core_concepts' must be a list.")
        return errors

    code_set = set(outcome_codes)
    tier_set = tuple(valid_tiers) if valid_tiers else VALID_TIERS
    seen_uris: dict[str, int] = {}
    for i, c in enumerate(concepts):
        if not isinstance(c, dict):
            errors.append(f"core_concepts[{i}] is not a mapping.")
            continue
        uri = c.get("uri")
        display_uri = uri if isinstance(uri, str) and uri else f"<index {i}>"
        if not isinstance(uri, str) or not uri.strip():
            errors.append(f"core_concepts[{i}] is missing a non-empty string 'uri'.")
        else:
            parsed = urlsplit(uri)
            local_name = parsed.fragment or parsed.path.rstrip("/").rsplit("/", 1)[-1]
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or not local_name:
                errors.append(
                    f"core_concepts[{i}] ({uri}): 'uri' must be an HTTP(S) concept URI "
                    "with a local name."
                )
            if uri in seen_uris:
                errors.append(
                    f"core_concepts[{i}] ({uri}): duplicate concept URI "
                    f"(first declared at index {seen_uris[uri]})."
                )
            else:
                seen_uris[uri] = i
        label = c.get("label")
        if not isinstance(label, str) or not label.strip():
            errors.append(f"core_concepts[{i}] ({display_uri}): missing non-empty string 'label'.")
        outcome = c.get("outcome")
        if not isinstance(outcome, str) or outcome not in code_set:
            errors.append(
                f"core_concepts[{i}] ({display_uri}): invalid outcome {outcome!r}; "
                f"must be one of {sorted(code_set)}."
            )
        rename_to = c.get("rename_to")
        deviation_reason = c.get("deviation_reason")
        if rename_to is not None and (not isinstance(rename_to, str) or not rename_to.strip()):
            errors.append(
                f"core_concepts[{i}] ({display_uri}): 'rename_to' must be a "
                "non-empty string when present."
            )
        if deviation_reason is not None and (
            not isinstance(deviation_reason, str) or not deviation_reason.strip()
        ):
            errors.append(
                f"core_concepts[{i}] ({display_uri}): 'deviation_reason' must be a "
                "non-empty string when present."
            )
        if outcome == "conforms-with-rename" and (
            not isinstance(rename_to, str) or not rename_to.strip()
        ):
            errors.append(
                f"core_concepts[{i}] ({display_uri}): 'conforms-with-rename' requires 'rename_to'."
            )
        if outcome == "deviates" and (
            not isinstance(deviation_reason, str) or not deviation_reason.strip()
        ):
            errors.append(
                f"core_concepts[{i}] ({display_uri}): 'deviates' requires 'deviation_reason'."
            )
        # #308 hole 4: the converse was unchecked — a stray 'rename_to'/'deviation_reason' on
        # an outcome that doesn't call for it validated clean, even though design-domain reads
        # 'rename_to' to pre-seed local names, so it silently changes downstream modelling.
        if rename_to and outcome != "conforms-with-rename":
            errors.append(
                f"core_concepts[{i}] ({display_uri}): 'rename_to' is only valid on "
                f"'conforms-with-rename', not {outcome!r}."
            )
        if deviation_reason and outcome != "deviates":
            errors.append(
                f"core_concepts[{i}] ({display_uri}): 'deviation_reason' is only valid on "
                f"'deviates', not {outcome!r}."
            )
        if rename_to and deviation_reason:
            errors.append(
                f"core_concepts[{i}] ({display_uri}): 'rename_to' and "
                "'deviation_reason' are contradictory on one outcome."
            )
        business_area = c.get("business_area")
        # #308 hole 5: business_area is optional, non-authoritative data (see the module
        # docstring), but was never type-checked at all — {not: a string} validated clean.
        if business_area is not None and (
            not isinstance(business_area, str) or not business_area.strip()
        ):
            errors.append(
                f"core_concepts[{i}] ({display_uri}): 'business_area' must be a "
                "non-empty string when present."
            )
        tier = c.get("tier")
        if tier not in tier_set:
            errors.append(
                f"core_concepts[{i}] ({display_uri}): invalid or missing tier {tier!r}; "
                f"must be one of {list(tier_set)}."
            )
        confidence = c.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0)
        ):
            errors.append(
                f"core_concepts[{i}] ({display_uri}): 'confidence' must be null or a "
                "number between 0.0 and 1.0."
            )
        rationale = c.get("rationale")
        if rationale is not None and not isinstance(rationale, str):
            errors.append(
                f"core_concepts[{i}] ({display_uri}): 'rationale' must be a string when present."
            )
        references = c.get("references")
        if references is not None and (
            not isinstance(references, list) or not all(isinstance(r, str) for r in references)
        ):
            errors.append(
                f"core_concepts[{i}] ({display_uri}): 'references' must be a list of strings."
            )
        likely_domains = c.get("likely_domains")
        if likely_domains is not None and (
            not isinstance(likely_domains, list)
            or not all(isinstance(d, str) and d.strip() for d in likely_domains)
        ):
            errors.append(
                f"core_concepts[{i}] ({display_uri}): 'likely_domains' must be null or a "
                "list of non-empty strings."
            )
        needs_confirmation = c.get("needs_confirmation", False)
        if not isinstance(needs_confirmation, bool):
            errors.append(
                f"core_concepts[{i}] ({display_uri}): 'needs_confirmation' must be a boolean."
            )
        decided_by = c.get("decided_by")
        if decided_by is not None and decided_by not in VALID_DECIDED_BY:
            errors.append(
                f"core_concepts[{i}] ({display_uri}): 'decided_by' must be one of "
                f"{sorted(VALID_DECIDED_BY)}, got {decided_by!r}."
            )

    scorecard_comparable = all(
        isinstance(c, dict) and isinstance(c.get("outcome"), str) and isinstance(c.get("tier"), str)
        for c in concepts
    )
    if scorecard_comparable:
        scorecard = artifact.get("scorecard")
        expected_scorecard = compute_scorecard(concepts, tier_set)
        if not isinstance(scorecard, dict):
            errors.append("Missing or malformed 'scorecard' block.")
        elif _scorecard_comparable_form(scorecard) != _scorecard_comparable_form(
            expected_scorecard
        ):
            errors.append(
                "'scorecard' contradicts 'core_concepts'; regenerate it from the recorded outcomes."
            )

    # #308 holes 1 + 2: `validate` never actually compared the artifact to the archetype it
    # claims to conform to, so an artifact with incomplete coverage, concepts belonging to a
    # different archetype, or a stale/tampered hash all validated clean. Opt-in on *archetype*
    # since resolving one needs a reference-models checkout (offline unit tests skip this).
    if archetype is not None:
        catalog_by_uri = {concept.uri: concept for concept in archetype.core_concepts}
        recorded_uris = {
            c.get("uri") for c in concepts if isinstance(c, dict) and isinstance(c.get("uri"), str)
        }
        for uri in sorted(set(catalog_by_uri) - recorded_uris):
            cc = catalog_by_uri[uri]
            errors.append(
                f"'core_concepts' is missing archetype concept {uri!r} ({cc.label}, "
                f"tier={cc.tier!r}); archetype {archetype.id!r} requires an outcome for "
                "every core concept."
            )
        for i, c in enumerate(concepts):
            if not isinstance(c, dict):
                continue
            uri = c.get("uri")
            if not isinstance(uri, str) or not uri.strip():
                continue
            cc = catalog_by_uri.get(uri)
            if cc is None:
                errors.append(
                    f"core_concepts[{i}] ({uri}) is not a core concept of archetype "
                    f"{archetype.id!r}'s catalog."
                )
                continue
            if c.get("label") != cc.label:
                errors.append(
                    f"core_concepts[{i}] ({uri}): 'label' {c.get('label')!r} does not match "
                    f"the catalog label {cc.label!r} for archetype {archetype.id!r}."
                )
            if c.get("tier") != cc.tier:
                errors.append(
                    f"core_concepts[{i}] ({uri}): 'tier' {c.get('tier')!r} does not match "
                    f"the catalog tier {cc.tier!r} for archetype {archetype.id!r}."
                )
        if is_stale(artifact, archetype):
            errors.append(
                "Conformance artifact is stale (DD-090): its recorded 'catalog_hash'/"
                f"'concept_set_hash' no longer match archetype {archetype.id!r} — rerun "
                "kairos-design-discovery against the current catalog."
            )
    return errors


def write_artifact(hub_root: Path, artifact: dict[str, Any]) -> Path:
    """Write *artifact* to ``<hub_root>/integration/discovery/core-concepts-conformance.yaml``.

    Creates the ``integration/discovery/`` directory if needed.  Returns the written path.
    """
    out_path = Path(hub_root) / ARTIFACT_RELPATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        yaml.safe_dump(artifact, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return out_path


def read_artifact(path: Path) -> dict[str, Any]:
    """Load a conformance artifact from *path* (``yaml.safe_load``).

    Raises:
        ConformanceArtifactError: if the file is missing or not a mapping.
    """
    path = Path(path)
    if not path.is_file():
        raise ConformanceArtifactError(f"Conformance artifact not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ConformanceArtifactError(
            f"Could not parse conformance artifact {path}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ConformanceArtifactError(f"Conformance artifact is not a mapping: {path}")
    return data


def _concept_in_scope(concept: dict[str, Any], domains: Collection[str] | None) -> bool:
    """Return True when *concept* is in scope for *domains* (issue #389/#390).

    ``domains`` is the caller's active-domain filter (e.g. ``--domain``/``--domains`` on the
    CLI). ``None`` or empty means unscoped — every concept is in scope, which is exactly
    today's behavior and matches every existing call site with zero change.

    When *domains* is non-empty, a concept surfaces only when it is **cross-cutting**
    (its ``likely_domains`` is absent or an empty list — the safe default for every
    pre-existing artifact, which must never be silently un-gated by this feature) or its
    ``likely_domains`` case-insensitively intersects *domains*.
    """
    if domains is None or not domains:
        return True
    likely_domains = concept.get("likely_domains")
    if not likely_domains:
        return True
    wanted = {d.lower() for d in domains}
    return any(isinstance(d, str) and d.lower() in wanted for d in likely_domains)


def open_questions(
    artifact: dict[str, Any], *, domains: Collection[str] | None = None
) -> list[dict[str, Any]]:
    """Return unresolved AI-decided concept judgments (DD-148), optionally domain-scoped.

    Keyed on the evidence recorded **per concept** — ``decided_by`` and
    ``needs_confirmation`` — never on the artifact-level ``mode`` marker. ``mode`` is a
    self-declared field inside the very artifact this function inspects (the DD-088
    fleet/interactive session marker); an artifact can claim ``mode: interactive`` while
    every concept was actually decided by AI and left unconfirmed, and gating on ``mode``
    let that self-declaration disable the entire check (issue #307). ``mode`` remains
    useful for provenance/reporting, just never as the condition here.

    A concept is unresolved when it is explicitly ``decided_by: "ai"`` and either
    ``needs_confirmation`` is true or ``confidence`` was never recorded. This applies in
    every mode — fleet and interactive alike — because the kairos-design-discovery skill
    marks every concept's ``decided_by`` explicitly (``"user"`` or ``"ai"``) regardless of
    session mode; a concept that omits ``decided_by`` altogether predates that bookkeeping
    (or was never AI-touched) and is not treated as AI-decided here.

    Args:
        artifact: the parsed conformance artifact.
        domains: optional active-domain filter (issue #389/#390) — see
            :func:`_concept_in_scope`. ``None`` (the default) is unscoped, matching every
            pre-existing call site exactly.
    """
    questions: list[dict[str, Any]] = []
    for concept in artifact.get("core_concepts") or []:
        if not isinstance(concept, dict):
            continue
        if concept.get("decided_by") != "ai":
            continue
        if not _concept_in_scope(concept, domains):
            continue
        needs_confirmation = bool(concept.get("needs_confirmation", False))
        confidence = concept.get("confidence")
        if needs_confirmation or confidence is None:
            questions.append(
                {
                    "uri": concept.get("uri"),
                    "label": concept.get("label"),
                    "reason": "needs_confirmation" if needs_confirmation else "missing confidence",
                    "domains": concept.get("likely_domains"),
                }
            )
    return questions


def has_unresolved_fleet_items(
    artifact: dict[str, Any], *, domains: Collection[str] | None = None
) -> bool:
    """Return True when *artifact* has at least one unresolved AI-decided judgment (DD-148).

    Name kept for existing call sites; the check itself is mode-agnostic — see
    :func:`open_questions`. *domains* is threaded straight through — see
    :func:`_concept_in_scope` for the scoping rule.
    """
    return bool(open_questions(artifact, domains=domains))


def _has_authored_discovery_narrative(hub_root: Path) -> bool:
    """Return True when ``businessdiscovery/`` has any authored (non-template) .ttl file.

    Uses the shared ``hub_utils.is_authored_discovery_ttl`` predicate (rather than a local
    copy) so this DD-148 hard gate and ``hub_inspection``'s advisory ``next`` snapshot can
    never drift apart again: a scaffold-provided template (init's
    businessdiscovery/glossary-template.ttl) is not authored evidence, and counting it as
    such here would silently disable this gate on a hub with zero real discovery content
    (issue #288). ``hub_utils`` is a dependency-light leaf module — importing it here does
    not create a cycle with ``hub_inspection`` (which imports from this module). This is the
    DD-048 discovery narrative/glossary, a separate artifact from the DD-090 conformance YAML
    this module otherwise deals with — either satisfies "discovery ran".
    """
    root = Path(hub_root) / "businessdiscovery"
    if not root.is_dir():
        return False
    try:
        return any(path.is_file() and is_authored_discovery_ttl(path) for path in root.rglob("*"))
    except OSError:
        return False


def check_discovery_gate(hub_root: Path, *, domains: Collection[str] | None = None) -> list[str]:
    """Return hard-gate error strings for *hub_root* (empty when the gate passes).

    Used by ``kairos-ontology compile``/``validate`` (DD-148) to hard-fail when business
    discovery hasn't run at all — neither a DD-048 ``businessdiscovery/`` narrative nor a
    DD-090 conformance artifact exists — or when a conformance artifact exists with
    concept judgments unconfirmed by a human, regardless of the session's ``mode`` (DD-088).
    The two artifacts are independent: a hub with only a narrative and no conformance run
    (e.g. no archetype applies) passes; the unresolved-judgments check only ever applies to
    the conformance artifact, since that's the only place judgment provenance is recorded.

    Deliberately lighter than ``validate_artifact()``: it never needs the reference-models
    outcome-codes catalog, since compile/validate must be able to run this check without
    resolving an accelerator.

    Args:
        domains: optional active-domain filter (issue #389/#390) threaded straight through
            to :func:`open_questions` — see :func:`_concept_in_scope` for the scoping rule.
            ``None`` (the default) is unscoped, matching every existing caller's behavior
            unchanged: an unresolved judgment tagged to an unrelated domain no longer blocks
            a domain-scoped ``compile``/``validate --domain``, while a cross-cutting one (no
            ``likely_domains``) or one tagged to the active domain still does.
    """
    hub_root = Path(hub_root)
    path = hub_root / ARTIFACT_RELPATH
    artifact: dict[str, Any] | None = None
    if path.is_file():
        try:
            artifact = read_artifact(path)
        except ConformanceArtifactError as exc:
            return [str(exc)]

    if artifact is None and not _has_authored_discovery_narrative(hub_root):
        return [
            "No business discovery evidence found (neither businessdiscovery/*.ttl nor "
            f"{ARTIFACT_RELPATH}) — run kairos-design-discovery first."
        ]
    if artifact is None:
        return []

    errors = []
    for question in open_questions(artifact, domains=domains):
        label = question.get("label") or question.get("uri") or "<unknown concept>"
        errors.append(
            f"Unresolved discovery item ({question['reason']}): {label} — "
            "confirm it with a human via kairos-design-discovery before proceeding."
        )
    return errors


def is_stale(artifact: dict[str, Any], archetype: Archetype) -> bool:
    """Return True when the artifact's concept set no longer matches *archetype*.

    Used by ``kairos-design-domain`` to warn (v1) that the conformance run predates the
    current archetype catalog and should be refreshed.
    """
    recorded = (artifact.get("archetype") or {}).get("concept_set_hash")
    if not recorded:
        return True
    return recorded != archetype.concept_set_hash()
