# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``scaffold-extensions``: draft OWL for the accepted extension decisions (#883)."""

from __future__ import annotations

from pathlib import Path

import click

from ..core.extension_stubs import build_extension_stubs
from ..core.hub_utils import find_hub_root


@click.command(name="scaffold-extensions")
@click.option("--domain", required=True, help="Hub data domain to render extensions for.")
@click.option(
    "-o",
    "--out",
    "out_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Output draft TTL path (default: "
    "<repo>/ontology-hub-publish/extensions-draft/<domain>.ttl).",
)
@click.option(
    "--namespace",
    default=None,
    help="Property namespace (default: the domain ontology's own, from catalog-v001.xml).",
)
@click.option("--dry-run", is_flag=True, default=False, help="Print the draft, write nothing.")
def scaffold_extensions_cmd(domain: str, out_path: Path | None, namespace: str | None, dry_run: bool):
    """Draft OWL properties from the accepted ``registered-extension`` decisions.

    Every property rendered was already decided — this reads the disposition ledger and
    writes what is recorded there, with the name, range and owning class the aligner
    proposed. It makes no judgement of its own.

    That matters because the decisions had no consumer. ``registered-extension``'s own
    definition points at ``register-concept``, which registers a *class* the archetype
    catalog lacks; these are *columns* wanting *properties* on classes that already
    exist. An operator who closed the gate column by column ended up re-deriving every
    property by hand from a second file.

    Output is a DRAFT written outside ``model/ontologies/`` so the validator does not
    load it, the same contract ``suggest-shapes`` uses (DD-076): review it as a diff and
    move what you accept into the owning domain's ontology.

    Skipped and reported, never guessed: a non-datatype range (an object property needs
    a target class and a relationship decision), a name that is not camelCase, and a name
    accepted with two different class or range readings.

    Examples:
      kairos-ontology scaffold-extensions --domain roro --dry-run
      kairos-ontology scaffold-extensions --domain roro
    """
    hub_root = find_hub_root(Path.cwd())
    if hub_root is None:
        raise click.ClickException("no ontology hub found from the current directory")

    resolved_namespace = namespace or _domain_namespace(hub_root, domain)
    text, report = build_extension_stubs(hub_root, domain=domain, namespace=resolved_namespace)

    click.echo(f"🧩 scaffold-extensions — domain '{domain}'")
    click.echo(f"   registered-extension decisions seen: {report.decisions_seen}")
    click.echo(f"   properties rendered:                 {len(report.properties)}")
    if report.classes:
        for on_class, count in report.classes.items():
            local = on_class.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
            click.echo(f"     {local}: {count}")
    if report.skipped:
        click.echo(f"   skipped, needing a decision:         {len(report.skipped)}")
        for item in report.skipped[:8]:
            click.echo(f"     {item['property']}: {item['reason']}")
        if len(report.skipped) > 8:
            click.echo(f"     … and {len(report.skipped) - 8} more")

    if not report.properties:
        click.echo(
            "\n   Nothing to render. Either the gate has no accepted extensions for this "
            "domain, or its decisions predate the structured property and record it only "
            "in their prose rationale — re-run draft-gap-decisions to restore it."
        )
        return

    if dry_run:
        click.echo("\n" + text)
        return

    target = out_path or (
        hub_root.parent / "ontology-hub-publish" / "extensions-draft" / f"{domain}.ttl"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    click.echo(f"\n✅ Draft written: {target}")
    click.echo(
        "   DRAFT — outside model/ontologies/ so the validator does not load it. Review "
        "and move what you accept into the owning domain's ontology."
    )


def _domain_namespace(hub_root: Path, domain: str) -> str:
    """The domain ontology's own namespace, so a rendered property lands in it.

    Read from the hub catalog, which maps each domain ontology URI to its file. Falls
    back to the ``_master.ttl`` base with the domain appended, which is the shape
    ``scaffold-domain`` mints.
    """
    catalog = hub_root / "catalog-v001.xml"
    if catalog.is_file():
        try:
            import re

            text = catalog.read_text(encoding="utf-8")
            match = re.search(
                rf'uri\s+name="([^"]*/{re.escape(domain)})"', text
            )
            if match:
                return match.group(1) + "#"
        except OSError:
            pass
    master = hub_root / "model" / "ontologies" / "_master.ttl"
    if master.is_file():
        try:
            import re

            match = re.search(r"<(https?://[^>]+)/master>", master.read_text(encoding="utf-8"))
            if match:
                return f"{match.group(1)}/{domain}#"
        except OSError:
            pass
    return f"https://example.com/ont/{domain}#"
