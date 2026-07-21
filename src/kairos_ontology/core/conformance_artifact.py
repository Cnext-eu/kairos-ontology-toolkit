# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Core Concepts Conformance artifact: schema, builder, writer, reader (DD-090).

The conformance artifact (``ontology-hub/integration/discovery/core-concepts-conformance.yaml``)
is the **machine** output of the Core Concepts Conformance phase of ``kairos-design-discovery``.
``kairos-design-domain`` reads it at reference-model selection to pre-seed imports and
pre-justify known deviations. ``derive-claims`` may also consume a committed, validated
artifact to create proposed-only candidates; it never grants approval authority.

The artifact intentionally carries:

* the selected archetype id + label,
* ``ref_model_modules`` (iri + tier) so design-domain can pre-seed ``owl:imports``,
* the resolved reference-models version,
* ``catalog_hash`` + ``concept_set_hash`` for stale detection,
* per-concept outcomes (validated against the shared ``outcome-codes.yaml`` enum),
* topology confirmations + cardinality answers,
* a coverage scorecard.

It does **not** invent ``business_area`` as structured data — that grouping lives in the
discovery markdown and catalog comments, not the machine catalog, so it is optional and
non-authoritative here.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from .archetype_loader import Archetype, VALID_TIERS

#: Schema version of the conformance artifact itself.
ARTIFACT_SCHEMA_VERSION = 1

#: Default location of the artifact relative to the hub root.
ARTIFACT_RELPATH = Path("integration/discovery/core-concepts-conformance.yaml")


