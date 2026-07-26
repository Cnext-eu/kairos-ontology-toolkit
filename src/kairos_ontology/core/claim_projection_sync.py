# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Claim-driven projection sync (Slice 2).

Deterministic bridge between the Claim Registry and projection-facing authored
surfaces:

* domain ontology ``owl:imports`` (A1: imports generated from approved imported
  class claims),
* silver extension per-class ``kairos-ext:silverInclude`` assertions.

This module is AI-free and purely structural.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD
from rdflib.plugins.parsers.notation3 import BadSyntax

from .binding_analysis import approved_imported_class_uris, approved_imported_term_refs
from .claim_registry import ClaimRegistry, load_registry
from .managed_text_block import (
    ManagedBlockError,
    compose_managed_file,
    replace_managed_block,
    split_managed_block,
)
from .projections.shared import KAIROS_EXT
from .reference_modules import (
    ModuleDiagnostic,
    ReferenceModuleContext,
    build_managed_import_plan,
    build_reference_module_context,
    validate_external_term_imports,
)


def _truthy(value: object) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes"}


def _module_scope_evidence(
    *,
    claims_dir: Path,
    ontologies_dir: Path,
    domains_filter: list[str] | None,
) -> tuple[set[str], set[str], set[str]]:
    """Collect module-selection evidence without loading any module closures."""
    lowers = [item.lower() for item in domains_filter] if domains_filter else None

    def in_scope(domain: str) -> bool:
        return lowers is None or any(token in domain.lower() for token in lowers)

    domains = set(domains_filter or ())
    claimed_terms: set[str] = set()
    imported_iris: set[str] = set()
    if claims_dir.is_dir():
        for path in claims_dir.glob("*-claims.yaml"):
            domain = path.name.removesuffix("-claims.yaml")
            if not in_scope(domain):
                continue
            domains.add(domain)
            registry = load_registry(path)
            claimed_terms.update(
                term_uri
                for _claim_id, term_uri, _claim_type in approved_imported_term_refs(registry)
            )
    if ontologies_dir.is_dir():
        for path in (*ontologies_dir.glob("*.ttl"), *ontologies_dir.glob("*.rdf")):
            if not in_scope(path.stem):
                continue
            domains.add(path.stem)
            try:
                graph = Graph().parse(path)
            except Exception:  # syntax/load diagnostics are owned by the caller
                continue
            imported_iris.update(str(value) for value in graph.objects(predicate=OWL.imports))
            claimed_terms.update(
                str(node)
                for triple in graph
                for node in triple
                if isinstance(node, URIRef)
            )
    return domains, claimed_terms, imported_iris


def _class_uri_to_import_uri(class_uri: str) -> str:
    if "#" in class_uri:
        return class_uri.rsplit("#", 1)[0]
    if "/" in class_uri:
        return class_uri.rsplit("/", 1)[0]
    return class_uri


def _ontology_subject(graph: Graph) -> URIRef | None:
    for subject in graph.subjects(RDF.type, OWL.Ontology):
        if isinstance(subject, URIRef):
            return subject
    return None


def _domain_namespace_variants(ontology_iri: str) -> tuple[str, str]:
    bare = ontology_iri.rstrip("#/")
    return bare + "#", bare + "/"


def _is_local_class_uri(class_uri: str, ontology_iri: str) -> bool:
    hash_ns, slash_ns = _domain_namespace_variants(ontology_iri)
    return class_uri.startswith(hash_ns) or class_uri.startswith(slash_ns)


def _approved_imported_class_uris(registry, ontology_iri: str) -> set[str]:
    """Return approved imported class URIs that are external to *ontology_iri*.

    Delegates the claim filter (approved + imported origin + claim/specialize
    disposition) to the canonical :func:`binding_analysis.approved_imported_class_uris`
    so import sync and materialization never reimplement divergent filters. Only
    the sync-specific "external to this domain" rule is applied here.
    """
    return {
        uri
        for uri in approved_imported_class_uris(registry)
        if not _is_local_class_uri(uri, ontology_iri)
    }


def _expected_external_imports(approved_imported_class_uris: set[str]) -> set[str]:
    return {_class_uri_to_import_uri(uri).rstrip("#/") for uri in approved_imported_class_uris}


def _collect_hub_domain_bases(ontologies_dir: Path) -> set[str]:
    """Collect the IRIs of every intra-hub ``owl:Ontology`` base.

    Any ``*.ttl`` under ``model/ontologies/`` that declares an ``owl:Ontology`` is
    a legitimate intra-hub import target — including the ``_``-prefixed shared bases
    (``_foundation.ttl``, ``_master.ttl``) that every domain ontology is expected to
    import. Only the ``-ext.ttl`` extension surfaces are excluded, since they are
    silver/gold extension files, not domain bases. Imports of any collected base are
    neither flagged as ``extra`` nor stripped during sync.
    """
    bases: set[str] = set()
    if not ontologies_dir.is_dir():
        return bases
    for path in sorted(ontologies_dir.glob("*.ttl")):
        if path.name.endswith("-ext.ttl"):
            continue
        graph = Graph()
        try:
            graph.parse(path, format="turtle")
        except BadSyntax as exc:
            raise ValueError(f"Invalid Turtle in hub ontology base {path}: {exc}") from exc
        subj = _ontology_subject(graph)
        if subj is not None:
            bases.add(str(subj).rstrip("#/"))
    return bases


@dataclass
class DomainProjectionSync:
    domain: str
    claims_file: Path
    ontology_file: Path
    extension_file: Path
    missing_imports: list[str] = field(default_factory=list)
    extra_imports: list[str] = field(default_factory=list)
    missing_includes: list[str] = field(default_factory=list)
    extra_includes: list[str] = field(default_factory=list)
    import_diagnostics: list[ModuleDiagnostic] = field(default_factory=list)
    activation_inventory: dict = field(default_factory=dict)
    disputed_claims: list = field(default_factory=list)
    has_bulk_include_imports: bool = False
    error: str | None = None

    @property
    def in_sync(self) -> bool:
        return (
            self.error is None
            and not self.missing_imports
            and not self.extra_imports
            and not self.missing_includes
            and not self.extra_includes
            and not any(item.level == "error" for item in self.import_diagnostics)
            and not self.has_bulk_include_imports
        )


@dataclass
class ProjectionSyncReport:
    domains: list[DomainProjectionSync] = field(default_factory=list)
    #: The skill that owns enforcing this report's blocking behaviour (DD-122).
    #: ``check-claims`` surfaces sync drift for visibility but does not block on
    #: it by default; ``claims-to-silver-ext --check-only`` remains the owning
    #: workflow that blocks.
    owner_skill: str = "kairos-design-domain"
    #: Set by :func:`apply_projection_sync` (``None`` for ``evaluate_projection_sync``
    #: / ``--check-only``, which never write anything) to the explicit
    #: created/updated/unchanged accounting from :func:`scaffold_missing_surfaces`.
    scaffold_result: "ScaffoldSurfacesResult | None" = None

    @property
    def out_of_sync(self) -> list[DomainProjectionSync]:
        return [d for d in self.domains if not d.in_sync]

    @property
    def is_blocking(self) -> bool:
        return bool(self.out_of_sync)

    @property
    def disputed_claims(self) -> list:
        """All disputed-claim entries across every evaluated domain (DD-122)."""
        return [item for d in self.domains for item in d.disputed_claims]


