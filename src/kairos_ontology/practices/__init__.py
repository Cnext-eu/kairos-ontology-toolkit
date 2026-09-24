# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The modelling best-practice catalogue (DD-240, issue #996).

One place where every best-practice rule the toolkit knows is defined, explained,
enforced and excused. Each area is a subfolder with a ``rules.yaml``:

* ``semantic-model/`` -- the shape of a Gold / Power BI model. The Microsoft Best
  Practice Analyzer rules are part of this area too, but their dispositions stay in
  ``core/projections/dbt/bpa_profile.py``, where the vendored upstream file is triaged
  (DD-238); the catalogue projects them in, so they are listed here without a second
  copy of the data.
* ``ddd/`` -- strategic and tactical DDD architecture. Documentation only (DD-091): a
  finding reports, and never changes Silver.

The catalogue is the source the generated hub pages (``docs/toolkit/practices/``) and
the design skills read, so a rule cannot say one thing in the skill and another in the
compiler. It declares rules; the checks that evaluate them stay next to the code they
inspect and name their entry here by ``check``.

Regenerate the pages after editing a ``rules.yaml``::

    uv run python scripts/generate_practices.py
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

ROOT = Path(__file__).parent

#: Areas, in the order the catalogue lists them. The folder name is the area.
AREAS = ("semantic-model", "ddd")

#: How a rule is enforced.
ENFORCEMENTS = ("blocking", "warning", "advisory", "post-deploy", "none")

#: Where a rule is checked. ``design`` means the design skill asks for it and nothing
#: evaluates it; ``none`` is a BPA rule the emitter satisfies by construction, or one
#: that does not apply or was rejected.
STAGES = (
    "validate --ddd",
    "compile --check",
    "emit-gold",
    "project --target ddd",
    "dataplatform",
    "design",
    "none",
)

#: The objects an exception can be attached to, per area.
EXCEPTION_OBJECTS = {
    "semantic-model": ("model", "table", "column", "measure", "relationship"),
    "ddd": ("class", "property", "context"),
}

_FIELDS = (
    "id",
    "statement",
    "rationale",
    "enforcement",
    "stage",
    "check",
    "source",
    "excusable",
)


@dataclass(frozen=True, slots=True)
class Practice:
    """One catalogued rule."""

    id: str
    area: str
    #: The rule in one sentence.
    statement: str
    #: Why it matters, with a concrete failure it prevents.
    rationale: str
    enforcement: str
    stage: str
    #: The diagnostic code of the implementing check, or ``none`` for advice.
    check: str
    #: The upstream authority: a BPA rule ID, a DD record, an issue.
    source: str
    #: Whether a hub may record an exception to it.
    excusable: bool
    #: The objects an exception may name; empty when the rule is not excusable.
    objects: tuple[str, ...] = ()
    #: True for an entry projected from the BPA profile rather than a ``rules.yaml``.
    bpa: bool = False


class CatalogueError(ValueError):
    """A ``rules.yaml`` entry is malformed. Raised at load, so the suite catches it."""


def _load_area(area: str) -> tuple[Practice, ...]:
    path = ROOT / area / "rules.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = payload.get("rules") or []
    practices = []
    for entry in entries:
        missing = [name for name in _FIELDS if name not in entry]
        if missing:
            raise CatalogueError(f"{path}: {entry.get('id', '?')} lacks {', '.join(missing)}")
        practice = Practice(
            id=str(entry["id"]),
            area=area,
            statement=" ".join(str(entry["statement"]).split()),
            rationale=" ".join(str(entry["rationale"]).split()),
            enforcement=str(entry["enforcement"]),
            stage=str(entry["stage"]),
            check=str(entry["check"]),
            source=str(entry["source"]),
            excusable=bool(entry["excusable"]),
            objects=tuple(entry.get("objects") or ()),
        )
        if not practice.id.startswith(f"{area}."):
            raise CatalogueError(f"{path}: {practice.id} is not in the {area}. namespace")
        if practice.enforcement not in ENFORCEMENTS:
            raise CatalogueError(f"{path}: {practice.id} enforcement {practice.enforcement!r}")
        if practice.stage not in STAGES:
            raise CatalogueError(f"{path}: {practice.id} stage {practice.stage!r}")
        if practice.excusable != bool(practice.objects) or not set(practice.objects) <= set(
            EXCEPTION_OBJECTS[area]
        ):
            raise CatalogueError(
                f"{path}: {practice.id} must name the objects an exception attaches to "
                "exactly when it is excusable"
            )
        practices.append(practice)
    return tuple(practices)