class ConformanceArtifactError(Exception):
    """Raised when a conformance artifact is malformed or fails validation."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_scorecard(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    """Return counts of outcomes overall and grouped by tier.

    Args:
        outcomes: list of per-concept dicts, each with at least ``outcome`` and ``tier``.
    """
    by_outcome = Counter(o.get("outcome", "unknown") for o in outcomes)
    by_tier: dict[str, Counter] = {tier: Counter() for tier in VALID_TIERS}
    for o in outcomes:
        tier = o.get("tier")
        if tier in by_tier:
            by_tier[tier][o.get("outcome", "unknown")] += 1
    return {
        "total": len(outcomes),
        "by_outcome": dict(sorted(by_outcome.items())),
        "by_tier": {tier: dict(sorted(c.items())) for tier, c in by_tier.items()},
    }


def build_artifact(
    *,
    archetype: Archetype,
    refmodels_version: str | None,
    outcomes: list[dict[str, Any]],
    topology_confirmations: list[dict[str, Any]] | None = None,
    cardinality_answers: list[dict[str, Any]] | None = None,
    discovery_doc: str | None = None,
    generated_by: str = "kairos-design-discovery",
) -> dict[str, Any]:
    """Assemble the conformance artifact mapping.

    Args:
        archetype: the loaded archetype catalog.
        refmodels_version: resolved reference-models repo version (or None).
        outcomes: per-concept outcome dicts (``uri``, ``label``, ``tier``, ``outcome``,
            optional ``rename_to`` / ``deviation_reason`` / ``business_area``).
        topology_confirmations: yes/no confirmation entries for derived relationship edges.
        cardinality_answers: answers to the genuinely-undeclared cardinality questions.
        discovery_doc: relative path/name of the paired discovery markdown, if any.
        generated_by: provenance tag.
    """
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "generated_by": generated_by,
        "generated_at": _utc_now_iso(),
        "archetype": {
            "id": archetype.id,
            "label": archetype.label,
            "source": archetype.source_path.name,
            "catalog_hash": archetype.catalog_hash,
            "concept_set_hash": archetype.concept_set_hash(),
        },
        "refmodels_version": refmodels_version,
        "discovery_doc": discovery_doc,
        "ref_model_modules": [
            {"iri": m.iri, "tier": m.tier} for m in archetype.ref_model_modules
        ],
        "core_concepts": outcomes,
        "topology_confirmations": topology_confirmations or [],
        "cardinality_answers": cardinality_answers or [],
        "scorecard": compute_scorecard(outcomes),
    }


def validate_artifact(artifact: dict[str, Any], outcome_codes: list[str]) -> list[str]:
    """Return a list of validation error strings (empty when valid).

    Validates structural shape, concept URI/label/tier identity, that every outcome
    is one of *outcome_codes* (loaded from the contract — not hardcoded), conditional
    rename/deviation fields, duplicate concepts, and scorecard consistency.
    """
    errors: list[str] = []
    if not isinstance(artifact, dict):
        return ["Artifact is not a mapping."]

    if artifact.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        errors.append(
            f"Unsupported artifact schema_version {artifact.get('schema_version')!r} "
            f"(expected {ARTIFACT_SCHEMA_VERSION})."
        )

    archetype = artifact.get("archetype")
    if (
        not isinstance(archetype, dict)
        or not isinstance(archetype.get("id"), str)
        or not archetype["id"].strip()
    ):
        errors.append("Missing or malformed 'archetype' block (needs an 'id').")

    concepts = artifact.get("core_concepts")
    if not isinstance(concepts, list):
        errors.append("'core_concepts' must be a list.")
        return errors

    code_set = set(outcome_codes)
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
            errors.append(
                f"core_concepts[{i}] ({display_uri}): missing non-empty string 'label'."
            )
        outcome = c.get("outcome")
        if not isinstance(outcome, str) or outcome not in code_set:
            errors.append(
                f"core_concepts[{i}] ({display_uri}): invalid outcome {outcome!r}; "
                f"must be one of {sorted(code_set)}."
            )
        rename_to = c.get("rename_to")
        deviation_reason = c.get("deviation_reason")
        if rename_to is not None and (
            not isinstance(rename_to, str) or not rename_to.strip()
        ):
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
                f"core_concepts[{i}] ({display_uri}): "
                "'conforms-with-rename' requires 'rename_to'."
            )
        if outcome == "deviates" and (
            not isinstance(deviation_reason, str) or not deviation_reason.strip()
        ):
            errors.append(
                f"core_concepts[{i}] ({display_uri}): "
                "'deviates' requires 'deviation_reason'."
            )
        if rename_to and deviation_reason:
            errors.append(
                f"core_concepts[{i}] ({display_uri}): 'rename_to' and "
                "'deviation_reason' are contradictory on one outcome."
            )
        tier = c.get("tier")
        if tier not in VALID_TIERS:
            errors.append(
                f"core_concepts[{i}] ({display_uri}): invalid or missing tier {tier!r}; "
                f"must be one of {list(VALID_TIERS)}."
            )

    scorecard_comparable = all(
        isinstance(c, dict)
        and isinstance(c.get("outcome"), str)
        and isinstance(c.get("tier"), str)
        for c in concepts
    )
    if scorecard_comparable:
        scorecard = artifact.get("scorecard")
        expected_scorecard = compute_scorecard(concepts)
        if not isinstance(scorecard, dict):
            errors.append("Missing or malformed 'scorecard' block.")
        elif scorecard != expected_scorecard:
            errors.append(
                "'scorecard' contradicts 'core_concepts'; regenerate it from the "
                "recorded outcomes."
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


def load_validated_artifact(
    path: Path, outcome_codes: list[str]
) -> dict[str, Any]:
    """Read and validate *path*, raising one explicit error for all findings."""
    artifact = read_artifact(path)
    errors = validate_artifact(artifact, outcome_codes)
    if errors:
        details = "\n".join(f"- {error}" for error in errors)
        raise ConformanceArtifactError(
            f"Invalid conformance artifact {Path(path)} "
            f"({len(errors)} error(s)):\n{details}"
        )
    return artifact


def is_stale(artifact: dict[str, Any], archetype: Archetype) -> bool:
    """Return True when the artifact's concept set no longer matches *archetype*.

    Used by ``kairos-design-domain`` to warn (v1) that the conformance run predates the
    current archetype catalog and should be refreshed.
    """
    recorded = (artifact.get("archetype") or {}).get("concept_set_hash")
    if not recorded:
        return True
    return recorded != archetype.concept_set_hash()
