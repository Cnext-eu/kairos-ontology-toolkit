# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused resolution of contracted dbt models as v5 compiler source symbols."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from ..dbt_contracts import SUPPORTED_ADAPTERS
from ..projections.dbt.policy_normalize import _source_type
from .adapter import ResolvedColumn, ResolvedRelation
from .bindings import EntityBinding
from .result import CompileDiagnostic, CompileError, SourceLocation

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REF_RE = re.compile(r"\bref\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")
_TRANSFORMS_PARTS = ("integration", "transforms", "dbt")


def _is_absolute_http_iri(value: object) -> bool:
    """Return True when *value* is an absolute ``http(s)://`` IRI with a netloc.

    The same shape rule ``dbt_contracts.py``'s ``_is_http_iri`` applies at bundle time;
    duplicated (rather than imported) because that module's helper takes no non-string
    fast path and this one is called on raw, untrusted YAML values.
    """

    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _failure(binding: EntityBinding, code: str, message: str, pointer: str) -> CompileError:
    return CompileError(
        [
            CompileDiagnostic(
                code=code,
                message=message,
                location=SourceLocation(
                    path=binding.source_path or "<binding>",
                    pointer=f"/source/dbtModel/{pointer}",
                ),
            )
        ]
    )


def _resolve_authored_path(
    binding: EntityBinding,
    hub_root: Path,
    authored: str,
    *,
    suffixes: frozenset[str],
    pointer: str,
) -> Path:
    relative = Path(authored)
    if relative.is_absolute() or ".." in relative.parts:
        raise _failure(
            binding,
            "dbt-source.unsafe-path",
            f"dbt {pointer} must be a repository-relative path",
            pointer,
        )
    resolved = (hub_root / relative).resolve()
    transforms = hub_root.joinpath(*_TRANSFORMS_PARTS).resolve()
    models = (transforms / "models").resolve()
    if (
        not resolved.is_relative_to(models)
        or resolved.suffix.lower() not in suffixes
        or not resolved.is_file()
    ):
        raise _failure(
            binding,
            "dbt-source.path-unresolved",
            (
                f"dbt {pointer} must resolve to an existing {sorted(suffixes)} file "
                f"under integration/transforms/dbt/models"
            ),
            pointer,
        )
    return resolved


def _load_contract(binding: EntityBinding, path: Path) -> dict[str, Any]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise _failure(
            binding,
            "dbt-source.contract-invalid",
            f"could not parse dbt output contract: {exc}",
            "contractPath",
        ) from exc
    if not isinstance(document, dict) or document.get("version") != 2:
        raise _failure(
            binding,
            "dbt-source.contract-invalid",
            "authoritative dbt output contract must be a version: 2 mapping",
            "contractPath",
        )
    models = document.get("models")
    if not isinstance(models, list):
        raise _failure(
            binding,
            "dbt-source.contract-invalid",
            "authoritative dbt output contract must declare a models list",
            "contractPath",
        )
    return document


def _dependency_sql_paths(
    binding: EntityBinding,
    hub_root: Path,
    selected_path: Path,
) -> tuple[Path, ...]:
    """Resolve the selected model's transitive authored ``ref()`` SQL closure."""
    models_dir = hub_root.joinpath(*_TRANSFORMS_PARTS, "models")
    resolved: dict[str, Path] = {}
    pending = [selected_path]
    while pending:
        path = pending.pop()
        model_name = path.stem
        previous = resolved.get(model_name.casefold())
        if previous is not None:
            if previous != path:
                raise _failure(
                    binding,
                    "dbt-source.dependency-unresolved",
                    (
                        f"dbt model name {model_name!r} resolves to more than one authored "
                        "SQL dependency"
                    ),
                    "sqlPath",
                )
            continue
        resolved[model_name.casefold()] = path
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise _failure(
                binding,
                "dbt-source.dependency-unresolved",
                f"could not read dbt SQL dependency {path}: {exc}",
                "sqlPath",
            ) from exc
        for ref_name in sorted(set(_REF_RE.findall(text))):
            matches = tuple(sorted(models_dir.rglob(f"{ref_name}.sql")))
            if len(matches) != 1:
                raise _failure(
                    binding,
                    "dbt-source.dependency-unresolved",
                    (
                        f"dbt ref({ref_name!r}) must resolve to exactly one authored SQL file "
                        "under integration/transforms/dbt/models"
                    ),
                    "sqlPath",
                )
            pending.append(matches[0].resolve())
    return tuple(sorted(resolved.values(), key=lambda path: path.as_posix()))