def _bpa_practices() -> tuple[Practice, ...]:
    """Project every BPA profile rule into the semantic-model area (DD-238)."""
    from ..core.projections.dbt import bpa_profile as bpa

    upstream = {rule["ID"]: rule for rule in bpa.load_upstream_rules()}
    kind_stage = {
        bpa.DispositionKind.COMPILE_DIAGNOSTIC: "compile --check",
        bpa.DispositionKind.RENDER_ASSERT: "emit-gold",
        bpa.DispositionKind.POST_DEPLOY_ADVISORY: "dataplatform",
    }

    def enforcement(item: bpa.Disposition) -> str:
        if item.kind is bpa.DispositionKind.RENDER_ASSERT or item.blocking:
            return "blocking"
        if item.kind is bpa.DispositionKind.COMPILE_DIAGNOSTIC:
            return "warning"
        if item.kind is bpa.DispositionKind.POST_DEPLOY_ADVISORY:
            return "post-deploy"
        return "none"

    practices = []
    for item in bpa.all_rules():
        # A rule's strictest target decides its row; BPA_PROFILE.md has both.
        strictest = min(
            (item.fabric, item.databricks),
            key=lambda value: ENFORCEMENTS.index(enforcement(value)),
        )
        scopes = bpa.rule_scopes(item.rule_id)
        objects = tuple(
            kind for kind, kind_scopes in bpa.IGNORE_OBJECT_SCOPES.items() if scopes & kind_scopes
        )
        rule = upstream.get(item.rule_id)
        practices.append(
            Practice(
                id=item.rule_id,
                area="semantic-model",
                statement=str(rule.get("Name", item.rule_id)) if rule else item.rule_id,
                rationale=strictest.reason,
                enforcement=enforcement(strictest),
                stage=kind_stage.get(strictest.kind, "none"),
                check=", ".join(
                    sorted({item.fabric.enforced_by, item.databricks.enforced_by} - {""})
                )
                or "none",
                source=f"BPA {item.rule_id}"
                + (f", {strictest.decision}" if strictest.decision else ""),
                # Any rule an exception can attach to (DD-238): a partition-scoped rule,
                # say, names no object an author could excuse.
                excusable=bool(objects),
                objects=objects,
                bpa=True,
            )
        )
    return tuple(practices)


@cache
def load_catalogue() -> tuple[Practice, ...]:
    """Every catalogued rule: each area's own rules, then the projected BPA rules."""
    practices: list[Practice] = []
    for area in AREAS:
        practices.extend(_load_area(area))
    practices.extend(_bpa_practices())
    seen: set[str] = set()
    for practice in practices:
        if practice.id in seen:
            raise CatalogueError(f"practice id {practice.id} is declared twice")
        seen.add(practice.id)
    return tuple(practices)


@cache
def _by_id() -> dict[str, Practice]:
    return {item.id: item for item in load_catalogue()}


@cache
def _by_check() -> dict[str, Practice]:
    return {
        code: item
        for item in load_catalogue()
        if not item.bpa
        for code in item.check.split(", ")
        if code != "none"
    }


def practice(practice_id: str) -> Practice | None:
    """Return the catalogued rule *practice_id*, or ``None``."""
    return _by_id().get(practice_id)


def practice_for_check(code: str) -> Practice | None:
    """Return the catalogue-owned rule a diagnostic *code* implements, or ``None``."""
    return _by_check().get(code)


def area_practices(area: str) -> tuple[Practice, ...]:
    return tuple(item for item in load_catalogue() if item.area == area)


# ---------------------------------------------------------------------------
# Generated pages
# ---------------------------------------------------------------------------

