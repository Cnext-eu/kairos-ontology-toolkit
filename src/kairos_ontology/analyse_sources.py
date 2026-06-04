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


def resolve_reference_models(
    ref_models_dir: Path, *, catalog_path: Path | None = None
) -> list[dict[str, Any]]:
    """Discover and resolve reference model TTLs, merging sub-modules by domain.

    Handles modular reference models where root files declare owl:imports
    to sub-modules containing actual class definitions.

    Strategy:
    1. Recursively find all .ttl files
    2. Group by top-level subdirectory (= domain)
    3. Merge all TTLs in each domain into a single graph
    4. If catalog_path is provided, resolve owl:imports for each root file
    5. Skip domains with <=2 classes (likely import stubs only)

    Args:
        ref_models_dir: Directory containing reference model TTL files.
        catalog_path: Optional XML catalog for resolving owl:imports URIs.

    Returns list of domain summaries (same format as parse_reference_model).
    """
    all_ttls = sorted(ref_models_dir.glob("**/*.ttl"))
    if not all_ttls:
        return []

    # Group by domain: use first-level subdirectory as domain key
    # Files at root level are their own domain (one file = one domain)
    domain_groups: dict[str, list[Path]] = {}

    for ttl_path in all_ttls:
        rel = ttl_path.relative_to(ref_models_dir)
        parts = rel.parts

        if len(parts) == 1:
            # Root-level file: domain = stem
            domain_key = ttl_path.stem
        else:
            # Nested: domain = first subdirectory name
            domain_key = parts[0]

        domain_groups.setdefault(domain_key, []).append(ttl_path)

    # Merge each domain group into a single graph
    domains: list[dict[str, Any]] = []

    for domain_key, ttl_files in domain_groups.items():
        if len(ttl_files) == 1 and catalog_path and catalog_path.exists():
            # Single file with catalog: resolve owl:imports
            try:
                from kairos_ontology.catalog_utils import load_graph_with_catalog
                catalog_result = load_graph_with_catalog(ttl_files[0], catalog_path)
                result = parse_reference_model(
                    graph=catalog_result.graph, domain_name=domain_key
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

            result = parse_reference_model(graph=merged, domain_name=domain_key)
            result["ref_source"] = domain_key
            if result["classes"]:
                domains.append(result)

    logger.info(
        "Resolved %d domain(s) from %d TTL file(s) in %s",
        len(domains), len(all_ttls), ref_models_dir,
    )
    return domains


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

    # Format domain classes and properties
    domain_lines = []
    for cls in domain_summary["classes"]:
        props_str = ", ".join(p["name"] for p in cls["properties"][:10])
        comment_str = f" — {cls['comment']}" if cls.get("comment") else ""
        domain_lines.append(f"  - {cls['name']} ({cls['label']}{comment_str}): [{props_str}]")

    return f"""Determine whether this source table contributes data to the given reference model domain.
Focus on the TABLE AS A WHOLE — its name, the column names collectively, and the sample data values.

SOURCE TABLE: {table_name}
COLUMNS AND SAMPLE DATA:
  | Column | Type | Sample Values |
{chr(10).join(col_lines)}

REFERENCE MODEL DOMAIN: {domain_summary['domain_name']}
CLASSES:
{chr(10).join(domain_lines)}

Answer these questions:
1. Does this table's subject matter (name + data patterns) belong to this domain?
2. Which reference model class does this table most likely feed data into?
3. Which columns are most indicative of domain membership (top 3-5)?

Respond with JSON only:
{{
  "domain_relevance": 0.0-1.0,
  "rationale": "1-2 sentence explanation of why this table fits or doesn't fit",
  "likely_entity": "ClassName or empty string if no clear match",
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


def analyse_source_system(
    source_vocab_path: Path,
    ref_domains: list[dict[str, Any]],
    model: str = DEFAULT_MODEL,
    threshold: float = 0.3,
) -> SourceAnalysis:
    """Analyse one source system against pre-resolved reference model domains.

    Args:
        source_vocab_path: Path to the source system's .vocabulary.ttl
        ref_domains: Pre-parsed domain summaries (from resolve_reference_models)
        model: LLM model name
        threshold: Minimum domain relevance to include in output

    Returns:
        SourceAnalysis with domain affinities and table-level match details.
    """
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
                {"domain": a.domain, "confidence": a.confidence}
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
) -> list[Path]:
    """Run analysis for all source systems in a hub.

    Args:
        sources_dir: Path to integration/sources/ directory
        ref_models_dir: Path to ontology-reference-models/ directory
        output_dir: Where to write analysis output
        model: LLM model to use
        threshold: Minimum affinity confidence to report
        max_domains: Maximum number of reference domains to analyse (rate limit protection)
        domains_filter: Optional list of domain names to include (case-insensitive substring)
        materialize_dir: Optional path to write merged TTLs for inspection
        catalog_path: Optional XML catalog for resolving owl:imports in reference models

    Returns:
        List of output file paths written.
    """
    # Find all source vocabulary files
    vocab_files = sorted(sources_dir.glob("*/*.vocabulary.ttl"))
    if not vocab_files:
        raise ValueError(f"No source vocabulary files found in {sources_dir}")

    # Resolve reference models (recursive discovery + merge)
    ref_domains = resolve_reference_models(ref_models_dir, catalog_path=catalog_path)
    if not ref_domains:
        raise ValueError(
            f"No reference model TTL files with classes found in {ref_models_dir}.\n"
            f"Ensure your reference model TTLs contain owl:Class definitions.\n"
            f"The folder may only have owl:imports stubs — sub-module TTLs with "
            f"actual classes should be in subdirectories."
        )

    # Apply --domains filter
    if domains_filter:
        filter_lower = [d.lower() for d in domains_filter]
        ref_domains = [
            d for d in ref_domains
            if any(f in d["domain_name"].lower() for f in filter_lower)
        ]
        if not ref_domains:
            raise ValueError(
                f"No domains matched filter: {domains_filter}. "
                f"Available domains: {[d['domain_name'] for d in resolve_reference_models(ref_models_dir)]}"
            )

    if max_domains and len(ref_domains) > max_domains:
        logger.info(
            "Limiting to %d of %d domains (--max-domains)",
            max_domains, len(ref_domains),
        )
        ref_domains = ref_domains[:max_domains]

    # Pre-flight summary
    total_classes = sum(len(d.get("classes", [])) for d in ref_domains)
    total_props = sum(
        sum(len(c.get("properties", [])) for c in d.get("classes", []))
        for d in ref_domains
    )
    logger.info(
        "Resolved %d domain(s) with %d classes, %d properties",
        len(ref_domains), total_classes, total_props,
    )

    # Materialize merged TTLs if requested
    if materialize_dir:
        _materialize_domains(ref_domains, ref_models_dir, materialize_dir)

    logger.info(
        "Analysing %d source system(s) against %d reference domain(s)",
        len(vocab_files), len(ref_domains),
    )

    analyses: list[SourceAnalysis] = []
    output_files: list[Path] = []

    for vocab_path in vocab_files:
        logger.info("Analysing source: %s", vocab_path.stem)
        analysis = analyse_source_system(
            vocab_path, ref_domains, model=model, threshold=threshold
        )
        analyses.append(analysis)

        output_file = write_analysis_output(analysis, output_dir)
        output_files.append(output_file)
        logger.info("  → Written: %s", output_file.name)

    # Write summary matrix
    if analyses:
        matrix_file = write_affinity_matrix(analyses, output_dir)
        output_files.append(matrix_file)

    return output_files


def _materialize_domains(
    ref_domains: list[dict[str, Any]],
    ref_models_dir: Path,
    materialize_dir: Path,
) -> None:
    """Write merged TTLs per domain to disk for inspection."""
    materialize_dir.mkdir(parents=True, exist_ok=True)
    for domain in ref_domains:
        domain_name = domain["domain_name"].replace(" ", "-").replace("/", "_").lower()
        ref_source = domain.get("ref_source", domain_name)

        # Re-parse and merge the source files for this domain
        source_dir = ref_models_dir / ref_source
        if source_dir.is_dir():
            merged = Graph()
            for ttl in sorted(source_dir.glob("**/*.ttl")):
                try:
                    merged.parse(ttl, format="turtle")
                except Exception:
                    pass
            out_path = materialize_dir / f"{domain_name}.ttl"
            merged.serialize(destination=str(out_path), format="turtle")
            logger.info("  Materialized: %s (%d triples)", out_path.name, len(merged))
