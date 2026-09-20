# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Render the accepted `registered-extension` decisions as draft OWL properties (#883).

Closing the DD-169 gate honestly is expensive: on one real hub it meant 701 column-grain
decisions, 501 of them `registered-extension` — each one a statement that a source column
carries business data the reference model has no property for, and each one backed by a
property `propose-alignment` had already drafted in full.

Nothing consumed them. The disposition's own definition points at `register-concept`,
which registers a **class** the archetype catalog lacks and rejects a URI already in the
catalog; these are **columns** wanting **properties** on classes that already exist. So an
operator who did the expensive right thing ended with 501 records no tool could act on,
and a strong incentive to go back to the cheap wrong answer next time.

This is the mechanical half of the answer. It does not decide anything: every property it
renders was already decided, by a human or an autopilot, and recorded with the name, range
and owning class the aligner proposed. It writes them out as OWL so they can be reviewed
as a diff and promoted, rather than re-derived by hand from a second file.

Draft output, following `suggest-shapes` (DD-076): written **outside** `model/ontologies/`
so the validator does not load it, because a generated property is a proposal until a
modeller moves it.

Two rules the generated TTL must satisfy, both enforced by `validate --syntax`:

* every property needs `rdfs:label`, `rdfs:domain` and (being a datatype property)
  `rdfs:range`;
* no source-system, table or column name may appear in `rdfs:comment` — source
  representation belongs in the EntityBinding, not the canonical model
  (`kairos-design-domain` SKILL.md §5). The ledger already records which columns argued
  for a property, so that evidence is not lost by keeping it out of here.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: Datatype ranges a generated property may carry. An `owl:ObjectProperty` needs a target
#: class and a relationship decision, which is modelling rather than rendering, so a
#: non-datatype range is reported and skipped instead of guessed.
XSD_RANGES: frozenset[str] = frozenset(
    {
        "xsd:string", "xsd:integer", "xsd:decimal", "xsd:boolean", "xsd:date",
        "xsd:dateTime", "xsd:time", "xsd:long", "xsd:double", "xsd:float",
        "xsd:duration", "xsd:anyURI",
    }
)

#: camelCase, per the naming gate `validate --syntax` applies to every property.
_CAMEL_CASE = re.compile(r"^[a-z][A-Za-z0-9]*$")

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


@dataclass(frozen=True, slots=True)
class ExtensionProperty:
    """One property to declare, and the decisions that asked for it."""

    name: str
    range: str
    on_class: str
    why: str
    columns: tuple[str, ...]  # "system.table.COLUMN", evidence only — never rendered


