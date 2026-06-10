# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Post-modeling coverage report — measures ontology alignment to reference models.

Analyses how well the final domain ontology aligns with industry reference models,
with source evidence tracing. Uses LLM (gpt-5.4-mini via configurable AI provider)
for semantic matching beyond simple name comparison.

Requires AI provider configuration (GITHUB_TOKEN or AZURE_AI_ENDPOINT + AZURE_AI_KEY).
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

from .analyse_sources import (
    DEFAULT_MODEL,
    resolve_reference_models,
)
from .ai_provider import get_ai_client

logger = logging.getLogger(__name__)

KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PropertyAlignment:
    """Alignment result for a single ontology property."""
    name: str
    label: str
    ref_property: str | None  # None = custom (no match)
    alignment: str  # exact | semantic | partial | custom
    confidence: float
    source_columns: list[str] = field(default_factory=list)
    suggestion: str = ""


@dataclass
class ClassAlignment:
    """Alignment result for a single ontology class."""
    name: str
    label: str
    ref_class: str | None
    alignment: str  # exact | semantic | partial | custom
    confidence: float
    properties: list[PropertyAlignment] = field(default_factory=list)
    source_evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DomainCoverage:
    """Coverage result for one ontology domain."""
    domain: str
    classes: list[ClassAlignment] = field(default_factory=list)
    class_coverage_pct: float = 0.0
    property_coverage_pct: float = 0.0


@dataclass
class CoverageReport:
    """Complete coverage report."""
    generated_at: str
    model_used: str
    total_classes: int = 0
    aligned_classes: int = 0
    class_coverage_pct: float = 0.0
    total_properties: int = 0
    aligned_properties: int = 0
    property_coverage_pct: float = 0.0
    domains: list[DomainCoverage] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Ontology parsing
# ---------------------------------------------------------------------------


def parse_domain_ontology(ttl_path: Path) -> dict[str, Any]:
    """Parse a domain ontology into classes and properties."""
    g = Graph()
    g.parse(ttl_path, format="turtle")

    domain_name = ttl_path.stem
    for ont in g.subjects(RDF.type, OWL.Ontology):
        label = g.value(ont, RDFS.label)
        if label:
            domain_name = str(label)
        break

    classes: list[dict[str, Any]] = []

    for cls_uri in g.subjects(RDF.type, OWL.Class):
        if not isinstance(cls_uri, URIRef):
            continue
        cls_name = cls_uri.split("#")[-1].split("/")[-1]
        cls_label = str(g.value(cls_uri, RDFS.label) or cls_name)

        properties: list[dict[str, str]] = []
        for prop_uri in g.subjects(RDFS.domain, cls_uri):
            if not isinstance(prop_uri, URIRef):
                continue
            prop_name = prop_uri.split("#")[-1].split("/")[-1]
            prop_label = str(g.value(prop_uri, RDFS.label) or prop_name)
            properties.append({"name": prop_name, "label": prop_label})

        classes.append({
            "name": cls_name,
            "label": cls_label,
            "properties": properties,
        })

    return {"domain_name": domain_name, "file": ttl_path.name, "classes": classes}


# ---------------------------------------------------------------------------
# LLM-powered alignment
# ---------------------------------------------------------------------------


def _build_coverage_prompt(
    ontology_classes: list[dict],
    ref_classes: list[dict],
) -> str:
    """Build LLM prompt for ontology-to-reference alignment."""
    ont_lines = []
    for cls in ontology_classes:
        props = ", ".join(p["name"] for p in cls["properties"][:20])
        ont_lines.append(f"  - {cls['name']} ({cls['label']}): [{props}]")

    ref_lines = []
    for cls in ref_classes:
        props = ", ".join(p["name"] for p in cls["properties"][:20])
        ref_lines.append(f"  - {cls['name']} ({cls['label']}): [{props}]")

    return f"""Compare this domain ontology against the reference model.
For each ontology class and property, determine if it aligns with a reference model concept.

DOMAIN ONTOLOGY:
{chr(10).join(ont_lines)}

REFERENCE MODEL:
{chr(10).join(ref_lines)}

Respond with JSON:
{{
  "class_alignments": [
    {{
      "ontology_class": "ClassName",
      "ref_class": "RefClassName" or null,
      "alignment": "exact|semantic|partial|custom",
      "confidence": 0.0-1.0,
      "property_alignments": [
        {{
          "ontology_property": "propName",
          "ref_property": "RefClass.refPropName" or null,
          "alignment": "exact|semantic|partial|custom",
          "confidence": 0.0-1.0,
          "suggestion": "" (improvement suggestion if custom)
        }}
      ]
    }}
  ],
  "overall_suggestions": ["suggestion1", "suggestion2"]
}}

Be thorough. Consider semantic meaning, not just name matching.
"exact" = same concept and name; "semantic" = same concept, different name;
"partial" = related but not equivalent; "custom" = no reference model counterpart."""


