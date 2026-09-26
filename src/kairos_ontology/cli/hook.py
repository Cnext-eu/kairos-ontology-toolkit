# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``kairos-ontology hook read-context``: a Claude Code hook that makes a raw ontology read
self-correcting (DD-245).

Denying ``Read`` on ``model/ontologies/**`` broke authoring (#659: ``Edit`` needs a prior
``Read``), so the file stays readable. Instead, this hook runs after the read and tells the
model what the file does not contain: which modules it imports, which of its classes carry
inherited properties that are not in the file, and which tool to call before concluding.
For a reference-model file, which is never authored, it denies the read before it happens.

Wired by the scaffold's ``.claude/settings.json`` for ``PreToolUse`` and ``PostToolUse`` on
``Read``. Claude Code only: Copilot has no hook mechanism. Never blocks on its own failure:
any problem prints ``{}`` and exits 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

#: Path fragments of the installed reference models: read-only by construction.
REFERENCE_MODEL_MARKERS = (
    "kairos_ontology_referencemodels",
    "ontology-reference-models",
    "/referencemodels/",
)
_ONTOLOGY_SUFFIXES = {".ttl", ".rdf", ".owl"}


def _is_domain_file(path: Path) -> bool:
    parts = path.as_posix().split("/")
    return (
        path.suffix.lower() in _ONTOLOGY_SUFFIXES
        and not path.name.startswith("_")
        and len(parts) >= 3
        and parts[-3:-1] == ["model", "ontologies"]
    )


def _closure_note(path: Path) -> str:
    """What the file at *path* does not contain, from its resolved closure."""
    from ..core.ontology_loader import SemanticProfile, load_ontology

    loaded = load_ontology(path, profile=SemanticProfile.KAIROS_DESIGN, degraded=True)
    index = loaded.semantic_index
    root_graph = loaded.sources[0].graph if loaded.sources else loaded.graph
    root_iri = ""
    from rdflib import OWL, RDF

    for ont in root_graph.subjects(RDF.type, OWL.Ontology):
        root_iri = str(ont).rstrip("#/")
        break
    imports = sorted(
        {
            (entry.import_uri or entry.ontology_iri or "")
            for entry in loaded.manifest
            if entry.import_depth == 1 and (entry.import_uri or entry.ontology_iri)
        }
    )
    own = [
        record
        for record in index.classes
        if not root_iri
        or record.uri.startswith(root_iri + "#")
        or record.uri.startswith(root_iri + "/")
    ]
    inheriting = []
    for record in own:
        inherited = [
            row for row in index.class_properties(record.uri) if row["origin"] == "inherited"
        ]
        if inherited:
            inheriting.append((record.name, len(inherited)))
    inheriting.sort(key=lambda item: (-item[1], item[0]))
    domain = path.stem
    lines = [
        f"You read `{path.name}`, one domain of an owl:imports closure. The file carries only "
        f"its own triples (DD-103)."
    ]
    if imports:
        lines.append(f"It imports {len(imports)} module(s): {', '.join(imports)}.")
    if inheriting:
        examples = ", ".join(f"{name} ({count} inherited)" for name, count in inheriting[:5])
        more = f" and {len(inheriting) - 5} more" if len(inheriting) > 5 else ""
        lines.append(
            f"{len(inheriting)} of its {len(own)} classes carry properties inherited from those "
            f"modules that are NOT in this file: {examples}{more}."
        )
    if not loaded.complete:
        lines.append("The closure did not fully resolve; some imported modules are missing.")
    lines.append(
        "Before concluding what a class carries or means, call the `list_class_properties` / "
        "`explain_term` MCP tools, or run `kairos-ontology list-class-properties <IRI> --domain "
        f"{domain}` / `explain-term <IRI> --domain {domain}`."
    )
    return " ".join(lines)


def read_context(payload: dict[str, Any]) -> dict[str, Any]:
    """The hook's JSON answer for one Claude Code hook *payload*; ``{}`` when silent."""
    try:
        event = str(payload.get("hook_event_name") or "")
        tool_input = payload.get("tool_input") or {}
        raw = str(tool_input.get("file_path") or "")
        if not raw:
            return {}
        path = Path(raw)
        posix = path.as_posix()
        if event == "PreToolUse":
            if any(marker in posix for marker in REFERENCE_MODEL_MARKERS) and (
                path.suffix.lower() in _ONTOLOGY_SUFFIXES
            ):
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            "Reference-model files are read through the closure, never as "
                            "text: use the explain_term / show_class_inventory tools or "
                            "`kairos-ontology explain-term <IRI> --domain <domain>` (DD-103)."
                        ),
                    }
                }
            return {}
        if event == "PostToolUse" and _is_domain_file(path) and path.is_file():
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": _closure_note(path),
                }
            }
        return {}
    except Exception:  # noqa: BLE001 - a hook must never fail the tool call it observes
        return {}


@click.group(name="hook")
def hook_group() -> None:
    """Claude Code hooks the hub scaffold wires (DD-245)."""


@hook_group.command(name="read-context")
def read_context_cmd() -> None:
    """Answer a Claude Code Read hook from the JSON on stdin.

    PostToolUse on a domain `.ttl`: adds context naming the file's imports and the classes
    whose inherited properties are not in the file. PreToolUse on a reference-model file:
    denies the read. Anything else, or any failure: `{}`.
    """
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        payload = {}
    click.echo(json.dumps(read_context(payload if isinstance(payload, dict) else {})))


__all__ = ["REFERENCE_MODEL_MARKERS", "hook_group", "read_context"]
