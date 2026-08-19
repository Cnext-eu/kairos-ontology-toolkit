# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Design rulings — durable, transferable human modeling decisions (DD-192).

The measured problem no detector closes: a well-fitting wrong sibling
(``shipments`` anchored to ``Shipment`` maps enough properties to pass every
absolute check, while the defensible answers sit one sibling over). Only a
human resolves it — and without a durable record, that human resolves the
same ambiguity again on every re-run, every new table, every new hub.

A ruling records the resolution once, **by condition**, in
``integration/discovery/design-rulings.yaml``:

.. code-block:: yaml

    - id: DR-001
      kind: disambiguation          # disambiguation | rejection | preference
      scope:
        class_pair: [Shipment, TransportMovement]
        applies_when: "one row per executed physical movement: planned AND
          actual timestamps, vehicle/trailer resource columns, row chaining"
      ruling: TransportMovement
      rationale: "DCSA Shipment is the commercial consignment-level object."
      decided_by: user
      date: 2026-08-19

Rulings render into the global anchoring prompt and OUTRANK the model's own
reading of the catalog wherever their condition matches. Validated live: the
ruled table flipped to the ruled answer (0.91–0.95, rejected candidate kept
as alternate) with collateral movement confined to already-unstable rows —
the ruling applies by *condition*, not by table name, which is what makes it
transferable.

Boundaries that keep this from becoming a shadow ontology (§6c of the
signal-first proposal): a ruling never introduces a class (a ruling naming a
class the catalog cannot resolve is skipped and reported), never maps
columns, and is **always human-decided** — an entry whose ``decided_by`` is
not ``user`` is inert and reported, so a model may *propose* a ruling but an
unconfirmed proposal feeds nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

RULINGS_FILENAME = "design-rulings.yaml"
RULING_KINDS = frozenset({"disambiguation", "rejection", "preference"})


@dataclass(frozen=True, slots=True)
class DesignRuling:
    """One validated, human-decided ruling."""

    id: str
    kind: str
    ruling: str
    rationale: str
    applies_when: str
    class_pair: tuple[str, ...]

    def render(self) -> str:
        pair = "/".join(self.class_pair)
        condition = self.applies_when or "always"
        return (
            f"- [{self.id}] {self.kind} {pair}: when {condition} -> "
            f"anchor to '{self.ruling}'. Rationale: {self.rationale}"
        )


@dataclass(slots=True)
class RulingsLoadResult:
    """Loaded rulings plus everything that was rejected, with reasons."""

    rulings: list[DesignRuling]
    skipped: list[dict[str, str]]

    @property
    def path_note(self) -> str:
        return ""


def rulings_path(sources_dir: Path) -> Path:
    """The authored rulings file, sibling to ``integration/sources``."""
    return Path(sources_dir).parent / "discovery" / RULINGS_FILENAME


def load_design_rulings(path: Path) -> RulingsLoadResult:
    """Load and validate the rulings file. Absent file → empty result, no error.

    Validation is strict where the §6c boundaries demand it and lenient
    elsewhere: an entry that is not human-decided, names no ruling target, or
    is of an unknown kind is *skipped with a recorded reason* — never applied,
    never a hard failure that blocks anchoring.
    """
    result = RulingsLoadResult(rulings=[], skipped=[])
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return result
    except yaml.YAMLError as exc:
        result.skipped.append({"id": "<file>", "reason": f"unparseable YAML: {exc}"})
        return result
    if not isinstance(raw, list):
        if raw is not None:
            result.skipped.append({"id": "<file>", "reason": "expected a top-level list"})
        return result
    for entry in raw:
        if not isinstance(entry, dict):
            result.skipped.append({"id": "<entry>", "reason": "not a mapping"})
            continue
        rid = str(entry.get("id") or "<no-id>")
        kind = str(entry.get("kind") or "")
        ruling = str(entry.get("ruling") or "")
        decided_by = str(entry.get("decided_by") or "")
        if decided_by != "user":
            result.skipped.append(
                {"id": rid, "reason": f"decided_by is '{decided_by or '(absent)'}' — "
                                      "only human-decided rulings feed the prompt (§6c)"}
            )
            continue
        if kind not in RULING_KINDS:
            result.skipped.append({"id": rid, "reason": f"unknown kind '{kind}'"})
            continue
        if not ruling:
            result.skipped.append({"id": rid, "reason": "no ruling target"})
            continue
        scope = entry.get("scope") or {}
        if not isinstance(scope, dict):
            scope = {}
        result.rulings.append(
            DesignRuling(
                id=rid,
                kind=kind,
                ruling=ruling,
                rationale=str(entry.get("rationale") or ""),
                applies_when=str(scope.get("applies_when") or ""),
                class_pair=tuple(str(c) for c in scope.get("class_pair") or ()),
            )
        )
    return result


def render_rulings_prompt(rulings: list[DesignRuling]) -> str:
    """The prompt section: human authority, applied by condition."""
    if not rulings:
        return ""
    lines = "\n".join(r.render() for r in rulings)
    return (
        "\nHUMAN DESIGN RULINGS (accumulated decisions by this hub's owners — these "
        "OUTRANK your own reading of the catalog; apply each ruling wherever its "
        "condition matches, and never re-litigate it):\n" + lines + "\n"
    )


def partition_resolvable(
    rulings: list[DesignRuling], known_class_names: set[str]
) -> tuple[list[DesignRuling], list[dict[str, str]]]:
    """Split rulings into (applicable, skipped-with-reason) against the catalog.

    A ruling never introduces a class (§6c): a ``disambiguation``/``preference``
    whose target the catalog cannot resolve would steer the model toward a name
    the post-validation step must then null — so it is skipped and reported
    instead. ``rejection`` rulings name a class to AVOID, which needs no
    resolution to be actionable.
    """
    applicable: list[DesignRuling] = []
    skipped: list[dict[str, str]] = []
    for ruling in rulings:
        if ruling.kind != "rejection" and ruling.ruling not in known_class_names:
            skipped.append(
                {"id": ruling.id,
                 "reason": f"ruling target '{ruling.ruling}' does not resolve in the "
                           "catalog — a ruling never introduces a class (§6c)"}
            )
            continue
        applicable.append(ruling)
    return applicable, skipped
