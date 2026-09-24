# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Per-environment Databricks connection configuration for Gold semantic models.

Both semantic modes need connection details, for different reasons. A
``directQuery`` model over Databricks SQL must name a concrete server hostname and
HTTP path, and an unresolved placeholder there produces a semantic model that cannot
connect to anything (issue #283). A Direct Lake model binds through a named
expression whose OneLake URL embeds a specific workspace and lakehouse, so it needs
``gold.direct_lake_connection`` and fails closed without it -- this module said
"it needs none" until #623, which was wrong in both directions: the projector had
already required it since #619, and the emitted model could not be promoted to
another workspace because nothing rewrote those GUIDs at deploy time.

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

import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

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


#: Governance rule for the Direct Lake OneLake connection (#619 Bugs 4/6).
GOLD_DIRECT_LAKE_RULE_ID = "DD-113-direct-lake-connection"

_DIRECT_LAKE_KEY = "direct_lake_connection"
_DIRECT_LAKE_ENVIRONMENT_FIELDS = ("workspace_id", "item_id")
#: The pre-DD-239 name for ``item_id``, still accepted. dbt's Direct Lake adapter
#: (`fabric-warehouse`) writes Gold into a Fabric *Warehouse*, so "lakehouse" sent authors
#: looking for an item that does not hold the tables.
_DIRECT_LAKE_ITEM_ALIAS = "lakehouse_id"
_DIRECT_LAKE_CONFIG_PATH = f"{_GOLD_KEY}.{_DIRECT_LAKE_KEY}"
#: A Fabric workspace/lakehouse ID is a GUID; anything else is an unresolved
#: placeholder (the exact failure mode #619 Bugs 4/6 report).
_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
#: The value the scaffolded ``kairos.yaml`` ships as an example. It is GUID-shaped, so
#: format validation alone cannot tell it from a real ID (issue #662).
_PLACEHOLDER_GUID = "00000000-0000-0000-0000-000000000000"


@dataclass(frozen=True, slots=True)
class GoldDirectLakeEnvironmentSpec:
    """One environment's OneLake coordinates: a workspace and the Fabric item in it.

    ``item_id`` is the item Gold lives in (DD-239). For the `fabric-warehouse` adapter --
    the only one that emits Direct Lake -- that is the Warehouse dbt writes the `gold_*`
    schemas into, whose Delta tables OneLake serves at `<item>/Tables/<schema>/<table>`.
    """

    name: str
    workspace_id: str
    item_id: str

    @property
    def lakehouse_id(self) -> str:
        """Deprecated name for ``item_id``."""
        return self.item_id


@dataclass(frozen=True, slots=True)
class GoldDirectLakeConnectionSpec:
    """Every environment a released Direct Lake semantic model may be promoted into."""

    default_environment: str
    environments: tuple[GoldDirectLakeEnvironmentSpec, ...]

    @property
    def default(self) -> GoldDirectLakeEnvironmentSpec:
        """Return the environment whose values are emitted into the artifact."""
        return next(item for item in self.environments if item.name == self.default_environment)


#: Shown with every malformed-block diagnostic. The scaffolded ``kairos.yaml`` shipped a
#: list-of-dicts example (``- name: dev``) that this parser rejects, and the symptom-only
#: message ("must be a non-empty mapping") left no way to self-correct without reading
#: this module's source (issue #663).
_DIRECT_LAKE_SHAPE_EXAMPLE = """

expected shape:

gold:
  direct_lake_connection:
    default_environment: dev
    environments:
      dev:
        workspace_id: <workspace GUID>
        item_id: <GUID of the Warehouse dbt writes Gold into>
      prod:
        workspace_id: <workspace GUID>
        item_id: <GUID of the Warehouse dbt writes Gold into>

'environments' is a mapping keyed by environment name, not a list of '- name:' entries."""


def _direct_lake_invalid(detail: str) -> GoldContractError:
    return GoldContractError(
        "gold.direct-lake-connection-invalid",
        f"kairos.yaml {_DIRECT_LAKE_CONFIG_PATH} is malformed: {detail}"
        f"{_DIRECT_LAKE_SHAPE_EXAMPLE}",
        rule_id=GOLD_DIRECT_LAKE_RULE_ID,
    )


def _direct_lake_guid(environment: str, field: str, raw: object) -> str:
    if not isinstance(raw, str) or not _GUID.match(raw.strip()):
        raise _direct_lake_invalid(
            f"environment {environment!r} needs a GUID {field!r} "
            "(author the resolved workspace/item ID, not a template placeholder)"
        )
    value = raw.strip()
    if value.lower() == _PLACEHOLDER_GUID:
        raise _direct_lake_invalid(
            f"environment {environment!r} {field!r} is the all-zero placeholder GUID. "
            "It matches the GUID format, so nothing downstream would reject it, and the "
            "emitted TMDL would carry a OneLake path that resolves to nothing -- a "
            "well-formed model that silently cannot deploy. Author the real ID, or, if "
            "this environment's infrastructure is owned downstream, declare it in the "
            "dataplatform's .github/fabric/gold-connections.yml and let the deploy "
            "workflow supply the value (see CICD.md, 'Fabric and Power BI')."
        )
    return value


def _direct_lake_environment(name: object, raw: object) -> GoldDirectLakeEnvironmentSpec:
    if not isinstance(name, str) or not name.strip():
        raise _direct_lake_invalid(f"environment key {name!r} is not a non-empty string")
    environment = name.strip()
    if not isinstance(raw, dict):
        raise _direct_lake_invalid(f"environment {environment!r} must be a mapping")
    accepted = {*_DIRECT_LAKE_ENVIRONMENT_FIELDS, _DIRECT_LAKE_ITEM_ALIAS}
    unknown = sorted(set(map(str, raw)) - accepted)
    if unknown:
        raise _direct_lake_invalid(f"environment {environment!r} has unknown key(s) {unknown}")
    if "item_id" in raw and _DIRECT_LAKE_ITEM_ALIAS in raw:
        raise _direct_lake_invalid(
            f"environment {environment!r} sets both 'item_id' and its deprecated alias "
            f"{_DIRECT_LAKE_ITEM_ALIAS!r}; keep 'item_id'"
        )
    field = "item_id"
    if _DIRECT_LAKE_ITEM_ALIAS in raw:
        field = _DIRECT_LAKE_ITEM_ALIAS
        warnings.warn(
            f"{_DIRECT_LAKE_ITEM_ALIAS!r} is deprecated; rename it to 'item_id' -- the Fabric "
            "item Gold lives in, which for fabric-warehouse is the Warehouse (DD-239)",
            FutureWarning,
            stacklevel=2,
        )
    return GoldDirectLakeEnvironmentSpec(
        name=environment,
        workspace_id=_direct_lake_guid(environment, "workspace_id", raw.get("workspace_id")),
        item_id=_direct_lake_guid(environment, field, raw.get(field)),
    )


def _direct_lake_default_environment(
    raw: object,
    environments: tuple[GoldDirectLakeEnvironmentSpec, ...],
) -> str:
    names = [item.name for item in environments]
    if raw is None:
        if len(environments) > 1:
            raise _direct_lake_invalid(
                f"{_DEFAULT_ENVIRONMENT_KEY!r} is required when more than one environment "
                f"is declared (declared: {names})"
            )
        return names[0]
    if not isinstance(raw, str) or raw.strip() not in names:
        raise _direct_lake_invalid(
            f"{_DEFAULT_ENVIRONMENT_KEY!r} {raw!r} is not one of the declared environments {names}"
        )
    return raw.strip()


def parse_gold_direct_lake_connection(config: object) -> GoldDirectLakeConnectionSpec | None:
    """Read the Direct Lake OneLake connection block out of already-loaded ``kairos.yaml``."""
    if not isinstance(config, dict):
        return None
    gold = config.get(_GOLD_KEY)
    if gold is None:
        return None
    if not isinstance(gold, dict):
        raise _direct_lake_invalid(f"{_GOLD_KEY!r} must be a mapping")
    block = gold.get(_DIRECT_LAKE_KEY)
    if block is None:
        return None
    if not isinstance(block, dict):
        raise _direct_lake_invalid("the direct_lake_connection block must be a mapping")
    unknown = sorted(set(map(str, block)) - {_ENVIRONMENTS_KEY, _DEFAULT_ENVIRONMENT_KEY})
    if unknown:
        raise _direct_lake_invalid(f"unknown key(s) {unknown}")
    declared = block.get(_ENVIRONMENTS_KEY)
    if not isinstance(declared, dict) or not declared:
        raise _direct_lake_invalid(
            f"{_ENVIRONMENTS_KEY!r} must be a non-empty mapping of environment keys"
        )
    environments = tuple(
        sorted(
            (_direct_lake_environment(name, raw) for name, raw in declared.items()),
            key=lambda item: item.name,
        )
    )
    return GoldDirectLakeConnectionSpec(
        default_environment=_direct_lake_default_environment(
            block.get(_DEFAULT_ENVIRONMENT_KEY),
            environments,
        ),
        environments=environments,
    )


def load_gold_direct_lake_connection(
    hub_root: Path | None,
) -> GoldDirectLakeConnectionSpec | None:
    """Load the hub's Gold Direct Lake connection block, or ``None`` when unauthored."""
    if hub_root is None:
        return None
    config_path = Path(hub_root) / "kairos.yaml"
    if not config_path.is_file():
        return None
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise _direct_lake_invalid(f"{config_path} could not be read ({exc})") from exc
    return parse_gold_direct_lake_connection(config)


# --------------------------------------------------------------------------------------
# Gold product scope (issue #744)
# --------------------------------------------------------------------------------------

#: Governance rule for product scope.
GOLD_PRODUCT_RULE_ID = "DD-222-gold-product-scope"

_PRODUCTS_KEY = "products"
_SHARED_DOMAINS_KEY = "shared_domains"
_PRODUCTS_CONFIG_PATH = f"{_GOLD_KEY}.{_PRODUCTS_KEY}"
_SHARED_DOMAINS_CONFIG_PATH = f"{_GOLD_KEY}.{_SHARED_DOMAINS_KEY}"
#: Used verbatim in artifact paths and as the stem of the manifest filename, so the same
#: character class the emitter already sanitises domains to.
_PRODUCT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True, slots=True)
class GoldProductConfig:
    """One analytical product and the ontology domains it is built from.

    A Gold product follows a business process, not a modelling boundary: facts from one
    domain joined to conformed dimensions from several others. Domains stay the unit of
    ontology design and of Silver compilation; the product is the unit of *delivery*.
    """

    name: str
    domains: tuple[str, ...]
    display_name: str = ""
    #: False for a product the hub never declared -- one Gold-configured domain standing
    #: alone under its own name, which is what every hub emitted before #744.
    declared: bool = True
    #: Which of *this product's* `domains` the hub declared shared (#829). A conformed
    #: dimension is materialized once by the domain that binds it and read by every
    #: product that needs it, so these contribute tables the product does not own.
    shared_domains: tuple[str, ...] = ()

    def owns(self, domain: str) -> bool:
        """Whether this product's emit is where *domain*'s tables are actually built."""
        return domain not in self.shared_domains

    @property
    def model_name(self) -> str:
        """The path-safe stem for this product's emitted item folders.

        Always derived from `name`, never from `display_name`: a display name is free text
        for the Fabric workspace and may contain spaces or characters that are illegal in a
        path, a zip entry or a fabric-cicd `repository_directory`. The display name reaches
        Fabric through `.platform`, which is what names the item there.
        """
        return "".join(part.capitalize() for part in re.split(r"[-_]", self.name) if part)


