# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""JSON-Schema validation of the emitted Fabric package files (issue #623).

The TOM SDK gate beside this one (:mod:`.tmdl_validate`) reads only the TMDL tree.
Everything Power BI Desktop and Fabric look at *before* the model -- ``.pbip``,
``definition.pbir``, ``definition.pbism``, ``.platform``, and the PBIR report JSON --
went unchecked, and the schema URLs baked into those files were string literals that
nothing ever dereferenced. A project could therefore pass every local gate and still
be refused on open, which is exactly what #623 reported: the ``.pbip`` carried a
``$schema`` URI that 404s.

**Each document is validated against the schema it declares.** That is the point: a
file claiming a schema it does not satisfy is a defect, and a file declaring a URI we
have never heard of is *also* a defect -- which is how the 404 URI is caught without
anyone having to enumerate correct URIs in a test.

Schemas are vendored under ``fabric_schema/``. Validation never touches the network:
emit runs in CI and on developer machines, and a gate that reaches out is a gate that
fails offline. The published copies these were taken from are byte-identical at the
``$id`` each file records; refreshing them is a deliberate, reviewable act.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

#: Directory holding the vendored Microsoft schemas, keyed by their ``$id``.
_SCHEMA_DIR = Path(__file__).parent / "fabric_schema"

#: Emitted files that are Fabric package metadata. Everything else the Gold projector
#: returns (TMDL, dbt, DDL, DAX, ERD, the Kairos product report) is out of scope --
#: ``<domain>-gold-product.json`` in particular is ours, not Microsoft's.
_PACKAGE_SUFFIXES = (".pbip", ".pbir", ".pbism", ".platform")
_PACKAGE_NAMES = ("report.json", "version.json", "pages.json", "page.json")


@dataclass(frozen=True, slots=True)
class PbipValidationResult:
    """One emitted package file's validation outcome."""

    artifact_path: str
    status: str  # "pass" | "fail"
    message: str


def is_package_artifact(path: str) -> bool:
    """Return whether *path* is a Fabric package file this module validates."""
    name = path.rsplit("/", 1)[-1]
    return name.endswith(_PACKAGE_SUFFIXES) or name in _PACKAGE_NAMES


@lru_cache(maxsize=1)
def _schemas() -> dict[str, dict]:
    """Load the vendored schemas, indexed by their declared ``$id``."""
    loaded: dict[str, dict] = {}
    for path in sorted(_SCHEMA_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        identifier = document.get("$id")
        if identifier:
            loaded[identifier] = document
    return loaded


def _validator(schema: dict):
    """Build a Draft7 validator that resolves refs locally and never over HTTP.

    ``report`` and ``page`` schemas ``$ref`` sibling Microsoft families
    (``filterConfiguration``, ``semanticQuery``, ``formattingObjectDefinitions``).
    The documents Kairos emits are minimal -- an empty bound canvas -- so those
    branches never apply and the refs are never followed. Rather than vendor those
    trees speculatively, an unresolvable ref raises: if a future change starts
    emitting visuals or filters, this fails loudly instead of silently reaching the
    network or silently passing.
    """
    import jsonschema
    from referencing import Registry, Resource
    from referencing.exceptions import NoSuchResource
    from referencing.jsonschema import DRAFT7

    def _refuse(uri: str):
        raise NoSuchResource(ref=uri)

    registry = Registry(retrieve=_refuse).with_resources(
        (identifier, Resource.from_contents(document, default_specification=DRAFT7))
        for identifier, document in _schemas().items()
    )
    return jsonschema.Draft7Validator(schema, registry=registry)


def validate_package_artifacts(artifacts: dict[str, str]) -> tuple[PbipValidationResult, ...]:
    """Validate every Fabric package file in *artifacts* against its declared schema.

    Returns one result per package file, in path order. Files that are not package
    metadata are skipped silently; a package file that declares no ``$schema``, or one
    this module does not have vendored, fails -- see the module docstring.
    """
    results: list[PbipValidationResult] = []
    known = _schemas()
    for path in sorted(artifacts):
        if not is_package_artifact(path):
            continue
        raw = artifacts[path]
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            results.append(PbipValidationResult(path, "fail", f"not valid JSON: {exc}"))
            continue
        if not isinstance(document, dict):
            results.append(PbipValidationResult(path, "fail", "expected a JSON object"))
            continue

        declared = document.get("$schema")
        if not declared:
            results.append(
                PbipValidationResult(path, "fail", "no $schema declared; Fabric requires one")
            )
            continue
        schema = known.get(str(declared))
        if schema is None:
            results.append(
                PbipValidationResult(
                    path,
                    "fail",
                    f"declares an unknown schema {declared!r} -- either the URI is wrong "
                    f"(the published families are listed in fabric_schema/) or the schema "
                    f"needs vendoring",
                )
            )
            continue

        try:
            errors = sorted(
                _validator(schema).iter_errors(document), key=lambda item: list(item.path)
            )
        except Exception as exc:  # noqa: BLE001 - an unresolvable ref must be reported, not raised
            results.append(
                PbipValidationResult(path, "fail", f"could not validate: {type(exc).__name__}: {exc}")
            )
            continue

        if errors:
            detail = "; ".join(
                f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
                for error in errors[:5]
            )
            if len(errors) > 5:
                detail += f" (and {len(errors) - 5} more)"
            results.append(PbipValidationResult(path, "fail", detail))
        else:
            results.append(PbipValidationResult(path, "pass", ""))
    return tuple(results)
