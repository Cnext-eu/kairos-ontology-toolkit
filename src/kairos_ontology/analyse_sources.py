# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""LLM-powered source-to-domain affinity analysis.

Matches source vocabulary columns against reference model properties using
the GitHub Models API (gpt-5-mini). Produces per-source affinity reports
that the modeling skill uses to scope context and seed evidence tables.

Requires GITHUB_TOKEN environment variable.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from rdflib import Graph, Namespace, RDF, RDFS, OWL, Literal, URIRef
from rdflib.namespace import XSD

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"
DEFAULT_MODEL = "gpt-5-mini"

KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ColumnSuggestion:
    """A suggested mapping from a source column to a reference model property."""
    column: str
    ref_property: str
    confidence: float
    evidence: str


@dataclass
class TableMatch:
    """Match result for a single source table against a reference model domain."""
    table: str
    total_columns: int
    matched_columns: int
    suggestions: list[ColumnSuggestion] = field(default_factory=list)
    unmatched_columns: list[dict[str, str]] = field(default_factory=list)


@dataclass
class DomainAffinity:
    """Affinity score of a source system to a reference model domain."""
    domain: str
    ref_model_file: str
    confidence: float
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

        # Find columns belonging to this table
        for col_uri in g.subjects(KAIROS_BRONZE.belongsToTable, tbl_uri):
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


def parse_reference_model(ttl_path: Path) -> dict[str, Any]:
    """Parse a reference model TTL file into a domain summary.

    Returns dict with domain_name, classes (with properties and labels).
    """
    g = Graph()
    g.parse(ttl_path, format="turtle")

    # Get ontology metadata
    domain_name = ttl_path.stem
    for ont in g.subjects(RDF.type, OWL.Ontology):
        label = g.value(ont, RDFS.label)
        if label:
            domain_name = str(label)
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
        "domain_name": domain_name,
        "file": ttl_path.name,
        "classes": classes,
    }


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------


def _get_openai_client():
    """Create an OpenAI client configured for GitHub Models API."""
    from openai import OpenAI

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise EnvironmentError(
            "GITHUB_TOKEN environment variable is required for source analysis. "
            "Set it to a GitHub personal access token."
        )

    return OpenAI(
        base_url=GITHUB_MODELS_ENDPOINT,
        api_key=token,
    )


def _build_analysis_prompt(
    table_name: str,
    columns: list[dict[str, Any]],
    domain_summary: dict[str, Any],
) -> str:
    """Build the LLM prompt for matching one table against one domain."""
    # Format columns
    col_lines = []
    for col in columns:
        samples_str = f" (samples: {', '.join(col['samples'][:3])})" if col.get("samples") else ""
        col_lines.append(f"  - {col['name']} ({col['data_type']}){samples_str}")

    # Format domain classes and properties
    domain_lines = []
    for cls in domain_summary["classes"]:
        props_str = ", ".join(p["name"] for p in cls["properties"][:15])
        domain_lines.append(f"  - {cls['name']} ({cls['label']}): [{props_str}]")

    return f"""Analyse this source table and determine how well it maps to the reference model domain.

SOURCE TABLE: {table_name}
COLUMNS:
{chr(10).join(col_lines)}

REFERENCE MODEL DOMAIN: {domain_summary['domain_name']}
CLASSES AND PROPERTIES:
{chr(10).join(domain_lines)}

For each source column, determine if it semantically maps to a reference model property.
Consider: naming variations, abbreviations, sample values, data types, and domain context.

Respond with JSON:
{{
  "domain_relevance": 0.0-1.0,
  "matches": [
    {{
      "column": "source_column_name",
      "ref_property": "ClassName.propertyName",
      "confidence": 0.0-1.0,
      "evidence": "brief explanation"
    }}
  ],
  "unmatched": [
    {{
      "column": "column_name",
      "reason": "why no match"
    }}
  ]
}}

Only include matches with confidence >= 0.5. Be thorough but precise."""


def analyse_table_against_domain(
    client,
    model: str,
    table_name: str,
    columns: list[dict[str, Any]],
    domain_summary: dict[str, Any],
) -> dict[str, Any]:
    """Use LLM to match one source table against one reference model domain."""
    prompt = _build_analysis_prompt(table_name, columns, domain_summary)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "You are an expert data architect. You analyse source system columns "
                    "and match them to industry reference model properties based on semantic "
                    "meaning, not just name similarity. Always respond with valid JSON."
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
        return {"domain_relevance": 0.0, "matches": [], "unmatched": []}