@dataclass
class ExtensionStubReport:
    """What could be rendered, and what could not."""

    properties: list[ExtensionProperty] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    decisions_seen: int = 0

    @property
    def classes(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for prop in self.properties:
            counts[prop.on_class] = counts.get(prop.on_class, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _skip(report: ExtensionStubReport, name: str, reason: str) -> None:
    report.skipped.append({"property": name, "reason": reason})


def collect_extension_properties(
    hub_root: Path, *, class_uris: dict[str, str] | None = None
) -> ExtensionStubReport:
    """Gather every accepted `registered-extension` decision that names a property.

    ``propose-alignment`` records ``on_class`` as a bare **local name** (``CargoItem``),
    not a URI — it names a class in the domain's own candidate pool. ``rdfs:domain``
    needs the URI, so *class_uris* maps local name to anchor URI and doubles as the
    scope: a decision naming a class outside it belongs to another domain's render.
    A value that is already a URI is passed through, so a caller holding real IRIs does
    not need the map.

    A decision recorded before `proposed_property` was structured carries the property
    only inside its prose rationale; it is counted and skipped rather than parsed back
    out of English.
    """
    from .source_disposition import load_dispositions

    report = ExtensionStubReport()
    merged: dict[str, ExtensionProperty] = {}
    evidence: dict[str, list[str]] = {}
    divergent: dict[str, set[str]] = {}
    unresolved: dict[str, str] = {}

    for entry in load_dispositions(Path(hub_root)).values():
        if str(entry.get("disposition") or "") != "registered-extension":
            continue
        if not str(entry.get("column") or ""):
            continue  # a table-grain extension is a different claim
        report.decisions_seen += 1
        proposal = entry.get("proposed_property") or {}
        name = str(proposal.get("name") or "")
        if not name:
            continue  # pre-#883 decision: the property lives only in the prose
        named = str(proposal.get("on_class") or "")
        on_class = _resolve_class(named, class_uris)
        if not on_class:
            if named:
                unresolved.setdefault(name, named)
            continue
        source = f"{entry.get('system')}.{entry.get('table')}.{entry.get('column')}"
        evidence.setdefault(name, []).append(source)
        divergent.setdefault(name, set()).add(f"{on_class}|{proposal.get('range')}")
        merged.setdefault(
            name,
            ExtensionProperty(
                name=name,
                range=str(proposal.get("range") or ""),
                on_class=on_class,
                why=str(proposal.get("why") or ""),
                columns=(),
            ),
        )

    for name, prop in sorted(merged.items()):
        if not _CAMEL_CASE.match(name):
            _skip(report, name, "not camelCase; validate --syntax rejects it")
            continue
        if not prop.on_class:
            _skip(report, name, "no owning class recorded")
            continue
        if prop.range not in XSD_RANGES:
            _skip(
                report,
                name,
                f"range {prop.range!r} is not a datatype; an object property needs a "
                "target class and a relationship decision",
            )
            continue
        if len(divergent[name]) > 1:
            _skip(
                report,
                name,
                "the same name was accepted with different class/range readings; "
                "resolve it before rendering",
            )
            continue
        report.properties.append(
            ExtensionProperty(
                name=prop.name,
                range=prop.range,
                on_class=prop.on_class,
                why=prop.why,
                columns=tuple(sorted(evidence[name])),
            )
        )
    for name, named in sorted(unresolved.items()):
        if name in merged:
            continue
        _skip(
            report,
            name,
            f"accepted on class {named!r}, which is not among this domain's anchors — "
            "it belongs to another domain's render",
        )
    return report


def _resolve_class(named: str, class_uris: dict[str, str] | None) -> str:
    """The class URI for a recorded ``on_class``, or ``""`` when out of scope."""
    if not named:
        return ""
    if "#" in named or "://" in named:
        return named if class_uris is None or named in class_uris.values() else ""
    if class_uris is None:
        return ""
    return class_uris.get(named, "")


def _label_of(name: str) -> str:
    """``billOfLadingNumber`` -> ``Bill of lading number``."""
    spaced = _CAMEL_BOUNDARY.sub(" ", name).strip()
    return spaced[:1].upper() + spaced[1:].lower() if spaced else name


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip()


def render_extension_ttl(
    report: ExtensionStubReport, *, namespace: str, domain: str
) -> str:
    """Render the collected properties as a draft Turtle document.

    Deliberately not a complete ontology: no ``owl:Ontology`` header and no
    ``owl:imports``, because this is a block to paste into an authored domain file after
    review, not a file to import. Grouped by owning class so a reviewer reads one
    concept at a time.
    """
    lines = [
        f"# Draft hub-local extension properties for the '{domain}' domain.",
        "#",
        "# Rendered from integration/sources/_analysis/table-dispositions.yaml: every",
        "# property below is a source column the DD-169 gate already accepted as",
        "# `registered-extension`, with the name, range and owning class recorded on that",
        "# decision. Nothing here is a new judgement.",
        "#",
        "# DRAFT. Review each one and move it into the owning domain's ontology; this file",
        "# is written outside model/ontologies/ so the validator does not load it.",
        "#",
        "# The columns that argued for each property stay in the disposition ledger, not",
        "# here: source representation belongs in the EntityBinding, and a source-system",
        "# name in an rdfs:comment fails `validate --syntax`.",
        "",
        f"@prefix : <{namespace}> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
    ]
    by_class: dict[str, list[ExtensionProperty]] = {}
    for prop in report.properties:
        by_class.setdefault(prop.on_class, []).append(prop)

    for on_class, props in sorted(by_class.items(), key=lambda item: (-len(item[1]), item[0])):
        local = on_class.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        lines += [
            "# " + "-" * 74,
            f"# {len(props)} propert{'y' if len(props) == 1 else 'ies'} on {local}",
            "# " + "-" * 74,
            "",
        ]
        for prop in sorted(props, key=lambda p: p.name):
            comment = _escape(prop.why) or f"Hub-local extension property on {local}."
            lines += [
                f":{prop.name} a owl:DatatypeProperty ;",
                f'    rdfs:label "{_escape(_label_of(prop.name))}"@en ;',
                f'    rdfs:comment "{comment}"@en ;',
                f"    rdfs:domain <{on_class}> ;",
                f"    rdfs:range {prop.range} .",
                "",
            ]
    return "\n".join(lines)


def anchor_classes_for_domain(analysis_dir: Path, domain: str) -> dict[str, str]:
    """``local name -> anchor URI`` for the classes the sheet assigns to *domain*.

    Keyed on the local name because that is how a decision records its owning class;
    valued with the URI because that is what ``rdfs:domain`` needs.
    """
    from .anchor_tables import load_table_anchors

    try:
        anchors = load_table_anchors(Path(analysis_dir))
    except Exception:  # noqa: BLE001 - advisory; an unreadable sheet scopes to nothing
        return {}
    resolved: dict[str, str] = {}
    for entry in anchors.values():
        if str(entry.get("domain") or "") != domain:
            continue
        uri = str(entry.get("anchor_uri") or "")
        if not uri:
            continue
        resolved.setdefault(uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1], uri)
    return resolved


def build_extension_stubs(
    hub_root: Path, *, domain: str, namespace: str
) -> tuple[str, ExtensionStubReport]:
    """Collect and render one domain's accepted extension properties."""
    hub_root = Path(hub_root)
    analysis = hub_root / "integration" / "sources" / "_analysis"
    classes = anchor_classes_for_domain(analysis, domain)
    report = collect_extension_properties(hub_root, class_uris=classes)
    return render_extension_ttl(report, namespace=namespace, domain=domain), report
