# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Class-level disposition ledger (DD-231, #847).

Source **tables** have a disposition ledger (DD-164): an unbound, undisposed table is an
error, not an omission. Ontology **classes** had the opposite: an ``owl:Class`` no
EntityBinding targets never enters the CompilePlan, so it is silently absent from the
contract, from Silver, from the ERDs and from Gold -- not an error, not a warning. That
silence is correct as a *compile* behaviour (the ontology is allowed to run ahead of its
sources), but there was nowhere to record the intent. "Not bound yet, deliberately,
because X" could only be inferred from ``design-landscape``, which persists nothing and
cannot tell "deferred" from "forgotten".

The population that makes this bite is a context engineer's logical model carried into the
ontology as a deliberate superset of Silver: dozens of authored, meaningful classes whose
status otherwise lives in someone's memory.

This module makes the decision an artifact, ``integration/discovery/class-dispositions.yaml``,
beside the other class-IRI-keyed discovery artifacts. Four defects of the source ledger are
not reproduced here: a malformed ledger *raises* rather than reading as empty; ``decided_by``
is closed in core, not only in the CLI; ``clear`` is reachable from the CLI; and ``list
--undecided`` exists.

Adoption is opt-in, then binding: until the hub creates the ledger every undecided class is
a **warning** (no existing hub goes red on upgrade); once the ledger exists an undecided
class is an **error**, degradable with ``--degraded`` exactly like DD-164. Same shape as
adopting a Silver contract (DD-213 §6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from .hub_utils import is_domain_ontology

SCHEMA_VERSION = 1
GENERATED_BY = "kairos-ontology class-disposition"

#: Where the ledger lives, relative to the hub root. Class-IRI-keyed artifacts live under
#: ``integration/discovery/`` (registered concepts, core-concepts conformance);
#: ``integration/sources/_analysis/`` is for source-keyed ones.
LEDGER_RELPATH = Path("integration") / "discovery" / "class-dispositions.yaml"

#: The closed set of authored answers. Each is a decision someone can defend in review.
DISPOSITIONS: dict[str, str] = {
    "deferred": (
        "In scope and to be bound later; carries a reason and stays visible as a known gap."
    ),
    "architecture-only": (
        "A concept the architecture needs -- a bounded context's aggregate, a logical-model "
        "class, a published-language term -- with no Silver intent. Never a binding target "
        "until this disposition is withdrawn."
    ),
    "abstract": (
        "A superclass that groups its subclasses and is never instantiated on its own; the "
        "subclasses carry the data."
    ),
}

#: Dispositions a human (or an attributed agent) must justify in prose.
_REQUIRES_RATIONALE = frozenset({"deferred", "architecture-only"})

#: Who may be recorded as having decided. Closed here, not only in the CLI: the source
#: ledger validated this in ``click.Choice`` alone, and hand-written entries passed.
DECIDED_BY: tuple[str, ...] = ("user", "ai", "autopilot")

#: Derived statuses, never authored: the bindings directory is the authority.
STATUS_BOUND = "bound"
STATUS_BOUND_VIA_SUBCLASS = "bound-via-subclass"

CODE_UNDECIDED = "class-disposition.undecided-class"
CODE_UNKNOWN_VALUE = "class-disposition.unknown-value"
CODE_MISSING_RATIONALE = "class-disposition.missing-rationale"
CODE_UNKNOWN_DECIDER = "class-disposition.unknown-decider"
CODE_STALE = "class-disposition.stale"
CODE_UNKNOWN_CLASS = "class-disposition.unknown-class"
CODE_MALFORMED = "class-disposition.malformed-ledger"

#: ``@prefix x: <ns> .`` and SPARQL-style ``PREFIX x: <ns>``; group 1 may be empty (the
#: default prefix a domain file conventionally uses for its own terms).
_PREFIX_DECLARATION = re.compile(
    r"^\s*(?:@prefix|PREFIX)\s+([A-Za-z0-9_.-]*):\s*<([^>]*)>", re.IGNORECASE | re.MULTILINE
)


class ClassDispositionError(ValueError):
    """A ledger that cannot be trusted, or a record that must not be written."""


@dataclass(frozen=True)
class DomainFile:
    """One domain ontology file as the hub authored it: its own graph and its own prefixes."""

    name: str
    path: Path
    graph: Graph
    prefixes: dict[str, str]


@dataclass(frozen=True)
class HubClass:
    """One class the hub itself declares, in its own namespace."""

    iri: str
    domain: str
    label: str

    @property
    def local_name(self) -> str:
        return self.iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


@dataclass(frozen=True)
class ClassDiagnostic:
    level: str  # "error" | "warning"
    code: str
    message: str
    class_iri: str = ""
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "class": self.class_iri,
            "remediation": self.remediation,
        }


