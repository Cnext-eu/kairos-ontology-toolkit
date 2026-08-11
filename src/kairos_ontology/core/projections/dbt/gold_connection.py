# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Per-environment Databricks connection configuration for Gold semantic models.

A ``directQuery`` Power BI semantic model over Databricks SQL is the only Gold
artifact that needs external connection details. A Direct Lake partition resolves
its binding from the Fabric workspace it is deployed into, so it needs none; a
Power Query partition must name a concrete server hostname and HTTP path, and an
unresolved placeholder there produces a semantic model that cannot connect to
anything (issue #283).

The values are authored per environment in ``kairos.yaml`` because one released
semantic model is promoted across environments:

.. code-block:: yaml

    gold:
      databricks_connection:
        default_environment: DEV
        environments:
          DEV:
            server_hostname: adb-1111111111111111.11.azuredatabricks.net
            http_path: /sql/1.0/warehouses/dev0000000000000
          PROD:
            server_hostname: adb-2222222222222222.22.azuredatabricks.net
            http_path: /sql/1.0/warehouses/prod000000000000

The projector emits the default environment's values into the TMDL partition and a
fabric-cicd ``parameter.yml`` that rewrites them for the target environment at
deploy time (see ``gold_render._parameter_yaml``). Authoring is fail-closed: an
absent block blocks Databricks Gold projection outright, and a malformed block is
never partially applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .gold_specs import GoldContractError

#: Governance rule for the Databricks semantic-model connection (DD-113).
GOLD_CONNECTION_RULE_ID = "DD-113-connection"

#: ``kairos.yaml`` keys owning the Gold semantic-model connection.
_GOLD_KEY = "gold"
_CONNECTION_KEY = "databricks_connection"
_ENVIRONMENTS_KEY = "environments"
_DEFAULT_ENVIRONMENT_KEY = "default_environment"
_ENVIRONMENT_FIELDS = ("server_hostname", "http_path")

#: Characters that would either break the TMDL string literal the value is
#: embedded in or re-introduce an unsubstituted templating placeholder.
_REJECTED_CHARACTERS = ('"', "\\", "{", "}", "\r", "\n", "\t")

_CONFIG_PATH = f"{_GOLD_KEY}.{_CONNECTION_KEY}"


@dataclass(frozen=True, slots=True)
class GoldConnectionEnvironmentSpec:
    """One environment's Databricks SQL warehouse coordinates."""

    name: str
    server_hostname: str
    http_path: str


@dataclass(frozen=True, slots=True)
class GoldDatabricksConnectionSpec:
    """Every environment a released Gold semantic model may be promoted into."""

    default_environment: str
    environments: tuple[GoldConnectionEnvironmentSpec, ...]

    @property
    def default(self) -> GoldConnectionEnvironmentSpec:
        """Return the environment whose values are emitted into the artifact."""
        return next(item for item in self.environments if item.name == self.default_environment)


def _invalid(detail: str) -> GoldContractError:
    return GoldContractError(
        "gold.databricks-connection-invalid",
        f"kairos.yaml {_CONFIG_PATH} is malformed: {detail}",
        rule_id=GOLD_CONNECTION_RULE_ID,
    )


def _value(environment: str, field: str, raw: object) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise _invalid(f"environment {environment!r} needs a non-empty string {field!r}")
    value = raw.strip()
    rejected = sorted({item for item in _REJECTED_CHARACTERS if item in value})
    if rejected:
        raise _invalid(
            f"environment {environment!r} {field!r} contains unusable character(s) "
            f"{rejected}; author the resolved value, not a template placeholder"
        )
    return value


def _environment(name: object, raw: object) -> GoldConnectionEnvironmentSpec:
    if not isinstance(name, str) or not name.strip():
        raise _invalid(f"environment key {name!r} is not a non-empty string")
    environment = name.strip()
    if not isinstance(raw, dict):
        raise _invalid(f"environment {environment!r} must be a mapping")
    unknown = sorted(set(map(str, raw)) - set(_ENVIRONMENT_FIELDS))
    if unknown:
        raise _invalid(f"environment {environment!r} has unknown key(s) {unknown}")
    return GoldConnectionEnvironmentSpec(
        name=environment,
        server_hostname=_value(environment, "server_hostname", raw.get("server_hostname")),
        http_path=_value(environment, "http_path", raw.get("http_path")),
    )


def _default_environment(
    raw: object,
    environments: tuple[GoldConnectionEnvironmentSpec, ...],
) -> str:
    names = [item.name for item in environments]
    if raw is None:
        if len(environments) > 1:
            raise _invalid(
                f"{_DEFAULT_ENVIRONMENT_KEY!r} is required when more than one environment "
                f"is declared (declared: {names})"
            )
        return names[0]
    if not isinstance(raw, str) or raw.strip() not in names:
        raise _invalid(
            f"{_DEFAULT_ENVIRONMENT_KEY!r} {raw!r} is not one of the declared environments {names}"
        )
    return raw.strip()


def parse_gold_databricks_connection(config: object) -> GoldDatabricksConnectionSpec | None:
    """Read the connection block out of already-loaded ``kairos.yaml`` content."""
    if not isinstance(config, dict):
        return None
    gold = config.get(_GOLD_KEY)
    if gold is None:
        return None
    if not isinstance(gold, dict):
        raise _invalid(f"{_GOLD_KEY!r} must be a mapping")
    block = gold.get(_CONNECTION_KEY)
    if block is None:
        return None
    if not isinstance(block, dict):
        raise _invalid("the connection block must be a mapping")
    unknown = sorted(set(map(str, block)) - {_ENVIRONMENTS_KEY, _DEFAULT_ENVIRONMENT_KEY})
    if unknown:
        raise _invalid(f"unknown key(s) {unknown}")
    declared = block.get(_ENVIRONMENTS_KEY)
    if not isinstance(declared, dict) or not declared:
        raise _invalid(f"{_ENVIRONMENTS_KEY!r} must be a non-empty mapping of environment keys")
    environments = tuple(
        sorted(
            (_environment(name, raw) for name, raw in declared.items()),
            key=lambda item: item.name,
        )
    )
    return GoldDatabricksConnectionSpec(
        default_environment=_default_environment(
            block.get(_DEFAULT_ENVIRONMENT_KEY),
            environments,
        ),
        environments=environments,
    )


def load_gold_databricks_connection(
    hub_root: Path | None,
) -> GoldDatabricksConnectionSpec | None:
    """Load the hub's Gold Databricks connection block, or ``None`` when unauthored."""
    if hub_root is None:
        return None
    config_path = Path(hub_root) / "kairos.yaml"
    if not config_path.is_file():
        return None
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise _invalid(f"{config_path} could not be read ({exc})") from exc
    return parse_gold_databricks_connection(config)