def evaluate_domain_projection_sync(
    *,
    domain: str,
    claims_file: Path,
    ontology_file: Path,
    extension_file: Path,
    hub_domain_bases: set[str],
    module_context: ReferenceModuleContext | None = None,
) -> DomainProjectionSync:
    status = DomainProjectionSync(
        domain=domain,
        claims_file=claims_file,
        ontology_file=ontology_file,
        extension_file=extension_file,
    )

    activation = module_context.config.activation(domain) if module_context else None
    if not claims_file.exists() and activation is None:
        status.error = (
            f"missing Claim Registry for domain {domain!r}: {claims_file}. "
            "Use kairos-design-source to create the domain Claim Registry, then rerun "
            "check-claims."
        )
        return status
    if not ontology_file.exists():
        status.error = f"missing ontology file: {ontology_file}"
        return status
    if not extension_file.exists():
        status.error = f"missing extension file: {extension_file}"
        return status

    try:
        registry = (
            load_registry(claims_file)
            if claims_file.exists()
            else ClaimRegistry(domain=domain)
        )
        ontology_graph = Graph()
        ontology_graph.parse(ontology_file, format="turtle")
        ext_graph = Graph()
        ext_graph.parse(extension_file, format="turtle")
    except Exception as exc:  # noqa: BLE001
        status.error = str(exc)
        return status

    ontology_subj = _ontology_subject(ontology_graph)
    if ontology_subj is None:
        status.error = f"no owl:Ontology found in {ontology_file.name}"
        return status
    ontology_iri = str(ontology_subj)
    actual_includes = {
        str(subj)
        for subj in ext_graph.subjects(KAIROS_EXT.silverInclude, None)
        if not _is_local_class_uri(str(subj), ontology_iri)
        and _truthy(ext_graph.value(subj, KAIROS_EXT.silverInclude))
    }
    authored_text, _has_block = _split_managed_block(
        _read_turtle_text(ontology_file),
        path=ontology_file,
    )
    authored_graph = Graph()
    authored_graph.parse(data=authored_text, format="turtle")

    plan = build_managed_import_plan(
        registry,
        domain=domain,
        context=module_context,
        authored_ontology_graph=authored_graph,
        projected_uris=actual_includes,
        local_ontology_iri=ontology_iri,
    )
    status.import_diagnostics = list(plan.diagnostics)
    status.activation_inventory = plan.activation_inventory
    status.disputed_claims = [
        {**item.to_dict(), "domain": domain} for item in plan.disputed_claims
    ]
    configuration_errors = [
        item for item in plan.diagnostics if item.level == "error"
    ]
    if configuration_errors:
        status.error = "; ".join(item.message for item in configuration_errors)
        return status
    expected_includes = {
        uri
        for uri in plan.selected_class_uris
        if not _is_local_class_uri(uri, ontology_iri)
    }
    expected_imports = set(plan.expected_imports)

    def _is_managed_import(triple) -> bool:
        _s, predicate, obj = triple
        iri = str(obj).rstrip("#")
        return (
            predicate == OWL.imports
            and iri.rstrip("/") not in hub_domain_bases
            and iri in expected_imports
        )

    def _is_managed_include(triple) -> bool:
        subject, predicate, _obj = triple
        if predicate == KAIROS_EXT.silverIncludeImports:
            return True
        if predicate == KAIROS_EXT.silverInclude:
            return not _is_local_class_uri(str(subject), ontology_iri)
        return False

    try:
        _require_current_managed_surface(ontology_file, _is_managed_import)
        _require_current_managed_surface(extension_file, _is_managed_include)
    except ProjectionMigrationRequiredError as exc:
        status.error = str(exc)
        return status

    authored_imports = {
        str(obj).rstrip("#")
        for obj in authored_graph.objects(ontology_subj, OWL.imports)
    }
    actual_imports: set[str] = set()
    for obj in ontology_graph.objects(ontology_subj, OWL.imports):
        iri = str(obj).rstrip("#")
        # Intra-hub shared bases (e.g. _foundation/_master) are neither required
        # nor "extra" — skip them so they aren't flagged/stripped (issue #190). But
        # if a base is *also* a claim-driven expected import, it must still count as
        # a satisfied import rather than being silently dropped.
        if iri.rstrip("/") in hub_domain_bases and iri not in expected_imports:
            continue
        actual_imports.add(iri)
    managed_imports = actual_imports - authored_imports

    bulk_subj = URIRef(ontology_iri.rstrip("#/"))
    status.has_bulk_include_imports = _truthy(ext_graph.value(bulk_subj, KAIROS_EXT.silverIncludeImports))

    status.missing_imports = sorted(expected_imports - actual_imports)
    status.extra_imports = sorted(managed_imports - expected_imports)
    status.missing_includes = sorted(expected_includes - actual_includes)
    status.extra_includes = sorted(actual_includes - expected_includes)
    status.import_diagnostics.extend(validate_external_term_imports(ontology_graph, plan))
    status.import_diagnostics = sorted(
        status.import_diagnostics,
        key=lambda item: (
            item.code,
            item.term_uri or "",
            item.expected_ontology_iri or "",
        ),
    )
    return status


def evaluate_projection_sync(
    *,
    claims_dir: Path,
    ontologies_dir: Path,
    extensions_dir: Path,
    domains_filter: list[str] | None = None,
    ref_models_dir: Path | None = None,
    catalog_path: Path | None = None,
    accelerator: str | None = None,
    module_context: ReferenceModuleContext | None = None,
) -> ProjectionSyncReport:
    report = ProjectionSyncReport()

    lowers = [d.lower() for d in domains_filter] if domains_filter else None

    def _in_scope(name: str) -> bool:
        if lowers is None:
            return True
        return any(token in name.lower() for token in lowers)

    if module_context is None:
        scoped_domains, claimed_terms, imported_iris = _module_scope_evidence(
            claims_dir=claims_dir,
            ontologies_dir=ontologies_dir,
            domains_filter=domains_filter,
        )
        module_context = build_reference_module_context(
            ref_models_dir,
            catalog_path=catalog_path,
            accelerator=accelerator,
            requested_domains=scoped_domains if domains_filter else None,
            claimed_term_uris=claimed_terms,
            imported_ontology_iris=imported_iris,
        )
    hub_domain_bases = _collect_hub_domain_bases(ontologies_dir)

    domains = {
        path.name.replace("-claims.yaml", "")
        for path in claims_dir.glob("*-claims.yaml")
    } if claims_dir.is_dir() else set()
    if module_context:
        domains.update(item.domain for item in module_context.config.domains)
    for path in ontologies_dir.glob("*.ttl"):
        if _MANAGED_BEGIN in path.read_text(encoding="utf-8"):
            domains.add(path.stem)
    for path in extensions_dir.glob("*-silver-ext.ttl"):
        if _MANAGED_BEGIN in path.read_text(encoding="utf-8"):
            domains.add(path.name.removesuffix("-silver-ext.ttl"))

    for domain in sorted(domains):
        if not _in_scope(domain):
            continue
        claims_file = claims_dir / f"{domain}-claims.yaml"
        ontology_file = ontologies_dir / f"{domain}.ttl"
        extension_file = extensions_dir / f"{domain}-silver-ext.ttl"
        report.domains.append(
            evaluate_domain_projection_sync(
                domain=domain,
                claims_file=claims_file,
                ontology_file=ontology_file,
                extension_file=extension_file,
                hub_domain_bases=hub_domain_bases,
                module_context=module_context,
            )
        )
    return report


