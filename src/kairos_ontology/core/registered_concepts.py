# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Hub-side registration of source-discovered concepts (issue #505, Layer B).

Three mechanisms could stop an ontology domain being modeled. Two of them turned out not to
exist as described:

* the archetype tier ``not_applicable`` is not in the published tier enum at all
  (``VALID_TIERS = ("required", "recommended", "optional")``) -- ref-models #82 was closed for
  exactly that reason, so #505's Layer A is moot;
* the ``not-applicable`` *outcome* is real, and issue #507 (Layer C) handles it.

The third is real and is what this module closes: **a business concept that exists in the
source data but has no entry in the archetype catalog at all is invisible to the entire
system**. Discovery only ever iterates the catalog, so such a concept cannot be judged, cannot
carry a ``likely_domains`` tag, never reaches ``design-landscape``, and never becomes an
authored domain. On the CLdN hub roughly ten BI-relevant concepts sat in this hole (planning
zones, tariff scales, empty-unit lifecycle, distance/toll matrix, order source attribution).

## The four design decisions #505 left open

1. **Human confirmation?** *Required*, consistent with DD-148/DD-149. A registration records
   ``decided_by``; an ``ai``/``autopilot`` registration with ``needs_confirmation: true`` or no
   ``confidence`` is an open question and blocks ``compile``/``validate`` exactly like an
   unresolved archetype judgment. Registration is a proposal until a human signs it.

2. **Persisted where?** Its own ``integration/discovery/registered-concepts.yaml``, with its own
   ``schema_version``, mirrored into a **sibling** ``registered_concepts`` list in the
   conformance artifact. Deliberately *not* inside the artifact's ``core_concepts``:
   ``validate_artifact``'s #308 coverage/identity checks require every ``core_concepts`` entry
   to be a real concept of the resolved archetype's catalog, and ``concept_set_hash`` staleness
   would fire on every registration. Registering a concept must not make the archetype look
   wrong.

3. **Extend the archetype schema for "open" concepts?** *No.* Registration is hub-side only;
   the reference-models repo is untouched. The archetype catalog stays a stable shared contract
   across every hub that uses it, and adding a concept to one hub never needs a cross-repo
   release.

4. **Scorecard interaction?** Registered concepts are counted in their own bucket, never folded
   into the archetype ``total``, so archetype-conformance percentages stay comparable across
   hubs. (Reported by ``discovery-conformance summarize``, which computes its payload
   independently -- the artifact's own ``scorecard`` is left alone for the same reason #507
   left it alone: ``validate_artifact`` compares it for equality against a recomputation.)

Leaf module: no :mod:`kairos_ontology.cli` imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Collection
from urllib.parse import urlsplit

import yaml

#: v1: initial shape.
SCHEMA_VERSION = 1

#: Default location relative to the hub root.
REGISTERED_RELPATH = Path("integration/discovery/registered-concepts.yaml")

#: Registered concepts always carry the ``optional`` tier. They were never recommended by an
#: archetype -- the source data argued them into scope -- so claiming ``required`` or
#: ``recommended`` would misrepresent a blueprint obligation the blueprint never made.
REGISTERED_TIER = "optional"

#: Mirrors ``conformance_artifact.VALID_DECIDED_BY``; duplicated rather than imported to keep
#: this module a leaf of that one rather than a cycle.
VALID_DECIDED_BY = {"user", "ai", "autopilot"}


class RegisteredConceptError(Exception):
    """Raised when the registered-concepts artifact is malformed or a registration is invalid."""


@dataclass(frozen=True)
class RegisteredConcept:
    """One source-discovered concept the archetype catalog does not contain."""

    uri: str
    label: str
    source_system: str
    source_evidence: tuple[str, ...]
    rationale: str
    tier: str = REGISTERED_TIER
    likely_domains: tuple[str, ...] = ()
    decided_by: str = "user"
    confidence: float | None = None
    needs_confirmation: bool = False
    registered_at: str = ""
    references: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "label": self.label,
            "tier": self.tier,
            "source_system": self.source_system,
            "source_evidence": list(self.source_evidence),
            "rationale": self.rationale,
            "likely_domains": list(self.likely_domains),
            "decided_by": self.decided_by,
            "confidence": self.confidence,
            "needs_confirmation": self.needs_confirmation,
            "references": list(self.references),
            "registered_at": self.registered_at,
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_concept_uri(value: Any) -> bool:
    """Same rule ``validate_artifact`` applies to ``core_concepts[].uri``: HTTP(S) + local name.

    Kept identical on purpose -- a registered concept ends up alongside catalog concepts in
    every downstream consumer, so accepting a shape the catalog would reject here would only
    push the failure somewhere less actionable.
    """
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlsplit(value)
    local_name = parsed.fragment or parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and bool(local_name)


