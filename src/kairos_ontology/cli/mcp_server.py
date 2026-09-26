# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``kairos-ontology mcp serve``: the closure-aware inspection commands as tools (DD-245).

An agent working in a hub can always ``Read`` a domain ``.ttl``; the file is on its disk and
authoring needs it. What it must not do is conclude what a class *means* from that file,
because the parents, inherited properties and inverse relations live in the modules the
file ``owl:imports``. The CLI resolves that closure, but a CLI command is three things to
remember and a shell to run; a tool is one call whose description says why it exists.
This server exposes the same functions the CLI uses, over stdio, started by the IDE from
the hub's own environment. Stateless: every call loads through ``load_ontology`` and the
in-process caches.

The ``[mcp]`` extra is optional. Without it, ``mcp serve`` says how to install it and
nothing else in the toolkit changes.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import click

INSTRUCTIONS = (
    "Kairos ontology hub. A domain .ttl file carries only its own triples; the classes it "
    "extends, the properties it inherits and the inverse relations it takes part in live in "
    "the modules it owl:imports (DD-103). These tools read the resolved import closure. Use "
    "them, not the file text, to answer what a class or property means or carries."
)

_PROFILES = ("asserted", "rdfs", "kairos-design", "owl-rl")


def _hub(hub: Path | None) -> Path:
    from ..core.hub_utils import find_hub_root

    root = hub or find_hub_root(Path.cwd(), require_model=True)
    if root is None:
        raise ValueError("Cannot locate a hub (model/ + integration/) from the working directory.")
    return Path(root)


def _domain_path(hub: Path, domain: str) -> Path:
    path = hub / "model" / "ontologies" / f"{domain}.ttl"
    if not path.is_file():
        raise ValueError(f"Domain ontology not found: {path}")
    return path


def _load(hub: Path, domain: str, profile: str = "kairos-design"):
    from ..core.ontology_loader import load_ontology

    if profile not in _PROFILES:
        raise ValueError(f"profile must be one of {', '.join(_PROFILES)}")
    # The catalog is found from the file's parents, as the CLI does.
    return load_ontology(_domain_path(hub, domain), profile=profile)


def _not_carried(index, record: dict[str, Any]) -> list[str]:
    from ..core.semantic_index import PROFILE_DEPENDENT_FIELDS

    return [f for f in PROFILE_DEPENDENT_FIELDS if f in record and not index.carries(f)]


