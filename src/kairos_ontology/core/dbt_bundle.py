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

from kairos_ontology.core.compiler.dbt_source import strip_jinja_comments
from kairos_ontology.core.dbt_contracts import (
    APPROVED_DBT_PACKAGES,
    DbtContractError,
    DbtContractModel,
)

_MACRO_DEFINITION_RE = re.compile(
    r"{%-?\s*macro\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.IGNORECASE,
)
#: Every ``ref()`` target this bundle's fail-closed closure validation must be able to
#: resolve. Deliberately broader than the compiler's ``dbt_source.REF_RE`` and NOT merged
#: with it (#586 stage b): that one is a *selection* rule that must match dbt's own
#: resolution exactly (case-sensitive, because Jinja is -- ``REF('x')`` is an
#: undefined-function error in dbt, not a ref -- and single-argument), while this one is a
#: *validation* rule and is intentionally over-broad, accepting IGNORECASE spellings and
#: dbt's two-argument package form ``ref('pkg', 'model')``. Merging in either direction
#: loses something real: IGNORECASE in the selection walk would invent phantom dependencies,
#: the package form there would demand a cross-package target exist as an authored hub file,
#: and dropping either here would relax a fail-closed check. What the two DO share is
#: :func:`strip_jinja_comments`, so neither sees a commented-out call.
_REF_RE = re.compile(
    r"\bref\s*\(\s*['\"][^'\"]+['\"]\s*,\s*['\"]([^'\"]+)['\"]"
    r"|\bref\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_SOURCE_RE = re.compile(
    r"\bsource\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"][^'\"]+['\"]\s*\)",
    re.IGNORECASE,
)
_GROUP_RE = re.compile(r"\bgroup\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
_CUSTOM_MACRO_RE = re.compile(r"^(?!kairos_)[a-z][a-z0-9_]*__[a-z][a-z0-9_]*$")
#: The only file shapes ``seeds/`` contributes: dbt seed data, plus its optional sibling
#: column-docs properties document (#586 stage b).
_SEED_SUFFIXES = frozenset({".csv", ".yml", ".yaml"})
_PROPERTIES_SUFFIXES = frozenset({".yml", ".yaml"})
_CUSTOM_MACRO_CALL_RE = re.compile(
    r"\b((?!kairos_)[a-z][a-z0-9_]*__[a-z][a-z0-9_]*)\s*\(",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DbtBundle:
    """Validated custom artifacts ready to merge into a generated dbt project."""

    artifacts: Mapping[str, str]
    model_names: frozenset[str]
    macro_names: frozenset[str]
    packages: tuple[str, ...]
    #: Stems of the authored seed CSVs carried in :attr:`artifacts` (#586 stage b). These
    #: are valid ``ref()`` targets, so they belong to the same dbt name namespace as
    #: :attr:`model_names` -- a stem in both is rejected during assembly.
    seed_names: frozenset[str] = frozenset()


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


def _references(content: str) -> set[str]:
    return {first or second for first, second in _REF_RE.findall(strip_jinja_comments(content))}


def _source_names(content: str) -> set[str]:
    return set(_SOURCE_RE.findall(strip_jinja_comments(content)))


def _group_names(content: str) -> set[str]:
    return set(_GROUP_RE.findall(content))


def _scoped_macro_closure(
    required_macros: set[str],
    macro_artifacts: Mapping[str, str],
) -> tuple[dict[str, str], set[str]]:
    selected: dict[str, str] = {}
    required = set(required_macros)
    while True:
        defined = {
            name for content in selected.values() for name in _MACRO_DEFINITION_RE.findall(content)
        }
        unresolved = required - defined
        additions = {
            key: content
            for key, content in macro_artifacts.items()
            if key not in selected
            and unresolved.intersection(_MACRO_DEFINITION_RE.findall(content))
        }
        if not additions:
            return selected, required
        selected.update(additions)
        required.update(
            call
            for content in additions.values()
            for call in _CUSTOM_MACRO_CALL_RE.findall(content)
        )


def _selected_group_names(content: str, model_names: set[str]) -> set[str]:
    try:
        document = yaml.safe_load(content)
    except yaml.YAMLError:
        return set()
    if not isinstance(document, dict):
        return set()
    groups: set[str] = set()
    for model in document.get("models", []):
        if not isinstance(model, dict) or model.get("name") not in model_names:
            continue
        group = model.get("group")
        config = model.get("config")
        if group is None and isinstance(config, dict):
            group = config.get("group")
        if isinstance(group, str) and group:
            groups.add(group)
    return groups


def _filter_properties(
    content: str,
    path: Path,
    model_names: set[str],
    test_names: set[str],
    source_names: set[str] | None = None,
    group_names: set[str] | None = None,
    seed_names: set[str] | None = None,
) -> str | None:
    try:
        document = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise DbtContractError(f"{path}: could not parse custom dbt properties: {exc}") from exc
    if not isinstance(document, dict):
        raise DbtContractError(f"{path}: custom dbt properties document must be a mapping")

    models = [
        model
        for model in document.get("models", [])
        if isinstance(model, dict) and model.get("name") in model_names
    ]
    unit_tests = [
        test
        for test in document.get("unit_tests", [])
        if isinstance(test, dict)
        and (test.get("model") in model_names or test.get("name") in test_names)
    ]
    sources = [
        source
        for source in document.get("sources", [])
        if isinstance(source, dict) and source.get("name") in (source_names or set())
    ]
    groups = [
        group
        for group in document.get("groups", [])
        if isinstance(group, dict) and group.get("name") in (group_names or set())
    ]
    # #586 stage b: without `seeds` on this allow-list a scoped bundle silently dropped a
    # seed's whole column-docs document, emitting an undocumented seed with no warning.
    seeds = [
        seed
        for seed in document.get("seeds", [])
        if isinstance(seed, dict) and seed.get("name") in (seed_names or set())
    ]
    if not models and not unit_tests and not sources and not groups and not seeds:
        return None

    filtered: dict[str, object] = {"version": document.get("version", 2)}
    if models:
        filtered["models"] = models
    if unit_tests:
        filtered["unit_tests"] = unit_tests
    if sources:
        filtered["sources"] = sources
    if groups:
        filtered["groups"] = groups
    if seeds:
        filtered["seeds"] = seeds
    return yaml.safe_dump(filtered, sort_keys=False)


def assemble_dbt_bundle(
    transforms_dir: Path,
    contracts: Sequence[DbtContractModel],
    *,
    generated_artifacts: Sequence[str] = (),
    known_resources: Sequence[str] = (),
    active_contract_names: Sequence[str] | None = None,
) -> DbtBundle:
    """Validate and assemble the selected custom dbt contract closure without writing output.

    ``active_contract_names=None`` preserves full-bundle behavior. An explicit sequence
    scopes assembly to those roots plus custom models reached transitively through ``ref()``.
    """

    transforms_dir = Path(transforms_dir).resolve()
    if not transforms_dir.is_dir():
        raise DbtContractError(f"{transforms_dir}: transforms directory does not exist")

    # #586 stage b: `seeds` joins this walk. Without it an authored seed CSV never entered
    # `available_artifacts`, so its stem was absent from `known` below and an authored
    # model's `{{ ref('country_codes') }}` raised "unresolved dbt ref targets" -- which
    # projector.py turns into a fatal "dbt assembly failed" for the whole dbt target. The
    # net effect was a hub that `compile --emit` built and `generate` refused to.
    paths = sorted(
        path
        for directory in ("models", "macros", "tests")
        for path in (transforms_dir / directory).rglob("*")
        if path.is_file()
    )
    # Only dbt's own seed shapes are carried: a stray README or .gitkeep beside a seed is
    # not a dbt artifact and must not be read as UTF-8 text or emitted.
    paths.extend(
        sorted(
            path
            for path in (transforms_dir / "seeds").rglob("*")
            if path.is_file() and path.suffix.lower() in _SEED_SUFFIXES
        )
    )
    available_artifacts: dict[str, str] = {}
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_relative_to(transforms_dir):
            raise DbtContractError(f"{path}: symlink escapes the custom dbt transforms directory")
        key = _artifact_key(path, transforms_dir)
        if key.casefold() in {existing.casefold() for existing in available_artifacts}:
            raise DbtContractError(f"{path}: duplicate case-insensitive artifact path {key!r}")
        available_artifacts[key] = _read_text(path)
    available_macro_artifacts = {
        key: content
        for key, content in available_artifacts.items()
        if PurePosixPath(key).parts[:1] == ("macros",) and PurePosixPath(key).suffix == ".sql"
    }

    sql_models: dict[str, Path] = {}
    for path in (transforms_dir / "models").rglob("*.sql"):
        if path.stem in sql_models:
            raise DbtContractError(
                f"{path}: duplicate dbt model name {path.stem!r}; "
                f"first declared in {sql_models[path.stem]}"
            )
        sql_models[path.stem] = path
    # Authored seeds, indexed by the dbt resource name their stem declares. Duplicates are
    # already rejected by the case-insensitive artifact-path check above.
    seed_csv_keys = {
        PurePosixPath(key).stem: key
        for key in available_artifacts
        if PurePosixPath(key).parts[:1] == ("seeds",) and PurePosixPath(key).suffix == ".csv"
    }
    seed_properties_keys = {
        PurePosixPath(key).stem: key
        for key in available_artifacts
        if PurePosixPath(key).parts[:1] == ("seeds",)
        and PurePosixPath(key).suffix in _PROPERTIES_SUFFIXES
    }
    # dbt resolves ref() in ONE resource namespace, so a stem claimed by both a model and a
    # seed makes the generated project fail to parse. Fail closed here rather than emit it.
    seed_model_collisions = sorted(set(seed_csv_keys) & set(sql_models))
    if seed_model_collisions:
        raise DbtContractError(
            f"authored dbt seed names collide with custom dbt model names: "
            f"{seed_model_collisions}; dbt models and seeds share one ref() namespace"
        )
    contract_registry = {contract.name: contract for contract in contracts}
    if len(contract_registry) != len(contracts):
        raise DbtContractError("custom dbt contracts contain duplicate model names")
    contract_names = set(contract_registry)
    if active_contract_names is None:
        selected_names = set(contract_names)
    else:
        selected_names = set(active_contract_names)
        unknown = sorted(selected_names - contract_names)
        if unknown:
            raise DbtContractError(f"active custom dbt contracts were not discovered: {unknown}")
        while True:
            selected_contracts = tuple(contract_registry[name] for name in sorted(selected_names))
            required_tests = {
                test
                for contract in selected_contracts
                for decision in getattr(contract, "decisions", ())
                for test in decision.verified_by
            }
            required_macros = {
                macro for contract in selected_contracts for macro in contract.required_macros
            }
            dependencies: set[str] = set()
            for name in selected_names:
                sql_path = sql_models.get(name)
                if sql_path is not None:
                    dependencies.update(
                        _references(available_artifacts[_artifact_key(sql_path, transforms_dir)])
                    )
            for path in [
                *(transforms_dir / "models").rglob("*.yml"),
                *(transforms_dir / "models").rglob("*.yaml"),
            ]:
                filtered = _filter_properties(
                    available_artifacts[_artifact_key(path, transforms_dir)],
                    path,
                    selected_names,
                    required_tests,
                )
                if filtered is not None:
                    dependencies.update(_references(filtered))
            for path in (transforms_dir / "tests").rglob("*.sql"):
                content = available_artifacts[_artifact_key(path, transforms_dir)]
                references = _references(content)
                if path.stem in required_tests or references & selected_names:
                    dependencies.update(references)
            selected_macros, _expanded_macros = _scoped_macro_closure(
                required_macros,
                available_macro_artifacts,
            )
            for content in selected_macros.values():
                dependencies.update(_references(content))
            discovered = (dependencies & contract_names) - selected_names
            if not discovered:
                break
            selected_names.update(discovered)

    selected_contracts = tuple(contract_registry[name] for name in sorted(selected_names))
    uncontracted_models = sorted(set(sql_models) - contract_names)
    if uncontracted_models:
        if active_contract_names is None:
            raise DbtContractError(
                f"custom dbt models require meta.kairos contracts: {uncontracted_models}"
            )

    required_tests = {
        test
        for contract in selected_contracts
        for decision in getattr(contract, "decisions", ())
        for test in decision.verified_by
    }
    required_macros = {
        macro for contract in selected_contracts for macro in contract.required_macros
    }
    selected_macro_artifacts, required_macros = _scoped_macro_closure(
        required_macros,
        available_macro_artifacts,
    )
    selected_source_names: set[str] = set()
    selected_group_names: set[str] = set()
    for name in selected_names:
        path = sql_models.get(name)
        if path is not None:
            content = available_artifacts[_artifact_key(path, transforms_dir)]
            selected_source_names.update(_source_names(content))
            selected_group_names.update(_group_names(content))
    for path in [
        *(transforms_dir / "models").rglob("*.yml"),
        *(transforms_dir / "models").rglob("*.yaml"),
    ]:
        content = available_artifacts[_artifact_key(path, transforms_dir)]
        filtered = _filter_properties(
            content,
            path,
            selected_names,
            required_tests,
        )
        if filtered is not None:
            selected_source_names.update(_source_names(filtered))
        selected_group_names.update(_selected_group_names(content, selected_names))
    for path in (transforms_dir / "tests").rglob("*.sql"):
        content = available_artifacts[_artifact_key(path, transforms_dir)]
        references = _references(content)
        if path.stem in required_tests or references & selected_names:
            selected_source_names.update(_source_names(content))
    for content in selected_macro_artifacts.values():
        selected_source_names.update(_source_names(content))
        selected_group_names.update(_group_names(content))
    artifacts: dict[str, str] = {}
    if active_contract_names is None:
        artifacts.update(available_artifacts)
    else:
        for name in selected_names:
            path = sql_models.get(name)
            if path is not None:
                key = _artifact_key(path, transforms_dir)
                artifacts[key] = available_artifacts[key]
        for path in [
            *(transforms_dir / "models").rglob("*.yml"),
            *(transforms_dir / "models").rglob("*.yaml"),
        ]:
            key = _artifact_key(path, transforms_dir)
            filtered = _filter_properties(
                available_artifacts[key],
                path,
                selected_names,
                required_tests,
                selected_source_names,
                selected_group_names,
            )
            if filtered is not None:
                artifacts[key] = filtered
        for path in (transforms_dir / "tests").rglob("*.sql"):
            key = _artifact_key(path, transforms_dir)
            if (
                path.stem in required_tests
                or _references(available_artifacts[key]) & selected_names
            ):
                artifacts[key] = available_artifacts[key]
        # A seed joins a scoped bundle exactly when something already selected refs it.
        # Seeds are data, never Jinja, so they cannot reference anything and one pass
        # suffices -- but macros can ref() a seed, so their bytes are consulted too.
        scoped_references = {
            reference
            for content in (
                *(
                    content
                    for key, content in artifacts.items()
                    if PurePosixPath(key).suffix in {".sql", ".yml", ".yaml"}
                ),
                *selected_macro_artifacts.values(),
            )
            for reference in _references(content)
        }
        for name in sorted(scoped_references & set(seed_csv_keys)):
            csv_key = seed_csv_keys[name]
            artifacts[csv_key] = available_artifacts[csv_key]
            properties_key = seed_properties_keys.get(name)
            if properties_key is None:
                continue
            filtered = _filter_properties(
                available_artifacts[properties_key],
                transforms_dir / Path(properties_key),
                set(),
                set(),
                seed_names={name},
            )
            if filtered is not None:
                artifacts[properties_key] = filtered

    generated_keys = {PurePosixPath(path).as_posix().casefold() for path in generated_artifacts}
    for key in artifacts:
        if key.casefold() in generated_keys:
            raise DbtContractError(
                f"{transforms_dir / Path(key)}: custom artifact collides with "
                f"generated artifact {key!r}"
            )
    generated_model_names = {
        PurePosixPath(path).stem
        for path in generated_artifacts
        if PurePosixPath(path).parts[:1] == ("models",) and PurePosixPath(path).suffix == ".sql"
    }
    # Only the seeds actually carried in this bundle are valid ref() targets: a scoped
    # bundle must not certify a ref() to a seed it did not emit.
    seed_names = {
        PurePosixPath(key).stem
        for key in artifacts
        if PurePosixPath(key).parts[:1] == ("seeds",) and PurePosixPath(key).suffix == ".csv"
    }
    model_collisions = sorted((selected_names | seed_names) & generated_model_names)
    if model_collisions:
        raise DbtContractError(
            f"custom dbt model names collide with generated resources: {model_collisions}"
        )

    macro_names: dict[str, Path] = {}
    macro_artifacts = (
        available_macro_artifacts if active_contract_names is None else selected_macro_artifacts
    )
    for key, content in macro_artifacts.items():
        path = transforms_dir / Path(key)
        definitions = _MACRO_DEFINITION_RE.findall(content)
        if not definitions:
            raise DbtContractError(f"{path}: macro file does not define a dbt macro")
        artifacts[key] = content
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

    missing_macros = sorted(required_macros - macro_names.keys())
    if missing_macros:
        raise DbtContractError(f"required custom macros are not defined: {missing_macros}")

    known = selected_names | generated_model_names | seed_names | set(known_resources)
    for key, content in artifacts.items():
        path = PurePosixPath(key)
        if path.suffix not in {".sql", ".yml", ".yaml"}:
            continue
        references = _references(content)
        missing_refs = sorted(references - known)
        if missing_refs:
            raise DbtContractError(
                f"{transforms_dir / Path(key)}: unresolved dbt ref targets {missing_refs}"
            )

    packages = tuple(
        sorted(
            {package for contract in selected_contracts for package in contract.required_packages}
        )
    )
    if packages:
        if "packages.yml".casefold() not in generated_keys:
            artifacts["packages.yml"] = _render_packages(packages)

    return DbtBundle(
        artifacts=MappingProxyType(dict(sorted(artifacts.items()))),
        model_names=frozenset(selected_names),
        macro_names=frozenset(macro_names),
        packages=packages,
        seed_names=frozenset(seed_names),
    )
