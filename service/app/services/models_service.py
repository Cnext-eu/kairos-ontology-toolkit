# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""GitHub Models API chat service — OpenAI-compatible, no Copilot subscription required.

Uses https://models.inference.ai.azure.com with any GitHub PAT.
Yields the same event-dict format as ``sdk_service.stream_chat``.
"""

import asyncio
import json
import logging
from typing import AsyncIterator, Optional

from openai import AsyncOpenAI

from rdflib import Graph

from kairos_ontology.ontology_ops import (
    add_class,
    add_property,
    modify_class,
    parse_ontology_content,
    remove_class,
    serialize_graph,
)
from kairos_ontology.projector import VALID_TARGETS, project_graph
from kairos_ontology.validator import validate_content

from . import github_service as gh

logger = logging.getLogger(__name__)

_GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"
_DEFAULT_MODEL = "gpt-4o"  # requires GitHub Copilot; falls back to gpt-4o-mini if unavailable

_SYSTEM_PROMPT = """\
You are an expert ontology assistant for the Kairos platform.
You help business analysts understand and modify OWL/Turtle ontologies.

Available tools:
- query_ontology: search classes, properties, relationships
- propose_change: generate a TTL modification with diff preview
- validate_ontology: run SHACL / syntax validation
- generate_projection: generate dbt / neo4j / azure-search / a2ui / prompt artifacts
- explain_ontology: produce a human-readable summary of a domain
- suggest_improvements: analyze a domain and return actionable suggestions

RULES:
- Always output valid Turtle syntax when proposing changes.
- Never modify the main branch directly — always use feature branches.
- Explain changes in plain English before showing TTL.
- When the user asks to apply a change, always call propose_change first to show
  a diff, then ask for confirmation before proceeding.
