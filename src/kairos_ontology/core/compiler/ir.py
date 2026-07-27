# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Graph-free intermediate representation for the v5 compiler (DD-133).

``EntityBindingSpec`` is the resolved, graph-free view of one authored ``EntityBinding``
after symbol resolution; ``CanonicalProjectIR`` is the ordered, immutable bundle handed to
emission. Both are populated by the binding adapter (a later phase); this module only
defines their closed shapes so schema, adapter, and emission agree on one contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .bindings import EntityBinding
from .scope import BuildScope


@dataclass(frozen=True, slots=True)
class EntityBindingSpec:
    """One authored binding plus its graph-free resolved projection facts."""

    binding: EntityBinding
    bound: Any = None
    artifact_paths: tuple[str, ...] = ()
    blocked: bool = False

    @property
    def name(self) -> str:
        """Return the stable binding name."""
        return self.binding.name

    @property
    def domain(self) -> str:
        """Return the owning domain."""
        return self.binding.domain


@dataclass(frozen=True, slots=True)
class CanonicalProjectIR:
    """Ordered, immutable project IR consumed by emission."""

    domain: str
    entities: tuple[EntityBindingSpec, ...] = ()
    provenance_hash: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)
    scope: BuildScope | None = None
    artifact_paths: tuple[str, ...] = ()