# Managed-block markers (issue #191). ``claims-to-silver-ext`` owns only the triples
# *between* these markers; everything else in the file is authored content preserved
# verbatim. The managed region is regenerated wholesale as text (full URIs, so it is
# independent of the authored prefix declarations), which means authored comments, the
# DD-072 provenance header, prefix layout and triple ordering all survive every sync —
# instead of being destroyed by a whole-graph rdflib re-serialize.
_MANAGED_BEGIN = "# >>> kairos-managed (generated from the Claim Registry — do not edit)"
_MANAGED_END = "# <<< kairos-managed"


class ProjectionMigrationRequiredError(ValueError):
    """Raised when a projection surface still uses the pre-managed-block layout."""


@dataclass(frozen=True)
class ManagedSurfaceInspection:
    """Parsed layout facts for one projection-facing TTL surface."""

    authored_text: str
    has_block: bool
    stray_managed_triples: tuple[tuple[object, object, object], ...]


def projection_migration_error(path: Path, reason: str) -> str:
    """Build the actionable diagnostic shared by readers and the CLI."""
    return (
        f"{path}: legacy claim projection sync layout ({reason}). Run "
        "`kairos-ontology migrate --hub <hub>` to convert it to a managed block; "
        "the Claim Registry remains authoritative."
    )


def _stray_resources(triples: tuple[tuple[object, object, object], ...]) -> str:
    """Name controlled resources so managed-block diagnostics are actionable."""
    return ", ".join(
        sorted({f"<{subject}> via <{predicate}>" for subject, predicate, _ in triples})
    )


def _read_turtle_text(path: Path) -> str:
    """Read UTF-8 Turtle without normalizing user-authored line endings."""
    return path.read_bytes().decode("utf-8")


