# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Draft domain-model evidence report generation.

The report is an advisory planning view over existing evidence streams. It does
not approve claims, write ontology TTL, or participate in projection authority.
"""

from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ._cache import compute_entry_hash
from .claim_registry import ClaimRegistry, load_registry
from .derive_claims import (
    class_claim_id,
    load_affinity_by_domain,
    load_skos_links,
    load_tmdl_concept_mappings,
)

DRAFT_MODEL_SCHEMA_VERSION = 1
DATA_PRODUCT_CONTRACT_SCHEMA_VERSION = 1


@dataclass
class DraftModelArtifacts:
    """Paths written by a draft-model report run."""

    summary_yaml: Path
    markdown: Path
    mermaid: Path
    domain_yamls: list[Path] = field(default_factory=list)


def _local_name(uri: str | None) -> str:
    if not uri:
        return ""
    return uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", value.strip())
    text = text.strip("_")
    return text or "unnamed"


def _normalise_domain(value: str | None) -> str:
    return _slug(value or "unrouted_reporting").lower()


def _normalise_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iter_existing_files(paths: list[Path | None]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if not path or not path.exists():
            continue
        if path.is_file():
            files.append(path)
            continue
        for pattern in ("*.yaml", "*.yml", "*.ttl"):
            files.extend(sorted(path.rglob(pattern)))
    return sorted(set(files))


def _input_provenance(paths: list[Path | None]) -> dict[str, Any]:
    files = [
        {"path": str(path), "sha256": _file_sha256(path)}
        for path in _iter_existing_files(paths)
    ]
    return {
        "input_files": files,
        "input_sha256": compute_entry_hash(files),
        "stale": False,
    }


def _evidence_status(evidence: list[str]) -> str:
    if "claim-approved" in evidence:
        return "claim-approved"
    if "mapping-backed" in evidence:
        return "mapping-backed"
    if "source-backed" in evidence:
        return "source-backed"
    if "glossary-supported" in evidence and "tmdl-only" in evidence:
        return "tmdl+glossary"
    if "glossary-supported" in evidence:
        return "glossary-supported"
    if "tmdl-only" in evidence:
        return "tmdl-only"
    return "unresolved"


def load_data_product_contract(path: Path) -> dict[str, Any]:
    """Load and validate a planning-only data-product contract."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Data-product contract must be a YAML mapping: {path}")
    if data.get("projection_authority") is not False:
        raise ValueError("Data-product contracts must declare projection_authority: false")
    return data


def _contract_product_name(contract: dict[str, Any], contract_path: Path | None) -> str:
    product = contract.get("product") or contract.get("name") or contract.get("data_product")
    if product:
        return str(product)
    if contract_path:
        return contract_path.parent.name
    return "data-product"


def _extract_contract_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str | int | float):
        return [str(value)]
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(_extract_contract_values(item))
        return values
    if isinstance(value, dict):
        values = []
        for key, item in value.items():
            if key in {
                "name",
                "field",
                "fields",
                "column",
                "columns",
                "measure",
                "measures",
                "table",
                "tables",
                "dimension",
                "dimensions",
                "fact",
                "facts",
                "domain",
                "source",
                "sources",
                "tmdl_name",
                "expression",
            }:
                values.extend(_extract_contract_values(item))
        return values
    return []


def _contract_terms(contract: dict[str, Any]) -> list[str]:
    ignored = {"true", "false", "none", "null", "1"}
    terms = {
        _normalise_token(value)
        for value in _extract_contract_values(contract)
        if _normalise_token(value) and _normalise_token(value) not in ignored
    }
    return sorted(terms)


def _record_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str | int | float | bool):
        return [str(value)]
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(_record_values(item))
        return values
    if isinstance(value, dict):
        values = []
        for item in value.values():
            values.extend(_record_values(item))
        return values
    return []


def _matches_terms(record: dict[str, Any], terms: list[str]) -> bool:
    if not terms:
        return True
    text = _normalise_token(" ".join(_record_values(record)))
    return any(term and (term in text or text in term) for term in terms)


