# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Content-addressed provenance sidecar for emitted artifacts (DD-218).

``.kairos-compile-manifest.*.json`` records what emission *wrote* -- one sha256 per
output file -- and nothing about what those bytes were computed *from*. A dataplatform
repository holding an emitted dbt package therefore cannot answer "which ontology and
which bindings produced this?" without reconstructing it from the Git revision it
happened to pin.

This module emits that answer as an ordinary compiler artifact rather than as manifest
metadata. The manifest is a closed document -- ``_parse_manifest`` rejects any top-level
key outside ``{"files", "schema"}``, so extending it breaks an older toolkit reading a
newer publish tree -- and it is written four times per compile over disjoint artifact
sets, with the shared manifest last-writer-wins across domains, so there is no correct
answer to whose provenance belongs in it. A sidecar has neither problem: it is one more
entry in the rendered mapping, and the manifest records its sha256 like any other file.

Deterministic by construction. DD-133 validation requirement 10 forbids wall-clock values
in artifact content, so there is no timestamp here. There is no Git revision either: it is
unavailable in ``core`` by design, it is not a pure function of the inputs (a dirty
worktree still has a HEAD), and the per-input digests below are strictly stronger evidence
than a commit id.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from .scope import BuildScope

PROVENANCE_SCHEMA: Final = "kairos.eu/compile-provenance/v1"


def provenance_artifact_path(domain: str, *, lane: str = "") -> str:
    """Return the artifact path for one lane's provenance sidecar.

    Lives under ``metadata/`` beside the release-review and gold-product documents the
    renderer already emits, so it lands in the domain-owned artifact set rather than the
    shared one.
    """
    suffix = f"-{lane}" if lane else ""
    return f"metadata/{domain}{suffix}.provenance.json"


def build_provenance_document(scope: BuildScope) -> str:
    """Render the provenance sidecar for one build scope.

    Inputs are ordered by ``(name, content)`` -- the same total order
    :meth:`BuildScope.provenance_hash` sorts by, and for the same reason (#600): names
    are not unique, so a name-only key leaves colliding inputs in an insertion order that
    varies with ``PYTHONHASHSEED``. Keeping the two orders identical means the sidecar
    can be read as an itemisation of the hash rather than a second, differently-ordered
    view of it.
    """
    document = {
        "schema": PROVENANCE_SCHEMA,
        "domain": scope.domain,
        "apiVersion": scope.api_version,
        "namespace": scope.namespace,
        "adapter": scope.adapter,
        "toolkit": scope.toolkit_version,
        "provenanceHash": scope.provenance_hash(),
        "inputs": [
            {
                "name": item.name,
                "sha256": hashlib.sha256(item.content.encode("utf-8")).hexdigest(),
            }
            for item in sorted(scope.inputs, key=lambda i: (i.name, i.content))
        ],
    }
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def provenance_artifact(scope: BuildScope, *, lane: str = "") -> tuple[str, str]:
    """Return the ``(path, content)`` pair to merge into a rendered artifact mapping."""
    return provenance_artifact_path(scope.domain, lane=lane), build_provenance_document(scope)
