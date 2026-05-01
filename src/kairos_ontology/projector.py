# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Projection orchestrator - generates downstream artifacts."""

import json
import traceback as _tb
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS
from .projections.uri_utils import extract_local_name
from .projections.shared import OntologyClassInfo

VALID_TARGETS = ["dbt", "neo4j", "azure-search", "a2ui", "prompt", "silver", "gold", "report"]

# Targets that live under output/medallion/ (medallion architecture outputs).
_MEDALLION_TARGETS = {"dbt", "silver", "powerbi"}

# Targets processed after the per-domain loop (they span all domains).
_POST_DOMAIN_TARGETS = {"report"}

# Filename patterns that are NOT domain ontologies and should be skipped.
_NON_DOMAIN_SUFFIXES = ("-silver-ext", "-ext")
_NON_DOMAIN_PREFIXES = ("_",)


# ---------------------------------------------------------------------------
# Projection report collector
# ---------------------------------------------------------------------------

@dataclass
class ProjectionReport:
    """Accumulates structured events during a projection run.

    Call :meth:`write` at the end to persist ``projection-report.json``.
    """

    toolkit_version: str = ""
    generated_at: str = ""
    targets_requested: List[str] = field(default_factory=list)

    # {domain_name: {file, triples, namespace, status, ?error}}
    domains: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # [{target, domain, status, ?files_generated, ?files, ?error, ?traceback, ?reason}]
    projections: List[Dict[str, Any]] = field(default_factory=list)

    # [{step, status, ?reason}]
    post_steps: List[Dict[str, Any]] = field(default_factory=list)

    # [{level, ?domain, ?target, message}]
    events: List[Dict[str, Any]] = field(default_factory=list)

    # Running counters
    _total_files: int = field(default=0, repr=False)
    _errors: int = field(default=0, repr=False)
    _warnings: int = field(default=0, repr=False)
    _skipped: int = field(default=0, repr=False)

    # ── recording helpers ──────────────────────────────────────────────

    def record(
        self,
        level: str,
        message: str,
        *,
        domain: Optional[str] = None,
        target: Optional[str] = None,
    ) -> None:
        """Append a structured event (info / warning / error)."""
        entry: Dict[str, Any] = {"level": level, "message": message}
        if domain:
            entry["domain"] = domain
        if target:
            entry["target"] = target
        self.events.append(entry)
        if level == "error":
            self._errors += 1
        elif level == "warning":
            self._warnings += 1

    def record_domain_load(
        self,
        name: str,
        *,
        file: str,
        triples: int = 0,
        namespace: Optional[str] = None,
        status: str = "ok",
        error: Optional[str] = None,
    ) -> None:
        """Record whether a domain ontology was loaded successfully."""
        entry: Dict[str, Any] = {
            "file": file,
            "triples": triples,
            "namespace": namespace,
            "status": status,
        }
        if error:
            entry["error"] = error
        self.domains[name] = entry

    def record_projection(
        self,
        target: str,
        domain: str,
        *,
        status: str,
        files: Optional[List[str]] = None,
        error: Optional[str] = None,
        traceback_str: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Record the outcome of a single target × domain projection."""
        entry: Dict[str, Any] = {
            "target": target,
            "domain": domain,
            "status": status,
        }
        if files is not None:
            entry["files_generated"] = len(files)
            entry["files"] = files
            self._total_files += len(files)
        if error:
            entry["error"] = error
            self._errors += 1
        if traceback_str:
            entry["traceback"] = traceback_str
        if reason:
            entry["reason"] = reason
        if status == "skipped":
            self._skipped += 1
        self.projections.append(entry)

    def record_post_step(
        self,
        step: str,
        *,
        status: str = "ok",
        reason: Optional[str] = None,
    ) -> None:
        """Record a post-domain step (master ERD, SVG export, etc.)."""
        entry: Dict[str, Any] = {"step": step, "status": status}
        if reason:
            entry["reason"] = reason
        if status == "skipped":
            self._skipped += 1
        self.post_steps.append(entry)

    # ── serialisation ──────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Return the full report as a JSON-serialisable dict."""
        return {
            "toolkit_version": self.toolkit_version,
            "generated_at": self.generated_at,
            "targets_requested": self.targets_requested,
            "summary": {
                "domains_found": len(self.domains),
                "domains_loaded": sum(
                    1 for d in self.domains.values() if d["status"] == "ok"
                ),
                "domains_failed_to_load": sum(
                    1 for d in self.domains.values() if d["status"] != "ok"
                ),
                "total_files_generated": self._total_files,
                "errors": self._errors,
                "warnings": self._warnings,
                "skipped": self._skipped,
            },
            "domains": self.domains,
            "projections": self.projections,
            "post_steps": self.post_steps,
            "events": self.events,
        }

    def write(self, output_dir: Path) -> Path:
        """Write ``projection-report.json`` into *output_dir* and return path."""
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "projection-report.json"
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path


def _is_domain_ontology(path: Path) -> bool:
    """Return True if *path* looks like a domain ontology file.

    Excludes annotation/configuration files such as ``*-silver-ext.ttl``
    and metadata files whose name starts with ``_`` (e.g. ``_master.ttl``).
    """
    stem = path.stem
    if any(stem.startswith(p) for p in _NON_DOMAIN_PREFIXES):
        return False
    if any(stem.endswith(s) for s in _NON_DOMAIN_SUFFIXES):
        return False
    return True


def project_graph(
    graph: Graph,
    targets: Optional[List[str]] = None,
    namespace: Optional[str] = None,
    ontology_name: str = "ontology",
    shapes_dir: Optional[Path] = None,
) -> Dict[str, Dict[str, str]]:
    """Generate projection artifacts from an in-memory rdflib Graph.

    Args:
        graph: Loaded rdflib Graph.
        targets: List of projection targets (e.g. ``["dbt", "neo4j"]``).
                 Defaults to all targets.
        namespace: Base namespace to filter classes.  Auto-detected if ``None``.
        ontology_name: Name used in output filenames.
        shapes_dir: Optional path to SHACL shapes directory.

    Returns:
        ``{target: {filename: content}}`` mapping.
        A ``"_report"`` key is added whose value is the
        :class:`ProjectionReport` instance for structured diagnostics.
    """
    from kairos_ontology import __version__ as toolkit_version

    report = ProjectionReport(
        toolkit_version=toolkit_version,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    targets = targets or VALID_TARGETS
    report.targets_requested = list(targets)
    template_base = Path(__file__).parent / "templates"
    ns = namespace or _auto_detect_namespace(graph)
    meta = extract_ontology_metadata(graph, ns)

    report.record_domain_load(
        ontology_name, file=f"{ontology_name}.ttl",
        triples=len(graph), namespace=ns, status="ok",
    )

    results: Dict[str, Dict[str, str]] = {}
    for target_name in targets:
        if target_name not in VALID_TARGETS:
            report.record("warning", f"Unknown target '{target_name}' — skipped")
            continue
        try:
            artifacts = _run_projection(
                target_name, graph, Path("."), template_base, ns, shapes_dir,
                ontology_name, ontology_metadata=meta,
            )
            if artifacts:
                results[target_name] = artifacts
                report.record_projection(
                    target_name, ontology_name,
                    status="ok", files=sorted(artifacts.keys()),
                )
            else:
                report.record_projection(
                    target_name, ontology_name,
                    status="skipped", reason="No classes found in namespace",
                )
        except Exception as exc:
            report.record_projection(
                target_name, ontology_name,
                status="error", error=str(exc), traceback_str=_tb.format_exc(),
            )
            report.record("error", str(exc), domain=ontology_name, target=target_name)

    results["_report"] = report  # type: ignore[assignment]
    return results


def _discover_extensions(
    target_name: str,
    onto_name: str,
    onto_info: dict,
    extensions_dir: Optional[Path],
) -> tuple[Optional[Path], Optional[Path]]:
    """Discover extension files for a given target and ontology domain.

    Returns:
        (ext_path, gold_ext_path) tuple. Either may be None.
    """
    ext_path: Optional[Path] = None
    gold_ext_path: Optional[Path] = None
    src_file: Path = onto_info["file"]

    if target_name == "silver":
        # Look in model/extensions/ first (new layout)
        if extensions_dir and extensions_dir.exists():
            candidates = list(extensions_dir.glob(f"{onto_name}-silver-ext.ttl"))
            candidates += list(extensions_dir.glob("*-silver-ext.ttl"))
            ext_path = candidates[0] if candidates else None
        # Fallback: check alongside the ontology file (legacy layout)
        if not ext_path:
            candidates = list(src_file.parent.glob(f"{onto_name}-silver-ext.ttl"))
            candidates += list(src_file.parent.glob("*-silver-ext.ttl"))
            ext_path = candidates[0] if candidates else None

    elif target_name == "powerbi":
        if extensions_dir and extensions_dir.exists():
            candidates = list(extensions_dir.glob(f"{onto_name}-gold-ext.ttl"))
            candidates += list(extensions_dir.glob("*-gold-ext.ttl"))
            ext_path = candidates[0] if candidates else None
        if not ext_path:
            candidates = list(src_file.parent.glob(f"{onto_name}-gold-ext.ttl"))
            candidates += list(src_file.parent.glob("*-gold-ext.ttl"))
            ext_path = candidates[0] if candidates else None

    elif target_name == "dbt":
        # dbt needs silver-ext.ttl for naturalKey/silver annotations
        if extensions_dir and extensions_dir.exists():
            candidates = list(extensions_dir.glob(f"{onto_name}-silver-ext.ttl"))
            candidates += list(extensions_dir.glob("*-silver-ext.ttl"))
            ext_path = candidates[0] if candidates else None
        if not ext_path:
            candidates = list(src_file.parent.glob(f"{onto_name}-silver-ext.ttl"))
            candidates += list(src_file.parent.glob("*-silver-ext.ttl"))
            ext_path = candidates[0] if candidates else None
        # dbt also needs gold-ext.ttl for gold model generation
        if extensions_dir and extensions_dir.exists():
            candidates = list(extensions_dir.glob(f"{onto_name}-gold-ext.ttl"))
            candidates += list(extensions_dir.glob("*-gold-ext.ttl"))
            gold_ext_path = candidates[0] if candidates else None
        if not gold_ext_path:
            candidates = list(src_file.parent.glob(f"{onto_name}-gold-ext.ttl"))
            candidates += list(src_file.parent.glob("*-gold-ext.ttl"))
            gold_ext_path = candidates[0] if candidates else None

    return ext_path, gold_ext_path


def _write_artifacts(artifacts: dict[str, str], target_output: Path) -> int:
    """Write projection artifacts to disk.

    Args:
        artifacts: Mapping of relative file path to content.
        target_output: Base output directory.

    Returns:
        Number of files written.
    """
    for file_path, content in artifacts.items():
        output_file = target_output / file_path
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(content, encoding='utf-8')
    return len(artifacts)


def run_projections(ontologies_path: Path, catalog_path: Path, output_path: Path, target: str, namespace: str = None):
    """Run projection generation.
    
    Args:
        ontologies_path: Path to ontology files
        catalog_path: Path to XML catalog for imports
        output_path: Where to write generated files
        target: Projection target (dbt, neo4j, etc.) or 'all'
        namespace: Base namespace to project (e.g., 'http://example.org/ont/'). 
                   If None, auto-detects from ontology.
    """
    from kairos_ontology import __version__ as toolkit_version

    report = ProjectionReport(
        toolkit_version=toolkit_version,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    print("🚀 Kairos Ontology Projections")
    print("=" * 50)
    
    # Get all ontology files
    ontology_files = list(ontologies_path.glob("**/*.ttl")) + list(ontologies_path.glob("**/*.rdf"))
    # Skip non-domain files: silver-ext annotations, _master imports, etc.
    ontology_files = [f for f in ontology_files if _is_domain_ontology(f)]
    
    if not ontology_files:
        print(f"  ⚠️  No ontology files found in {ontologies_path}")
        report.record("warning", f"No ontology files found in {ontologies_path}")
        report.write(output_path)
        return
    
    print(f"\nFound {len(ontology_files)} ontology file(s)")
    print("Each ontology will generate separate output files per domain\n")
    
    # Process each ontology file separately (each represents a data domain)
    print("Loading ontologies...")
    ontology_graphs = []
    
    for onto_file in ontology_files:
        try:
            file_graph = Graph()
            if catalog_path and catalog_path.exists():
                # Load with catalog support for imports
                from .catalog_utils import load_graph_with_catalog
                file_graph = load_graph_with_catalog(onto_file, catalog_path)
            else:
                # Load without catalog
                file_graph.parse(onto_file, format='turtle' if onto_file.suffix == '.ttl' else 'xml')
            
            # Store graph with its source file info
            ontology_graphs.append({
                'file': onto_file,
                'graph': file_graph,
                'name': onto_file.stem
            })
            print(f"  ✓ Loaded {onto_file.name} ({len(file_graph)} triples)")
            report.record_domain_load(
                onto_file.stem,
                file=onto_file.name,
                triples=len(file_graph),
                status="ok",
            )
        except Exception as e:
            print(f"  ⚠️  Could not parse {onto_file.name}: {e}")
            report.record_domain_load(
                onto_file.stem,
                file=onto_file.name,
                status="load_failed",
                error=str(e),
            )
            report.record("error", f"Could not parse {onto_file.name}: {e}",
                          domain=onto_file.stem)
    
    if not ontology_graphs:
        print("  ⚠️  No ontologies loaded - check ontology files exist")
        report.record("error", "No ontologies loaded — check ontology files exist")
        report.write(output_path)
        return
    
    print()
    
    # Create output directories
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Determine template directory
    template_base = Path(__file__).parent / "templates"
    
    # Look for SHACL shapes directory — hub layout: model/ontologies/, model/shapes/
    hub_root = ontologies_path.parent.parent if ontologies_path.parent else None
    shapes_dir = hub_root / "model" / "shapes" if hub_root else None
    if shapes_dir and shapes_dir.exists():
        print(f"  Found SHACL shapes directory: {shapes_dir}\n")

    # Look for source system reference docs (with bronze vocab) and SKOS mappings
    sources_dir = hub_root / "integration" / "sources" if hub_root else None
    mappings_dir = hub_root / "model" / "mappings" if hub_root else None
    extensions_dir = hub_root / "model" / "extensions" if hub_root else None
    if sources_dir and sources_dir.exists():
        print(f"  Found source system references: {sources_dir}")
    if mappings_dir and mappings_dir.exists():
        print(f"  Found SKOS mappings directory: {mappings_dir}\n")

    targets_to_run = (
        ['dbt', 'neo4j', 'azure-search', 'a2ui', 'prompt', 'silver', 'powerbi', 'report']
        if target == 'all' else [target]
    )
    report.targets_requested = list(targets_to_run)

    # Accumulate per-domain manifest data: {domain_name: {meta, targets: {target: [files]}}}
    manifests: dict[str, dict] = {}

    for target_name in targets_to_run:
        # Report target is handled after the per-domain loop (spans all domains)
        if target_name in _POST_DOMAIN_TARGETS:
            continue
        print(f"📦 Generating {target_name} projection...")
        # Medallion targets go under output/medallion/; others directly under output/
        # Silver artifacts are consolidated into the dbt project tree
        if target_name in _MEDALLION_TARGETS:
            target_output = output_path / "medallion" / (
                "dbt" if target_name == "silver" else target_name
            )
        else:
            target_output = output_path / target_name
        target_output.mkdir(parents=True, exist_ok=True)
        
        total_files = 0
        
        for onto_info in ontology_graphs:
            onto_graph = onto_info['graph']
            onto_name = onto_info['name']
            
            # Auto-detect namespace for this ontology if not provided
            onto_namespace = namespace
            if onto_namespace is None:
                onto_namespace = _auto_detect_namespace(onto_graph)
                print(f"  [{onto_name}] Auto-detected namespace: {onto_namespace}")

            # Extract ontology provenance metadata
            onto_meta = extract_ontology_metadata(onto_graph, onto_namespace)

            # Populate namespace on the domain entry (first time we know it)
            if onto_name in report.domains and not report.domains[onto_name].get("namespace"):
                report.domains[onto_name]["namespace"] = onto_namespace
            
            try:
                # Discover extension files for this target/domain
                ext_path, gold_ext_path = _discover_extensions(
                    target_name, onto_name, onto_info, extensions_dir
                )
                if ext_path:
                    label = "silver ext" if target_name == "dbt" else "projection ext"
                    print(f"  [{onto_name}] Using {label}: {ext_path.name}")
                    report.record("info", f"Using {label}: {ext_path.name}",
                                  domain=onto_name, target=target_name)
                if gold_ext_path:
                    print(f"  [{onto_name}] Using gold ext: {gold_ext_path.name}")
                    report.record("info", f"Using gold ext: {gold_ext_path.name}",
                                  domain=onto_name, target=target_name)

                artifacts = _run_projection(target_name, onto_graph, target_output, template_base,
                                            onto_namespace, shapes_dir, onto_name,
                                            projection_ext_path=ext_path,
                                            gold_ext_path=gold_ext_path,
                                            ontology_metadata=onto_meta,
                                            sources_dir=sources_dir,
                                            mappings_dir=mappings_dir)
                if artifacts:
                    total_files += _write_artifacts(artifacts, target_output)
                    print(f"  [{onto_name}] ✓ Generated {len(artifacts)} file(s)")
                    report.record_projection(
                        target_name, onto_name,
                        status="ok",
                        files=sorted(artifacts.keys()),
                    )

                    # Track for manifest
                    if onto_name not in manifests:
                        manifests[onto_name] = {
                            "meta": onto_meta,
                            "targets": {},
                        }
                    manifests[onto_name]["targets"][target_name] = sorted(artifacts.keys())
                else:
                    report.record_projection(
                        target_name, onto_name,
                        status="skipped",
                        reason="No classes found in namespace",
                    )
                    report.record("info",
                                  "No classes found in namespace — skipped",
                                  domain=onto_name, target=target_name)
            except Exception as e:
                print(f"  [{onto_name}] ✗ Failed: {e}")
                _tb.print_exc()
                report.record_projection(
                    target_name, onto_name,
                    status="error",
                    error=str(e),
                    traceback_str=_tb.format_exc(),
                )
                report.record("error", str(e),
                              domain=onto_name, target=target_name)

        # After all domains: generate master ERD for silver target
        if target_name == "silver" and total_files > 0:
            from .projections.medallion_silver_projector import generate_master_erd, render_mermaid_svg
            dbt_output = output_path / "medallion" / "dbt"
            hub_name = ontologies_path.parent.parent.name if ontologies_path.parent else "ontology-hub"
            master_mmd = generate_master_erd(dbt_output, hub_name=hub_name)
            if master_mmd:
                diagrams_dir = dbt_output / "docs" / "diagrams"
                diagrams_dir.mkdir(parents=True, exist_ok=True)
                master_path = diagrams_dir / "master-erd.mmd"
                master_path.write_text(master_mmd, encoding="utf-8")
                total_files += 1
                print(f"  ✓ Master ERD written: dbt/docs/diagrams/master-erd.mmd")
                report.record_post_step("master_silver_erd", status="ok")
            else:
                report.record_post_step("master_silver_erd", status="skipped",
                                        reason="No domain ERDs found to merge")

            # Render all .mmd files to SVG via Mermaid CLI (if available)
            svg_count = 0
            diagrams_root = dbt_output / "docs" / "diagrams"
            if diagrams_root.exists():
                for mmd_file in sorted(diagrams_root.rglob("*.mmd")):
                    svg = render_mermaid_svg(mmd_file)
                    if svg:
                        svg_count += 1
            if svg_count:
                total_files += svg_count
                print(f"  ✓ Rendered {svg_count} SVG file(s) via Mermaid CLI")
                report.record_post_step("silver_svg_export", status="ok")
            else:
                print("  [info] Mermaid CLI (mmdc) not found -- SVG export skipped."
                      " Install: npm install -D @mermaid-js/mermaid-cli")
                report.record_post_step("silver_svg_export", status="skipped",
                                        reason="mmdc not found on PATH")

        # After all domains: generate master gold ERD
        if target_name == "powerbi" and total_files > 0:
            from .projections.medallion_gold_projector import generate_master_gold_erd
            from .projections.medallion_silver_projector import render_mermaid_svg
            gold_output = output_path / "medallion" / "powerbi"
            hub_name = ontologies_path.parent.parent.name if ontologies_path.parent else "ontology-hub"
            master_mmd = generate_master_gold_erd(gold_output, hub_name=hub_name)
            if master_mmd:
                master_path = gold_output / "master-gold-erd.mmd"
                master_path.write_text(master_mmd, encoding="utf-8")
                total_files += 1
                print(f"  ✓ Master Gold ERD written: powerbi/master-gold-erd.mmd")
                report.record_post_step("master_gold_erd", status="ok")
            else:
                report.record_post_step("master_gold_erd", status="skipped",
                                        reason="No domain gold ERDs found to merge")

            svg_count = 0
            if gold_output.exists():
                for mmd_file in sorted(gold_output.rglob("*.mmd")):
                    svg = render_mermaid_svg(mmd_file)
                    if svg:
                        svg_count += 1
            if svg_count:
                total_files += svg_count
                print(f"  ✓ Rendered {svg_count} SVG file(s) via Mermaid CLI")
                report.record_post_step("gold_svg_export", status="ok")
            else:
                print("  [info] Mermaid CLI (mmdc) not found -- SVG export skipped."
                      " Install: npm install -D @mermaid-js/mermaid-cli")
                report.record_post_step("gold_svg_export", status="skipped",
                                        reason="mmdc not found on PATH")

        print(f"  ✓ {target_name} projection completed: {total_files} total files\n")

    # ── Post-domain targets (span all ontology domains) ──────────────────
    if "report" in targets_to_run:
        print("📦 Generating report projection...")
        report_output = output_path / "report"
        report_output.mkdir(parents=True, exist_ok=True)

        # Merge all domain ontology graphs for cross-domain property lookup
        merged_classes: dict = {}
        for onto_info in ontology_graphs:
            onto_ns = namespace or _auto_detect_namespace(onto_info["graph"])
            if onto_ns:
                from .projections.report_projector import (
                    _extract_ontology_properties,
                )
                domain_classes = _extract_ontology_properties(
                    onto_info["graph"], onto_ns
                )
                merged_classes.update(domain_classes)

        from .projections.report_projector import generate_mapping_report
        report_artifacts = generate_mapping_report(
            ontology_classes=merged_classes,
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            template_dir=template_base,
        )
        report_count = 0
        for fname, html in report_artifacts.items():
            out_file = report_output / fname
            out_file.write_text(html, encoding="utf-8")
            report_count += 1
            print(f"  ✓ {fname}")
        print(f"  ✓ report projection completed: {report_count} total files\n")
        report.record_post_step("mapping_report", status="ok")
    
    print("✅ Projection generation completed!")
    print(f"   Generated artifacts for {len(ontology_graphs)} data domain(s)")

    # Write per-domain projection manifests
    for domain_name, mdata in manifests.items():
        manifest = {
            "domain": domain_name,
            "ontology_iri": mdata["meta"]["iri"],
            "ontology_version": mdata["meta"]["version"],
            "ontology_label": mdata["meta"]["label"],
            "namespace": mdata["meta"]["namespace"],
            "toolkit_version": mdata["meta"]["toolkit_version"],
            "generated_at": mdata["meta"]["generated_at"],
            "targets": mdata["targets"],
        }
        manifest_path = output_path / f"{domain_name}-projection-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"   📋 Manifest: {manifest_path.name}")

    # Write the projection report
    report_path = report.write(output_path)
    print(f"   📋 Report:   {report_path.name}")


def extract_ontology_metadata(graph: Graph, namespace: str) -> dict:
    """Extract provenance metadata from the owl:Ontology declaration.

    Returns a dict with keys: ``iri``, ``version``, ``label``, ``namespace``,
    ``toolkit_version``, and ``generated_at``.  Missing values default to
    sensible placeholders so callers can always rely on the keys being present.
    """
    from kairos_ontology import __version__ as toolkit_version

    iri: str = namespace.rstrip("#/")
    version: str = ""
    label: str = ""

    # Find the owl:Ontology that lives in the given namespace
    for subj in graph.subjects(predicate=None, object=OWL.Ontology):
        subj_str = str(subj)
        if subj_str.startswith(namespace.rstrip("#/")):
            iri = subj_str
            ver = graph.value(subj, OWL.versionInfo)
            if ver:
                version = str(ver)
            lbl = graph.value(subj, RDFS.label)
            if lbl:
                label = str(lbl)
            break

    return {
        "iri": iri,
        "version": version,
        "label": label,
        "namespace": namespace,
        "toolkit_version": toolkit_version,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _auto_detect_namespace(graph: Graph) -> str:
    """Auto-detect the ontology's base namespace using semantic web best practices.
    
    Method 1: Check owl:Ontology declaration (preferred - semantic web standard)
    Method 2: Exclude owl:imports and count classes in remaining namespaces
    Method 3: Fallback to URN format
    
    This approach scales to any external ontology without hardcoded exclusion lists.
    """
    
    # Method 1: Look for owl:Ontology declaration (BEST PRACTICE)
    # The namespace containing the owl:Ontology instance is the main ontology namespace
    ontology_query = """
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    
    SELECT ?ontology
    WHERE {
        ?ontology a owl:Ontology .
    }
    """
    
    # Standard W3C namespaces to always exclude
    standard_namespaces = {
        'http://www.w3.org/2002/07/owl#',
        'http://www.w3.org/2000/01/rdf-schema#',
        'http://www.w3.org/2004/02/skos/core#',
        'http://www.w3.org/2001/XMLSchema#',
        'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    }
    
    ontology_namespaces = []
    for row in graph.query(ontology_query):
        onto_uri = str(row['ontology'])
        
        # Extract namespace from ontology URI.
        # Key insight: many ontologies declare URI without '#' (e.g.
        # https://example.com/ont/client) but their classes use '#' fragments
        # (e.g. https://example.com/ont/client#Client).  In that case the
        # namespace is '{onto_uri}#', NOT the parent path.
        if '#' in onto_uri:
            namespace = onto_uri.rsplit('#', 1)[0] + '#'
        else:
            # Probe: do any owl:Class URIs start with '{onto_uri}#'?
            hash_ns = onto_uri + '#'
            has_hash_classes = any(
                str(cls).startswith(hash_ns)
                for cls in graph.subjects(RDF.type, OWL.Class)
                if isinstance(cls, URIRef)
            )
            if has_hash_classes:
                namespace = hash_ns
            elif '/' in onto_uri:
                namespace = onto_uri.rsplit('/', 1)[0] + '/'
            else:
                namespace = onto_uri + ':'  # URN format
        
        # Skip standard W3C ontologies
        if namespace not in standard_namespaces:
            ontology_namespaces.append(namespace)
    
    # Method 2: Get imported ontology namespaces to exclude
    imports_query = """
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    
    SELECT ?imported
    WHERE {
        ?ontology owl:imports ?imported .
    }
    """
    
    imported_namespaces = set()
    for row in graph.query(imports_query):
        import_uri = str(row['imported'])
        
        # Extract namespace from import URI
        if '#' in import_uri:
            namespace = import_uri.rsplit('#', 1)[0] + '#'
        elif '/' in import_uri:
            namespace = import_uri.rsplit('/', 1)[0] + '/'
        else:
            namespace = import_uri + ':'
        
        imported_namespaces.add(namespace)
    
    # If we found owl:Ontology declarations, prefer the one that's NOT imported
    if ontology_namespaces:
        for onto_ns in ontology_namespaces:
            # Check if this ontology namespace is NOT in the imports
            if onto_ns not in imported_namespaces:
                return onto_ns
        
        # If all ontology namespaces are imported (rare), return the first one
        return ontology_namespaces[0]
    
    # Method 3: Fallback - count classes per namespace, excluding imports and standards
    class_query = """
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    
    SELECT ?class
    WHERE {
        ?class a owl:Class .
        FILTER(isIRI(?class))
    }
    """
    
    namespace_counts = {}
    for row in graph.query(class_query):
        class_uri = str(row['class'])
        
        # Extract namespace
        if '#' in class_uri:
            namespace = class_uri.rsplit('#', 1)[0] + '#'
        elif '/' in class_uri:
            namespace = class_uri.rsplit('/', 1)[0] + '/'
        else:
            namespace = class_uri.rsplit(':', 1)[0] + ':'
        
        # Skip standard W3C namespaces
        if namespace in standard_namespaces:
            continue
        
        # Skip imported namespaces
        if namespace in imported_namespaces:
            continue
        
        namespace_counts[namespace] = namespace_counts.get(namespace, 0) + 1
    
    if namespace_counts:
        # Return namespace with most classes
        return max(namespace_counts, key=namespace_counts.get)
    
    # Ultimate fallback
    return "urn:kairos:ont:core:"


def _run_projection(target: str, graph: Graph, output_path: Path, template_base: Path,
                    namespace: str, shapes_dir: Path = None, ontology_name: str = None,
                    projection_ext_path: Optional[Path] = None,
                    gold_ext_path: Optional[Path] = None,
                    ontology_metadata: Optional[dict] = None,
                    sources_dir: Optional[Path] = None,
                    mappings_dir: Optional[Path] = None) -> dict:
    """Run a specific projection type using simplified logic.
    
    Args:
        target: Projection type (dbt, neo4j, azure-search, a2ui, prompt, silver)
        graph: RDFLib graph for this specific ontology
        output_path: Base output path for this target
        template_base: Path to templates
        namespace: Namespace to filter classes
        shapes_dir: Optional SHACL shapes directory
        ontology_name: Name of the ontology file (without extension)
        projection_ext_path: Optional path to *-silver-ext.ttl (silver target only)
        gold_ext_path: Optional path to *-gold-ext.ttl (dbt target — for gold models)
        ontology_metadata: Provenance metadata from extract_ontology_metadata()
        sources_dir: Optional path to integration/sources/ directory (dbt target)
        mappings_dir: Optional path to mappings/ SKOS directory (dbt target)
    """
    
    query = """
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    
    SELECT ?class ?label ?comment
    WHERE {
        ?class a owl:Class .
        OPTIONAL { ?class rdfs:label ?label }
        OPTIONAL { ?class rdfs:comment ?comment }
        FILTER(isIRI(?class))
    }
    """
    
    classes = []
    for row in graph.query(query):
        class_uri = str(row['class'])
        if not class_uri.startswith(namespace):
            continue
        
        class_name = extract_local_name(class_uri)
        classes.append(OntologyClassInfo(
            uri=class_uri,
            name=class_name,
            label=str(row.label) if row.label else class_name,
            comment=str(row.comment) if row.comment else f"{class_name} entity",
        ).to_dict())
    
    if not classes:
        return {}
    
    meta = ontology_metadata or {}

    # Generate based on target using full-featured projector classes
    # Pass ontology_name so each projector can create domain-specific filenames
    if target == 'dbt':
        from .projections.medallion_dbt_projector import generate_dbt_artifacts
        return generate_dbt_artifacts(
            classes, graph, template_base / "dbt", namespace, shapes_dir,
            ontology_name, ontology_metadata=meta,
            bronze_dir=sources_dir, sources_dir=sources_dir, mappings_dir=mappings_dir,
            gold_ext_path=gold_ext_path,
            silver_ext_path=projection_ext_path,
        )
    elif target == 'neo4j':
        from .projections.neo4j_projector import generate_neo4j_artifacts
        return generate_neo4j_artifacts(
            classes, graph, template_base / "neo4j", namespace,
            ontology_name, ontology_metadata=meta,
        )
    elif target == 'azure-search':
        from .projections.azure_search_projector import generate_azure_search_artifacts
        return generate_azure_search_artifacts(
            classes, graph, template_base / "azure-search", namespace,
            ontology_name, ontology_metadata=meta,
        )
    elif target == 'a2ui':
        from .projections.a2ui_projector import generate_a2ui_artifacts
        return generate_a2ui_artifacts(
            classes, graph, template_base / "a2ui", namespace,
            ontology_name, ontology_metadata=meta,
        )
    elif target == 'prompt':
        from .projections.prompt_projector import generate_prompt_artifacts
        return generate_prompt_artifacts(
            classes, graph, template_base / "prompt", namespace,
            ontology_name, ontology_metadata=meta,
        )
    elif target == 'silver':
        from .projections.medallion_silver_projector import generate_silver_artifacts
        return generate_silver_artifacts(
            classes=classes,
            graph=graph,
            namespace=namespace,
            shapes_dir=shapes_dir,
            ontology_name=ontology_name or "domain",
            projection_ext_path=projection_ext_path,
            ontology_metadata=meta,
        )
    elif target == 'powerbi':
        from .projections.medallion_gold_projector import generate_gold_artifacts
        return generate_gold_artifacts(
            classes=classes,
            graph=graph,
            namespace=namespace,
            shapes_dir=shapes_dir,
            ontology_name=ontology_name or "domain",
            projection_ext_path=projection_ext_path,
            ontology_metadata=meta,
        )
    
    return {}