def resolve_dbt_model_dependency_paths(
    binding: EntityBinding, hub_root: str | Path
) -> tuple[Path, ...]:
    """Return the selected contracted model's validated transitive SQL closure."""
    model_ref = binding.source.dbt_model
    if model_ref is None:
        raise _failure(
            binding,
            "dbt-source.missing",
            "binding does not select source.dbtModel",
            "name",
        )
    root = Path(hub_root).resolve()
    selected_path = _resolve_authored_path(
        binding,
        root,
        model_ref.sql_path,
        suffixes=frozenset({".sql"}),
        pointer="sqlPath",
    )
    return _dependency_sql_paths(binding, root, selected_path)


def _selected_model(binding: EntityBinding, document: dict[str, Any]) -> dict[str, Any]:
    model_ref = binding.source.dbt_model
    assert model_ref is not None
    matches = [
        model
        for model in document["models"]
        if isinstance(model, dict) and model.get("name") == model_ref.name
    ]
    if len(matches) != 1:
        raise _failure(
            binding,
            "dbt-source.model-unresolved",
            (
                f"dbt model {model_ref.name!r} must occur exactly once in its "
                "authoritative output contract"
            ),
            "name",
        )
    return matches[0]


def _contract_columns(
    binding: EntityBinding, model: dict[str, Any], grain_key: tuple[str, ...]
) -> tuple[ResolvedColumn, ...]:
    raw_columns = model.get("columns")
    if not isinstance(raw_columns, list) or not raw_columns:
        raise _failure(
            binding,
            "dbt-source.columns-invalid",
            "authoritative dbt output contract must declare non-empty output columns",
            "contractPath",
        )
    columns: list[ResolvedColumn] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_columns):
        if not isinstance(raw, dict):
            raise _failure(
                binding,
                "dbt-source.columns-invalid",
                f"dbt output column {index} must be a mapping",
                "contractPath",
            )
        name = raw.get("name")
        data_type = raw.get("data_type")
        if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name) or name.casefold() in seen:
            raise _failure(
                binding,
                "dbt-source.columns-invalid",
                f"dbt output column {index} has a missing, invalid, or duplicate name",
                "contractPath",
            )
        if not isinstance(data_type, str) or _source_type(data_type) is None:
            raise _failure(
                binding,
                "dbt-source.type-invalid",
                f"dbt output column {name!r} has unsupported data_type {data_type!r}",
                "contractPath",
            )
        seen.add(name.casefold())
        tests = raw.get("data_tests", raw.get("tests", []))
        constraints = raw.get("constraints", [])
        if not isinstance(tests, list) or not isinstance(constraints, list):
            raise _failure(
                binding,
                "dbt-source.columns-invalid",
                f"dbt output column {name!r} tests and constraints must be lists",
                "contractPath",
            )
        declared_not_null = any(
            test == "not_null" or (isinstance(test, dict) and "not_null" in test) for test in tests
        ) or any(
            isinstance(constraint, dict) and constraint.get("type") == "not_null"
            for constraint in constraints
        )
        columns.append(
            ResolvedColumn(
                name=name,
                data_type=data_type,
                nullable=name not in grain_key and not declared_not_null,
                is_primary_key=name in grain_key,
            )
        )
    return tuple(columns)


def _kairos_meta(binding: EntityBinding, model: dict[str, Any]) -> dict[str, Any]:
    config = model.get("config")
    if (
        not isinstance(config, dict)
        or not isinstance(config.get("contract"), dict)
        or config["contract"].get("enforced") is not True
    ):
        raise _failure(
            binding,
            "dbt-source.contract-not-enforced",
            "selected dbt model must set config.contract.enforced: true",
            "contractPath",
        )
    meta = model.get("meta")
    kairos = meta.get("kairos") if isinstance(meta, dict) else None
    if not isinstance(kairos, dict):
        raise _failure(
            binding,
            "dbt-source.contract-invalid",
            "selected dbt model must declare meta.kairos output metadata",
            "contractPath",
        )
    return kairos


