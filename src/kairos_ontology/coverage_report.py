# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Post-modeling coverage report — measures ontology alignment to reference models.

Analyses how well the final domain ontology aligns with industry reference models,
with source evidence tracing. Uses deterministic alignment based on owl:imports,
rdfs:seeAlso links, and name matching — no LLM required.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef

from .analyse_sources import (
    resolve_reference_models,
)

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
    """Parse a domain ontology into classes and properties.

    Also extracts ``rdfs:seeAlso`` links (for "Inspired" strategy) and
    ``owl:imports`` IRIs (for "Enforced" strategy) to enable deterministic
    alignment against reference models.
    """
    g = Graph()
    g.parse(ttl_path, format="turtle")

    domain_name = ttl_path.stem
    imports: list[str] = []
    for ont in g.subjects(RDF.type, OWL.Ontology):
        label = g.value(ont, RDFS.label)
        if label:
            domain_name = str(label)
        for imp in g.objects(ont, OWL.imports):
            imports.append(str(imp))
        break

    classes: list[dict[str, Any]] = []

    for cls_uri in g.subjects(RDF.type, OWL.Class):
        if not isinstance(cls_uri, URIRef):
            continue
        cls_name = cls_uri.split("#")[-1].split("/")[-1]
        cls_label = str(g.value(cls_uri, RDFS.label) or cls_name)

        # Collect rdfs:seeAlso links for this class
        see_also: list[str] = []
        for sa in g.objects(cls_uri, RDFS.seeAlso):
            see_also.append(str(sa))

        properties: list[dict[str, Any]] = []
        for prop_uri in g.subjects(RDFS.domain, cls_uri):
            if not isinstance(prop_uri, URIRef):
                continue
            prop_name = prop_uri.split("#")[-1].split("/")[-1]
            prop_label = str(g.value(prop_uri, RDFS.label) or prop_name)
            prop_see_also = [str(sa) for sa in g.objects(prop_uri, RDFS.seeAlso)]
            properties.append({
                "name": prop_name,
                "label": prop_label,
                "see_also": prop_see_also,
            })

        classes.append({
            "name": cls_name,
            "label": cls_label,
            "uri": str(cls_uri),
            "see_also": see_also,
            "properties": properties,
        })

    return {
        "domain_name": domain_name,
        "file": ttl_path.name,
        "imports": imports,
        "classes": classes,
    }


# ---------------------------------------------------------------------------
# Deterministic alignment
# ---------------------------------------------------------------------------


def _uri_local_name(uri: str) -> str:
    """Extract the local name from a URI (after # or last /)."""
    return uri.split("#")[-1].split("/")[-1]


def _build_ref_index(ref_domains: list[dict]) -> dict[str, dict]:
    """Build a lookup index from reference model classes.

    Returns dict: lowercased class name → {name, label, domain, uri, properties}.
    Also indexes by full URI for seeAlso matching.
    """
    by_name: dict[str, dict] = {}
    by_uri: dict[str, dict] = {}
    for domain in ref_domains:
        for cls in domain["classes"]:
            entry = {**cls, "domain": domain["domain_name"]}
            by_name[cls["name"].lower()] = entry
            if "uri" in cls:
                by_uri[cls["uri"]] = entry
    return {"by_name": by_name, "by_uri": by_uri}


