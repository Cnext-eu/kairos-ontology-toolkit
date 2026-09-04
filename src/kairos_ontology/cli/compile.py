# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Click surface for the stateless Kairos v5 compiler."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import click

from ..core import ontology_loader
from ..core.compiler import CompileMode, compile_domain
from ..core.compiler.result import CompileDiagnostic
from ..core.conformance_artifact import check_discovery_gate
from ..core.determinism import write_text_lf
from ..core.hub_utils import find_hub_root, publish_root
from ..core.observability import current_operation_id

#: dbt project sub-path under the publish root (``<publish_root>/medallion/dbt``).
_DBT_EMIT_SUBPATH = Path("medallion") / "dbt"
_SHARED_MANIFEST_NAME = ".kairos-compile-manifest.shared.json"
_DEPENDENCY_MANIFEST_NAME = ".kairos-compile-manifest.dependencies.json"
_DEPENDENCY_STATE_SCHEMA = "kairos.eu/compiler-dbt-dependencies/v1"
_DEPENDENCY_STATE_PREFIX = ".kairos-compile-dependencies."
_PACKAGE_ARTIFACTS = frozenset({"README.md", "dbt_project.yml", "packages.yml"})


@dataclass(frozen=True, slots=True)
class _DependencyKind:
    """What one ``PlannedDbtDependency.kind`` is allowed to look like on disk."""

    #: File suffixes (lowercased, with the dot) this kind may use.
    suffixes: frozenset[str]
    #: True when the entry must name a dbt resource whose name equals the path stem.
    requires_model_name: bool
    #: Emitted-project directory prefix this kind must live under.
    prefix: str


#: The single registry of dependency kinds `_load_dependency_states` validates against
#: (#586 stage b). This replaced a hand-expanded boolean ladder plus a separate
#: ``"seeds/" if kind == "seed" else "models/"`` prefix ternary whose else-branch silently
#: claimed every *future* kind lived under ``models/``. A kind absent from this table now
#: fails closed for free, so adding one is a deliberate, reviewable edit here rather than an
#: accident. ``properties`` and ``seed_properties`` carry no ``model_name`` because a
#: properties document is not a dbt resource -- the SQL/CSV beside it owns the name.
_DEPENDENCY_KINDS: dict[str, _DependencyKind] = {
    "sql": _DependencyKind(frozenset({".sql"}), True, "models/"),
    "properties": _DependencyKind(frozenset({".yml", ".yaml"}), False, "models/"),
    "seed": _DependencyKind(frozenset({".csv"}), True, "seeds/"),
    "seed_properties": _DependencyKind(frozenset({".yml", ".yaml"}), False, "seeds/"),
}


def _dependency_entry_is_valid(kind: str, path: str, model_name: str) -> bool:
    """Return True when *path*/*model_name* match the registered rules for *kind*."""
    rules = _DEPENDENCY_KINDS.get(kind)
    if rules is None:
        return False
    if not path.startswith(rules.prefix) or Path(path).suffix.lower() not in rules.suffixes:
        return False
    if rules.requires_model_name:
        return bool(model_name) and Path(path).stem == model_name
    return not model_name


def _domain_integrity_failures(hub: Path, domain: str) -> list:
    """Return this domain's non-degradable integrity errors, or ``[]``.

    Best-effort by design: a hub with no resolvable accelerator, or an ontology
    directory that cannot be read, yields no findings rather than blocking a compile on
    an infrastructure problem. The blueprint-boundary check needs the accelerator and is
    degradable anyway, so it is deliberately not consulted here — only the two
    correctness codes, which need nothing but the hub's own files.
    """
    try:
        from ..core.ontology_integrity import NON_DEGRADABLE_CODES, audit_ontology_integrity

        report = audit_ontology_integrity(
            ontologies_dir=hub / "model" / "ontologies",
            data_domains={},
            domains=[domain],
        )
    except Exception:  # noqa: BLE001 - never fail a compile on the guard itself
        return []
    return [item for item in report.errors if item.code in NON_DEGRADABLE_CODES]


def _payload(result) -> dict:
    return {
        "domain": result.domain,
        "mode": result.mode,
        "succeeded": result.succeeded,
        "provenance_hash": result.provenance_hash,
        "operation_id": current_operation_id(),
        "diagnostics": [asdict(item) for item in result.diagnostics.ordered],
        "explain": asdict(result.explain) if result.explain is not None else None,
        "artifacts": [path for path, _ in result.artifacts],
    }