def _line_ending(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _split_managed_block(text: str, *, path: Path | None = None) -> tuple[str, bool]:
    """Return all authored text and whether it contains one well-formed block.

    Delegates the splice mechanics to the shared
    :mod:`kairos_ontology.core.managed_text_block` implementation (one algorithm,
    no second copy) and translates its generic :class:`ManagedBlockError` into
    this module's actionable :class:`ProjectionMigrationRequiredError`, which
    names the ``migrate`` remediation the Claim Registry workflow needs.
    """
    label = str(path) if path is not None else "<projection surface>"
    try:
        return split_managed_block(
            text, begin_marker=_MANAGED_BEGIN, end_marker=_MANAGED_END, label=label
        )
    except ManagedBlockError as exc:
        raise ProjectionMigrationRequiredError(
            projection_migration_error(path or Path(label), "malformed managed-block markers")
        ) from exc


def _strip_managed_block(text: str, *, path: Path | None = None) -> str:
    """Return authored content after validating a canonical managed-block layout."""
    authored, _ = _split_managed_block(text, path=path)
    return authored


def _turtle_statement(subject: URIRef, predicate: URIRef, obj: object) -> str:
    if isinstance(obj, Literal):
        if obj.datatype is not None:
            rendered = f'"{obj}"^^<{obj.datatype}>'
        elif obj.language:
            rendered = f'"{obj}"@{obj.language}'
        else:
            rendered = f'"{obj}"'
    else:
        rendered = f"<{obj}>"
    return f"<{subject}> <{predicate}> {rendered} ."


def _compose_managed_file(authored_text: str, managed_lines: list[str]) -> str:
    """Append a deterministic block without reformatting authored Turtle."""
    return compose_managed_file(
        authored_text,
        managed_lines,
        begin_marker=_MANAGED_BEGIN,
        end_marker=_MANAGED_END,
    )


def _replace_managed_block(text: str, managed_lines: list[str], *, path: Path) -> str:
    """Replace only the managed span, preserving authored bytes on both sides."""
    # Validate first so a malformed surface raises this module's migration error
    # rather than the generic ManagedBlockError.
    _split_managed_block(text, path=path)
    return replace_managed_block(
        text,
        managed_lines,
        begin_marker=_MANAGED_BEGIN,
        end_marker=_MANAGED_END,
        label=str(path),
    )


def _inspect_managed_surface(path: Path, is_managed_authored) -> ManagedSurfaceInspection:
    """Identify controlled triples that remain outside the managed block."""
    text = _read_turtle_text(path)
    authored_text, has_block = _split_managed_block(text, path=path)
    graph = Graph()
    graph.parse(data=authored_text, format="turtle")
    stray = tuple(sorted((triple for triple in graph if is_managed_authored(triple)), key=str))
    return ManagedSurfaceInspection(
        authored_text=authored_text,
        has_block=has_block,
        stray_managed_triples=stray,
    )


def _require_current_managed_surface(path: Path, is_managed_authored) -> None:
    """Reject a legacy inline managed surface instead of converting it at runtime."""
    inspection = _inspect_managed_surface(path, is_managed_authored)
    if inspection.stray_managed_triples:
        raise ProjectionMigrationRequiredError(
            projection_migration_error(
                path,
                "Claim Registry-controlled triples appear outside the managed block: "
                + _stray_resources(inspection.stray_managed_triples),
            )
        )


def _sync_managed_surface(
    path: Path,
    *,
    managed_triples: list[tuple[URIRef, URIRef, object]],
    is_managed_authored,
) -> None:
    """Rewrite only an already-canonical managed block of *path*.

    Legacy inline controlled triples are deliberately rejected here.  They are
    converted by the explicit ``migrate`` workflow, which stages backups before
    writing, rather than being silently discarded during ordinary projection sync.
    """
    text = _read_turtle_text(path)
    authored_text = _strip_managed_block(text, path=path)

    authored_graph = Graph()
    authored_graph.parse(data=authored_text, format="turtle")
    if any(is_managed_authored(triple) for triple in authored_graph):
        stray = tuple(
            sorted(
                (triple for triple in authored_graph if is_managed_authored(triple)),
                key=str,
            )
        )
        raise ProjectionMigrationRequiredError(
            projection_migration_error(
                path,
                "Claim Registry-controlled triples appear outside the managed block: "
                + _stray_resources(stray),
            )
        )

    managed_lines = sorted(
        _turtle_statement(s, p, o) for (s, p, o) in managed_triples
    )
    path.write_bytes(
        _replace_managed_block(text, managed_lines, path=path).encode("utf-8")
    )


_PREFIX_DECLARATION = re.compile(
    r"(?im)^\s*(?:@prefix|prefix)\s+([A-Za-z_][\w.-]*):\s*<([^>]+)>\s*\.?"
)
_TURTLE_TERM = r"(?:<[^>\r\n]+>|[A-Za-z_][\w.-]*:[^\s;,.]+)"


@dataclass
class ProjectionMigrationPlan:
    """Candidate managed-block rewrites for legacy projection surfaces."""

    writes: dict[Path, str] = field(default_factory=dict)
    domains: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _prefixes_in(text: str) -> dict[str, str]:
    return {prefix: namespace for prefix, namespace in _PREFIX_DECLARATION.findall(text)}


def _term_uri(token: str | None, prefixes: dict[str, str]) -> str | None:
    """Resolve a simple IRI/prefixed Turtle term without changing source text."""
    if not token:
        return None
    token = token.strip()
    if token.startswith("<") and token.endswith(">"):
        return token[1:-1]
    if ":" not in token:
        return None
    prefix, local = token.split(":", 1)
    namespace = prefixes.get(prefix)
    return namespace + local if namespace is not None else None


def _predicate_aliases(text: str, predicate_iris: set[str]) -> dict[str, str]:
    """Return lexical predicate spellings declared by *text* for the given IRIs."""
    aliases = {f"<{iri}>": iri for iri in predicate_iris}
    for prefix, namespace in _prefixes_in(text).items():
        for iri in predicate_iris:
            if iri.startswith(namespace):
                aliases[f"{prefix}:{iri[len(namespace):]}"] = iri
    if str(OWL.imports) in predicate_iris:
        aliases.setdefault("owl:imports", str(OWL.imports))
    if str(KAIROS_EXT.silverInclude) in predicate_iris:
        aliases.setdefault("kairos-ext:silverInclude", str(KAIROS_EXT.silverInclude))
    if str(KAIROS_EXT.silverIncludeImports) in predicate_iris:
        aliases.setdefault(
            "kairos-ext:silverIncludeImports",
            str(KAIROS_EXT.silverIncludeImports),
        )
    return aliases


def _replace_preceding_semicolon(lines: list[str], index: int) -> None:
    """Turn the previous property-list semicolon into a final period."""
    for previous in range(index - 1, -1, -1):
        body = lines[previous].rstrip("\r\n")
        if not body.strip() or body.lstrip().startswith("#"):
            continue
        replaced, count = re.subn(r";([ \t]*)$", r".\1", body)
        if count:
            ending = lines[previous][len(body):]
            lines[previous] = replaced + ending
            return
        break
    raise ProjectionMigrationRequiredError(
        "Cannot safely remove a legacy managed Turtle property-list item."
    )


def _remove_inline_managed_triples(
    authored_text: str,
    *,
    predicate_iris: set[str],
    is_controlled,
) -> str:
    """Remove only controlled Turtle lines, retaining every other authored byte.

    This deliberately supports the conventional Turtle produced by prior syncs
    (standalone triples and semicolon property lists).  If a more exotic legacy
    declaration cannot be relocated without rewriting unrelated authored text, the
    caller receives a migration error instead of a lossy best-effort conversion.
    """
    prefixes = _prefixes_in(authored_text)
    aliases = _predicate_aliases(authored_text, predicate_iris)
    predicate_pattern = "|".join(
        re.escape(token) for token in sorted(aliases, key=lambda item: (-len(item), item))
    )
    line_pattern = re.compile(
        rf"^(?P<indent>[ \t]*)(?:(?P<subject>{_TURTLE_TERM})[ \t]+)?"
        rf"(?P<predicate>{predicate_pattern})[ \t]+(?P<object>.+?)(?P<delimiter>[;.])[ \t]*$"
    )
    lines = authored_text.splitlines(keepends=True)
    remove: list[tuple[int, bool, str]] = []
    current_subject: str | None = None

    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        if not body.strip() or body.lstrip().startswith("#") or body.lstrip().startswith("@"):
            continue
        match = line_pattern.match(body)
        if match:
            subject = _term_uri(match.group("subject"), prefixes) or current_subject
            predicate_iri = aliases[match.group("predicate")]
            object_uri = _term_uri(match.group("object").strip(), prefixes)
            direct_subject = match.group("subject") is not None
            if is_controlled(subject, predicate_iri, object_uri):
                remove.append((index, direct_subject, match.group("delimiter")))

        # A non-indented statement starts a new property-list subject.  Continuation
        # predicates are deliberately not mistaken for a subject.
        if not body[:1].isspace():
            first_term = re.match(rf"^\s*(?P<term>{_TURTLE_TERM})[ \t]+", body)
            if first_term and first_term.group("term") not in aliases:
                current_subject = _term_uri(first_term.group("term"), prefixes)
        if body.rstrip().endswith("."):
            current_subject = None

    for index, direct_subject, delimiter in remove:
        if delimiter == "." and not direct_subject:
            _replace_preceding_semicolon(lines, index)
        lines[index] = ""
    return "".join(lines)


def _migrate_surface_text(
    inspection: ManagedSurfaceInspection,
    *,
    path: Path,
    predicate_iris: set[str],
    is_controlled_lexical,
    is_managed_authored,
    managed_lines: list[str],
) -> str:
    """Relocate inline controlled triples into the deterministic managed block."""
    authored = inspection.authored_text
    if inspection.stray_managed_triples:
        try:
            authored = _remove_inline_managed_triples(
                authored,
                predicate_iris=predicate_iris,
                is_controlled=is_controlled_lexical,
            )
            parsed = Graph()
            parsed.parse(data=authored, format="turtle")
        except ProjectionMigrationRequiredError as exc:
            raise ProjectionMigrationRequiredError(
                projection_migration_error(path, str(exc))
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise ProjectionMigrationRequiredError(
                projection_migration_error(path, f"could not safely relocate legacy triples: {exc}")
            ) from exc
        if any(is_managed_authored(triple) for triple in parsed):
            raise ProjectionMigrationRequiredError(
                projection_migration_error(
                    path,
                    "a legacy managed Turtle declaration could not be relocated safely",
                )
            )
    return _compose_managed_file(authored, sorted(managed_lines))


def plan_legacy_projection_sync_migration(
    *,
    claims_dir: Path,
    ontologies_dir: Path,
    extensions_dir: Path,
) -> ProjectionMigrationPlan:
    """Plan explicit legacy whole-graph → managed-block conversion.

    The function only plans strings and never writes.  ``migrate`` publishes these
    candidates atomically with durable backups after all inventory and TTL inputs
    have been validated.
    """
    plan = ProjectionMigrationPlan()
    if not claims_dir.is_dir():
        return plan

    try:
        hub_domain_bases = _collect_hub_domain_bases(ontologies_dir)
    except Exception as exc:  # noqa: BLE001
        plan.errors.append(str(exc))
        return plan

    for claims_file in sorted(claims_dir.glob("*-claims.yaml")):
        domain = claims_file.name.replace("-claims.yaml", "")
        ontology_file = ontologies_dir / f"{domain}.ttl"
        extension_file = extensions_dir / f"{domain}-silver-ext.ttl"
        if not ontology_file.is_file() or not extension_file.is_file():
            continue
        try:
            registry = load_registry(claims_file)
            ontology_graph = Graph()
            ontology_graph.parse(ontology_file, format="turtle")
            ontology_subject = _ontology_subject(ontology_graph)
            if ontology_subject is None:
                raise ValueError(f"{ontology_file}: no owl:Ontology declaration found")
            ontology_iri = str(ontology_subject)
            expected_includes = _approved_imported_class_uris(registry, ontology_iri)
            expected_imports = _expected_external_imports(expected_includes)

            def is_managed_import(triple) -> bool:
                _subject, predicate, obj = triple
                return predicate == OWL.imports and str(obj).rstrip("#/") not in hub_domain_bases

            def is_managed_include(triple) -> bool:
                subject, predicate, _obj = triple
                if predicate == KAIROS_EXT.silverIncludeImports:
                    return True
                if predicate == KAIROS_EXT.silverInclude:
                    return not _is_local_class_uri(str(subject), ontology_iri)
                return False

            ontology_inspection = _inspect_managed_surface(ontology_file, is_managed_import)
            extension_inspection = _inspect_managed_surface(extension_file, is_managed_include)
            if not (
                ontology_inspection.stray_managed_triples
                or extension_inspection.stray_managed_triples
            ):
                continue

            def is_managed_import_lexical(
                _subject: str | None, predicate: str, obj: str | None
            ) -> bool:
                return (
                    predicate == str(OWL.imports)
                    and obj is not None
                    and obj.rstrip("#/") not in hub_domain_bases
                )

            def is_managed_include_lexical(
                subject: str | None, predicate: str, _obj: str | None
            ) -> bool:
                if predicate == str(KAIROS_EXT.silverIncludeImports):
                    return True
                return (
                    predicate == str(KAIROS_EXT.silverInclude)
                    and subject is not None
                    and not _is_local_class_uri(subject, ontology_iri)
                )

            import_lines = [
                _turtle_statement(ontology_subject, OWL.imports, URIRef(iri))
                for iri in sorted(expected_imports)
            ]
            include_lines = [
                _turtle_statement(
                    URIRef(class_uri),
                    KAIROS_EXT.silverInclude,
                    Literal(True, datatype=XSD.boolean),
                )
                for class_uri in sorted(expected_includes)
            ]
            plan.writes[ontology_file] = _migrate_surface_text(
                ontology_inspection,
                path=ontology_file,
                predicate_iris={str(OWL.imports)},
                is_controlled_lexical=is_managed_import_lexical,
                is_managed_authored=is_managed_import,
                managed_lines=import_lines,
            )
            plan.writes[extension_file] = _migrate_surface_text(
                extension_inspection,
                path=extension_file,
                predicate_iris={
                    str(KAIROS_EXT.silverInclude),
                    str(KAIROS_EXT.silverIncludeImports),
                },
                is_controlled_lexical=is_managed_include_lexical,
                is_managed_authored=is_managed_include,
                managed_lines=include_lines,
            )
            plan.domains.append(domain)
        except Exception as exc:  # noqa: BLE001
            plan.errors.append(str(exc))

    return plan


def _rewrite_domain_projection_surfaces(
    *,
    domain: str,
    claims_file: Path,
    ontology_file: Path,
    extension_file: Path,
    hub_domain_bases: set[str],
    module_context: ReferenceModuleContext | None = None,
) -> None:
    registry = (
        load_registry(claims_file)
        if claims_file.exists()
        else ClaimRegistry(domain=domain)
    )
    ontology_graph = Graph()
    ontology_graph.parse(ontology_file, format="turtle")

    ontology_subj = _ontology_subject(ontology_graph)
    if ontology_subj is None:
        raise ValueError(f"{ontology_file}: no owl:Ontology declaration found")
    ontology_iri = str(ontology_subj)
    authored_text, _has_block = _split_managed_block(
        _read_turtle_text(ontology_file),
        path=ontology_file,
    )
    authored_graph = Graph()
    authored_graph.parse(data=authored_text, format="turtle")
    plan = build_managed_import_plan(
        registry,
        domain=domain,
        context=module_context,
        authored_ontology_graph=authored_graph,
        local_ontology_iri=ontology_iri,
    )
    expected_includes = {
        uri
        for uri in plan.selected_class_uris
        if not _is_local_class_uri(uri, ontology_iri)
    }
    expected_imports = set(plan.expected_imports)

    # Ontology owl:imports (A1): managed = external (non-hub-base) imports driven by
    # approved imported claims. Intra-hub bases (_foundation/_master) stay authored.
    authored_imports = {
        str(value).rstrip("#")
        for value in authored_graph.objects(ontology_subj, OWL.imports)
    }
    import_triples: list[tuple[URIRef, URIRef, object]] = [
        (ontology_subj, OWL.imports, URIRef(iri))
        for iri in sorted(expected_imports - authored_imports)
    ]

    def _is_managed_import(triple) -> bool:
        _s, p, o = triple
        iri = str(o).rstrip("#")
        return (
            p == OWL.imports
            and iri.rstrip("/") not in hub_domain_bases
            and iri in expected_imports
        )

    _sync_managed_surface(
        ontology_file,
        managed_triples=import_triples,
        is_managed_authored=_is_managed_import,
    )

    # Silver extension silverInclude: managed = imported (non-local) class includes.
    # The bulk silverIncludeImports flag is forbidden (A1) and stripped if authored.
    include_triples: list[tuple[URIRef, URIRef, object]] = [
        (URIRef(class_uri), KAIROS_EXT.silverInclude, Literal(True, datatype=XSD.boolean))
        for class_uri in sorted(expected_includes)
    ]

    def _is_managed_include(triple) -> bool:
        s, p, _o = triple
        if p == KAIROS_EXT.silverIncludeImports:
            return True
        if p == KAIROS_EXT.silverInclude:
            return not _is_local_class_uri(str(s), ontology_iri)
        return False

    _sync_managed_surface(
        extension_file,
        managed_triples=include_triples,
        is_managed_authored=_is_managed_include,
    )


def _infer_hub_base(ontologies_dir: Path) -> str:
    """Infer the hub's ontology base namespace from existing domain ontologies.

    Takes any existing ``owl:Ontology`` IRI under *ontologies_dir* and strips its
    last path segment to get the shared base (e.g. ``https://acme.com/ont/_foundation``
    → ``https://acme.com/ont``). Falls back to a clearly-placeholder base when the
    directory holds no ontologies yet, so a brand-new hub still produces valid TTL.
    """
    bases = _collect_hub_domain_bases(ontologies_dir)
    for iri in sorted(bases):
        trimmed = iri.rstrip("#/")
        if "/" in trimmed:
            return trimmed.rsplit("/", 1)[0]
    return "https://example.org/ont"


def _domain_iri_for(domain: str, ontologies_dir: Path) -> str:
    return f"{_infer_hub_base(ontologies_dir)}/{domain}"


#: Provenance header prepended to scaffolded skeletons (DD-072). Authored content
#: (local subclasses, gap properties, labels) belongs below it; the managed
#: ``owl:imports`` / ``silverInclude`` triples are synced from the Claim Registry.
_SCAFFOLD_HEADER = (
    "# ---------------------------------------------------------------------------\n"
    "# Skeleton scaffolded by `kairos-ontology claims-to-silver-ext` (DD-072).\n"
    "# Managed surfaces (owl:imports / kairos-ext:silverInclude) are synced from the\n"
    "# Claim Registry. Add local subclasses, gap properties, labels and comments\n"
    "# below — authored content is yours to maintain.\n"
    "# ---------------------------------------------------------------------------\n"
)


def _write_with_header(graph: Graph, destination: Path) -> None:
    body = graph.serialize(format="turtle")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(_SCAFFOLD_HEADER + "\n" + body, encoding="utf-8")


class ScaffoldMetadataError(ValueError):
    """Raised when generated skeleton content would fail the baseline ontology
    metadata checks required of hand-authored ontologies (see
    ``kairos-execute-validate`` Level 3: ``owl:Ontology`` + ``rdfs:label`` +
    ``rdfs:comment`` + ``owl:versionInfo``)."""


#: Lowercase-hyphen domain identifiers only (matches the documented hub
#: convention: "Filename = domain identifier (lowercase, hyphens for
#: multi-word)"). Rejecting anything else here — rather than writing an
#: ontology with an unusable IRI/filename — is cheap, deterministic, up-front
#: validation of candidate content before any write is attempted.
_DOMAIN_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def _validate_domain_slug(domain: str) -> None:
    """Validate candidate content before writing: reject an unusable domain name."""
    if not _DOMAIN_SLUG_RE.match(domain):
        raise ValueError(
            f"invalid domain identifier {domain!r}: expected lowercase letters, "
            "digits and hyphens only (e.g. 'customer', 'order-line')."
        )


def _validate_generated_metadata(graph: Graph, subject: URIRef, *, path: Path) -> None:
    """Enforce, on the in-memory candidate graph, the same ontology-level metadata
    baseline required of hand-authored files: exactly the given ``owl:Ontology``
    subject with an ``https://`` IRI, ``rdfs:label``, ``rdfs:comment`` and
    ``owl:versionInfo``. Raised *before* anything is written to disk.
    """
    if not str(subject).startswith("https://"):
        raise ScaffoldMetadataError(f"{path}: ontology IRI must use https:// — got {subject}")
    missing = [
        name
        for name, predicate in (
            ("rdfs:label", RDFS.label),
            ("rdfs:comment", RDFS.comment),
            ("owl:versionInfo", OWL.versionInfo),
        )
        if graph.value(subject, predicate) is None
    ]
    if missing:
        raise ScaffoldMetadataError(
            f"{path}: generated skeleton is missing required metadata: {', '.join(missing)}"
        )
    # Round-trip through Turtle before writing — a cheap, generic syntax check
    # that also catches any accidental non-Turtle-safe literal content.
    Graph().parse(data=graph.serialize(format="turtle"), format="turtle")


def _scaffold_ontology_skeleton(
    *, domain: str, ontology_file: Path, ontologies_dir: Path
) -> str:
    """Create a minimal valid domain ontology skeleton and return its IRI.

    Meets the same baseline metadata checks required of hand-authored ontologies
    (``owl:Ontology`` + ``rdfs:label`` + ``rdfs:comment`` + ``owl:versionInfo``),
    plus the hub's foundation import when one is available. Validated before
    the file is written (see :func:`_validate_generated_metadata`).
    """
    _validate_domain_slug(domain)
    domain_iri = _domain_iri_for(domain, ontologies_dir)
    label = domain.replace("-", " ").replace("_", " ").title()
    subj = URIRef(domain_iri)
    graph = Graph()
    graph.bind("", Namespace(domain_iri.rstrip("#/") + "#"))
    graph.bind("owl", OWL)
    graph.bind("rdfs", RDFS)
    graph.add((subj, RDF.type, OWL.Ontology))
    graph.add((subj, RDFS.label, Literal(label, lang="en")))
    graph.add((subj, RDFS.comment, Literal(f"Ontology for the {label} domain.", lang="en")))
    graph.add((subj, OWL.versionInfo, Literal("0.1.0")))
    # Share the hub foundation base when one is present (required-import convention).
    for base in _collect_hub_domain_bases(ontologies_dir):
        if base.rstrip("#/").rsplit("/", 1)[-1].startswith("_foundation"):
            graph.add((subj, OWL.imports, URIRef(base)))
            break
    _validate_generated_metadata(graph, subj, path=ontology_file)
    _write_with_header(graph, ontology_file)
    return domain_iri


def _scaffold_extension_skeleton(
    *, domain: str, extension_file: Path, domain_iri: str
) -> None:
    """Create a minimal valid silver-extension skeleton for *domain*.

    Meets the same ontology-level metadata baseline as the domain skeleton
    itself, so a freshly scaffolded extension file passes the same checks a
    hand-authored one would. Validated before the file is written.
    """
    label = domain.replace("-", " ").replace("_", " ").title()
    ext_iri = domain_iri.rstrip("#/") + "-ext"
    subj = URIRef(ext_iri)
    graph = Graph()
    graph.bind("", Namespace(domain_iri.rstrip("#/") + "#"))
    graph.bind("kairos-ext", KAIROS_EXT)
    graph.bind("owl", OWL)
    graph.bind("rdfs", RDFS)
    graph.add((subj, RDF.type, OWL.Ontology))
    graph.add((subj, RDFS.label, Literal(f"{label} Silver Extension", lang="en")))
    graph.add(
        (
            subj,
            RDFS.comment,
            Literal(f"Silver-layer projection annotations for the {label} domain.", lang="en"),
        )
    )
    graph.add((subj, OWL.versionInfo, Literal("0.1.0")))
    _validate_generated_metadata(graph, subj, path=extension_file)
    _write_with_header(graph, extension_file)


#: Managed-block markers for the master ontology's domain registration (distinct
#: sentinel text from the Claim Registry import/include markers above — a
#: separate file, a separate managed concern). Same DD-083 mechanics: the block
#: is regenerated wholesale from every domain this workflow knows about, so
#: registration self-heals/converges on every run without ever touching
#: authored content outside it.
_MASTER_IMPORT_BEGIN = "# >>> kairos-managed (generated domain registration — do not edit)"
_MASTER_IMPORT_END = "# <<< kairos-managed"

#: Markdown table header this workflow recognizes as the README's domain table
#: (see ``ontology-hub/README.md.template``'s "Domain model overview" section).
_README_TABLE_HEADER = re.compile(
    r"^\|\s*Domain\s*\|\s*Description\s*\|\s*File\s*\|\s*Status\s*\|\s*$"
)
_README_PLACEHOLDER_CELL = "*(add domains here)*"


def _sync_master_registration(
    *, master_file: Path, ready_domains: list[tuple[str, str]]
) -> tuple[str, list[str]]:
    """Converge ``_master.ttl``'s managed ``owl:imports`` block with every domain
    this run knows about. Returns ``(status, warnings)`` where ``status`` is one
    of ``"updated"``, ``"unchanged"``, or ``"skipped"``.

    Registration is only this workflow's to converge when ``_master.ttl``
    already exists and is well-formed: a hub that never created one (or whose
    markers are malformed) is left entirely alone, with a warning explaining
    why — this workflow never creates or repairs ``_master.ttl`` itself.
    """
    if not ready_domains or not master_file.exists():
        return "skipped", []
    try:
        text = master_file.read_bytes().decode("utf-8")
        graph = Graph()
        graph.parse(master_file, format="turtle")
    except Exception as exc:  # noqa: BLE001 - report and skip, never crash the run
        return "skipped", [
            f"{master_file}: could not parse — domain registration skipped ({exc})."
        ]
    master_subj = _ontology_subject(graph)
    if master_subj is None:
        return "skipped", [
            f"{master_file}: no owl:Ontology subject found — domain registration skipped."
        ]

    managed_lines = [
        _turtle_statement(master_subj, OWL.imports, URIRef(domain_iri))
        for _domain, domain_iri in sorted(ready_domains)
    ]
    try:
        new_text = replace_managed_block(
            text,
            managed_lines,
            begin_marker=_MASTER_IMPORT_BEGIN,
            end_marker=_MASTER_IMPORT_END,
            label=str(master_file),
        )
    except ManagedBlockError as exc:
        return "skipped", [
            f"{exc} Fix the markers by hand before domain registration can converge."
        ]
    if new_text == text:
        return "unchanged", []
    master_file.write_bytes(new_text.encode("utf-8"))
    return "updated", []


def _update_readme_domain_table_row(
    text: str, *, domain: str, relative_ontology_path: str
) -> tuple[str, str]:
    """Ensure a domain-table row exists for *domain*; return ``(new_text, status)``.

    ``status`` is ``"updated"`` (a row was inserted), ``"unchanged"`` (a row
    already exists, or no such table was found in *text*). An existing row is
    never rewritten — authored Description/Status edits are preserved verbatim
    — and everything outside the table body is untouched byte-for-byte.
    """
    lines = text.splitlines(keepends=True)
    header_idx = next(
        (i for i, line in enumerate(lines) if _README_TABLE_HEADER.match(line.rstrip("\r\n"))),
        None,
    )
    if header_idx is None or header_idx + 1 >= len(lines):
        return text, "unchanged"
    separator_idx = header_idx + 1
    if not lines[separator_idx].lstrip().startswith("|"):
        return text, "unchanged"

    rows_start = separator_idx + 1
    rows_end = rows_start
    while rows_end < len(lines) and lines[rows_end].lstrip().startswith("|"):
        rows_end += 1
    row_lines = lines[rows_start:rows_end]

    file_marker = f"`{relative_ontology_path}`"
    for row in row_lines:
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        if cells[2] in (file_marker, relative_ontology_path):
            return text, "unchanged"
        if cells[0].strip("`* ").casefold() == domain.casefold():
            return text, "unchanged"

    # Drop the sole scaffold placeholder row when adding the first real domain.
    filtered_rows = [row for row in row_lines if _README_PLACEHOLDER_CELL not in row]

    newline = _line_ending(text)
    new_row = f"| {domain} | | {file_marker} | Scaffolded |{newline}"
    filtered_rows.append(new_row)

    new_text = "".join(lines[:rows_start] + filtered_rows + lines[rows_end:])
    return new_text, "updated"


def _sync_readme_domain_table(
    *, readme_file: Path, ready_domains: list[tuple[str, str]]
) -> tuple[str, list[str]]:
    """Ensure the README's "Domain model overview" table lists every domain this
    run knows about. Returns ``(status, warnings)``; never creates the README
    or the table itself — only converges rows within an existing table.
    """
    if not ready_domains or not readme_file.exists():
        return "skipped", []
    try:
        text = readme_file.read_bytes().decode("utf-8")
    except OSError as exc:
        return "skipped", [f"{readme_file}: could not read — domain table update skipped ({exc})."]

    changed = False
    for domain, _domain_iri in sorted(ready_domains):
        relative_path = f"model/ontologies/{domain}.ttl"
        new_text, status = _update_readme_domain_table_row(
            text, domain=domain, relative_ontology_path=relative_path
        )
        if status == "updated":
            text = new_text
            changed = True

    if not changed:
        header_present = any(
            _README_TABLE_HEADER.match(line.rstrip("\r\n")) for line in text.splitlines()
        )
        if not header_present:
            return "skipped", [
                f"{readme_file}: no 'Domain model overview' table found — "
                "README convergence skipped for this run."
            ]
        return "unchanged", []
    readme_file.write_bytes(text.encode("utf-8"))
    return "updated", []


@dataclass(frozen=True)
class ScaffoldSurfacesResult:
    """Explicit, auditable accounting of one :func:`scaffold_missing_surfaces` run.

    No step here claims rollback atomicity: every path already written before a
    later failure remains on disk exactly as written. ``errors`` names the
    domains that did not complete; ``created`` / ``updated`` / ``unchanged``
    reflect real, current on-disk state for everything this run considered.
    """

    created: tuple[Path, ...] = ()
    updated: tuple[Path, ...] = ()
    unchanged: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def counts(self) -> dict[str, int]:
        return {
            "created": len(self.created),
            "updated": len(self.updated),
            "unchanged": len(self.unchanged),
        }

    def describe(self) -> list[str]:
        """Human-readable lines: paths by bucket, a managed-vs-authored
        explanation, and a git-status hint for newly created (untracked) paths.
        """
        lines = [
            f"Scaffold summary: {len(self.created)} created, "
            f"{len(self.updated)} updated, {len(self.unchanged)} unchanged."
        ]
        for bucket, paths in (
            ("created", self.created),
            ("updated", self.updated),
            ("unchanged", self.unchanged),
        ):
            for path in paths:
                lines.append(f"  [{bucket}] {path}")
        if self.created:
            lines.append(
                "New files are untracked in git — run `git status` "
                "(or `git add <path>`) before committing."
            )
        lines.append(
            "Managed regions (delimited by `# >>> kairos-managed ... # <<< kairos-managed`) "
            "are regenerated wholesale and are safe to overwrite; everything else in every "
            "file listed above is authored content and is preserved verbatim."
        )
        for warning in self.warnings:
            lines.append(f"  ⚠ {warning}")
        for error in self.errors:
            lines.append(f"  ❌ {error}")
        return lines


class ScaffoldPartialFailureError(RuntimeError):
    """Raised when one or more domains failed to scaffold.

    No rollback is performed: ``result`` reflects exactly what was created,
    updated, or left unchanged — including for domains that succeeded — around
    the failure(s) named in ``result.errors``.
    """

    def __init__(self, message: str, result: ScaffoldSurfacesResult):
        super().__init__(message)
        self.result = result


def scaffold_missing_surfaces(
    *,
    claims_dir: Path,
    ontologies_dir: Path,
    extensions_dir: Path,
    domains_filter: list[str] | None = None,
    module_context: ReferenceModuleContext | None = None,
) -> ScaffoldSurfacesResult:
    """Create skeleton ``{domain}.ttl`` / ``{domain}-silver-ext.ttl`` files when
    absent, then convergently update ``_master.ttl``'s domain registration and
    the README domain table for every domain this run knows about.

    ``claims-to-silver-ext`` is a generator: rather than silently skipping a domain
    whose authored surfaces don't exist yet (issue #190 item 5), bootstrap a minimal,
    valid skeleton so the sync can proceed. Existing ``{domain}.ttl`` /
    ``*-silver-ext.ttl`` files are never touched.

    Each domain is scaffolded independently: an invalid domain name or a write
    failure for one domain is recorded in the returned result's ``errors`` and
    does not prevent the others from being scaffolded, nor does it undo files
    already written for them (no rollback atomicity). If any domain failed,
    :class:`ScaffoldPartialFailureError` is raised at the end carrying the full
    :class:`ScaffoldSurfacesResult` computed so far. The ``_master.ttl`` /
    README convergence steps are best-effort and non-fatal — any issue there is
    reported as a warning rather than blocking the run.
    """
    created: list[Path] = []
    updated: list[Path] = []
    unchanged: list[Path] = []
    warnings: list[str] = []
    errors: list[str] = []

    lowers = [d.lower() for d in domains_filter] if domains_filter else None

    def _in_scope(name: str) -> bool:
        if lowers is None:
            return True
        return any(token in name.lower() for token in lowers)

    domains = {
        path.name.replace("-claims.yaml", "")
        for path in claims_dir.glob("*-claims.yaml")
    } if claims_dir.is_dir() else set()
    if module_context:
        domains.update(item.domain for item in module_context.config.domains)

    ready_domains: list[tuple[str, str]] = []
    for domain in sorted(domains):
        if not _in_scope(domain):
            continue
        ontology_file = ontologies_dir / f"{domain}.ttl"
        extension_file = extensions_dir / f"{domain}-silver-ext.ttl"
        try:
            if not ontology_file.exists():
                domain_iri = _scaffold_ontology_skeleton(
                    domain=domain, ontology_file=ontology_file, ontologies_dir=ontologies_dir
                )
                created.append(ontology_file)
            else:
                domain_iri = _domain_iri_for(domain, ontologies_dir)
                unchanged.append(ontology_file)
            if not extension_file.exists():
                _scaffold_extension_skeleton(
                    domain=domain, extension_file=extension_file, domain_iri=domain_iri
                )
                created.append(extension_file)
            else:
                unchanged.append(extension_file)
        except (ValueError, OSError) as exc:
            errors.append(f"{domain}: {exc}")
            continue
        ready_domains.append((domain, domain_iri))

    master_file = ontologies_dir / "_master.ttl"
    master_status, master_warnings = _sync_master_registration(
        master_file=master_file, ready_domains=ready_domains
    )
    warnings.extend(master_warnings)
    if master_status == "updated":
        updated.append(master_file)
    elif master_status == "unchanged":
        unchanged.append(master_file)

    readme_file = ontologies_dir.parent.parent / "README.md"
    readme_status, readme_warnings = _sync_readme_domain_table(
        readme_file=readme_file, ready_domains=ready_domains
    )
    warnings.extend(readme_warnings)
    if readme_status == "updated":
        updated.append(readme_file)
    elif readme_status == "unchanged":
        unchanged.append(readme_file)

    result = ScaffoldSurfacesResult(
        created=tuple(created),
        updated=tuple(updated),
        unchanged=tuple(unchanged),
        warnings=tuple(warnings),
        errors=tuple(errors),
    )
    if errors:
        raise ScaffoldPartialFailureError(
            f"{len(errors)} of {len(ready_domains) + len(errors)} domain(s) failed to "
            "scaffold; files already written for other domains were not rolled back.",
            result,
        )
    return result


def apply_projection_sync(
    *,
    claims_dir: Path,
    ontologies_dir: Path,
    extensions_dir: Path,
    domains_filter: list[str] | None = None,
    scaffold_missing: bool = True,
    ref_models_dir: Path | None = None,
    catalog_path: Path | None = None,
    accelerator: str | None = None,
    module_context: ReferenceModuleContext | None = None,
) -> ProjectionSyncReport:
    if module_context is None:
        scoped_domains, claimed_terms, imported_iris = _module_scope_evidence(
            claims_dir=claims_dir,
            ontologies_dir=ontologies_dir,
            domains_filter=domains_filter,
        )
        module_context = build_reference_module_context(
            ref_models_dir,
            catalog_path=catalog_path,
            accelerator=accelerator,
            requested_domains=scoped_domains if domains_filter else None,
            claimed_term_uris=claimed_terms,
            imported_ontology_iris=imported_iris,
        )
    scaffold_result = None
    if scaffold_missing:
        scaffold_result = scaffold_missing_surfaces(
            claims_dir=claims_dir,
            ontologies_dir=ontologies_dir,
            extensions_dir=extensions_dir,
            domains_filter=domains_filter,
            module_context=module_context,
        )
    report = evaluate_projection_sync(
        claims_dir=claims_dir,
        ontologies_dir=ontologies_dir,
        extensions_dir=extensions_dir,
        domains_filter=domains_filter,
        module_context=module_context,
    )
    hub_domain_bases = _collect_hub_domain_bases(ontologies_dir)
    for status in report.out_of_sync:
        if status.error is not None:
            continue
        _rewrite_domain_projection_surfaces(
            domain=status.domain,
            claims_file=status.claims_file,
            ontology_file=status.ontology_file,
            extension_file=status.extension_file,
            hub_domain_bases=hub_domain_bases,
            module_context=module_context,
        )
    final_report = evaluate_projection_sync(
        claims_dir=claims_dir,
        ontologies_dir=ontologies_dir,
        extensions_dir=extensions_dir,
        domains_filter=domains_filter,
        module_context=module_context,
    )
    final_report.scaffold_result = scaffold_result
    return final_report
