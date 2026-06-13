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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef

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
    confidence: float = 0.0
    likely_entity: str = ""
    rationale: str = ""
    indicative_columns: list[str] = field(default_factory=list)
    # Each entry: {"domain", "domain_group", "domain_uris"}
    secondary_domains: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SourceAnalysis:
    """Complete analysis result for one source system."""
    system: str
    analysed_at: str
    model_used: str
    table_assignments: list[TableAssignment] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Source vocabulary parsing
# ---------------------------------------------------------------------------


def parse_source_vocabulary(vocab_path: Path) -> dict[str, list[dict[str, Any]]]:
    """Parse a bronze vocabulary TTL file into a table→columns structure.

    Returns dict mapping table_name → list of column dicts with
    {name, data_type, nullable, samples}.
    """
    g = Graph()
    g.parse(vocab_path, format="turtle")

    tables: dict[str, list[dict[str, Any]]] = {}

    # Find all source tables
    for tbl_uri in g.subjects(RDF.type, KAIROS_BRONZE.SourceTable):
        tbl_name = str(g.value(tbl_uri, KAIROS_BRONZE.tableName) or
                       tbl_uri.split("#")[-1].split("/")[-1])
        columns = []

        # Find columns belonging to this table (both predicates are used)
        col_uris = set(g.subjects(KAIROS_BRONZE.belongsToTable, tbl_uri))
        col_uris.update(g.subjects(KAIROS_BRONZE.sourceTable, tbl_uri))
        for col_uri in col_uris:
            col_name = str(g.value(col_uri, KAIROS_BRONZE.columnName) or
                           col_uri.split("#")[-1].split("/")[-1])
            data_type = str(g.value(col_uri, KAIROS_BRONZE.dataType) or "unknown")
            nullable = bool(g.value(col_uri, KAIROS_BRONZE.nullable))
            samples_raw = g.value(col_uri, KAIROS_BRONZE.sampleValues)
            samples = str(samples_raw).split(" | ") if samples_raw else []

            columns.append({
                "name": col_name,
                "data_type": data_type,
                "nullable": nullable,
                "samples": samples,
            })

        tables[tbl_name] = columns

    return tables


# ---------------------------------------------------------------------------
# Reference model parsing
# ---------------------------------------------------------------------------