def _product_invalid(detail: str) -> GoldContractError:
    return GoldContractError(
        "gold.products-invalid",
        f"{_PRODUCTS_CONFIG_PATH} is malformed: {detail}",
        rule_id=GOLD_PRODUCT_RULE_ID,
    )


def parse_gold_products(config: object) -> tuple[GoldProductConfig, ...]:
    """Parse the ``gold.products`` block, or return ``()`` when unauthored."""
    if not isinstance(config, dict):
        return ()
    gold = config.get(_GOLD_KEY)
    if not isinstance(gold, dict):
        return ()
    raw = gold.get(_PRODUCTS_KEY)
    if raw is None:
        return ()
    if not isinstance(raw, list) or not raw:
        raise _product_invalid("expected a non-empty list of products")

    shared_domains = _parse_shared_domains(gold)
    products: list[GoldProductConfig] = []
    seen_names: set[str] = set()
    domain_owner: dict[str, str] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise _product_invalid("each product must be a mapping with 'name' and 'domains'")
        unknown = sorted(set(entry) - {"name", "domains", "display_name"})
        if unknown:
            raise _product_invalid(f"unknown key(s) {unknown} on a product")
        name = entry.get("name")
        if not isinstance(name, str) or not _PRODUCT_NAME.fullmatch(name):
            raise _product_invalid(
                f"product name {name!r} must be lower-case letters, digits and hyphens "
                "(it is used verbatim in emitted artifact paths)"
            )
        if name in seen_names:
            raise _product_invalid(f"duplicate product name {name!r}")
        seen_names.add(name)
        domains = entry.get("domains")
        if (
            not isinstance(domains, list)
            or not domains
            or not all(isinstance(item, str) and item for item in domains)
        ):
            raise _product_invalid(f"product {name!r} must declare a non-empty 'domains' list")
        if len(set(domains)) != len(domains):
            raise _product_invalid(f"product {name!r} repeats a domain")
        for domain in domains:
            if domain in shared_domains:
                # A conformed dimension is materialized once by the domain that binds it
                # and read by every product that needs it, so the rule below does not
                # apply -- see `_parse_shared_domains` for why this must be declared.
                continue
            owner = domain_owner.get(domain)
            if owner is not None:
                # One Gold table belongs to one semantic model. Two products over the same
                # domain would emit its tables twice under different names, and a report
                # author would have no way to tell which copy is authoritative.
                raise _product_invalid(
                    f"domain {domain!r} is claimed by both {owner!r} and {name!r}; "
                    "a domain belongs to exactly one Gold product "
                    f"(declare it under {_SHARED_DOMAINS_CONFIG_PATH} if it is a "
                    "conformed dimension both products read)"
                )
            domain_owner[domain] = name
        display_name = entry.get("display_name", "")
        if not isinstance(display_name, str):
            raise _product_invalid(f"product {name!r} has a non-string 'display_name'")
        products.append(
            GoldProductConfig(
                name=name,
                domains=tuple(domains),
                display_name=display_name.strip(),
                shared_domains=tuple(item for item in domains if item in shared_domains),
            )
        )
    conflicting = sorted(shared_domains & seen_names)
    if conflicting:
        raise _shared_domains_invalid(
            f"{conflicting} name(s) a declared product; a shared domain contributes "
            "tables to products and is not one itself"
        )
    return tuple(products)