def _domain_manifest_name(domain: str) -> str:
    safe_domain = re.sub(r"[^A-Za-z0-9_.-]", "_", domain)
    if not safe_domain:
        safe_domain = "domain"
    return f".kairos-compile-manifest.{safe_domain}.json"


def _dependency_state_name(domain: str) -> str:
    safe_domain = re.sub(r"[^A-Za-z0-9_.-]", "_", domain) or "domain"
    return f"{_DEPENDENCY_STATE_PREFIX}{safe_domain}.json"


def _content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _dependency_state_text(domain: str, files: list[dict[str, str]]) -> str:
    document = {
        "domain": domain,
        "files": sorted(files, key=lambda item: item["path"]),
        "schema": _DEPENDENCY_STATE_SCHEMA,
    }
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _is_source_catalog_artifact(path: str) -> bool:
    return path.startswith("models/silver/") and path.endswith("__sources.yml")


def _is_shared_artifact(path: str) -> bool:
    return (
        path in _PACKAGE_ARTIFACTS
        or path.startswith("macros/")
        or _is_source_catalog_artifact(path)
    )


def _existing_domains(target: Path, current_domain: str) -> tuple[str, ...]:
    domains = {current_domain}
    silver = target / "models" / "silver"
    if silver.is_dir():
        domains.update(path.name for path in silver.iterdir() if path.is_dir())
    return tuple(sorted(domains))


