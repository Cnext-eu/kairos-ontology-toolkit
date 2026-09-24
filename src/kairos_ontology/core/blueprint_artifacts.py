# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The accelerator blueprint's own design judgement, read where it decides something (#913).

An accelerator pack ships a dossier under ``accelerator-packs/<pack>/current/blueprint/``:
a canonical class registry, an overlap register, capability coverage, source shapes. The
toolkit read none of it, so global anchoring chose ``bsp/commercial#TransportLeg`` for a
domain the blueprint maps to ``mmt/consignment``, whose registry names
``mmt/consignment#TransportLeg`` as the canonical ``transport-leg`` -- and 33 hub-local
properties were then authored onto the wrong copy.

Not every pack has a dossier (``financial-services`` has none), so every reader here
returns an empty result for a missing or unreadable file rather than failing.
"""

from __future__ import annotations

from pathlib import Path

import yaml

#: Registry dispositions that withdraw a class from being canonical.
_NOT_CANONICAL = frozenset({"rejected"})


def blueprint_dir(ref_models_dir: Path, accelerator: str) -> Path:
    """``accelerator-packs/<accelerator>/current/blueprint`` under the refmodels root."""
    return Path(ref_models_dir) / "accelerator-packs" / accelerator / "current" / "blueprint"


def load_canonical_class_uris(ref_models_dir: Path | None, accelerator: str | None) -> frozenset[str]:
    """Every ``class_uri`` the canonical class registry names, unless it was rejected.

    The registry holds one ``class_uri`` per concept, which is exactly the answer to
    "which copy of a class name is the canonical one".
    """
    if ref_models_dir is None or not accelerator:
        return frozenset()
    path = blueprint_dir(Path(ref_models_dir), accelerator) / "canonical-class-registry.yaml"
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return frozenset()
    if not isinstance(document, dict):
        return frozenset()
    return frozenset(
        str(concept.get("class_uri")).rstrip("#/")
        for concept in document.get("concepts") or []
        if isinstance(concept, dict)
        and concept.get("class_uri")
        and str(concept.get("disposition") or "") not in _NOT_CANONICAL
    )
