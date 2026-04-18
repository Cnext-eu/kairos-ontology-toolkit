"""Validation router — syntax and SHACL validation for ontologies."""

from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from kairos_ontology.validator import validate_content

from ..services import github_service as gh

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
):
    """Validate an ontology domain from the repo."""
    token = _extract_token(authorization)
    file_path = _domain_to_path(req.domain)
    content = await gh.read_file(token, file_path)
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
    name = domain if "." in domain else f"{domain}.ttl"
    return f"{gh.settings.github_ontologies_path}/{name}"
