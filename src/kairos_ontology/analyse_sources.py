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

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TableMatch:
    """Match result for a single source table against a reference model domain."""
    table: str
    total_columns: int
    domain_relevance: float = 0.0
    rationale: str = ""
    likely_entity: str = ""
    indicative_columns: list[str] = field(default_factory=list)


@dataclass
class DomainAffinity:
    """Affinity score of a source system to a reference model domain."""
    domain: str
    ref_model_file: str
    confidence: float
    total_classes: int = 0
    ref_source: str = ""
    matched_tables: list[TableMatch] = field(default_factory=list)
    domain_uris: list[str] = field(default_factory=list)
    group: str = ""


@dataclass
class SourceAnalysis:
    """Complete analysis result for one source system."""
    system: str
    analysed_at: str
    model_used: str
    domain_affinities: list[DomainAffinity] = field(default_factory=list)


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
                          domain_name: str | None = None) -> dict[str, Any]:
    """Parse a reference model TTL file (or pre-loaded graph) into a domain summary.

    Args:
        ttl_path: Path to a single TTL file (mutually exclusive with graph)
        graph: Pre-loaded rdflib Graph (used for merged multi-file domains)
        domain_name: Override domain name (used with graph parameter)

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

        classes.append({
            "name": cls_name,
            "label": cls_label,
            "comment": cls_comment,
            "properties": properties,
        })

    return {
        "domain_name": resolved_name,
        "file": ttl_path.name if ttl_path else "(merged)",
        "classes": classes,
    }


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
                    graph=catalog_result.graph, domain_name=display_name
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
                    result = parse_reference_model(ttl_files[0])
                    if result["classes"]:
                        result["ref_source"] = domain_key
                        domains.append(result)
                except Exception as e2:
                    logger.warning("Failed to parse %s: %s", ttl_files[0], e2)
        elif len(ttl_files) == 1:
            # Single file without catalog: parse directly
            try:
                result = parse_reference_model(ttl_files[0])
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

            result = parse_reference_model(graph=merged, domain_name=display_name)
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
# LLM client
# ---------------------------------------------------------------------------


def _get_openai_client():
    """Create an OpenAI client configured for the active AI provider."""
    from kairos_ontology.ai_provider import get_ai_client
    return get_ai_client()


def _build_analysis_prompt(
    table_name: str,
    columns: list[dict[str, Any]],
    domain_summary: dict[str, Any],
) -> str:
    """Build the LLM prompt for classifying one table against one domain."""
    # Format columns as a table with sample data
    col_lines = []
    for col in columns:
        samples_str = ", ".join(col["samples"][:3]) if col.get("samples") else ""
        col_lines.append(f"  | {col['name']} | {col['data_type']} | {samples_str} |")

    dd_meta = domain_summary.get("data_domain_meta")
    classes = domain_summary.get("classes", [])

    # Build the domain description block. Two modes:
    #   1. Data-domain-first (no classes): describe the domain via its ownership.
    #   2. Reference-model (has classes): list classes + properties.
    if not classes and dd_meta:
        display = domain_summary.get("display_name") or domain_summary["domain_name"]
        group = domain_summary.get("group", "")
        uris = domain_summary.get("uris", [])
        group_line = f"\nDOMAIN GROUP: {group}" if group else ""
        uri_line = (
            "\nMODEL URIs: " + ", ".join(uris) if uris else ""
        )
        domain_block = f"""DATA DOMAIN: {domain_summary['domain_name']} — {display}{group_line}{uri_line}

This domain OWNS: {dd_meta.get('owns', 'not specified')}
This domain does NOT own: {dd_meta.get('does_not_own', 'not specified')}

Classify the table against this DATA DOMAIN based on its subject matter and
the ownership boundaries above — not against individual classes."""
        entity_question = (
            "2. If it belongs, what business entity name best describes the table's "
            "subject (free text, e.g. \"SalesContract\", \"PartyAddress\")?"
        )
        entity_hint = "Business entity name or empty string if no clear match"
    else:
        domain_lines = []
        for cls in classes:
            props_str = ", ".join(p["name"] for p in cls["properties"][:10])
            comment_str = f" — {cls['comment']}" if cls.get("comment") else ""
            domain_lines.append(
                f"  - {cls['name']} ({cls['label']}{comment_str}): [{props_str}]"
            )

        ownership_section = ""
        if dd_meta:
            ownership_section = f"""
