# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Ontology validation module - syntax, SHACL, consistency, GDPR PII scanning."""

import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD
from pyshacl import validate as shacl_validate
import json

# Canonical PII keyword list lives in ._samples (single source of truth, also
# used by the sample-exposure masking policy); re-exported for compatibility.
from ._samples import PII_KEYWORDS, _normalize
from .hub_utils import is_domain_ontology_stem
from .reference_modules import (
    ModuleDiagnostic,
    ReferenceModuleContext,
    build_managed_import_plan,
    build_reference_module_context,
)
# Lightweight, best-effort binding/source-relation readers (issue #325). These are the
# same tolerant helpers `resolve_scope()` uses to build a compile scope (kernel.py
# ~line 564-650) and that hub_inspection.py/design_landscape.py already reach into at
# module scope for advisory reporting — reused here rather than re-parsing binding YAML
# or source vocabulary TTL a second, subtly different way.
from .compiler.kernel import (
    _binding_domain,
    _binding_source_ref,
    _binding_target_class,
    _source_relations,
)

logger = logging.getLogger(__name__)

KAIROS_EXT = Namespace("https://kairos.cnext.eu/ext#")

# Issue #325: a property whose local name ends in a bare "Code" segment is, by
# convention, a reference/lookup identifier for the matched concept -- NOT the concept's
# actual content -- but only for concepts that cannot themselves be compressed into a
# short code. "address" is the only keyword in this set today: a postal address is
# inherently multi-component free text, so "<X>AddressCode" can only be a lookup key into
# an address record, never an address itself (this is what produced the real false
# positive on `Address.addressCode`, issue #325).
#
# This is deliberately NOT extended to the identifier-shaped keywords (national_id, iban,
# ssn, passport, tax_id) or to the categorical ones (gender, nationality, marital_status,
# ethnicity, religion) -- core/_samples.py's own `_IDENTIFIER_TOKENS`/
# `_kind_from_person_column_tokens` already treats a "Code"/"Id"/"Number" suffix on a
# person-context column as identifier-shaped PII, not an exemption, and a
# `nationalIdCode`/`genderCode`/`maritalStatusCode` is routinely the coded value ITSELF
# (e.g. "M"/"F", an ISO nationality code) -- suppressing those would reopen the exact
# false-negative class this fix exists to close. Extend this set only with the same kind
# of concrete, evidenced false positive that motivated "address".
_CODE_SUFFIX_EXEMPT_KEYWORDS: frozenset[str] = frozenset({"address"})


# Thin alias kept for existing call sites below. The actual predicate lives in
# hub_utils.is_domain_ontology_stem — a leaf module shared with core/projector.py,
# core/hub_inspection.py, and core/catalog_test.py — so the four copies cannot drift
# apart again (issue #289).
def _is_domain_ontology(path: Path) -> bool:
    """Return True if *path* looks like a domain ontology file.

    Excludes annotation/configuration files such as ``*-silver-ext.ttl``
    and metadata files whose name starts with ``_`` (e.g. ``_master.ttl``).
    """
    return is_domain_ontology_stem(path.stem)


def validate_content(
    ontology_content: str,
    shapes_content: Optional[str] = None,
    do_syntax: bool = True,
    do_shacl: bool = True,
) -> dict:
    """Validate ontology content (TTL string) programmatically.

    Args:
        ontology_content: Turtle-formatted ontology string.
        shapes_content: Optional SHACL shapes as a Turtle string.
        do_syntax: Run syntax validation.
        do_shacl: Run SHACL validation (requires shapes_content).

    Returns:
        Dict with ``syntax`` and ``shacl`` keys, each containing
        ``passed`` (bool), and ``errors`` (list of str).
    """
    result: dict = {
        "syntax": {"passed": True, "errors": []},
        "shacl": {"passed": True, "errors": []},
    }

    # Syntax
    graph = None
    if do_syntax:
        try:
            graph = Graph()
            graph.parse(data=ontology_content, format="turtle")
        except Exception as e:
            result["syntax"]["passed"] = False
            result["syntax"]["errors"].append(str(e))
            return result  # can't continue without a valid graph

    # SHACL
    if do_shacl and shapes_content:
        if graph is None:
            graph = Graph()
            graph.parse(data=ontology_content, format="turtle")
        shapes_graph = Graph()
        shapes_graph.parse(data=shapes_content, format="turtle")
        conforms, _, report_text = shacl_validate(
            graph,
            shacl_graph=shapes_graph,
            inference="rdfs",
            abort_on_first=False,
        )
        if not conforms:
            result["shacl"]["passed"] = False
            result["shacl"]["errors"].append(report_text)

    return result


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case for PII matching."""
    import re

    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _property_range_is_boolean(graph: Graph, prop: URIRef) -> bool:
    """True when *prop* declares ``rdfs:range xsd:boolean``.

    ``rdfs:range`` is author-declared ontology metadata, not inferred from mutable
    sample data (unlike the ``column_types`` gating that issue #302's fix rejected for
    the sample redactor -- see `_CODE_SUFFIX_EXEMPT_KEYWORDS` above and the CHANGELOG for
    the full comparison). A boolean is the one datatype that structurally cannot hold any
    of ``PII_KEYWORDS``'s free-text/identifier concepts, so this gate is scoped to exactly
    that type and nothing else -- numeric and temporal properties are deliberately left
    alone, so a ``dateOfBirth: xsd:dateTime`` or a hypothetical ``age: xsd:decimal`` still
    gets flagged, per the #302 caveat.
    """
    return any(r == XSD.boolean for r in graph.objects(prop, RDFS.range))


def _is_governed_code_property_name(snake_local: str) -> bool:
    """True when the local name's last snake-case segment is a bare ``code``."""
    tokens = snake_local.split("_")
    return len(tokens) > 1 and tokens[-1] == "code"