def parse_reference_model(ttl_path: Path | None = None, *, graph: Graph | None = None,
                          domain_name: str | None = None,
                          include_specializations: bool = False) -> dict[str, Any]:
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
        g = Graph()
        g.parse(ttl_path, format="turtle")
    else:
        raise ValueError("Either ttl_path or graph must be provided")

    # Get ontology metadata
    resolved_name = domain_name or (ttl_path.stem if ttl_path else "unknown")
    for ont in g.subjects(RDF.type, OWL.Ontology):
        label = g.value(ont, RDFS.label)
        if label:
            resolved_name = str(label)
        break

    classes: list[dict[str, Any]] = []

    for cls_uri in g.subjects(RDF.type, OWL.Class):
        # Skip blank nodes
        if not isinstance(cls_uri, URIRef):
            continue
        cls_name = cls_uri.split("#")[-1].split("/")[-1]
        cls_label = str(g.value(cls_uri, RDFS.label) or cls_name)
        cls_comment = str(g.value(cls_uri, RDFS.comment) or "")

        # Find properties with this class as domain
        properties: list[dict[str, str]] = []
        for prop_uri in g.subjects(RDFS.domain, cls_uri):
            prop_name = prop_uri.split("#")[-1].split("/")[-1]
            prop_label = str(g.value(prop_uri, RDFS.label) or prop_name)
            prop_range = ""
            range_val = g.value(prop_uri, RDFS.range)
            if range_val:
                prop_range = range_val.split("#")[-1].split("/")[-1]
            properties.append({
                "name": prop_name,
                "label": prop_label,
                "range": prop_range,
            })

        cls_dict: dict[str, Any] = {
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
                prop_label = str(graph.value(prop_uri, RDFS.label) or prop_name)
                prop_range = ""
                range_val = graph.value(prop_uri, RDFS.range)
                if range_val:
                    prop_range = str(range_val).split("#")[-1].split("/")[-1]
                prop_type = "datatype"
                if (prop_uri, RDF.type, OWL.ObjectProperty) in graph:
                    prop_type = "object"
                child_props.append({
                    "name": prop_name,
                    "label": prop_label,
                    "range": prop_range,
                    "type": prop_type,
                })

            result.append({
                "class": child_name,
                "class_uri": child_str,
                "distance": depth + 1,
                "properties": child_props,
            })

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

    Args:
        ref_models_dir: Directory containing reference model TTL files.
        catalog_path: Optional XML catalog for resolving owl:imports URIs.
        exclude_patterns: Glob patterns to exclude (e.g. ``["archive/**"]``).
        include_specializations: Walk subClassOf downward per class (DD-044).

    Returns list of domain summaries (same format as parse_reference_model).
    """
    all_ttls = sorted(ref_models_dir.glob("**/*.ttl"))
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

    # Merge each domain group into a single graph
    domains: list[dict[str, Any]] = []

    for domain_key, ttl_files in domain_groups.items():
        display_name = _domain_display_name(domain_key)

        if len(ttl_files) == 1 and catalog_path and catalog_path.exists():
            # Single file with catalog: resolve owl:imports
            try:
                from kairos_ontology.catalog_utils import load_graph_with_catalog
                catalog_result = load_graph_with_catalog(ttl_files[0], catalog_path)
                result = parse_reference_model(
                    graph=catalog_result.graph, domain_name=display_name,
                    include_specializations=include_specializations,
                )
                result["ref_source"] = domain_key
                result["file"] = str(ttl_files[0])
                if result["classes"]:
                    domains.append(result)
            except Exception as e:
                logger.warning(
                    "Catalog resolution failed for %s, falling back: %s",
                    ttl_files[0], e,
                )
                # Fall back to simple parse
                try:
                    result = parse_reference_model(
                        ttl_files[0],
                        include_specializations=include_specializations,
                    )
                    if result["classes"]:
                        result["ref_source"] = domain_key
                        domains.append(result)
                except Exception as e2:
                    logger.warning("Failed to parse %s: %s", ttl_files[0], e2)
        elif len(ttl_files) == 1:
            # Single file without catalog: parse directly
            try:
                result = parse_reference_model(
                    ttl_files[0],
                    include_specializations=include_specializations,
                )
                if result["classes"]:
                    result["ref_source"] = domain_key
                    domains.append(result)
            except Exception as e:
                logger.warning("Failed to parse %s: %s", ttl_files[0], e)
        else:
            # Multiple files: merge into single graph
            merged = Graph()
            for ttl in ttl_files:
                try:
                    merged.parse(ttl, format="turtle")
                except Exception as e:
                    logger.warning("Failed to parse %s: %s", ttl, e)

            if catalog_path and catalog_path.exists():
                # Also resolve owl:imports from merged graph
                try:
                    from kairos_ontology.catalog_utils import CatalogResolver
                    resolver = CatalogResolver(catalog_path)
                    for import_uri in list(merged.objects(predicate=OWL.imports)):
                        import_str = str(import_uri)
                        if import_str.startswith("file://"):
                            continue
                        resolved = resolver.resolve(import_str)
                        if resolved and Path(resolved).exists():
                            try:
                                merged.parse(resolved, format="turtle")
                            except Exception:
                                pass
                except Exception as e:
                    logger.debug("Catalog import resolution skipped: %s", e)

            result = parse_reference_model(
                graph=merged, domain_name=display_name,
                include_specializations=include_specializations,
            )
            result["ref_source"] = domain_key
            if result["classes"]:
                domains.append(result)

    logger.info(
        "Resolved %d domain(s) from %d TTL file(s) in %s",
        len(domains), len(all_ttls), ref_models_dir,
    )
    return domains


def load_data_domains(ref_models_dir: Path, accelerator: str | None = None) -> dict[str, dict[str, Any]]:
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

    for dd_path in ref_models_dir.glob(glob_pattern):
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
                    }
            logger.info("Loaded %d data domains from %s", len(result), dd_path)
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
        targets.append({
            "domain_name": dd_id,
            "display_name": dd_meta.get("name", dd_id),
            "group": dd_meta.get("group", ""),
            "uris": dd_meta.get("uris", []),
            "modules": dd_meta.get("modules", []),
            "file": "data-domains.yaml",
            "ref_source": dd_meta.get("group", ""),
            "classes": [],
            "data_domain_meta": dd_meta,
        })
    return targets


# ---------------------------------------------------------------------------
# Semantic grounding — resolve directly-imported module classes
# ---------------------------------------------------------------------------


def _module_format(path: Path) -> str:
    """Best-effort RDF format from a file suffix (defaults to turtle)."""
    return {".ttl": "turtle", ".owl": "xml", ".rdf": "xml",
            ".jsonld": "json-ld", ".nt": "nt"}.get(path.suffix.lower(), "turtle")


def _resolve_module_classes(
    path: Path, cache: dict[str, list[dict[str, str]]],
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
            label = str(g.value(cls_uri, RDFS.label) or name)
            comment = str(g.value(cls_uri, RDFS.comment) or "")
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
        from kairos_ontology.catalog_utils import CatalogResolver
        resolver = CatalogResolver(Path(catalog_path))
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
    classes: list[dict[str, Any]], cap: int = MAX_DOMAIN_CLASSES,
) -> list[dict[str, str]]:
    """Trim a full class list down to a capped {name,label,comment} summary."""
    out: list[dict[str, str]] = []
    for c in classes[:cap]:
        out.append({
            "name": c.get("name", ""),
            "label": c.get("label", "") or c.get("name", ""),
            "comment": c.get("comment", ""),
        })
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
        candidates.append({
            "id": d["domain_name"],
            "group": d.get("group", ""),
            "uris": d.get("uris", []),
            "owns": dd_meta.get("owns", ""),
            "does_not_own": dd_meta.get("does_not_own", ""),
            "class_summary": class_summary,
        })
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


def _get_openai_client():
    """Create an OpenAI client configured for the active AI provider."""
    from kairos_ontology.ai_provider import get_ai_client
    return get_ai_client()


def _format_columns(columns: list[dict[str, Any]]) -> str:
    """Render columns as a markdown-ish table with up to 3 sample values each."""
    col_lines = []
    for col in columns:
        samples_str = ", ".join(col["samples"][:3]) if col.get("samples") else ""
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

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "You are an expert data architect. You classify source system "
                    "tables into business data domains based on table names, column "
                    "names, and sample data values. You always pick exactly one "
                    "primary domain. Always respond with valid JSON."
                )},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.warning("LLM single-call analysis failed for table %s: %s", table_name, e)
        result = {}
    if not isinstance(result, dict):
        result = {}

    matched = _resolve_domain_id(result.get("domain", ""), candidate_ids)
    if matched is not None:
        domain_id = matched
        confidence = _coerce_confidence(result.get("confidence"))
        likely_entity = str(result.get("likely_entity", "") or "")
        rationale = str(result.get("rationale", "") or "")
        indicative = _as_str_list(result.get("indicative_columns"))
    else:
        domain_id = _pick_fallback(valid_ids, fallback_ids)
        confidence = 0.0
        likely_entity = ""
        rationale = (
            str(result.get("rationale", "") or "")
            or f"Model returned no valid domain; fell back to '{domain_id}'."
        )
        indicative = []

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

    Returns:
        SourceAnalysis with one TableAssignment per (non-empty) source table.
    """
    if report is None:
        report = _noop_report

    sys_name = source_vocab_path.stem.replace(".vocabulary", "")
    tables = parse_source_vocabulary(source_vocab_path)
    if not tables:
        logger.warning("No tables found in %s", source_vocab_path)
        return SourceAnalysis(
            system=sys_name,
            analysed_at=datetime.now(timezone.utc).isoformat(),
            model_used=model,
        )

    client = _get_openai_client()
    candidates = _build_candidates(ref_domains)
    meta_by_id = {c["id"]: c for c in candidates}

    assignments: list[TableAssignment] = []
    for tbl_name, columns in tables.items():
        if not columns:
            continue

        res = analyse_table_single_call(client, model, tbl_name, columns, candidates)
        domain_id = res["domain"]
        meta = meta_by_id.get(domain_id, {})

        secondary: list[dict[str, Any]] = []
        for sid in res["secondary_domains"]:
            smeta = meta_by_id.get(sid, {})
            secondary.append({
                "domain": sid,
                "domain_group": smeta.get("group", ""),
                "domain_uris": smeta.get("uris", []),
            })

        report(
            f"      ├─ {tbl_name} → {domain_id} "
            f"({res['confidence']:.2f}) {res['likely_entity']}",
            level="verbose",
        )
        assignments.append(TableAssignment(
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
        ))

    return SourceAnalysis(
        system=sys_name,
        analysed_at=datetime.now(timezone.utc).isoformat(),
        model_used=model,
        table_assignments=assignments,
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
        data["tables"].append(table_dict)

        entry = summary.setdefault(ta.domain, {
            "domain": ta.domain,
            "domain_group": ta.domain_group,
            "domain_uris": ta.domain_uris,
            "table_count": 0,
            "tables": [],
        })
        entry["table_count"] += 1
        entry["tables"].append(ta.table)

    data["domain_summary"] = sorted(
        summary.values(), key=lambda e: e["table_count"], reverse=True
    )

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

    # Find all source vocabulary files
    vocab_files = sorted(sources_dir.glob("*/*.vocabulary.ttl"))
    if not vocab_files:
        raise ValueError(f"No source vocabulary files found in {sources_dir}")

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

    # Apply --domains filter
    if domains_filter:
        filter_lower = [d.lower() for d in domains_filter]
        ref_domains = [
            d for d in ref_domains
            if any(f in d["domain_name"].lower() for f in filter_lower)
        ]
        if not ref_domains:
            raise ValueError(
                f"No domains matched filter: {domains_filter}."
            )

    if max_domains and len(ref_domains) > max_domains:
        logger.info(
            "Limiting to %d of %d domains (--max-domains)",
            max_domains, len(ref_domains),
        )
        ref_domains = ref_domains[:max_domains]

    # Pre-flight summary
    total_classes = sum(
        len(d.get("classes", [])) or len(d.get("class_summary", []))
        for d in ref_domains
    )
    logger.info(
        "Strategy=%s — %d domain(s), %d classes",
        strategy, len(ref_domains), total_classes,
    )
    report(
        f"  Strategy: {strategy} — {len(ref_domains)} domain(s) to classify against."
    )

    # Materialize the resolved analysis context if requested
    output_files: list[Path] = []
    if materialize_dir:
        report(f"▶ Phase 2/3 — Materializing resolved context to {materialize_dir}")
        _materialize_context(ref_domains, ref_models_dir, materialize_dir, strategy)

    report(
        f"▶ Phase 3/3 — Analysing {len(vocab_files)} source system(s) "
        f"against {len(ref_domains)} domain(s)"
    )

    analyses: list[SourceAnalysis] = []

    for vocab_path in vocab_files:
        sys_name = vocab_path.stem.replace(".vocabulary", "")
        report(f"  • {sys_name} …")
        analysis = analyse_source_system(
            vocab_path, ref_domains, model=model, threshold=threshold, report=report
        )
        analyses.append(analysis)

        output_file = write_analysis_output(analysis, output_dir)
        output_files.append(output_file)
        n_tables = len(analysis.table_assignments)
        domains_hit = {ta.domain for ta in analysis.table_assignments}
        report(
            f"    → {n_tables} table(s) classified into {len(domains_hit)} "
            f"domain(s) → {output_file.name}"
        )

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
            yaml.dump(domain_doc, f, default_flow_style=False, sort_keys=False,
                      allow_unicode=True)
        manifest_domains.append({
            "domain": name,
            "uris": domain.get("uris", []),
            "n_classes": len(resolved_classes),
        })

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "toolkit_version": __version__,
        "strategy": strategy,
        "ref_models_dir": str(ref_models_dir),
        "domain_count": len(ref_domains),
        "domains": manifest_domains,
    }
    with open(materialize_dir / "_manifest.yaml", "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, default_flow_style=False, sort_keys=False,
                  allow_unicode=True)
    logger.info("Materialized resolved context to %s", materialize_dir)