@dataclass
class ClassDispositionReport:
    schema_version: int = SCHEMA_VERSION
    ledger_present: bool = False
    diagnostics: list[ClassDiagnostic] = field(default_factory=list)
    classes_total: int = 0
    classes_bound: int = 0
    classes_disposed: int = 0
    classes_undecided: int = 0
    undecided: list[HubClass] = field(default_factory=list)
    statuses: dict[str, str] = field(default_factory=dict)
    notices: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[ClassDiagnostic]:
        return [d for d in self.diagnostics if d.level == "error"]

    @property
    def warnings(self) -> list[ClassDiagnostic]:
        return [d for d in self.diagnostics if d.level == "warning"]

    @property
    def is_blocking(self) -> bool:
        return bool(self.errors)

    def coverage(self) -> float:
        """Fraction of hub classes with *any* recorded outcome -- bound or disposed."""
        if not self.classes_total:
            return 1.0
        return round((self.classes_bound + self.classes_disposed) / self.classes_total, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ledger_present": self.ledger_present,
            "totals": {
                "classes": self.classes_total,
                "bound": self.classes_bound,
                "disposed": self.classes_disposed,
                "undecided": self.classes_undecided,
            },
            "decision_coverage": self.coverage(),
            "statuses": dict(sorted(self.statuses.items())),
            "undecided": [
                {"class": item.iri, "domain": item.domain, "label": item.label}
                for item in self.undecided
            ],
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "notices": list(self.notices),
        }


# ---------------------------------------------------------------------------
# Population: the classes the hub declares in its own namespaces
# ---------------------------------------------------------------------------


def load_domain_files(hub_root: Path) -> dict[str, DomainFile]:
    """Return each domain file's **own** graph and prefixes -- no import closure.

    Through the canonical loader (DD-103), keeping only the depth-0 source of each load
    result: the population is what the hub *declares*, and the resolved closure would pull
    the reference models in. Loaded ``degraded`` so an import the catalog cannot resolve
    does not silently drop the domain from the population -- imports are irrelevant here.
    Prefixes are read from the file text rather than from any graph, because a graph that
    came back from the loader's parse cache may not carry them. A file the loader cannot
    read is skipped; syntax is ``validate``'s job and is reported there.
    """
    files: dict[str, DomainFile] = {}
    hub_root = Path(hub_root)
    ontologies = hub_root / "model" / "ontologies"
    if not ontologies.is_dir():
        return files
    catalog = hub_root / "catalog-v001.xml"
    from .ontology_loader import SemanticProfile, load_ontology

    for path in sorted(ontologies.glob("*.ttl")):
        if not is_domain_ontology(path):
            continue
        try:
            loaded = load_ontology(
                path,
                catalog_path=catalog if catalog.is_file() else None,
                profile=SemanticProfile.KAIROS_DESIGN,
                degraded=True,
            )
        except Exception:  # noqa: BLE001 - syntax is reported by validate itself
            continue
        own = next(
            (source.graph for source in loaded.sources if source.manifest.import_depth == 0),
            None,
        )
        if own is None:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        prefixes = {match.group(1): match.group(2) for match in _PREFIX_DECLARATION.finditer(text)}
        files[path.stem] = DomainFile(name=path.stem, path=path, graph=own, prefixes=prefixes)
    return files


def _own_namespaces(graph: Graph) -> list[str]:
    return sorted(
        str(iri) for iri in graph.subjects(RDF.type, OWL.Ontology) if isinstance(iri, URIRef)
    )