def _binding_source_evidence(
    hub_root: Path, domain_name: str
) -> dict[str, list[tuple[str, str, str]]]:
    """Best-effort: map each ``domain_name``-scoped bound class to PII-keyword hits found
    in its EntityBinding's *source* columns (not its canonical property names).

    Returns ``{class_local_name: [(source_relation, column_name, keyword), ...]}``.

    A class bound to a source relation whose physical columns carry a PII keyword is a
    strong positive signal regardless of what the canonical (mapped) property was named --
    this is what issue #325 calls out as the missed false-negative case (a class sourced
    from person data whose canonical properties were renamed to something that no longer
    contains a keyword substring).

    Advisory and deliberately best-effort, mirroring how ``hub_inspection.py`` /
    ``design_landscape.py`` already read bindings for advisory reporting: a hub with no
    ``integration/bindings`` or ``integration/sources``, or a binding/source file that
    fails to parse, yields no evidence rather than raising -- the GDPR scan must never
    crash `validate` on a partially-authored hub.

    Bindings are scoped to *domain_name* via ``metadata.domain`` (``None``/absent counts
    as unscoped, matching ``resolve_scope()``'s own filter in ``compiler/kernel.py`` --
    NOT by comparing the binding's ``target.class`` prefix against the domain name, since
    a class's usable prefix can legitimately differ from the ontology file stem (prefix
    aliasing across an import closure)).
    """
    evidence: dict[str, list[tuple[str, str, str]]] = {}

    bindings_dir = hub_root / "integration" / "bindings"
    if not bindings_dir.is_dir():
        return evidence

    binding_paths = sorted(bindings_dir.glob("*.binding.yaml"))
    if not binding_paths:
        return evidence

    sources_dir = hub_root / "integration" / "sources"
    source_paths = tuple(sorted(sources_dir.glob("**/*.ttl"))) if sources_dir.is_dir() else ()
    if not source_paths:
        return evidence

    try:
        relations = _source_relations(source_paths)
    except Exception:
        logger.debug(
            "GDPR scan: could not resolve source relations under %s", sources_dir, exc_info=True
        )
        return evidence
    relations_by_ref = {relation.ref: relation for relation in relations}

    for binding_path in binding_paths:
        try:
            text = binding_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if _binding_domain(text) not in (None, domain_name):
            continue
        target_class = _binding_target_class(text)
        if not target_class:
            continue
        cls_local = target_class.rsplit(":", 1)[-1]
        relation = relations_by_ref.get(_binding_source_ref(text))
        if relation is None:
            continue

        hits = evidence.setdefault(cls_local, [])
        seen_keywords = {kw for _rel, _col, kw in hits}
        for column in relation.columns:
            normalized = _normalize(column.name)
            for kw in PII_KEYWORDS:
                if kw in normalized:
                    if kw not in seen_keywords:
                        hits.append((relation.ref, column.name, kw))
                        seen_keywords.add(kw)
                    break

    return evidence


def validate_gdpr(
    ontology_content: str,
    extension_content: Optional[str] = None,
    *,
    source_evidence: Optional[dict[str, list[tuple[str, str, str]]]] = None,
) -> dict:
    """Scan an ontology for PII-like properties that lack GDPR satellite protection.

    For each ``owl:DatatypeProperty``, checks whether the property local name or
    ``rdfs:label`` contains any PII keyword.  Then verifies whether the property's
    ``rdfs:domain`` class (or a parent class) is protected by
    ``kairos-ext:gdprSatelliteOf``.

    A name-keyword match is suppressed (issue #325) when:
      * the property's declared ``rdfs:range`` is ``xsd:boolean`` -- no PII keyword
        describes a plausible boolean fact; or
      * the matched keyword is in ``_CODE_SUFFIX_EXEMPT_KEYWORDS`` (today, just
        ``"address"``) and the property's local name ends in a bare ``Code`` segment --
        a governed reference/lookup code, not the concept's content.

    Independently of name-based matching, *source_evidence* (see
    `_binding_source_evidence`) adds warnings for classes whose EntityBinding source
    columns carry a PII keyword, even when the canonical property name does not -- still
    subject to the same ``gdprSatelliteOf`` protection check as name-based hits.

    Args:
        ontology_content: Turtle-formatted domain ontology.
        extension_content: Optional silver-ext TTL with ``kairos-ext:`` annotations.
        source_evidence: Optional ``{class_local_name: [(relation, column, keyword)]}``
            binding-sourced evidence for this domain (see `_binding_source_evidence`).

    Returns:
        Dict with ``passed`` (bool — True if no unprotected PII found),
        ``warnings`` (list of dicts with class, property, keyword), and
        ``protected_classes`` (list of class URIs that have gdprSatelliteOf).
    """
    graph = Graph()
    graph.parse(data=ontology_content, format="turtle")

    if extension_content:
        graph.parse(data=extension_content, format="turtle")

    # Collect classes protected by gdprSatelliteOf (the satellite class itself)
    protected_classes: set[str] = set()
    for subj in graph.subjects(KAIROS_EXT.gdprSatelliteOf, None):
        protected_classes.add(str(subj))

    # Also collect the parent classes that HAVE a GDPR satellite
    # (i.e. the parent is indirectly protected — its PII is in the satellite)
    parents_with_satellite: set[str] = set()
    for subj, obj in graph.subject_objects(KAIROS_EXT.gdprSatelliteOf):
        parents_with_satellite.add(str(obj))

    warnings: list[dict] = []

    for prop in graph.subjects(RDF.type, OWL.DatatypeProperty):
        prop_uri = str(prop)
        local = prop_uri.rsplit("#", 1)[-1] if "#" in prop_uri else prop_uri.rsplit("/", 1)[-1]
        snake_local = _camel_to_snake(local)

        # Check label too
        label = str(graph.value(prop, RDFS.label) or "")
        label_lower = label.lower().replace(" ", "_")

        # Find matching PII keyword
        matched_keyword = None
        for kw in PII_KEYWORDS:
            if kw in snake_local or kw in label_lower:
                matched_keyword = kw
                break

        if not matched_keyword:
            continue

        # Datatype/name-shape gates (issue #325) -- see docstring above.
        if _property_range_is_boolean(graph, prop):
            continue
        if matched_keyword in _CODE_SUFFIX_EXEMPT_KEYWORDS and _is_governed_code_property_name(
            snake_local
        ):
            continue

        # Find domain class(es) for this property
        for domain_cls in graph.objects(prop, RDFS.domain):
            cls_uri = str(domain_cls)
            # Skip if this class IS a GDPR satellite (it's already protected)
            if cls_uri in protected_classes:
                continue
            # Skip if this class HAS a GDPR satellite (PII should be there)
            if cls_uri in parents_with_satellite:
                continue
            # Unprotected PII
            cls_local = cls_uri.rsplit("#", 1)[-1] if "#" in cls_uri else cls_uri.rsplit("/", 1)[-1]
            warnings.append(
                {
                    "class": cls_local,
                    "class_uri": cls_uri,
                    "property": local,
                    "property_uri": prop_uri,
                    "keyword": matched_keyword,
                }
            )

    if source_evidence:
        flagged_classes = {w["class"] for w in warnings}
        class_uri_by_local: dict[str, str] = {}
        for cls in graph.subjects(RDF.type, OWL.Class):
            cls_uri = str(cls)
            cls_local = cls_uri.rsplit("#", 1)[-1] if "#" in cls_uri else cls_uri.rsplit("/", 1)[-1]
            class_uri_by_local.setdefault(cls_local, cls_uri)

        for cls_local, hits in source_evidence.items():
            cls_uri = class_uri_by_local.get(cls_local)
            if cls_uri is None:
                continue  # the binding targets a class this ontology file doesn't declare
            if cls_uri in protected_classes or cls_uri in parents_with_satellite:
                continue
            if cls_local in flagged_classes:
                continue  # already unprotected via a name-based hit; avoid duplicate noise
            for relation, column, keyword in hits:
                warnings.append(
                    {
                        "class": cls_local,
                        "class_uri": cls_uri,
                        "property": column,
                        "property_uri": None,
                        "keyword": keyword,
                        "evidence": "source-binding",
                        "source": f"{relation}.{column}",
                    }
                )

    return {
        "passed": len(warnings) == 0,
        "warnings": warnings,
        "protected_classes": list(protected_classes),
    }