def read_registered(hub_root: Path) -> list[dict[str, Any]]:
    """Return the hub's registered concepts, or ``[]`` when none are registered.

    An absent file is the normal case (most hubs register nothing), so it is not an error.
    A present-but-malformed file *is*: silently treating it as empty would erase a human's
    deliberate registrations without saying so.
    """
    path = Path(hub_root) / REGISTERED_RELPATH
    if not path.is_file():
        return []
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RegisteredConceptError(f"Could not parse {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise RegisteredConceptError(f"Registered-concepts artifact is not a mapping: {path}")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise RegisteredConceptError(
            f"Unsupported registered-concepts schema_version "
            f"{document.get('schema_version')!r} (expected {SCHEMA_VERSION}) in {path}"
        )
    concepts = document.get("concepts")
    if not isinstance(concepts, list):
        raise RegisteredConceptError(f"'concepts' must be a list in {path}")
    return [entry for entry in concepts if isinstance(entry, dict)]


def write_registered(hub_root: Path, concepts: list[dict[str, Any]]) -> Path:
    """Persist *concepts*, sorted by URI so the file's diff is stable across re-registrations."""
    path = Path(hub_root) / REGISTERED_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "kairos-ontology register-concept",
        "concepts": sorted(concepts, key=lambda entry: str(entry.get("uri") or "")),
    }
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return path


def validate_registered(concepts: list[dict[str, Any]]) -> list[str]:
    """Return error strings for a registered-concepts list (empty when valid)."""
    errors: list[str] = []
    seen: dict[str, int] = {}
    for index, entry in enumerate(concepts):
        if not isinstance(entry, dict):
            errors.append(f"concepts[{index}] is not a mapping.")
            continue
        uri = entry.get("uri")
        display = uri if isinstance(uri, str) and uri else f"<index {index}>"
        if not is_concept_uri(uri):
            errors.append(
                f"concepts[{index}] ({display}): 'uri' must be an HTTP(S) concept URI with a "
                "local name."
            )
        elif uri in seen:
            errors.append(
                f"concepts[{index}] ({uri}): duplicate registration (first at index {seen[uri]})."
            )
        else:
            seen[uri] = index
        label = entry.get("label")
        if not isinstance(label, str) or not label.strip():
            errors.append(f"concepts[{index}] ({display}): 'label' must be a non-empty string.")
        rationale = entry.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            errors.append(
                f"concepts[{index}] ({display}): 'rationale' must be a non-empty string — a "
                "registration adds a concept the archetype deliberately did not include, so "
                "why it belongs is the whole record."
            )
        evidence = entry.get("source_evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(
                f"concepts[{index}] ({display}): 'source_evidence' must be a non-empty list of "
                "'<table>' or '<table>.<column>' strings — registration is a claim about source "
                "data, and an unevidenced claim is a guess."
            )
        tier = entry.get("tier")
        if tier != REGISTERED_TIER:
            errors.append(
                f"concepts[{index}] ({display}): 'tier' must be {REGISTERED_TIER!r} — a "
                "registered concept was never recommended by an archetype, so it cannot claim "
                "a blueprint obligation the blueprint never made."
            )
        decided_by = entry.get("decided_by")
        if decided_by is not None and decided_by not in VALID_DECIDED_BY:
            errors.append(
                f"concepts[{index}] ({display}): 'decided_by' must be one of "
                f"{sorted(VALID_DECIDED_BY)}."
            )
        confidence = entry.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0.0 <= float(confidence) <= 1.0
        ):
            errors.append(
                f"concepts[{index}] ({display}): 'confidence' must be a float between 0.0 and "
                "1.0, or omitted."
            )
    return errors