def analyse_coverage_with_llm(
    client,
    model: str,
    ontology_classes: list[dict],
    ref_classes: list[dict],
) -> dict[str, Any]:
    """Use LLM to align ontology classes against reference model."""
    prompt = _build_coverage_prompt(ontology_classes, ref_classes)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "You are an expert ontologist. You compare domain ontologies against "
                    "industry reference models to assess coverage and alignment. "
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
        logger.warning("LLM coverage analysis failed: %s", e)
        return {"class_alignments": [], "overall_suggestions": []}


# ---------------------------------------------------------------------------
# Source evidence tracing
# ---------------------------------------------------------------------------


def trace_source_evidence(
    ontology_path: Path,
    sources_dir: Path,
) -> dict[str, list[str]]:
    """Trace which source columns contribute to each ontology property.

    Reads SKOS mapping files to find source→domain column mappings.
    Returns dict: property_name → [system.table.column, ...]
    """
    evidence: dict[str, list[str]] = {}

    # Find all mapping files
    mappings_dir = ontology_path.parent.parent / "mappings"
    if not mappings_dir.is_dir():
        return evidence

    for mapping_file in mappings_dir.glob("*.ttl"):
        try:
            g = Graph()
            g.parse(mapping_file, format="turtle")

            # Look for skos:exactMatch / skos:closeMatch triples
            from rdflib.namespace import SKOS
            for s, p, o in g.triples((None, None, None)):
                if str(p) in (str(SKOS.exactMatch), str(SKOS.closeMatch)):
                    # s = source column URI, o = domain property URI
                    source_part = str(s).split("#")[-1].split("/")[-1]
                    domain_part = str(o).split("#")[-1].split("/")[-1]
                    evidence.setdefault(domain_part, []).append(source_part)
        except Exception as e:
            logger.debug("Could not parse mapping file %s: %s", mapping_file, e)

    return evidence


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def run_coverage_report(
    ontology_dir: Path,
    ref_models_dir: Path,
    sources_dir: Path | None = None,
    model: str = DEFAULT_MODEL,
    output_format: str = "both",
) -> CoverageReport:
    """Generate a coverage report for the ontology against reference models.

    Args:
        ontology_dir: Path to model/ontologies/ directory
        ref_models_dir: Path to ontology-reference-models/ directory
        sources_dir: Path to integration/sources/ (for evidence tracing)
        model: LLM model to use
        output_format: "yaml", "markdown", or "both"

    Returns:
        CoverageReport with full alignment details.
    """
    client = get_ai_client(model)

    # Parse all domain ontologies
    ontology_files = sorted(ontology_dir.glob("*.ttl"))
    ontology_files = [f for f in ontology_files if not f.name.startswith("_")]

    # Resolve reference models (recursive discovery + merge)
    ref_domains = resolve_reference_models(ref_models_dir)

    # Aggregate all reference classes
    all_ref_classes: list[dict] = []
    for domain in ref_domains:
        all_ref_classes.extend(domain["classes"])

    # Analyse each domain ontology
    report = CoverageReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        model_used=model,
    )

    all_suggestions: list[str] = []

    for ont_file in ontology_files:
        ont_data = parse_domain_ontology(ont_file)
        if not ont_data["classes"]:
            continue

        # LLM analysis (batch by domain file, max ~20 classes per call)
        result = analyse_coverage_with_llm(
            client, model, ont_data["classes"], all_ref_classes
        )

        # Source evidence
        evidence = {}
        if sources_dir:
            evidence = trace_source_evidence(ont_file, sources_dir)

        # Build domain coverage
        domain_cov = DomainCoverage(domain=ont_data["domain_name"])

        for cls_align in result.get("class_alignments", []):
            props = []
            for pa in cls_align.get("property_alignments", []):
                prop_name = pa["ontology_property"]
                props.append(PropertyAlignment(
                    name=prop_name,
                    label=prop_name,
                    ref_property=pa.get("ref_property"),
                    alignment=pa.get("alignment", "custom"),
                    confidence=pa.get("confidence", 0.0),
                    source_columns=evidence.get(prop_name, []),
                    suggestion=pa.get("suggestion", ""),
                ))

            domain_cov.classes.append(ClassAlignment(
                name=cls_align["ontology_class"],
                label=cls_align["ontology_class"],
                ref_class=cls_align.get("ref_class"),
                alignment=cls_align.get("alignment", "custom"),
                confidence=cls_align.get("confidence", 0.0),
                properties=props,
            ))

        # Calculate coverage percentages
        total_cls = len(domain_cov.classes)
        aligned_cls = sum(1 for c in domain_cov.classes if c.alignment != "custom")
        domain_cov.class_coverage_pct = round(
            aligned_cls / total_cls * 100) if total_cls else 0.0

        total_props = sum(len(c.properties) for c in domain_cov.classes)
        aligned_props = sum(
            1 for c in domain_cov.classes
            for p in c.properties if p.alignment != "custom"
        )
        domain_cov.property_coverage_pct = round(
            aligned_props / total_props * 100) if total_props else 0.0

        report.domains.append(domain_cov)
        report.total_classes += total_cls
        report.aligned_classes += aligned_cls
        report.total_properties += total_props
        report.aligned_properties += aligned_props

        all_suggestions.extend(result.get("overall_suggestions", []))

    # Final percentages
    report.class_coverage_pct = round(
        report.aligned_classes / report.total_classes * 100
    ) if report.total_classes else 0.0
    report.property_coverage_pct = round(
        report.aligned_properties / report.total_properties * 100
    ) if report.total_properties else 0.0
    report.suggestions = all_suggestions

    return report


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


