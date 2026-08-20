# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""LLM-powered source-to-domain affinity analysis.

Matches source vocabulary tables against reference model domains using
the configured AI provider. Produces per-source affinity reports that the
modeling skill uses to scope context and seed evidence tables.

Requires an AI provider configuration (GITHUB_TOKEN or AZURE_AI_ENDPOINT).
"""

from __future__ import annotations

import json
import logging
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef

from ._concurrency import call_with_backoff, map_concurrent, DEFAULT_MAX_WORKERS
from .ontology_loader import stable_value
from ._cache import SidecarCache, compute_entry_hash, open_cache
from .source_catalog import build_source_catalog
from .ai_provider import (
    ROLE_ALIGNMENT,
    create_chat_completion,
    resolve_ai_seed,
    resolve_reasoning_effort,
    sanitize_provider_error,
)
from .generation_outcome import (
    OUTCOME_PROVIDER_FAILURE,
    OUTCOME_SEMANTIC_SUCCESS,
    OUTCOME_UNRESOLVED_ANSWER,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "gpt-5.4-mini"

KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")

# Maximum number of reference/module class labels surfaced per candidate domain
# in the single-call classification prompt. The full owl:imports closure (incl.
# FIBO) is intentionally NOT expanded — only the directly-imported module classes
# are summarised, capped here to keep the prompt bounded.
MAX_DOMAIN_CLASSES = 18

# Maximum number of secondary (non-primary) domains retained per table.
MAX_SECONDARY_DOMAINS = 2

# Deterministic fallback domain ids, in priority order, used when the model
# returns an id that is not among the candidate domains. The first id that is
# present in the candidate set is chosen; if none is present the table is left
# ``unclassified``.
FALLBACK_DOMAIN_IDS = ["mdm", "reference-data"]

# Sample evidence is advisory: source analysis may continue without samples, but
# low coverage should be visible because values often disambiguate weak schemas.
LOW_SAMPLE_COVERAGE_THRESHOLD = 0.5

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TableAssignment:
    """Table-centric classification result.

    Each source table is assigned to exactly ONE primary data domain, with
    optional secondary domains. URIs and group are resolved server-side from the
    chosen candidate domain.
    """

    table: str
    total_columns: int
    domain: str
    domain_group: str = ""
    domain_uris: list[str] = field(default_factory=list)
    confidence: float | None = 0.0
    likely_entity: str = ""
    rationale: str = ""
    indicative_columns: list[str] = field(default_factory=list)
    # Each entry: {"domain", "domain_group", "domain_uris"}
    secondary_domains: list[dict[str, Any]] = field(default_factory=list)
    # DD-159: typed generation outcome per table.
    generation_outcome: str = OUTCOME_SEMANTIC_SUCCESS
    generation_error: str = ""
    generation_provider: str = ""
    generation_model: str = ""


@dataclass
class SampleEvidence:
    """Source-level sample data coverage for an analysis run."""

    analysed_tables: int
    sampled_tables: int
    coverage_ratio: float
    threshold: float = LOW_SAMPLE_COVERAGE_THRESHOLD
    warning: bool = False
    missing_sample_tables: list[str] = field(default_factory=list)


@dataclass
class SourceAnalysis:
    """Complete analysis result for one source system."""

    system: str
    analysed_at: str
    model_used: str
    table_assignments: list[TableAssignment] = field(default_factory=list)
    sample_evidence: SampleEvidence | None = None


class AffinityTotalFailureError(RuntimeError):
    """Raised when every attempted table's semantic generation failed.

    "Attempted" excludes tables served from the per-table sidecar cache (no
    LLM call made). When raised, **no** affinity YAML was written by the run:
    writes are staged and committed only after the run-wide verdict is known,
    so a pre-existing affinity file for this system is left byte-identical.
    Callers must exit non-zero and never report success.

    Mirrors :class:`propose_alignment.AlignmentTotalFailureError`.
    """


def _filter_analysis_by_domain(
    analysis: SourceAnalysis, output_domain_filter: list[str]
) -> SourceAnalysis:
    """Return a copy of *analysis* keeping only tables whose **primary** domain
    matches one of the (lower-cased) ``output_domain_filter`` values.

    The ``--domains`` flag is an output focus, applied *after* classification
    against the full candidate set (issue #189). Matching mirrors the legacy
    substring semantics: a table is kept when any filter value is a substring of
    its primary ``domain`` id. Downstream coverage buckets by primary domain
    only, so secondary domains are deliberately ignored here.
    """
    kept = [
        ta
        for ta in analysis.table_assignments
        if any(f in ta.domain.lower() for f in output_domain_filter)
    ]
    return SourceAnalysis(
        system=analysis.system,
        analysed_at=analysis.analysed_at,
        model_used=analysis.model_used,
        table_assignments=kept,
        sample_evidence=analysis.sample_evidence,
    )


# ---------------------------------------------------------------------------
# Source vocabulary parsing
# ---------------------------------------------------------------------------


def parse_source_vocabulary(vocab_path: Path) -> dict[str, list[dict[str, Any]]]:
    """Parse a bronze vocabulary TTL file into a table→columns structure.

    Returns dict mapping table_name → list of column dicts with
    {name, data_type, nullable, samples, distinct_count}.
    """
    g = Graph()
    g.parse(vocab_path, format="turtle")

    tables: dict[str, list[dict[str, Any]]] = {}

    # Find all source tables.
    #
    # DD-175: sorted, both here and over the columns below. These lists are
    # rendered straight into the alignment prompt, and graph iteration — and a
    # set of URIRefs, whose iteration order follows string hashing and is
    # randomised per process — put the columns in a different order on every
    # run. That made the prompt itself unstable, which no sampling seed can
    # compensate for. The bronze vocabulary records no column ordinal, so URI
    # order is the available deterministic order.
    for tbl_uri in sorted(g.subjects(RDF.type, KAIROS_BRONZE.SourceTable), key=str):
        tbl_name = str(
            g.value(tbl_uri, KAIROS_BRONZE.tableName) or tbl_uri.split("#")[-1].split("/")[-1]
        )
        columns = []

        # Find columns belonging to this table (both predicates are used)
        col_uris = set(g.subjects(KAIROS_BRONZE.belongsToTable, tbl_uri))
        col_uris.update(g.subjects(KAIROS_BRONZE.sourceTable, tbl_uri))
        for col_uri in sorted(col_uris, key=str):
            col_name = str(
                g.value(col_uri, KAIROS_BRONZE.columnName) or col_uri.split("#")[-1].split("/")[-1]
            )
            data_type = str(g.value(col_uri, KAIROS_BRONZE.dataType) or "unknown")
            nullable = bool(g.value(col_uri, KAIROS_BRONZE.nullable))
            samples_raw = g.value(col_uri, KAIROS_BRONZE.sampleValues)
            samples = str(samples_raw).split(" | ") if samples_raw else []
            distinct_count_raw = g.value(col_uri, KAIROS_BRONZE.distinctCount)
            distinct_count = int(distinct_count_raw) if distinct_count_raw is not None else None

            columns.append(
                {
                    "name": col_name,
                    "data_type": data_type,
                    "nullable": nullable,
                    "samples": samples,
                    "distinct_count": distinct_count,
                }
            )

        tables[tbl_name] = columns

    return tables


def parse_source_primary_keys(vocab_path: Path) -> dict[str, tuple[str, ...]]:
    """Parse a bronze vocabulary TTL file's declared ``primaryKeyColumns`` per table.

    Returns dict mapping table_name -> ordered tuple of primary-key column names (empty when
    a table declares none). Kept separate from :func:`parse_source_vocabulary` (which does not
    surface this table-level field) so callers that only need primary-key evidence -- e.g.
    ``scaffold_binding``'s grain/technical-field heuristics -- can reuse this exempted Bronze
    parse site instead of parsing the vocabulary graph themselves.
    """
    g = Graph()
    g.parse(vocab_path, format="turtle")

    keys: dict[str, tuple[str, ...]] = {}
    for tbl_uri in g.subjects(RDF.type, KAIROS_BRONZE.SourceTable):
        tbl_name = str(
            g.value(tbl_uri, KAIROS_BRONZE.tableName) or tbl_uri.split("#")[-1].split("/")[-1]
        )
        raw = g.value(tbl_uri, KAIROS_BRONZE.primaryKeyColumns)
        keys[tbl_name] = tuple(str(raw).split()) if raw else ()
    return keys


def analyse_sample_evidence(
    tables: dict[str, list[dict[str, Any]]],
    *,
    threshold: float = LOW_SAMPLE_COVERAGE_THRESHOLD,
) -> SampleEvidence:
    """Compute table-level sample coverage for source-analysis evidence."""
    analysed = {name: cols for name, cols in tables.items() if cols}
    analysed_count = len(analysed)
    sampled_tables = [
        name for name, columns in analysed.items() if any(col.get("samples") for col in columns)
    ]
    sampled_count = len(sampled_tables)
    coverage = round(sampled_count / analysed_count, 4) if analysed_count else 1.0
    sampled_set = set(sampled_tables)
    missing = sorted(name for name in analysed if name not in sampled_set)
    return SampleEvidence(
        analysed_tables=analysed_count,
        sampled_tables=sampled_count,
        coverage_ratio=coverage,
        threshold=threshold,
        warning=analysed_count > 0 and coverage < threshold,
        missing_sample_tables=missing,
    )


# ---------------------------------------------------------------------------
# Reference model parsing
# ---------------------------------------------------------------------------


def _domain_properties_for(graph: Graph, cls_uri: URIRef) -> set[URIRef]:
    """Return the properties that apply to *cls_uri*, using the DD-131 authority.

    Thin adapter over ``projections.shared``: that module already resolves union and
    ``schema:domainIncludes`` semantics for the projectors and ``validate-mapping``, and
    its own docstring calls itself "the single authority ... so union semantics are
    resolved identically everywhere". This routes source analysis through it rather than
    keeping a second, narrower interpretation of what a property's domain is.
    """
    from .projections.shared import effective_domain_classes, properties_with_domain

    return {
        prop
        for prop in properties_with_domain(graph)
        if cls_uri in effective_domain_classes(graph, prop)
    }


def parse_reference_model(
    ttl_path: Path | None = None,
    *,
    graph: Graph | None = None,
    domain_name: str | None = None,
    include_specializations: bool = False,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    """Parse a reference model TTL file (or pre-loaded graph) into a domain summary.

    Args:
        ttl_path: Path to a single TTL file (mutually exclusive with graph)
        graph: Pre-loaded rdflib Graph (used for merged multi-file domains)
        domain_name: Override domain name (used with graph parameter)
        include_specializations: If True, walk subClassOf downward and include
            a ``specializations`` key per class (DD-044).

    Returns dict with domain_name, file, classes (with properties and labels).
    """
    if graph is not None:
        g = graph
    elif ttl_path is not None:
        from .ontology_loader import SemanticProfile, load_ontology

        loaded = load_ontology(
            ttl_path,
            catalog_path=catalog_path,
            profile=SemanticProfile.KAIROS_DESIGN,
        )
        return _reference_summary_from_index(
            loaded.semantic_index,
            loaded.graph,
            domain_name=domain_name or ttl_path.stem,
            file_name=ttl_path.name,
            include_specializations=include_specializations,
        )
    else:
        raise ValueError("Either ttl_path or graph must be provided")

    # Get ontology metadata
    resolved_name = domain_name or (ttl_path.stem if ttl_path else "unknown")
    for ont in g.subjects(RDF.type, OWL.Ontology):
        label = stable_value(g, ont, RDFS.label)
        if label:
            resolved_name = str(label)
        break

    classes: list[dict[str, Any]] = []

    for cls_uri in g.subjects(RDF.type, OWL.Class):
        # Skip blank nodes
        if not isinstance(cls_uri, URIRef):
            continue
        cls_name = cls_uri.split("#")[-1].split("/")[-1]
        cls_label = str(stable_value(g, cls_uri, RDFS.label) or cls_name)
        cls_comment = str(stable_value(g, cls_uri, RDFS.comment) or "")

        # Find properties with this class as domain.
        #
        # Via the shared DD-131 authority rather than a direct rdfs:domain lookup. The
        # bespoke query this replaced saw only literal `rdfs:domain` triples, so it
        # silently dropped two whole families the reference models rely on:
        # `schema:domainIncludes` (the REUSABLE pattern — a property deliberately left
        # domainless so asserting one does not infer subsumption onto every class using
        # it) and `owl:unionOf` domains. bsp/party declares hasAddress /
        # hasBillingAddress / hasShippingAddress exactly that way, so alignment was told
        # TradeParty has no address property and truthfully reported "no address
        # property is listed on TradeParty" while the property sat in the model.
        properties: list[dict[str, str]] = []
        for prop_uri in sorted(_domain_properties_for(g, cls_uri), key=str):
            prop_name = prop_uri.split("#")[-1].split("/")[-1]
            prop_label = str(stable_value(g, prop_uri, RDFS.label) or prop_name)
            prop_range = ""
            range_val = stable_value(g, prop_uri, RDFS.range)
            if range_val:
                prop_range = range_val.split("#")[-1].split("/")[-1]
            properties.append(
                {
                    "name": prop_name,
                    "label": prop_label,
                    "range": prop_range,
                    # Lets the prompt distinguish "links to an entity" from "is a
                    # literal" (DD-172); without it both render identically.
                    "type": (
                        "object"
                        if (prop_uri, RDF.type, OWL.ObjectProperty) in g
                        else "datatype"
                    ),
                }
            )

        cls_dict: dict[str, Any] = {
            "uri": str(cls_uri),
            "name": cls_name,
            "label": cls_label,
            "comment": cls_comment,
            "properties": properties,
        }
        if include_specializations:
            cls_dict["specializations"] = find_specializations(g, cls_uri)
        classes.append(cls_dict)

    return {
        "domain_name": resolved_name,
        "file": ttl_path.name if ttl_path else "(merged)",
        "classes": classes,
    }


def _reference_summary_from_index(
    index,
    graph: Graph,
    *,
    domain_name: str,
    file_name: str,
    include_specializations: bool,
) -> dict[str, Any]:
    """Render the established reference summary shape from the semantic index."""
    for ontology in graph.subjects(RDF.type, OWL.Ontology):
        label = stable_value(graph, ontology, RDFS.label)
        if label:
            domain_name = str(label)
            break
    properties = {item.uri: item for item in index.properties}
    classes = {item.uri: item for item in index.classes}

    def render_property(link) -> dict[str, Any]:
        prop = properties[link.uri]
        range_uri = prop.ranges[0].uri if prop.ranges else ""
        return {
            "uri": prop.uri,
            "name": prop.name,
            "label": prop.label,
            "comment": prop.comment,
            "range": range_uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1],
            "range_uri": range_uri,
            "type": prop.property_type,
            "inherited": not link.provenance.asserted,
        }

    rendered: list[dict[str, Any]] = []
    for cls in index.classes:
        item: dict[str, Any] = {
            "uri": cls.uri,
            "name": cls.name,
            "label": cls.label,
            "comment": cls.comment,
            "properties": [render_property(link) for link in cls.direct_properties],
            "inherited_properties": [render_property(link) for link in cls.inherited_properties],
        }
        if include_specializations:
            item["specializations"] = [
                {
                    "class": classes[link.uri].name,
                    "class_uri": link.uri,
                    "distance": link.distance,
                    "properties": [
                        render_property(prop) for prop in classes[link.uri].direct_properties
                    ],
                }
                for link in cls.descendants
            ]
        rendered.append(item)
    return {
        "domain_name": domain_name,
        "file": file_name,
        "classes": rendered,
        "semantic_profile": index.profile.value,
        "closure_hash": index.closure_hash,
        "import_complete": index.import_complete,
        # Carried alongside import_complete because it is the same kind of signal and
        # the two disagree: a module can resolve its whole closure and still lose
        # properties whose rdfs:domain names a class it never imports.
        "unattached_property_domains": list(index.unattached_property_domains),
    }


# ---------------------------------------------------------------------------
# Specialization discovery (DD-044)
# ---------------------------------------------------------------------------


def find_specializations(
    graph: Graph, cls_uri: URIRef, *, max_depth: int = 3
) -> list[dict[str, Any]]:
    """Walk ``rdfs:subClassOf`` downward to discover descendant classes and their properties.

    Descendant properties are **specialization evidence** — they indicate what subclasses
    add, not what the parent class inherits.  See DD-044 for semantics.

    Args:
        graph: The RDF graph containing class and property definitions.
        cls_uri: The class URI to find specializations for.
        max_depth: Maximum depth of ``subClassOf`` traversal (default 3).

    Returns:
        List of dicts, each with ``class``, ``class_uri``, ``distance``, and
        ``properties`` (list of ``{name, label, range, type}``).
    """
    result: list[dict[str, Any]] = []
    visited: set[str] = {str(cls_uri)}

    # BFS with depth tracking
    queue: list[tuple[URIRef, int]] = [(cls_uri, 0)]

    while queue:
        current, depth = queue.pop(0)
        if depth >= max_depth:
            continue

        # Find direct subclasses of current
        for child in graph.subjects(RDFS.subClassOf, current):
            if not isinstance(child, URIRef):
                continue
            child_str = str(child)
            if child_str in visited:
                continue
            visited.add(child_str)

            # Collect properties declared on this child class
            child_name = child_str.split("#")[-1].split("/")[-1]
            child_props: list[dict[str, str]] = []
            for prop_uri in graph.subjects(RDFS.domain, child):
                prop_name = str(prop_uri).split("#")[-1].split("/")[-1]
                prop_label = str(stable_value(graph, prop_uri, RDFS.label) or prop_name)
                prop_range = ""
                range_val = stable_value(graph, prop_uri, RDFS.range)
                if range_val:
                    prop_range = str(range_val).split("#")[-1].split("/")[-1]
                prop_type = "datatype"
                if (prop_uri, RDF.type, OWL.ObjectProperty) in graph:
                    prop_type = "object"
                child_props.append(
                    {
                        "name": prop_name,
                        "label": prop_label,
                        "range": prop_range,
                        "type": prop_type,
                    }
                )

            result.append(
                {
                    "class": child_name,
                    "class_uri": child_str,
                    "distance": depth + 1,
                    "properties": child_props,
                }
            )

            queue.append((child, depth + 1))

    return result


def _find_ontology_package_dirs(all_ttls: list[Path], ref_models_dir: Path) -> set[str]:
    """Scan TTL files and return relative directory paths that contain owl:Ontology."""
    package_dirs: set[str] = set()
    for ttl_path in all_ttls:
        try:
            g = Graph()
            g.parse(ttl_path, format="turtle")
            if any(g.subjects(RDF.type, OWL.Ontology)):
                rel_dir = ttl_path.parent.relative_to(ref_models_dir).as_posix()
                package_dirs.add(rel_dir)
        except Exception:
            pass  # parse failures handled in main loop
    return package_dirs


def _assign_domain_key(
    ttl_path: Path,
    ref_models_dir: Path,
    package_dirs: set[str],
) -> str:
    """Assign a domain grouping key for a TTL file.

    Strategy:
    1. Root-level files → domain key is the file stem
    2. Files in an ontology package dir → group by that directory
    3. Files with a package-dir ancestor → group by nearest ancestor
    4. Fallback → group by immediate parent directory
    """
    rel = ttl_path.relative_to(ref_models_dir)
    parts = rel.parts

    if len(parts) == 1:
        return ttl_path.stem

    # Check if file's own directory is a package
    rel_dir = ttl_path.parent.relative_to(ref_models_dir).as_posix()
    if rel_dir in package_dirs:
        return rel_dir

    # Walk up from parent to root looking for nearest package directory
    current = ttl_path.parent
    while current != ref_models_dir:
        candidate = current.relative_to(ref_models_dir).as_posix()
        if candidate in package_dirs:
            return candidate
        current = current.parent

    # Fallback: immediate parent directory
    return ttl_path.parent.relative_to(ref_models_dir).as_posix()


def _domain_display_name(domain_key: str) -> str:
    """Convert a domain grouping key to a short display name.

    ``derived-ontologies/BSP`` → ``BSP``; ``party`` → ``party``.
    """
    return domain_key.rsplit("/", 1)[-1] if "/" in domain_key else domain_key


def resolve_reference_models(
    ref_models_dir: Path,
    *,
    catalog_path: Path | None = None,
    exclude_patterns: list[str] | None = None,
    include_specializations: bool = False,
) -> list[dict[str, Any]]:
    """Discover and resolve reference model TTLs, merging sub-modules by domain.

    Uses ontology-aware grouping: directories containing ``owl:Ontology``
    declarations are treated as domain package roots.  Files are assigned to
    the nearest ancestor package directory.  Falls back to immediate parent
    directory when no ontology declarations are found.

    Any path with an ``archive`` segment is always excluded (issue #566),
    regardless of *exclude_patterns* -- there is no way to opt back in, by
    design: an archived TTL is a frozen pre-fix snapshot the maintaining repo
    itself keeps only for history, never for resolution.

    Args:
        ref_models_dir: Directory containing reference model TTL files.
        catalog_path: Optional XML catalog for resolving owl:imports URIs.
        exclude_patterns: Additional glob patterns to exclude.
        include_specializations: Walk subClassOf downward per class (DD-044).

    Returns list of domain summaries (same format as parse_reference_model).
    """
    all_ttls = sorted(ref_models_dir.glob("**/*.ttl"))
    if not all_ttls:
        return []

    # Archived snapshots are excluded unconditionally, not only when a caller
    # opts in (issue #566). An archived file shares its permanent module
    # IRI/namespace with the live file it was frozen from (archiving happens
    # before a fix lands, by that repo's own documented convention), so a
    # defect already resolved in the live file still resolves here too unless
    # the archive copy is dropped -- misattributing a historical defect as a
    # live one. Matched on a literal path *segment*, not a caller-supplied
    # glob, so it is robust regardless of vendor folder layout -- the same
    # check kairos-ontology-referencemodels' own validate_structure.py check 10
    # already applies for the identical reason.
    all_ttls = [
        t for t in all_ttls if "archive" not in t.relative_to(ref_models_dir).parts
    ]
    if not all_ttls:
        return []

    # Apply exclusion filters. Match each TTL's relative posix path against the
    # glob patterns with fnmatch so behaviour is consistent across platforms
    # (Path.glob("dir/**") matches only directories on POSIX but files on Windows).
    if exclude_patterns:
        import fnmatch

        def _is_excluded(ttl: Path) -> bool:
            rel = ttl.relative_to(ref_models_dir).as_posix()
            return any(fnmatch.fnmatch(rel, pat) for pat in exclude_patterns)

        all_ttls = [t for t in all_ttls if not _is_excluded(t)]
        if not all_ttls:
            return []

    # Phase 1: identify ontology package directories
    package_dirs = _find_ontology_package_dirs(all_ttls, ref_models_dir)

    # Phase 2: assign each TTL to a domain group
    domain_groups: dict[str, list[Path]] = {}
    for ttl_path in all_ttls:
        domain_key = _assign_domain_key(ttl_path, ref_models_dir, package_dirs)
        domain_groups.setdefault(domain_key, []).append(ttl_path)

    # Load each grouped root through the canonical closure API and merge summaries
    # by full URI. This also covers packages whose modules do not import each other.
    domains: list[dict[str, Any]] = []
    #: module IRI -> {(property_uri, unreachable_domain_class_uri)}. Accumulated across
    #: every module resolved in this call and reported once at the end, rather than per
    #: module: the same bundle is re-resolved many times in a run, so a per-parse warning
    #: would repeat the same finding until it became unreadable.
    unattached: defaultdict[str, set[tuple[str, str]]] = defaultdict(set)

    for domain_key, ttl_files in domain_groups.items():
        display_name = _domain_display_name(domain_key)
        classes_by_uri: dict[str, dict[str, Any]] = {}
        closure_hashes: set[str] = set()
        complete = True
        resolved_display_name = display_name
        for ttl_file in ttl_files:
            try:
                result = parse_reference_model(
                    ttl_file,
                    domain_name=display_name,
                    include_specializations=include_specializations,
                    catalog_path=(catalog_path if catalog_path and catalog_path.exists() else None),
                )
                for cls in result["classes"]:
                    classes_by_uri.setdefault(cls["uri"], cls)
                resolved_display_name = result.get("domain_name") or resolved_display_name
                if result.get("closure_hash"):
                    closure_hashes.add(result["closure_hash"])
                complete = complete and bool(result.get("import_complete", True))
                # Keyed on the *property's* module, not the domain class's: that is the
                # module missing an owl:imports, so that is where the fix goes.
                for prop_uri, cls_uri in result.get("unattached_property_domains") or ():
                    unattached[_module_of_uri(prop_uri)].add((prop_uri, cls_uri))
            except Exception as e:
                logger.warning(
                    "Canonical reference-model loading failed for %s: %s",
                    ttl_file,
                    e,
                )
        if classes_by_uri:
            domains.append(
                {
                    "domain_name": resolved_display_name,
                    "file": ", ".join(str(path) for path in ttl_files),
                    "classes": [classes_by_uri[uri] for uri in sorted(classes_by_uri)],
                    "ref_source": domain_key,
                    "semantic_profile": "kairos-design",
                    "closure_hashes": sorted(closure_hashes),
                    "import_complete": complete,
                }
            )

    logger.info(
        "Resolved %d domain(s) from %d TTL file(s) in %s",
        len(domains),
        len(all_ttls),
        ref_models_dir,
    )
    _warn_unattached_property_domains(unattached)
    return domains


def _module_of_uri(uri: str) -> str:
    """Return the module IRI part of a term URI (everything before the fragment)."""
    return uri.split("#", 1)[0]


def _warn_unattached_property_domains(
    unattached: "defaultdict[str, set[tuple[str, str]]] | dict[str, set[tuple[str, str]]]",
) -> None:
    """Report properties that resolved to no class, once per resolution pass.

    Two unrelated causes produce the same symptom -- a property that attaches to no
    class and is therefore invisible to alignment -- so they get two separate messages
    (DD-204, #328):

    * **Missing owl:imports.** A property whose ``rdfs:domain`` names a class its
      module never ``owl:imports`` attaches to nothing, so every consumer sees the
      class as lacking a property it actually has. That silence is the defect: it
      makes a real reference term indistinguishable from a missing one, and a
      coverage report will then propose adding a term the model already defines.
    * **``rdfs:domain owl:Thing``.** ``owl:Thing`` is the OWL spec's implicit
      universal class -- no real ontology file ever declares it ``owl:Class`` /
      ``rdfs:Class``, so it never enters ``_class_uris`` (semantic_index.py) and the
      property is unattached no matter how complete the module's imports are. Adding
      an ``owl:imports`` fixes nothing here, so telling an author to add one is wrong.

    Advisory only. The toolkit consumes bundles it does not own, so a malformed vendor
    module must not stop a run -- but it must not pass unremarked either.
    """
    if not unattached:
        return
    owl_thing = str(OWL.Thing)
    missing_import: defaultdict[str, set[tuple[str, str]]] = defaultdict(set)
    owl_thing_domain: defaultdict[str, set[tuple[str, str]]] = defaultdict(set)
    for module, pairs in unattached.items():
        for prop_uri, cls_uri in pairs:
            bucket = owl_thing_domain if cls_uri == owl_thing else missing_import
            bucket[module].add((prop_uri, cls_uri))

    def _by_module(groups: "dict[str, set[tuple[str, str]]]") -> str:
        return ", ".join(
            f"{module.rsplit('/ont/', 1)[-1]} ({len(pairs)})"
            for module, pairs in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        )

    if missing_import:
        total = sum(len(pairs) for pairs in missing_import.values())
        logger.warning(
            "%d property-domain assertion(s) could not be attached to any class while "
            "resolving reference models: %s. Those properties are invisible to alignment, "
            "so a class will look like it is missing a term it actually has. The cause is "
            "usually a missing owl:imports in the source module -- adding the module to a "
            "hub's data-domains.yaml does NOT resolve it.",
            total,
            _by_module(missing_import),
        )
    if owl_thing_domain:
        total = sum(len(pairs) for pairs in owl_thing_domain.values())
        logger.warning(
            "%d property-domain assertion(s) declare rdfs:domain owl:Thing (a "
            "cross-cutting/no-fixed-domain pattern, see issue #328): %s. These are NOT a "
            "missing owl:imports -- owl:Thing is never declared a class in any real "
            "ontology file, so it can never be resolved by importing more of the graph. "
            "They are invisible to alignment by design of that pattern, until the "
            "toolkit decides how to support it.",
            total,
            _by_module(owl_thing_domain),
        )
    for module, pairs in sorted(unattached.items()):
        for prop_uri, cls_uri in sorted(pairs):
            logger.debug("  %s declares rdfs:domain %s, which is absent", prop_uri, cls_uri)


def load_data_domains(
    ref_models_dir: Path, accelerator: str | None = None
) -> dict[str, dict[str, Any]]:
    """Find and parse data-domains.yaml from accelerator pack blueprints.

    Returns a dict keyed by domain id (e.g. ``"party"``) with ownership metadata:
    ``{"name", "owns", "does_not_own", "group", "uris", "modules"}``.

    Args:
        ref_models_dir: Directory containing accelerator-packs/.
        accelerator: If given, only load the data-domains.yaml of that pack
            (e.g. ``"logistics"``). If omitted, the first match wins.

    Returns empty dict if no data-domains.yaml is found.
    """
    if accelerator:
        glob_pattern = f"accelerator-packs/{accelerator}/client-hub-blueprint/data-domains.yaml"
    else:
        glob_pattern = "accelerator-packs/*/client-hub-blueprint/data-domains.yaml"

    for dd_path in sorted(ref_models_dir.glob(glob_pattern)):
        try:
            with open(dd_path, encoding="utf-8") as f:
                dd = yaml.safe_load(f)
            result: dict[str, dict[str, Any]] = {}
            for group in dd.get("groups", []):
                group_id = group.get("id", "")
                for domain in group.get("domains", []):
                    imports = domain.get("imports", []) or []
                    result[domain["id"]] = {
                        "name": domain.get("name", domain["id"]),
                        "owns": domain.get("owns", ""),
                        "does_not_own": domain.get("does_not_own", ""),
                        "group": group_id,
                        "uris": [imp["uri"] for imp in imports if imp.get("uri")],
                        "modules": [imp["module"] for imp in imports if imp.get("module")],
                        "imports": [
                            {
                                key: imp[key]
                                for key in ("uri", "module", "profile", "module_id")
                                if imp.get(key)
                            }
                            for imp in imports
                        ],
                    }
            logger.info("Loaded %d data domains from %s", len(result), dd_path)
            return result
        except Exception as e:
            logger.warning("Failed to load data-domains.yaml: %s", e)
    return {}


def load_cross_domain_bridges(
    ref_models_dir: Path, accelerator: str | None = None
) -> list[dict[str, Any]]:
    """Return the pack blueprint's declared ``cross_domain_relationships`` (DD-181).

    Each bridge names a ``source_domain`` that may reference a ``range_class_uri``
    owned by a ``target_domain``, through an exact ``property_uri``. The logistics
    pack ships 24.

    A bridge is the blueprint's own statement that reaching across a boundary is
    *authorised* — which is precisely the authority the anchor pool needs, and why
    honouring it requires no extra flag.

    Returned verbatim, without filtering on which fields are populated: the scaffold
    header needs only ``property_uri`` while the anchor pool needs
    ``range_class_uri``, so each consumer applies its own requirement.
    """
    if accelerator:
        glob_pattern = f"accelerator-packs/{accelerator}/client-hub-blueprint/data-domains.yaml"
    else:
        glob_pattern = "accelerator-packs/*/client-hub-blueprint/data-domains.yaml"

    for path in sorted(Path(ref_models_dir).glob(glob_pattern)):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - advisory input, never fails a run
            continue
        if not isinstance(payload, dict):
            continue
        return [
            bridge
            for bridge in payload.get("cross_domain_relationships") or []
            if isinstance(bridge, dict)
        ]
    return []


def bridge_anchor_classes(bridges: list[dict[str, Any]], domain_id: str) -> dict[str, str]:
    """Map ``class_uri -> target_domain`` for bridges declared *from* ``domain_id``.

    These are classes the domain is authorised to reference but does not own. A
    source table holding rows of a referenced entity — ``stops`` under
    ``consignment``, whose rows *are* transport calls — should be able to anchor
    to one, while the class stays owned where the blueprint puts it.
    """
    return {
        str(bridge["range_class_uri"]): str(bridge.get("target_domain") or "")
        for bridge in bridges
        if str(bridge.get("source_domain") or "") == domain_id and bridge.get("range_class_uri")
    }


def load_accelerator_uri_modules(
    ref_models_dir: Path, accelerator: str | None = None
) -> dict[str, dict[str, Any]]:
    """Map each imported reference-model URI to its module label and owning domains.

    Unlike :func:`load_data_domains` (which returns parallel ``uris``/``modules``
    lists per domain), this preserves the per-import ``uri ↔ module`` pairing and
    aggregates which data-domain ids import each URI — the metadata
    ``propose-alignment`` needs to tag cross-module matches (issue #166, DD-070).

    Returns ``{uri: {"module": str, "domains": [domain_id, ...]}}`` for one
    accelerator pack's ``data-domains.yaml``. Empty dict when none is found.
    """
    if accelerator:
        glob_pattern = f"accelerator-packs/{accelerator}/client-hub-blueprint/data-domains.yaml"
    else:
        glob_pattern = "accelerator-packs/*/client-hub-blueprint/data-domains.yaml"

    for dd_path in sorted(ref_models_dir.glob(glob_pattern)):
        try:
            with open(dd_path, encoding="utf-8") as f:
                dd = yaml.safe_load(f)
            result: dict[str, dict[str, Any]] = {}
            for group in dd.get("groups", []):
                for domain in group.get("domains", []):
                    domain_id = domain.get("id", "")
                    for imp in domain.get("imports", []) or []:
                        uri = imp.get("uri")
                        if not uri:
                            continue
                        entry = result.setdefault(uri, {"module": "", "domains": []})
                        if not entry["module"] and imp.get("module"):
                            entry["module"] = imp["module"]
                        if domain_id and domain_id not in entry["domains"]:
                            entry["domains"].append(domain_id)
            logger.info("Loaded %d accelerator import URIs from %s", len(result), dd_path)
            return result
        except Exception as e:
            logger.warning("Failed to load data-domains.yaml: %s", e)
    return {}


def list_accelerator_packs(ref_models_dir: Path) -> list[str]:
    """List accelerator pack names that have a data-domains.yaml blueprint."""
    packs: list[str] = []
    for dd_path in sorted(
        ref_models_dir.glob("accelerator-packs/*/client-hub-blueprint/data-domains.yaml")
    ):
        # accelerator-packs/<name>/client-hub-blueprint/data-domains.yaml
        packs.append(dd_path.parent.parent.name)
    return packs


def build_data_domain_targets(
    data_domains: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build classification targets from data-domains.yaml metadata.

    Each data domain (party, commercial, booking, ...) becomes a shallow
    classification target — no TTL/owl:imports resolution is needed because the
    LLM classifies against the ``owns``/``does_not_own`` descriptions and the
    domain name.  This is the data-domain-first strategy.

    Returns a list of domain summaries compatible with ``analyse_source_system``.
    """
    targets: list[dict[str, Any]] = []
    for dd_id, dd_meta in data_domains.items():
        targets.append(
            {
                "domain_name": dd_id,
                "display_name": dd_meta.get("name", dd_id),
                "group": dd_meta.get("group", ""),
                "uris": dd_meta.get("uris", []),
                "modules": dd_meta.get("modules", []),
                "file": "data-domains.yaml",
                "ref_source": dd_meta.get("group", ""),
                "classes": [],
                "data_domain_meta": dd_meta,
            }
        )
    return targets


# ---------------------------------------------------------------------------
# Semantic grounding — resolve directly-imported module classes
# ---------------------------------------------------------------------------


def _module_format(path: Path) -> str:
    """Best-effort RDF format from a file suffix (defaults to turtle)."""
    return {".ttl": "turtle", ".owl": "xml", ".rdf": "xml", ".jsonld": "json-ld", ".nt": "nt"}.get(
        path.suffix.lower(), "turtle"
    )


def _resolve_module_classes(
    path: Path,
    cache: dict[str, list[dict[str, str]]],
) -> list[dict[str, str]]:
    """Extract the ``owl:Class`` definitions *declared in a single module file*.

    Provenance-based: only the classes asserted in ``path`` itself are returned
    (the file's ``owl:imports`` are NOT followed), so transitive FIBO classes do
    not leak in. Results are cached by file path so each module is parsed once per
    run and shared across all candidate domains that import it.
    """
    key = str(path)
    if key in cache:
        return cache[key]
    classes: list[dict[str, str]] = []
    try:
        g = Graph()
        g.parse(path, format=_module_format(path))
        for cls_uri in g.subjects(RDF.type, OWL.Class):
            if not isinstance(cls_uri, URIRef):
                continue
            name = cls_uri.split("#")[-1].split("/")[-1]
            label = str(stable_value(g, cls_uri, RDFS.label) or name)
            comment = str(stable_value(g, cls_uri, RDFS.comment) or "")
            classes.append({"name": name, "label": label, "comment": comment})
    except Exception as e:  # pragma: no cover - parse error path
        logger.debug("Module parse failed for %s: %s", path, e)
    cache[key] = classes
    return classes


def _resolve_uris_to_classes(
    uris: list[str],
    resolver,
    module_cache: dict[str, list[dict[str, str]]],
    cap: int = MAX_DOMAIN_CLASSES,
) -> list[dict[str, str]]:
    """Resolve a domain's import URIs to a capped, de-duplicated class summary."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for uri in uris:
        try:
            path = resolver.resolve(uri)
        except Exception as e:  # pragma: no cover - resolver error path
            logger.debug("Catalog resolve failed for %s: %s", uri, e)
            continue
        if not path or not Path(path).exists():
            logger.debug("No catalog mapping for data-domain URI %s", uri)
            continue
        for c in _resolve_module_classes(Path(path), module_cache):
            if c["name"] in seen:
                continue
            seen.add(c["name"])
            out.append(c.copy())
    return out[:cap]


def resolve_domain_class_summaries(
    ref_domains: list[dict[str, Any]],
    catalog_path: Path | None,
    cap: int = MAX_DOMAIN_CLASSES,
    report=None,
) -> None:
    """Attach a capped ``class_summary`` to each data-domain target in place.

    For every target that carries import ``uris`` but no resolved ``classes``
    (the data-domain-first path), resolve those URIs to their local module TTLs
    via the XML catalog and extract the directly-declared classes. Resolution is
    done **once per run** with a module-level cache shared across all domains,
    tables and source systems. Unresolvable URIs are skipped gracefully so the
    classifier falls back to ``owns``/``does_not_own`` text alone.
    """
    if report is None:
        report = _noop_report
    if not catalog_path or not Path(catalog_path).exists():
        logger.debug("No catalog available; skipping semantic grounding")
        return
    try:
        from kairos_ontology.core.catalog_utils import CatalogResolver

        resolver = CatalogResolver.with_reference_models(Path(catalog_path))
    except Exception as e:
        logger.warning("Catalog load failed (%s); skipping semantic grounding", e)
        return

    module_cache: dict[str, list[dict[str, str]]] = {}
    grounded = 0
    for domain in ref_domains:
        if domain.get("classes"):
            continue  # reference-model path already carries classes
        uris = domain.get("uris", [])
        if not uris:
            continue
        summary = _resolve_uris_to_classes(uris, resolver, module_cache, cap)
        if summary:
            domain["class_summary"] = summary
            grounded += 1
    if grounded:
        report(
            f"  Grounded {grounded} domain(s) with module class semantics "
            f"({len(module_cache)} module file(s) resolved)."
        )


def _summarize_classes(
    classes: list[dict[str, Any]],
    cap: int = MAX_DOMAIN_CLASSES,
) -> list[dict[str, str]]:
    """Trim a full class list down to a capped {name,label,comment} summary."""
    out: list[dict[str, str]] = []
    for c in classes[:cap]:
        out.append(
            {
                "name": c.get("name", ""),
                "label": c.get("label", "") or c.get("name", ""),
                "comment": c.get("comment", ""),
            }
        )
    return out


def _build_candidates(ref_domains: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the normalized candidate-domain list used for single-call prompts.

    Unifies both strategies: data-domain-first targets carry ``data_domain_meta``
    (owns/does_not_own) and a resolved ``class_summary``; reference-model targets
    carry full ``classes`` which are summarised here.
    """
    candidates: list[dict[str, Any]] = []
    for d in ref_domains:
        dd_meta = d.get("data_domain_meta") or {}
        class_summary = d.get("class_summary")
        if class_summary is None:
            class_summary = _summarize_classes(d.get("classes", []))
        candidates.append(
            {
                "id": d["domain_name"],
                "group": d.get("group", ""),
                "uris": d.get("uris", []),
                "owns": dd_meta.get("owns", ""),
                "does_not_own": dd_meta.get("does_not_own", ""),
                "class_summary": class_summary,
            }
        )
    return candidates


def _pick_fallback(valid_ids: set[str], fallback_ids: list[str]) -> str:
    """Return the first fallback id present in the candidate set, else 'unclassified'."""
    for fid in fallback_ids:
        if fid in valid_ids:
            return fid
    return "unclassified"


def _normalize_id(s: str) -> str:
    """Lowercase alphanumeric-only form, for tolerant candidate-id matching."""
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _resolve_domain_id(raw: str, candidate_ids: list[str]) -> str | None:
    """Match a model-returned domain value to a candidate id.

    Exact match first; otherwise a normalized (case/space/punctuation-insensitive)
    match, but only when it is unambiguous. Returns None if no confident match —
    important for reference-model candidate ids that may contain spaces/slashes.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw in candidate_ids:
        return raw
    norm = _normalize_id(raw)
    if not norm:
        return None
    matches = [cid for cid in candidate_ids if _normalize_id(cid) == norm]
    return matches[0] if len(matches) == 1 else None


def _coerce_confidence(val: Any) -> float:
    """Parse a confidence value defensively and clamp to [0.0, 1.0]."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(1.0, f)), 2)


def _as_str_list(val: Any) -> list[str]:
    """Coerce an arbitrary JSON value into a list of strings."""
    if isinstance(val, list):
        return [str(x) for x in val]
    if val:
        return [str(val)]
    return []


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------


def _get_openai_client(model: str = DEFAULT_MODEL):
    """Create an OpenAI client configured for the active AI provider.

    Uses the ``alignment`` role (issue #562 collapsed the separate ``affinity``
    role into it: one configured provider, the strongest one, for every
    pre-modeling LLM call) so a per-role endpoint/model override applies to the
    high-volume table → domain classification call (issue #182).

    Calls :func:`require_ai_provider` first so a missing/misconfigured provider
    fails fast before any table is attempted, instead of silently failing every
    table and caching fabricated fallback domains (DD-159).
    """
    from kairos_ontology.core.ai_preflight import require_ai_provider

    require_ai_provider(ROLE_ALIGNMENT, model=model, probe=False)
    from kairos_ontology.core.ai_provider import get_ai_client

    return get_ai_client(model=model, role=ROLE_ALIGNMENT)


#: Sample values per column sent to the affinity model (DD-166).
#:
#: Deliberately far below the alignment step's limit. Affinity answers "which domain is
#: this table?", for which a couple of values is a type hint and twenty is twenty times
#: the prompt weight and PII exposure for no better answer. Alignment answers "which
#: property is this column?", where the value distribution *is* the evidence.
MAX_AFFINITY_SAMPLES = 3


def _format_columns(columns: list[dict[str, Any]]) -> str:
    """Render columns as a markdown-ish table with a few sample values each."""
    col_lines = []
    for col in columns:
        samples = col.get("samples") or []
        samples_str = ", ".join(samples[:MAX_AFFINITY_SAMPLES])
        col_lines.append(f"  | {col['name']} | {col['data_type']} | {samples_str} |")
    return "\n".join(col_lines)


def _build_single_call_prompt(
    table_name: str,
    columns: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> str:
    """Build a single prompt that classifies one table against ALL candidates.

    The model picks exactly ONE primary domain id (plus optional secondaries)
    from the candidate ids listed in the prompt.
    """
    cand_blocks = []
    for c in candidates:
        header = f"### {c['id']}" + (f"  (group: {c['group']})" if c.get("group") else "")
        lines = [header]
        if c.get("owns"):
            lines.append(f"  OWNS: {c['owns']}")
        if c.get("does_not_own"):
            lines.append(f"  DOES NOT OWN: {c['does_not_own']}")
        cs = c.get("class_summary") or []
        if cs:
            labels = ", ".join(x.get("label") or x.get("name", "") for x in cs)
            lines.append(f"  KEY CONCEPTS: {labels}")
        cand_blocks.append("\n".join(lines))

    candidate_ids = ", ".join(c["id"] for c in candidates)

    return f"""Classify this source database table into exactly ONE primary business data domain.
Focus on the TABLE AS A WHOLE — its name, the column names collectively, and the sample data values.

SOURCE TABLE: {table_name}
COLUMNS AND SAMPLE DATA:
  | Column | Type | Sample Values |
{_format_columns(columns)}

CANDIDATE DATA DOMAINS (choose the single best PRIMARY fit):
{chr(10).join(cand_blocks)}

Instructions:
- Pick the ONE primary domain whose subject matter and ownership boundaries best match the table.
- The primary `domain` MUST be exactly one of these ids: {candidate_ids}
- Optionally list up to {MAX_SECONDARY_DOMAINS} secondary domains (also from the ids above) only if the table clearly also feeds them. Use [] if none.
- Identify the likely business entity the table represents and the columns most indicative of the chosen domain.

Respond with JSON only:
{{
  "domain": "<one of the candidate ids>",
  "secondary_domains": ["<id>", "..."],
  "confidence": 0.0-1.0,
  "likely_entity": "Business entity name (e.g. SalesContract, PartyAddress)",
  "rationale": "1-2 sentence explanation of the primary choice",
  "indicative_columns": ["col1", "col2", "col3"]
}}"""


def analyse_table_single_call(
    client,
    model: str,
    table_name: str,
    columns: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    fallback_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Classify one source table against all candidate domains in a single LLM call.

    Returns a normalized dict ``{domain, secondary_domains, confidence,
    likely_entity, rationale, indicative_columns}``. The returned ``domain`` is
    always a valid candidate id, the configured fallback, or ``"unclassified"``.
    """
    fallback_ids = fallback_ids if fallback_ids is not None else FALLBACK_DOMAIN_IDS
    candidate_ids = [c["id"] for c in candidates]
    valid_ids = set(candidate_ids)
    prompt = _build_single_call_prompt(table_name, columns, candidates)

    response = call_with_backoff(
        lambda: create_chat_completion(
            client,
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert data architect. You classify source system "
                        "tables into business data domains based on table names, column "
                        "names, and sample data values. You always pick exactly one "
                        "primary domain. Always respond with valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            seed=resolve_ai_seed(ROLE_ALIGNMENT),
            reasoning_effort=resolve_reasoning_effort(ROLE_ALIGNMENT),
            response_format={"type": "json_object"},
        )
    )
    result = json.loads(response.choices[0].message.content)
    if not isinstance(result, dict):
        result = {}

    matched = _resolve_domain_id(result.get("domain", ""), candidate_ids)
    if matched is not None:
        domain_id = matched
        confidence = _coerce_confidence(result.get("confidence"))
        likely_entity = str(result.get("likely_entity", "") or "")
        rationale = str(result.get("rationale", "") or "")
        indicative = _as_str_list(result.get("indicative_columns"))
        fell_back = False
    else:
        domain_id = _pick_fallback(valid_ids, fallback_ids)
        confidence = 0.0
        likely_entity = ""
        rationale = (
            str(result.get("rationale", "") or "")
            or f"Model returned no valid domain; fell back to '{domain_id}'."
        )
        indicative = []
        fell_back = True

    secondaries: list[str] = []
    for raw_sid in _as_str_list(result.get("secondary_domains")):
        sid = _resolve_domain_id(raw_sid, candidate_ids)
        if sid and sid != domain_id and sid not in secondaries:
            secondaries.append(sid)
        if len(secondaries) >= MAX_SECONDARY_DOMAINS:
            break

    return {
        "domain": domain_id,
        "secondary_domains": secondaries,
        "confidence": confidence,
        "likely_entity": likely_entity,
        "rationale": rationale,
        "indicative_columns": indicative,
        "_fell_back": fell_back,
    }


# ---------------------------------------------------------------------------
# Main analysis orchestrator
# ---------------------------------------------------------------------------


def _noop_report(message: str, level: str = "info") -> None:
    """Default no-op progress reporter."""


def make_reporter(verbose: bool = False, quiet: bool = False):
    """Build a progress reporter that prints to stdout, honouring verbosity.

    Levels: ``"info"`` (default), ``"verbose"`` (only when verbose), and
    ``"error"`` (always shown). When ``quiet`` is set, only errors print.
    """

    def report(message: str, level: str = "info") -> None:
        if level == "error":
            print(message)
            return
        if quiet:
            return
        if level == "verbose" and not verbose:
            return
        print(message)

    return report


def analyse_source_system(
    source_vocab_path: Path,
    ref_domains: list[dict[str, Any]],
    model: str = DEFAULT_MODEL,
    threshold: float = 0.3,
    report=None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    cache: SidecarCache | None = None,
    system_name: str | None = None,
    tables: dict[str, list[dict[str, Any]]] | None = None,
    client=None,
) -> SourceAnalysis:
    """Analyse one source system against candidate domains, table by table.

    Table-centric: each source table is classified in a SINGLE LLM call against
    all candidate domains, yielding exactly one primary domain (plus optional
    secondaries). Group and URIs are resolved server-side from the chosen
    candidate.

    Args:
        source_vocab_path: Path to the source system's .vocabulary.ttl
        ref_domains: Pre-resolved domain targets (data-domain-first or
            reference-model). Each may carry ``class_summary``/``classes``.
        model: LLM model name
        threshold: Reserved for backward compatibility (unused — one primary
            domain is always returned per table).
        report: Optional progress reporter (see make_reporter)
        max_workers: Max concurrent per-table LLM calls. ``1`` runs serially.
        cache: Optional sidecar cache; reuses unchanged per-table classifications.

    Returns:
        SourceAnalysis with one TableAssignment per (non-empty) source table.
    """
    if report is None:
        report = _noop_report

    sys_name = system_name or source_vocab_path.stem.replace(".vocabulary", "")
    source_tables = tables if tables is not None else parse_source_vocabulary(source_vocab_path)
    if not source_tables:
        logger.warning("No tables found in %s", source_vocab_path)
        return SourceAnalysis(
            system=sys_name,
            analysed_at=datetime.now(timezone.utc).isoformat(),
            model_used=model,
        )
    sample_evidence = analyse_sample_evidence(source_tables)
    if sample_evidence.warning:
        missing = ", ".join(sample_evidence.missing_sample_tables[:8])
        if len(sample_evidence.missing_sample_tables) > 8:
            missing += f", +{len(sample_evidence.missing_sample_tables) - 8} more"
        report(
            "  ⚠ Sample data coverage is low for "
            f"{sys_name}: {sample_evidence.sampled_tables}/"
            f"{sample_evidence.analysed_tables} analysed table(s) have sample values "
            f"({sample_evidence.coverage_ratio:.0%}; threshold "
            f"{sample_evidence.threshold:.0%}). Source analysis will continue, "
            "but schema-only tables may be semantically ambiguous; review sample "
            f"availability before modeling. Missing samples: {missing or '(none)'}."
        )

    if client is None:
        client = _get_openai_client(model)
    candidates = _build_candidates(ref_domains)
    meta_by_id = {c["id"]: c for c in candidates}
    # Stable signature of the candidate domain set for cache-key invalidation.
    candidate_signature = compute_entry_hash(sorted(c["id"] for c in candidates))

    table_items = [(name, cols) for name, cols in source_tables.items() if cols]

    def _classify(item: tuple[str, list[dict[str, Any]]]) -> dict[str, Any]:
        tbl_name, columns = item
        cache_key = (
            compute_entry_hash(
                {
                    "system": sys_name,
                    "table": tbl_name,
                    "model": model,
                    "candidates": candidate_signature,
                    "columns": [
                        {
                            "name": c.get("name"),
                            "type": c.get("data_type"),
                            "samples": c.get("samples", []),
                        }
                        for c in columns
                    ],
                }
            )
            if cache is not None
            else ""
        )
        if cache is not None:
            cached = cache.get(cache_key)
            if cached is not None:
                return {
                    "table": tbl_name,
                    "columns": columns,
                    "res": cached,
                    "cache_key": cache_key,
                    "from_cache": True,
                    "generation_outcome": OUTCOME_SEMANTIC_SUCCESS,
                    "generation_error": "",
                    "generation_provider": "",
                    "generation_model": model,
                }
        try:
            res = analyse_table_single_call(client, model, tbl_name, columns, candidates)
            # If the model returned an unresolvable domain, analyse_table_single_call
            # picks a fallback — record the outcome so we don't cache it as success.
            if res.get("_fell_back", False):
                outcome = OUTCOME_UNRESOLVED_ANSWER
            else:
                outcome = OUTCOME_SEMANTIC_SUCCESS
            error_msg = ""
        except Exception as exc:  # noqa: BLE001 — isolate one table failure
            logger.warning("Classification failed for %s.%s: %s", sys_name, tbl_name, exc)
            error_msg = sanitize_provider_error(exc)
            res = {
                "domain": "",
                "secondary_domains": [],
                "confidence": 0.0,
                "likely_entity": "",
                "rationale": f"Classification error: {error_msg}",
                "indicative_columns": [],
            }
            outcome = OUTCOME_PROVIDER_FAILURE
        return {
            "table": tbl_name,
            "columns": columns,
            "res": res,
            "cache_key": cache_key,
            "from_cache": False,
            "generation_outcome": outcome,
            "generation_error": error_msg,
            "generation_provider": "",
            "generation_model": model,
        }

    def _report_classified(entry: dict[str, Any]) -> None:
        res = entry["res"]
        cache_marker = " (cached)" if entry["from_cache"] else ""
        outcome = entry.get("generation_outcome", OUTCOME_SEMANTIC_SUCCESS)
        if outcome == OUTCOME_PROVIDER_FAILURE:
            report(
                f"      ⚠ {entry['table']} → classification FAILED: "
                f"{entry.get('generation_error', '(unknown)')}{cache_marker}",
            )
        elif outcome == OUTCOME_UNRESOLVED_ANSWER:
            report(
                f"      ⚠ {entry['table']} → {res['domain']} "
                f"(fallback — model returned unresolvable domain){cache_marker}",
            )
        else:
            report(
                f"      ✓ {entry['table']} → {res['domain']} "
                f"({res['confidence']:.2f}) {res['likely_entity']}{cache_marker}",
            )

    classified = map_concurrent(
        _classify,
        table_items,
        max_workers=max_workers,
        on_result=_report_classified,
    )

    assignments: list[TableAssignment] = []
    for entry in classified:
        tbl_name = entry["table"]
        columns = entry["columns"]
        res = entry["res"]
        outcome = entry.get("generation_outcome", OUTCOME_SEMANTIC_SUCCESS)
        error_msg = entry.get("generation_error", "")
        # DD-159: never cache a failure or fallback — only cache semantic success.
        if (
            cache is not None
            and not entry["from_cache"]
            and entry["cache_key"]
            and outcome == OUTCOME_SEMANTIC_SUCCESS
        ):
            cache.put(entry["cache_key"], res)

        domain_id = res["domain"]
        meta = meta_by_id.get(domain_id, {})

        secondary: list[dict[str, Any]] = []
        for sid in res["secondary_domains"]:
            smeta = meta_by_id.get(sid, {})
            secondary.append(
                {
                    "domain": sid,
                    "domain_group": smeta.get("group", ""),
                    "domain_uris": smeta.get("uris", []),
                }
            )

        ta = TableAssignment(
            table=tbl_name,
            total_columns=len(columns),
            domain=domain_id,
            domain_group=meta.get("group", ""),
            domain_uris=meta.get("uris", []),
            confidence=res["confidence"],
            likely_entity=res["likely_entity"],
            rationale=res["rationale"],
            indicative_columns=res["indicative_columns"],
            secondary_domains=secondary,
            generation_outcome=outcome,
            generation_error=error_msg,
            generation_provider=entry.get("generation_provider", ""),
            generation_model=entry.get("generation_model", ""),
        )
        if outcome != OUTCOME_SEMANTIC_SUCCESS:
            # Normalize failed assignments: empty domain + null confidence.
            ta.domain = ""
            ta.confidence = None
            ta.domain_group = ""
            ta.domain_uris = []
        assignments.append(ta)

    return SourceAnalysis(
        system=sys_name,
        analysed_at=datetime.now(timezone.utc).isoformat(),
        model_used=model,
        table_assignments=assignments,
        sample_evidence=sample_evidence,
    )


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


def write_analysis_output(analysis: SourceAnalysis, output_dir: Path) -> Path:
    """Write table-centric analysis results to YAML.

    Schema (``schema_version: 2``): a flat ``tables[]`` list (one entry per source
    table, each with its single primary ``domain`` + optional ``secondary_domains``)
    plus a ``domain_summary[]`` rollup grouping tables by primary domain.

    Returns the path to the written system affinity file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {
        "system": analysis.system,
        "analysed_at": analysis.analysed_at,
        "model_used": analysis.model_used,
        "schema_version": 2,
        "tables": [],
    }
    if analysis.sample_evidence is not None:
        se = analysis.sample_evidence
        data["sample_evidence"] = {
            "analysed_tables": se.analysed_tables,
            "sampled_tables": se.sampled_tables,
            "coverage_ratio": se.coverage_ratio,
            "threshold": se.threshold,
            "status": "low" if se.warning else "ok",
            "warning": se.warning,
            "missing_sample_tables": se.missing_sample_tables,
        }

    summary: dict[str, dict[str, Any]] = {}
    for ta in analysis.table_assignments:
        table_dict: dict[str, Any] = {
            "table": ta.table,
            "total_columns": ta.total_columns,
            "domain": ta.domain,
            "domain_group": ta.domain_group,
            "domain_uris": ta.domain_uris,
            "confidence": ta.confidence,
            "likely_entity": ta.likely_entity,
            "rationale": ta.rationale,
            "indicative_columns": ta.indicative_columns,
        }
        if ta.secondary_domains:
            table_dict["secondary_domains"] = ta.secondary_domains
        # DD-159: emit generation_* only on non-success so happy-path YAML
        # stays byte-identical (no extra keys).
        if ta.generation_outcome != OUTCOME_SEMANTIC_SUCCESS:
            table_dict["generation_outcome"] = ta.generation_outcome
            if ta.generation_error:
                table_dict["generation_error"] = ta.generation_error
            if ta.generation_provider:
                table_dict["generation_provider"] = ta.generation_provider
            if ta.generation_model:
                table_dict["generation_model"] = ta.generation_model
        data["tables"].append(table_dict)

        entry = summary.setdefault(
            ta.domain,
            {
                "domain": ta.domain,
                "domain_group": ta.domain_group,
                "domain_uris": ta.domain_uris,
                "table_count": 0,
                "tables": [],
            },
        )
        entry["table_count"] += 1
        entry["tables"].append(ta.table)

    data["domain_summary"] = sorted(summary.values(), key=lambda e: e["table_count"], reverse=True)

    output_file = output_dir / f"{analysis.system}-affinity.yaml"
    with open(output_file, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return output_file


def write_affinity_matrix(analyses: list[SourceAnalysis], output_dir: Path) -> Path:
    """Write a summary affinity matrix (per-system primary-domain table counts)."""
    output_dir.mkdir(parents=True, exist_ok=True)

    matrix: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "systems": [],
    }

    for analysis in analyses:
        counts: dict[str, int] = {}
        meta: dict[str, tuple[str, list[str]]] = {}
        for ta in analysis.table_assignments:
            counts[ta.domain] = counts.get(ta.domain, 0) + 1
            meta[ta.domain] = (ta.domain_group, ta.domain_uris)

        domains = [
            {
                "domain": dom,
                **({"domain_group": meta[dom][0]} if meta[dom][0] else {}),
                **({"domain_uris": meta[dom][1]} if meta[dom][1] else {}),
                "table_count": cnt,
            }
            for dom, cnt in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        ]
        matrix["systems"].append({"system": analysis.system, "domains": domains})

    output_file = output_dir / "affinity-matrix.yaml"
    with open(output_file, "w", encoding="utf-8") as f:
        yaml.dump(matrix, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return output_file


# ---------------------------------------------------------------------------
# High-level runner
# ---------------------------------------------------------------------------


def run_analyse_sources(
    sources_dir: Path,
    ref_models_dir: Path,
    output_dir: Path,
    model: str = DEFAULT_MODEL,
    threshold: float = 0.3,
    max_domains: int | None = None,
    domains_filter: list[str] | None = None,
    materialize_dir: Path | None = None,
    catalog_path: Path | None = None,
    exclude_patterns: list[str] | None = None,
    accelerator: str | None = None,
    shallow: bool = False,
    report=None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    force: bool = False,
    cost_warning: bool = False,
) -> list[Path]:
    """Run analysis for all source systems in a hub.

    Two classification strategies:

    * **Data-domain-first** (when ``accelerator`` is given and that pack has a
      ``data-domains.yaml``): classify tables toward the accelerator's *data
      domains* (party, commercial, booking, ...) using their ownership
      descriptions and import URIs. No owl:imports resolution is needed, so this
      path is fast.
    * **Reference-model** (fallback): resolve and group TTL files, classify
      tables against the resulting model-level domains.

    Args:
        sources_dir: Path to integration/sources/ directory
        ref_models_dir: Path to ontology-reference-models/ directory
        output_dir: Where to write analysis output
        model: LLM model to use
        threshold: Minimum affinity confidence to report
        max_domains: Maximum number of reference domains to analyse
        domains_filter: Optional list of domain names to include (substring match)
        materialize_dir: Optional path to write the resolved analysis context
        catalog_path: Optional XML catalog for resolving owl:imports
        exclude_patterns: Glob patterns to exclude from ref models
        accelerator: Accelerator pack name to drive data-domain-first classification
        shallow: Skip owl:imports resolution in the reference-model fallback path
        report: Optional progress reporter (see make_reporter). Defaults to a
            no-op so library callers stay silent; the CLI passes a printing one.

    Returns:
        List of output file paths written.
    """
    if report is None:
        report = _noop_report

    catalog = build_source_catalog(sources_dir)
    catalog.require_consistent()
    source_systems = catalog.analysis_tables()
    obsolete_reports = (
        (
            catalog.generated_report_stems(),
            "generated-dbt-contracts",
            "contract metadata is authoritative",
        ),
        (
            catalog.superseded_report_stems(),
            "superseded-source-layouts",
            "directory-level source identity is authoritative",
        ),
    )
    for stems, archive_name, reason in obsolete_reports:
        for stem in sorted(stems):
            legacy_report = output_dir / f"{stem}-affinity.yaml"
            if not legacy_report.is_file():
                continue
            archive_dir = output_dir / "archive" / archive_name
            archive_dir.mkdir(parents=True, exist_ok=True)
            archived = archive_dir / legacy_report.name
            archived.unlink(missing_ok=True)
            shutil.move(str(legacy_report), archived)
            report(f"  ↪ Archived {legacy_report.name}; {reason}.")
    if not source_systems:
        raise ValueError(f"No non-generated source vocabulary tables found in {sources_dir}")

    # ----- Strategy selection -------------------------------------------------
    strategy: str
    if accelerator:
        report(f"▶ Phase 1/3 — Loading data domains (accelerator: {accelerator})")
        data_domains = load_data_domains(ref_models_dir, accelerator=accelerator)
        if not data_domains:
            available = list_accelerator_packs(ref_models_dir)
            raise ValueError(
                f"No data-domains.yaml found for accelerator '{accelerator}'.\n"
                f"Available accelerator packs: {available or '(none)'}"
            )
        ref_domains = build_data_domain_targets(data_domains)
        strategy = "data-domain-first"
        report(f"  Loaded {len(ref_domains)} data domain(s) from '{accelerator}'.")
        # Ground each data domain with the classes from its directly-imported
        # module TTLs (resolved once per run via the catalog and shared cache).
        if not shallow:
            resolve_domain_class_summaries(ref_domains, catalog_path, report=report)
    else:
        report("▶ Phase 1/3 — Resolving reference models")
        effective_catalog = None if shallow else catalog_path
        ref_domains = resolve_reference_models(
            ref_models_dir,
            catalog_path=effective_catalog,
            exclude_patterns=exclude_patterns,
        )
        if not ref_domains:
            raise ValueError(
                f"No reference model TTL files with classes found in {ref_models_dir}.\n"
                f"Ensure your reference model TTLs contain owl:Class definitions.\n"
                f"The folder may only have owl:imports stubs — sub-module TTLs with "
                f"actual classes should be in subdirectories.\n"
                f"Tip: pass --accelerator <name> to classify against an accelerator "
                f"pack's data domains instead."
            )
        strategy = "reference-model" + (" (shallow)" if shallow else "")
        # Enrich domain summaries with data-domain ownership metadata if available
        data_domains = load_data_domains(ref_models_dir)
        if data_domains:
            for domain in ref_domains:
                domain_name_lower = domain["domain_name"].lower().replace(" ", "-")
                for dd_id, dd_meta in data_domains.items():
                    if dd_id in domain_name_lower or domain_name_lower in dd_id:
                        domain["data_domain_meta"] = dd_meta
                        break

    # --domains is a post-classification OUTPUT filter, NOT a candidate-set
    # restriction (issue #189). Tables are always classified against the full
    # domain set so each table gets its true primary domain; we then keep only
    # the requested domain(s) in the written output. Restricting candidates here
    # would force every table into the filtered domain (or unclassified).
    output_domain_filter = [d.lower() for d in domains_filter] if domains_filter else None
    if output_domain_filter:
        known = {d["domain_name"].lower() for d in ref_domains}
        unmatched = [f for f in output_domain_filter if not any(f in name for name in known)]
        if unmatched:
            report(
                f"  ⚠ --domains value(s) {unmatched} match no domain in the "
                f"candidate set; output for them will be empty.",
            )

    if max_domains and len(ref_domains) > max_domains:
        logger.info(
            "Limiting to %d of %d domains (--max-domains)",
            max_domains,
            len(ref_domains),
        )
        report(
            f"  ⚠ --max-domains={max_domains} truncates the candidate set from "
            f"{len(ref_domains)} domains; classification may be biased toward the "
            f"retained domains. Prefer running without --max-domains for modeling "
            f"evidence.",
        )
        ref_domains = ref_domains[:max_domains]

    # Pre-flight summary
    total_classes = sum(
        len(d.get("classes", [])) or len(d.get("class_summary", [])) for d in ref_domains
    )
    logger.info(
        "Strategy=%s — %d domain(s), %d classes",
        strategy,
        len(ref_domains),
        total_classes,
    )
    report(f"  Strategy: {strategy} — {len(ref_domains)} domain(s) to classify against.")

    # Materialize the resolved analysis context if requested
    output_files: list[Path] = []
    if materialize_dir:
        report(f"▶ Phase 2/3 — Materializing resolved context to {materialize_dir}")
        _materialize_context(ref_domains, ref_models_dir, materialize_dir, strategy)

    report(
        f"▶ Phase 3/3 — Analysing {len(source_systems)} source system(s) "
        f"against {len(ref_domains)} domain(s)"
    )

    analyses: list[SourceAnalysis] = []

    # DD-159: preflight the AI provider before the cost banner and loop,
    # so a missing/misconfigured provider fails fast instead of silently
    # failing every table and caching fabricated fallbacks.
    from .ai_preflight import require_ai_provider
    require_ai_provider(ROLE_ALIGNMENT, model=model, probe=False)

    # Per-table sidecar cache; disabled with --force.
    cache = open_cache(output_dir, "analyse-sources", enabled=not force)

    if cost_warning:
        from ._cost import print_cost_warning

        total_tables = sum(len(tables) for tables in source_systems.values())
        print_cost_warning(
            command="analyse-sources",
            table_count=total_tables,
            max_workers=max_workers,
            model=model,
            force=force,
        )

    for sys_name, tables in sorted(source_systems.items()):
        source_paths = sorted(
            {
                path
                for table in catalog.tables.values()
                if table.system == sys_name and not table.generated
                for path in table.paths
            }
        )
        vocab_path = source_paths[0]
        table_count = len(tables)
        worker_count = min(max_workers, table_count) if table_count else 0
        report(
            f"  • {sys_name} … {table_count} table(s), up to {worker_count} concurrent LLM call(s)"
        )
        analysis = analyse_source_system(
            vocab_path,
            ref_domains,
            model=model,
            threshold=threshold,
            report=report,
            max_workers=max_workers,
            cache=cache,
            system_name=sys_name,
            tables=tables,
        )

        # DD-159: detect total failure for this system — every attempted
        # (non-cached) table was a provider failure. Cached tables are excluded
        # from "attempted" since no LLM call was made.
        attempted = [
            ta for ta in analysis.table_assignments
            if ta.generation_outcome != OUTCOME_SEMANTIC_SUCCESS
        ]
        all_attempted_failed = (
            bool(analysis.table_assignments)
            and all(
                ta.generation_outcome == OUTCOME_PROVIDER_FAILURE
                for ta in analysis.table_assignments
            )
        )
        if all_attempted_failed:
            # Total failure: do NOT write — leave any pre-existing file untouched.
            report(
                f"  ⛔ {sys_name}: total provider failure — "
                f"{len(analysis.table_assignments)} table(s) all failed. "
                f"Affinity file not written."
            )
            raise AffinityTotalFailureError(
                f"Every table in '{sys_name}' failed classification "
                f"({len(analysis.table_assignments)} table(s)). "
                f"No affinity file was written. Check AI provider configuration "
                f"with: kairos-ontology check-ai-config"
            )

        # Partial failure: warn but proceed.
        if attempted:
            report(
                f"  ⚠ {sys_name}: {len(attempted)} table(s) had non-success outcomes "
                f"(partial failure — file will be written with empty domains)."
            )

        # Apply the --domains OUTPUT filter (primary-domain match) after the
        # table was classified against the full candidate set (issue #189).
        if output_domain_filter:
            analysis = _filter_analysis_by_domain(analysis, output_domain_filter)
        analyses.append(analysis)

    # Staged writes: commit all analyses AFTER the loop succeeded.
    for analysis in analyses:
        output_file = write_analysis_output(analysis, output_dir)
        output_files.append(output_file)
        n_tables = len(analysis.table_assignments)
        domains_hit = {ta.domain for ta in analysis.table_assignments}
        if output_domain_filter:
            classified_count = n_tables
            report(
                f"    → {n_tables}/{classified_count} table(s) kept "
                f"(--domains filter) into {len(domains_hit)} domain(s) "
                f"→ {output_file.name}"
            )
        else:
            report(
                f"    → {n_tables} table(s) classified into {len(domains_hit)} "
                f"domain(s) → {output_file.name}"
            )

    cache.flush()

    # Write summary matrix
    if analyses:
        matrix_file = write_affinity_matrix(analyses, output_dir)
        output_files.append(matrix_file)

    return output_files


def _materialize_context(
    ref_domains: list[dict[str, Any]],
    ref_models_dir: Path,
    materialize_dir: Path,
    strategy: str,
) -> None:
    """Write the resolved analysis context (what the LLM sees) for inspection.

    Layout::

        .resolved/
          _manifest.yaml      # strategy, counts, timestamp, toolkit version
          domains/
            <domain>.yaml      # the resolved domain target (name, uris, owns, classes)
    """
    from kairos_ontology import __version__

    domains_dir = materialize_dir / "domains"
    domains_dir.mkdir(parents=True, exist_ok=True)

    manifest_domains: list[dict[str, Any]] = []
    for domain in ref_domains:
        name = domain["domain_name"]
        safe = name.replace(" ", "-").replace("/", "_").lower()
        dd_meta = domain.get("data_domain_meta", {})
        resolved_classes = domain.get("classes") or domain.get("class_summary", [])
        domain_doc: dict[str, Any] = {
            "domain": name,
            "display_name": domain.get("display_name", name),
            "group": domain.get("group", ""),
            "uris": domain.get("uris", []),
            "modules": domain.get("modules", []),
            "owns": dd_meta.get("owns", ""),
            "does_not_own": dd_meta.get("does_not_own", ""),
            "classes": [c.get("name") for c in resolved_classes],
        }
        with open(domains_dir / f"{safe}.yaml", "w", encoding="utf-8") as f:
            yaml.dump(domain_doc, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        manifest_domains.append(
            {
                "domain": name,
                "uris": domain.get("uris", []),
                "n_classes": len(resolved_classes),
            }
        )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "toolkit_version": __version__,
        "strategy": strategy,
        "ref_models_dir": str(ref_models_dir),
        "domain_count": len(ref_domains),
        "domains": manifest_domains,
    }
    with open(materialize_dir / "_manifest.yaml", "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    logger.info("Materialized resolved context to %s", materialize_dir)
