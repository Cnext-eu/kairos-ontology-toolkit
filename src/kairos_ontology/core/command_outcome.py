# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Shared exit-code / blocking-decision shape for CLI commands (issues #405, #408).

Several ``generate-*``/``check-*`` style commands process many independent sources in
one run (a directory of TTLs, a batch of tables, …) and need the same answer to one
question: **did this run produce enough to call the command successful, and does the
exit code reflect that?**

The axis that decides blocking is **artifact production, not per-command policy**.
Evidence for that split: ``import-flatfile`` is *both* in the same module — a total
failure (no table read from any file) raises :class:`ValueError` → exit 1
(:mod:`kairos_ontology.core.import_flatfile`, ``run_import_flatfile``'s "No CSV, Excel,
or Parquet files could be read" branch), while a *partial* failure (some files failed,
others produced tables) returns 0 and reports the failures for visibility
(:mod:`kairos_ontology.cli.sources`, documented at its ``import-flatfile-report``
rendering). A command that instead made *any* single independent-source failure
blocking would be unconvergeable whenever that source is something the invoking user
does not own and cannot fix (e.g. ``generate-inventory`` globbing a vendored
reference-models checkout — see ``core/catalog_test.py``'s "fail only for what the hub
author owns and can fix" exit-code policy, and ``cli/setup.py``'s ``init`` reference-
inventory pre-generation, which never aborts on a single source's failure).

This module is a **leaf**: no imports from :mod:`kairos_ontology.cli`, so it can be
unit-tested and consumed by any core module without pulling in Click.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Reason vocabulary (module-level constants, mirroring core/propose_alignment.py's
# OUTCOME_* constants — a fixed vocabulary instead of ad hoc strings at each call site,
# so every consumer classifies a decline the same way).
# ---------------------------------------------------------------------------

#: A source could not produce its artifact because another source already claimed the
#: same output name (a naming collision the toolkit will not silently resolve by guessing).
REASON_COLLISION = "collision"
#: A source raised while its artifact was being produced (parse error, write I/O error, …).
REASON_EXCEPTION = "exception"
#: A source parsed cleanly but yielded nothing that would produce an artifact (e.g. a TTL
#: with zero classes) — not a failure, just nothing to do for this source.
REASON_EMPTY = "empty"
#: A source was excluded by design before it was ever attempted (e.g. a pattern-library
#: template stub, or an archived reference-model version) — never a failure.
REASON_EXCLUDED = "excluded"

#: Reasons that block on their own — i.e. block even when the target that produced
#: them still produced *something* (so ``CommandOutcomeTarget.total_failure`` alone
#: would not already catch them). A DD-054 name collision silently loses an entire
#: source's inventory with no other signal that it happened (the DD-054 amendment:
#: "aborts loudly on any residual same-name collision" rather than a `continue`d
#: ❌ that still exits 0), so it must always be author-actionable-and-blocking.
#:
#: ``REASON_EXCEPTION`` is deliberately *not* in this set: a source that raises while
#: being parsed/written is very often outside the hub author's ownership (e.g. a
#: vendored ``ontology-reference-models/`` checkout the author cannot edit), and the
#: DD-153/DD-047 ownership rule is to fail only for what the author owns and can fix.
#: Making every exception blocking would relocate #405's unconvergeable-forever
#: pathology from ``check-inventory`` to ``generate-inventory`` — exactly what DD-153
#: rejects. Such exceptions still surface (``has_warnings``) and still escalate under
#: ``--strict``; they just do not block a plain run on their own. Do not add
#: ``REASON_EXCEPTION`` here without re-reading that rationale.
_BLOCKING_REASONS = frozenset({REASON_COLLISION})


@dataclass(frozen=True, slots=True)
class CommandOutcomeDecline:
    """One source this run did not turn into a produced artifact, and why.

    Mirrors :class:`kairos_ontology.core.scaffold_system.ScaffoldSystemDecline`'s
    ``(item, reason, detail)`` shape: *item* identifies the source (a path, a table
    name, …), *reason* is one of this module's ``REASON_*`` constants (or a caller's
    own fixed vocabulary), and *detail* is the human-readable explanation.
    """

    item: str
    reason: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"item": self.item, "reason": self.reason, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class CommandOutcomeTarget:
    """Per-scope bookkeeping for one requested target within a run.

    A "target" is one independently-requested scope a command processes — e.g.
    ``generate-inventory``'s reference-models directory and ontologies directory are
    two separate targets, each glob-discovering its own sources. *attempted* is the
    number of sources discovered for this target (before any classification below);
    *produced* is how many became artifacts; *failed* is how many landed in
    :attr:`CommandOutcome.failed` (collision or exception) for this target.
    """

    name: str
    attempted: int = 0
    produced: int = 0
    failed: int = 0

    @property
    def total_failure(self) -> bool:
        """True when this target had sources to attempt and none produced an artifact
        because they failed.

        Deliberately requires *both* ``attempted > 0`` and ``failed > 0``: a target with
        nothing to attempt (an empty directory) or one whose sources were only
        legitimately excluded/empty (no failures at all) is not a failure — there was
        simply nothing to build, which must never be confused with "this target is
        broken."
        """
        return self.attempted > 0 and self.produced == 0 and self.failed > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "attempted": self.attempted,
            "produced": self.produced,
            "failed": self.failed,
            "total_failure": self.total_failure,
        }


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    """The exit-code-deciding summary of one command run over many independent sources.

    ``schema_version`` and :meth:`to_dict` mirror
    :class:`kairos_ontology.core.scaffold_system.ScaffoldSystemResult`. ``is_blocking``
    and ``has_warnings`` are named in the spirit of
    :class:`kairos_ontology.core.inventory.InventoryCheckReport` so no CLI command
    re-derives the blocking rule inline (the same drift ``core/hub_inspection.py``'s
    inline copy of ``InventoryCheckReport``'s rule caused — see issue #405's review).

    The rule::

        is_blocking =
              no artifact produced for any requested target
           or a named failure of a blocking kind occurred      # REASON_COLLISION today
           or (strict and (advisory_findings or a named failure of a non-blocking kind))

    ``no artifact produced for any requested target`` is
    ``any(t.total_failure for t in self.targets)`` — a target that had sources to
    attempt and produced nothing because all of them failed, regardless of *why* they
    failed. ``a named failure of a blocking kind`` distinguishes failure *kind* from
    failure *count*: every entry a caller routes into ``failed`` is, by construction,
    named individually in that command's own output (a decline a caller only discovers
    via aggregate silence, with no per-source name surfaced, does not belong in
    ``failed``), but not every named failure is equally actionable by the hub author.
    ``_BLOCKING_REASONS`` (currently just ``REASON_COLLISION``) lists the reasons that
    block a run on their own; a reason outside that set (e.g. ``REASON_EXCEPTION`` on a
    vendored source the author does not own) is *advisory* — it still shows up via
    ``has_warnings`` and still escalates under ``--strict``, but does not, by itself,
    fail a plain run. See ``_BLOCKING_REASONS``' comment for the ownership rationale.
    ``advisory_findings`` is an opt-in signal a caller sets when it has non-artifact-
    affecting findings that should only escalate under ``--strict`` (mirroring
    ``InventoryCheckReport.unverifiable``'s ``strict and report.unverifiable``
    treatment in ``check_inventory_cmd``).
    """

    command: str
    produced: tuple[str, ...] = ()
    failed: tuple[CommandOutcomeDecline, ...] = ()
    skipped: tuple[CommandOutcomeDecline, ...] = ()
    targets: tuple[CommandOutcomeTarget, ...] = ()
    strict: bool = False
    advisory_findings: bool = False
    schema_version: int = SCHEMA_VERSION

    @property
    def _non_blocking_failure(self) -> bool:
        """True when ``failed`` contains an entry whose reason is not, on its own,
        blocking (i.e. outside ``_BLOCKING_REASONS`` — today, a ``REASON_EXCEPTION``).

        Kept separate from ``advisory_findings`` (a caller-set opt-in bool) because
        this one is *derived* from the reasons a caller already recorded, not asserted
        independently — the same failure list feeds both ``is_blocking`` and
        ``has_warnings`` without the caller having to mirror it into a second flag.
        """
        return any(decline.reason not in _BLOCKING_REASONS for decline in self.failed)

    @property
    def is_blocking(self) -> bool:
        no_artifact_for_target = any(target.total_failure for target in self.targets)
        named_failure_of_blocking_kind = any(
            decline.reason in _BLOCKING_REASONS for decline in self.failed
        )
        escalatable = self.advisory_findings or self._non_blocking_failure
        return (
            no_artifact_for_target
            or named_failure_of_blocking_kind
            or (self.strict and escalatable)
        )

    @property
    def has_warnings(self) -> bool:
        """True when a source was skipped, failed in a non-blocking way, or an
        (unescalated) advisory finding exists."""
        return bool(self.skipped) or self._non_blocking_failure or self.advisory_findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "command": self.command,
            "produced": list(self.produced),
            "failed": [item.to_dict() for item in self.failed],
            "skipped": [item.to_dict() for item in self.skipped],
            "targets": [target.to_dict() for target in self.targets],
            "strict": self.strict,
            "advisory_findings": self.advisory_findings,
            "is_blocking": self.is_blocking,
            "has_warnings": self.has_warnings,
        }
