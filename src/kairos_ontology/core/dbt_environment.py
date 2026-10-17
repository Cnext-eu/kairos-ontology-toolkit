# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The dbt target is the environment authority (DD-255, #1114).

A dataplatform already names its environments: the outputs of its committed
``profiles.yml``. This module reads one of them and works out everything a Kairos
deploy needs for that environment, so nothing is declared twice:

- the **environment key** is the target name, normalised with
  :func:`~kairos_ontology.core.projections.dbt.gold_connection.normalize_environment_key`;
- the **Gold connection** comes from the target itself. For Databricks that is its
  ``host`` and ``http_path``. For Fabric it is the Warehouse whose SQL endpoint and name
  are the target's ``server`` and ``database``, found through the Fabric REST API;
- the **models and reports workspaces**, which dbt does not know, come from the
  namespaced package vars ``vars.kairos.environments.<env>`` in ``dbt_project.yml``, and
  default to the Gold workspace.

Explicit GitHub Environment variables still win, so an existing deploy keeps working:
``FABRIC_ITEM_ID`` (+ ``FABRIC_GOLD_WORKSPACE_ID``, falling back to
``FABRIC_WORKSPACE_ID``), ``FABRIC_WORKSPACE_ID`` for the models workspace and
``FABRIC_REPORTS_WORKSPACE_ID``. Every resolved value records where it came from.

``profiles.yml`` values are rendered with ``env_var()`` only -- the one Jinja function a
profile needs -- and only the fields resolution reads, so a target whose token comes from
an unset secret still resolves its endpoint. ``vars.kairos`` is read as YAML and never
compiled by Kairos; dbt treats it as a global var named ``kairos``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import yaml
from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from .fabric_api import FabricApiError, FabricClient, FabricWarehouse
from .projections.dbt.gold_connection import (
    GoldConnectionEnvironmentSpec,
    GoldDirectLakeEnvironmentSpec,
    normalize_environment_key,
)

#: dbt adapter ``type`` values a Kairos Gold deploy can resolve.
SUPPORTED_TARGET_TYPES = ("fabric", "databricks")

#: The keys ``vars.kairos.environments.<env>`` may carry.
KAIROS_VAR_FIELDS = ("models_workspace", "reports_workspace", "gold_workspace")

_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class EnvironmentResolutionError(Exception):
    """The dbt target, its vars, or the Fabric lookup cannot resolve the environment."""


# --------------------------------------------------------------------------------------
# profiles.yml
# --------------------------------------------------------------------------------------


def find_profiles_dir(
    project_dir: Path,
    profiles_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Return the directory dbt would read ``profiles.yml`` from.

    dbt's own order: ``--profiles-dir``, then ``DBT_PROFILES_DIR``, then the project
    directory, then ``~/.dbt``.
    """
    environ = os.environ if environ is None else environ
    if profiles_dir is not None:
        return Path(profiles_dir)
    if environ.get("DBT_PROFILES_DIR"):
        return Path(environ["DBT_PROFILES_DIR"])
    if (Path(project_dir) / "profiles.yml").is_file():
        return Path(project_dir)
    return Path.home() / ".dbt"


def _read_yaml(path: Path, what: str) -> object:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EnvironmentResolutionError(f"No {what} at {path}") from exc
    except (OSError, yaml.YAMLError) as exc:
        raise EnvironmentResolutionError(f"{path} could not be read: {exc}") from exc


def project_profile_name(project_dir: Path) -> str:
    """Return ``profile:`` from the project's ``dbt_project.yml``."""
    document = _read_yaml(Path(project_dir) / "dbt_project.yml", "dbt_project.yml")
    profile = document.get("profile") if isinstance(document, dict) else None
    if not isinstance(profile, str) or not profile.strip():
        raise EnvironmentResolutionError(
            f"{Path(project_dir) / 'dbt_project.yml'} names no `profile:`"
        )
    return profile.strip()


@dataclass(frozen=True)
class DbtTarget:
    """One output of a dbt profile. Fields are rendered on read (:meth:`get`)."""

    name: str
    profile: str
    path: Path
    raw: Mapping[str, object]
    environ: Mapping[str, str] = field(repr=False, default_factory=dict)

    @property
    def key(self) -> str:
        """The environment key this target names."""
        return normalize_environment_key(self.name)

    @property
    def type(self) -> str:
        return str(self.raw.get("type", "")).strip()

    def get(self, name: str, *, required: bool = True) -> str | None:
        """Render one field, ``env_var()`` resolved; reject an unfilled placeholder."""
        value = self.raw.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            if required:
                raise EnvironmentResolutionError(
                    f"{self.path}: target {self.name!r} has no {name!r}"
                )
            return None
        rendered = _render(str(value), self.environ, where=f"target {self.name!r} {name!r}")
        if "{" in rendered or "}" in rendered:
            raise EnvironmentResolutionError(
                f"{self.path}: target {self.name!r} {name!r} is still the scaffold "
                f"placeholder {rendered!r}; fill in the real value"
            )
        return rendered


def _render(value: str, environ: Mapping[str, str], *, where: str) -> str:
    if "{{" not in value and "{%" not in value:
        return value.strip()

    def env_var(name: str, default: str | None = None) -> str:
        if name in environ:
            return environ[name]
        if default is not None:
            return str(default)
        raise EnvironmentResolutionError(
            f"profiles.yml {where} reads env_var({name!r}), which is not set"
        )

    sandbox = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)
    try:
        return sandbox.from_string(value).render(env_var=env_var).strip()
    except EnvironmentResolutionError:
        raise
    except TemplateError as exc:
        raise EnvironmentResolutionError(
            f"profiles.yml {where} uses Jinja beyond env_var(): {exc}"
        ) from exc


