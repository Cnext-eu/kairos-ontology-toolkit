"""Projection router — generate downstream artifacts from ontologies."""

from typing import List, Optional

from fastapi import APIRouter, Header
from pydantic import BaseModel
from rdflib import Graph

from kairos_ontology.projector import VALID_TARGETS, project_graph

from ..config import get_github_service, settings

router = APIRouter()


class ProjectRequest(BaseModel):
    domain: str
    targets: Optional[List[str]] = None


@router.get("/targets")
async def list_targets():
    """Return available projection targets."""
    return {"targets": VALID_TARGETS}


@router.post("")
async def generate_projection(
    req: ProjectRequest,
    authorization: str = Header(..., alias="Authorization"),
):
    """Generate projection artifacts for a domain."""
    token = _extract_token(authorization)
    file_path = _domain_to_path(req.domain)
    gh = get_github_service()
    content = await gh.read_file(token, file_path)

    graph = Graph()
    graph.parse(data=content, format="turtle")

    results = project_graph(
        graph,
        targets=req.targets,
        ontology_name=req.domain.replace(".ttl", ""),
    )
    return {"domain": req.domain, "targets": results}


def _extract_token(authorization: str) -> str:
    if authorization.lower().startswith("bearer "):
        return authorization[7:]
    return authorization


def _domain_to_path(domain: str) -> str:
    name = domain if "." in domain else f"{domain}.ttl"
    return f"{settings.github_ontologies_path}/{name}"