DOMAIN OWNERSHIP CONTEXT:
  This domain OWNS: {dd_meta.get('owns', 'not specified')}
  This domain does NOT own: {dd_meta.get('does_not_own', 'not specified')}
"""
        domain_block = f"""REFERENCE MODEL DOMAIN: {domain_summary['domain_name']}
CLASSES:
{chr(10).join(domain_lines)}
{ownership_section}"""
        entity_question = (
            "2. Which reference model class does this table most likely feed data into?"
        )
        entity_hint = "ClassName or empty string if no clear match"

    return f"""Determine whether this source table contributes data to the given reference model domain.
Focus on the TABLE AS A WHOLE — its name, the column names collectively, and the sample data values.

SOURCE TABLE: {table_name}
COLUMNS AND SAMPLE DATA:
  | Column | Type | Sample Values |
{chr(10).join(col_lines)}

{domain_block}
Answer these questions:
1. Does this table's subject matter (name + data patterns) belong to this domain?
{entity_question}
3. Which columns are most indicative of domain membership (top 3-5)?

Respond with JSON only:
{{
  "domain_relevance": 0.0-1.0,
  "rationale": "1-2 sentence explanation of why this table fits or doesn't fit",
  "likely_entity": "{entity_hint}",
  "indicative_columns": ["col1", "col2", "col3"]
}}"""


def analyse_table_against_domain(
    client,
    model: str,
    table_name: str,
    columns: list[dict[str, Any]],
    domain_summary: dict[str, Any],
) -> dict[str, Any]:
    """Use LLM to classify one source table's affinity to one domain."""
    prompt = _build_analysis_prompt(table_name, columns, domain_summary)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "You are an expert data architect. You classify source system "
                    "tables by determining which business domain they belong to, "
                    "based on table names, column names, and sample data values. "
                    "Always respond with valid JSON."
                )},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        logger.warning("LLM analysis failed for table %s: %s", table_name, e)
        return {"domain_relevance": 0.0, "rationale": "", "likely_entity": "",
                "indicative_columns": []}


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
    """Analyse one source system against pre-resolved reference model domains.

    Args:
        source_vocab_path: Path to the source system's .vocabulary.ttl
        ref_domains: Pre-parsed domain summaries (from resolve_reference_models)
        model: LLM model name
        threshold: Minimum domain relevance to include in output
        report: Optional progress reporter (see make_reporter)

    Returns:
        SourceAnalysis with domain affinities and table-level match details.
    """
    if report is None:
        report = _noop_report
    client = _get_openai_client()

    tables = parse_source_vocabulary(source_vocab_path)
    if not tables:
        logger.warning("No tables found in %s", source_vocab_path)
        return SourceAnalysis(
            system=source_vocab_path.stem.replace(".vocabulary", ""),
            analysed_at=datetime.now(timezone.utc).isoformat(),
            model_used=model,
        )

    domain_results: dict[str, DomainAffinity] = {}

    for domain in ref_domains:
        domain_key = domain["domain_name"]
        table_matches: list[TableMatch] = []
        total_relevance = 0.0

        for tbl_name, columns in tables.items():
            if not columns:
                continue

            result = analyse_table_against_domain(
                client, model, tbl_name, columns, domain
            )

            relevance = result.get("domain_relevance", 0.0)
            total_relevance += relevance

            if relevance >= threshold:
                report(
                    f"      ├─ {tbl_name} → {domain_key} "
                    f"({relevance:.2f}) {result.get('likely_entity', '')}",
                    level="verbose",
                )
                table_matches.append(TableMatch(
                    table=tbl_name,
                    total_columns=len(columns),
                    domain_relevance=round(relevance, 2),
                    rationale=result.get("rationale", ""),
                    likely_entity=result.get("likely_entity", ""),
                    indicative_columns=result.get("indicative_columns", []),
                ))

        if table_matches:
            avg_relevance = total_relevance / len(tables) if tables else 0.0
            domain_results[domain_key] = DomainAffinity(
                domain=domain_key,
                ref_model_file=domain["file"],
                confidence=round(avg_relevance, 2),
                total_classes=len(domain.get("classes", [])),
                ref_source=domain.get("ref_source", ""),
                matched_tables=table_matches,
                domain_uris=domain.get("uris", []),
                group=domain.get("group", ""),
            )

    sys_name = source_vocab_path.stem.replace(".vocabulary", "")
    affinities = sorted(domain_results.values(), key=lambda d: d.confidence, reverse=True)

    return SourceAnalysis(
        system=sys_name,
        analysed_at=datetime.now(timezone.utc).isoformat(),
        model_used=model,
        domain_affinities=affinities,
    )


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


