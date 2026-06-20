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

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, XSD
from rdflib.plugins.parsers.notation3 import BadSyntax

from .claim_registry import load_registry
from .projections.shared import KAIROS_EXT


def _truthy(value: object) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes"}


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
    uris: set[str] = set()
    for claim in registry.claims:
        if claim.status != "approved":
            continue
        if claim.origin != "imported":
            continue
        if claim.disposition not in {"claim", "specialize"}:
            continue
        if not claim.class_uri:
            continue
        if _is_local_class_uri(claim.class_uri, ontology_iri):
            continue
        uris.add(claim.class_uri)
    return uris


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
            and not self.has_bulk_include_imports
        )


@dataclass
class ProjectionSyncReport:
    domains: list[DomainProjectionSync] = field(default_factory=list)

    @property
    def out_of_sync(self) -> list[DomainProjectionSync]:
        return [d for d in self.domains if not d.in_sync]

    @property
    def is_blocking(self) -> bool:
        return bool(self.out_of_sync)


def evaluate_domain_projection_sync(
    *,
    domain: str,
    claims_file: Path,
    ontology_file: Path,
    extension_file: Path,
    hub_domain_bases: set[str],
) -> DomainProjectionSync:
    status = DomainProjectionSync(
        domain=domain,
        claims_file=claims_file,
        ontology_file=ontology_file,
        extension_file=extension_file,
    )

    if not claims_file.exists():
        status.error = f"missing claims file: {claims_file}"
        return status
    if not ontology_file.exists():
        status.error = f"missing ontology file: {ontology_file}"
        return status
    if not extension_file.exists():
        status.error = f"missing extension file: {extension_file}"
        return status

    try:
        registry = load_registry(claims_file)
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

    expected_includes = _approved_imported_class_uris(registry, ontology_iri)
    expected_imports = _expected_external_imports(expected_includes)

    actual_imports: set[str] = set()
    for obj in ontology_graph.objects(ontology_subj, OWL.imports):
        iri = str(obj).rstrip("#/")
        # Intra-hub shared bases (e.g. _foundation/_master) are neither required
        # nor "extra" — skip them so they aren't flagged/stripped (issue #190). But
        # if a base is *also* a claim-driven expected import, it must still count as
        # a satisfied import rather than being silently dropped.
        if iri in hub_domain_bases and iri not in expected_imports:
            continue
        actual_imports.add(iri)

    actual_includes: set[str] = set()
    for subj in ext_graph.subjects(KAIROS_EXT.silverInclude, None):
        subj_iri = str(subj)
        if _is_local_class_uri(subj_iri, ontology_iri):
            continue
        if _truthy(ext_graph.value(subj, KAIROS_EXT.silverInclude)):
            actual_includes.add(subj_iri)

    bulk_subj = URIRef(ontology_iri.rstrip("#/"))
    status.has_bulk_include_imports = _truthy(ext_graph.value(bulk_subj, KAIROS_EXT.silverIncludeImports))

    status.missing_imports = sorted(expected_imports - actual_imports)
    status.extra_imports = sorted(actual_imports - expected_imports)
    status.missing_includes = sorted(expected_includes - actual_includes)
    status.extra_includes = sorted(actual_includes - expected_includes)
    return status