def _parse_shared_domains(gold: dict) -> frozenset[str]:
    """Parse ``gold.shared_domains`` -- the domains several products may claim (#829).

    Declared, never inferred. Sharing could be guessed from a domain authoring only
    dimensions, but then adding the first fact to it would silently re-materialize every
    one of its tables in every consuming product -- a change in physical layout with no
    edit to say so. An explicit list makes that a decision somebody wrote down.

    A domain nothing references yet is accepted: declaring the conformed dimension before
    adding the second product is the natural authoring order, and this function raises
    rather than warns, so there is nowhere for a softer signal to go.
    """
    raw = gold.get(_SHARED_DOMAINS_KEY)
    if raw is None:
        return frozenset()
    if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
        raise _shared_domains_invalid("expected a list of domain names")
    if len(set(raw)) != len(raw):
        raise _shared_domains_invalid("a domain is listed twice")
    return frozenset(raw)


def _shared_domains_invalid(detail: str) -> GoldContractError:
    return GoldContractError(
        "gold.shared-domains-invalid",
        f"{_SHARED_DOMAINS_CONFIG_PATH} is malformed: {detail}",
        rule_id=GOLD_PRODUCT_RULE_ID,
    )


def load_gold_products(hub_root: Path | None) -> tuple[GoldProductConfig, ...]:
    """Load the hub's declared Gold products, or ``()`` when none are declared."""
    if hub_root is None:
        return ()
    config_path = Path(hub_root) / "kairos.yaml"
    if not config_path.is_file():
        return ()
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise _product_invalid(f"{config_path} could not be read ({exc})") from exc
    return parse_gold_products(config)