def _entity_triage(entity: dict[str, Any]) -> str:
    status = str(entity.get("evidence_status") or "unresolved")
    if status in {"claim-approved", "mapping-backed"}:
        return "covered"
    if status == "source-backed":
        return "claim-needed"
    if status in {"tmdl-only", "tmdl+glossary", "glossary-supported"}:
        return "domain-gap"
    return "claim-needed"


def _has_claim_or_mapping_backing(entities: list[dict[str, Any]]) -> bool:
    return any(
        entity.get("evidence_status") in {"claim-approved", "mapping-backed"}
        for entity in entities
    )


def _load_registries(claims_dir: Path | None) -> dict[str, ClaimRegistry]:
    if not claims_dir or not claims_dir.is_dir():
        return {}
    registries: dict[str, ClaimRegistry] = {}
    for path in sorted(claims_dir.glob("*-claims.yaml")):
        domain = path.name.replace("-claims.yaml", "")
        registries[domain] = load_registry(path)
    return registries


def _load_tmdl_relationships(tmdl_dir: Path | None) -> list[dict[str, Any]]:
    """Load relationship records from import-tmdl concept-mapping YAML files."""
    if not tmdl_dir or not tmdl_dir.is_dir():
        return []
    relationships: list[dict[str, Any]] = []
    for mapping_file in sorted(tmdl_dir.glob("*-concept-mapping.yaml")):
        data = yaml.safe_load(mapping_file.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        model = str(data.get("model_name") or mapping_file.stem)
        table_domains = {
            str(t.get("tmdl_name") or ""): _normalise_domain(
                t.get("domain") or t.get("data_domain") or None
            )
            for t in data.get("tables", []) or []
            if isinstance(t, dict)
        }
        for rel in data.get("relationships", []) or []:
            if not isinstance(rel, dict):
                continue
            from_ref = str(rel.get("from") or "")
            to_ref = str(rel.get("to") or "")
            from_table = from_ref.split(".", 1)[0]
            to_table = to_ref.split(".", 1)[0]
            relationships.append(
                {
                    "model": model,
                    "from": from_ref,
                    "to": to_ref,
                    "from_table": from_table,
                    "to_table": to_table,
                    "cardinality": rel.get("cardinality") or "",
                    "reference_model_match": rel.get("reference_model_match") or "",
                    "is_active": rel.get("is_active", True),
                    "from_domain": table_domains.get(from_table, "unrouted_reporting"),
                    "to_domain": table_domains.get(to_table, "unrouted_reporting"),
                    "evidence": ["tmdl-only"],
                }
            )
    return relationships


def _load_tmdl_measures(tmdl_dir: Path | None) -> list[dict[str, Any]]:
    """Load table-scoped measure evidence from concept mappings and engineering packs."""
    if not tmdl_dir or not tmdl_dir.is_dir():
        return []
    measures: list[dict[str, Any]] = []
    for mapping_file in sorted(tmdl_dir.glob("*-concept-mapping.yaml")):
        data = yaml.safe_load(mapping_file.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        model = str(data.get("model_name") or mapping_file.stem)
        for table in data.get("tables", []) or []:
            if not isinstance(table, dict):
                continue
            domain = _normalise_domain(table.get("domain") or table.get("data_domain") or None)
            for measure in table.get("measures", []) or []:
                if isinstance(measure, dict):
                    name = str(measure.get("name") or "")
                    expression = str(measure.get("expression") or "")
                else:
                    name = str(measure)
                    expression = ""
                if name:
                    measures.append(
                        {
                            "model": model,
                            "table": table.get("tmdl_name") or "",
                            "measure": name,
                            "expression": expression,
                            "domain": domain,
                            "disposition_suggestion": "gold-candidate",
                            "evidence": ["tmdl-only"],
                        }
                    )
    return measures


def _load_glossary_terms(glossary_dir: Path | None) -> list[dict[str, str]]:
    """Load confirmed SKOS labels/altLabels from business-discovery glossary TTL."""
    if not glossary_dir or not glossary_dir.exists():
        return []
    ttl_files = sorted(glossary_dir.glob("*.ttl")) if glossary_dir.is_dir() else [glossary_dir]
    if not ttl_files:
        return []
    try:
        from rdflib import Graph, URIRef
    except Exception:
        return []
    pref_label = URIRef("http://www.w3.org/2004/02/skos/core#prefLabel")
    alt_label = URIRef("http://www.w3.org/2004/02/skos/core#altLabel")
    terms: list[dict[str, str]] = []
    for ttl in ttl_files:
        graph = Graph()
        try:
            graph.parse(ttl, format="turtle")
        except Exception:
            continue
        for subj, _, label in graph.triples((None, pref_label, None)):
            terms.append({"uri": str(subj), "label": str(label), "type": "prefLabel"})
        for subj, _, label in graph.triples((None, alt_label, None)):
            terms.append({"uri": str(subj), "label": str(label), "type": "altLabel"})
    return terms


def _term_matches(name: str, terms: list[dict[str, str]]) -> list[dict[str, str]]:
    lower = re.sub(r"[^a-z0-9]+", "", name.lower())
    if not lower:
        return []
    matches = []
    for term in terms:
        label = re.sub(r"[^a-z0-9]+", "", term["label"].lower())
        if label and (label in lower or lower in label):
            matches.append(term)
    return matches[:5]


def _claim_nodes(registry: ClaimRegistry, glossary_terms: list[dict[str, str]]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for claim in registry.claims:
        if claim.type not in {"class", "reference_data"}:
            continue
        name = _local_name(claim.class_uri) or claim.id
        evidence = []
        if claim.status == "approved":
            evidence.append("claim-approved")
        if any(ev.type == "source_table" for ev in claim.evidence_sources):
            evidence.append("source-backed")
        if any(ev.type == "skos_mapping" for ev in claim.evidence_sources):
            evidence.append("mapping-backed")
        if any(ev.type == "tmdl_concept_mapping" for ev in claim.evidence_sources):
            evidence.append("tmdl-only")
        glossary = _term_matches(name, glossary_terms)
        if glossary:
            evidence.append("glossary-supported")
        nodes.append(
            {
                "id": claim.id,
                "label": name,
                "claim_id": claim.id,
                "claim_status": claim.status,
                "disposition_suggestion": claim.disposition,
                "evidence": sorted(set(evidence)) or ["unresolved"],
                "evidence_status": _evidence_status(evidence),
                "glossary_matches": glossary,
            }
        )
    return nodes


def _affinity_nodes(domain: str, tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes = []
    for table in tables:
        label = str(table.get("likely_entity") or table.get("table") or "Unnamed")
        evidence = ["source-backed"]
        nodes.append(
            {
                "id": f"{domain}-affinity-{_slug(str(table.get('system') or 'source'))}-"
                f"{_slug(str(table.get('table') or label))}",
                "label": label,
                "source": {"system": table.get("system"), "table": table.get("table")},
                "confidence": table.get("confidence"),
                "disposition_suggestion": "claim",
                "evidence": evidence,
                "evidence_status": _evidence_status(evidence),
            }
        )
    return nodes


def _tmdl_nodes(
    domain: str,
    tables: list[dict[str, Any]],
    known_claims: set[str],
    glossary_terms: list[dict[str, str]],
) -> list[dict[str, Any]]:
    nodes = []
    for table in tables:
        table_domain = _normalise_domain(table.get("domain") or table.get("data_domain") or None)
        ref_match = str(table.get("reference_model_match") or "")
        if table_domain != domain and (not ref_match or class_claim_id(domain, ref_match) not in known_claims):
            continue
        label = ref_match or str(table.get("tmdl_name") or "UnroutedTmdl")
        evidence = ["tmdl-only"]
        glossary = _term_matches(label, glossary_terms)
        if glossary:
            evidence.append("glossary-supported")
        action = str(table.get("action") or "").strip()
        disposition = {
            "use": "claim",
            "specialize": "specialize",
            "new_class": "gap",
            "skip": "skip",
        }.get(action, "defer")
        nodes.append(
            {
                "id": f"{domain}-tmdl-{_slug(label)}",
                "label": label,
                "tmdl_table": table.get("tmdl_name") or "",
                "table_type": table.get("type") or "",
                "columns": table.get("columns") or [],
                "disposition_suggestion": disposition,
                "evidence": sorted(set(evidence)),
                "evidence_status": _evidence_status(evidence),
                "glossary_matches": glossary,
            }
        )
    return nodes


def _apply_data_product_filter(
    report: dict[str, Any],
    *,
    contract: dict[str, Any],
    contract_path: Path | None,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """Return a data-product-scoped advisory view over the draft model report."""
    product = _contract_product_name(contract, contract_path)
    product_slug = _normalise_domain(product)
    terms = _contract_terms(contract)
    filtered_domains: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []

    for domain, data in report["domains"].items():
        entities = [
            {**entity, "product_triage": _entity_triage(entity)}
            for entity in data.get("candidate_entities", [])
            if _matches_terms(entity, terms) or domain in terms
        ]
        relationships = [
            {**rel, "product_triage": "silver-question"}
            for rel in data.get("relationship_questions", [])
            if isinstance(rel, dict) and (_matches_terms(rel, terms) or domain in terms)
        ]
        backed = _has_claim_or_mapping_backing(entities)
        gold_candidates = []
        for measure in data.get("gold_candidates", []):
            if not isinstance(measure, dict) or not (_matches_terms(measure, terms) or domain in terms):
                continue
            triage = "gold-annotation-needed" if backed else "claim-needed"
            gold_candidates.append({**measure, "product_triage": triage})

        if not (entities or relationships or gold_candidates):
            continue

        filtered_domains[domain] = {
            **data,
            "candidate_entities": entities,
            "relationship_questions": relationships,
            "gold_candidates": gold_candidates,
            "next_action": _product_next_action(entities, relationships, gold_candidates),
        }

    measure_names: dict[str, dict[str, Any]] = {}
    for domain, data in filtered_domains.items():
        for measure in data.get("gold_candidates", []):
            name = _normalise_token(str(measure.get("measure") or ""))
            if not name:
                continue
            prior = measure_names.get(name)
            if prior and prior.get("expression") != measure.get("expression"):
                conflicts.append(
                    {
                        "type": "measure-definition-conflict",
                        "measure": measure.get("measure"),
                        "domains": sorted({str(prior.get("domain")), domain}),
                        "status": "requires-human-review",
                    }
                )
            else:
                measure_names[name] = {**measure, "domain": domain}

    summary = {
        "product": product,
        "domains": len(filtered_domains),
        "candidate_entities": sum(
            len(data.get("candidate_entities", [])) for data in filtered_domains.values()
        ),
        "relationship_questions": sum(
            len(data.get("relationship_questions", [])) for data in filtered_domains.values()
        ),
        "gold_candidates": sum(
            len(data.get("gold_candidates", [])) for data in filtered_domains.values()
        ),
        "conflicts": len(conflicts),
    }
    payload_for_hash = {
        "contract": contract,
        "domains": filtered_domains,
        "conflicts": conflicts,
        "provenance": provenance,
    }
    return {
        "schema_version": DRAFT_MODEL_SCHEMA_VERSION,
        "artifact": "data-product-draft-model-report",
        "product": product,
        "product_slug": product_slug,
        "advisory": True,
        "projection_authority": False,
        "contract": {
            "path": str(contract_path) if contract_path else None,
            "schema_version": contract.get(
                "schema_version",
                DATA_PRODUCT_CONTRACT_SCHEMA_VERSION,
            ),
            "projection_authority": False,
        },
        "triage_basis": "derived-from-dd086-evidence-status",
        "requested_terms": terms,
        "provenance": provenance,
        "input_sha256": compute_entry_hash(payload_for_hash),
        "summary": summary,
        "conflicts": conflicts,
        "domains": filtered_domains,
        "cross_domain_erd": render_mermaid_erd(filtered_domains),
    }


def _product_next_action(
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    gold_candidates: list[dict[str, Any]],
) -> str:
    triage = {
        str(item.get("product_triage"))
        for item in [*entities, *relationships, *gold_candidates]
        if isinstance(item, dict)
    }
    if "domain-gap" in triage:
        return "Resolve domain gaps before mapping or gold annotation."
    if "claim-needed" in triage:
        return "Review claim evidence and approve only source-backed items."
    if "silver-question" in triage:
        return "Confirm silver keys/FKs/SCD choices before gold design."
    if "gold-annotation-needed" in triage:
        return "Hand confirmed candidates to gold design as a perspective-scoped slice."
    return "The product slice is covered by existing evidence; review projection outputs."


def build_draft_model_report(
    *,
    claims_dir: Path | None = None,
    analysis_dir: Path | None = None,
    mappings_dir: Path | None = None,
    tmdl_dir: Path | None = None,
    glossary_dir: Path | None = None,
    domains_filter: list[str] | None = None,
    data_product_contract: dict[str, Any] | None = None,
    data_product_contract_path: Path | None = None,
) -> dict[str, Any]:
    """Build an all-domain advisory draft-model report as serialisable data."""
    registries = _load_registries(claims_dir)
    affinity_by_domain = load_affinity_by_domain(analysis_dir) if analysis_dir else {}
    tmdl_tables = load_tmdl_concept_mappings(tmdl_dir) if tmdl_dir else []
    tmdl_relationships = _load_tmdl_relationships(tmdl_dir)
    tmdl_measures = _load_tmdl_measures(tmdl_dir)
    skos_links = load_skos_links(mappings_dir) if mappings_dir else []
    glossary_terms = _load_glossary_terms(glossary_dir)

    domains = set(registries) | set(affinity_by_domain)
    for table in tmdl_tables:
        explicit_domain = table.get("domain") or table.get("data_domain")
        if explicit_domain:
            domains.add(_normalise_domain(str(explicit_domain)))
    for rel in tmdl_relationships:
        domains.add(_normalise_domain(str(rel.get("from_domain") or "")))
        domains.add(_normalise_domain(str(rel.get("to_domain") or "")))
    for measure in tmdl_measures:
        domains.add(_normalise_domain(str(measure.get("domain") or "")))

    filters = [f.lower() for f in (domains_filter or []) if f.strip()]
    if filters:
        domains = {d for d in domains if any(f in d.lower() for f in filters)}

    report_domains: dict[str, Any] = {}
    all_known_claims = {
        domain: {claim.id for claim in registry.claims}
        for domain, registry in registries.items()
    }
    for domain in sorted(domains):
        registry = registries.get(domain, ClaimRegistry(domain=domain))
        nodes = _claim_nodes(registry, glossary_terms)
        nodes.extend(_affinity_nodes(domain, affinity_by_domain.get(domain, [])))
        nodes.extend(_tmdl_nodes(domain, tmdl_tables, all_known_claims.get(domain, set()), glossary_terms))
        deduped_nodes = {node["id"]: node for node in nodes}

        domain_measures = [m for m in tmdl_measures if _normalise_domain(m.get("domain")) == domain]
        domain_relationships = [
            rel
            for rel in tmdl_relationships
            if _normalise_domain(rel.get("from_domain")) == domain
            or _normalise_domain(rel.get("to_domain")) == domain
        ]
        advisory_candidates = list(registry.relationship_candidates)
        for candidate in advisory_candidates:
            candidate.setdefault("evidence", ["source-backed"])
            candidate.setdefault("status", "advisory")

        report_domains[domain] = {
            "domain": domain,
            "lifecycle_inputs": {
                "claims": "available" if domain in registries else "not_available_yet",
                "affinity": "available" if domain in affinity_by_domain else "not_available_yet",
                "mappings": "available" if skos_links else "not_available_yet",
                "tmdl": "available" if tmdl_tables else "not_available_yet",
                "glossary": "available" if glossary_terms else "not_available_yet",
            },
            "candidate_entities": list(deduped_nodes.values()),
            "relationship_questions": domain_relationships + advisory_candidates,
            "gold_candidates": domain_measures,
            "mapping_gaps": "not_available_yet" if not skos_links else [],
            "next_action": _next_action(domain in registries, bool(skos_links), bool(domain_measures)),
        }

    provenance = _input_provenance(
        [claims_dir, analysis_dir, mappings_dir, tmdl_dir, glossary_dir, data_product_contract_path]
    )
    payload_for_hash = {
        "domains": report_domains,
        "relationship_count": len(tmdl_relationships),
        "measure_count": len(tmdl_measures),
        "glossary_count": len(glossary_terms),
        "provenance": provenance,
    }
    report = {
        "schema_version": DRAFT_MODEL_SCHEMA_VERSION,
        "artifact": "draft-domain-model-report",
        "advisory": True,
        "projection_authority": False,
        "provenance": provenance,
        "input_sha256": compute_entry_hash(payload_for_hash),
        "summary": {
            "domains": len(report_domains),
            "tmdl_relationships": len(tmdl_relationships),
            "tmdl_measures": len(tmdl_measures),
            "glossary_terms": len(glossary_terms),
            "skos_links": len(skos_links),
        },
        "domains": report_domains,
        "cross_domain_erd": render_mermaid_erd(report_domains),
    }
    if data_product_contract_path:
        data_product_contract = load_data_product_contract(data_product_contract_path)
    if data_product_contract:
        return _apply_data_product_filter(
            report,
            contract=data_product_contract,
            contract_path=data_product_contract_path,
            provenance=provenance,
        )
    return report


def _next_action(has_registry: bool, has_mappings: bool, has_measures: bool) -> str:
    if not has_registry:
        return "Run domain design; use this draft as the evidence agenda."
    if not has_mappings:
        return "Run mapping, then claims fit-gap enrichment."
    if has_measures:
        return "Review claims, then hand measure candidates to gold design."
    return "Review claims and proceed to silver design when approved."


def render_mermaid_erd(domains: dict[str, Any]) -> str:
    """Render one advisory cross-domain Mermaid flowchart."""
    lines = [
        "```mermaid",
        "flowchart LR",
        "  %% Advisory draft model ERD - not projection input",
    ]
    emitted: set[str] = set()
    for domain, data in domains.items():
        lines.append(f"  subgraph domain_{_slug(domain)}[{domain}]")
        for entity in data.get("candidate_entities", []):
            node_id = f"{_slug(domain)}__{_slug(str(entity.get('id') or entity.get('label')))}"
            if node_id in emitted:
                continue
            emitted.add(node_id)
            label = str(entity.get("label") or entity.get("id") or "Unnamed")
            status = str(entity.get("evidence_status") or "unresolved")
            lines.append(f'    {node_id}["{label}<br/>{status}"]')
        if not data.get("candidate_entities"):
            lines.append(f'    {_slug(domain)}__empty["No candidates yet<br/>unresolved"]')
        lines.append("  end")
    for domain, data in domains.items():
        for rel in data.get("relationship_questions", []):
            if not isinstance(rel, dict):
                continue
            from_domain = _normalise_domain(rel.get("from_domain") or domain)
            to_domain = _normalise_domain(rel.get("to_domain") or domain)
            from_table = str(rel.get("from_table") or rel.get("source_table") or "UnresolvedSource")
            to_table = str(rel.get("to_table") or rel.get("target_concept") or "UnresolvedTarget")
            from_node = f"{_slug(from_domain)}__tmdl_{_slug(from_table)}"
            to_node = f"{_slug(to_domain)}__tmdl_{_slug(to_table)}"
            if from_node not in emitted:
                lines.append(f'  {from_node}["{from_table}<br/>tmdl-only"]')
                emitted.add(from_node)
            if to_node not in emitted:
                lines.append(f'  {to_node}["{to_table}<br/>tmdl-only"]')
                emitted.add(to_node)
            label = str(rel.get("cardinality") or rel.get("suggested_relationship") or "question")
            lines.append(f"  {from_node} -. {label} .-> {to_node}")
    lines.append("```")
    return "\n".join(lines)


def render_markdown_report(report: dict[str, Any]) -> str:
    """Render the draft report as Markdown with an embedded global ERD."""
    is_product = report.get("artifact") == "data-product-draft-model-report"
    title = (
        f"Data-product vertical-slice report: {report.get('product')}"
        if is_product
        else "Draft domain-model evidence report"
    )
    lines = [
        f"# {title}",
        "",
        "> Advisory planning output only. This report is not claim authority, not TTL, "
        "and not projection input.",
        "",
        "## Summary",
        "",
        f"- Domains: {report['summary']['domains']}",
    ]
    if is_product:
        lines.extend(
           [
               f"- Candidate entities: {report['summary']['candidate_entities']}",
               f"- Relationship questions: {report['summary']['relationship_questions']}",
               f"- Gold candidates: {report['summary']['gold_candidates']}",
               f"- Conflicts: {report['summary']['conflicts']}",
               f"- Triage basis: {report['triage_basis']}",
           ]
        )
    else:
        lines.extend(
           [
               f"- TMDL relationships: {report['summary']['tmdl_relationships']}",
               f"- TMDL measures: {report['summary']['tmdl_measures']}",
               f"- Glossary terms: {report['summary']['glossary_terms']}",
               f"- SKOS links: {report['summary']['skos_links']}",
           ]
        )
    lines.extend(
        [
            f"- Input SHA-256: `{report['input_sha256']}`",
            "",
            "## Cross-domain draft ERD",
            "",
            report["cross_domain_erd"],
            "",
            "## Domain evidence packs",
            "",
        ]
    )
    for domain, data in report["domains"].items():
        lines.extend(
            [
                f"### {domain}",
                "",
                f"Next action: {data['next_action']}",
                "",
                "| Entity | Evidence | Suggested disposition |",
                "|---|---|---|",
            ]
        )
        for entity in data.get("candidate_entities", []):
            evidence = ", ".join(entity.get("evidence", []))
            lines.append(
                f"| {entity.get('label', entity.get('id'))} | {evidence} | "
                f"{entity.get('disposition_suggestion', 'defer')} |"
            )
        if not data.get("candidate_entities"):
            lines.append("| _(none)_ | unresolved | defer |")
        lines.extend(["", "**Relationship questions:**", ""])
        rels = data.get("relationship_questions", [])
        if rels:
            for rel in rels:
                if "from" in rel and "to" in rel:
                    lines.append(
                        f"- `{rel['from']}` -> `{rel['to']}` "
                        f"({rel.get('cardinality') or 'question'})"
                    )
                else:
                    lines.append(f"- {rel.get('suggested_relationship', 'relationship question')}")
        else:
            lines.append("- _(none)_")
        lines.extend(["", "**Gold candidates:**", ""])
        gold = data.get("gold_candidates", [])
        if gold:
            for measure in gold:
                lines.append(f"- `{measure['measure']}` on `{measure['table']}`")
        else:
            lines.append("- _(none)_")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _unfence_mermaid(mermaid: str) -> str:
    lines = mermaid.splitlines()
    if lines and lines[0].strip() == "```mermaid":
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).rstrip() + "\n"


def write_draft_model_report(report: dict[str, Any], output_dir: Path) -> DraftModelArtifacts:
    """Write YAML, Markdown, Mermaid, and per-domain YAML artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    domain_dir = output_dir / "domains"
    domain_dir.mkdir(exist_ok=True)
    if report.get("artifact") == "data-product-draft-model-report":
        summary_yaml = output_dir / "data-product-plan.yaml"
        markdown = output_dir / "data-product-report.md"
        mermaid = output_dir / "data-product-erd.mmd"
    else:
        summary_yaml = output_dir / "draft-model-report.yaml"
        markdown = output_dir / "draft-model-report.md"
        mermaid = output_dir / "draft-model-erd.mmd"

    summary_yaml.write_text(yaml.safe_dump(report, sort_keys=False, width=100), encoding="utf-8")
    markdown.write_text(render_markdown_report(report), encoding="utf-8")
    mermaid.write_text(_unfence_mermaid(report["cross_domain_erd"]), encoding="utf-8")

    domain_yamls = []
    for domain, data in report["domains"].items():
        path = domain_dir / f"{domain}.yaml"
        path.write_text(yaml.safe_dump(data, sort_keys=False, width=100), encoding="utf-8")
        domain_yamls.append(path)
    return DraftModelArtifacts(summary_yaml, markdown, mermaid, domain_yamls)