def write_coverage_yaml(report: CoverageReport, output_path: Path) -> Path:
    """Write coverage report as YAML.

    If *output_path* points to a **directory**, a timestamped filename is generated
    automatically (``coverage-{YYYY-MM-DD-HHmmss}.yaml``).  If it points to a
    **file**, that exact path is used (backwards-compatible).
    """
    if output_path.is_dir() or not output_path.suffix:
        from datetime import datetime as _dt, timezone as _tz
        ts = _dt.now(_tz.utc).strftime("%Y-%m-%d-%H%M%S")
        output_path = output_path / f"coverage-industry-{ts}.yaml"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {
        "report_type": "coverage",
        "generated_at": report.generated_at,
        "model_used": report.model_used,
        "summary": {
            "total_classes": report.total_classes,
            "aligned_classes": report.aligned_classes,
            "class_coverage_pct": f"{report.class_coverage_pct}%",
            "total_properties": report.total_properties,
            "aligned_properties": report.aligned_properties,
            "property_coverage_pct": f"{report.property_coverage_pct}%",
        },
        "domains": [],
    }

    for domain in report.domains:
        dom_dict: dict[str, Any] = {
            "name": domain.domain,
            "class_coverage_pct": f"{domain.class_coverage_pct}%",
            "property_coverage_pct": f"{domain.property_coverage_pct}%",
            "classes": [],
        }
        for cls in domain.classes:
            cls_dict: dict[str, Any] = {
                "name": cls.name,
                "ref_class": cls.ref_class,
                "alignment": cls.alignment,
                "confidence": cls.confidence,
                "properties": [
                    {
                        "name": p.name,
                        "ref_property": p.ref_property,
                        "alignment": p.alignment,
                        "confidence": p.confidence,
                        **({"source_columns": p.source_columns} if p.source_columns else {}),
                        **({"suggestion": p.suggestion} if p.suggestion else {}),
                    }
                    for p in cls.properties
                ],
            }
            if cls.source_evidence:
                cls_dict["source_evidence"] = cls.source_evidence
            dom_dict["classes"].append(cls_dict)
        data["domains"].append(dom_dict)

    if report.suggestions:
        data["improvement_suggestions"] = report.suggestions

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return output_path


def write_coverage_markdown(report: CoverageReport, output_path: Path) -> Path:
    """Write coverage report as human-readable markdown.

    If *output_path* points to a **directory**, a timestamped filename is generated
    automatically (``coverage-{YYYY-MM-DD-HHmmss}.md``).  If it points to a
    **file**, that exact path is used (backwards-compatible).
    """
    if output_path.is_dir() or not output_path.suffix:
        from datetime import datetime as _dt, timezone as _tz
        ts = _dt.now(_tz.utc).strftime("%Y-%m-%d-%H%M%S")
        output_path = output_path / f"coverage-industry-{ts}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Ontology Coverage Report",
        "",
        f"Generated: {report.generated_at}  ",
        f"Model: {report.model_used}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total classes | {report.total_classes} |",
        f"| Aligned classes | {report.aligned_classes} ({report.class_coverage_pct}%) |",
        f"| Total properties | {report.total_properties} |",
        f"| Aligned properties | {report.aligned_properties} ({report.property_coverage_pct}%) |",
        "",
    ]

    for domain in report.domains:
        lines.append(f"## {domain.domain}")
        lines.append("")
        lines.append(f"Class coverage: {domain.class_coverage_pct}% | "
                     f"Property coverage: {domain.property_coverage_pct}%")
        lines.append("")
        lines.append("| Class | Ref Model | Alignment | Properties Aligned |")
        lines.append("|-------|-----------|-----------|-------------------|")

        for cls in domain.classes:
            aligned_props = sum(1 for p in cls.properties if p.alignment != "custom")
            total_props = len(cls.properties)
            ref_str = cls.ref_class or "—"
            lines.append(
                f"| {cls.name} | {ref_str} | {cls.alignment} | "
                f"{aligned_props}/{total_props} |"
            )
        lines.append("")

    if report.suggestions:
        lines.append("## Improvement Suggestions")
        lines.append("")
        for suggestion in report.suggestions:
            lines.append(f"- {suggestion}")
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
