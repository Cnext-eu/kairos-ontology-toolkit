# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Hub-wide check that every ``externalReference`` key names a column its parent emits (#934).

``compile`` checks the key against the parent's declared Silver contract (DD-213), and
only that: a domain's compile scope deliberately excludes other domains' emitted artifacts
(DD-133/140). Most hubs author no contracts, so on them the compile check never ran, and a
cross-domain join on a column the parent does not emit passed ``compile --check``, emitted
SQL and cleared ``audit-silver-samples``, failing only in the warehouse.

``validate`` already reads the whole hub, so it can check the same claim against what the
parent's *binding* derives: an authored ``technicalFields`` name, else ``camel_to_snake`` of
a mapped property's local name -- the rule the emitter uses and ``propose-relationships``
already follows (#928, #932). That is a derivation from authored inputs, not a read of an
emitted artifact.

Findings are warnings, not errors: a contract may pin a column name the binding alone does
not show, and ``compile`` remains the authority wherever a contract exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .propose_relationships import BoundEntity, _slug, index_bindings


@dataclass(frozen=True, slots=True)
class ExternalReferenceFinding:
    """One ``externalReference`` key column the parent binding does not emit."""

    binding: str
    path: str
    relationship: str
    parent: str
    column: str
    emitted: tuple[str, ...]

    @property
    def message(self) -> str:
        shown = ", ".join(self.emitted[:12]) + (" …" if len(self.emitted) > 12 else "")
        return (
            f"{self.binding}: externalReference key column {self.column!r} for "
            f"{self.relationship} is not a column {self.parent} emits (its binding derives: "
            f"{shown or '(none)'}). The key names the parent's *output* column, not this "
            "binding's source column; the join would fail in the warehouse."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": "relationship.external-reference-key-not-emitted",
            "binding": self.binding,
            "path": self.path,
            "relationship": self.relationship,
            "parent": self.parent,
            "column": self.column,
            "message": self.message,
        }


@dataclass(slots=True)
class ExternalReferenceReport:
    """Every ``externalReference`` key checked across the hub."""

    checked: int = 0
    findings: list[ExternalReferenceFinding] = field(default_factory=list)
    #: ``domain.name`` parents no binding in this hub declares, so nothing to check against.
    unresolved_parents: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "findings": [item.to_dict() for item in self.findings],
            "unresolved_parents": sorted(set(self.unresolved_parents)),
        }


def emitted_columns(parent: BoundEntity) -> frozenset[str]:
    """The Silver columns *parent*'s binding derives: technical fields and mapped fields.

    The same three-site rule as ``contracts.entity_output_columns`` minus what only a
    contract can say (a pinned ``columnName``); the surrogate key is not an
    ``externalReference`` key column, so it is not needed here.
    """
    return frozenset(parent.technical_outputs.values()) | frozenset(parent.field_outputs.values())


def audit_external_references(hub_root: Path) -> ExternalReferenceReport:
    """Check every ``externalReference`` key in the hub against its parent's binding."""
    bindings_dir = Path(hub_root) / "integration" / "bindings"
    contracts_dir = Path(hub_root) / "model" / "contracts"
    report = ExternalReferenceReport()
    entities = index_bindings(bindings_dir)
    # `externalReference.name` is the parent's generated model name: the slug of its
    # target class (DD-138, `adapter._slug`), which is what `propose-relationships`
    # writes. A binding's own name is accepted too, for keys authored by hand that way.
    by_name: dict[tuple[str, str], BoundEntity] = {}
    for entity in entities:
        by_name.setdefault((entity.domain, entity.name), entity)
    for entity in entities:
        slug = _slug(entity.target_class)
        if slug:
            by_name[(entity.domain, slug)] = entity
    if not bindings_dir.is_dir():
        return report
    for path in sorted(bindings_dir.glob("*.binding.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue  # an unreadable binding is compile's to report
        if not isinstance(data, dict):
            continue
        meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        binding_name = str(meta.get("name", path.stem))
        for relationship in data.get("relationships") or []:
            if not isinstance(relationship, dict):
                continue
            external = relationship.get("externalReference")
            if not isinstance(external, dict):
                continue
            parent_key = (str(external.get("domain") or ""), str(external.get("name") or ""))
            parent = by_name.get(parent_key)
            label = f"{parent_key[0]}.{parent_key[1]}"
            if parent is None:
                report.unresolved_parents.append(label)
                continue
            if (contracts_dir / f"{parent.domain}.contract.yaml").is_file():
                # A declared contract may pin column names the binding does not show, and
                # `compile` checks the key against it. Checking here too could only disagree.
                continue
            emitted = emitted_columns(parent)
            for item in external.get("key") or []:
                column = str(item.get("column") or "") if isinstance(item, dict) else ""
                if not column:
                    continue
                report.checked += 1
                if column not in emitted:
                    report.findings.append(
                        ExternalReferenceFinding(
                            binding=binding_name,
                            path=path.relative_to(Path(hub_root)).as_posix(),
                            relationship=str(relationship.get("property") or "?"),
                            parent=label,
                            column=column,
                            emitted=tuple(sorted(emitted)),
                        )
                    )
    return report