def run_gdpr_validation(
    ontologies_path: Path,
    catalog_path: Optional[Path] = None,
    hub_root: Optional[Path] = None,
) -> int:
    """Run GDPR PII scan across all domain ontologies.

    Prints warnings for classes with PII-like properties that lack
    ``kairos-ext:gdprSatelliteOf`` annotations, including classes whose EntityBinding
    source columns carry PII evidence the canonical property name does not (issue #325).

    Args:
        ontologies_path: Directory to scan for domain ontology files.
        catalog_path: Unused by this scan (accepted for call-site symmetry with the
            other ``run_*_validation`` entry points).
        hub_root: Root of the ontology hub, used to resolve ``integration/bindings`` and
            ``integration/sources`` for binding-sourced evidence. Defaults to
            ``ontologies_path.parent.parent`` (the ``<hub>/model/ontologies`` convention)
            when omitted; callers with a non-default ``--ontologies`` layout should pass
            the real hub root explicitly (the CLI always does).
    """
    print("\U0001f512 Kairos GDPR PII Scan")
    print("=" * 50)

    resolved_hub_root = hub_root if hub_root is not None else ontologies_path.parent.parent

    ontology_files = list(ontologies_path.glob("**/*.ttl"))
    ontology_files = [f for f in ontology_files if _is_domain_ontology(f)]

    # Pair each domain with its extension (if any)
    ext_map: dict[str, Path] = {}
    for f in ontologies_path.glob("**/*-silver-ext.ttl"):
        domain_name = f.stem.replace("-silver-ext", "")
        ext_map[domain_name] = f

    total_warnings = 0
    total_domains = 0

    for ontology_file in ontology_files:
        domain_name = ontology_file.stem
        ext_file = ext_map.get(domain_name)
        ext_content = ext_file.read_text(encoding="utf-8") if ext_file else None

        ontology_content = ontology_file.read_text(encoding="utf-8")
        source_evidence = _binding_source_evidence(resolved_hub_root, domain_name)
        result = validate_gdpr(ontology_content, ext_content, source_evidence=source_evidence)
        total_domains += 1

        if result["warnings"]:
            total_warnings += len(result["warnings"])
            print(f"\n  \u26a0\ufe0f  {ontology_file.name}:")
            for w in result["warnings"]:
                if w.get("evidence") == "source-binding":
                    print(
                        f"     {w['class']} \u2014 bound source column "
                        f"'{w['source']}' matches PII keyword '{w['keyword']}' "
                        "without gdprSatelliteOf (canonical property name does not)"
                    )
                else:
                    print(
                        f"     {w['class']}.{w['property']} \u2014 "
                        f"PII keyword '{w['keyword']}' without gdprSatelliteOf"
                    )

    print(f"\n  Scanned {total_domains} domains")
    if total_warnings:
        print(f"  \u26a0\ufe0f  {total_warnings} unprotected PII warning(s)")
        print("  Consider adding kairos-ext:gdprSatelliteOf annotations.")
    else:
        print("  \u2705 No unprotected PII detected")

    return total_warnings


_PASCAL_CASE_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_CAMEL_CASE_RE = re.compile(r"^[a-z][A-Za-z0-9]*$")


@dataclass(frozen=True)
class NamingDiagnostic:
    """Structured naming/annotation-convention diagnostic."""

    level: str
    code: str
    message: str
    term_uri: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _local_name(term_uri: str) -> str:
    if "#" in term_uri:
        return term_uri.rsplit("#", 1)[-1]
    return term_uri.rsplit("/", 1)[-1]