def align_classes_deterministic(
    ont_data: dict[str, Any],
    ref_index: dict[str, dict],
) -> list[dict[str, Any]]:
    """Align ontology classes to reference model using deterministic rules.

    Alignment priority:
    1. **linked** — class has ``rdfs:seeAlso`` pointing to a reference class URI
    2. **imported** — class name matches a ref class and the domain imports the ref ontology
    3. **name-match** — class name matches a ref class name (case-insensitive)
    4. **custom** — no reference model counterpart
    """
    by_name = ref_index["by_name"]
    by_uri = ref_index["by_uri"]
    imports = set(ont_data.get("imports", []))

    results: list[dict[str, Any]] = []

    for cls in ont_data["classes"]:
        ref_cls = None
        alignment = "custom"
        confidence = 0.0

        # 1. Check rdfs:seeAlso links
        for sa_uri in cls.get("see_also", []):
            if sa_uri in by_uri:
                ref_cls = by_uri[sa_uri]
                alignment = "linked"
                confidence = 1.0
                break
            # Also try matching by local name from seeAlso URI
            sa_name = _uri_local_name(sa_uri).lower()
            if sa_name in by_name:
                ref_cls = by_name[sa_name]
                alignment = "linked"
                confidence = 0.9
                break

        # 2. Check name match + imports
        if ref_cls is None:
            cls_lower = cls["name"].lower()
            if cls_lower in by_name:
                ref_cls = by_name[cls_lower]
                if imports:
                    alignment = "imported"
                    confidence = 0.8
                else:
                    alignment = "name-match"
                    confidence = 0.6

        # Align properties
        prop_alignments = _align_properties(cls, ref_cls, ref_index)

        results.append({
            "ontology_class": cls["name"],
            "ref_class": ref_cls["name"] if ref_cls else None,
            "ref_domain": ref_cls["domain"] if ref_cls else None,
            "alignment": alignment,
            "confidence": confidence,
            "property_alignments": prop_alignments,
        })

    return results


def _align_properties(
    ont_cls: dict,
    ref_cls: dict | None,
    ref_index: dict,
) -> list[dict[str, Any]]:
    """Align ontology properties to reference class properties."""
    ref_props_by_name: dict[str, dict] = {}
    if ref_cls:
        for p in ref_cls.get("properties", []):
            ref_props_by_name[p["name"].lower()] = p

    results = []
    for prop in ont_cls.get("properties", []):
        ref_prop = None
        alignment = "custom"
        confidence = 0.0

        # Check rdfs:seeAlso on property
        for sa_uri in prop.get("see_also", []):
            sa_name = _uri_local_name(sa_uri).lower()
            if sa_name in ref_props_by_name:
                ref_prop = ref_props_by_name[sa_name]
                alignment = "linked"
                confidence = 1.0
                break

        # Check name match within the matched ref class
        if ref_prop is None:
            prop_lower = prop["name"].lower()
            if prop_lower in ref_props_by_name:
                ref_prop = ref_props_by_name[prop_lower]
                alignment = "name-match"
                confidence = 0.7

        ref_name = f"{ref_cls['name']}.{ref_prop['name']}" if ref_cls and ref_prop else None

        results.append({
            "ontology_property": prop["name"],
            "ref_property": ref_name,
            "alignment": alignment,
            "confidence": confidence,
        })

    return results


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
    output_format: str = "both",
) -> CoverageReport:
    """Generate a coverage report for the ontology against reference models.

    Uses deterministic alignment based on ``rdfs:seeAlso`` links,
    ``owl:imports``, and name matching — no LLM required.

    Args:
        ontology_dir: Path to model/ontologies/ directory
        ref_models_dir: Path to ontology-reference-models/ directory
        sources_dir: Path to integration/sources/ (for evidence tracing)
        output_format: "yaml", "markdown", or "both"

    Returns:
        CoverageReport with full alignment details.
    """
    # Parse all domain ontologies (supports subdirectory layout)
    ontology_files = sorted(ontology_dir.glob("**/*.ttl"))
    ontology_files = [f for f in ontology_files if not f.name.startswith("_")]

    # Resolve reference models (recursive discovery + merge)
    ref_domains = resolve_reference_models(ref_models_dir)

    # Build lookup index for deterministic alignment
    ref_index = _build_ref_index(ref_domains)

    # Analyse each domain ontology
    report = CoverageReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    for ont_file in ontology_files:
        ont_data = parse_domain_ontology(ont_file)
        if not ont_data["classes"]:
            continue

        # Deterministic alignment
        class_alignments = align_classes_deterministic(ont_data, ref_index)

        # Source evidence
        evidence = {}
        if sources_dir:
            evidence = trace_source_evidence(ont_file, sources_dir)

        # Build domain coverage
        domain_cov = DomainCoverage(domain=ont_data["domain_name"])

        for cls_align in class_alignments:
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

    # Final percentages
    report.class_coverage_pct = round(
        report.aligned_classes / report.total_classes * 100
    ) if report.total_classes else 0.0
    report.property_coverage_pct = round(
        report.aligned_properties / report.total_properties * 100
    ) if report.total_properties else 0.0

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