_TITLES = {
    "semantic-model": "Semantic model (Gold / Power BI) practices",
    "ddd": "DDD architecture practices",
}

_INTROS = {
    "semantic-model": (
        "Rules for the shape of a Gold semantic model: what the compiler reports about how "
        "facts, dimensions and relationships fit together. The object-level Microsoft Best "
        "Practice Analyzer rules follow, summarised; [BPA_PROFILE.md](../BPA_PROFILE.md) "
        "has each rule's disposition per storage mode."
    ),
    "ddd": (
        "Rules for the strategic and tactical DDD design recorded in the overlay "
        "(`*-ddd-ext.ttl`) and the strategic file (`ddd-contexts-ext.ttl`). Documentation "
        "only (DD-091): a finding is reported by `validate --ddd` and listed in the "
        "context design notes, and never changes Silver."
    ),
}

_EXCEPTION_HELP = {
    "semantic-model": (
        "Record an exception to an excusable rule in the Gold extension, on the "
        "`owl:Ontology` resource:",
        "```turtle",
        '<ontology> kairos-ext:practiceException "semantic-model.fact-to-fact on '
        "relationship fact_charge.consignment_id -> fact_consignment.consignment_id: "
        'charges are analysed per consignment by design" .',
        "```",
        "The reason is mandatory, and an exception that excuses nothing fails the check "
        "that would have made the finding, so it cannot outlive its reason. "
        "`kairos-ext:bpaIgnoreRule` is the same mechanism under its original name and "
        "keeps working for BPA rules.",
    ),
    "ddd": (
        "Record an exception to an excusable rule in the domain's DDD overlay or the "
        "strategic file, on the `owl:Ontology` resource. The target is the full IRI or the "
        "local name of the class, property or context:",
        "```turtle",
        '<ontology> kairos-ddd:practiceException "ddd.cross-context-relationship-on-map on '
        'property hasCarrier: the carrier is read from a published reference list" .',
        "```",
        "The reason is mandatory, and an exception that excuses nothing fails "
        "`validate --ddd` (`ddd.practice-exception-unused`).",
    ),
}


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render_area_markdown(area: str) -> str:
    """Render ``docs/guide/practices/<area>.md``. Deterministic: no clock, no environment."""
    own = [item for item in area_practices(area) if not item.bpa]
    lines = [
        f"# {_TITLES[area]}",
        "",
        "<!-- Generated by `python scripts/generate_practices.py`. Do not edit by hand. -->",
        "",
        _INTROS[area],
        "",
        "Enforcement: **blocking** fails the stage; **warning** is reported and never "
        "blocks; **advisory** is reported for review; **post-deploy** is checked against "
        "the deployed model by the dataplatform; **none** needs no check.",
        "",
        "## Rules",
        "",
    ]
    for item in own:
        lines += [
            f"### `{item.id}`",
            "",
            item.statement,
            "",
            f"- **Why:** {item.rationale}",
            f"- **Enforcement:** {item.enforcement}, at `{item.stage}`"
            if item.stage not in ("design", "none")
            else f"- **Enforcement:** {item.enforcement} ({item.stage} guidance)",
            f"- **Check:** `{item.check}`" if item.check != "none" else "- **Check:** none",
            f"- **Source:** {item.source}",
            "- **Excusable:** "
            + (f"yes, on a {' or '.join(item.objects)}" if item.excusable else "no"),
            "",
        ]
    lines += ["## Exceptions", "", *_EXCEPTION_HELP[area], ""]
    bpa_rules = [item for item in area_practices(area) if item.bpa]
    if bpa_rules:
        lines += [
            "## Best Practice Analyzer rules",
            "",
            "| Rule | Enforcement | Stage | Check |",
            "|---|---|---|---|",
        ]
        lines += [
            "| `{}` | {} | {} | {} |".format(
                item.id,
                item.enforcement,
                item.stage,
                ", ".join(f"`{code}`" for code in item.check.split(", "))
                if item.check != "none"
                else "—",
            )
            for item in bpa_rules
        ]
        lines.append("")
    return "\n".join(lines)