def validate_naming_conventions(ontology_content: str) -> dict:
    """Check ontology naming and annotation conventions for one domain file.

    Every rule below is already documented as authoring convention (scaffold
    ``ontologies/README.md`` and ``copilot-instructions.md``) but was previously
    enforced only by an LLM re-deriving the checks by hand each design session.
    This validates the whole file every run, matching every other check in this
    module — there is no "new vs existing" scoping.

    Checks (scoped to terms this file itself declares — safe because this
    parses only *ontology_content*, a single file, with no ``owl:imports``
    resolution, so every ``owl:Class``/``owl:DatatypeProperty``/
    ``owl:ObjectProperty`` type-assertion found here was authored here; there
    is no imported/accelerator content in this graph to accidentally flag):
      - exactly one ``owl:Ontology`` declaration, with ``rdfs:label`` and
        ``owl:versionInfo``;
      - every class has ``rdfs:label`` and ``rdfs:comment``;
      - every ``owl:DatatypeProperty``/``owl:ObjectProperty`` has
        ``rdfs:label`` and ``rdfs:domain``;
      - every ``owl:DatatypeProperty`` has ``rdfs:range`` (error). For an
        ``owl:ObjectProperty`` an absent ``rdfs:range`` is only a **warning**:
        DD-133 §7 states that a ``relationships:`` entry does not require the
        object property to declare a named ``rdfs:range``, and the compiler
        validates such a relationship on its authored ``target:``/``on:``
        endpoint alone — it is exactly the reference-model
        ``deferred-relationship`` shape. Erroring here would block, in
        ``validate``, a shape ``compile`` declares supported.
      - an ``owl:ObjectProperty`` whose ``rdfs:range`` *is* ``owl:Thing``
        (warning): that is strictly worse than omitting the range, because the
        compiler's relationship guard rejects a declared range that differs from
        the authored ``target:`` class while an omitted one compiles.
      - class names are PascalCase; property names are camelCase;
      - no term is declared as more than one of
        {Class, DatatypeProperty, ObjectProperty}.

    Not checked here (requires judgment, stays in the design skill's prose):
    whether a class is an accidental reference-model specialization, and
    whether source types can feasibly populate a proposed property's range.

    Returns dict: {"passed": bool, "errors": list[dict], "warnings": list[dict]}
    (errors/warnings are ``NamingDiagnostic.to_dict()`` entries).
    """
    graph = Graph()
    graph.parse(data=ontology_content, format="turtle")

    errors: list[NamingDiagnostic] = []
    warnings: list[NamingDiagnostic] = []

    ontology_subjects = [s for s in graph.subjects(RDF.type, OWL.Ontology) if isinstance(s, URIRef)]
    if not ontology_subjects:
        errors.append(
            NamingDiagnostic(
                level="error",
                code="missing_ontology_declaration",
                message="No owl:Ontology declaration found in this file.",
            )
        )
    else:
        if len(ontology_subjects) > 1:
            for extra in ontology_subjects[1:]:
                errors.append(
                    NamingDiagnostic(
                        level="error",
                        code="multiple_ontology_declarations",
                        message=f"Multiple owl:Ontology declarations found: {extra}",
                        term_uri=str(extra),
                    )
                )
        primary = ontology_subjects[0]
        if graph.value(primary, RDFS.label) is None:
            errors.append(
                NamingDiagnostic(
                    level="error",
                    code="ontology_missing_label",
                    message=f"owl:Ontology {primary} is missing rdfs:label.",
                    term_uri=str(primary),
                )
            )
        if graph.value(primary, OWL.versionInfo) is None:
            errors.append(
                NamingDiagnostic(
                    level="error",
                    code="ontology_missing_version_info",
                    message=f"owl:Ontology {primary} is missing owl:versionInfo.",
                    term_uri=str(primary),
                )
            )

    class_uris = {str(s) for s in graph.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)}
    datatype_property_uris = {
        str(s) for s in graph.subjects(RDF.type, OWL.DatatypeProperty) if isinstance(s, URIRef)
    }
    object_property_uris = {
        str(s) for s in graph.subjects(RDF.type, OWL.ObjectProperty) if isinstance(s, URIRef)
    }
    property_uris = datatype_property_uris | object_property_uris

    for term_uri in sorted(class_uris & property_uris):
        errors.append(
            NamingDiagnostic(
                level="error",
                code="term_declared_as_multiple_types",
                message=f"{term_uri} is declared as both a class and a property.",
                term_uri=term_uri,
            )
        )

    for class_uri in sorted(class_uris):
        subject = URIRef(class_uri)
        if graph.value(subject, RDFS.label) is None:
            errors.append(
                NamingDiagnostic(
                    level="error",
                    code="class_missing_label",
                    message=f"Class {class_uri} is missing rdfs:label.",
                    term_uri=class_uri,
                )
            )
        if graph.value(subject, RDFS.comment) is None:
            errors.append(
                NamingDiagnostic(
                    level="error",
                    code="class_missing_comment",
                    message=f"Class {class_uri} is missing rdfs:comment.",
                    term_uri=class_uri,
                )
            )
        if not _PASCAL_CASE_RE.match(_local_name(class_uri)):
            errors.append(
                NamingDiagnostic(
                    level="error",
                    code="class_name_not_pascal_case",
                    message=f"Class {class_uri} is not PascalCase.",
                    term_uri=class_uri,
                )
            )

    for property_uri in sorted(property_uris):
        subject = URIRef(property_uri)
        if graph.value(subject, RDFS.label) is None:
            errors.append(
                NamingDiagnostic(
                    level="error",
                    code="property_missing_label",
                    message=f"Property {property_uri} is missing rdfs:label.",
                    term_uri=property_uri,
                )
            )
        if graph.value(subject, RDFS.domain) is None:
            errors.append(
                NamingDiagnostic(
                    level="error",
                    code="property_missing_domain",
                    message=f"Property {property_uri} is missing rdfs:domain.",
                    term_uri=property_uri,
                )
            )
        # An object property that is *also* declared a datatype property is not a
        # trustworthy "object property" — keep the strict datatype rules for it.
        is_object_property = (
            property_uri in object_property_uris and property_uri not in datatype_property_uris
        )
        declared_range = graph.value(subject, RDFS.range)
        if declared_range is None:
            if is_object_property:
                # DD-133 §7: "A relationships: entry does not require the object property
                # to declare a named rdfs:range." An absent range leaves the range
                # unconstrained and the relationship is validated on its authored
                # target:/on: endpoint alone — the reference-model deferred-relationship
                # shape. compile supports it, so validate must not block it; warn only.
                warnings.append(
                    NamingDiagnostic(
                        level="warning",
                        code="property_missing_range",
                        message=(
                            f"Object property {property_uri} is missing rdfs:range. This is "
                            "supported (DD-133 §7): the relationship is validated on its "
                            "authored target:/on: endpoint alone, as the reference-model "
                            "deferred-relationship pattern prescribes. Declare the target "
                            "class once it exists."
                        ),
                        term_uri=property_uri,
                    )
                )
            else:
                errors.append(
                    NamingDiagnostic(
                        level="error",
                        code="property_missing_range",
                        message=f"Property {property_uri} is missing rdfs:range.",
                        term_uri=property_uri,
                    )
                )
        elif is_object_property and declared_range == OWL.Thing:
            # Worse than omitting it: the compiler's relationship guard is
            # ``prop.range_uri and prop.range_uri != target_class.uri``, so an omitted
            # range short-circuits and compiles, while owl:Thing is a resolvable named
            # range that never equals the authored target: class and therefore always
            # fails as safety.relationship-endpoint (DD-133 §7).
            warnings.append(
                NamingDiagnostic(
                    level="warning",
                    code="property_range_owl_thing",
                    message=(
                        f"Object property {property_uri} declares rdfs:range owl:Thing, which "
                        "is worse than omitting rdfs:range entirely. The compiler compares a "
                        "declared named range against the authored target: class, so "
                        "owl:Thing always fails as safety.relationship-endpoint, whereas an "
                        "omitted range leaves the range unconstrained and compiles (DD-133 "
                        "§7). Remove the rdfs:range triple, or declare the real target class."
                    ),
                    term_uri=property_uri,
                )
            )
        if not _CAMEL_CASE_RE.match(_local_name(property_uri)):
            errors.append(
                NamingDiagnostic(
                    level="error",
                    code="property_name_not_camel_case",
                    message=f"Property {property_uri} is not camelCase.",
                    term_uri=property_uri,
                )
            )

    return {
        "passed": len(errors) == 0,
        "errors": [e.to_dict() for e in errors],
        "warnings": [w.to_dict() for w in warnings],
    }