# ---------------------------------------------------------------------------
# Main analysis orchestrator
# ---------------------------------------------------------------------------


def analyse_source_system(
    source_vocab_path: Path,
    ref_model_paths: list[Path],
    model: str = DEFAULT_MODEL,
    threshold: float = 0.3,
) -> SourceAnalysis:
    """Analyse one source system against all reference model domains.

    Args:
        source_vocab_path: Path to the source system's .vocabulary.ttl
        ref_model_paths: List of reference model .ttl files
        model: LLM model name
        threshold: Minimum domain relevance to include in output

    Returns:
        SourceAnalysis with domain affinities and column suggestions.
    """
    client = _get_openai_client()

    # Parse source vocabulary
    tables = parse_source_vocabulary(source_vocab_path)
    if not tables:
        logger.warning("No tables found in %s", source_vocab_path)
        return SourceAnalysis(
            system=source_vocab_path.stem.replace(".vocabulary", ""),
            analysed_at=datetime.now(timezone.utc).isoformat(),
            model_used=model,
        )

    # Parse reference models
    ref_domains = []
    for ref_path in ref_model_paths:
        try:
            domain = parse_reference_model(ref_path)
            if domain["classes"]:
                ref_domains.append(domain)
        except Exception as e:
            logger.warning("Failed to parse reference model %s: %s", ref_path, e)

    # Analyse each table against each domain
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
                matches = result.get("matches", [])
                unmatched = result.get("unmatched", [])

                suggestions = [
                    ColumnSuggestion(
                        column=m["column"],
                        ref_property=m["ref_property"],
                        confidence=m["confidence"],
                        evidence=m.get("evidence", ""),
                    )
                    for m in matches
                ]

                table_matches.append(TableMatch(
                    table=tbl_name,
                    total_columns=len(columns),
                    matched_columns=len(suggestions),
                    suggestions=suggestions,
                    unmatched_columns=unmatched,
                ))

        if table_matches:
            avg_relevance = total_relevance / len(tables) if tables else 0.0
            domain_results[domain_key] = DomainAffinity(
                domain=domain_key,
                ref_model_file=domain["file"],
                confidence=round(avg_relevance, 2),
                matched_tables=table_matches,
            )

    # Build final result sorted by confidence
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
    """Write analysis results to YAML files.

    Returns the path to the written system affinity file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Per-system affinity file
    data: dict[str, Any] = {
        "system": analysis.system,
        "analysed_at": analysis.analysed_at,
        "model_used": analysis.model_used,
        "domain_affinities": [],
    }

    for aff in analysis.domain_affinities:
        aff_dict: dict[str, Any] = {
            "domain": aff.domain,
            "ref_model": aff.ref_model_file,
            "confidence": aff.confidence,
            "matched_tables": [],
        }
        for tm in aff.matched_tables:
            table_dict: dict[str, Any] = {
                "table": tm.table,
                "matched_columns": f"{tm.matched_columns}/{tm.total_columns}",
                "suggestions": [
                    {
                        "column": s.column,
                        "ref_property": s.ref_property,
                        "confidence": s.confidence,
                        "evidence": s.evidence,
                    }
                    for s in tm.suggestions
                ],
            }
            if tm.unmatched_columns:
                table_dict["unmatched_columns"] = tm.unmatched_columns
            aff_dict["matched_tables"].append(table_dict)
        data["domain_affinities"].append(aff_dict)

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
) -> list[Path]:
    """Run analysis for all source systems in a hub.

    Args:
        sources_dir: Path to integration/sources/ directory
        ref_models_dir: Path to ontology-reference-models/ directory
        output_dir: Where to write analysis output
        model: LLM model to use
        threshold: Minimum affinity confidence to report

    Returns:
        List of output file paths written.
    """
    # Find all source vocabulary files
    vocab_files = sorted(sources_dir.glob("*/*.vocabulary.ttl"))
    if not vocab_files:
        raise ValueError(f"No source vocabulary files found in {sources_dir}")

    # Find all reference model TTL files
    ref_model_files = sorted(ref_models_dir.glob("*.ttl"))
    if not ref_model_files:
        raise ValueError(f"No reference model TTL files found in {ref_models_dir}")

    logger.info(
        "Analysing %d source system(s) against %d reference model(s)",
        len(vocab_files), len(ref_model_files),
    )

    analyses: list[SourceAnalysis] = []
    output_files: list[Path] = []

    for vocab_path in vocab_files:
        logger.info("Analysing source: %s", vocab_path.stem)
        analysis = analyse_source_system(
            vocab_path, ref_model_files, model=model, threshold=threshold
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
