# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
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
    modify_class,
    parse_ontology_content,
    remove_class,
    remove_property,
    serialize_graph,
)

from ..config import get_github_service, settings

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


class BatchChange(BaseModel):
    domain: str
    action: str
    details: dict


class BatchApplyRequest(BaseModel):
    changes: list[BatchChange]
    message: str = "ontology: batch changes"
    create_pr: bool = True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/query")
async def query_ontology(
    domain: Optional[str] = None,
    search: Optional[str] = None,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    repo_owner: Optional[str] = Header(None, alias="X-Kairos-Repo-Owner"),
    repo_name: Optional[str] = Header(None, alias="X-Kairos-Repo-Name"),
):
    """List / search classes, properties, and relationships.

    No user auth required — repo access is handled by the GitHub App.
    """
    gh = get_github_service()
    files = await gh.list_ttl_files(owner=repo_owner, repo=repo_name)

    results = []
    for f in files:
        if domain and not f["name"].startswith(domain):
            continue
        try:
            content = await gh.read_file(f["path"], owner=repo_owner, repo=repo_name)
            info = parse_ontology_content(content)
        except Exception:
            # Skip files that cannot be read or parsed rather than crashing
            continue
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
    authorization: Optional[str] = Header(None, alias="Authorization"),
    repo_owner: Optional[str] = Header(None, alias="X-Kairos-Repo-Owner"),
    repo_name: Optional[str] = Header(None, alias="X-Kairos-Repo-Name"),
):
    """Propose a TTL change and return a diff preview.

    No user auth required — repo access is handled by the GitHub App.
    """
    file_path = _domain_to_path(req.domain)
    gh = get_github_service()
    original = await gh.read_file(file_path, owner=repo_owner, repo=repo_name)

    graph = Graph()
    graph.parse(data=original, format="turtle")

    info = parse_ontology_content(original)
    ns = info.namespace

    # Apply the requested mutation
    _apply_action(graph, ns, req.action, dict(req.details))

    new_content = serialize_graph(graph)
    diff = _unified_diff(original, new_content, file_path)

    return {"domain": req.domain, "diff": diff, "new_content": new_content}


@router.post("/apply")
async def apply_change(
    req: ApplyRequest,
    authorization: str = Header(..., alias="Authorization"),
    repo_owner: Optional[str] = Header(None, alias="X-Kairos-Repo-Owner"),
    repo_name: Optional[str] = Header(None, alias="X-Kairos-Repo-Name"),
):
    """Commit proposed TTL content to a feature branch and create a PR."""
    file_path = _domain_to_path(req.domain)

    # Get current file SHA (needed for update)
    gh = get_github_service()
    files = await gh.list_ttl_files(owner=repo_owner, repo=repo_name)
    sha = None
    for f in files:
        if f["path"] == file_path:
            sha = f["sha"]
            break

    branch_name = f"ontology/ai-{uuid.uuid4().hex[:8]}"
    await gh.create_branch(branch_name, owner=repo_owner, repo=repo_name)
    await gh.write_file(
        file_path, req.new_content, branch_name, req.message,
        sha=sha, owner=repo_owner, repo=repo_name,
    )
    pr = await gh.create_pull_request(
        branch_name,
        title=req.message,
        body="Proposed by Kairos Ontology AI assistant.",
        owner=repo_owner,
        repo=repo_name,
    )
    return {"branch": branch_name, "pull_request": pr.get("html_url")}


@router.post("/batch-apply")
async def batch_apply(
    req: BatchApplyRequest,
    authorization: str = Header(..., alias="Authorization"),
    repo_owner: Optional[str] = Header(None, alias="X-Kairos-Repo-Owner"),
    repo_name: Optional[str] = Header(None, alias="X-Kairos-Repo-Name"),
):
    """Apply multiple changes atomically: one branch, one commit per domain, one PR."""
    if not req.changes:
        raise HTTPException(400, "No changes provided")

    gh = get_github_service()

    # Group changes by domain
    domain_changes: dict[str, list[BatchChange]] = {}
    for c in req.changes:
        domain_changes.setdefault(c.domain, []).append(c)

    branch_name = f"ontology/batch-{uuid.uuid4().hex[:8]}"
    await gh.create_branch(branch_name, owner=repo_owner, repo=repo_name)

    files = await gh.list_ttl_files(owner=repo_owner, repo=repo_name)
    file_sha_map = {f["path"]: f["sha"] for f in files}

    results = []
    for domain, changes in domain_changes.items():
        file_path = _domain_to_path(domain)
        original = await gh.read_file(file_path, owner=repo_owner, repo=repo_name)
        graph = Graph()
        graph.parse(data=original, format="turtle")
        info = parse_ontology_content(original)
        ns = info.namespace

        for c in changes:
            d = dict(c.details)
            _apply_action(graph, ns, c.action, d)

        new_content = serialize_graph(graph)
        sha = file_sha_map.get(file_path)
        await gh.write_file(
            file_path, new_content, branch_name, req.message,
            sha=sha, owner=repo_owner, repo=repo_name,
        )
        results.append({"domain": domain, "changes_applied": len(changes)})

    pr_url = None
    if req.create_pr:
        pr = await gh.create_pull_request(
            branch_name,
            title=req.message,
            body=f"Batch update: {sum(len(v) for v in domain_changes.values())} changes "
                 f"across {len(domain_changes)} domain(s).\n\nProposed by Kairos WebUI.",
            owner=repo_owner,
            repo=repo_name,
        )
        pr_url = pr.get("html_url")

    return {"branch": branch_name, "pull_request": pr_url, "domains": results}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_token(authorization: str) -> str:
    if authorization.lower().startswith("bearer "):
        return authorization[7:]
    return authorization


def _domain_to_path(domain: str) -> str:
    # Sanitise: strip path separators to prevent traversal
    safe = domain.replace("/", "").replace("\\", "").replace("..", "")
    name = safe if "." in safe else f"{safe}.ttl"
    base = settings.github_ontologies_path
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


def _apply_action(graph: Graph, ns: str, action: str, details: dict):
    """Apply a single mutation action to a graph. Mutates *details* dict."""
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
    elif action == "remove_property":
        uri = details.get("property_uri") or f"{ns}{details.get('property_name', '')}"
        remove_property(graph, uri)
    else:
        raise HTTPException(400, f"Unknown action: {action}")