def validate_managed_imports(
    ontology_file: Path,
    *,
    domain: str | None = None,
    module_context: ReferenceModuleContext | None = None,
) -> list[ModuleDiagnostic]:
    """Validate configured and authored managed imports."""
    graph = Graph()
    graph.parse(
        ontology_file,
        format="turtle" if ontology_file.suffix == ".ttl" else "xml",
    )
    resolved_domain = domain or ontology_file.stem
    plan = build_managed_import_plan(
        domain=resolved_domain,
        context=module_context,
        ontology_graph=graph,
    )
    return list(plan.diagnostics)


@dataclass(frozen=True)
class LifecycleStateProposal:
    """A computed, non-writing suggestion of the DD-080 lifecycle boundary that
    a validation run's results evidence.

    This is informational only. ``run_validation`` never mutates
    ``.kairos-state/`` — writing versioned lifecycle evidence (e.g.
    ``design-validation.json``) remains exclusively the domain of the
    interactive skills / ``kairos-flow`` orchestrator (see DD-080). A caller
    that wants to persist this suggestion as evidence must do so itself; the
    validator performs no filesystem side effects beyond the explicit
    JSON/Markdown report paths it is asked to write.
    """

    suggested_state: str
    achieved: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "suggested_state": self.suggested_state,
            "achieved": self.achieved,
            "reason": self.reason,
        }


def propose_lifecycle_state(
    results: dict,
    *,
    do_syntax: bool,
    do_shacl: bool,
) -> LifecycleStateProposal:
    """Compute a non-writing DD-080 lifecycle-state suggestion from *results*.

    Pure function: reads only the in-memory ``results`` dict produced by
    ``run_validation`` and performs no I/O. It never reads or writes
    ``.kairos-state/`` — see ``LifecycleStateProposal`` for why.
    """
    total_failed = (
        results["syntax"]["failed"]
        + results.get("naming", {}).get("failed", 0)
        + results["imports"]["failed"]
        + results["shacl"]["failed"]
        + results["consistency"]["failed"]
        + results.get("decisions", {}).get("failed", 0)
    )
    if total_failed:
        return LifecycleStateProposal(
            suggested_state="design-valid",
            achieved=False,
            reason=(
                f"{total_failed} finding(s) failed; syntax/import/SHACL/consistency "
                "checks must pass before design-valid evidence can be claimed."
            ),
        )
    if not (do_syntax and do_shacl):
        return LifecycleStateProposal(
            suggested_state="design-valid",
            achieved=False,
            reason=(
                "Run with --all (or --syntax --shacl together) to produce evidence "
                "covering the design-valid boundary; this run only covers a subset."
            ),
        )
    return LifecycleStateProposal(
        suggested_state="design-valid",
        achieved=True,
        reason=(
            "Syntax and SHACL checks passed with no consistency failures. To have "
            "kairos-flow recognize this boundary, record versioned evidence under "
            ".kairos-state/reports/design-validation.json yourself — this suggestion "
            "does not write that file."
        ),
    )


def _finding_sort_key(error: object) -> str:
    """Return a stable sort key for a findings entry (dict or plain string)."""
    if isinstance(error, dict):
        return json.dumps(error, sort_keys=True, default=str)
    return str(error)


def render_validation_markdown(
    results: dict,
    *,
    toolkit_version: str,
    ontologies_path: Path,
    shapes_path: Path,
    catalog_path: Optional[Path],
    ref_models_dir: Optional[Path],
    accelerator: Optional[str],
    do_syntax: bool,
    do_shacl: bool,
    do_consistency: bool,
    degraded: bool,
    ontology_files: list[Path],
    state_proposal: Optional[LifecycleStateProposal] = None,
) -> str:
    """Render a deterministic Markdown validation report.

    Includes the toolkit version, the effective command options, catalog and
    accelerator, the scope of scanned files, and the findings — all derived only
    from the passed-in values, so identical input always renders byte-identical
    Markdown regardless of dict/glob iteration order or wall-clock time.
    """
    lines: list[str] = []
    lines.append("# Kairos Ontology Validation Report")
    lines.append("")
    lines.append(f"- **Toolkit version:** {toolkit_version}")
    lines.append(f"- **Catalog:** {catalog_path if catalog_path else '_none resolved_'}")
    lines.append(f"- **Accelerator:** {accelerator if accelerator else '_none_'}")
    lines.append("")
    lines.append("## Effective command options")
    lines.append("")
    lines.append("| Option | Value |")
    lines.append("|--------|-------|")
    options: list[tuple[str, object]] = [
        ("ontologies", ontologies_path),
        ("shapes", shapes_path),
        ("catalog", catalog_path or "_(auto-detect)_"),
        ("ref-models", ref_models_dir or "_(auto-detect)_"),
        ("accelerator", accelerator or "_(none)_"),
        ("syntax", do_syntax),
        ("shacl", do_shacl),
        ("consistency", do_consistency),
        ("degraded", degraded),
    ]
    for name, value in options:
        lines.append(f"| `{name}` | {value} |")
    lines.append("")
    lines.append("## Scope / files")
    lines.append("")
    sorted_files = sorted(str(f) for f in ontology_files)
    if sorted_files:
        for f in sorted_files:
            lines.append(f"- `{f}`")
    else:
        lines.append("_No ontology files found in scope._")
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    sections = ("syntax", "naming", "imports", "shacl", "consistency", "decisions")
    lines.append("| Check | Passed | Failed | Warnings |")
    lines.append("|-------|--------|--------|----------|")
    for section in sections:
        data = results.get(section, {})
        warning_count = len(data.get("warnings") or [])
        lines.append(
            f"| {section} | {data.get('passed', 0)} | {data.get('failed', 0)} | {warning_count} |"
        )
    lines.append("")
    # Warnings are rendered as well as errors — they never feed ``total_failed`` or the
    # exit code, but a finding nobody can see is a finding nobody acts on (e.g. the
    # DD-133 §7 object-property range warnings). Errors first, then warnings; within a
    # kind the section order is fixed and the entries are sorted by ``_finding_sort_key``,
    # so the rendered Markdown stays byte-deterministic (DD-120).
    for kind in ("errors", "warnings"):
        for section in sections:
            findings = results.get(section, {}).get(kind) or []
            if not findings:
                continue
            lines.append(f"### {section.capitalize()} {kind}")
            lines.append("")
            for finding in sorted(findings, key=_finding_sort_key):
                if isinstance(finding, dict):
                    file_ = finding.get("file", "")
                    message = (
                        finding.get("error")
                        or finding.get("message")
                        or finding.get("report")
                        or ""
                    )
                    lines.append(f"- `{file_}`: {message}")
                else:
                    lines.append(f"- {finding}")
            lines.append("")
    if state_proposal is not None:
        lines.append("## Suggested lifecycle state (non-writing signal)")
        lines.append("")
        lines.append(f"- **State:** `{state_proposal.suggested_state}`")
        lines.append(f"- **Achieved:** {state_proposal.achieved}")
        lines.append(f"- **Reason:** {state_proposal.reason}")
        lines.append("")
    return "\n".join(lines) + "\n"


