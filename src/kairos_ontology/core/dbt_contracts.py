# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Read-only discovery of ordinary contracted dbt models."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

import yaml

from .adapters import SUPPORTED_ADAPTER_IDS, UnsupportedAdapterError, resolve_adapter

SUPPORTED_MATERIALIZATIONS = frozenset({"table", "view", "incremental"})
#: Canonical vocabulary owned by :mod:`kairos_ontology.core.adapters` (DD-215).
SUPPORTED_ADAPTERS = frozenset(SUPPORTED_ADAPTER_IDS)
APPROVED_DBT_PACKAGES: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "dbt-labs/dbt_utils": (">=1.0.0", "<2.0.0"),
        "metaplane/dbt_expectations": (">=0.10.0", "<1.0.0"),
    }
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MACRO_RE = re.compile(r"^(?!kairos_)[a-z][a-z0-9_]*__[a-z][a-z0-9_]*$")


def canonical_adapters(values: Iterable[str]) -> tuple[str, ...] | None:
    """Resolve authored adapter ids, or ``None`` when any of them is unsupported.

    Authored contracts are client content, so the deprecated ``fabric`` spelling must keep
    resolving here exactly as it does for ``kairos.yaml`` (DD-215).
    """
    resolved: list[str] = []
    for value in values:
        try:
            canonical, _ = resolve_adapter(value)
        except UnsupportedAdapterError:
            return None
        resolved.append(canonical)
    return tuple(resolved)


class DbtContractError(ValueError):
    """Raised when a custom dbt contract or its bundle is invalid."""


@dataclass(frozen=True)
class DbtContractColumn:
    """One physical output column in a contracted dbt model."""

    name: str
    data_type: str
    description: str | None = None
    not_null: bool = False
    tests: tuple[str, ...] = ()


@dataclass(frozen=True)
class DbtContractModel:
    """One ordinary dbt SQL model and its enforced YAML output contract."""

    name: str
    description: str
    materialization: str
    target_class: str
    virtual_source_iri: str
    grain: str
    supported_adapters: tuple[str, ...]
    grain_key: tuple[str, ...]
    required_packages: tuple[str, ...]
    required_macros: tuple[str, ...]
    columns: tuple[DbtContractColumn, ...]
    properties_path: Path
    sql_path: Path
    canonical_cdc_bindings: tuple[tuple[str, str], ...] = ()


def _error(path: Path, message: str) -> DbtContractError:
    return DbtContractError(f"{path}: {message}")