def register_concept(
    hub_root: Path,
    *,
    uri: str,
    label: str,
    source_system: str,
    source_evidence: Collection[str],
    rationale: str,
    likely_domains: Collection[str] = (),
    decided_by: str = "user",
    confidence: float | None = None,
    needs_confirmation: bool = False,
    references: Collection[str] = (),
    catalog_uris: Collection[str] = (),
    force: bool = False,
) -> tuple[Path, RegisteredConcept]:
    """Register one source-discovered concept and return ``(written path, entry)``.

    *catalog_uris* is the resolved archetype's own concept set. A URI already in it is
    **rejected**: that concept belongs in ``core_concepts`` with a real discovery judgment, and
    registering it instead would route it around the archetype coverage checks entirely.

    Re-registering an existing URI is rejected unless *force*, so a second run cannot silently
    overwrite a human's recorded rationale.
    """

    if not is_concept_uri(uri):
        raise RegisteredConceptError(
            f"--uri must be an HTTP(S) concept URI with a local name, got {uri!r}"
        )
    if uri in set(catalog_uris):
        raise RegisteredConceptError(
            f"{uri} is already a core concept of this archetype's catalog; record a discovery "
            "judgment for it via discovery-conformance instead of registering it."
        )
    if decided_by not in VALID_DECIDED_BY:
        raise RegisteredConceptError(
            f"--decided-by must be one of {sorted(VALID_DECIDED_BY)}, got {decided_by!r}"
        )

    entry = RegisteredConcept(
        uri=uri,
        label=label.strip(),
        source_system=source_system.strip(),
        source_evidence=tuple(sorted({str(item).strip() for item in source_evidence if item})),
        rationale=rationale.strip(),
        likely_domains=tuple(sorted({str(d).strip().lower() for d in likely_domains if d})),
        decided_by=decided_by,
        confidence=confidence,
        needs_confirmation=needs_confirmation,
        references=tuple(str(item).strip() for item in references if item),
        registered_at=_utc_now_iso(),
    )

    existing = read_registered(hub_root)
    if any(item.get("uri") == uri for item in existing) and not force:
        raise RegisteredConceptError(
            f"{uri} is already registered; pass --force to replace its recorded registration."
        )
    remaining = [item for item in existing if item.get("uri") != uri]
    payload = entry.to_dict()

    errors = validate_registered(remaining + [payload])
    if errors:
        raise RegisteredConceptError("; ".join(errors))

    return write_registered(hub_root, remaining + [payload]), entry


def registered_open_questions(
    concepts: list[dict[str, Any]], *, domains: Collection[str] | None = None
) -> list[dict[str, Any]]:
    """Unresolved AI-made registrations, in :func:`open_questions`' shape.

    Same rule as an archetype judgment (DD-148): AI-decided **and** either flagged
    ``needs_confirmation`` or carrying no ``confidence``. A registration adds a concept the
    blueprint deliberately did not include, so letting an AI make that call unreviewed would be
    a strictly larger authority than the one DD-148 already withholds for judging a concept the
    blueprint *did* include.
    """
    questions: list[dict[str, Any]] = []
    wanted = {str(d).lower() for d in domains} if domains else None
    for entry in concepts:
        if not isinstance(entry, dict):
            continue
        if entry.get("decided_by") not in ("ai", "autopilot"):
            continue
        likely_domains = entry.get("likely_domains") or []
        if wanted and likely_domains:
            if not any(isinstance(d, str) and d.lower() in wanted for d in likely_domains):
                continue
        needs_confirmation = bool(entry.get("needs_confirmation", False))
        if not needs_confirmation and entry.get("confidence") is not None:
            continue
        questions.append(
            {
                "uri": entry.get("uri"),
                "label": entry.get("label"),
                "reason": "needs_confirmation" if needs_confirmation else "missing confidence",
                "domains": likely_domains,
                "scope_reason": (
                    "tagged to domain(s): " + ", ".join(str(d) for d in likely_domains)
                    if likely_domains
                    else "cross-cutting (no likely_domains tagged)"
                ),
                "registered": True,
            }
        )
    return questions