"""

# ---------------------------------------------------------------------------
# OpenAI function schemas
# ---------------------------------------------------------------------------

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_ontology",
            "description": "Search classes, properties, and relationships in the ontology.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain file name (e.g. 'customer')"},
                    "search": {"type": "string", "description": "Free-text filter for class names"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_change",
            "description": (
                "Propose a modification to the ontology (add/modify/remove class or property). "
                "Returns a unified diff and the new TTL content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain file name"},
                    "action": {
                        "type": "string",
                        "enum": ["add_class", "modify_class", "add_property", "remove_class"],
                    },
                    "details": {"type": "object", "description": "Action-specific parameters"},
                },
                "required": ["domain", "action", "details"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_ontology",
            "description": "Run syntax and SHACL validation on an ontology domain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain file name"},
                },
                "required": ["domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_projection",
            "description": "Generate downstream artifacts from an ontology domain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain file name"},
                    "targets": {
                        "type": "array",
                        "items": {"type": "string", "enum": VALID_TARGETS},
                        "description": "Projection targets (omit for all)",
                    },
                },
                "required": ["domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_ontology",
            "description": "Produce a human-readable summary of an ontology domain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain file name"},
                },
                "required": ["domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_improvements",
            "description": (
                "Analyze an ontology domain and return actionable improvement suggestions "
                "(missing labels, incomplete properties, naming issues, etc.)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain file name"},
                },
                "required": ["domain"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations (standalone async functions)
# ---------------------------------------------------------------------------

def _domain_to_path(domain: str) -> str:
    safe = domain.replace("/", "").replace("\\", "").replace("..", "")
    name = safe if "." in safe else f"{safe}.ttl"
    return f"{gh.settings.github_ontologies_path}/{name}"


def _class_dict(c) -> dict:
    return {
        "uri": c.uri,
        "name": c.name,
        "label": c.label,
        "comment": c.comment,
        "superclasses": c.superclasses,
        "properties": [
            {"name": p.name, "type": p.range_name, "is_object": p.is_object_property}
            for p in c.properties
        ],
    }


def _unified_diff(old: str, new: str, filename: str) -> str:
    import difflib
    return "\n".join(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(),
            fromfile=f"a/{filename}", tofile=f"b/{filename}",
            lineterm="",
        )
    )


async def _tool_query_ontology(
    token: str,
    domain: Optional[str],
    search: Optional[str],
    repo_owner: Optional[str] = None,
    repo_name: Optional[str] = None,
) -> str:
    files = await gh.list_ttl_files(owner=repo_owner, repo=repo_name)
    results = []
    for f in files:
        if domain and not f["name"].startswith(domain):
            continue
        content = await gh.read_file(f["path"], owner=repo_owner, repo=repo_name)
        info = parse_ontology_content(content)
        entry = {
            "domain": f["name"],
            "namespace": info.namespace,
            "classes": [_class_dict(c) for c in info.classes],
            "relationships": [
                {"name": r.name, "domain": r.domain, "range": r.range}
                for r in info.relationships
            ],
        }
        if search:
            term = search.lower()
            entry["classes"] = [
                c for c in entry["classes"]
                if term in c["name"].lower() or term in (c.get("comment") or "").lower()
            ]
        results.append(entry)
    return json.dumps(results, indent=2)


async def _tool_propose_change(
    token: str,
    domain: str,
    action: str,
    details: dict,
    repo_owner: Optional[str] = None,
    repo_name: Optional[str] = None,
) -> str:
    file_path = _domain_to_path(domain)
    original = await gh.read_file(file_path, owner=repo_owner, repo=repo_name)
    graph = Graph()
    graph.parse(data=original, format="turtle")
    info = parse_ontology_content(original)
    ns = info.namespace

    if action == "add_class":
        add_class(graph, ns, **details)
    elif action == "modify_class":
        uri = details.pop("class_uri", None) or f"{ns}{details.pop('class_name', '')}"
        modify_class(graph, uri, **details)
    elif action == "add_property":
        domain_uri = details.pop("domain_uri", None)
        if not domain_uri:
            cname = details.pop("domain_class", "")
            domain_uri = f"{ns}{cname}"
        add_property(graph, ns, domain_uri=domain_uri, **details)
    elif action == "remove_class":
        uri = details.get("class_uri") or f"{ns}{details.get('class_name', '')}"
        remove_class(graph, uri)
    else:
        return json.dumps({"error": f"Unknown action: {action}"})

    new_content = serialize_graph(graph)
    diff = _unified_diff(original, new_content, file_path)
    return json.dumps({"domain": domain, "diff": diff, "new_content": new_content})


async def _tool_validate_ontology(
    token: str,
    domain: str,
    repo_owner: Optional[str] = None,
    repo_name: Optional[str] = None,
) -> str:
    file_path = _domain_to_path(domain)
    content = await gh.read_file(file_path, owner=repo_owner, repo=repo_name)
    return json.dumps(validate_content(content), indent=2)


async def _tool_generate_projection(
    token: str,
    domain: str,
    targets: Optional[list],
    repo_owner: Optional[str] = None,
    repo_name: Optional[str] = None,
) -> str:
    file_path = _domain_to_path(domain)
    content = await gh.read_file(file_path, owner=repo_owner, repo=repo_name)
    graph = Graph()
    graph.parse(data=content, format="turtle")
    results = project_graph(graph, targets=targets, ontology_name=domain.replace(".ttl", ""))
    return json.dumps({"domain": domain, "targets": results}, indent=2)


async def _tool_explain_ontology(
    token: str,
    domain: str,
    repo_owner: Optional[str] = None,
    repo_name: Optional[str] = None,
) -> str:
    file_path = _domain_to_path(domain)
    content = await gh.read_file(file_path, owner=repo_owner, repo=repo_name)
    info = parse_ontology_content(content)
    return json.dumps(
        {
            "domain": domain,
            "namespace": info.namespace,
            "classes": [_class_dict(c) for c in info.classes],
            "relationships": [
                {"name": r.name, "domain": r.domain, "range": r.range}
                for r in info.relationships
            ],
        },
        indent=2,
    )


async def _tool_suggest_improvements(
    token: str,
    domain: str,
    repo_owner: Optional[str] = None,
    repo_name: Optional[str] = None,
) -> str:
    from rdflib.namespace import OWL, RDF, RDFS

    file_path = _domain_to_path(domain)
    content = await gh.read_file(file_path, owner=repo_owner, repo=repo_name)

    g = Graph()
    g.parse(data=content, format="turtle")
    info = parse_ontology_content(content)

    issues = []
    for cls_uri in g.subjects(RDF.type, OWL.Class):
        name = str(cls_uri).split("#")[-1].split("/")[-1]
        if not any(True for _ in g.objects(cls_uri, RDFS.label)):
            issues.append({"severity": "warning", "class": name, "issue": "Missing rdfs:label"})
        if not any(True for _ in g.objects(cls_uri, RDFS.comment)):
            issues.append({"severity": "info", "class": name, "issue": "Missing rdfs:comment"})

    for rel in info.relationships:
        if not rel.name:
            issues.append({"severity": "warning", "property": str(rel), "issue": "Property missing name"})

    validation = validate_content(content)
    return json.dumps(
        {
            "domain": domain,
            "class_count": len(info.classes),
            "issues": issues,
            "validation": validation,
        },
        indent=2,
    )


async def _dispatch_tool(
    name: str,
    args: dict,
    token: str,
    repo_owner: Optional[str],
    repo_name: Optional[str],
) -> str:
    try:
        if name == "query_ontology":
            return await _tool_query_ontology(
                token, args.get("domain"), args.get("search"), repo_owner, repo_name
            )
        if name == "propose_change":
            return await _tool_propose_change(
                token, args["domain"], args["action"], args.get("details", {}),
                repo_owner, repo_name,
            )
        if name == "validate_ontology":
            return await _tool_validate_ontology(token, args["domain"], repo_owner, repo_name)
        if name == "generate_projection":
            return await _tool_generate_projection(
                token, args["domain"], args.get("targets"), repo_owner, repo_name
            )
        if name == "explain_ontology":
            return await _tool_explain_ontology(token, args["domain"], repo_owner, repo_name)
        if name == "suggest_improvements":
            return await _tool_suggest_improvements(token, args["domain"], repo_owner, repo_name)
        return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as exc:
        logger.error("Tool %s failed: %s", name, exc, exc_info=True)
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Main streaming function
# ---------------------------------------------------------------------------

async def stream_chat(
    user_message: str,
    github_token: str,
    ontology_context: str = "",
    conversation_history: str = "",
    repo_owner: Optional[str] = None,
    repo_name: Optional[str] = None,
    model: str = _DEFAULT_MODEL,
) -> AsyncIterator[dict]:
    """Stream a chat response using the GitHub Models API.

    Yields the same event-dict format as ``sdk_service.stream_chat``:
    - ``{"type": "delta", "content": "..."}``
    - ``{"type": "tool_start", "name": "..."}``
    - ``{"type": "tool_end", "name": "..."}``
    - ``{"type": "error", "message": "..."}``
    """
    client = AsyncOpenAI(
        base_url=_GITHUB_MODELS_ENDPOINT,
        api_key=github_token,
    )

    system_text = _SYSTEM_PROMPT
    if ontology_context:
        system_text += f"\n\nONTOLOGY CONTEXT:\n{ontology_context}"
    if conversation_history:
        system_text += (
            "\n\n─── CONVERSATION HISTORY ───\n"
            f"{conversation_history}\n"
            "─── END HISTORY ───"
        )

    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_message},
    ]

    # Agentic loop — run until model stops calling tools
    max_rounds = 6
    for _ in range(max_rounds):
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=_TOOLS,
                stream=True,
            )
        except Exception as exc:
            err_str = str(exc)
            # If model is not accessible (no Copilot), try gpt-4o-mini fallback
            if model != "gpt-4o-mini" and ("403" in err_str or "404" in err_str or "not found" in err_str.lower()):
                logger.warning("Model %s not accessible, falling back to gpt-4o-mini: %s", model, exc)
                model = "gpt-4o-mini"
                try:
                    stream = await client.chat.completions.create(
                        model=model,
                        messages=messages,
                        tools=_TOOLS,
                        stream=True,
                    )
                except Exception as exc2:
                    logger.error("Fallback model error: %s", exc2)
                    yield {"type": "error", "message": str(exc2)}
                    return
            elif "413" in err_str or "tokens_limit_reached" in err_str.lower():
                if model != "gpt-4o-mini":
                    logger.warning("Token limit hit for %s, falling back to gpt-4o-mini", model)
                    model = "gpt-4o-mini"
                    try:
                        stream = await client.chat.completions.create(
                            model=model,
                            messages=messages,
                            tools=_TOOLS,
                            stream=True,
                        )
                    except Exception as exc2:
                        logger.error("Fallback model error: %s", exc2)
                        yield {"type": "error", "message": str(exc2)}
                        return
                else:
                    yield {"type": "error", "message": "Request too large even for gpt-4o-mini. Please select a specific domain to narrow the context."}
                    return
            elif "401" in err_str or "unauthorized" in err_str.lower():
                logger.error("GitHub Models API auth error: %s", exc)
                yield {
                    "type": "error",
                    "message": (
                        "GitHub Models API authentication failed. "
                        "Please enter a GitHub PAT with **Copilot** (models:read) access "
                        "in the token field in the sidebar."
                    ),
                }
                return
            else:
                logger.error("GitHub Models API error: %s", exc)
                yield {"type": "error", "message": err_str}
                return

        # Collect streamed response
        role = "assistant"
        content_parts: list[str] = []
        tool_calls_raw: dict[int, dict] = {}  # index → {id, name, args_str}

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            if delta.content:
                content_parts.append(delta.content)
                yield {"type": "delta", "content": delta.content}

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_raw:
                        tool_calls_raw[idx] = {"id": tc.id or "", "name": "", "args_str": ""}
                    if tc.id:
                        tool_calls_raw[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_raw[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_raw[idx]["args_str"] += tc.function.arguments

        full_content = "".join(content_parts)

        # Build assistant message for history
        assistant_msg: dict = {"role": role, "content": full_content or None}
        if tool_calls_raw:
            assistant_msg["tool_calls"] = [
                {
                    "id": v["id"],
                    "type": "function",
                    "function": {"name": v["name"], "arguments": v["args_str"]},
                }
                for v in tool_calls_raw.values()
            ]
        messages.append(assistant_msg)

        if not tool_calls_raw:
            # Model is done — no more tool calls
            return

        # Execute tool calls and append results
        tool_results = await asyncio.gather(
            *[
                _run_tool(tc, github_token, repo_owner, repo_name)
                for tc in tool_calls_raw.values()
            ]
        )
        for event, tool_msg in tool_results:
            yield event[0]  # tool_start
            yield event[1]  # tool_end
            messages.append(tool_msg)


async def _run_tool(
    tc: dict,
    token: str,
    repo_owner: Optional[str],
    repo_name: Optional[str],
) -> tuple[list[dict], dict]:
    """Execute one tool call and return (events, tool_message)."""
    name = tc["name"]
    try:
        args = json.loads(tc["args_str"] or "{}")
    except json.JSONDecodeError:
        args = {}

    events = [
        {"type": "tool_start", "name": name, "intent": ""},
        {"type": "tool_end", "name": name},
    ]

    result = await _dispatch_tool(name, args, token, repo_owner, repo_name)
    tool_msg = {
        "role": "tool",
        "tool_call_id": tc["id"],
        "content": result,
    }
    return events, tool_msg