def _required_string(data: dict[str, Any], key: str, path: Path, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _error(path, f"{context}.{key} must be a non-empty string")
    return value.strip()


def _string_list(
    value: object, path: Path, context: str, *, non_empty: bool = False
) -> tuple[str, ...]:
    if not isinstance(value, list) or (non_empty and not value):
        qualifier = "a non-empty list" if non_empty else "a list"
        raise _error(path, f"{context} must be {qualifier} of strings")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise _error(path, f"{context} must contain only non-empty strings")
    return tuple(item.strip() for item in value)


def _is_http_iri(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _load_properties(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise _error(path, f"could not parse YAML: {exc}") from exc
    if not isinstance(loaded, dict) or loaded.get("version") != 2:
        raise _error(path, "dbt properties document must be a version: 2 mapping")
    if not isinstance(loaded.get("models", []), list):
        raise _error(path, "'models' must be a list")
    return loaded


def _parse_columns(model: dict[str, Any], path: Path, name: str) -> tuple[DbtContractColumn, ...]:
    raw_columns = model.get("columns")
    if not isinstance(raw_columns, list) or not raw_columns:
        raise _error(path, f"model {name!r} must declare a non-empty columns list")
    columns: list[DbtContractColumn] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_columns):
        context = f"model {name!r} columns[{index}]"
        if not isinstance(raw, dict):
            raise _error(path, f"{context} must be a mapping")
        column_name = _required_string(raw, "name", path, context)
        data_type = _required_string(raw, "data_type", path, context)
        folded = column_name.casefold()
        if not _IDENTIFIER_RE.fullmatch(column_name) or folded in seen:
            raise _error(path, f"{context}.name is invalid or duplicated: {column_name!r}")
        seen.add(folded)
        tests = raw.get("data_tests", raw.get("tests", []))
        constraints = raw.get("constraints", [])
        if not isinstance(tests, list) or not isinstance(constraints, list):
            raise _error(path, f"{context} tests and constraints must be lists")
        not_null = any(
            test == "not_null" or isinstance(test, dict) and "not_null" in test for test in tests
        ) or any(
            isinstance(constraint, dict) and constraint.get("type") == "not_null"
            for constraint in constraints
        )
        normalized_tests = tuple(
            sorted(
                test if isinstance(test, str) else next(iter(test))
                for test in tests
                if isinstance(test, str) or isinstance(test, dict) and test
            )
        )
        description = raw.get("description")
        if description is not None and not isinstance(description, str):
            raise _error(path, f"{context}.description must be a string")
        columns.append(
            DbtContractColumn(column_name, data_type, description, not_null, normalized_tests)
        )
    return tuple(columns)


def _parse_contract(
    model: dict[str, Any],
    path: Path,
    sql_paths: dict[str, list[Path]],
) -> DbtContractModel:
    name = _required_string(model, "name", path, "model")
    if not _IDENTIFIER_RE.fullmatch(name):
        raise _error(path, f"model name is not a valid dbt identifier: {name!r}")
    description = _required_string(model, "description", path, f"model {name!r}")
    config = model.get("config")
    if not isinstance(config, dict):
        raise _error(path, f"model {name!r}.config must be a mapping")
    materialization = _required_string(config, "materialized", path, f"model {name!r}.config")
    if materialization not in SUPPORTED_MATERIALIZATIONS:
        raise _error(path, f"model {name!r} has unsupported materialization {materialization!r}")
    contract = config.get("contract")
    if not isinstance(contract, dict) or contract.get("enforced") is not True:
        raise _error(path, f"model {name!r} must set config.contract.enforced: true")
    meta_holder = model.get("meta")
    meta = meta_holder.get("kairos") if isinstance(meta_holder, dict) else None
    if not isinstance(meta, dict):
        raise _error(path, f"model {name!r}.meta.kairos must be a mapping")
    target_class = _required_string(meta, "target_class", path, f"model {name!r}.meta.kairos")
    virtual_source_iri = _required_string(
        meta, "virtual_source_iri", path, f"model {name!r}.meta.kairos"
    )
    if not _is_http_iri(target_class) or not _is_http_iri(virtual_source_iri):
        raise _error(path, f"model {name!r} target and virtual source must be HTTP(S) IRIs")
    columns = _parse_columns(model, path, name)
    column_names = {column.name for column in columns}
    grain_key = _string_list(
        meta.get("grain_key"), path, f"model {name!r}.meta.kairos.grain_key", non_empty=True
    )
    if len(set(grain_key)) != len(grain_key) or not set(grain_key) <= column_names:
        raise _error(path, f"model {name!r} grain_key must contain unique contract columns")
    adapters = _string_list(
        meta.get("supported_adapters"),
        path,
        f"model {name!r}.meta.kairos.supported_adapters",
        non_empty=True,
    )
    if len(set(adapters)) != len(adapters) or not canonical_adapters(adapters):
        raise _error(path, f"model {name!r} has invalid supported_adapters")
    packages = _string_list(
        meta.get("required_packages", []),
        path,
        f"model {name!r}.meta.kairos.required_packages",
    )
    if len(set(packages)) != len(packages) or not set(packages) <= APPROVED_DBT_PACKAGES.keys():
        raise _error(path, f"model {name!r} has duplicate or unapproved required_packages")
    macros = _string_list(
        meta.get("required_macros", []), path, f"model {name!r}.meta.kairos.required_macros"
    )
    if len(set(macros)) != len(macros) or any(not _MACRO_RE.fullmatch(item) for item in macros):
        raise _error(path, f"model {name!r} has invalid required_macros")
    matches = sql_paths.get(name, [])
    if len(matches) != 1:
        raise _error(path, f"model {name!r} must resolve to exactly one matching model SQL")
    raw_cdc = meta.get("canonical_cdc_bindings", {})
    if not isinstance(raw_cdc, dict) or any(
        key not in {"operation", "source_updated_at", "source_effective_at", "ingested_at"}
        or not isinstance(value, str)
        or value not in column_names
        for key, value in raw_cdc.items()
    ):
        raise _error(path, f"model {name!r} has invalid canonical_cdc_bindings")
    return DbtContractModel(
        name=name,
        description=description,
        materialization=materialization,
        target_class=target_class,
        virtual_source_iri=virtual_source_iri,
        grain=_required_string(meta, "grain", path, f"model {name!r}.meta.kairos"),
        supported_adapters=adapters,
        grain_key=grain_key,
        required_packages=packages,
        required_macros=macros,
        columns=columns,
        properties_path=path,
        sql_path=matches[0],
        canonical_cdc_bindings=tuple(sorted(raw_cdc.items())),
    )


@dataclass(frozen=True)
class DbtModelStub:
    """One ``models[]`` entry in a properties document, before contract parsing.

    The full inventory -- including models with **no** ``meta.kairos`` block, which
    :func:`discover_dbt_contracts` drops. ``validate-dbt-contracts`` needs those: a `stg_*`
    model that wrongly declares a `meta.kairos` block, and an `int_*` model that wrongly
    omits one, are both only visible against the whole inventory.

    ``kairos_meta`` is the **raw, unvalidated** block. That matters: a `<CONFIRM_...>`
    scaffold sentinel is rejected by :func:`_parse_contract` as a malformed IRI long before
    anything can notice it *is* a sentinel, so the only way to tell an author "you have not
    filled in the scaffold yet" rather than "your IRI is invalid" is to read it pre-parse.
    """

    name: str
    properties_path: Path
    has_kairos_meta: bool
    kairos_meta: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class DbtContractIssue:
    """One problem found while scanning, attributed to a model where one is identifiable."""

    path: Path
    message: str
    #: ``None`` for a document-level failure (unparseable YAML, a non-mapping ``models[]``
    #: entry) -- there is no model name to attribute it to yet.
    model: str | None = None


@dataclass(frozen=True)
class DbtContractScan:
    """Everything one pass over ``<transforms>/models`` found, errors included.

    :func:`discover_dbt_contracts` raises on the first bad model, which is right for the
    bundle path (a half-assembled dbt project is not shippable) but wrong for a lint, where
    one malformed contract must not hide the other twenty. This carries both.
    """

    models: tuple[DbtContractModel, ...]
    inventory: tuple[DbtModelStub, ...]
    #: Walk failures ordered before parse failures -- the same order
    #: :func:`discover_dbt_contracts` would have raised them in.
    errors: tuple[DbtContractIssue, ...]


def scan_dbt_contracts(transforms_dir: Path, hub_root: Path) -> DbtContractScan:
    """Non-raising :func:`discover_dbt_contracts`: collect every model **and** every error.

    A missing/outside-the-hub transforms directory is still raised, not collected -- that is
    a caller mistake, not a finding about the hub's contracts.
    """

    root = Path(hub_root).resolve()
    transforms = Path(transforms_dir).resolve()
    models_dir = transforms / "models"
    if not transforms.is_relative_to(root) or not models_dir.is_dir():
        raise DbtContractError(f"{transforms}: transforms directory must be inside hub root")

    walk_errors: list[DbtContractIssue] = []
    parse_errors: list[DbtContractIssue] = []
    documents: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted([*models_dir.rglob("*.yml"), *models_dir.rglob("*.yaml")]):
        try:
            documents.append((path, _load_properties(path)))
        except DbtContractError as exc:
            walk_errors.append(DbtContractIssue(path, str(exc)))

    selected: list[tuple[dict[str, Any], Path]] = []
    inventory: list[DbtModelStub] = []
    resources: dict[str, Path] = {}
    for path, document in documents:
        for index, model in enumerate(document.get("models", [])):
            if not isinstance(model, dict):
                walk_errors.append(
                    DbtContractIssue(path, str(_error(path, f"models[{index}] must be a mapping")))
                )
                continue
            try:
                name = _required_string(model, "name", path, f"models[{index}]")
            except DbtContractError as exc:
                walk_errors.append(DbtContractIssue(path, str(exc)))
                continue
            if name in resources:
                walk_errors.append(
                    DbtContractIssue(
                        path, str(_error(path, f"duplicate dbt model resource {name!r}")), name
                    )
                )
                continue
            resources[name] = path
            meta = model.get("meta")
            kairos = meta.get("kairos") if isinstance(meta, dict) else None
            has_kairos = isinstance(meta, dict) and "kairos" in meta
            inventory.append(
                DbtModelStub(name, path, has_kairos, kairos if isinstance(kairos, dict) else None)
            )
            if has_kairos:
                selected.append((model, path))

    sql_paths: dict[str, list[Path]] = {}
    for sql_path in models_dir.rglob("*.sql"):
        sql_paths.setdefault(sql_path.stem, []).append(sql_path.resolve())

    models: list[DbtContractModel] = []
    for model, path in selected:
        try:
            models.append(_parse_contract(model, path, sql_paths))
        except DbtContractError as exc:
            parse_errors.append(DbtContractIssue(path, str(exc), str(model.get("name") or "")))

    return DbtContractScan(
        models=tuple(sorted(models, key=lambda item: item.name)),
        inventory=tuple(sorted(inventory, key=lambda item: item.name)),
        errors=tuple(walk_errors) + tuple(parse_errors),
    )


def discover_dbt_contracts(transforms_dir: Path, hub_root: Path) -> tuple[DbtContractModel, ...]:
    """Discover ordinary SQL/YAML model contracts without registries or persistence.

    Fail-fast wrapper over :func:`scan_dbt_contracts`: any finding at all is raised as the
    :class:`DbtContractError` it used to be, preserving this function's exact contract for
    the bundle path. Use ``scan_dbt_contracts`` when you want to report every problem.
    """

    scan = scan_dbt_contracts(transforms_dir, hub_root)
    if scan.errors:
        raise DbtContractError(scan.errors[0].message)
    return scan.models