def resolve_dbt_model_source(
    binding: EntityBinding,
    hub_root: str | Path,
    *,
    dependency_paths: tuple[Path, ...] | None = None,
) -> ResolvedRelation:
    """Resolve one ``source.dbtModel`` to an adapter-compatible source relation.

    Resolution is intentionally independent of transformation candidate, synchronization, and
    execution-evidence registries. The binding's explicit SQL/YAML paths select one ordinary dbt
    model and its enforced physical output contract.

    *dependency_paths*, when the caller has already resolved the model's transitive SQL
    closure via :func:`resolve_dbt_model_dependency_paths`, skips repeating that walk here
    purely for its validation side effect.
    """

    model_ref = binding.source.dbt_model
    if model_ref is None:
        raise _failure(
            binding,
            "dbt-source.missing",
            "binding does not select source.dbtModel",
            "name",
        )
    root = Path(hub_root).resolve()
    sql_path = _resolve_authored_path(
        binding,
        root,
        model_ref.sql_path,
        suffixes=frozenset({".sql"}),
        pointer="sqlPath",
    )
    if dependency_paths is None:
        _dependency_sql_paths(binding, root, sql_path)
    contract_path = _resolve_authored_path(
        binding,
        root,
        model_ref.contract_path,
        suffixes=frozenset({".yml", ".yaml"}),
        pointer="contractPath",
    )
    if sql_path.stem != model_ref.name:
        raise _failure(
            binding,
            "dbt-source.model-unresolved",
            f"dbt sqlPath must name selected model {model_ref.name!r}",
            "sqlPath",
        )

    model = _selected_model(binding, _load_contract(binding, contract_path))
    kairos = _kairos_meta(binding, model)
    # Issue #397: this is the same meta.kairos.supported_adapters rule dbt_contracts.py's
    # stricter, bundle-time _parse_contract() already enforces (SUPPORTED_ADAPTERS
    # imported from there to avoid drift) — checking it here at compile time closes the
    # gap where a malformed contract passed `compile --check`/`--emit` and was only
    # caught later, by a separate tool, during `generate`/bundling.
    supported_adapters = kairos.get("supported_adapters")
    if (
        not isinstance(supported_adapters, list)
        or not supported_adapters
        or any(not isinstance(item, str) or not item.strip() for item in supported_adapters)
        or len(set(supported_adapters)) != len(supported_adapters)
        or not set(supported_adapters) <= SUPPORTED_ADAPTERS
    ):
        raise _failure(
            binding,
            "dbt-source.contract-invalid",
            "selected dbt model must declare a non-empty, valid "
            f"meta.kairos.supported_adapters (one or more of {sorted(SUPPORTED_ADAPTERS)})",
            "contractPath",
        )
    grain = kairos.get("grain")
    grain_key = kairos.get("grain_key")
    if not isinstance(grain, str) or not grain.strip():
        raise _failure(
            binding,
            "dbt-source.grain-invalid",
            "selected dbt model must declare a non-empty meta.kairos.grain",
            "contractPath",
        )
    if (
        not isinstance(grain_key, list)
        or not grain_key
        or any(not isinstance(item, str) or not item for item in grain_key)
        or len(set(grain_key)) != len(grain_key)
    ):
        raise _failure(
            binding,
            "dbt-source.grain-invalid",
            "selected dbt model must declare a unique, non-empty meta.kairos.grain_key",
            "contractPath",
        )
    contracted_key = tuple(grain_key)
    columns = _contract_columns(binding, model, contracted_key)
    names = {column.name for column in columns}
    if not set(contracted_key) <= names:
        raise _failure(
            binding,
            "dbt-source.grain-invalid",
            "dbt grain_key must contain only contracted output columns",
            "contractPath",
        )
    if binding.grain.columns != contracted_key:
        raise _failure(
            binding,
            "dbt-source.grain-mismatch",
            "EntityBinding grain columns must exactly match the contracted dbt grain_key",
            "contractPath",
        )
    if binding.identity.source_key != contracted_key:
        raise _failure(
            binding,
            "dbt-source.identity-mismatch",
            "EntityBinding sourceKey must exactly match the contracted dbt grain_key",
            "contractPath",
        )

    virtual_iri = kairos.get("virtual_source_iri")
    if not _is_absolute_http_iri(virtual_iri):
        raise _failure(
            binding,
            "dbt-source.contract-invalid",
            "selected dbt model must declare an absolute HTTP(S) virtual_source_iri",
            "contractPath",
        )
    # Issue #503: target_class was declared by the contract, written as a
    # `<CONFIRM_TARGET_CLASS>` sentinel by `scaffold-staging`, and required by
    # `dbt_contracts.py`'s bundle-time `_parse_contract` -- but never read here, so an
    # unconfirmed sentinel (or a plain typo) sailed through `compile --check`. Shape is
    # enforced here; the binding-vs-contract *identity* comparison needs a resolved class
    # URI and therefore lives in `validate_contract_target_class` below.
    target_class = kairos.get("target_class")
    if not _is_absolute_http_iri(target_class):
        raise _failure(
            binding,
            "dbt-source.contract-invalid",
            "selected dbt model must declare an absolute HTTP(S) meta.kairos.target_class",
            "contractPath",
        )
    assert isinstance(target_class, str)
    return ResolvedRelation(
        ref=model_ref.name,
        uri=virtual_iri,
        system_label="dbt",
        table_name=model_ref.name,
        columns=columns,
        database="",
        schema="",
        connection_type="dbt",
        system_uri=f"{virtual_iri}/source-system",
        target_class=target_class,
    )


