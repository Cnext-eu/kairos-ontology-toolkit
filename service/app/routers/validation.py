"""Validation router — syntax and SHACL validation for ontologies."""

from typing import Optional

from fastapi import APIRouter, Header
from pydantic import BaseModel

from kairos_ontology.validator import validate_content

from ..config import get_github_service, settings

router = APIRouter()


class ValidateRequest(BaseModel):
    domain: str
    shapes_content: Optional[str] = None


class ValidateContentRequest(BaseModel):
    ontology_content: str
    shapes_content: Optional[str] = None


@router.post("")
async def validate_domain(
    req: ValidateRequest,
    authorization: str = Header(..., alias="Authorization"),
    repo_owner: Optional[str] = Header(None, alias="X-Kairos-Repo-Owner"),
    repo_name: Optional[str] = Header(None, alias="X-Kairos-Repo-Name"),
):
    """Validate an ontology domain from the repo."""
    token = _extract_token(authorization)
    file_path = _domain_to_path(req.domain)
    gh = get_github_service()
    content = await gh.read_file(token, file_path, owner=repo_owner, repo=repo_name)
    return validate_content(content, shapes_content=req.shapes_content)


@router.post("/content")
async def validate_raw(req: ValidateContentRequest):
    """Validate raw TTL content (for previewing AI changes before commit)."""
    return validate_content(req.ontology_content, shapes_content=req.shapes_content)


def _extract_token(authorization: str) -> str:
    if authorization.lower().startswith("bearer "):
        return authorization[7:]
    return authorization


def _domain_to_path(domain: str) -> str:
    # Sanitise: strip path separators to prevent traversal
    safe = domain.replace("/", "").replace("\\", "").replace("..", "")
    name = safe if "." in safe else f"{safe}.ttl"
    return f"{settings.github_ontologies_path}/{name}"
