"""Repository discovery and selection router."""

from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from ..config import get_github_service, settings

router = APIRouter()


@router.get("/")
async def list_repos(
    authorization: str = Header(..., alias="Authorization"),
):
    """List ontology hub repos accessible to the GitHub App."""
    token = _extract_token(authorization)
    gh = get_github_service()

    if settings.dev_mode:
        # In dev mode, return just the configured repo
        return [
            {
                "owner": settings.github_repo_owner or "local",
                "name": settings.github_repo_name or "dev",
                "full_name": (
                    f"{settings.github_repo_owner}/{settings.github_repo_name}"
                ),
                "description": "Local development",
                "default_branch": settings.github_default_branch,
            }
        ]

    repos = await gh.list_repos(token)
    return repos


@router.get("/active")
async def get_active_repo():
    """Return the currently active repo configuration."""
    return {
        "owner": settings.github_repo_owner,
        "name": settings.github_repo_name,
        "default_branch": settings.github_default_branch,
        "ontologies_path": settings.github_ontologies_path,
    }


def _extract_token(authorization: str) -> str:
    if authorization.lower().startswith("bearer "):
        return authorization[7:]
    return authorization
