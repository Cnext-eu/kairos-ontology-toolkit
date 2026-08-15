# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Standalone lint for the hand-authored intermediate dbt layer (issue #504).

The toolkit generates Silver dbt models from the ``CompilePlan``, but the *hand-authored*
models under ``integration/transforms/dbt/models/`` -- ``stg_<source>__<entity>``,
``int_merged__<entity>``, ``int_<source>__<entity>`` -- had no validation of their own. Their
``meta.kairos`` contract was only ever checked indirectly, when an ``EntityBinding`` referenced
one via ``source.dbtModel`` **and** ``compile --check`` ran for that domain. The authoring flow
is "author stg_* -> author int_merged__ -> author properties YAML -> return to the mapping
skill -> bind", and there was nothing to run between the third and fourth steps: a wrong
``grain_key`` surfaced only once a binding existed to contradict it, potentially much later.

This module is that missing gate. It is deliberately **offline**: no dbt install, no adapter,
no warehouse connection -- distinguishing it from ``core/dbt_validation.py``, which shells out
to real ``dbt`` against the *emitted* project under ``ontology-hub-publish/medallion/dbt``.
The two commands validate different trees at different lifecycle stages and neither subsumes
the other.

Leaf module: no :mod:`kairos_ontology.cli` imports, so it stays unit-testable without Click
(the same rule :mod:`kairos_ontology.core.command_outcome` documents).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .dbt_contracts import DbtContractError, DbtContractModel, scan_dbt_contracts
from .hub_utils import is_scaffold_placeholder_text

SCHEMA_VERSION = 1

#: "Does this class IRI exist in the hub's ontology import closure?" -- injected by the CLI
#: so this module never depends on the ontology loader (see :func:`run_dbt_contract_lint`).
ClassResolver = Callable[[str], bool]

#: Prefix for per-source staging models. A stage is internal to one hand-authored transform
#: and is never itself a bindable virtual source, so it must NOT carry a ``meta.kairos`` block
#: (``scaffold-staging`` deliberately writes stages without one).
_STAGE_PREFIX = "stg_"
#: Prefixes for intermediate models, which *are* bindable and therefore must carry one.
_INTERMEDIATE_PREFIXES = ("int_merged__", "int_")

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True)
class DbtContractFinding:
    """One lint verdict about one dbt properties document."""

    code: str
    severity: str
    message: str
    #: Hub-relative POSIX path when resolvable, else the absolute path as a string.
    path: str
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "path": self.path,
            "model": self.model,
        }


@dataclass(frozen=True)
class DbtContractLintReport:
    """Every finding, plus what was actually scanned."""

    findings: tuple[DbtContractFinding, ...] = ()
    contracted_models: tuple[str, ...] = ()
    scanned_documents: int = 0
    #: False when ``integration/transforms/dbt/models`` does not exist at all -- an empty
    #: report then means "nothing authored yet", not "everything is clean".
    transforms_present: bool = True
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def errors(self) -> tuple[DbtContractFinding, ...]:
        return tuple(f for f in self.findings if f.severity == SEVERITY_ERROR)

    @property
    def warnings(self) -> tuple[DbtContractFinding, ...]:
        return tuple(f for f in self.findings if f.severity == SEVERITY_WARNING)

    @property
    def passed(self) -> bool:
        """Warnings never fail the command; only errors do.

        Items 7/8 (a stage carrying ``meta.kairos``, an intermediate missing one) and the
        unreferenced-model check are naming/wiring advice about a tree the author may be
        mid-way through building, so they must not block. Everything else is a broken
        contract that will fail at bind time anyway, reported earlier.
        """
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "passed": self.passed,
            "transforms_present": self.transforms_present,
            "scanned_documents": self.scanned_documents,
            "contracted_models": list(self.contracted_models),
            "findings": [finding.to_dict() for finding in self.findings],
            "notes": list(self.notes),
        }