def build_server(hub: Path | None = None):
    """The MCP server for one hub. Imports the SDK lazily; raises ImportError without it."""
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("kairos", instructions=INSTRUCTIONS, version="1")

    @server.tool()
    def show_class_inventory(
        domain: str, profile: str = "kairos-design", max_classes: int | None = None
    ) -> dict[str, Any]:
        """Every class in the domain's resolved owl:imports closure, with its ancestors,
        direct and inherited properties, and provenance. The .ttl file does not contain the
        inherited ones. `metadata.coverage` says which fields the profile fills."""
        root = _hub(hub)
        loaded = _load(root, domain, profile)
        data = loaded.semantic_index.slice(max_classes=max_classes)
        data["unattached_property_domains"] = [
            list(pair) for pair in loaded.semantic_index.unattached_property_domains
        ]
        return data

    @server.tool()
    def list_class_properties(class_iri: str, domain: str) -> dict[str, Any]:
        """Direct and inherited properties of one class across the domain's owl:imports
        closure, each with `origin` (direct|inherited) and `distance`. This is the only
        view that includes properties inherited from imported modules; a .ttl read as
        text misses them (DD-103)."""
        root = _hub(hub)
        loaded = _load(root, domain)
        index = loaded.semantic_index
        if index.class_by_uri(class_iri) is None:
            raise ValueError(f"Class not in the closure of '{domain}': {class_iri}")
        return {
            "class_uri": class_iri,
            "semantic_profile": loaded.profile.value,
            "import_complete": loaded.complete,
            "properties": index.class_properties(class_iri),
            "coverage": index.coverage,
        }

    @server.tool()
    def explain_term(iri: str, domain: str, profile: str = "kairos-design") -> dict[str, Any]:
        """One class, property or individual with label, comment, links and import
        provenance, resolved through the domain's owl:imports closure. Fields the chosen
        profile does not populate are listed in `not_carried_by_profile`; an empty list
        there is a real 'declares none'."""
        from .inspection import _closure_miss_message

        root = _hub(hub)
        loaded = _load(root, domain, profile)
        index = loaded.semantic_index
        term = index.term(iri)
        if term is None:
            raise ValueError(_closure_miss_message(loaded, iri, _domain_path(root, domain)))
        record = asdict(term)
        return {
            "semantic_profile": loaded.profile.value,
            "closure_hash": loaded.closure_hash,
            "import_complete": loaded.complete,
            "coverage": index.coverage,
            "not_carried_by_profile": _not_carried(index, record),
            "term": record,
        }

    @server.tool()
    def resolve_ontology(domain: str) -> dict[str, Any]:
        """The domain's resolved owl:imports closure: every module loaded, at what depth,
        from where, and whether the closure is complete."""
        root = _hub(hub)
        loaded = _load(root, domain, "asserted")
        return {
            "import_complete": loaded.complete,
            "closure_hash": loaded.closure_hash,
            "manifest": [entry.to_dict() for entry in loaded.manifest],
            "diagnostics": [item.to_dict() for item in loaded.diagnostics],
        }

    @server.tool()
    def compile_check(domain: str) -> dict[str, Any]:
        """Run the write-free compile check for one domain and return its ordered
        diagnostics (code, severity, rule_id, location, message). Same result as
        `kairos-ontology compile <domain> --check --format json`."""
        from ..core.compiler import CompileMode, compile_domain
        from .compile import _payload

        root = _hub(hub)
        return _payload(compile_domain(root, domain, CompileMode.CHECK))

    @server.tool()
    def compile_explain(domain: str) -> dict[str, Any]:
        """Explain one domain's normalized compile plan: entities, sources, grain,
        identity, relationships and planned artifact paths. Write-free."""
        from ..core.compiler import CompileMode, compile_domain
        from .compile import _payload

        root = _hub(hub)
        return _payload(compile_domain(root, domain, CompileMode.EXPLAIN))

    @server.tool()
    def logs_show(group_by: str = "task") -> dict[str, Any]:
        """The newest run log of the hub: how the last writing command ended, its tasks
        with durations, and every diagnostic grouped by task, code or severity."""
        from .logs import _groups, _load as _load_log
        from .run_log import newest_run_log, run_log_directory

        root = _hub(hub)
        latest = newest_run_log(root)
        if latest is None:
            raise ValueError(f"No run logs in {run_log_directory(root)}.")
        if group_by not in {"task", "code", "severity"}:
            raise ValueError("group_by must be task, code or severity")
        run = _load_log(latest)
        return {**run, "group_by": group_by, "groups": _groups(run, group_by)}

    return server


@click.group(name="mcp")
def mcp_group() -> None:
    """Serve the closure-aware inspection commands as MCP tools (DD-245)."""


@mcp_group.command(name="serve")
@click.option(
    "--hub",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Hub root; found from the working directory when omitted.",
)
def mcp_serve_cmd(hub: Path | None) -> None:
    """Start the Kairos MCP server on stdio.

    Register it once in the hub (`.mcp.json` for Claude Code, `.vscode/mcp.json` for
    Copilot; the scaffold ships both) and the IDE starts it from the hub's environment.
    Tools: show_class_inventory, list_class_properties, explain_term, resolve_ontology,
    compile_check, compile_explain, logs_show. Needs the `[mcp]` extra.
    """
    try:
        server = build_server(hub)
    except ImportError as exc:
        raise click.ClickException(
            "The MCP server needs the optional [mcp] extra: `uv sync --extra mcp` in the "
            "hub, or `pip install 'kairos-ontology-toolkit[mcp]'`."
        ) from exc
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    server.run("stdio")


def tool_result_json(result: Any) -> Any:
    """The JSON a tool returned, from an MCP `CallToolResult` (test helper)."""
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            return json.loads(text)
    return None


__all__ = ["INSTRUCTIONS", "build_server", "mcp_group", "tool_result_json"]
