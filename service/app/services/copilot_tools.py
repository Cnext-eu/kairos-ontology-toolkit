"""Copilot SDK tool definitions for ontology operations.

Defines 5 tools that the Copilot agent can invoke during a chat session:
  - query_ontology
  - propose_change
  - validate_ontology
  - generate_projection
  - apply_change

Tools are created via ``make_tools(token)`` which returns Tool instances
with the GitHub token captured in closures for repo access.
"""

import difflib
import json
import uuid
from typing import Optional

from rdflib import Graph

from kairos_ontology.ontology_ops import (
    ClassInfo,
    add_class,
    add_property,
    list_relationships,
    modify_class,
    parse_ontology_content,
    remove_class,
    serialize_graph,
)
from kairos_ontology.projector import VALID_TARGETS, project_graph
from kairos_ontology.validator import validate_content

from . import github_service as gh


def _class_dict(c: ClassInfo) -> dict:
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


def _domain_to_path(domain: str) -> str:
    name = domain if "." in domain else f"{domain}.ttl"
    return f"{gh.settings.github_ontologies_path}/{name}"


def _unified_diff(old: str, new: str, filename: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(),
            fromfile=f"a/{filename}", tofile=f"b/{filename}",
            lineterm="",
        )
    )


def make_tools(github_token: str) -> list:
    """Create Copilot SDK Tool instances bound to *github_token*.

    Uses the low-level Tool API so closures can capture the token
    without decorator-scope issues.
    """
    from copilot.tools import Tool, ToolInvocation, ToolResult

    # ------------------------------------------------------------------
    # 1. query_ontology
    # ------------------------------------------------------------------
    async def _query(inv: ToolInvocation) -> ToolResult:
        domain = inv.arguments.get("domain")
        search = inv.arguments.get("search")
        try:
            files = await gh.list_ttl_files(github_token)
            results = []
            for f in files:
                if domain and not f["name"].startswith(domain):
                    continue
                content = await gh.read_file(github_token, f["path"])
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
                        if term in c["name"].lower()
                        or term in (c.get("comment") or "").lower()
                    ]
                results.append(entry)
            return ToolResult(
                text_result_for_llm=json.dumps(results, indent=2),
                result_type="success",
            )
        except Exception as exc:
            return ToolResult(
                text_result_for_llm=f"Error querying ontology: {exc}",
                result_type="error",
            )

    query_tool = Tool(
        name="query_ontology",
        description=(
            "Search classes, properties, and relationships in the ontology. "
            "Use to explore the structure before proposing changes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Ontology domain file name (e.g. 'customer')",
                },
                "search": {
                    "type": "string",
                    "description": "Free-text search term to filter classes",
                },
            },
        },
        handler=_query,
        skip_permission=True,
    )

    # ------------------------------------------------------------------
    # 2. propose_change
    # ------------------------------------------------------------------
    async def _propose(inv: ToolInvocation) -> ToolResult:
        domain = inv.arguments.get("domain", "")
        action = inv.arguments.get("action", "")
        details = inv.arguments.get("details", {})
        try:
            file_path = _domain_to_path(domain)
            original = await gh.read_file(github_token, file_path)
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
                return ToolResult(
                    text_result_for_llm=f"Unknown action: {action}",
                    result_type="error",
                )

            new_content = serialize_graph(graph)
            diff = _unified_diff(original, new_content, file_path)
            return ToolResult(
                text_result_for_llm=json.dumps(
                    {"domain": domain, "diff": diff, "new_content": new_content}
                ),
                result_type="success",
                session_log=f"Proposed {action} on {domain}",
            )
        except Exception as exc:
            return ToolResult(
                text_result_for_llm=f"Error proposing change: {exc}",
                result_type="error",
            )

    propose_tool = Tool(
        name="propose_change",
        description=(
            "Propose a modification to the ontology (add/modify class or property). "
            "Returns a unified diff preview and the new TTL content."
        ),
        parameters={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Ontology domain file name"},
                "action": {
                    "type": "string",
                    "enum": ["add_class", "modify_class", "add_property", "remove_class"],
                    "description": "The type of change to make",
                },
                "details": {"type": "object", "description": "Action-specific parameters"},
            },
            "required": ["domain", "action", "details"],
        },
        handler=_propose,
    )

    # ------------------------------------------------------------------
    # 3. validate_ontology
    # ------------------------------------------------------------------
    async def _validate(inv: ToolInvocation) -> ToolResult:
        domain = inv.arguments.get("domain", "")
        try:
            file_path = _domain_to_path(domain)
            content = await gh.read_file(github_token, file_path)
            result = validate_content(content)
            return ToolResult(
                text_result_for_llm=json.dumps(result, indent=2),
                result_type="success",
            )
        except Exception as exc:
            return ToolResult(
                text_result_for_llm=f"Error validating: {exc}",
                result_type="error",
            )

    validate_tool = Tool(
        name="validate_ontology",
        description="Run syntax and SHACL validation on an ontology domain.",
        parameters={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Ontology domain file name"},
            },
            "required": ["domain"],
        },
        handler=_validate,
        skip_permission=True,
    )

    # ------------------------------------------------------------------
    # 4. generate_projection
    # ------------------------------------------------------------------
    async def _project(inv: ToolInvocation) -> ToolResult:
        domain = inv.arguments.get("domain", "")
        targets = inv.arguments.get("targets")
        try:
            file_path = _domain_to_path(domain)
            content = await gh.read_file(github_token, file_path)
            graph = Graph()
            graph.parse(data=content, format="turtle")
            results = project_graph(
                graph,
                targets=targets,
                ontology_name=domain.replace(".ttl", ""),
            )
            return ToolResult(
                text_result_for_llm=json.dumps(
                    {"domain": domain, "targets": results}, indent=2
                ),
                result_type="success",
            )
        except Exception as exc:
            return ToolResult(
                text_result_for_llm=f"Error generating projection: {exc}",
                result_type="error",
            )

    project_tool = Tool(
        name="generate_projection",
        description=(
            "Generate downstream artifacts (dbt, neo4j, azure-search, a2ui, prompt) "
            "from an ontology domain."
        ),
        parameters={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Ontology domain file name"},
                "targets": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": VALID_TARGETS,
                    },
                    "description": "Projection targets (omit for all)",
                },
            },
            "required": ["domain"],
        },
        handler=_project,
        skip_permission=True,
    )

    # ------------------------------------------------------------------
    # 5. apply_change
    # ------------------------------------------------------------------
    async def _apply(inv: ToolInvocation) -> ToolResult:
        domain = inv.arguments.get("domain", "")
        new_content = inv.arguments.get("new_content", "")
        message = inv.arguments.get("message", "ontology: AI-proposed change")
        try:
            file_path = _domain_to_path(domain)
            files = await gh.list_ttl_files(github_token)
            sha = None
            for f in files:
                if f["path"] == file_path:
                    sha = f["sha"]
                    break

            branch_name = f"ontology/ai-{uuid.uuid4().hex[:8]}"
            await gh.create_branch(github_token, branch_name)
            await gh.write_file(
                github_token, file_path, new_content, branch_name, message, sha=sha,
            )
            pr = await gh.create_pull_request(
                github_token,
                branch_name,
                title=message,
                body="Proposed by Kairos Ontology AI assistant.",
            )
            return ToolResult(
                text_result_for_llm=json.dumps(
                    {"branch": branch_name, "pull_request": pr.get("html_url")}
                ),
                result_type="success",
                session_log=f"Created PR from branch {branch_name}",
            )
        except Exception as exc:
            return ToolResult(
                text_result_for_llm=f"Error applying change: {exc}",
                result_type="error",
            )

    apply_tool = Tool(
        name="apply_change",
        description=(
            "Commit a proposed change to a feature branch and open a pull request. "
            "Only call this after the user has reviewed and approved a proposed change."
        ),
        parameters={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Domain file to change"},
                "new_content": {"type": "string", "description": "Full TTL content to write"},
                "message": {"type": "string", "description": "Commit / PR title"},
            },
            "required": ["domain", "new_content", "message"],
        },
        handler=_apply,
    )

    return [query_tool, propose_tool, validate_tool, project_tool, apply_tool]
