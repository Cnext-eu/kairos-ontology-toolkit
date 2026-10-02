# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``business-doc``: a domain's business validation document (DD-254, #1105)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import click

from ..core.hub_utils import find_hub_root, publish_root
from ..core.projections.business_doc import (
    FACTS_FILENAME,
    BusinessDocError,
    build_facts,
    facts_json,
    load_narrative,
    validate_narrative,
)


def _output_dir(hub: Path, domain: str, output: Optional[Path]) -> Path:
    return output if output is not None else publish_root(hub) / "business" / domain


def _rasterizer(warnings: list[str]):
    from ..core.projections.business_doc.diagram_svg import find_browser, svg_to_png

    browser = find_browser()
    if browser is None:
        warnings.append(
            "no headless Chrome, Chromium or Edge found: diagrams are written as SVG beside "
            "the document (set KAIROS_CHROME to a browser executable to embed them)"
        )
        return None

    def rasterize(svg: str, width: float, height: float) -> Optional[bytes]:
        try:
            return svg_to_png(svg, width, height, browser)
        except RuntimeError as exc:
            warnings.append(str(exc))
            return None

    return rasterize


@click.command(name="business-doc")
@click.argument("domain")
@click.option(
    "--facts",
    "mode",
    flag_value="facts",
    help="Write business-doc.facts.json: the domain's facts, read from the hub.",
)
@click.option(
    "--render",
    "mode",
    flag_value="render",
    help="Validate --narrative against the facts and write the Word document.",
)
@click.option(
    "--narrative",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="The confirmed business-doc.narrative.yaml (required with --render).",
)
@click.option(
    "--version",
    "doc_version",
    type=click.IntRange(min=1),
    help="Document version; defaults to the narrative's document.version.",
)
@click.option(
    "--entity",
    "entities",
    multiple=True,
    help="Core entity (CURIE or IRI); repeat. Default: the classes bound in the domain.",
)
@click.option(
    "--output",
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory. Default: ontology-hub-publish/business/<domain>/.",
)
@click.option("--no-pdf", is_flag=True, help="Skip the PDF preview.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
)
def business_doc_cmd(
    domain: str,
    mode: Optional[str],
    narrative: Optional[Path],
    doc_version: Optional[int],
    entities: tuple[str, ...],
    output: Optional[Path],
    no_pdf: bool,
    output_format: str,
) -> None:
    """Build a domain's logical data model document for business sign-off.

    \b
    --facts   derives every fact from the ontology closure, the Silver contract, the
              compile plan, the source ledgers and the decisions; the same hub gives the
              same bytes.
    --render  joins those facts with the confirmed narrative and writes
              <domain>-validation-v<N>.docx (+ a PDF preview when LibreOffice or Word is
              available). A narrative that names an unknown ID, or leaves an entity,
              relationship or field unplaced without an omitted: reason, is refused.

    The document is evidence for a design decision, never for a compile or a release.
    """
    if mode is None:
        raise click.UsageError("choose --facts or --render")
    if mode == "render" and narrative is None:
        raise click.UsageError("--render needs --narrative <business-doc.narrative.yaml>")
    hub = find_hub_root(Path.cwd(), require_model=True)
    if hub is None:
        raise click.ClickException("no ontology hub here (model/ontologies/ not found)")
    try:
        facts = build_facts(hub, domain, entities=entities)
    except BusinessDocError as exc:
        raise click.ClickException(str(exc)) from exc
    out_dir = _output_dir(hub, domain, output)
    out_dir.mkdir(parents=True, exist_ok=True)
    facts_path = out_dir / FACTS_FILENAME
    facts_path.write_text(facts_json(facts), encoding="utf-8", newline="\n")

    if mode == "facts":
        summary = {
            "ok": True,
            "domain": domain,
            "facts": str(facts_path),
            "facts_hash": facts["facts_hash"],
            "entities": len(facts["entities"]),
            "relationships": len(facts["relationships"]),
            "externals": len(facts["externals"]),
            "candidate_gaps": len(facts["candidate_gaps"]),
            "warnings": facts["warnings"],
        }
        if output_format == "json":
            click.echo(json.dumps(summary, indent=2))
            return
        click.echo(f"✅ Facts for {domain}: {facts_path}")
        click.echo(
            f"   {summary['entities']} entities, {summary['relationships']} "
            f"relationships, {summary['externals']} external entities, "
            f"{summary['candidate_gaps']} candidate gaps"
        )
        for warning in facts["warnings"]:
            click.echo(f"   ⚠ {warning}")
        return

    try:
        document = load_narrative(narrative)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    errors = validate_narrative(facts, document)
    if errors:
        if output_format == "json":
            click.echo(json.dumps({"ok": False, "errors": errors}, indent=2))
        else:
            click.echo(f"✗ The narrative does not match the facts ({len(errors)}):", err=True)
            for error in errors:
                click.echo(f"   ✗ {error}", err=True)
        raise SystemExit(1)

    from ..core.projections.business_doc.render_docx import pdf_preview, render_document

    warnings: list[str] = list(facts["warnings"])
    try:
        result = render_document(
            facts, document, version=doc_version, rasterize=_rasterizer(warnings)
        )
    except BusinessDocError as exc:
        raise click.ClickException(str(exc)) from exc
    number = doc_version or int(document["document"]["version"])
    docx_path = out_dir / f"{domain}-validation-v{number}.docx"
    docx_path.write_bytes(result.docx)
    svg_paths = []
    for name, svg in sorted(result.svgs.items()):
        path = out_dir / name
        path.write_text(svg, encoding="utf-8", newline="\n")
        svg_paths.append(str(path))
    warnings += result.warnings
    pdf = None if no_pdf else pdf_preview(docx_path)
    if pdf is None and not no_pdf:
        warnings.append("no PDF preview: neither LibreOffice nor Word was available")

    payload = {
        "ok": True,
        "domain": domain,
        "document": str(docx_path),
        "pdf": pdf,
        "svgs": svg_paths,
        "document_version": number,
        "model_version": facts["model_version"],
        "facts_hash": facts["facts_hash"],
        "warnings": warnings,
    }
    if output_format == "json":
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"✅ {docx_path}")
    if pdf:
        click.echo(f"   PDF preview: {pdf}")
    click.echo(
        f"   document v{number}, model {facts['model_version'] or 'unversioned'}, "
        f"facts {facts['facts_hash'][:12]}"
    )
    for warning in warnings:
        click.echo(f"   ⚠ {warning}")