def hub_classes(files: dict[str, DomainFile]) -> list[HubClass]:
    """Every ``owl:Class`` a domain file declares under its own ontology IRI, IRI-sorted.

    A reference-model IRI re-declared locally to attach a label (the style
    ``kairos-design-domain`` recommends) is *not* in the population: it is not the hub's
    class to dispose of, and demanding a decision for it would be attrition, not
    governance.
    """
    classes: dict[str, HubClass] = {}
    for domain, item in sorted(files.items()):
        namespaces = _own_namespaces(item.graph)
        for cls in item.graph.subjects(RDF.type, OWL.Class):
            if not isinstance(cls, URIRef):
                continue
            iri = str(cls)
            if not any(iri.startswith(ns) for ns in namespaces):
                continue
            label = item.graph.value(cls, RDFS.label)
            classes.setdefault(
                iri,
                HubClass(
                    iri=iri,
                    domain=domain,
                    label=str(label) if label else iri.rsplit("#", 1)[-1],
                ),
            )
    return [classes[iri] for iri in sorted(classes)]


def resolve_class_token(
    token: str, files: dict[str, DomainFile], domain: str = ""
) -> Optional[str]:
    """Resolve an absolute IRI or ``prefix:Local`` token against the domain files' prefixes.

    The named domain's declarations are tried first, then every other domain's, so a
    binding whose ``metadata.domain`` is stale still resolves when any hub file declares
    the prefix. ``None`` when nothing does -- never a guess.
    """
    token = (token or "").strip()
    if not token:
        return None
    if "://" in token or token.startswith("urn:"):
        return token
    if ":" not in token:
        return None
    prefix, _, local = token.partition(":")
    order = [files[domain]] if domain in files else []
    order += [item for name, item in sorted(files.items()) if name != domain]
    for item in order:
        namespace = item.prefixes.get(prefix)
        if namespace is not None:
            return f"{namespace}{local}"
    return None


def bound_classes(hub_root: Path, files: dict[str, DomainFile]) -> dict[str, list[str]]:
    """Return ``{class IRI: [binding file, ...]}`` for every class an EntityBinding targets."""
    bound: dict[str, list[str]] = {}
    bindings_dir = Path(hub_root) / "integration" / "bindings"
    if not bindings_dir.is_dir():
        return bound
    for path in sorted(bindings_dir.glob("*.yaml")):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a malformed binding is the compiler's problem
            continue
        if not isinstance(payload, dict):
            continue
        target = payload.get("target") or {}
        metadata = payload.get("metadata") or {}
        token = str(target.get("class") or "") if isinstance(target, dict) else ""
        domain = str(metadata.get("domain") or "") if isinstance(metadata, dict) else ""
        iri = resolve_class_token(token, files, domain)
        if iri:
            bound.setdefault(iri, []).append(path.name)
    return bound


def _subclasses_of(iri: str, files: dict[str, DomainFile], population: set[str]) -> set[str]:
    """Hub classes below *iri*, transitively, across every domain file."""
    found: set[str] = set()
    frontier = [URIRef(iri)]
    while frontier:
        parent = frontier.pop()
        for item in files.values():
            for child in item.graph.subjects(RDFS.subClassOf, parent):
                if (
                    isinstance(child, URIRef)
                    and str(child) in population
                    and str(child) not in found
                ):
                    found.add(str(child))
                    frontier.append(child)
    return found


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------


def ledger_path(hub_root: Path) -> Path:
    return Path(hub_root) / LEDGER_RELPATH


def load_ledger(hub_root: Path) -> tuple[bool, dict[str, dict[str, Any]]]:
    """Return ``(present, {class IRI: entry})``.

    An absent file is the normal case before adoption and is not an error. A
    present-but-malformed file *is*: silently treating it as empty would erase every
    recorded decision without saying so, and turn a corrupt file into a wall of
    "undecided" errors pointing at the wrong problem.
    """
    path = ledger_path(hub_root)
    if not path.is_file():
        return False, {}
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ClassDispositionError(f"Could not parse {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ClassDispositionError(f"Class-disposition ledger is not a mapping: {path}")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ClassDispositionError(
            f"Unsupported class-disposition schema_version "
            f"{document.get('schema_version')!r} (expected {SCHEMA_VERSION}) in {path}"
        )
    entries = document.get("classes")
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise ClassDispositionError(f"'classes' must be a list in {path}")
    recorded: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not str(entry.get("class") or "").strip():
            raise ClassDispositionError(f"classes[{index}] in {path} has no 'class' IRI")
        recorded[str(entry["class"]).strip()] = entry
    return True, recorded