def evaluate_projection_sync(
    *,
    claims_dir: Path,
    ontologies_dir: Path,
    extensions_dir: Path,
    domains_filter: list[str] | None = None,
) -> ProjectionSyncReport:
    report = ProjectionSyncReport()
    if not claims_dir.is_dir():
        return report

    lowers = [d.lower() for d in domains_filter] if domains_filter else None

    def _in_scope(name: str) -> bool:
        if lowers is None:
            return True
        return any(token in name.lower() for token in lowers)

    hub_domain_bases = _collect_hub_domain_bases(ontologies_dir)

    for claims_file in sorted(claims_dir.glob("*-claims.yaml")):
        domain = claims_file.name.replace("-claims.yaml", "")
        if not _in_scope(domain):
            continue
        ontology_file = ontologies_dir / f"{domain}.ttl"
        extension_file = extensions_dir / f"{domain}-silver-ext.ttl"
        report.domains.append(
            evaluate_domain_projection_sync(
                domain=domain,
                claims_file=claims_file,
                ontology_file=ontology_file,
                extension_file=extension_file,
                hub_domain_bases=hub_domain_bases,
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


def _strip_managed_block(text: str) -> str:
    """Return *text* with the managed block (and its markers) removed."""
    begin = text.find(_MANAGED_BEGIN)
    if begin == -1:
        return text
    end = text.find(_MANAGED_END, begin)
    if end == -1:
        # Malformed/truncated block: drop everything from the begin marker on.
        return text[:begin]
    end_full = end + len(_MANAGED_END)
    if end_full < len(text) and text[end_full] == "\n":
        end_full += 1
    return text[:begin] + text[end_full:]


def _leading_comment_lines(text: str) -> str:
    """Capture the leading blank/comment lines (e.g. the provenance header)."""
    out: list[str] = []
    for line in text.splitlines():
        if line.strip() == "" or line.lstrip().startswith("#"):
            out.append(line)
        else:
            break
    return "\n".join(out).strip("\n")


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
    """Stitch preserved *authored_text* with a freshly rendered managed block."""
    authored = authored_text.strip("\n")
    parts = [authored] if authored else []
    if managed_lines:
        block = _MANAGED_BEGIN + "\n" + "\n".join(managed_lines) + "\n" + _MANAGED_END
        parts.append(block)
    return ("\n\n".join(parts) + "\n") if parts else ""


def _sync_managed_surface(
    path: Path,
    *,
    managed_triples: list[tuple[URIRef, URIRef, object]],
    is_managed_authored,
) -> None:
    """Rewrite only the managed block of *path*, preserving authored content (#191).

    Steady-state files (managed triples already confined to the block) keep their
    authored region byte-for-byte. Legacy files written by the pre-#191 whole-graph
    serializer may carry managed triples inline in the authored region; those are
    stripped one time (such files have no authored comments to lose, having already
    been re-serialized), preserving any leading provenance header.
    """
    text = path.read_text(encoding="utf-8")
    authored_text = _strip_managed_block(text)

    authored_graph = Graph()
    authored_graph.parse(data=authored_text, format="turtle")
    stray = [t for t in authored_graph if is_managed_authored(t)]
    if stray:
        leading = _leading_comment_lines(authored_text)
        for triple in stray:
            authored_graph.remove(triple)
        serialized = authored_graph.serialize(format="turtle")
        authored_text = f"{leading}\n\n{serialized}" if leading else serialized

    managed_lines = sorted(
        _turtle_statement(s, p, o) for (s, p, o) in managed_triples
    )
    path.write_text(_compose_managed_file(authored_text, managed_lines), encoding="utf-8")


def _rewrite_domain_projection_surfaces(
    *,
    claims_file: Path,
    ontology_file: Path,
    extension_file: Path,
    hub_domain_bases: set[str],
) -> None:
    registry = load_registry(claims_file)
    ontology_graph = Graph()
    ontology_graph.parse(ontology_file, format="turtle")

    ontology_subj = _ontology_subject(ontology_graph)
    if ontology_subj is None:
        raise ValueError(f"{ontology_file}: no owl:Ontology declaration found")
    ontology_iri = str(ontology_subj)
    expected_includes = _approved_imported_class_uris(registry, ontology_iri)
    expected_imports = _expected_external_imports(expected_includes)

    # Ontology owl:imports (A1): managed = external (non-hub-base) imports driven by
    # approved imported claims. Intra-hub bases (_foundation/_master) stay authored.
    import_triples: list[tuple[URIRef, URIRef, object]] = [
        (ontology_subj, OWL.imports, URIRef(iri)) for iri in sorted(expected_imports)
    ]

    def _is_managed_import(triple) -> bool:
        _s, p, o = triple
        return p == OWL.imports and str(o).rstrip("#/") not in hub_domain_bases

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


def _scaffold_ontology_skeleton(
    *, domain: str, ontology_file: Path, ontologies_dir: Path
) -> str:
    """Create a minimal valid domain ontology skeleton and return its IRI."""
    from rdflib.namespace import RDFS

    domain_iri = _domain_iri_for(domain, ontologies_dir)
    graph = Graph()
    subj = URIRef(domain_iri)
    graph.add((subj, RDF.type, OWL.Ontology))
    graph.add((subj, RDFS.label, Literal(domain.replace("-", " ").title(), lang="en")))
    # Share the hub foundation base when one is present (scaffold convention).
    for base in _collect_hub_domain_bases(ontologies_dir):
        if base.rstrip("#/").rsplit("/", 1)[-1].startswith("_foundation"):
            graph.add((subj, OWL.imports, URIRef(base)))
            break
    _write_with_header(graph, ontology_file)
    return domain_iri


def _scaffold_extension_skeleton(
    *, domain: str, extension_file: Path, domain_iri: str
) -> None:
    """Create a minimal valid silver-extension skeleton for *domain*."""
    graph = Graph()
    graph.add((URIRef(domain_iri.rstrip("#/") + "-ext"), RDF.type, OWL.Ontology))
    _write_with_header(graph, extension_file)


def scaffold_missing_surfaces(
    *,
    claims_dir: Path,
    ontologies_dir: Path,
    extensions_dir: Path,
    domains_filter: list[str] | None = None,
) -> list[Path]:
    """Create skeleton ``{domain}.ttl`` / ``{domain}-silver-ext.ttl`` files when absent.

    ``claims-to-silver-ext`` is a generator: rather than silently skipping a domain
    whose authored surfaces don't exist yet (issue #190 item 5), bootstrap a minimal,
    valid skeleton so the sync can proceed. Existing files are never touched.
    Returns the list of files created.
    """
    created: list[Path] = []
    if not claims_dir.is_dir():
        return created

    lowers = [d.lower() for d in domains_filter] if domains_filter else None

    def _in_scope(name: str) -> bool:
        if lowers is None:
            return True
        return any(token in name.lower() for token in lowers)

    for claims_file in sorted(claims_dir.glob("*-claims.yaml")):
        domain = claims_file.name.replace("-claims.yaml", "")
        if not _in_scope(domain):
            continue
        ontology_file = ontologies_dir / f"{domain}.ttl"
        extension_file = extensions_dir / f"{domain}-silver-ext.ttl"
        if not ontology_file.exists():
            domain_iri = _scaffold_ontology_skeleton(
                domain=domain, ontology_file=ontology_file, ontologies_dir=ontologies_dir
            )
            created.append(ontology_file)
        else:
            domain_iri = _domain_iri_for(domain, ontologies_dir)
        if not extension_file.exists():
            _scaffold_extension_skeleton(
                domain=domain, extension_file=extension_file, domain_iri=domain_iri
            )
            created.append(extension_file)
    return created


def apply_projection_sync(
    *,
    claims_dir: Path,
    ontologies_dir: Path,
    extensions_dir: Path,
    domains_filter: list[str] | None = None,
    scaffold_missing: bool = True,
) -> ProjectionSyncReport:
    if scaffold_missing:
        scaffold_missing_surfaces(
            claims_dir=claims_dir,
            ontologies_dir=ontologies_dir,
            extensions_dir=extensions_dir,
            domains_filter=domains_filter,
        )
    report = evaluate_projection_sync(
        claims_dir=claims_dir,
        ontologies_dir=ontologies_dir,
        extensions_dir=extensions_dir,
        domains_filter=domains_filter,
    )
    hub_domain_bases = _collect_hub_domain_bases(ontologies_dir)
    for status in report.out_of_sync:
        if status.error is not None:
            continue
        _rewrite_domain_projection_surfaces(
            claims_file=status.claims_file,
            ontology_file=status.ontology_file,
            extension_file=status.extension_file,
            hub_domain_bases=hub_domain_bases,
        )
    return evaluate_projection_sync(
        claims_dir=claims_dir,
        ontologies_dir=ontologies_dir,
        extensions_dir=extensions_dir,
        domains_filter=domains_filter,
    )