def run_validation(
    ontologies_path: Path,
    shapes_path: Path,
    catalog_path: Path,
    do_syntax: bool,
    do_shacl: bool,
    do_consistency: bool,
    report_path: Optional[Path] = None,
    degraded: bool = False,
    ref_models_dir: Optional[Path] = None,
    accelerator: Optional[str] = None,
    markdown_report_path: Optional[Path] = None,
    decisions_path: Optional[Path] = None,
    gdpr_warnings: int = 0,
):
    """Run validation pipeline.

    Args:
        ontologies_path: Directory to scan for domain ontology files.
        shapes_path: Directory containing SHACL shape files (optional; skipped
            if it does not exist).
        catalog_path: Optional XML catalog used to resolve ``owl:imports``.
        do_syntax: Run Level 1 syntax validation.
        do_shacl: Run Level 2 SHACL validation.
        do_consistency: Run Level 3 consistency validation.
        report_path: Explicit path to write the JSON results report to. The
            parent directory is created if missing. When omitted (the
            default), no report file is written — this keeps the contract
            explicit for direct library callers instead of silently guessing
            a location relative to the process's current working directory.
            CLI callers should always pass
            ``<repo>/ontology-hub-publish/validation-report.json``.
        markdown_report_path: Additive: explicit path to also (or instead) write a
            deterministic Markdown validation report (toolkit version, effective
            command options, catalog, accelerator, scope/files, and findings — see
            ``render_validation_markdown``). Omitted by default, which preserves the
            pre-existing JSON-only report contract exactly.
        decisions_path: Optional OKF decision bundle directory to validate when present.
        gdpr_warnings: Count of unprotected-PII warnings from a GDPR scan that already
            ran earlier in this same ``validate`` invocation (issue #325). Purely
            advisory and does NOT affect the exit code here (see the issue's own framing:
            whether unprotected PII should block is a separate product decision, and this
            fix keeps the GDPR scan non-blocking, matching the toolkit's other
            warning-tolerant advisory checks -- DD-089's silver-sample-audit, the
            NK-coverage-warned-not-enforced precedent). What it DOES change: the final
            summary line below no longer claims a clean bill of health while GDPR
            warnings are open. Defaults to 0 (unchanged behavior) for callers that ran no
            GDPR scan or don't pass it.
    """

    print("🔍 Kairos Ontology Validation")
    print("=" * 50)

    results = {
        "syntax": {"passed": 0, "failed": 0, "errors": []},
        "naming": {"passed": 0, "failed": 0, "errors": [], "warnings": []},
        "imports": {"passed": 0, "failed": 0, "errors": [], "warnings": []},
        "shacl": {"passed": 0, "failed": 0, "errors": []},
        "consistency": {"passed": 0, "failed": 0, "errors": []},
        "decisions": {"passed": 0, "failed": 0, "errors": [], "warnings": []},
    }

    # Find all ontology files. Sorted for deterministic iteration/reporting order
    # (glob() order is filesystem-dependent), which the Markdown report relies on.
    ontology_files = list(ontologies_path.glob("**/*.ttl")) + list(ontologies_path.glob("**/*.rdf"))
    # Skip non-domain files: silver-ext annotations, _master imports, etc.
    ontology_files = sorted((f for f in ontology_files if _is_domain_ontology(f)), key=str)

    print(f"\nFound {len(ontology_files)} ontology files\n")

    # Semantic import preflight is separate from syntax parsing. It catches
    # externally used governed terms whose required owl:imports edge is absent;
    # the canonical loader cannot discover an import edge that was never authored.
    if do_shacl or do_consistency:
        imported_ontology_iris: set[str] = set()
        for ontology_file in ontology_files:
            try:
                scope_graph = Graph().parse(ontology_file)
            except Exception:  # syntax diagnostics below retain ownership of parse failures
                continue
            imported_ontology_iris.update(
                str(imported) for imported in scope_graph.objects(predicate=OWL.imports)
            )
        module_context = build_reference_module_context(
            ref_models_dir,
            catalog_path=catalog_path,
            accelerator=accelerator,
            requested_domains=(path.stem for path in ontology_files),
            imported_ontology_iris=imported_ontology_iris,
        )
        print("🔗 Managed Import Completeness")
        print("-" * 50)
        for ontology_file in ontology_files:
            activation = (
                module_context.config.activation(ontology_file.stem) if module_context else None
            )
            if activation is None and module_context is None:
                continue
            try:
                diagnostics = validate_managed_imports(
                    ontology_file,
                    domain=ontology_file.stem,
                    module_context=module_context,
                )
            except Exception as exc:  # noqa: BLE001
                results["imports"]["failed"] += 1
                results["imports"]["errors"].append({"file": str(ontology_file), "error": str(exc)})
                print(f"  ✗ {ontology_file.name}: {exc}")
                continue

            errors = [item for item in diagnostics if item.level == "error"]
            warnings = [item for item in diagnostics if item.level != "error"]
            hard_errors = [item for item in errors if item.code != "missing_managed_import"]
            degradable_errors = [item for item in errors if item.code == "missing_managed_import"]
            results["imports"]["warnings"].extend(
                {"file": str(ontology_file), **item.to_dict()} for item in warnings
            )
            if hard_errors or (degradable_errors and not degraded):
                results["imports"]["failed"] += 1
                results["imports"]["errors"].extend(
                    {"file": str(ontology_file), **item.to_dict()} for item in errors
                )
                print(f"  ✗ {ontology_file.name}: {len(errors)} missing/invalid import(s)")
                for item in errors:
                    print(f"    {item.message}")
            else:
                results["imports"]["passed"] += 1
                if degradable_errors:
                    results["imports"]["warnings"].extend(
                        {"file": str(ontology_file), **item.to_dict()} for item in degradable_errors
                    )
                    print(
                        f"  ⚠ {ontology_file.name}: degraded mode accepted "
                        f"{len(degradable_errors)} import error(s)"
                    )
                else:
                    print(f"  ✓ {ontology_file.name}")
            for item in warnings:
                print(f"    ⚠ {item.message}")
        imports_warning_count = len(results["imports"]["warnings"])
        if imports_warning_count:
            print(f"\n  Imports — Warnings: {imports_warning_count}")
        print()

    if decisions_path is not None and Path(decisions_path).is_dir():
        from .decision_records import validate_decision_bundle

        dres = validate_decision_bundle(Path(decisions_path))
        results["decisions"]["errors"].extend(d.to_dict() for d in dres.errors)
        results["decisions"]["warnings"].extend(d.to_dict() for d in dres.warnings)
        results["decisions"]["failed"] = len(dres.errors)
        results["decisions"]["passed"] = len(
            [r for r in dres.records if not any(e.file == r.path.name for e in dres.errors)]
        )

        print("🗒️  Decision Log")
        print("-" * 50)
        record_names = {record.path.name for record in dres.records}
        if not dres.records and not dres.errors and not dres.warnings:
            print("  ✓ No decision records found")
        for record in dres.records:
            record_errors = [error for error in dres.errors if error.file == record.path.name]
            record_warnings = [
                warning for warning in dres.warnings if warning.file == record.path.name
            ]
            if record_errors:
                print(f"  ✗ {record.path.name}: {len(record_errors)} error(s)")
                for error in record_errors:
                    print(f"    {error.message}")
            else:
                print(f"  ✓ {record.path.name}")
            for warning in record_warnings:
                print(f"    ⚠ {warning.message}")
        for error in dres.errors:
            if error.file not in record_names:
                print(f"  ✗ {error.file}: {error.message}")
        for warning in dres.warnings:
            if warning.file not in record_names:
                print(f"  ⚠ {warning.file}: {warning.message}")
        decisions_warning_count = len(results["decisions"]["warnings"])
        decisions_warnings_suffix = (
            f", Warnings: {decisions_warning_count}" if decisions_warning_count else ""
        )
        print(
            f"\n  Passed: {results['decisions']['passed']}, "
            f"Failed: {results['decisions']['failed']}{decisions_warnings_suffix}\n"
        )

    # Level 1: Syntax Validation
    if do_syntax:
        print("📋 Level 1: Syntax Validation")
        print("-" * 50)
        for ontology_file in ontology_files:
            try:
                g = Graph()
                g.parse(ontology_file, format="turtle" if ontology_file.suffix == ".ttl" else "xml")
                results["syntax"]["passed"] += 1
                print(f"  ✓ {ontology_file.name}")
            except Exception as e:
                results["syntax"]["failed"] += 1
                results["syntax"]["errors"].append({"file": str(ontology_file), "error": str(e)})
                print(f"  ✗ {ontology_file.name}: {e}")
                continue

            naming_result = validate_naming_conventions(ontology_file.read_text(encoding="utf-8"))
            if naming_result["errors"]:
                results["naming"]["failed"] += 1
                results["naming"]["errors"].extend(
                    {"file": str(ontology_file), **e} for e in naming_result["errors"]
                )
                print(
                    f"    ✗ {len(naming_result['errors'])} naming/annotation error(s) "
                    f"in {ontology_file.name}"
                )
            else:
                results["naming"]["passed"] += 1
            results["naming"]["warnings"].extend(
                {"file": str(ontology_file), **w} for w in naming_result["warnings"]
            )

        print(f"\n  Passed: {results['syntax']['passed']}, Failed: {results['syntax']['failed']}\n")
        naming_warning_count = len(results["naming"]["warnings"])
        naming_warnings_suffix = (
            f", Warnings: {naming_warning_count}" if naming_warning_count else ""
        )
        print(
            f"  Naming/annotation — Passed: {results['naming']['passed']}, "
            f"Failed: {results['naming']['failed']}{naming_warnings_suffix}\n"
        )
        # Mirror render_validation_markdown's per-section warning rendering (rc22): a
        # warning nobody sees on the console is a warning nobody acts on, and the JSON/
        # Markdown reports already surface these (issue #332).
        if naming_warning_count:
            print("  Naming/annotation warnings:")
            for w in results["naming"]["warnings"]:
                file_ = w.get("file", "")
                message = w.get("message", "")
                print(f"    ⚠ {file_}: {message}")
            print()

    # Level 2: SHACL Validation
    if do_shacl and shapes_path.exists():
        print("📐 Level 2: SHACL Validation")
        print("-" * 50)

        # Load all shapes
        shapes_graph = Graph()
        for shape_file in shapes_path.glob("**/*.shacl.ttl"):
            shapes_graph.parse(shape_file, format="turtle")

        for ontology_file in ontology_files:
            try:
                from .ontology_loader import SemanticProfile, load_ontology

                loaded = load_ontology(
                    ontology_file,
                    catalog_path=catalog_path,
                    profile=SemanticProfile.RDFS,
                    degraded=degraded,
                )
                data_graph = loaded.graph

                conforms, report_graph, report_text = shacl_validate(
                    data_graph, shacl_graph=shapes_graph, inference="rdfs", abort_on_first=False
                )

                if conforms:
                    results["shacl"]["passed"] += 1
                    results["shacl"].setdefault("semantic_context", {})[str(ontology_file)] = {
                        "profile": loaded.profile.value,
                        "closure_hash": loaded.closure_hash,
                        "import_complete": loaded.complete,
                    }
                    print(f"  ✓ {ontology_file.name}")
                else:
                    results["shacl"]["failed"] += 1
                    results["shacl"]["errors"].append(
                        {"file": str(ontology_file), "report": report_text}
                    )
                    print(f"  ✗ {ontology_file.name}")
                    print(f"    {report_text}")

            except Exception as e:
                results["shacl"]["failed"] += 1
                results["shacl"]["errors"].append({"file": str(ontology_file), "error": str(e)})
                print(f"  ✗ {ontology_file.name}: {e}")

        print(f"\n  Passed: {results['shacl']['passed']}, Failed: {results['shacl']['failed']}\n")

    # Level 3: Consistency Validation (SPARQL queries)
    if do_consistency:
        print("🔗 Level 3: Consistency Validation")
        print("-" * 50)
        # TODO: Implement naturalKey completeness check once the validator
        # loads extension files (silver-ext.ttl). Currently, naturalKey
        # annotations may live in extensions rather than the domain ontology,
        # so checking here would produce false positives. The dbt projector
        # already emits warnings for missing naturalKey at projection time
        # (when the merged graph is available).
        print("  (Custom SPARQL queries for consistency checks)")
        print("  Not implemented yet - future enhancement\n")

    # Save results (explicit destination only — see report_path docstring above)
    # Non-writing lifecycle-state suggestion (typed, DD-080): computed here purely
    # from in-memory `results`; never persisted to `.kairos-state/` by this function.
    state_proposal = propose_lifecycle_state(results, do_syntax=do_syntax, do_shacl=do_shacl)
    results["state_proposal"] = state_proposal.to_dict()

    if report_path is not None:
        report_path = Path(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"📄 Results saved to {report_path}")

    if markdown_report_path is not None:
        from kairos_ontology import __version__ as _toolkit_version

        markdown_report_path = Path(markdown_report_path)
        markdown_report_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_report_path.write_text(
            render_validation_markdown(
                results,
                toolkit_version=_toolkit_version,
                ontologies_path=ontologies_path,
                shapes_path=shapes_path,
                catalog_path=catalog_path,
                ref_models_dir=ref_models_dir,
                accelerator=accelerator,
                do_syntax=do_syntax,
                do_shacl=do_shacl,
                do_consistency=do_consistency,
                degraded=degraded,
                ontology_files=ontology_files,
                state_proposal=state_proposal,
            ),
            encoding="utf-8",
        )
        print(f"📄 Markdown report saved to {markdown_report_path}")

    # Exit code
    total_failed = (
        results["syntax"]["failed"]
        + results["naming"]["failed"]
        + results["imports"]["failed"]
        + results["shacl"]["failed"]
        + results["consistency"]["failed"]
        + results["decisions"]["failed"]
    )
    # Issue #332: warnings never feed the exit code (unchanged), but the final line
    # must not claim a clean bill of health while ANY section still has open warnings
    # -- naming/imports/decisions (each carries its own `warnings` list, printed with
    # its section above, mirroring render_validation_markdown's per-section rendering)
    # as well as the GDPR scan's warnings (issue #325's precedent for this same
    # qualified-summary pattern, kept verbatim below for compatibility).
    section_warning_count = (
        len(results["naming"]["warnings"])
        + len(results["imports"]["warnings"])
        + len(results["decisions"]["warnings"])
    )
    total_open_warnings = gdpr_warnings + section_warning_count

    if total_failed > 0:
        print(f"\n❌ Validation failed with {total_failed} errors")
        exit(1)
    elif total_open_warnings:
        # Deliberately non-blocking (exit 0) -- see `gdpr_warnings` docstring above;
        # whether warnings should ever fail the run is a separate product decision
        # this fix does not make.
        detail_parts = []
        if gdpr_warnings:
            detail_parts.append(
                f"{gdpr_warnings} unprotected PII warning(s) from the GDPR scan above"
            )
        if section_warning_count:
            detail_parts.append(f"{section_warning_count} warning(s) in the sections above")
        print(f"\n✅ All validations passed (⚠️  {' and '.join(detail_parts)} remain open)")
    else:
        print("\n✅ All validations passed!")