def _write_ledger(hub_root: Path, entries: dict[str, dict[str, Any]]) -> Path:
    path = ledger_path(hub_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": GENERATED_BY,
        # Sorted by IRI so the file's diff is stable across re-recordings.
        "classes": [entries[iri] for iri in sorted(entries)],
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def init_ledger(hub_root: Path) -> tuple[Path, bool]:
    """Create an empty ledger, turning undecided classes from warnings into errors.

    Returns ``(path, created)``; an existing ledger is left untouched. Creating the file is
    the adoption act (DD-213 §6 for contracts): from now on `validate` demands an answer
    for every hub class that no binding targets.
    """
    path = ledger_path(hub_root)
    if path.is_file():
        return path, False
    return _write_ledger(hub_root, {}), True


def record_class_disposition(
    *,
    hub_root: Path,
    class_iri: str,
    disposition: str,
    rationale: str = "",
    decided_by: str = "user",
    evidence: tuple[str, ...] = (),
) -> Path:
    """Write or replace one class's disposition, returning the ledger path.

    *class_iri* may be a ``prefix:Local`` token; it is resolved against the hub's domain
    files and must name a class the hub declares, so a typo cannot record a decision about
    nothing. Creates the ledger if absent -- recording the first decision is as much an
    adoption act as ``init``.
    """
    if disposition not in DISPOSITIONS:
        raise ClassDispositionError(
            f"Unknown disposition {disposition!r}; expected one of {sorted(DISPOSITIONS)}."
        )
    if disposition in _REQUIRES_RATIONALE and not rationale.strip():
        raise ClassDispositionError(f"Disposition {disposition!r} requires a rationale.")
    if decided_by not in DECIDED_BY:
        raise ClassDispositionError(
            f"Unknown decided_by {decided_by!r}; expected one of {sorted(DECIDED_BY)}."
        )
    files = load_domain_files(hub_root)
    iri = resolve_class_token(class_iri, files)
    population = {item.iri: item for item in hub_classes(files)}
    if iri is None or iri not in population:
        raise ClassDispositionError(
            f"{class_iri!r} is not a class this hub declares in its own namespace; "
            "check the IRI or prefix with 'kairos-ontology show-class-inventory'."
        )
    _present, entries = load_ledger(hub_root)
    entry: dict[str, Any] = {
        "class": iri,
        "domain": population[iri].domain,
        "disposition": disposition,
        "rationale": rationale.strip(),
        "decided_by": decided_by,
    }
    if evidence:
        entry["evidence"] = list(evidence)
    entries[iri] = entry
    return _write_ledger(hub_root, entries)


def clear_class_dispositions(
    hub_root: Path,
    *,
    classes: set[str] | None = None,
    disposition: str | None = None,
    decided_by: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove matching entries, returning what was (or would be) removed.

    Withdrawing a decision has to be as auditable and as reachable as recording it; the
    source ledger's ``clear`` existed in core but no command called it (#847). Filters are
    conjunctive and optional; ``decided_by`` lets an agent's blanket answers be withdrawn
    without touching a decision a human made.
    """
    present, entries = load_ledger(hub_root)
    if not present:
        return {"removed": 0, "kept": 0, "classes": []}
    files = load_domain_files(hub_root) if classes else {}
    wanted = {resolve_class_token(token, files) or token for token in (classes or ())}

    def matches(iri: str, entry: dict[str, Any]) -> bool:
        if classes is not None and iri not in wanted:
            return False
        if disposition is not None and str(entry.get("disposition") or "") != disposition:
            return False
        if decided_by is not None and str(entry.get("decided_by") or "") != decided_by:
            return False
        return True

    removed = sorted(iri for iri, entry in entries.items() if matches(iri, entry))
    kept = {iri: entry for iri, entry in entries.items() if iri not in removed}
    if removed and not dry_run:
        _write_ledger(hub_root, kept)
    return {"removed": len(removed), "kept": len(kept), "classes": removed}


# ---------------------------------------------------------------------------
# The audit `validate` runs
# ---------------------------------------------------------------------------


def _remediation(item: HubClass) -> str:
    return (
        "Bind it with kairos-design-mapping, or record why not: 'kairos-ontology "
        f"class-disposition set --class {item.iri} --disposition <"
        + "|".join(sorted(DISPOSITIONS))
        + '> --rationale "..."\'.'
    )


def audit_class_dispositions(*, hub_root: Path) -> ClassDispositionReport:
    """Require an outcome for every class the hub declares.

    Derived first: ``bound`` when an EntityBinding targets the class, ``bound-via-subclass``
    when a hub-local subclass is bound (the parent's data flows through the child). There
    is deliberately no ``bound-via-superclass``: a bound ``Party`` does not settle unbound
    ``Customer`` / ``Supplier`` subclasses, because bindings carry no discriminator;
    ``abstract``, ``deferred`` or ``architecture-only`` is the answer for those.

    Raises :class:`ClassDispositionError` for a ledger that cannot be trusted.
    """
    hub_root = Path(hub_root)
    files = load_domain_files(hub_root)
    population = hub_classes(files)
    report = ClassDispositionReport(classes_total=len(population))
    if not population:
        report.notices.append(
            "No hub-declared classes found under model/ontologies; nothing to decide."
        )
        return report

    present, entries = load_ledger(hub_root)
    report.ledger_present = present
    bound = bound_classes(hub_root, files)
    iris = {item.iri for item in population}

    for item in population:
        entry = entries.pop(item.iri, None)
        if item.iri in bound:
            report.classes_bound += 1
            report.statuses[item.iri] = STATUS_BOUND
            if entry is not None:
                report.diagnostics.append(
                    ClassDiagnostic(
                        "warning",
                        CODE_STALE,
                        f"{item.local_name} is recorded as '{entry.get('disposition')}' but "
                        f"{', '.join(bound[item.iri])} binds it; the ledger entry is stale.",
                        item.iri,
                        f"Withdraw it: 'kairos-ontology class-disposition clear --class {item.iri}'.",
                    )
                )
            continue
        if _subclasses_of(item.iri, files, iris) & set(bound):
            report.classes_bound += 1
            report.statuses[item.iri] = STATUS_BOUND_VIA_SUBCLASS
            continue
        if entry is not None:
            disposition = str(entry.get("disposition") or "").strip()
            decider = str(entry.get("decided_by") or "").strip()
            if disposition not in DISPOSITIONS:
                report.diagnostics.append(
                    ClassDiagnostic(
                        "error",
                        CODE_UNKNOWN_VALUE,
                        f"{item.local_name} records disposition {disposition!r}, which is not one "
                        f"of: {', '.join(sorted(DISPOSITIONS))}.",
                        item.iri,
                        "Use one of the closed disposition values.",
                    )
                )
                continue
            if disposition in _REQUIRES_RATIONALE and not str(entry.get("rationale") or "").strip():
                report.diagnostics.append(
                    ClassDiagnostic(
                        "error",
                        CODE_MISSING_RATIONALE,
                        f"{item.local_name} is recorded as '{disposition}' with no rationale.",
                        item.iri,
                        "State why, in one sentence. A reviewer cannot tell a considered "
                        "deferral from a forgotten class without it.",
                    )
                )
                continue
            if decider not in DECIDED_BY:
                report.diagnostics.append(
                    ClassDiagnostic(
                        "error",
                        CODE_UNKNOWN_DECIDER,
                        f"{item.local_name} records decided_by {decider!r}; expected one of "
                        f"{', '.join(DECIDED_BY)}.",
                        item.iri,
                        "Attribute the decision so a reviewer can weight it.",
                    )
                )
                continue
            report.classes_disposed += 1
            report.statuses[item.iri] = disposition
            continue

        report.classes_undecided += 1
        report.undecided.append(item)
        report.diagnostics.append(
            ClassDiagnostic(
                "error" if present else "warning",
                CODE_UNDECIDED,
                f"{item.domain}: {item.local_name} ({item.iri}) is neither bound nor given an "
                "explicit disposition.",
                item.iri,
                _remediation(item),
            )
        )

    # Entries left over name classes the hub does not declare: a typo, or a class that was
    # renamed or deleted after the decision was recorded.
    for iri in sorted(entries):
        report.diagnostics.append(
            ClassDiagnostic(
                "warning",
                CODE_UNKNOWN_CLASS,
                f"The ledger records {iri}, which no domain file declares in its own namespace.",
                iri,
                f"Withdraw it: 'kairos-ontology class-disposition clear --class {iri}'.",
            )
        )
    if not present and report.classes_undecided:
        report.notices.append(
            "No class-disposition ledger yet: undecided classes are warnings. Run "
            "'kairos-ontology class-disposition init' to make them errors (DD-231)."
        )
    return report