def resolve_gold_product(
    hub_root: Path | None,
    requested: str,
    *,
    hub_domains: tuple[str, ...],
) -> GoldProductConfig:
    """Resolve *requested* -- a product name or a domain name -- to one product.

    A domain that no declared product claims stays its own implicit product under its own
    name, so a hub that declares nothing keeps emitting exactly what it emitted before
    #744. Whether that domain actually authors a Gold profile is deliberately *not*
    checked here: the caller checks it per participating domain and can say so precisely,
    which is a better error than "unknown product" for a real domain that simply has no
    Gold extension yet.
    """
    products = load_gold_products(hub_root)
    for product in products:
        if product.name in hub_domains and product.name not in product.domains:
            # Product names are matched before domain names and share the output
            # directory and manifest, so a product named after an unrelated domain would
            # silently make that domain's own Gold unemittable and delete its tree on the
            # next emit. Cheap to reject, invisible to debug.
            raise GoldContractError(
                "gold.product-shadows-domain",
                (
                    f"Gold product {product.name!r} is named after the hub domain "
                    f"{product.name!r}, which it does not include. Rename the product: "
                    "a product name it shares with an unrelated domain would hide that "
                    "domain's own Gold output and overwrite its emitted tree"
                ),
                rule_id=GOLD_PRODUCT_RULE_ID,
            )
        if product.name == requested:
            return product
    claiming = [product for product in products if requested in product.domains]
    if len(claiming) > 1:
        # A shared domain has no product of its own to stand in for it, and picking one of
        # several would emit a model whose name says nothing about which it is.
        raise GoldContractError(
            "gold.domain-shared-across-products",
            (
                f"domain {requested!r} is a conformed dimension shared by "
                f"{', '.join(repr(product.name) for product in claiming)}; it is "
                "materialized by `compile` and read by each of them. Emit the product "
                "that needs it: "
                + " or ".join(f"`emit-gold {product.name}`" for product in claiming)
            ),
            rule_id=GOLD_PRODUCT_RULE_ID,
        )
    if claiming:
        owner = claiming[0]
        raise GoldContractError(
            "gold.domain-belongs-to-product",
            (
                f"domain {requested!r} is part of the Gold product {owner.name!r}; "
                f"emit the product instead: `emit-gold {owner.name}` "
                f"(domains: {', '.join(owner.domains)})"
            ),
            rule_id=GOLD_PRODUCT_RULE_ID,
        )
    if requested in hub_domains:
        return GoldProductConfig(name=requested, domains=(requested,), declared=False)
    known = sorted({*(product.name for product in products), *hub_domains})
    raise GoldContractError(
        "gold.unknown-product",
        (
            f"{requested!r} is neither a declared Gold product nor a domain in this hub. "
            f"Known: {', '.join(known) if known else '(none)'}"
        ),
        rule_id=GOLD_PRODUCT_RULE_ID,
    )


