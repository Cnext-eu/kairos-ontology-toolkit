# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``export-reference-list``: a shipped reference list's members as a hub seed (DD-257)."""

from __future__ import annotations

from pathlib import Path

import click


def _resolve_token(token: str, hub: Path, domain: str | None) -> str:
    """An absolute IRI as given, or a ``prefix:Local`` qname through the hub's prefixes."""
    from ..core.class_disposition import load_domain_files, resolve_class_token

    resolved = resolve_class_token(token, load_domain_files(hub), domain or "")
    if resolved is None:
        raise click.UsageError(
            f"{token!r} is neither an absolute IRI nor a prefix:Local name a hub ontology declares."
        )
    return resolved


def _changes(diff) -> str:
    parts = []
    for label, keys in (
        ("added", diff.added),
        ("removed", diff.removed),
        ("changed", diff.changed),
    ):
        if keys:
            shown = ", ".join(f"{code_list}:{code}" for code_list, code in keys[:5])
            more = f" (+{len(keys) - 5} more)" if len(keys) > 5 else ""
            parts.append(f"{len(keys)} {label}: {shown}{more}")
    return "; ".join(parts)


def _seeds_dir(hub: Path) -> Path:
    return hub / "integration" / "transforms" / "dbt" / "seeds"


def _rel(path: Path, hub: Path) -> str:
    return path.relative_to(hub).as_posix()


def _ontology_path(hub: Path, domain: str | None, ontology: str | None) -> Path:
    if ontology:
        path = Path(ontology)
        return path if path.is_absolute() else hub / path
    if domain:
        path = hub / "model" / "ontologies" / f"{domain}.ttl"
        if not path.is_file():
            raise click.ClickException(f"No ontology for domain {domain!r}: {path}")
        return path
    raise click.UsageError("Provide --domain or --ontology.")


def _origin(hub: Path, class_uri: str, domain: str | None, path: Path) -> dict[str, str]:
    """What the header records, so ``--all`` can find the closure again."""
    if domain:
        return {"class": class_uri, "domain": domain}
    try:
        where = path.resolve().relative_to(hub.resolve()).as_posix()
    except ValueError:
        where = path.resolve().as_posix()
    return {"class": class_uri, "ontology": where}


def _export_one(
    *,
    hub: Path,
    class_uri: str,
    path: Path,
    catalog: str | None,
    name: str,
    adapter: str | None,
    origin: dict[str, str],
    check: bool,
    force: bool,
    loaded_cache: dict[Path, object],
) -> bool:
    """Write (or with *check*, compare) one seed. Returns ``False`` when *check* finds drift."""
    from ..core.hub_config import configured_adapter
    from ..core.ontology_loader import OntologyLoadError, load_ontology
    from ..core.projections.dbt.capabilities import physical_canonical_type
    from ..core.projections.dbt.policy_specs import CanonicalTypeKind, CanonicalTypeSpec
    from ..core.reference_lists import (
        ReferenceListError,
        collect_reference_list,
        column_lengths,
        diff_seed,
        is_generated,
        render_seed_csv,
        render_seed_docs,
    )

    if path not in loaded_cache:
        try:
            loaded_cache[path] = load_ontology(
                path, catalog_path=Path(catalog) if catalog else None
            )
        except OntologyLoadError as exc:
            raise click.ClickException(str(exc)) from exc
    try:
        reference = collect_reference_list(loaded_cache[path].graph, class_uri)
    except ReferenceListError as exc:
        raise click.ClickException(f"{name}: {exc}") from exc

    adapter_name = adapter or configured_adapter(hub)
    column_types = None
    if adapter_name:
        try:
            column_types = {
                column: physical_canonical_type(
                    adapter_name, CanonicalTypeSpec(kind=CanonicalTypeKind.STRING, length=length)
                )
                for column, length in column_lengths(reference).items()
            }
        except (KeyError, ValueError) as exc:
            raise click.ClickException(
                f"Cannot type the seed for adapter {adapter_name!r}: {exc}"
            ) from exc
    seeds_dir = _seeds_dir(hub)
    csv_path = seeds_dir / f"{name}.csv"
    docs_path = seeds_dir / f"{name}.yml"
    csv_text = render_seed_csv(reference)
    docs_text = render_seed_docs(reference, name, column_types, origin)

    if check:
        if not csv_path.is_file():
            click.echo(f"❌ {_rel(csv_path, hub)} does not exist; run without --check.")
            return False
        current = csv_path.read_text(encoding="utf-8")
        current_docs = docs_path.read_text(encoding="utf-8") if docs_path.is_file() else ""
        if current == csv_text and current_docs == docs_text:
            click.echo(
                f"✅ {_rel(csv_path, hub)} matches the closure ({len(reference.members)} rows)."
            )
            return True
        changes = _changes(diff_seed(current, reference)) or "metadata or column types differ"
        click.echo(f"❌ {_rel(csv_path, hub)} is stale: {changes}.")
        return False

    if not force:
        if docs_path.is_file() and not is_generated(docs_path.read_text(encoding="utf-8")):
            raise click.ClickException(
                f"{_rel(docs_path, hub)} was not generated by this command; pass --force to "
                "replace it, or --name to write a separate seed."
            )
        if csv_path.is_file() and not docs_path.is_file():
            raise click.ClickException(
                f"{_rel(csv_path, hub)} exists without generated docs; pass --force to "
                "replace it, or --name to write a separate seed."
            )
    seeds_dir.mkdir(parents=True, exist_ok=True)
    csv_path.write_bytes(csv_text.encode("utf-8"))
    docs_path.write_bytes(docs_text.encode("utf-8"))
    click.echo(
        f"✅ Wrote {_rel(csv_path, hub)} ({len(reference.members)} rows; columns "
        f"{', '.join(reference.columns)}) and its docs."
    )
    for item in reference.lists:
        click.echo(f"   {item.name}: snapshot {item.version or 'unversioned'}")
    deprecated = sum(item.deprecated for item in reference.members)
    if deprecated:
        click.echo(
            f"   {deprecated} deprecated (withdrawn) code(s) kept as rows with deprecated=true."
        )
    if reference.skipped:
        click.echo(
            f"   ⚠️ Skipped {len(reference.skipped)} member(s) with no code, "
            f"e.g. {reference.skipped[0]}"
        )
    if not column_types:
        click.echo(
            "   ⚠️ No adapter configured, so the seed has no column types and dbt will infer "
            "numbers from numeric codes. Pass --adapter."
        )
    return True