def load_dbt_target(
    project_dir: Path,
    target: str,
    *,
    profiles_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> DbtTarget:
    """Load *target* of the project's profile; its name matches case-insensitively."""
    environ = os.environ if environ is None else environ
    profile = project_profile_name(project_dir)
    directory = find_profiles_dir(project_dir, profiles_dir, environ)
    path = directory / "profiles.yml"
    document = _read_yaml(path, "profiles.yml")
    block = document.get(profile) if isinstance(document, dict) else None
    if not isinstance(block, dict):
        raise EnvironmentResolutionError(f"{path} has no profile {profile!r}")
    outputs = block.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        raise EnvironmentResolutionError(f"{path}: profile {profile!r} has no outputs")
    wanted = normalize_environment_key(target)
    matches = [name for name in outputs if normalize_environment_key(str(name)) == wanted]
    if not matches:
        raise EnvironmentResolutionError(
            f"{path}: profile {profile!r} has no target {target!r} "
            f"(targets: {sorted(map(str, outputs))}). Add it to profiles.yml first."
        )
    if len(matches) > 1:
        raise EnvironmentResolutionError(
            f"{path}: targets {sorted(map(str, matches))} are the same environment "
            f"({wanted!r}); keep one"
        )
    raw = outputs[matches[0]]
    if not isinstance(raw, dict):
        raise EnvironmentResolutionError(f"{path}: target {matches[0]!r} must be a mapping")
    return DbtTarget(name=str(matches[0]), profile=profile, path=path, raw=raw, environ=environ)


# --------------------------------------------------------------------------------------
# vars.kairos
# --------------------------------------------------------------------------------------


def load_kairos_vars(project_dir: Path) -> dict[str, dict[str, str]]:
    """Read ``vars.kairos.environments`` from ``dbt_project.yml``, keyed by environment."""
    path = Path(project_dir) / "dbt_project.yml"
    document = _read_yaml(path, "dbt_project.yml")
    variables = document.get("vars") if isinstance(document, dict) else None
    kairos = variables.get("kairos") if isinstance(variables, dict) else None
    if kairos is None:
        return {}
    where = f"{path}: vars.kairos"
    if not isinstance(kairos, dict):
        raise EnvironmentResolutionError(f"{where} must be a mapping")
    unknown = sorted(set(map(str, kairos)) - {"environments"})
    if unknown:
        raise EnvironmentResolutionError(f"{where} has unknown key(s) {unknown}")
    environments = kairos.get("environments")
    if environments is None:
        return {}
    if not isinstance(environments, dict):
        raise EnvironmentResolutionError(
            f"{where}.environments must be a mapping keyed by environment (dbt target) name"
        )
    resolved: dict[str, dict[str, str]] = {}
    for name, raw in environments.items():
        key = normalize_environment_key(str(name))
        if key in resolved:
            raise EnvironmentResolutionError(
                f"{where}.environments declares {key!r} twice under different casing"
            )
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise EnvironmentResolutionError(f"{where}.environments.{name} must be a mapping")
        unknown = sorted(set(map(str, raw)) - set(KAIROS_VAR_FIELDS))
        if unknown:
            raise EnvironmentResolutionError(
                f"{where}.environments.{name} has unknown key(s) {unknown} "
                f"(allowed: {list(KAIROS_VAR_FIELDS)})"
            )
        values: dict[str, str] = {}
        for item, value in raw.items():
            if not isinstance(value, str) or not value.strip():
                raise EnvironmentResolutionError(
                    f"{where}.environments.{name}.{item} must be a workspace name or GUID"
                )
            values[str(item)] = value.strip()
        resolved[key] = values
    return resolved


# --------------------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedEnvironment:
    """Everything a deploy needs for one environment, and where each value came from."""

    environment: str
    target: str
    target_type: str
    gold_workspace_id: str | None = None
    gold_item_id: str | None = None
    server_hostname: str | None = None
    http_path: str | None = None
    models_workspace_id: str | None = None
    reports_workspace_id: str | None = None
    sources: Mapping[str, str] = field(default_factory=dict)

    def connection_override(self) -> GoldDirectLakeEnvironmentSpec | GoldConnectionEnvironmentSpec:
        """The Gold connection as the override ``apply-gold-connection`` applies."""
        if self.target_type == "databricks":
            assert self.server_hostname and self.http_path
            return GoldConnectionEnvironmentSpec(
                name=self.environment,
                server_hostname=self.server_hostname,
                http_path=self.http_path,
            )
        if not (self.gold_workspace_id and self.gold_item_id):
            raise EnvironmentResolutionError(
                f"environment {self.environment!r}: the Gold Warehouse was not resolved "
                "(resolved offline?)"
            )
        return GoldDirectLakeEnvironmentSpec(
            name=self.environment,
            workspace_id=self.gold_workspace_id,
            item_id=self.gold_item_id,
        )

    def as_dict(self) -> dict[str, object]:
        values = {
            "environment": self.environment,
            "target": self.target,
            "target_type": self.target_type,
            "gold_workspace_id": self.gold_workspace_id,
            "gold_item_id": self.gold_item_id,
            "server_hostname": self.server_hostname,
            "http_path": self.http_path,
            "models_workspace_id": self.models_workspace_id,
            "reports_workspace_id": self.reports_workspace_id,
        }
        return {**values, "sources": dict(self.sources)}


def _endpoint_host(value: str) -> str:
    """The bare host of a SQL endpoint, however the target or Fabric spells it."""
    host = value.strip().lower()
    host = re.sub(r"^[a-z]+://", "", host)
    host = host.removeprefix("tcp:")
    host = re.split(r"[,/:;]", host, maxsplit=1)[0]
    return host


class _Workspaces:
    """Lazily list workspaces once, and resolve a name or GUID against them."""

    def __init__(self, client: FabricClient) -> None:
        self._client = client
        self._all = None

    def all(self):
        if self._all is None:
            try:
                self._all = self._client.workspaces()
            except FabricApiError as exc:
                raise EnvironmentResolutionError(str(exc)) from exc
        return self._all

    def resolve(self, value: str, *, what: str) -> str:
        if _GUID.match(value):
            return value
        matches = [ws for ws in self.all() if ws.display_name == value]
        if not matches:
            matches = [ws for ws in self.all() if ws.display_name.casefold() == value.casefold()]
        if len(matches) != 1:
            visible = sorted(ws.display_name for ws in self.all())
            found = "no" if not matches else f"{len(matches)}"
            raise EnvironmentResolutionError(
                f"{what} {value!r}: {found} visible workspace has that name "
                f"(visible: {visible}). Use the workspace GUID, or grant the deploy "
                "identity access."
            )
        return matches[0].id


def _find_gold_warehouse(
    target: DbtTarget,
    workspaces: _Workspaces,
    client: FabricClient,
    hint: str | None,
) -> FabricWarehouse:
    server = target.get("server")
    database = target.get("database")
    host = _endpoint_host(server)
    if hint:
        scope = [workspaces.resolve(hint, what="vars.kairos gold_workspace")]
    else:
        scope = [ws.id for ws in workspaces.all()]
    at_host: list[FabricWarehouse] = []
    for workspace_id in scope:
        try:
            warehouses = client.warehouses(workspace_id)
        except FabricApiError as exc:
            if hint:
                raise EnvironmentResolutionError(str(exc)) from exc
            continue  # a workspace the identity can list but not read is not the one
        at_host.extend(
            item for item in warehouses if _endpoint_host(item.connection_string) == host
        )
    named = [item for item in at_host if item.display_name == database]
    if not named:
        named = [item for item in at_host if item.display_name.casefold() == database.casefold()]
    if len(named) == 1:
        return named[0]
    if not named:
        seen = sorted(item.display_name for item in at_host)
        detail = (
            f"Warehouses at that endpoint: {seen}" if seen
            else f"no Warehouse at that endpoint in the {len(scope)} workspace(s) searched"
        )
        raise EnvironmentResolutionError(
            f"target {target.name!r}: no Warehouse named {database!r} at {host!r}; {detail}. "
            "Check the target's server/database, or the deploy identity's workspace access."
        )
    raise EnvironmentResolutionError(
        f"target {target.name!r}: {len(named)} Warehouses named {database!r} at {host!r} "
        f"(workspaces {sorted(item.workspace_id for item in named)}); set "
        "vars.kairos.environments.<env>.gold_workspace to choose one"
    )


def resolve_environment(
    project_dir: Path,
    target: str,
    *,
    profiles_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
    client: FabricClient | None = None,
    offline: bool = False,
) -> ResolvedEnvironment:
    """Resolve one environment from its dbt target, ``vars.kairos`` and Fabric.

    *offline* checks the target and vars without calling Fabric; values that need the
    API are then left ``None`` with the reason in ``sources``.
    """
    environ = os.environ if environ is None else environ
    dbt_target = load_dbt_target(project_dir, target, profiles_dir=profiles_dir, environ=environ)
    if dbt_target.type not in SUPPORTED_TARGET_TYPES:
        raise EnvironmentResolutionError(
            f"{dbt_target.path}: target {dbt_target.name!r} has type {dbt_target.type!r}; "
            f"Kairos resolves {list(SUPPORTED_TARGET_TYPES)}"
        )
    variables = load_kairos_vars(project_dir).get(dbt_target.key, {})
    client = client or FabricClient()
    workspaces = _Workspaces(client)
    sources: dict[str, str] = {"environment": f"dbt target {dbt_target.name!r}"}
    deferred = "fabric-api (skipped: offline)"

    def explicit(name: str) -> str | None:
        value = (environ.get(name) or "").strip()
        return value or None

    def workspace(env_name: str, var_name: str, fallback: tuple[str | None, str]):
        if explicit(env_name):
            return explicit(env_name), f"env {env_name}"
        if var_name in variables:
            value = variables[var_name]
            if _GUID.match(value):
                return value, f"vars.kairos {var_name}"
            if offline:
                return None, f"vars.kairos {var_name} {value!r} ({deferred})"
            resolved = workspaces.resolve(value, what=f"vars.kairos {var_name}")
            return resolved, f"vars.kairos {var_name} {value!r} via fabric-api"
        return fallback

    gold_workspace_id = gold_item_id = server_hostname = http_path = None
    if dbt_target.type == "databricks":
        server_hostname = _endpoint_host(dbt_target.get("host"))
        http_path = dbt_target.get("http_path")
        sources["server_hostname"] = sources["http_path"] = "dbt target"
        gold_source: tuple[str | None, str] = (None, "unset")
    else:
        dbt_target.get("server")
        dbt_target.get("database")  # fail early, offline too, on a missing or placeholder value
        if explicit("FABRIC_ITEM_ID"):
            gold_item_id = explicit("FABRIC_ITEM_ID")
            sources["gold_item_id"] = "env FABRIC_ITEM_ID"
            for name in ("FABRIC_GOLD_WORKSPACE_ID", "FABRIC_WORKSPACE_ID"):
                if explicit(name):
                    gold_workspace_id = explicit(name)
                    sources["gold_workspace_id"] = f"env {name}"
                    break
            else:
                raise EnvironmentResolutionError(
                    "FABRIC_ITEM_ID is set without FABRIC_GOLD_WORKSPACE_ID or "
                    "FABRIC_WORKSPACE_ID; set the workspace too, or unset FABRIC_ITEM_ID to "
                    "derive both from the dbt target"
                )
        elif offline:
            sources["gold_workspace_id"] = sources["gold_item_id"] = deferred
        else:
            warehouse = _find_gold_warehouse(
                dbt_target, workspaces, client, variables.get("gold_workspace")
            )
            gold_workspace_id, gold_item_id = warehouse.workspace_id, warehouse.id
            sources["gold_workspace_id"] = sources["gold_item_id"] = (
                f"fabric-api: Warehouse {warehouse.display_name!r} at the target's server"
            )
        gold_source = (gold_workspace_id, sources["gold_workspace_id"] + " (Gold workspace)")

    models_workspace_id, sources["models_workspace_id"] = workspace(
        "FABRIC_WORKSPACE_ID", "models_workspace", gold_source
    )
    reports_workspace_id, sources["reports_workspace_id"] = workspace(
        "FABRIC_REPORTS_WORKSPACE_ID",
        "reports_workspace",
        (models_workspace_id, sources["models_workspace_id"] + " (models workspace)"),
    )
    return ResolvedEnvironment(
        environment=dbt_target.key,
        target=dbt_target.name,
        target_type=dbt_target.type,
        gold_workspace_id=gold_workspace_id,
        gold_item_id=gold_item_id,
        server_hostname=server_hostname,
        http_path=http_path,
        models_workspace_id=models_workspace_id,
        reports_workspace_id=reports_workspace_id,
        sources=sources,
    )
