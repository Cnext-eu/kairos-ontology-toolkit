"""Copilot SDK tool definitions for ontology operations.

Defines 9 tools that the Copilot agent can invoke during a chat session:
  - query_ontology
  - propose_change
  - validate_ontology
  - generate_projection
  - apply_change
  - scaffold_hub
  - create_domain
  - explain_ontology
  - suggest_improvements

Tools are created via ``make_tools(token)`` which returns Tool instances
with the GitHub token captured in closures for repo access.
"""

import difflib
import json
import uuid
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from rdflib import Graph

from kairos_ontology.ontology_ops import (
    ClassInfo,
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

    # ------------------------------------------------------------------
    # 6. scaffold_hub
    # ------------------------------------------------------------------
    async def _scaffold(inv: ToolInvocation) -> ToolResult:
        domain_name = inv.arguments.get("domain_name", "example")
        description = inv.arguments.get("description", "Business domain ontology")
        namespace = inv.arguments.get(
            "namespace", f"http://kairos.example/ontology/{domain_name}#"
        )
        try:
            # Render starter ontology from template
            tmpl_dir = Path(__file__).resolve().parent.parent / "templates"
            env = Environment(loader=FileSystemLoader(str(tmpl_dir)))
            tmpl = env.get_template("domain_starter.ttl.jinja2")
            ttl_content = tmpl.render(
                namespace=namespace,
                label=f"{domain_name.replace('-', ' ').title()} Ontology",
                description=description,
                classes=[{
                    "name": domain_name.replace("-", " ").title().replace(" ", ""),
                    "label": domain_name.replace("-", " ").title(),
                    "comment": description,
                    "superclass": None,
                    "properties": [{
                        "name": f"{domain_name.replace('-', '')}Name",
                        "label": f"{domain_name.replace('-', ' ').title()} Name",
                        "range": "xsd:string",
                    }],
                }],
            )

            branch_name = f"ontology/setup-{domain_name}-{uuid.uuid4().hex[:6]}"
            await gh.create_branch(github_token, branch_name)

            base = gh.settings.github_ontologies_path
            await gh.write_file(
                github_token,
                f"{base}/{domain_name}.ttl",
                ttl_content,
                branch_name,
                f"ontology: scaffold {domain_name} domain",
            )

            # Create shapes placeholder
            shapes_placeholder = (
                f"# SHACL shapes for {domain_name} domain\n"
                f"# Add validation constraints here.\n"
            )
            await gh.write_file(
                github_token,
                f"shapes/{domain_name}.shacl.ttl",
                shapes_placeholder,
                branch_name,
                f"ontology: add shapes placeholder for {domain_name}",
            )

            pr = await gh.create_pull_request(
                github_token,
                branch_name,
                title=f"ontology: scaffold {domain_name} hub",
                body=(
                    f"Scaffolds the **{domain_name}** ontology domain.\n\n"
                    f"- `{base}/{domain_name}.ttl` — starter ontology\n"
                    f"- `shapes/{domain_name}.shacl.ttl` — SHACL shapes placeholder\n"
                ),
            )
            return ToolResult(
                text_result_for_llm=json.dumps({
                    "branch": branch_name,
                    "pull_request": pr.get("html_url"),
                    "files_created": [
                        f"{base}/{domain_name}.ttl",
                        f"shapes/{domain_name}.shacl.ttl",
                    ],
                }),
                result_type="success",
                session_log=f"Scaffolded hub for {domain_name}",
            )
        except Exception as exc:
            return ToolResult(
                text_result_for_llm=f"Error scaffolding hub: {exc}",
                result_type="error",
            )

    scaffold_tool = Tool(
        name="scaffold_hub",
        description=(
            "Create a new ontology hub structure in the repository. "
            "Creates a starter .ttl file and SHACL shapes placeholder on a feature branch, "
            "then opens a pull request."
        ),
        parameters={
            "type": "object",
            "properties": {
                "domain_name": {
                    "type": "string",
                    "description": "Domain name (e.g., 'customer', 'sales-order')",
                },
                "description": {
                    "type": "string",
                    "description": "Brief description of the domain",
                },
                "namespace": {
                    "type": "string",
                    "description": "Ontology namespace URI (optional, auto-generated if omitted)",
                },
            },
            "required": ["domain_name", "description"],
        },
        handler=_scaffold,
    )

    # ------------------------------------------------------------------
    # 7. create_domain
    # ------------------------------------------------------------------
    async def _create_domain(inv: ToolInvocation) -> ToolResult:
        domain_name = inv.arguments.get("domain_name", "example")
        description = inv.arguments.get("description", "")
        classes = inv.arguments.get("classes", [])
        namespace = inv.arguments.get(
            "namespace", f"http://kairos.example/ontology/{domain_name}#"
        )
        try:
            tmpl_dir = Path(__file__).resolve().parent.parent / "templates"
            env = Environment(loader=FileSystemLoader(str(tmpl_dir)))
            tmpl = env.get_template("domain_starter.ttl.jinja2")

            # Normalize class definitions
            tmpl_classes = []
            for cls in classes:
                name = cls.get("name", "Thing")
                props = []
                for p in cls.get("properties", []):
                    p_name = p if isinstance(p, str) else p.get("name", "")
                    p_range = (
                        "xsd:string" if isinstance(p, str) else p.get("range", "xsd:string")
                    )
                    p_label = (
                        p_name.replace("_", " ").title()
                        if isinstance(p, str)
                        else p.get("label", p_name)
                    )
                    props.append({"name": p_name, "range": p_range, "label": p_label})
                tmpl_classes.append({
                    "name": name,
                    "label": cls.get("label", name),
                    "comment": cls.get("comment", ""),
                    "superclass": cls.get("superclass"),
                    "properties": props,
                })

            ttl_content = tmpl.render(
                namespace=namespace,
                label=f"{domain_name.replace('-', ' ').title()} Ontology",
                description=description,
                classes=tmpl_classes,
            )

            # Validate the generated TTL
            validation = validate_content(ttl_content)
            return ToolResult(
                text_result_for_llm=json.dumps({
                    "domain": domain_name,
                    "ttl_content": ttl_content,
                    "validation": validation,
                    "class_count": len(tmpl_classes),
                }, indent=2),
                result_type="success",
            )
        except Exception as exc:
            return ToolResult(
                text_result_for_llm=f"Error creating domain: {exc}",
                result_type="error",
            )

    create_domain_tool = Tool(
        name="create_domain",
        description=(
            "Generate a complete starter ontology (valid TTL) from a structured description. "
            "Returns the content for review — does NOT write to the repository."
        ),
        parameters={
            "type": "object",
            "properties": {
                "domain_name": {
                    "type": "string",
                    "description": "Domain name (e.g., 'customer')",
                },
                "description": {
                    "type": "string",
                    "description": "What this domain represents",
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace URI (optional, auto-generated if omitted)",
                },
                "classes": {
                    "type": "array",
                    "description": "List of class definitions",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "PascalCase class name",
                            },
                            "label": {"type": "string"},
                            "comment": {"type": "string"},
                            "superclass": {
                                "type": "string",
                                "description": "Parent class name",
                            },
                            "properties": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "range": {
                                            "type": "string",
                                            "description": "XSD type",
                                        },
                                        "label": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
            "required": ["domain_name", "description", "classes"],
        },
        handler=_create_domain,
        skip_permission=True,
    )

    # ------------------------------------------------------------------
    # 8. explain_ontology
    # ------------------------------------------------------------------
    async def _explain(inv: ToolInvocation) -> ToolResult:
        domain = inv.arguments.get("domain", "")
        try:
            file_path = _domain_to_path(domain)
            content = await gh.read_file(github_token, file_path)
            info = parse_ontology_content(content)

            explanation = {
                "domain": domain,
                "namespace": info.namespace,
                "summary": (
                    f"The {domain} ontology defines {len(info.classes)} class(es) "
                    f"and {len(info.relationships)} relationship(s)."
                ),
                "classes": [],
                "relationships": [],
            }

            for cls in info.classes:
                cls_info = {
                    "name": cls.name,
                    "description": cls.comment or "(no description)",
                    "superclasses": cls.superclasses,
                    "properties": [
                        {
                            "name": p.name,
                            "type": p.range_name,
                            "kind": "object" if p.is_object_property else "data",
                        }
                        for p in cls.properties
                    ],
                }
                explanation["classes"].append(cls_info)

            for rel in info.relationships:
                explanation["relationships"].append({
                    "name": rel.name,
                    "from": rel.domain,
                    "to": rel.range,
                })

            return ToolResult(
                text_result_for_llm=json.dumps(explanation, indent=2),
                result_type="success",
            )
        except Exception as exc:
            return ToolResult(
                text_result_for_llm=f"Error explaining ontology: {exc}",
                result_type="error",
            )

    explain_tool = Tool(
        name="explain_ontology",
        description=(
            "Generate a structured human-readable explanation of an ontology domain. "
            "Shows classes, properties, relationships, and a summary."
        ),
        parameters={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Ontology domain name"},
            },
            "required": ["domain"],
        },
        handler=_explain,
        skip_permission=True,
    )

    # ------------------------------------------------------------------
    # 9. suggest_improvements
    # ------------------------------------------------------------------
    async def _suggest(inv: ToolInvocation) -> ToolResult:
        domain = inv.arguments.get("domain", "")
        try:
            file_path = _domain_to_path(domain)
            content = await gh.read_file(github_token, file_path)
            info = parse_ontology_content(content)

            suggestions = []

            for cls in info.classes:
                if not cls.comment:
                    suggestions.append({
                        "type": "missing_comment",
                        "severity": "warning",
                        "target": cls.name,
                        "message": f"Class '{cls.name}' has no rdfs:comment.",
                        "fix": f"Add rdfs:comment describing what {cls.name} represents.",
                    })
                if not cls.label:
                    suggestions.append({
                        "type": "missing_label",
                        "severity": "warning",
                        "target": cls.name,
                        "message": f"Class '{cls.name}' has no rdfs:label.",
                        "fix": "Add rdfs:label with a human-friendly name.",
                    })
                if not cls.properties and not cls.superclasses:
                    suggestions.append({
                        "type": "no_properties",
                        "severity": "info",
                        "target": cls.name,
                        "message": f"Class '{cls.name}' has no properties.",
                        "fix": "Consider adding datatype or object properties.",
                    })
                # Naming convention check
                if cls.name and not cls.name[0].isupper():
                    suggestions.append({
                        "type": "naming_convention",
                        "severity": "warning",
                        "target": cls.name,
                        "message": f"Class '{cls.name}' should use PascalCase.",
                        "fix": f"Rename to '{cls.name[0].upper() + cls.name[1:]}'.",
                    })

            # Check for SHACL shapes
            suggestions.append({
                "type": "shacl_shapes",
                "severity": "info",
                "target": domain,
                "message": (
                    f"Consider adding SHACL shapes for the {domain} domain "
                    f"to enforce property constraints."
                ),
                "fix": f"Create shapes/{domain}.shacl.ttl with NodeShape constraints.",
            })

            # Check isolated classes (no relationships to/from)
            rel_participants = set()
            for rel in info.relationships:
                rel_participants.add(rel.domain)
                rel_participants.add(rel.range)
            for cls in info.classes:
                if cls.name not in rel_participants and len(info.classes) > 1:
                    suggestions.append({
                        "type": "isolated_class",
                        "severity": "info",
                        "target": cls.name,
                        "message": (
                            f"Class '{cls.name}' has no relationships to other classes."
                        ),
                        "fix": "Consider adding object properties to connect it.",
                    })

            return ToolResult(
                text_result_for_llm=json.dumps({
                    "domain": domain,
                    "suggestion_count": len(suggestions),
                    "suggestions": suggestions,
                }, indent=2),
                result_type="success",
            )
        except Exception as exc:
            return ToolResult(
                text_result_for_llm=f"Error analyzing ontology: {exc}",
                result_type="error",
            )

    suggest_tool = Tool(
        name="suggest_improvements",
        description=(
            "Analyze an ontology domain and return actionable improvement suggestions. "
            "Checks for missing labels, comments, naming conventions, isolated classes, "
            "and SHACL shape coverage."
        ),
        parameters={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Ontology domain name"},
            },
            "required": ["domain"],
        },
        handler=_suggest,
        skip_permission=True,
    )

    return [query_tool, propose_tool, validate_tool, project_tool, apply_tool,
            scaffold_tool, create_domain_tool, explain_tool, suggest_tool]