# --------------------------------------------------------------------------------------
# Deploy-time Direct Lake overrides (issue #662)
# --------------------------------------------------------------------------------------

#: Repo-relative default location of the dataplatform's override file.
GOLD_CONNECTION_OVERRIDE_PATH = ".github/fabric/gold-connections.yml"


class GoldConnectionOverrideError(Exception):
    """The dataplatform's deploy-time override file is unusable."""


def _resolve_env_refs(value: str, environ: Mapping[str, str]) -> str:
    """Expand a whole-value ``${VAR}`` reference against *environ*.

    Only a complete ``${VAR}`` is expanded, never a substring: these values are GUIDs
    that get concatenated into a URL, and a partially-substituted GUID would produce a
    well-formed URL pointing somewhere nobody intended.
    """
    match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value.strip())
    if match is None:
        return value.strip()
    name = match.group(1)
    resolved = environ.get(name)
    if not resolved:
        raise GoldConnectionOverrideError(
            f"{GOLD_CONNECTION_OVERRIDE_PATH} references ${{{name}}}, which is unset or "
            "empty in the deploy environment"
        )
    return resolved.strip()


def parse_gold_connection_overrides(
    document: object,
    environ: Mapping[str, str],
    *,
    only: str | None = None,
) -> dict[str, GoldDirectLakeEnvironmentSpec]:
    """Read the dataplatform-owned ``gold-connections.yml`` into typed environments.

    *only* resolves and validates just that environment (#993). A deploy runs against one
    target and is given only that target's variables, so resolving every environment made
    a DEV deploy fail on PROD's unset ``${VAR}``. The others are still shape-checked.

    Deliberately validated with the same GUID rules the hub applies to its own
    ``kairos.yaml``, including the all-zero placeholder rejection: an override that ships
    a placeholder would repoint a deployment at a OneLake path resolving to nothing,
    which is the exact failure the hub-side check exists to prevent.
    """
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise GoldConnectionOverrideError(
            f"{GOLD_CONNECTION_OVERRIDE_PATH} must be a mapping with an 'environments' key"
        )
    declared = document.get(_ENVIRONMENTS_KEY)
    if declared is None:
        return {}
    if not isinstance(declared, dict):
        raise GoldConnectionOverrideError(
            f"{GOLD_CONNECTION_OVERRIDE_PATH}: {_ENVIRONMENTS_KEY!r} must be a mapping "
            "keyed by environment name, not a list"
        )
    resolved: dict[str, GoldDirectLakeEnvironmentSpec] = {}
    for name, raw in declared.items():
        if not isinstance(raw, dict):
            raise GoldConnectionOverrideError(
                f"{GOLD_CONNECTION_OVERRIDE_PATH}: environment {name!r} must be a mapping"
            )
        if only is not None and str(name) != only:
            continue
        expanded = {
            field: _resolve_env_refs(str(raw[field]), environ)
            for field in (*_DIRECT_LAKE_ENVIRONMENT_FIELDS, _DIRECT_LAKE_ITEM_ALIAS)
            if field in raw
        }
        try:
            resolved[str(name)] = _direct_lake_environment(str(name), expanded)
        except GoldContractError as exc:
            raise GoldConnectionOverrideError(f"{GOLD_CONNECTION_OVERRIDE_PATH}: {exc}") from exc
    return resolved