def contract_target_class(binding: EntityBinding, hub_root: str | Path) -> str:
    """Return the selected dbt model's ``meta.kairos.target_class``.

    Re-reads the authoritative contract through the same helpers
    :func:`resolve_dbt_model_source` uses, so the two can never disagree about *which*
    model a binding selects. Callers are expected to have already run
    :func:`resolve_dbt_model_source` (the compiler does, immediately before), which is what
    guarantees the value is present and IRI-shaped -- the shape check is repeated here only
    so this function is safe to call standalone.
    """

    model_ref = binding.source.dbt_model
    if model_ref is None:
        raise _failure(
            binding,
            "dbt-source.missing",
            "binding does not select source.dbtModel",
            "name",
        )
    contract_path = _resolve_authored_path(
        binding,
        Path(hub_root).resolve(),
        model_ref.contract_path,
        suffixes=frozenset({".yml", ".yaml"}),
        pointer="contractPath",
    )
    kairos = _kairos_meta(binding, _selected_model(binding, _load_contract(binding, contract_path)))
    target_class = kairos.get("target_class")
    if not _is_absolute_http_iri(target_class):
        raise _failure(
            binding,
            "dbt-source.contract-invalid",
            "selected dbt model must declare an absolute HTTP(S) meta.kairos.target_class",
            "contractPath",
        )
    assert isinstance(target_class, str)
    return target_class


def check_target_class_match(
    binding: EntityBinding, declared_target_class: str, resolved_class_uri: str
) -> None:
    """Raise when *declared_target_class* disagrees with the binding's resolved class.

    Issue #503: the binding's ``target.class`` token and the contract's
    ``meta.kairos.target_class`` IRI are two independent declarations of the same fact, and
    nothing compared them -- a contracted model could claim to produce ``bsp_fin:RevenueLine``
    while the binding mapped its columns onto ``bsp_fin:InvoiceLine``, and the drift only
    surfaced as wrong data. Split out of :func:`validate_contract_target_class` so a caller
    that already has ``declared_target_class`` (e.g. from a ``ResolvedRelation`` computed
    earlier in the same compile) can compare without re-reading the contract file.
    """

    if declared_target_class != resolved_class_uri:
        raise _failure(
            binding,
            "dbt-source.target-mismatch",
            (
                f"EntityBinding target class {resolved_class_uri!r} does not match the "
                f"contracted dbt meta.kairos.target_class {declared_target_class!r}"
            ),
            "contractPath",
        )


def validate_contract_target_class(
    binding: EntityBinding, hub_root: str | Path, resolved_class_uri: str
) -> None:
    """Raise when the binding's resolved target class disagrees with the dbt contract.

    *resolved_class_uri* is the binding's ``target.class`` after prefix/scope resolution,
    which is why this cannot live inside :func:`resolve_dbt_model_source` -- that runs before
    the compiler has a ``ResolutionContext``.
    """

    declared = contract_target_class(binding, hub_root)
    check_target_class_match(binding, declared, resolved_class_uri)