def _existing_gold_domains(
    target: Path,
    current_domains: tuple[str, ...],
    planned: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Gold domains to configure in ``dbt_project.yml``: already on disk, plus this run's.

    The disk scan alone accumulates across separate per-domain emits, but it runs
    *before* this run writes its own ``models/gold/**`` -- so a Gold-bearing domain's
    first ``compile --emit`` produced the models and a ``dbt_project.yml`` with no
    ``gold:`` block, and only converged on a second run. *planned* carries the domains
    this run is about to write (issue #665).
    """
    gold = target / "models" / "gold"
    domains = set(planned)
    if gold.is_dir():
        domains.update(
            path.name for path in gold.iterdir() if path.is_dir() and path.name != "shared"
        )
    domains.intersection_update(current_domains)
    return tuple(sorted(domains))


def _reconciled_shared_artifacts(result, target: Path) -> dict[str, str]:
    shared = {
        path: content
        for path, content in result.artifact_dict().items()
        if _is_shared_artifact(path)
    }
    current_source_paths = {path for path in shared if _is_source_catalog_artifact(path)}
    plan = result.plan.materialization_plan if result.plan is not None else None
    if plan is not None and plan.project.emit:
        from ..core.projections.dbt.render import render_project_config
        from ..core.projections.dbt.specs import HUB_DBT_PACKAGE_NAME

        domains = _existing_domains(target, result.domain)
        project = replace(
            plan.project,
            project_name=HUB_DBT_PACKAGE_NAME,
            domains=domains,
            gold_domains=_existing_gold_domains(target, domains, plan.project.gold_domains),
        )
        shared.update(render_project_config(replace(plan, project=project)))

    if target.is_dir():
        for existing in target.rglob("*"):
            if not existing.is_file():
                continue
            relative = existing.relative_to(target).as_posix()
            if _is_shared_artifact(relative) and relative not in shared:
                shared[relative] = existing.read_text(encoding="utf-8")

    for path, content in tuple(shared.items()):
        if path not in current_source_paths:
            continue
        existing = target.joinpath(*path.split("/"))
        if existing.is_file():
            from ..core.compiler.emit import ArtifactCollisionError
            from ..core.projector import SourcesUnionError, _union_sources_yaml

            try:
                shared[path] = _union_sources_yaml(existing.read_text(encoding="utf-8"), content)
            except SourcesUnionError as exc:
                # Preflight ordering guarantees the target tree is untouched on failure.
                raise ArtifactCollisionError(
                    f"conflicting source metadata across domains in {path!r}: {exc}"
                ) from exc
    return shared


def _load_dependency_states(
    target: Path,
) -> tuple[dict[str, list[dict[str, str]]], dict[str, str]]:
    """Load compiler-owned dependency selections and verify their emitted bytes."""
    manifest_path = target / _DEPENDENCY_MANIFEST_NAME
    if not manifest_path.exists() and not manifest_path.is_symlink():
        return {}, {}

    from ..core.compiler.emit import ManifestError, _parse_manifest

    owned = _parse_manifest(target, _DEPENDENCY_MANIFEST_NAME)
    content_by_path: dict[str, str] = {}
    for path, expected_sha in owned.items():
        emitted = target.joinpath(*path.split("/"))
        try:
            content = emitted.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ManifestError(
                f"cannot read manifest-owned dbt dependency artifact {emitted}: {exc}"
            ) from exc
        if _content_sha256(content) != expected_sha:
            raise ManifestError(
                f"manifest-owned dbt dependency artifact has changed bytes: {path!r}"
            )
        content_by_path[path] = content

    state_paths = {
        path
        for path in owned
        if path.startswith(_DEPENDENCY_STATE_PREFIX) and path.endswith(".json")
    }
    states: dict[str, list[dict[str, str]]] = {}
    referenced_paths: set[str] = set()
    for state_path in sorted(state_paths):
        try:
            document = json.loads(content_by_path[state_path])
        except json.JSONDecodeError as exc:
            raise ManifestError(f"malformed dbt dependency state {state_path!r}") from exc
        if (
            not isinstance(document, dict)
            or set(document) != {"domain", "files", "schema"}
            or document.get("schema") != _DEPENDENCY_STATE_SCHEMA
            or not isinstance(document.get("domain"), str)
            or not isinstance(document.get("files"), list)
        ):
            raise ManifestError(f"malformed dbt dependency state {state_path!r}")
        domain = document["domain"]
        if _dependency_state_name(domain) != state_path or domain in states:
            raise ManifestError(f"inconsistent dbt dependency state owner in {state_path!r}")

        entries: list[dict[str, str]] = []
        for item in document["files"]:
            if not isinstance(item, dict) or set(item) != {
                "kind",
                "model_name",
                "path",
                "sha256",
            }:
                raise ManifestError(f"malformed file entry in dbt dependency state {state_path!r}")
            entry = {key: str(value) for key, value in item.items()}
            path = entry["path"]
            digest = entry["sha256"]
            if (
                not _dependency_entry_is_valid(entry["kind"], path, entry["model_name"])
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                or owned.get(path) != digest
            ):
                raise ManifestError(
                    f"unsafe or inconsistent file entry in dbt dependency state {state_path!r}"
                )
            entries.append(entry)
            referenced_paths.add(path)
        states[domain] = entries

    dependency_paths = set(owned) - state_paths
    if referenced_paths != dependency_paths:
        raise ManifestError(
            "dbt dependency manifest and per-domain ownership states do not describe the same files"
        )
    return states, content_by_path


def _existing_generated_model_paths(result, target: Path) -> dict[str, str]:
    """Return manifest-authorized generated model names for collision checks."""
    from ..core.compiler.emit import _parse_manifest

    model_paths = {
        Path(path).stem.casefold(): path
        for path in result.artifact_dict()
        if path.startswith("models/") and path.endswith(".sql")
    }
    if not target.is_dir():
        return model_paths
    excluded = {
        _DEPENDENCY_MANIFEST_NAME,
        _SHARED_MANIFEST_NAME,
        _domain_manifest_name(result.domain),
    }
    for manifest in sorted(target.glob(".kairos-compile-manifest.*.json")):
        if manifest.name in excluded:
            continue
        for path in _parse_manifest(target, manifest.name):
            if not path.startswith("models/") or not path.endswith(".sql"):
                continue
            model_paths.setdefault(Path(path).stem.casefold(), path)
    return model_paths


def _check_cross_domain_model_collisions(result, target: Path) -> None:
    """Reject a generated model name another domain's emit already claims (issue #685).

    Within one domain, ``render._check_duplicate_model_names`` catches this from the rendered
    artifact paths. Across domains it cannot: gold shaping and rendering are per-domain, yet
    every domain emits into the *same* medallion dbt project, and one Gold extension per owning
    domain is the recommended pattern. So a ``party`` Gold table named ``client`` collides with
    the ``client`` domain's Silver model, project-wide and fatally, with each domain's own
    compile looking clean.

    Deliberately not reusing ``_existing_generated_model_paths``: it seeds the mapping with
    *this* run's paths and merges foreign manifests with ``setdefault``, so a cross-domain
    duplicate resolves to the local path and disappears. That precedence is right for its own
    caller, which only asks whether a *contracted* model shadows a generated one.
    """
    from ..core.compiler.emit import ArtifactCollisionError, _parse_manifest

    own_by_stem = {
        Path(path).stem.casefold(): path
        for path in result.artifact_dict()
        if path.startswith("models/") and path.endswith(".sql")
    }
    if not own_by_stem or not target.is_dir():
        return

    # Every manifest except this domain's own and the two non-domain ones: re-emitting a
    # domain must stay idempotent, and shared/dependency artifacts are not domain-owned.
    excluded = {
        _DEPENDENCY_MANIFEST_NAME,
        _SHARED_MANIFEST_NAME,
        _domain_manifest_name(result.domain),
    }
    foreign: dict[str, str] = {}
    for manifest in sorted(target.glob(".kairos-compile-manifest.*.json")):
        if manifest.name in excluded:
            continue
        for path in _parse_manifest(target, manifest.name):
            if path.startswith("models/") and path.endswith(".sql"):
                foreign.setdefault(Path(path).stem.casefold(), path)

    for stem, own_path in sorted(own_by_stem.items()):
        foreign_path = foreign.get(stem)
        if foreign_path is not None and foreign_path != own_path:
            raise ArtifactCollisionError(
                f"generated dbt model name {Path(own_path).stem!r} is emitted at "
                f"{own_path!r} by domain {result.domain!r} and at {foreign_path!r} by another "
                "domain already in this project. dbt resolves ref() in one namespace per "
                "project, so the assembled project cannot be parsed. Rename the Gold table "
                "(goldTableName) -- the scaffold convention is a dim_/fact_/bridge_ prefix."
            )


def _reconciled_dbt_dependencies(result, target: Path) -> dict[str, str] | None:
    """Reconcile plan-selected contracted dbt files across sequential domain emits."""
    from ..core.compiler.emit import ArtifactCollisionError

    plan_dependencies = result.plan.dbt_dependencies if result.plan is not None else ()
    manifest_path = target / _DEPENDENCY_MANIFEST_NAME
    manifest_exists = manifest_path.exists() or manifest_path.is_symlink()
    if not plan_dependencies and not manifest_exists:
        return None

    states, prior_content = _load_dependency_states(target)
    states.pop(result.domain, None)
    current_content: dict[str, str] = {}
    if plan_dependencies:
        current_entries: list[dict[str, str]] = []
        for dependency in plan_dependencies:
            current_entries.append(
                {
                    "kind": dependency.kind,
                    "model_name": dependency.model_name,
                    "path": dependency.path,
                    "sha256": _content_sha256(dependency.content),
                }
            )
            current_content[dependency.path] = dependency.content
        states[result.domain] = current_entries

    artifacts: dict[str, str] = {}
    selected_paths: dict[str, tuple[str, str]] = {}
    selected_models: dict[str, str] = {}
    generated_models = _existing_generated_model_paths(result, target)
    for domain in sorted(states):
        entries = states[domain]
        artifacts[_dependency_state_name(domain)] = _dependency_state_text(domain, entries)
        for entry in sorted(entries, key=lambda item: item["path"]):
            path = entry["path"]
            content = current_content[path] if domain == result.domain else prior_content[path]
            if _content_sha256(content) != entry["sha256"]:
                raise ArtifactCollisionError(
                    f"contracted dbt dependency {path!r} no longer matches domain {domain!r}"
                )
            path_key = path.casefold()
            previous = selected_paths.get(path_key)
            if previous is not None and (previous[0] != path or previous[1] != content):
                raise ArtifactCollisionError(
                    f"contracted dbt dependency path {path!r} has conflicting bytes or casing"
                )
            selected_paths[path_key] = (path, content)

            model_name = entry["model_name"]
            if model_name:
                model_key = model_name.casefold()
                previous_model = selected_models.get(model_key)
                generated_model = generated_models.get(model_key)
                if previous_model is not None and previous_model != path:
                    raise ArtifactCollisionError(
                        f"contracted dbt model name {model_name!r} resolves to both "
                        f"{previous_model!r} and {path!r}"
                    )
                if generated_model is not None:
                    raise ArtifactCollisionError(
                        f"contracted dbt model name {model_name!r} collides with generated "
                        f"model {generated_model!r}"
                    )
                selected_models[model_key] = path
            artifacts[path] = content
    return artifacts


def _preflight_emit(
    artifacts: dict[str, str],
    target: Path,
    *,
    manifest_name: str,
    replace_unowned_paths: tuple[str, ...] = (),
) -> None:
    """Validate every planned write before any unified-project manifest is mutated."""
    from ..core.compiler.emit import (
        ArtifactCollisionError,
        EmissionError,
        _parse_manifest,
        _validate_target_collisions,
        plan_emission,
    )

    if target.exists() and not target.is_dir():
        raise EmissionError(f"emission target must be a directory: {target}")
    plan = plan_emission(artifacts)
    if any(artifact.path == manifest_name for artifact in plan.artifacts):
        raise ArtifactCollisionError(
            f"artifact path {manifest_name!r} is reserved for the compiler manifest"
        )
    previously_owned = _parse_manifest(target, manifest_name) if target.exists() else {}
    _validate_target_collisions(
        target,
        plan.artifacts,
        previously_owned,
        replace_unowned_paths,
    )


def _emit_compile_artifacts(result, emit_dir: Path) -> Path:
    from ..core.compiler.emit import emit_artifacts

    target = emit_dir.resolve(strict=False)
    _check_cross_domain_model_collisions(result, target)
    artifacts = result.artifact_dict()
    domain_artifacts = {
        path: content for path, content in artifacts.items() if not _is_shared_artifact(path)
    }
    shared_artifacts = _reconciled_shared_artifacts(result, target)
    dependency_artifacts = _reconciled_dbt_dependencies(result, target)
    _preflight_emit(
        domain_artifacts,
        target,
        manifest_name=_domain_manifest_name(result.domain),
    )
    _preflight_emit(
        shared_artifacts,
        target,
        manifest_name=_SHARED_MANIFEST_NAME,
        replace_unowned_paths=tuple(shared_artifacts),
    )
    if dependency_artifacts is not None:
        _preflight_emit(
            dependency_artifacts,
            target,
            manifest_name=_DEPENDENCY_MANIFEST_NAME,
        )
    emit_artifacts(
        domain_artifacts,
        target,
        manifest_name=_domain_manifest_name(result.domain),
    )
    emit_artifacts(
        shared_artifacts,
        target,
        manifest_name=_SHARED_MANIFEST_NAME,
        replace_unowned_paths=tuple(shared_artifacts),
    )
    if dependency_artifacts is not None:
        emit_artifacts(
            dependency_artifacts,
            target,
            manifest_name=_DEPENDENCY_MANIFEST_NAME,
        )
    return target


@click.command(name="compile")
@click.argument("domains", nargs=-1)
@click.option(
    "--all",
    "all_domains",
    is_flag=True,
    help="Compile every domain declared by a binding in this hub. Each domain is still "
    "compiled independently and emitted atomically; they only share this process's "
    "read-only parse caches.",
)
@click.option("--check", "check_mode", is_flag=True, help="Validate without writing files.")
@click.option("--explain", "explain_mode", is_flag=True, help="Explain the normalized plan.")
@click.option(
    "--emit",
    "emit_mode",
    is_flag=True,
    help="Atomically emit generated dbt artifacts to the fixed canonical location "
    "<repo>/ontology-hub-publish/medallion/dbt (sibling of the hub). The target is "
    "not configurable. Requires --confirm-emit.",
)
@click.option(
    "--confirm-emit",
    "confirm_emit",
    is_flag=True,
    help="Required alongside --emit. Confirms this is an explicit, execution-phase "
    "invocation (owned by kairos-execute-project) — prevents design-time skills "
    "from accidentally emitting compiled artifacts.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(("text", "json")),
    default="text",
    show_default=True,
)
@click.option(
    "--no-cache",
    "no_cache",
    is_flag=True,
    help="Bypass the ontology-closure parse cache and force a clean reparse. Use after "
    "manually editing a hub's .cache/ontology-parse/ directory, or when debugging a "
    "suspected stale-cache result.",
)
def compile_cmd(
    domains: tuple[str, ...],
    all_domains: bool,
    check_mode: bool,
    explain_mode: bool,
    emit_mode: bool,
    confirm_emit: bool,
    output_format: str,
    no_cache: bool,
) -> None:
    """Check, explain, or emit one or more v5 DOMAINS from the current hub.

    ``--check`` and ``--explain`` may be combined in a single invocation to get both
    the diagnostic stream and the structured explain report together. ``--emit`` is
    the only side-effecting mode and remains mutually exclusive with the other two.

    Accepting several domains at once (#598) is a wall-clock fix, not a semantic one.
    The alignment gates resolve the entire reference-model vocabulary — work that is
    identical for every domain — so a release loop of N separate invocations paid that
    cost N times. One invocation pays it once and still compiles each domain
    independently, emitting each domain's artifacts atomically on its own.
    """
    if emit_mode and (check_mode or explain_mode):
        raise click.UsageError("--emit cannot be combined with --check or --explain")
    if not emit_mode and not check_mode and not explain_mode:
        raise click.UsageError(
            "exactly one of --emit, or at least one of --check/--explain, is required"
        )
    if emit_mode and not confirm_emit:
        raise click.UsageError(
            "--emit requires --confirm-emit. Emitting is an execution-phase action "
            "owned by kairos-execute-project — design skills (kairos-design-mapping, "
            "kairos-design-domain) must never pass --emit. If you are "
            "kairos-execute-project running after a successful check and explicit "
            "output-path confirmation, pass --confirm-emit."
        )
    if all_domains and domains:
        raise click.UsageError(
            "--all already compiles every domain in the hub; do not also name DOMAINS."
        )
    mode = (
        CompileMode.EMIT if emit_mode else CompileMode.CHECK if check_mode else CompileMode.EXPLAIN
    )
    # Reading an already-warm ontology-parse cache is never a write, so it is safe to
    # leave enabled process-wide for every mode; only --no-cache turns it off.
    ontology_loader.CACHE_ENABLED = not no_cache
    hub = find_hub_root(Path.cwd(), require_model=True) or Path.cwd()

    if all_domains:
        selected = _hub_domains(hub)
        if not selected:
            raise click.ClickException(
                "--all found no domains: no integration/bindings/*.binding.yaml in this "
                "hub declares a metadata.domain."
            )
    else:
        # dict.fromkeys, not set: a caller who names the same domain twice gets it
        # compiled once, in the order they asked for.
        selected = list(dict.fromkeys(domains))
        if not selected:
            raise click.UsageError(
                "provide at least one DOMAIN, or --all to compile every domain in the hub."
            )

    payloads: list[dict[str, Any]] = []
    failed: list[str] = []
    # DD-133/140: --emit is the one mode allowed to write into the hub, so it is the
    # one mode that may populate the on-disk caches. The scope has to cover the gates,
    # not just compile_domain: the DD-180/DD-169 gates are what resolve the reference
    # corpus, so the reference-index cache is computed there and would never be
    # persisted if writes only opened later. --check/--explain get scope(False) and
    # remain write-free. Scoped, not assigned, so the flag cannot leak into unrelated
    # later calls sharing this process.
    with ontology_loader.cache_write_scope(not no_cache and mode is CompileMode.EMIT):
        for one in selected:
            succeeded, payload = _compile_one_domain(
                hub,
                one,
                mode,
                check_mode=check_mode,
                explain_mode=explain_mode,
                emit_mode=emit_mode,
                no_cache=no_cache,
                output_format=output_format,
            )
            if payload is not None:
                payloads.append(payload)
            if not succeeded:
                failed.append(one)

    if mode is CompileMode.EMIT:
        _regenerate_master_silver_erd(hub)

    if output_format == "json" and payloads:
        # An explicitly named single domain keeps the exact object shape every existing
        # consumer parses. --all always returns an array: its arity is decided by the
        # hub, not the caller, so a shape that flips between a one-domain and a
        # two-domain hub would break a script on hub shape alone.
        single = len(selected) == 1 and not all_domains
        document: Any = payloads[0] if single else payloads
        click.echo(json.dumps(document, indent=2, sort_keys=True))

    if len(selected) > 1:
        # A failure must not be readable as "the loop finished", and one domain's
        # failure must not silently skip the rest.
        #
        # Under --format json stdout carries the payload and nothing else, so this
        # progress line goes to stderr there: a consumer runs the output through a JSON
        # parser, and a trailing human summary makes the whole document unparseable.
        click.echo(
            f"{'✗' if failed else '✓'} {len(selected) - len(failed)}/{len(selected)} "
            "domain(s) compiled",
            err=bool(failed) or output_format == "json",
        )
        if failed:
            click.echo(f"  failed: {', '.join(failed)}", err=True)
    if failed:
        raise click.exceptions.Exit(1)


def _regenerate_master_silver_erd(hub: Path) -> None:
    """Recompute the hub-wide bound Silver ERD from whatever domains are on disk.

    ``generate_master_erd`` is a pure disk-scan-and-merge over every
    ``docs/diagrams/**/*-erd.mmd`` already emitted under the dbt publish root, so this is
    safe to call after any single-domain ``--emit`` in a multi-domain hub: it reflects
    every domain emitted so far, not just the one(s) this invocation compiled. Ported
    from the legacy ``run_projections`` orchestrator (DD-011), whose dbt/silver targets
    are retired and unreachable; that call site is now commented out.
    """
    from ..core.projections.medallion_silver_projector import generate_master_erd

    dbt_output = publish_root(hub) / _DBT_EMIT_SUBPATH
    master_mmd = generate_master_erd(dbt_output, hub_name=hub.name)
    if master_mmd is None:
        return
    diagrams_dir = dbt_output / "docs" / "diagrams"
    diagrams_dir.mkdir(parents=True, exist_ok=True)
    write_text_lf(diagrams_dir / "master-erd.mmd", master_mmd)


def _hub_domains(hub: Path) -> list[str]:
    """Every domain declared by a binding in this hub, sorted.

    The same discovery the scaffolded release workflow used to inline as a shell
    one-liner over ``metadata.domain``; reuses ``hub_inspection``'s reader rather than
    adding another glob of the bindings directory.
    """
    from ..core.hub_inspection import _binding_domains

    counts, _ = _binding_domains(hub / "integration" / "bindings")
    return sorted(name for name in counts if name)


def _gate_payload(domain: str, mode: CompileMode, diagnostics: list) -> dict[str, Any]:
    """Shape a gate refusal like any other compile result (#598 follow-up).

    A gate returns before there is a ``CompileResult``, so a refused domain used to
    contribute no JSON at all -- under ``--all`` it simply vanished from the array and
    a consumer saw 13 of 14 entries with no machine-readable reason. Same keys as
    :func:`_payload`, so one parser handles both.
    """
    return {
        "domain": domain,
        "mode": mode.value if hasattr(mode, "value") else str(mode),
        "succeeded": False,
        "provenance_hash": "",
        "operation_id": current_operation_id(),
        "diagnostics": [asdict(item) for item in diagnostics],
        "explain": None,
        "artifacts": [],
    }


def _compile_one_domain(
    hub: Path,
    domain: str,
    mode: CompileMode,
    *,
    check_mode: bool,
    explain_mode: bool,
    emit_mode: bool,
    no_cache: bool,
    output_format: str,
) -> tuple[bool, dict[str, Any] | None]:
    """Run every gate, then compile, for exactly one domain.

    Returns ``(succeeded, json payload or None)``. Gate failures report themselves and
    return ``False`` rather than exiting the process, so a multi-domain invocation
    reports every domain instead of stopping at the first one; the caller turns any
    failure into the non-zero exit.
    """
    # Domain-scoped (issue #389/#390): every gate here is scoped to this one domain, so
    # an unresolved DD-148 judgment tagged to a different domain no longer blocks this
    # domain's compile; cross-cutting or matching-domain judgments still do. That scoping
    # is also what makes a multi-domain invocation safe: one domain's gate failure is
    # reported against that domain and leaves the others' verdicts untouched.
    discovery_errors = check_discovery_gate(hub, domains=[domain])
    if discovery_errors:
        for error in discovery_errors:
            click.echo(f"✗ {error}", err=True)
        return False, _gate_payload(
            domain,
            mode,
            [
                CompileDiagnostic(code="discovery.unresolved-judgment", message=str(error))
                for error in discovery_errors
            ],
        )

    # Ontology integrity, at the stage the damage is done (DD-163). Binding authoring is
    # where an agent is under pressure to make `binding.unknown-property` go away, and
    # minting the missing term locally is the fastest way to do it. validate would catch
    # the result, but not until a later stage -- the previous run's cross-domain
    # duplicates reached a dbt build failure before anything objected.
    #
    # Scoped to this domain and to the non-degradable subset only: a compile must not be
    # blocked by another domain's boundary divergence, and these two codes are
    # correctness failures a hub can always fix itself.
    # DD-169: the last point before a binding makes an omission permanent. Compile is
    # what a binding author runs, so gating it here is what "close the gap before entity
    # binding" actually means in practice.
    # DD-180: check the anchor before the columns. An unanchored table is the larger
    # omission — none of its columns can map well, and reporting a hundred homeless
    # columns underneath it describes the symptom while hiding the cause.
    try:
        from ..core.alignment_report import (
            render_unanchored_guidance,
            undecided_unanchored_tables,
        )

        unanchored = undecided_unanchored_tables(hub, domains=[domain])
    except Exception:  # noqa: BLE001 - never fail a compile on the guard itself
        unanchored = []
    if unanchored:
        click.echo(
            f"✗ {len(unanchored)} table(s) in '{domain}' have no reference class and no "
            "recorded decision. Their columns cannot map well until this is resolved:",
            err=True,
        )
        for line in render_unanchored_guidance(unanchored).splitlines()[2:]:
            click.echo(line, err=True)
        click.echo(
            "  Or record a table-level disposition to accept the table as out of scope.",
            err=True,
        )
        return False, _gate_payload(
            domain,
            mode,
            [
                CompileDiagnostic(
                    code="alignment.table-unanchored",
                    message=(
                        f"{table.system}.{table.table} has no reference class and no "
                        f"recorded decision (status: {table.status})"
                    ),
                    rule_id="DD-180",
                )
                for table in unanchored
            ],
        )

    try:
        from ..core.alignment_report import GAP_RESOLUTIONS, undecided_gap_columns

        undecided = undecided_gap_columns(hub, domains=[domain])
    except Exception:  # noqa: BLE001 - never fail a compile on the guard itself
        undecided = []
    if undecided:
        click.echo(
            f"✗ {len(undecided)} source column(s) in '{domain}' carry real business data "
            "with no canonical home and no recorded decision:",
            err=True,
        )
        for column in undecided[:10]:
            click.echo(
                f"    {column.system}.{column.table}.{column.column} "
                f"({column.data_type}) [{column.reason}]",
                err=True,
            )
        if len(undecided) > 10:
            click.echo(f"    … and {len(undecided) - 10} more", err=True)
        click.echo("  Resolve each by one of:", err=True)
        for resolution in GAP_RESOLUTIONS:
            click.echo(f"    - {resolution}", err=True)
        return False, _gate_payload(
            domain,
            mode,
            [
                CompileDiagnostic(
                    code="alignment.gap-column-undecided",
                    message=(
                        f"{column.system}.{column.table}.{column.column} "
                        f"({column.data_type}) carries business data with no canonical "
                        f"home and no recorded decision [{column.reason}]"
                    ),
                    rule_id="DD-169",
                )
                for column in undecided
            ],
        )

    integrity_failures = _domain_integrity_failures(hub, domain)
    if integrity_failures:
        for finding in integrity_failures:
            click.echo(f"✗ {finding.message}", err=True)
            click.echo(f"  ↪ {finding.remediation}", err=True)
        click.echo(
            "✗ ontology integrity must pass before a binding compiles; "
            "run 'kairos-ontology validate --all' for the full picture",
            err=True,
        )
        return False, _gate_payload(
            domain,
            mode,
            [
                CompileDiagnostic(
                    code="ontology.integrity",
                    message=f"{finding.message} -> {finding.remediation}",
                    rule_id="DD-163",
                )
                for finding in integrity_failures
            ],
        )

    # Cache-write permission is opened by the caller, around the whole domain loop, so
    # that it also covers the gates above (see compile_cmd).
    result = compile_domain(hub, domain, mode)
    if check_mode and explain_mode:
        # Both diagnostics and the explain report are already computed as part of the
        # same plan (CompileResult always carries both), so this is a free relabel —
        # not a second compile.
        result = replace(result, mode="check+explain")
    emit_target = None
    if emit_mode and result.can_emit:
        # The emit location is fixed and not configurable: derived dbt artifacts
        # always land in the sibling publish root, never inside the hub.
        requested_target = publish_root(hub) / _DBT_EMIT_SUBPATH
        emit_target = _emit_compile_artifacts(result, requested_target)
    payload = _payload(result) if output_format == "json" else None
    if payload is None:
        for diagnostic in result.diagnostics.ordered:
            click.echo(diagnostic.render(), err=not result.succeeded)
        if result.succeeded:
            if check_mode:
                click.echo(f"✓ {domain}: compile check passed")
            if explain_mode:
                report = result.explain
                click.echo(f"✓ {domain}: {len(report.entities)} entity binding(s)")
                for entity in report.entities:
                    click.echo(
                        f"  {entity.name}: {entity.source} → {entity.target_class} "
                        f"[grain: {', '.join(entity.grain)}]"
                    )
                    for gm in entity.grain_mechanisms:
                        click.echo(
                            f"    grain: {gm.column} via {gm.mechanism}"
                            + (f" → {gm.output}" if gm.output else "")
                        )
                    for rel in entity.relationship_shapes:
                        joins = f" on ({', '.join(rel.join)})" if rel.join else ""
                        temporal = " temporal" if rel.temporal else ""
                        click.echo(
                            f"    rel: {rel.property} → {rel.target} "
                            f"[{rel.cardinality}, {rel.mode}{temporal}]{joins}"
                        )
                    for check in entity.quality:
                        emitted = f" → {check.emitted_test}" if check.emitted_test else ""
                        columns = f"({', '.join(check.columns)})" if check.columns else ""
                        click.echo(f"    dq: {check.kind}{columns}{emitted}")
                    for rule in entity.data_quality:
                        quarantine = f" quarantine={rule.quarantine}" if rule.quarantine else ""
                        click.echo(
                            f"    dq-rule: {rule.rule_id} [{rule.kind}] "
                            f"scope={rule.scope} action={rule.action} "
                            f"severity={rule.severity}{quarantine}"
                        )
                        click.echo(f"      → {rule.result_model}")
                        click.echo(f"      → {rule.result_test}")
                for path in report.artifact_paths:
                    click.echo(f"  {path}")
            if emit_mode:
                click.echo(
                    f"✓ {domain}: emitted {len(result.artifacts)} artifact(s) to {emit_target}"
                )
    return result.succeeded, payload
