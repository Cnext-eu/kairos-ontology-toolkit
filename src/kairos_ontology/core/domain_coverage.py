# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``kairos-ontology domain-coverage`` core logic (issue #393).

Real, live evidence motivated this: a hub can have several fully authored domain
ontologies with zero active ``owl:imports`` in ``_master.ttl`` -- every prior
domain-authoring pass reported "``_master.ttl`` unchanged" as if that were
expected, when it is actually a real gap (a domain that is modeled, bound, and
validated but unreachable from the hub's single ontology entry point).

This module reports, per data domain, the union of:
  - whether the domain is listed in the resolved accelerator's blueprint
    (``data-domains.yaml``, via :func:`kairos_ontology.core.analyse_sources.load_data_domains`),
  - whether it has an authored domain ontology TTL under ``model/ontologies/``
    (via :func:`kairos_ontology.core.hub_inspection._ontology_domains`),
  - whether it has at least one EntityBinding
    (via :func:`kairos_ontology.core.hub_inspection._binding_domains`),
  - whether its declared ontology IRI is a live ``owl:imports`` in ``_master.ttl``
    (via :func:`kairos_ontology.core.master_ontology.list_active_master_imports`).

This is advisory only: it never fails a hub, and there is no ``--strict`` mode
(deliberately deferred -- see issue #393 suggestion #5, also deferred).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .analyse_sources import load_data_domains
from .catalog_utils import _declared_ontology_iri
from .hub_inspection import _binding_domains, _ontology_domains
from .master_ontology import list_active_master_imports

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DomainCoverageRow:
    """One domain's coverage across blueprint, authoring, binding, and import."""

    domain: str
    in_blueprint: Optional[bool]  # None => "n/a" (no accelerator pack installed at all)
    modeled: bool
    bound: bool
    imported: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "in_blueprint": self.in_blueprint,
            "modeled": self.modeled,
            "bound": self.bound,
            "imported": self.imported,
        }


@dataclass(frozen=True)
class DomainCoverageReport:
    """Full domain-coverage table plus the accelerator it was resolved against."""

    accelerator: Optional[str]
    rows: tuple[DomainCoverageRow, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "accelerator": self.accelerator,
            "domains": [row.to_dict() for row in self.rows],
        }


def _normalize_iri(iri: str) -> str:
    return iri.rstrip("/")


def build_domain_coverage_report(
    *,
    ontologies_dir: Path,
    bindings_dir: Path,
    master_path: Path,
    ref_models_dir: Optional[Path],
    accelerator: Optional[str],
) -> DomainCoverageReport:
    """Build the domain-coverage report for one hub.

    ``accelerator`` is the already-resolved accelerator id (or ``None`` when no
    accelerator pack is installed at all) -- resolution/ambiguity handling is the
    CLI layer's responsibility (mirroring ``check-inventory``'s precedent), not
    this function's.
    """
    blueprint_domains: dict[str, dict[str, Any]] = {}
    if accelerator and ref_models_dir is not None and Path(ref_models_dir).is_dir():
        blueprint_domains = load_data_domains(Path(ref_models_dir), accelerator=accelerator)

    ontology_domains, unreadable_domains = _ontology_domains(ontologies_dir)
    modeled_domains = ontology_domains | unreadable_domains

    binding_counts, _tier_counts = _binding_domains(bindings_dir)
    bound_domains = set(binding_counts)

    active_master_imports: set[str] = set()
    if master_path.is_file():
        try:
            active_master_imports = {
                _normalize_iri(iri) for iri in list_active_master_imports(master_path)
            }
        except Exception:  # defensive: a malformed _master.ttl must never crash this report
            active_master_imports = set()

    all_domains = sorted(set(blueprint_domains) | modeled_domains | bound_domains)

    rows: list[DomainCoverageRow] = []
    for name in all_domains:
        in_blueprint = None if accelerator is None else name in blueprint_domains
        modeled = name in modeled_domains
        bound = name in bound_domains

        imported = False
        if name in ontology_domains:  # only a readable file can have a declared IRI
            ttl_path = ontologies_dir / f"{name}.ttl"
            try:
                declared_iri = _declared_ontology_iri(ttl_path)
            except Exception:  # defensive: a parse-broken domain TTL is reported elsewhere
                declared_iri = None
            if declared_iri:
                imported = _normalize_iri(declared_iri) in active_master_imports

        rows.append(
            DomainCoverageRow(
                domain=name,
                in_blueprint=in_blueprint,
                modeled=modeled,
                bound=bound,
                imported=imported,
            )
        )

    return DomainCoverageReport(accelerator=accelerator, rows=tuple(rows))