def _relative(path: Path, hub_root: Path) -> str:
    try:
        return path.resolve().relative_to(hub_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _bound_dbt_model_names(hub_root: Path) -> set[str]:
    """Names every ``EntityBinding`` selects via ``source.dbtModel.name``.

    Read with a plain YAML load rather than the compiler's ``load_entity_binding``: this is an
    advisory cross-reference, and a binding that fails to load is ``compile --check``'s problem
    to report, not this lint's. An unreadable binding is simply skipped.
    """

    names: set[str] = set()
    bindings_dir = hub_root / "integration" / "bindings"
    if not bindings_dir.is_dir():
        return names
    for path in sorted(bindings_dir.glob("*.binding.yaml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
        if not isinstance(document, dict):
            continue
        source = document.get("source")
        dbt_model = source.get("dbtModel") if isinstance(source, dict) else None
        name = dbt_model.get("name") if isinstance(dbt_model, dict) else None
        if isinstance(name, str) and name.strip():
            names.add(name.strip())
    return names


def _sentinel_fields(kairos_meta: Any) -> tuple[str, ...]:
    """Return the ``meta.kairos`` fields still holding a ``<CONFIRM_...>`` scaffold sentinel.

    Reads the **raw, pre-parse** block on purpose. ``scaffold-staging`` writes an
    ``int_merged__`` contract as a sentinel skeleton so a human must confirm the irreducible
    judgment -- but every one of those sentinels is *also* structurally invalid
    (``<CONFIRM_TARGET_CLASS>`` is not an IRI, ``<CONFIRM_SUPPORTED_ADAPTER>`` is not a known
    adapter, ``<CONFIRM_GRAIN_KEY_COLUMN>`` names no contracted column), so parsing rejects it
    before anything can notice it *is* a sentinel. Checking post-parse would make this whole
    function unreachable and leave the author with "your IRI is invalid" when the real answer
    is "you have not filled in the scaffold yet".
    """

    if not isinstance(kairos_meta, dict):
        return ()
    unconfirmed = [
        key
        for key in ("target_class", "virtual_source_iri", "grain")
        if is_scaffold_placeholder_text(kairos_meta.get(key))
    ]
    for key in ("grain_key", "supported_adapters"):
        value = kairos_meta.get(key)
        if isinstance(value, list):
            unconfirmed.extend(
                f"{key}[{index}]"
                for index, item in enumerate(value)
                if is_scaffold_placeholder_text(item)
            )
    return tuple(unconfirmed)


def run_dbt_contract_lint(
    hub_root: Path,
    *,
    resolve_target_class: ClassResolver | None = None,
) -> DbtContractLintReport:
    """Lint every hand-authored dbt properties document under the hub's transforms tree.

    *resolve_target_class* answers "does this class IRI exist in the hub's ontology import
    closure?". It is injected rather than imported so this module stays free of the ontology
    loader's cost and of its failure modes -- a hub whose ontologies do not parse should still
    get the structural half of this lint. ``None`` skips the check and records a note, so an
    empty findings list is never mistaken for "target classes verified".
    """

    hub_root = Path(hub_root)
    transforms_dir = hub_root / "integration" / "transforms" / "dbt"
    findings: list[DbtContractFinding] = []
    notes: list[str] = []

    if not (transforms_dir / "models").is_dir():
        return DbtContractLintReport(
            transforms_present=False,
            notes=(
                f"no hand-authored dbt models directory at "
                f"{_relative(transforms_dir / 'models', hub_root)}; nothing to lint.",
            ),
        )

    try:
        scan = scan_dbt_contracts(transforms_dir, hub_root)
    except DbtContractError as exc:
        return DbtContractLintReport(
            findings=(
                DbtContractFinding(
                    code="dbt-contract.transforms-unresolved",
                    severity=SEVERITY_ERROR,
                    message=str(exc),
                    path=_relative(transforms_dir, hub_root),
                ),
            ),
        )

    # --- Unconfirmed scaffold sentinels ----------------------------------------------------
    # Reported first, and from the *raw* inventory, because every sentinel is also
    # structurally invalid -- so this has to pre-empt the parse error below rather than
    # duplicate it. One root cause, one finding, and the actionable message wins.
    sentinel_models: set[str] = set()
    for stub in scan.inventory:
        unconfirmed = _sentinel_fields(stub.kairos_meta)
        if not unconfirmed:
            continue
        sentinel_models.add(stub.name)
        findings.append(
            DbtContractFinding(
                code="dbt-contract.unconfirmed-sentinel",
                severity=SEVERITY_ERROR,
                message=(
                    f"meta.kairos still holds scaffold placeholder(s) for "
                    f"{', '.join(unconfirmed)}; replace them with the confirmed values before "
                    "binding this model"
                ),
                path=_relative(stub.properties_path, hub_root),
                model=stub.name,
            )
        )

    # --- Contract parse failures (meta.kairos completeness, grain_key subset of columns,
    # --- config.contract.enforced, approved packages/macros, unique SQL pairing) -----------
    # #504 items 2, 4 and 6 are exactly what dbt_contracts._parse_contract already enforces;
    # the lint's job is to surface all of them at once rather than the first.
    for issue in scan.errors:
        if issue.model and issue.model in sentinel_models:
            continue  # already reported, more usefully, as an unconfirmed sentinel
        findings.append(
            DbtContractFinding(
                code="dbt-contract.invalid",
                severity=SEVERITY_ERROR,
                message=issue.message,
                path=_relative(issue.path, hub_root),
                model=issue.model or None,
            )
        )

    # --- item 5: virtual_source_iri uniqueness across every contracted model ---------------
    # The hub-wide half of issue #503. `compile --check` can only ever see one domain's
    # bindings, so this is the authoritative check and the compiler's message points here.
    by_iri: dict[str, list[DbtContractModel]] = {}
    for model in scan.models:
        by_iri.setdefault(model.virtual_source_iri, []).append(model)
    for iri, claimants in sorted(by_iri.items()):
        if len(claimants) < 2:
            continue
        names = ", ".join(sorted(model.name for model in claimants))
        for model in claimants:
            findings.append(
                DbtContractFinding(
                    code="dbt-contract.virtual-source-duplicate",
                    severity=SEVERITY_ERROR,
                    message=(
                        f"virtual_source_iri {iri!r} is declared by {len(claimants)} contracted "
                        f"models ({names}); it identifies one model's output, so each needs "
                        "its own."
                    ),
                    path=_relative(model.properties_path, hub_root),
                    model=model.name,
                )
            )

    # --- item 3: target_class resolves in the hub's ontology import closure ----------------
    if resolve_target_class is None:
        notes.append(
            "target_class resolution was not run (no ontology closure available); "
            "meta.kairos.target_class was checked for IRI shape only."
        )
    else:
        for model in scan.models:
            if is_scaffold_placeholder_text(model.target_class):
                continue  # reported as an unconfirmed sentinel below, not as a bad IRI
            if not resolve_target_class(model.target_class):
                findings.append(
                    DbtContractFinding(
                        code="dbt-contract.target-class-unresolved",
                        severity=SEVERITY_ERROR,
                        message=(
                            f"meta.kairos.target_class {model.target_class!r} does not resolve "
                            "to a class in the hub's ontology import closure"
                        ),
                        path=_relative(model.properties_path, hub_root),
                        model=model.name,
                    )
                )

    # --- items 7 and 8: layering conventions (warnings) -------------------------------------
    for stub in scan.inventory:
        if stub.name.startswith(_STAGE_PREFIX) and stub.has_kairos_meta:
            findings.append(
                DbtContractFinding(
                    code="dbt-contract.stage-declares-kairos-meta",
                    severity=SEVERITY_WARNING,
                    message=(
                        f"staging model {stub.name!r} declares a meta.kairos block; a stage is "
                        "internal to one hand-authored transform and is never a bindable "
                        "virtual source. Move the block to the int_ model it feeds."
                    ),
                    path=_relative(stub.properties_path, hub_root),
                    model=stub.name,
                )
            )
        is_intermediate = any(
            stub.name.startswith(prefix) for prefix in _INTERMEDIATE_PREFIXES
        ) and not stub.name.startswith(_STAGE_PREFIX)
        if is_intermediate and not stub.has_kairos_meta:
            findings.append(
                DbtContractFinding(
                    code="dbt-contract.intermediate-missing-kairos-meta",
                    severity=SEVERITY_WARNING,
                    message=(
                        f"intermediate model {stub.name!r} has no meta.kairos block, so no "
                        "EntityBinding can select it via source.dbtModel. Add one, or rename "
                        "it to stg_* if it is an internal stage."
                    ),
                    path=_relative(stub.properties_path, hub_root),
                    model=stub.name,
                )
            )

    # --- unreferenced contracted models (warning) ------------------------------------------
    bound = _bound_dbt_model_names(hub_root)
    for model in scan.models:
        if model.name not in bound:
            findings.append(
                DbtContractFinding(
                    code="dbt-contract.model-unbound",
                    severity=SEVERITY_WARNING,
                    message=(
                        f"contracted model {model.name!r} is not selected by any EntityBinding's "
                        "source.dbtModel; its contract is validated but nothing consumes it yet."
                    ),
                    path=_relative(model.properties_path, hub_root),
                    model=model.name,
                )
            )

    findings.sort(key=lambda item: (item.severity != SEVERITY_ERROR, item.path, item.code))
    return DbtContractLintReport(
        findings=tuple(findings),
        contracted_models=tuple(model.name for model in scan.models),
        scanned_documents=len({stub.properties_path for stub in scan.inventory}),
        notes=tuple(notes),
    )
