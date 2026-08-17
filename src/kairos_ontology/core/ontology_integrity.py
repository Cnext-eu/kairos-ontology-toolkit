# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Hub-wide ontology integrity checks (DD-163).

Every other validator in this package is *single-file*: ``validate_naming_conventions``
parses one domain ``.ttl`` with no import resolution, and ``validate_managed_imports``
compares one domain's declared ``owl:imports`` against the blueprint. That scoping is
correct for what they check and is exactly why the defect class this module addresses
went undetected across a full 21-domain autopilot run.

The defects here are only visible when the hub is read *as a whole*, or when a file is
read against the blueprint boundary that placed it:

* the same concept minted as an unrelated local class in eight domains
  (``party#Booking``, ``mdm#Booking``, ``cargo#Booking``, ...), which no single-file
  parse can see and which reaches the user as a dbt duplicate-model build failure;
* a class whose own file header lists it under ``Deliberate exclusions``;
* a class the accelerator blueprint's ``does_not_own`` prose explicitly places
  elsewhere;
* a local class or property that is a name-for-name duplicate of a term in a module the
  file already imports, declared with no ``rdfs:subClassOf`` / ``rdfs:subPropertyOf``
  link to it — the reference model is imported and then ignored;
* an ``owl:imports`` that no term in the file references at all.

Design constraints this module holds to:

* **Deterministic.** No LLM, no network. Same hub in, same diagnostics out.
* **Precision over recall.** A false positive on a blocking check costs a human a
  manual override and teaches them to pass ``--degraded``; each check below either
  reads a machine-readable fact (two files declare the same local name) or the hub's
  own written-down intent (its header, its blueprint's ``does_not_own``). Fuzzy
  "does this feel like the wrong domain" inference is deliberately absent.
* **Advisory checks stay advisory.** Only the checks in :data:`BLOCKING_CODES` are
  errors; the rest report and never fail a build, so tightening one later is a
  reviewable one-line change rather than a rewrite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from rdflib import Graph, RDFS, URIRef
from rdflib.namespace import OWL, RDF

SCHEMA_VERSION = 1

#: Errors ``--degraded`` cannot clear.
#:
#: A blanket bypass on every integrity error would hand the mode that caused this defect
#: class a one-flag exit from it -- kairos-design-domain already tells fleet mode it "may
#: pass it explicitly". So the escape is scoped to the one check a hub might legitimately
#: fail, and withheld from the two where it cannot:
#:
#: * ``class-redeclared-across-domains`` -- two domains minting the same concept is a
#:   real downstream build break (colliding dbt model filenames), not a judgement call.
#:   There is no hub for which this is correct, so there is nothing to bypass.
#: * ``class-violates-declared-exclusion`` -- the file contradicts its own header. The
#:   fix costs nothing (delete the class, or correct the header if the exclusion is no
#:   longer intended), so a bypass would only preserve an inconsistency.
NON_DEGRADABLE_CODES: frozenset[str] = frozenset(
    {
        "integrity.class-redeclared-across-domains",
        "integrity.class-violates-declared-exclusion",
    }
)

#: Errors a hub may clear with ``--degraded``: a hub does not own the accelerator pack
#: and can have a defensible reason to diverge from a boundary it cannot edit.
DEGRADABLE_CODES: frozenset[str] = frozenset(
    {
        "integrity.class-outside-blueprint-boundary",
        # Same defect class as missing_managed_import, which validator.py:1470
        # deliberately makes degradable. A stricter sibling for the same kind of
        # mistake would be incoherent, and would newly block compile.
        "integrity.external-term-unresolved",
    }
)

#: Diagnostics that fail ``validate``. Everything else in :data:`ALL_CODES` reports and
#: never changes an exit code.
BLOCKING_CODES: frozenset[str] = NON_DEGRADABLE_CODES | DEGRADABLE_CODES

ALL_CODES: tuple[str, ...] = (
    "integrity.class-redeclared-across-domains",
    "integrity.class-violates-declared-exclusion",
    "integrity.class-outside-blueprint-boundary",
    "integrity.local-class-shadows-reference-model",
    "integrity.local-property-shadows-reference-model",
    "integrity.managed-import-unused",
    "integrity.value-object-collapsed",
    "integrity.class-unanchored",
    "integrity.external-term-unresolved",
)

# Header block a domain .ttl uses to record what it deliberately leaves to other
# domains. Written by the kairos-design-domain exemplar; parsed here so the file's own
# stated intent becomes enforceable instead of decorative.
_EXCLUSIONS_HEADER_RE = re.compile(
    r"^#\s*Deliberate exclusions.*?:\s*$", re.IGNORECASE | re.MULTILINE
)
_COMMENT_LINE_RE = re.compile(r"^#(.*)$")

# Scalar suffixes that, clustered on one prefix, mean an address value object was
# flattened into loose strings (companyBillingAddress/City/Country/PostalCode) instead
# of an object-property link to a shared Address class.
_ADDRESS_SUFFIXES: frozenset[str] = frozenset(
    {"address", "city", "country", "postalcode", "postcode", "zipcode", "stateprovince", "state"}
)
_ADDRESS_CLUSTER_MIN = 3


@dataclass(frozen=True)
class IntegrityDiagnostic:
    """One hub-wide integrity finding."""

    level: str  # "error" | "warning"
    code: str
    message: str
    domain: str
    term_uri: Optional[str] = None
    remediation: str = ""

    @property
    def blocking(self) -> bool:
        return self.level == "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "domain": self.domain,
            "term_uri": self.term_uri,
            "remediation": self.remediation,
        }


@dataclass
class DomainOntology:
    """One parsed domain ``.ttl``, reduced to the facts the hub-wide checks need."""

    domain: str
    path: Path
    namespace: str
    classes: dict[str, str] = field(default_factory=dict)  # local name -> URI
    object_properties: dict[str, str] = field(default_factory=dict)
    datatype_properties: dict[str, str] = field(default_factory=dict)
    imports: tuple[str, ...] = ()
    header_exclusions: str = ""
    anchored_classes: frozenset[str] = frozenset()
    anchored_properties: frozenset[str] = frozenset()
    referenced_external: frozenset[str] = frozenset()
    property_domains: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: ``(subject_local_name, predicate_local_name, target_uri)`` for every external term
    #: this file names via subClassOf / subPropertyOf / equivalentClass / domain / range.
    #: Full URIs, unlike :attr:`referenced_external`, so a target can be checked for
    #: existence rather than only its module for import.
    external_term_refs: frozenset[tuple[str, str, str]] = frozenset()

    @property
    def properties(self) -> dict[str, str]:
        return {**self.object_properties, **self.datatype_properties}


@dataclass
class IntegrityReport:
    """Result of a hub-wide integrity audit."""

    schema_version: int = SCHEMA_VERSION
    diagnostics: list[IntegrityDiagnostic] = field(default_factory=list)
    domains_scanned: int = 0
    total_classes: int = 0
    total_properties: int = 0
    anchored_classes: int = 0
    anchored_properties: int = 0
    duplicate_class_declarations: int = 0
    imports_declared: int = 0
    imports_used: int = 0
    notices: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[IntegrityDiagnostic]:
        return [d for d in self.diagnostics if d.level == "error"]

    @property
    def warnings(self) -> list[IntegrityDiagnostic]:
        return [d for d in self.diagnostics if d.level == "warning"]

    @property
    def is_blocking(self) -> bool:
        return bool(self.errors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "domains_scanned": self.domains_scanned,
            "totals": {
                "classes": self.total_classes,
                "properties": self.total_properties,
                "anchored_classes": self.anchored_classes,
                "anchored_properties": self.anchored_properties,
                "duplicate_class_declarations": self.duplicate_class_declarations,
                "imports_declared": self.imports_declared,
                "imports_used": self.imports_used,
            },
            "scores": self.scores(),
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "notices": list(self.notices),
        }

    def scores(self) -> dict[str, float]:
        """Return the loop's fitness metrics, each a 0.0-1.0 ratio (higher is better)."""

        def ratio(good: int, total: int) -> float:
            return round(good / total, 4) if total else 1.0

        return {
            "class_uniqueness": ratio(
                self.total_classes - self.duplicate_class_declarations, self.total_classes
            ),
            "class_anchoring": ratio(self.anchored_classes, self.total_classes),
            "property_anchoring": ratio(self.anchored_properties, self.total_properties),
            "import_utilisation": ratio(self.imports_used, self.imports_declared),
        }


# ---------------------------------------------------------------------------
# Prose matching
# ---------------------------------------------------------------------------


def _singular(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("sses"):
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        return token[:-1]
    return token


def _prose_tokens(text: str) -> set[str]:
    """Return lowercase singular word tokens from free-text blueprint/header prose."""
    return {_singular(word) for word in re.findall(r"[A-Za-z]+", text.lower()) if len(word) > 2}


def _split_camel(name: str) -> list[str]:
    return [part.lower() for part in re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+", name)]


def class_named_in_prose(class_name: str, prose: str) -> bool:
    """True when *prose* names the concept *class_name* denotes.

    Matches on the class's **head noun** — the last word of its CamelCase name — so
    ``TerminalBooking`` and ``IntermodalBooking`` both match prose saying "bookings",
    which is the whole point: prefixing a leaked class with the local domain name is
    the most common way the boundary gets crossed while looking compliant.

    Deliberately conservative: single-word prose tokens only, singularised on both
    sides, and a minimum length so short words cannot collide.
    """
    if not prose.strip():
        return False
    parts = _split_camel(class_name)
    if not parts:
        return False
    head = _singular(parts[-1])
    if len(head) < 4:
        return False
    return head in _prose_tokens(prose)


def extract_header_exclusions(text: str) -> str:
    """Return the ``Deliberate exclusions`` comment block from a domain ``.ttl``.

    Returns an empty string when the file has no such block, which makes the
    corresponding check a silent no-op rather than a failure — a hub predating the
    exemplar header must not be punished for it.
    """
    match = _EXCLUSIONS_HEADER_RE.search(text)
    if match is None:
        return ""
    lines: list[str] = []
    for raw in text[match.end() :].splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        comment = _COMMENT_LINE_RE.match(stripped)
        if comment is None:
            break
        body = comment.group(1).strip()
        # Only a divider (or the end of the comment header) closes the block. An earlier
        # heuristic also broke on any "Word Words:" line, which silently truncated the
        # block at scaffold-domain's own "Blueprint DOES NOT OWN:" line -- before the
        # bullets underneath it were ever read. Over-capturing trailing header prose is
        # harmless: parse_excluded_subjects only acts on bullets that name an owning
        # domain, and ignores everything else.
        if body.startswith("="):
            break
        lines.append(body)
    return "\n".join(lines)


#: ``- <subject phrase>: owned by the <domain> domain`` — the exemplar's exclusion form.
_OWNED_BY_RE = re.compile(r"owned by the\s+([A-Za-z][A-Za-z0-9-]*)\s+domain", re.IGNORECASE)


def parse_excluded_subjects(block: str, *, domain: str) -> list[tuple[str, str]]:
    """Return ``(subject_phrase, owning_domain)`` for each genuine exclusion bullet.

    The exemplar's exclusion block mixes two kinds of bullet and only one is an
    exclusion::

        - Party bookings: owned by the booking domain; ...      <- excluded
        - Contact details: owned by the party domain as PII ... <- NOT excluded

    The second names *this* domain as the owner: it is a clarification that the domain
    does own the concept, and reading it as an exclusion would flag the very class the
    header is defending. Only bullets naming a different owner are returned.
    """
    bullets: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("-"):
            bullets.append(stripped.lstrip("- ").strip())
        elif bullets:
            # Wrapped continuation of the previous bullet.
            bullets[-1] = f"{bullets[-1]} {stripped}"

    excluded: list[tuple[str, str]] = []
    for bullet in bullets:
        owner_match = _OWNED_BY_RE.search(bullet)
        if owner_match is None:
            continue
        owner = owner_match.group(1).lower()
        if owner == domain.lower():
            continue
        subject = bullet.split(":", 1)[0] if ":" in bullet else bullet[: owner_match.start()]
        if subject.strip():
            excluded.append((subject.strip(), owner))
    return excluded


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def _local_name(uri: str) -> str:
    if "#" in uri:
        return uri.rsplit("#", 1)[1]
    return uri.rstrip("/").rsplit("/", 1)[-1]


def _namespace_of(uri: str) -> str:
    if "#" in uri:
        return uri.rsplit("#", 1)[0] + "#"
    return uri.rstrip("/").rsplit("/", 1)[0] + "/"


def scan_domain_ontology(
    path: Path,
    domain: str,
    module_terms: Optional[dict[str, dict[str, set[str]]]] = None,
) -> Optional[DomainOntology]:
    """Parse one domain ``.ttl`` into the facts the hub-wide checks need.

    Returns ``None`` when the file cannot be parsed — syntax is already the
    single-file validator's job and reporting it twice would be noise.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    graph = Graph()
    try:
        graph.parse(data=text, format="turtle")
    except Exception:
        return None

    namespace = ""
    for subject in graph.subjects(RDF.type, OWL.Ontology):
        namespace = str(subject).rstrip("#/") + "#"
        break
    if not namespace:
        return None

    def _locals(rdf_type: URIRef) -> dict[str, str]:
        found: dict[str, str] = {}
        for subject in graph.subjects(RDF.type, rdf_type):
            uri = str(subject)
            if uri.startswith(namespace):
                found[_local_name(uri)] = uri
        return found

    classes = _locals(OWL.Class)
    object_properties = _locals(OWL.ObjectProperty)
    datatype_properties = _locals(OWL.DatatypeProperty)

    imports = tuple(sorted({str(obj).rstrip("#/") for obj in graph.objects(None, OWL.imports)}))

    def _resolves(target: URIRef) -> bool:
        """True when *target* is a term a reference module actually declares.

        An anchor is a claim that this class specialises a real reference term. Before
        this check the claim was taken on faith -- any non-local parent counted -- so a
        typo'd parent (right namespace, wrong local name) registered as *anchored* and
        silenced check_unanchored_classes and both arms of
        check_reference_model_shadowing, while inflating the anchoring score. A
        misspelled reference was treated better than a correctly spelled dangling one.

        With no ``module_terms`` (no catalog resolved -- ``compile`` passes none) this
        falls back to the old namespace-only test rather than declaring every anchor
        broken.
        """
        if not module_terms:
            return True
        known = module_terms.get(_namespace_of(str(target)).rstrip("#/"))
        if known is None:
            return True  # unmanaged module: missing_managed_import's business, not ours
        name = _local_name(str(target))
        return name in known["classes"] or name in known["properties"]

    anchored_classes = {
        _local_name(str(subject))
        for subject in graph.subjects(RDF.type, OWL.Class)
        if str(subject).startswith(namespace)
        and any(
            not str(parent).startswith(namespace) and _resolves(parent)
            for predicate in (RDFS.subClassOf, OWL.equivalentClass)
            for parent in graph.objects(subject, predicate)
            if isinstance(parent, URIRef)
        )
    }
    anchored_properties = {
        _local_name(str(subject))
        for subject in graph.subjects(RDFS.subPropertyOf, None)
        if str(subject).startswith(namespace)
        and any(
            not str(parent).startswith(namespace) and _resolves(parent)
            for parent in graph.objects(subject, RDFS.subPropertyOf)
            if isinstance(parent, URIRef)
        )
    }

    # An owl:imports triple names the module in its object position, so counting every
    # external URIRef would score every declared import as "used" by the very statement
    # that declares it. Skip those triples, and skip the W3C vocabularies, so what is
    # left is the file genuinely reaching into a reference model.
    _VOCAB_PREFIXES = (
        str(OWL),
        str(RDFS),
        str(RDF),
        "http://www.w3.org/2001/XMLSchema#",
        "http://www.w3.org/2004/02/skos/core#",
    )
    referenced_external = {
        _namespace_of(str(node)).rstrip("#/")
        for subject, predicate, obj in graph
        if predicate != OWL.imports
        for node in (subject, predicate, obj)
        if isinstance(node, URIRef)
        and not str(node).startswith(namespace)
        and str(node).startswith("http")
        and not str(node).startswith(_VOCAB_PREFIXES)
    }

    # Full URIs of external terms this file names in a structural position, as
    # ``(subject_local_name, predicate_local_name, target_uri)``. ``referenced_external``
    # keeps namespaces only, which answers "is the module imported" but not "does the
    # named term exist in it" — and a typo'd local name in a correctly imported module
    # is invisible to every other check here.
    external_term_refs: set[tuple[str, str, str]] = set()
    for predicate in (RDFS.subClassOf, RDFS.subPropertyOf, OWL.equivalentClass, RDFS.domain, RDFS.range):
        for subject, target in graph.subject_objects(predicate):
            if not isinstance(subject, URIRef) or not isinstance(target, URIRef):
                continue
            if not str(subject).startswith(namespace):
                continue
            if str(target).startswith(namespace) or str(target).startswith(_VOCAB_PREFIXES):
                continue
            external_term_refs.add(
                (_local_name(str(subject)), _local_name(str(predicate)), str(target))
            )

    property_domains: dict[str, tuple[str, ...]] = {}
    for local, uri in {**object_properties, **datatype_properties}.items():
        targets = tuple(
            sorted(
                _local_name(str(obj))
                for obj in graph.objects(URIRef(uri), RDFS.domain)
                if isinstance(obj, URIRef)
            )
        )
        property_domains[local] = targets

    return DomainOntology(
        domain=domain,
        path=path,
        namespace=namespace,
        classes=classes,
        object_properties=object_properties,
        datatype_properties=datatype_properties,
        imports=imports,
        header_exclusions=extract_header_exclusions(text),
        anchored_classes=frozenset(anchored_classes),
        anchored_properties=frozenset(anchored_properties),
        referenced_external=frozenset(referenced_external),
        external_term_refs=frozenset(external_term_refs),
        property_domains=property_domains,
    )


def scan_hub_ontologies(
    ontologies_dir: Path,
    module_terms: Optional[dict[str, dict[str, set[str]]]] = None,
) -> dict[str, DomainOntology]:
    """Parse every authored domain ``.ttl`` in *ontologies_dir*.

    Files beginning with ``_`` (``_master.ttl``, ``_foundation.ttl``) are
    toolkit-managed import bootstraps, not authored domains, and are skipped.
    """
    scanned: dict[str, DomainOntology] = {}
    if not ontologies_dir.is_dir():
        return scanned
    for path in sorted(ontologies_dir.glob("*.ttl")):
        if path.name.startswith("_"):
            continue
        parsed = scan_domain_ontology(path, path.stem, module_terms)
        if parsed is not None:
            scanned[path.stem] = parsed
    return scanned


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_cross_domain_duplicates(
    ontologies: dict[str, DomainOntology],
) -> list[IntegrityDiagnostic]:
    """Flag a class local name declared as ``owl:Class`` in more than one domain.

    Each domain has its own namespace, so these are unrelated OWL entities that merely
    share a name — no ``owl:equivalentClass``, no ``owl:sameAs``. Downstream this is not
    a style problem: the dbt projector derives a model file name from the class local
    name, so two domains declaring ``Company`` emit ``company.sql`` twice and dbt fails
    to parse the project.
    """
    owners: dict[str, list[str]] = {}
    for domain, onto in ontologies.items():
        for name in onto.classes:
            owners.setdefault(name, []).append(domain)

    diagnostics: list[IntegrityDiagnostic] = []
    for name, domains in sorted(owners.items()):
        if len(domains) < 2:
            continue
        others = sorted(domains)
        for domain in others:
            elsewhere = [d for d in others if d != domain]
            diagnostics.append(
                IntegrityDiagnostic(
                    level="error",
                    code="integrity.class-redeclared-across-domains",
                    message=(
                        f"Class '{name}' is declared locally in {len(others)} domains "
                        f"({', '.join(others)}). These are unrelated OWL entities sharing "
                        "a name, and the dbt projector will emit colliding model files."
                    ),
                    domain=domain,
                    term_uri=ontologies[domain].classes[name],
                    remediation=(
                        f"Declare '{name}' once in the domain that owns it and reference it "
                        f"from {', '.join(elsewhere)} via a declared cross-domain relationship "
                        "(externalReference, DD-133 §7) instead of re-minting it. Run "
                        f"'kairos-ontology domain-coverage --owns {name}' to confirm the owner."
                    ),
                )
            )
    return diagnostics


def check_declared_exclusions(
    ontologies: dict[str, DomainOntology],
) -> list[IntegrityDiagnostic]:
    """Flag a class the file's own ``Deliberate exclusions`` header places elsewhere.

    This is the cheapest possible check and the most defensible: the file states, in
    prose the author wrote, that a concept belongs to another domain, and then declares
    it anyway. No blueprint or reference model needs to resolve for it to fire.
    """
    diagnostics: list[IntegrityDiagnostic] = []
    for domain, onto in sorted(ontologies.items()):
        if not onto.header_exclusions:
            continue
        excluded = parse_excluded_subjects(onto.header_exclusions, domain=domain)
        if not excluded:
            continue
        for name, uri in sorted(onto.classes.items()):
            for subject, owner in excluded:
                # The domain's own name routinely appears in a subject phrase ("Party
                # bookings" in the party domain). Dropping it keeps the bullet pointed
                # at the concept it excludes rather than at the domain writing it down.
                scoped = " ".join(
                    token
                    for token in re.findall(r"[A-Za-z]+", subject)
                    if _singular(token.lower()) != _singular(domain.lower())
                )
                if not class_named_in_prose(name, scoped):
                    continue
                diagnostics.append(
                    IntegrityDiagnostic(
                        level="error",
                        code="integrity.class-violates-declared-exclusion",
                        message=(
                            f"Class '{name}' is declared in domain '{domain}', but this file's "
                            f"own 'Deliberate exclusions' header says \"{subject}\" is owned by "
                            f"the '{owner}' domain."
                        ),
                        domain=domain,
                        term_uri=uri,
                        remediation=(
                            f"Remove '{name}' here and reference the '{owner}' domain's class "
                            "via a declared cross-domain relationship, or correct the header if "
                            "the exclusion is no longer the intent. Do not leave the file "
                            "contradicting itself."
                        ),
                    )
                )
                break
    return diagnostics


def check_blueprint_boundaries(
    ontologies: dict[str, DomainOntology],
    data_domains: dict[str, dict[str, Any]],
) -> list[IntegrityDiagnostic]:
    """Flag a class the accelerator blueprint's ``does_not_own`` prose excludes.

    ``does_not_own`` is a contract field the toolkit already feeds to the source-affinity
    classifier, so its wording is behavioural, not decorative. Reading it here is the
    same text used for the same purpose one stage earlier.
    """
    diagnostics: list[IntegrityDiagnostic] = []
    for domain, onto in sorted(ontologies.items()):
        meta = data_domains.get(domain)
        if not isinstance(meta, dict):
            continue
        excluded = str(meta.get("does_not_own") or "")
        if not excluded.strip():
            continue
        for name, uri in sorted(onto.classes.items()):
            if class_named_in_prose(name, excluded):
                diagnostics.append(
                    IntegrityDiagnostic(
                        level="error",
                        code="integrity.class-outside-blueprint-boundary",
                        message=(
                            f"Class '{name}' is declared in domain '{domain}', whose blueprint "
                            f'DOES NOT OWN boundary reads: "{excluded.strip()}"'
                        ),
                        domain=domain,
                        term_uri=uri,
                        remediation=(
                            f"Model '{name}' in the domain that owns it. If this hub genuinely "
                            "needs the concept here, link it with a declared cross-domain "
                            "relationship rather than a local class. Run "
                            f"'kairos-ontology domain-coverage --explain {domain}' to see the "
                            "full boundary."
                        ),
                    )
                )
    return diagnostics


def check_reference_model_shadowing(
    ontologies: dict[str, DomainOntology],
    module_terms: dict[str, dict[str, set[str]]],
) -> list[IntegrityDiagnostic]:
    """Flag a local term duplicating, by name, a term in a module the file imports.

    *module_terms* maps a module IRI (no trailing ``#``/``/``) to
    ``{"classes": {...}, "properties": {...}}`` of local names it declares.

    A hub that imports ``bsp/party`` and then declares its own ``contactEmail`` has not
    reused the reference model — it has shadowed it, and the two terms are invisible to
    each other. Warning rather than error: an intentional narrowing is legitimate, but
    it must then carry ``rdfs:subClassOf`` / ``rdfs:subPropertyOf``, which is exactly
    what suppresses this diagnostic.
    """
    diagnostics: list[IntegrityDiagnostic] = []
    for domain, onto in sorted(ontologies.items()):
        imported_classes: dict[str, str] = {}
        imported_properties: dict[str, str] = {}
        for module in onto.imports:
            terms = module_terms.get(module)
            if not terms:
                continue
            for name in terms.get("classes", set()):
                imported_classes.setdefault(name, module)
            for name in terms.get("properties", set()):
                imported_properties.setdefault(name, module)

        for name, uri in sorted(onto.classes.items()):
            module = imported_classes.get(name)
            if module and name not in onto.anchored_classes:
                diagnostics.append(
                    IntegrityDiagnostic(
                        level="warning",
                        code="integrity.local-class-shadows-reference-model",
                        message=(
                            f"Local class '{name}' has the same name as a class in imported "
                            f"module <{module}>, with no rdfs:subClassOf or owl:equivalentClass "
                            "link to it."
                        ),
                        domain=domain,
                        term_uri=uri,
                        remediation=(
                            f"Reuse <{module}#{name}> directly, or declare the local class "
                            "rdfs:subClassOf it when the hub genuinely constrains it."
                        ),
                    )
                )

        for name, uri in sorted(onto.properties.items()):
            module = imported_properties.get(name)
            if module and name not in onto.anchored_properties:
                diagnostics.append(
                    IntegrityDiagnostic(
                        level="warning",
                        code="integrity.local-property-shadows-reference-model",
                        message=(
                            f"Local property '{name}' has the same name as a property in "
                            f"imported module <{module}>, with no rdfs:subPropertyOf link."
                        ),
                        domain=domain,
                        term_uri=uri,
                        remediation=(
                            f"Reuse <{module}#{name}>, or declare the local property "
                            "rdfs:subPropertyOf it."
                        ),
                    )
                )
    return diagnostics


def check_unused_imports(
    ontologies: dict[str, DomainOntology],
) -> list[IntegrityDiagnostic]:
    """Flag an ``owl:imports`` no term in the file references.

    Distinct from ``surplus_managed_import``, which asks whether the *blueprint*
    requires the module. This asks whether the *file* uses it. A domain can satisfy
    the blueprint's import plan perfectly and still reference nothing from any of it,
    which is what "imports declared, reference model ignored" looks like on disk.
    """
    diagnostics: list[IntegrityDiagnostic] = []
    for domain, onto in sorted(ontologies.items()):
        # A freshly scaffolded domain declares its blueprint-mandated imports before any
        # class exists, so every import is trivially "unused". Reporting that says only
        # "you have not authored this domain yet" -- 58 such warnings on a 22-domain
        # scaffold is exactly the noise that teaches people to skip the warning list.
        if not onto.classes and not onto.properties:
            continue
        for module in onto.imports:
            if module in onto.referenced_external:
                continue
            diagnostics.append(
                IntegrityDiagnostic(
                    level="warning",
                    code="integrity.managed-import-unused",
                    message=(
                        f"Domain '{domain}' imports <{module}> but references no term from it."
                    ),
                    domain=domain,
                    term_uri=module,
                    remediation=(
                        "Anchor at least one local class to the module with rdfs:subClassOf, "
                        "reuse its terms directly, or drop the import if the blueprint does "
                        "not mandate it."
                    ),
                )
            )
    return diagnostics


def check_collapsed_value_objects(
    ontologies: dict[str, DomainOntology],
) -> list[IntegrityDiagnostic]:
    """Flag an address value object flattened into a cluster of scalar properties.

    ``companyBillingAddress`` + ``companyBillingCity`` + ``companyBillingCountry`` +
    ``companyBillingPostalCode`` is four loose strings where the blueprint ships an
    ``Address`` class and an object property to reach it. Beyond the modelling loss,
    each scalar has to be annotated for PII separately, which is how a hub ends up with
    eight unresolved GDPR warnings instead of one annotated link.
    """
    diagnostics: list[IntegrityDiagnostic] = []
    for domain, onto in sorted(ontologies.items()):
        clusters: dict[str, list[str]] = {}
        for name in onto.datatype_properties:
            parts = _split_camel(name)
            if len(parts) < 2:
                continue
            suffix = parts[-1]
            if suffix not in _ADDRESS_SUFFIXES:
                continue
            prefix = "".join(parts[:-1])
            clusters.setdefault(prefix, []).append(name)
        # postalCode / stateProvince split into two camel parts; fold them back in.
        for name in onto.datatype_properties:
            parts = _split_camel(name)
            if len(parts) < 3:
                continue
            tail = parts[-2] + parts[-1]
            if tail in _ADDRESS_SUFFIXES:
                prefix = "".join(parts[:-2])
                if prefix in clusters and name not in clusters[prefix]:
                    clusters[prefix].append(name)

        for prefix, names in sorted(clusters.items()):
            if len(set(names)) < _ADDRESS_CLUSTER_MIN:
                continue
            diagnostics.append(
                IntegrityDiagnostic(
                    level="warning",
                    code="integrity.value-object-collapsed",
                    message=(
                        f"Domain '{domain}' flattens an address into {len(set(names))} scalar "
                        f"properties ({', '.join(sorted(set(names)))}) instead of an object "
                        "property to a shared Address class."
                    ),
                    domain=domain,
                    term_uri=onto.datatype_properties[sorted(names)[0]],
                    remediation=(
                        "Model the address as a value object and link it with one object "
                        "property. One link also carries one PII annotation instead of one "
                        "per scalar."
                    ),
                )
            )
    return diagnostics


def check_external_terms_resolve(
    ontologies: dict[str, DomainOntology],
    module_terms: dict[str, dict[str, set[str]]],
) -> list[IntegrityDiagnostic]:
    """Flag a reference term this file names that does not exist in the imported module.

    Distinct from ``missing_managed_import``, which asks whether the *module* is
    imported. This asks whether the *term* is real. A typo in the local name satisfies
    the import check completely — the namespace is imported, so nothing objects — and
    then nothing else notices:

        rdfs:subClassOf <https://www.kairosflow.ai/ont/mmt/cargo#CargoIteem>

    Worse than merely unreported. ``scan_domain_ontology`` counts a class as *anchored*
    on the strength of having any non-local parent, without resolving it, so a typo'd
    parent actively buys silence from :func:`check_unanchored_classes` and both arms of
    :func:`check_reference_model_shadowing`, and inflates the anchoring score. That
    silencing is left in place here and tracked separately: fixing it changes the
    behaviour of three existing checks and deserves its own change.

    Reports nothing when *module_terms* is empty — no catalog resolved means no basis to
    judge, which is the same stance :func:`check_reference_model_shadowing` takes.
    """
    diagnostics: list[IntegrityDiagnostic] = []
    if not module_terms:
        return diagnostics
    for domain, onto in sorted(ontologies.items()):
        for subject, predicate, target in sorted(onto.external_term_refs):
            module = _namespace_of(target).rstrip("#/")
            known = module_terms.get(module)
            if known is None:
                # Module is not one the catalog resolved. Either it is not managed at
                # all, or it is not imported -- and the second is missing_managed_import's
                # job. Saying nothing here avoids two errors for one mistake.
                continue
            name = _local_name(target)
            if name in known["classes"] or name in known["properties"]:
                continue
            diagnostics.append(
                IntegrityDiagnostic(
                    level="error",
                    code="integrity.external-term-unresolved",
                    message=(
                        f"'{subject}' declares {predicate} <{target}>, but module "
                        f"<{module}> declares no term named '{name}'. The reference is "
                        "dangling: the module is imported, so the import check passes, "
                        "and the term does not exist."
                    ),
                    domain=domain,
                    term_uri=target,
                    remediation=(
                        f"Correct the local name, or point {predicate} at a term "
                        f"<{module}> actually declares. Check for a typo first — the "
                        "namespace resolving is what makes this easy to miss."
                    ),
                )
            )
    return diagnostics


def check_unanchored_classes(
    ontologies: dict[str, DomainOntology],
) -> list[IntegrityDiagnostic]:
    """Report a domain whose local classes never reach any reference model.

    Reported per domain rather than per class: a domain with fourteen unanchored
    classes has one problem, not fourteen, and fourteen diagnostics would bury the
    blocking findings.
    """
    diagnostics: list[IntegrityDiagnostic] = []
    for domain, onto in sorted(ontologies.items()):
        if not onto.classes:
            continue
        unanchored = sorted(set(onto.classes) - onto.anchored_classes)
        if len(unanchored) != len(onto.classes):
            continue
        if not onto.imports:
            continue
        diagnostics.append(
            IntegrityDiagnostic(
                level="warning",
                code="integrity.class-unanchored",
                message=(
                    f"Domain '{domain}' declares {len(unanchored)} local class(es) and imports "
                    f"{len(onto.imports)} reference module(s), but no class is anchored to any "
                    "of them by rdfs:subClassOf or owl:equivalentClass."
                ),
                domain=domain,
                term_uri=None,
                remediation=(
                    "Anchor each local class to the reference-model class it specialises, or "
                    "reuse the reference-model class directly instead of declaring a local one."
                ),
            )
        )
    return diagnostics


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _module_terms(catalog_path: Optional[Path]) -> dict[str, dict[str, set[str]]]:
    """Read materialized reference inventories into ``{module_iri: {classes, properties}}``.

    Returns ``{}`` when inventories are absent — the shadowing check then silently
    reports nothing rather than guessing.
    """
    from .class_anchoring import read_reference_terms

    terms: dict[str, dict[str, set[str]]] = {}
    for term in read_reference_terms(catalog_path):
        module = term.module.rstrip("#/")
        bucket = "classes" if term.kind == "class" else "properties"
        terms.setdefault(module, {"classes": set(), "properties": set()})
        terms[module][bucket].add(term.name)
    return terms


def audit_ontology_integrity(
    *,
    ontologies_dir: Path,
    data_domains: Optional[dict[str, dict[str, Any]]] = None,
    catalog_path: Optional[Path] = None,
    domains: Optional[Iterable[str]] = None,
) -> IntegrityReport:
    """Run every hub-wide integrity check and return a scored report.

    *domains* scopes which domains are **reported**; cross-domain duplicate detection
    always scans the whole hub, because a duplicate is by definition invisible from
    inside one domain.
    """
    # Resolved BEFORE the scan: scan_domain_ontology needs it to tell a real anchor from
    # a typo'd one. Without it an unresolvable parent counts as an anchor and silences
    # check_unanchored_classes and both arms of check_reference_model_shadowing.
    module_terms = _module_terms(catalog_path)
    ontologies = scan_hub_ontologies(ontologies_dir, module_terms)
    report = IntegrityReport(domains_scanned=len(ontologies))
    if not ontologies:
        report.notices.append(
            f"No authored domain ontologies found under {ontologies_dir}; nothing to audit."
        )
        return report

    if not module_terms:
        report.notices.append(
            "No reference models resolved from the hub catalog; reference-model "
            "shadowing checks were skipped."
        )
    if not data_domains:
        report.notices.append(
            "No accelerator blueprint resolved; blueprint boundary checks were skipped."
        )

    diagnostics: list[IntegrityDiagnostic] = []
    diagnostics.extend(check_cross_domain_duplicates(ontologies))
    diagnostics.extend(check_declared_exclusions(ontologies))
    diagnostics.extend(check_blueprint_boundaries(ontologies, data_domains or {}))
    diagnostics.extend(check_reference_model_shadowing(ontologies, module_terms))
    diagnostics.extend(check_unused_imports(ontologies))
    diagnostics.extend(check_collapsed_value_objects(ontologies))
    diagnostics.extend(check_unanchored_classes(ontologies))
    diagnostics.extend(check_external_terms_resolve(ontologies, module_terms))

    if domains is not None:
        scope = set(domains)
        diagnostics = [d for d in diagnostics if d.domain in scope]

    # De-duplicate: a class can violate both its own header and the blueprint boundary.
    # Report the most specific finding once per (code, domain, term).
    seen: set[tuple[str, str, Optional[str]]] = set()
    deduped: list[IntegrityDiagnostic] = []
    for diagnostic in diagnostics:
        key = (diagnostic.code, diagnostic.domain, diagnostic.term_uri)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(diagnostic)

    report.diagnostics = sorted(
        deduped, key=lambda d: (d.level != "error", d.code, d.domain, d.term_uri or "")
    )

    report.total_classes = sum(len(o.classes) for o in ontologies.values())
    report.total_properties = sum(len(o.properties) for o in ontologies.values())
    report.anchored_classes = sum(len(o.anchored_classes) for o in ontologies.values())
    report.anchored_properties = sum(len(o.anchored_properties) for o in ontologies.values())
    report.imports_declared = sum(len(o.imports) for o in ontologies.values())
    report.imports_used = sum(
        len([m for m in o.imports if m in o.referenced_external]) for o in ontologies.values()
    )

    names: dict[str, int] = {}
    for onto in ontologies.values():
        for name in onto.classes:
            names[name] = names.get(name, 0) + 1
    report.duplicate_class_declarations = sum(count - 1 for count in names.values() if count > 1)

    return report
