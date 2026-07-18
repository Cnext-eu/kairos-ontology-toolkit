# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Read-only assembly of governed custom dbt transformation artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping, Sequence

import yaml

from kairos_ontology.core.dbt_contracts import (
    APPROVED_DBT_PACKAGES,
    DbtContractError,
    DbtContractModel,
)

_MACRO_DEFINITION_RE = re.compile(
    r"{%-?\s*macro\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.IGNORECASE,
)
_REF_RE = re.compile(
    r"\bref\s*\(\s*['\"][^'\"]+['\"]\s*,\s*['\"]([^'\"]+)['\"]"
    r"|\bref\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_CUSTOM_MACRO_RE = re.compile(r"^(?!kairos_)[a-z][a-z0-9_]*__[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class DbtBundle:
    """Validated custom artifacts ready to merge into a generated dbt project."""

    artifacts: Mapping[str, str]
    model_names: frozenset[str]
    macro_names: frozenset[str]
    packages: tuple[str, ...]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DbtContractError(f"{path}: could not read custom dbt artifact: {exc}") from exc


def _artifact_key(path: Path, transforms_dir: Path) -> str:
    return PurePosixPath(path.relative_to(transforms_dir)).as_posix()


def _render_packages(package_names: Sequence[str]) -> str:
    document = {
        "packages": [
            {
                "package": package,
                "version": list(APPROVED_DBT_PACKAGES[package]),
            }
            for package in package_names
        ]
    }
    return yaml.safe_dump(document, sort_keys=False)


def assemble_dbt_bundle(
    transforms_dir: Path,
    contracts: Sequence[DbtContractModel],
    *,
    generated_artifacts: Sequence[str] = (),
    known_resources: Sequence[str] = (),
) -> DbtBundle:
    """Validate and assemble custom dbt files without writing output."""

    transforms_dir = Path(transforms_dir).resolve()
    if not transforms_dir.is_dir():
        raise DbtContractError(f"{transforms_dir}: transforms directory does not exist")

    paths = sorted(
        path
        for directory in ("models", "macros", "tests")
        for path in (transforms_dir / directory).rglob("*")
        if path.is_file()
    )
    artifacts: dict[str, str] = {}
    generated_keys = {PurePosixPath(path).as_posix().casefold() for path in generated_artifacts}
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_relative_to(transforms_dir):
            raise DbtContractError(f"{path}: symlink escapes the custom dbt transforms directory")
        key = _artifact_key(path, transforms_dir)
        if key.casefold() in generated_keys:
            raise DbtContractError(
                f"{path}: custom artifact collides with generated artifact {key!r}"
            )
        if key.casefold() in {existing.casefold() for existing in artifacts}:
            raise DbtContractError(f"{path}: duplicate case-insensitive artifact path {key!r}")
        artifacts[key] = _read_text(path)

    sql_models: dict[str, Path] = {}
    for path in (transforms_dir / "models").rglob("*.sql"):
        if path.stem in sql_models:
            raise DbtContractError(
                f"{path}: duplicate dbt model name {path.stem!r}; "
                f"first declared in {sql_models[path.stem]}"
            )
        sql_models[path.stem] = path
    contract_names = {contract.name for contract in contracts}
    uncontracted_models = sorted(sql_models.keys() - contract_names)
    if uncontracted_models:
        raise DbtContractError(
            f"custom dbt models require meta.kairos contracts: {uncontracted_models}"
        )
    generated_model_names = {
        PurePosixPath(path).stem
        for path in generated_artifacts
        if PurePosixPath(path).parts[:1] == ("models",) and PurePosixPath(path).suffix == ".sql"
    }
    model_collisions = sorted(sql_models.keys() & generated_model_names)
    if model_collisions:
        raise DbtContractError(
            f"custom dbt model names collide with generated resources: {model_collisions}"
        )

    macro_names: dict[str, Path] = {}
    for path in (transforms_dir / "macros").rglob("*.sql"):
        content = artifacts[_artifact_key(path, transforms_dir)]
        definitions = _MACRO_DEFINITION_RE.findall(content)
        if not definitions:
            raise DbtContractError(f"{path}: macro file does not define a dbt macro")
        for name in definitions:
            if not _CUSTOM_MACRO_RE.fullmatch(name):
                raise DbtContractError(
                    f"{path}: custom macro {name!r} must be named "
                    "<hub-or-domain>__<macro-name> and cannot use the kairos_ prefix"
                )
            if name in macro_names:
                raise DbtContractError(
                    f"{path}: duplicate custom macro {name!r}; first defined in {macro_names[name]}"
                )
            macro_names[name] = path

    required_macros = {macro for contract in contracts for macro in contract.required_macros}
    missing_macros = sorted(required_macros - macro_names.keys())
    if missing_macros:
        raise DbtContractError(f"required custom macros are not defined: {missing_macros}")

    known = set(sql_models) | set(known_resources)
    for path in (transforms_dir / "models").rglob("*.sql"):
        content = artifacts[_artifact_key(path, transforms_dir)]
        references = {first or second for first, second in _REF_RE.findall(content)}
        missing_refs = sorted(references - known)
        if missing_refs:
            raise DbtContractError(f"{path}: unresolved dbt ref targets {missing_refs}")

    packages = tuple(
        sorted({package for contract in contracts for package in contract.required_packages})
    )
    if packages:
        if "packages.yml".casefold() not in generated_keys:
            artifacts["packages.yml"] = _render_packages(packages)

    return DbtBundle(
        artifacts=MappingProxyType(dict(sorted(artifacts.items()))),
        model_names=frozenset(sql_models),
        macro_names=frozenset(macro_names),
        packages=packages,
    )
