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
    inputs: tuple[ProvenanceInput, ...] = ()

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
        for item in sorted(self.inputs, key=lambda i: i.name):
            hasher.update(item.name.encode("utf-8"))
            hasher.update(b"\x1f")
            hasher.update(item.content.encode("utf-8"))
            hasher.update(b"\x00")
        return hasher.hexdigest()