def write_analysis_output(analysis: SourceAnalysis, output_dir: Path) -> Path:
    """Write analysis results to YAML in domain_contributions format.

    Returns the path to the written system affinity file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {
        "system": analysis.system,
        "analysed_at": analysis.analysed_at,
        "model_used": analysis.model_used,
        "domain_contributions": [],
    }

    for aff in analysis.domain_affinities:
        domain_dict: dict[str, Any] = {
            "domain": aff.domain,
            "ref_source": aff.ref_source or aff.ref_model_file,
            "confidence": aff.confidence,
            "total_classes": aff.total_classes,
            "contributing_tables": [],
        }
        if aff.group:
            domain_dict["group"] = aff.group
        if aff.domain_uris:
            domain_dict["domain_uris"] = aff.domain_uris
        for tm in aff.matched_tables:
            table_dict: dict[str, Any] = {
                "table": tm.table,
                "domain_relevance": tm.domain_relevance,
                "rationale": tm.rationale,
                "likely_entity": tm.likely_entity,
                "indicative_columns": tm.indicative_columns,
            }
            domain_dict["contributing_tables"].append(table_dict)
        data["domain_contributions"].append(domain_dict)

    output_file = output_dir / f"{analysis.system}-affinity.yaml"
    with open(output_file, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return output_file


def write_affinity_matrix(analyses: list[SourceAnalysis], output_dir: Path) -> Path:
    """Write a summary affinity matrix across all analysed sources."""
    output_dir.mkdir(parents=True, exist_ok=True)

    matrix: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "systems": [],
    }

    for analysis in analyses:
        sys_entry: dict[str, Any] = {
            "system": analysis.system,
            "domains": [
                {
                    "domain": a.domain,
                    "confidence": a.confidence,
                    **({"group": a.group} if a.group else {}),
                    **({"domain_uris": a.domain_uris} if a.domain_uris else {}),
                }
                for a in analysis.domain_affinities
            ],
        }
        matrix["systems"].append(sys_entry)

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
    total_classes = sum(len(d.get("classes", [])) for d in ref_domains)
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
        n_dom = len(analysis.domain_affinities)
        top = analysis.domain_affinities[0].domain if analysis.domain_affinities else "—"
        report(f"    → {n_dom} domain(s) matched (top: {top}) → {output_file.name}")

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
        domain_doc: dict[str, Any] = {
            "domain": name,
            "display_name": domain.get("display_name", name),
            "group": domain.get("group", ""),
            "uris": domain.get("uris", []),
            "modules": domain.get("modules", []),
            "owns": dd_meta.get("owns", ""),
            "does_not_own": dd_meta.get("does_not_own", ""),
            "classes": [c.get("name") for c in domain.get("classes", [])],
        }
        with open(domains_dir / f"{safe}.yaml", "w", encoding="utf-8") as f:
            yaml.dump(domain_doc, f, default_flow_style=False, sort_keys=False,
                      allow_unicode=True)
        manifest_domains.append({
            "domain": name,
            "uris": domain.get("uris", []),
            "n_classes": len(domain.get("classes", [])),
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