def declared_parameter_environments(parameter_yaml: str) -> frozenset[str]:
    """Return the environments every ``find_replace`` entry of *parameter_yaml* declares.

    fabric-cicd applies one ``replace_value[environment]`` per entry and silently skips an
    entry that does not declare the environment, so an environment is only fully
    parameterised when *every* entry names it -- hence the intersection (#993).
    """
    document = yaml.safe_load(parameter_yaml)
    entries = document.get("find_replace") if isinstance(document, dict) else None
    if not isinstance(entries, list) or not entries:
        raise GoldConnectionOverrideError("parameter.yml has no 'find_replace' entries")
    declared: frozenset[str] | None = None
    for entry in entries:
        replace_value = entry.get("replace_value") if isinstance(entry, dict) else None
        keys = frozenset(str(key) for key in replace_value) if isinstance(
            replace_value, dict
        ) else frozenset()
        declared = keys if declared is None else declared & keys
    return declared or frozenset()


def apply_gold_connection_override(
    parameter_yaml: str,
    environment: str,
    override: GoldDirectLakeEnvironmentSpec,
) -> tuple[str, str, str]:
    """Repoint one environment of a shipped ``parameter.yml`` at *override*.

    Returns ``(rewritten_yaml, previous_url, new_url)``.

    ``find_value`` is never touched. It is the OneLake URL the hub baked verbatim into
    the TMDL, and fabric-cicd matches it by literal substring -- only the hub knows it
    byte for byte, so letting the dataplatform supply it would make the rewrite silently
    miss and leave the model pointed at the hub's default workspace.
    """
    document = yaml.safe_load(parameter_yaml)
    if not isinstance(document, dict):
        raise GoldConnectionOverrideError("parameter.yml is not a mapping")
    entries = document.get("find_replace")
    if not isinstance(entries, list) or not entries:
        raise GoldConnectionOverrideError("parameter.yml has no 'find_replace' entries")

    new_url = (
        f"https://onelake.dfs.fabric.microsoft.com/{override.workspace_id}/{override.item_id}"
    )
    previous = ""
    rewritten = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        replace_value = entry.get("replace_value")
        if not isinstance(replace_value, dict):
            continue
        previous = str(replace_value.get(environment, "")) or previous
        replace_value[environment] = new_url
        rewritten += 1
    if not rewritten:
        raise GoldConnectionOverrideError(
            "parameter.yml has no 'replace_value' mapping to override; the hub may have "
            "emitted a non-Direct-Lake model"
        )
    return (
        yaml.safe_dump(document, sort_keys=False, default_flow_style=False, allow_unicode=True),
        previous,
        new_url,
    )
