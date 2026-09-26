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
    help="Property namespace (default: the domain ontology's own owl:Ontology IRI plus "
    "'#'). Must be a namespace this hub authors (DD-248).",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Render a property even when the owning class's import closure already has one "
    "of a similar name (DD-248). Without it such a property is skipped and listed.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Print the draft, write nothing.")
def scaffold_extensions_cmd(
    domain: str, out_path: Path | None, namespace: str | None, force: bool, dry_run: bool
):
    """Draft OWL properties from the accepted ``registered-extension`` decisions.

    Every property rendered was already decided — this reads the disposition ledger and
    writes what is recorded there, with the name, range and owning class the aligner
    proposed. It makes no judgement of its own, with one exception (DD-248): a property
    the owning class's import closure already offers under a similar name is skipped
    and listed, because a local copy of an inherited property is the defect this
    command must not manufacture. ``--force`` renders it anyway.

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
    from ..core.hub_namespace import domain_namespace

    hub_root = find_hub_root(Path.cwd())
    if hub_root is None:
        raise click.ClickException("no ontology hub found from the current directory")

    resolved_namespace = namespace or domain_namespace(hub_root, domain)
    _refuse_unsafe_namespace(hub_root, domain, resolved_namespace)
    text, report = build_extension_stubs(
        hub_root, domain=domain, namespace=resolved_namespace, force=force
    )

    click.echo(f"🧩 scaffold-extensions — domain '{domain}'")
    click.echo(f"   registered-extension decisions seen: {report.decisions_seen}")
    click.echo(f"   properties rendered:                 {len(report.properties)}")
    if report.classes:
        for on_class, count in report.classes.items():
            local = on_class.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
            click.echo(f"     {local}: {count}")
    if report.closure_candidates:
        verb = "rendered anyway (--force)" if force else "not rendered; --force overrides"
        click.echo(f"   closure candidates ({verb}):        {len(report.closure_candidates)}")
        for item in report.closure_candidates[:8]:
            best = item["candidates"][0]
            click.echo(
                f"     {item['property']} -> <{best['uri']}> ({best['match']}, {best['score']})"
            )
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


def _refuse_unsafe_namespace(hub_root: Path, domain: str, namespace: str | None) -> None:
    """A property is minted only into a namespace this hub authors (DD-248 §5).

    The previous heuristic fell back to ``https://example.com/ont/<domain>#`` and took any
    ``--namespace``, so a draft could land in a placeholder or in a reference module's
    namespace and validate clean. Both are refused with the fix named.
    """
    from ..core.hub_namespace import hub_ontology_namespaces, namespace_of

    if not namespace:
        raise click.ClickException(
            f"domain '{domain}' has no ontology under model/ontologies/ declaring an "
            "owl:Ontology IRI, so there is no namespace to mint into. Register the domain "
            "(`kairos-ontology scaffold-domain` / `init --domain`), or pass "
            "`--namespace <hub IRI>#`."
        )
    authored = hub_ontology_namespaces(hub_root)
    base = namespace_of(namespace.rstrip("#/") + "#").rstrip("#/")
    if base in authored:
        return
    owner = _reference_module_for(hub_root, base)
    detail = (
        f"it belongs to reference module <{owner}>; a hub never declares a property into "
        "a module it does not own"
        if owner
        else "it is not a namespace this hub authors"
    )
    raise click.ClickException(
        f"refusing to mint properties into <{namespace}>: {detail} (DD-248). Use the "
        "domain's own namespace (the default), or `--namespace` one of: "
        + ", ".join(f"<{ns}#>" for ns in sorted(authored))
    )


def _reference_module_for(hub_root: Path, base: str) -> str:
    """*base* when the catalog maps it to a file outside ``model/ontologies``, else ``""``."""
    try:
        from ..core.catalog_utils import CatalogResolver

        catalog = hub_root / "catalog-v001.xml"
        if not catalog.is_file():
            return ""
        mappings = CatalogResolver.with_reference_models(catalog).mappings
    except Exception:  # noqa: BLE001 - the refusal message is advisory detail
        return ""
    for iri, target in mappings.items():
        if iri.rstrip("#/") != base:
            continue
        try:
            Path(target).resolve().relative_to((hub_root / "model" / "ontologies").resolve())
        except ValueError:
            return base
        return ""
    return ""
