# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Immutable build scope and deterministic provenance for the v5 compiler (DD-133).

One :class:`BuildScope` is resolved per ``compile`` invocation and threaded, unchanged,
through every phase. Its provenance hash is byte-deterministic: it covers the schema
version, adapter, ontology/source closure, binding contents, templates/macros, and toolkit
version, and it deliberately **excludes** wall-clock values so repeat emission is stable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .result import CompileDiagnostic


@dataclass(frozen=True, slots=True)
class ProvenanceInput:
    """One named, content-addressed provenance contribution."""

    name: str
    content: str


@dataclass(frozen=True, slots=True)
class BuildScope:
    """The single immutable scope + provenance closure for one compile invocation."""

    domain: str
    hub_root: str
    api_version: str
    adapter: str
    namespace: str
    toolkit_version: str
    binding_paths: tuple[str, ...] = ()
    ontology_paths: tuple[str, ...] = ()
    #: Declared Silver contracts in scope (DD-213), the selected domain's first and then
    #: foreign-domain contracts that declare a cross-domain relationship target. Foreign
    #: contracts are load-bearing, not informational: a relationship FK column is named
    #: ``{property_column}_{target_model}`` (``kernel.py``), so the *parent's* declared
    #: ``modelName`` decides a child domain's column name. Resolving only the selected
    #: domain would let a parent rename silently break a child that is never recompiled
    #: in the same run.
    contract_paths: tuple[str, ...] = ()
    inputs: tuple[ProvenanceInput, ...] = ()
    prefix_warnings: tuple[CompileDiagnostic, ...] = ()

    def provenance_hash(self) -> str:
        """Return a wall-clock-free SHA-256 over all scope-defining inputs."""
        hasher = hashlib.sha256()
        header = "\n".join(
            (
                f"apiVersion={self.api_version}",
                f"adapter={self.adapter}",
                f"namespace={self.namespace}",
                f"toolkit={self.toolkit_version}",
                f"domain={self.domain}",
            )
        )
        hasher.update(header.encode("utf-8"))
        hasher.update(b"\x00")
        # Sort on (name, content), not name alone (#600). Names are not unique: an
        # ontology outside the hub root is recorded under its bare filename (see
        # kernel.py's ontology_paths loop), and reference modules from different
        # families share basenames. `sorted` is stable, so a name-only key left
        # colliding inputs in *insertion* order -- which follows the closure's set
        # iteration and therefore varies with PYTHONHASHSEED. Identical inputs then
        # hashed differently from one process to the next. Adding content makes the
        # order total: a tie now means same name *and* same bytes, so the two
        # contribute identically and their relative order cannot move the digest.
        for item in sorted(self.inputs, key=lambda i: (i.name, i.content)):
            hasher.update(item.name.encode("utf-8"))
            hasher.update(b"\x1f")
            hasher.update(item.content.encode("utf-8"))
            hasher.update(b"\x00")
        return hasher.hexdigest()
