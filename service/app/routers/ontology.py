"""Ontology CRUD router — query, propose changes, and apply them
via feature branches and pull requests.
"""

import difflib
import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from rdflib import Graph

from kairos_ontology.ontology_ops import (
    ClassInfo,
    add_class,
    add_property,
    list_classes,
    list_properties,
    list_relationships,
    modify_class,
    parse_ontology_content,
    remove_class,
    serialize_graph,
)

from ..services import github_service as gh

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    domain: Optional[str] = None
    search: Optional[str] = None


class ChangeRequest(BaseModel):
    domain: str
    action: str  # add_class | modify_class | add_property | remove_class
    details: dict


class ApplyRequest(BaseModel):
    domain: str
    new_content: str
    message: str = "ontology: AI-proposed change"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/query")
async def query_ontology(
    domain: Optional[str] = None,
    search: Optional[str] = None,
    authorization: str = Header(..., alias="Authorization"),
):
    """List / search classes, properties, and relationships."""
    token = _extract_token(authorization)
    files = await gh.list_ttl_files(token)

    results = []
    for f in files:
        if domain and not f["name"].startswith(domain):
            continue
        content = await gh.read_file(token, f["path"])
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
                if term in c["name"].lower() or term in c.get("comment", "").lower()
            ]
        results.append(entry)
    return results


@router.post("/change")
async def propose_change(
    req: ChangeRequest,
    authorization: str = Header(..., alias="Authorization"),
):
    """Propose a TTL change and return a diff preview."""
    token = _extract_token(authorization)
    file_path = _domain_to_path(req.domain)
    original = await gh.read_file(token, file_path)

    graph = Graph()
    graph.parse(data=original, format="turtle")

    info = parse_ontology_content(original)
    ns = info.namespace

    # Apply the requested mutation
    if req.action == "add_class":
        add_class(graph, ns, **req.details)
    elif req.action == "modify_class":
        uri = req.details.pop("class_uri", None) or f"{ns}{req.details.pop('class_name', '')}"
        modify_class(graph, uri, **req.details)
    elif req.action == "add_property":
        domain_uri = req.details.pop("domain_uri", None)
        if not domain_uri:
            cname = req.details.pop("domain_class", "")
            domain_uri = f"{ns}{cname}"
        add_property(graph, ns, domain_uri=domain_uri, **req.details)
    elif req.action == "remove_class":
        uri = req.details.get("class_uri") or f"{ns}{req.details.get('class_name', '')}"
        remove_class(graph, uri)
    else:
        raise HTTPException(400, f"Unknown action: {req.action}")

    new_content = serialize_graph(graph)
    diff = _unified_diff(original, new_content, file_path)

    return {"domain": req.domain, "diff": diff, "new_content": new_content}


@router.post("/apply")
async def apply_change(
    req: ApplyRequest,
    authorization: str = Header(..., alias="Authorization"),
):
    """Commit proposed TTL content to a feature branch and create a PR."""
    token = _extract_token(authorization)
    file_path = _domain_to_path(req.domain)

    # Get current file SHA (needed for update)
    files = await gh.list_ttl_files(token)
    sha = None
    for f in files:
        if f["path"] == file_path:
            sha = f["sha"]
            break

    branch_name = f"ontology/ai-{uuid.uuid4().hex[:8]}"
    await gh.create_branch(token, branch_name)
    await gh.write_file(token, file_path, req.new_content, branch_name, req.message, sha=sha)
    pr = await gh.create_pull_request(
        token,
        branch_name,
        title=req.message,
        body="Proposed by Kairos Ontology AI assistant.",
    )
    return {"branch": branch_name, "pull_request": pr.get("html_url")}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_token(authorization: str) -> str:
    if authorization.lower().startswith("bearer "):
        return authorization[7:]
    return authorization


def _domain_to_path(domain: str) -> str:
    name = domain if "." in domain else f"{domain}.ttl"
    base = gh.settings.github_ontologies_path
    return f"{base}/{name}"


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


def _unified_diff(old: str, new: str, filename: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(),
            fromfile=f"a/{filename}", tofile=f"b/{filename}",
            lineterm="",
        )
    )