# ---------------------------------------------------------------------------
# DD-044: Whitelist / mapping mismatch validation
# ---------------------------------------------------------------------------


def validate_whitelist_mapping(
    ontology_path: Path,
    extensions_dir: Path,
    mappings_dir: Optional[Path] = None,
) -> list[dict]:
    """Check for mismatches between silverInclude annotations and SKOS mappings.

    Returns a list of warning dicts with keys: ``class_uri``, ``class_name``,
    ``warning_type`` ("mapped_not_whitelisted" | "whitelisted_not_mapped"),
    and ``message``.
    """
    warnings: list[dict] = []

    # 1. Collect silverInclude'd classes from extension files
    whitelisted: set[str] = set()
    for ext_file in extensions_dir.glob("**/*-silver-ext.ttl"):
        try:
            g = Graph()
            g.parse(ext_file, format="turtle")
            for subj in g.subjects(KAIROS_EXT.silverInclude, None):
                val = g.value(subj, KAIROS_EXT.silverInclude)
                if val is not None and str(val).lower() in ("true", "1"):
                    whitelisted.add(str(subj))
        except Exception:
            pass

    # 2. Collect mapped classes from SKOS mapping files
    mapped: set[str] = set()
    if mappings_dir and mappings_dir.is_dir():
        SKOS_NS = Namespace("http://www.w3.org/2004/02/skos/core#")
        for mapping_file in mappings_dir.glob("*.ttl"):
            try:
                g = Graph()
                g.parse(mapping_file, format="turtle")
                for _s, _p, o in g.triples((None, SKOS_NS.broadMatch, None)):
                    # The object is typically a domain property URI — extract class
                    uri_str = str(o)
                    if "#" in uri_str:
                        mapped.add(uri_str.rsplit("#", 1)[0] + "#")
                    elif "/" in uri_str:
                        mapped.add(uri_str.rsplit("/", 1)[0] + "/")
            except Exception:
                pass

    if not whitelisted and not mapped:
        return warnings

    # 3. Check for mismatches
    for cls_uri in mapped - whitelisted:
        cls_name = cls_uri.split("#")[-1].split("/")[-1] if cls_uri else cls_uri
        warnings.append(
            {
                "class_uri": cls_uri,
                "class_name": cls_name,
                "warning_type": "mapped_not_whitelisted",
                "message": (
                    f"Class {cls_name} has SKOS source mappings but no "
                    f"silverInclude annotation. It will not be projected to silver."
                ),
            }
        )

    for cls_uri in whitelisted - mapped:
        cls_name = cls_uri.split("#")[-1].split("/")[-1] if cls_uri else cls_uri
        warnings.append(
            {
                "class_uri": cls_uri,
                "class_name": cls_name,
                "warning_type": "whitelisted_not_mapped",
                "message": (
                    f"Class {cls_name} has silverInclude but no source mappings. "
                    f"It will produce an empty silver table."
                ),
            }
        )

    return warnings