def _generated_seeds(hub: Path) -> list[tuple[Path, dict[str, str]]]:
    """Every generated seed-docs document under the seeds directory, with its origin."""
    from ..core.reference_lists import is_generated, read_origin

    seeds_dir = _seeds_dir(hub)
    if not seeds_dir.is_dir():
        return []
    found = []
    for path in sorted(seeds_dir.rglob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if is_generated(text):
            found.append((path, read_origin(text)))
    return found


@click.command(name="export-reference-list")
@click.argument("class_iri", required=False)
@click.option("--domain", default=None, help="Hub domain whose closure holds the list.")
@click.option("--ontology", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--catalog", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option(
    "--name",
    "seed_name",
    default=None,
    help="Seed name (default: the class's local name in snake_case).",
)
@click.option(
    "--adapter",
    default=None,
    help="dbt adapter whose text type the seed's columns get (default: the hub's adapter).",
)
@click.option(
    "--all",
    "all_seeds",
    is_flag=True,
    help="Every seed this command generated, each from the class and domain its docs record.",
)
@click.option(
    "--check",
    is_flag=True,
    help="Write nothing; exit 1 when a seed on disk differs from the closure's members.",
)
@click.option(
    "--force", is_flag=True, help="Overwrite a seed that was not generated by this command."
)
def export_reference_list_cmd(
    class_iri, domain, ontology, catalog, seed_name, adapter, all_seeds, check, force
):
    """Write a shipped reference list's members as a dbt seed under integration/transforms/dbt/seeds/.

    CLASS_IRI is the list class (unece:TransportModeCodeList) or your governed class that
    lists subclass (ref:TransportModeCode). One row per member, keyed on (code_list, code),
    with the upstream IRI as a column. Each row also carries its list's snapshot version and
    source, whether the code is deprecated, and one column per datatype property the
    members carry (DD-258). The generated seed docs record the class and domain, describe
    every column, and type every column as text so codes such as 02 keep their leading zero.

    Only lists the reference models ship with members (kind 1, DD-257) can be exported.
    Local extension rows go in a separate <name>_local seed, which this command never
    touches.

    After a reference-models upgrade, `--all` regenerates every generated seed, and
    `--check --all` (which pr-validate runs) fails when one is stale.
    """
    from ..core.hub_utils import find_hub_root
    from ..core.reference_lists import default_seed_name

    hub = find_hub_root(Path.cwd(), require_model=True)
    if hub is None:
        raise click.ClickException("Cannot locate a hub: run this inside an ontology hub.")
    loaded_cache: dict[Path, object] = {}

    if all_seeds:
        if class_iri or domain or ontology or seed_name or force:
            raise click.UsageError(
                "--all takes each seed's class and domain from its docs; drop CLASS_IRI, "
                "--domain, --ontology, --name and --force."
            )
        seeds = _generated_seeds(hub)
        if not seeds:
            click.echo("No generated reference seeds in this hub; nothing to do.")
            return
        ok = True
        for docs_path, origin in seeds:
            if "class" not in origin or not ({"domain", "ontology"} & origin.keys()):
                click.echo(
                    f"❌ {_rel(docs_path, hub)} records no class and domain; regenerate it once "
                    "with `export-reference-list <class> --domain <domain>`."
                )
                ok = False
                continue
            ok &= _export_one(
                hub=hub,
                class_uri=origin["class"],
                path=_ontology_path(hub, origin.get("domain"), origin.get("ontology")),
                catalog=catalog,
                name=docs_path.stem,
                adapter=adapter,
                origin=origin,
                check=check,
                force=True,
                loaded_cache=loaded_cache,
            )
        if not ok:
            if check:
                click.echo(
                    "Run `kairos-ontology export-reference-list --all` and commit the result."
                )
            raise SystemExit(1)
        return

    if not class_iri:
        raise click.UsageError("Provide CLASS_IRI, or --all.")
    path = _ontology_path(hub, domain, ontology)
    class_uri = _resolve_token(class_iri, hub, domain)
    ok = _export_one(
        hub=hub,
        class_uri=class_uri,
        path=path,
        catalog=catalog,
        name=seed_name or default_seed_name(class_uri),
        adapter=adapter,
        origin=_origin(hub, class_uri, domain, path),
        check=check,
        force=force,
        loaded_cache=loaded_cache,
    )
    if not ok:
        click.echo("Re-run without --check.")
        raise SystemExit(1)
