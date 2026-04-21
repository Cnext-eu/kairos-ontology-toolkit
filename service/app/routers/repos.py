# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Repository discovery and selection router."""

from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException

from ..config import get_github_service, settings

router = APIRouter()


@router.get("/")
async def list_repos(
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """List ontology hub repos accessible to the authenticated user or App."""
    token = _extract_token(authorization) if authorization else None

    if settings.dev_mode:
        # In dev mode, try PAT-based discovery first
        pat = token if token and token != "dev-token" else settings.dev_github_token
        if pat:
            try:
                repos = await _list_repos_via_pat(pat)
                if repos:
                    return repos
            except Exception:
                pass
        # Fall back to configured repo stub
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

    gh = get_github_service()
    repos = await gh.list_repos()
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


async def _list_repos_via_pat(pat: str) -> list[dict]:
    """Discover repos via a user PAT (GET /user/repos)."""
    url = "https://api.github.com/user/repos"
    repos = []
    page = 1
    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {pat}",
                    "Accept": "application/vnd.github+json",
                },
                params={"per_page": 100, "page": page, "sort": "updated"},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            for r in data:
                # Include repos that look like ontology hubs OR have ontologies/ dir
                if r["name"].endswith("-ontology-hub") or r.get("topics") and "ontology" in r.get("topics", []):
                    repos.append({
                        "owner": r["owner"]["login"],
                        "name": r["name"],
                        "full_name": r["full_name"],
                        "description": r.get("description") or "",
                        "default_branch": r.get("default_branch", "main"),
                    })
            if len(data) < 100:
                break
            page += 1
    return repos


def _extract_token(authorization: str) -> str:
    if authorization.lower().startswith("bearer "):
        return authorization[7:]
    return authorization
