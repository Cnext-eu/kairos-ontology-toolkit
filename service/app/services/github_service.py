# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""GitHub REST API wrapper — read files, create branches, commits, PRs.

All repo operations are stateless (no local cloning).  Uses httpx for async calls.
Authenticates via a GitHub App installation token (JWT → installation token exchange).
"""

import base64
import time
from typing import Optional

import httpx

from ..config import settings

_BASE = "https://api.github.com"

# Cached installation token
_install_token: Optional[str] = None
_install_token_expires: float = 0


def _build_jwt() -> str:
    """Build a JWT signed with the GitHub App's private key."""
    import jwt  # PyJWT

    iat = int(time.time()) - 60  # 60s clock-skew buffer
    payload = {
        "iat": iat,
        "exp": iat + (9 * 60),  # 9 min from iat — stays within GitHub's 10-min window
        "iss": settings.github_app_id,  # must remain a string per GitHub API
    }
    # Private key may have escaped newlines from .env
    private_key = settings.github_app_private_key.replace("\\n", "\n")
    return jwt.encode(payload, private_key, algorithm="RS256")


async def _get_installation_token() -> str:
    """Return a GitHub App installation token.

    Generates a JWT from the app's private key, then exchanges it for
    a short-lived installation access token via the GitHub API.
    Caches the token until near expiry.
    """
    global _install_token, _install_token_expires

    # Return cached token if still valid (with 5 min buffer)
    if _install_token and time.time() < (_install_token_expires - 300):
        return _install_token

    jwt_token = _build_jwt()
    url = f"{_BASE}/app/installations/{settings.github_installation_id}/access_tokens"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()

    data = resp.json()
    _install_token = data["token"]
    # GitHub installation tokens expire after 1 hour
    _install_token_expires = time.time() + 3600
    return _install_token


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _validate_owner(owner: str | None) -> str:
    """Ensure the requested owner matches the configured org to prevent confused-deputy attacks."""
    o = owner or settings.github_repo_owner
    allowed = settings.github_repo_owner
    if allowed and o.lower() != allowed.lower():
        raise ValueError(
            f"Repo owner '{o}' is not allowed. Only '{allowed}' repos are accessible."
        )
    return o


def _repo_url(owner: str | None = None, repo: str | None = None) -> str:
    o = _validate_owner(owner)
    r = repo or settings.github_repo_name
    return f"{_BASE}/repos/{o}/{r}"


# ---- Repo discovery --------------------------------------------------------

async def list_repos() -> list[dict]:
    """List ontology hub repos accessible to the GitHub App installation."""
    install_token = await _get_installation_token()
    url = f"{_BASE}/installation/repositories"
    repos = []
    page = 1
    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.get(
                url,
                headers=_headers(install_token),
                params={"per_page": 100, "page": page},
            )
            resp.raise_for_status()
            data = resp.json()
            for r in data.get("repositories", []):
                if r["name"].endswith("-ontology-hub"):
                    repos.append({
                        "owner": r["owner"]["login"],
                        "name": r["name"],
                        "full_name": r["full_name"],
                        "description": r.get("description") or "",
                        "default_branch": r.get("default_branch", "main"),
                    })
            if len(data.get("repositories", [])) < 100:
                break
            page += 1
    return repos

async def _token() -> str:
    """Return the installation token for all API calls."""
    return await _get_installation_token()


# ---- Read ------------------------------------------------------------------

async def list_ttl_files(
    path: Optional[str] = None,
    branch: Optional[str] = None,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
) -> list[dict]:
    """List ontology files (*.ttl, *.rdf) under *path* in the repo.

    If the configured path returns nothing, falls back to ``ontologies/``
    at the repo root so repos with a flat layout are also supported.
    """
    t = await _token()
    primary_path = path or settings.github_ontologies_path
    branch = branch or settings.github_default_branch
    fallback_paths = [primary_path, "ontologies"]

    async with httpx.AsyncClient() as client:
        for candidate in dict.fromkeys(fallback_paths):  # deduplicate, preserve order
            url = f"{_repo_url(owner, repo)}/contents/{candidate}"
            resp = await client.get(url, headers=_headers(t), params={"ref": branch})
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            items = resp.json()
            if not isinstance(items, list):
                items = [items]
            files = [
                {"name": f["name"], "path": f["path"], "sha": f["sha"], "size": f["size"]}
                for f in items
                if f["name"].endswith((".ttl", ".rdf"))
            ]
            if files:
                return files
    return []


async def read_file(
    path: str = "",
    branch: Optional[str] = None,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
) -> str:
    """Read a file's content from the repo (decoded from base64)."""
    t = await _token()
    branch = branch or settings.github_default_branch
    url = f"{_repo_url(owner, repo)}/contents/{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(t), params={"ref": branch})
        resp.raise_for_status()
    data = resp.json()
    return base64.b64decode(data["content"]).decode("utf-8")


_APPLICATION_MODELS_PATH = "ontology-hub/output/medallion/silver"
_APPLICATION_MODELS_FALLBACK_PATHS = [
    "ontology-hub/output/medallion/silver",
    "output/medallion/silver",
]


async def list_mmd_files(
    branch: Optional[str] = None,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
) -> list[dict]:
    """List Mermaid class-diagram files (*.mmd) in the silver output folder.

    Tries ``ontology-hub/output/medallion/silver/`` first, then falls back to
    ``output/medallion/silver/`` for repos with a flat layout.
    """
    t = await _token()
    branch = branch or settings.github_default_branch
    async with httpx.AsyncClient() as client:
        for candidate in dict.fromkeys(_APPLICATION_MODELS_FALLBACK_PATHS):
            url = f"{_repo_url(owner, repo)}/contents/{candidate}"
            resp = await client.get(url, headers=_headers(t), params={"ref": branch})
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            items = resp.json()
            if not isinstance(items, list):
                items = [items]
            files = [
                {"name": f["name"], "path": f["path"], "sha": f["sha"], "size": f["size"]}
                for f in items
                if f["name"].endswith(".mmd")
            ]
            if files:
                return files
    return []


async def read_mmd_file(
    name: str,
    branch: Optional[str] = None,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
) -> str:
    """Read the content of a Mermaid file, trying all known folder locations."""
    safe_name = name.replace("/", "").replace("\\", "").replace("..", "")
    if not safe_name.endswith(".mmd"):
        safe_name += ".mmd"
    t = await _token()
    branch = branch or settings.github_default_branch
    async with httpx.AsyncClient() as client:
        for candidate in dict.fromkeys(_APPLICATION_MODELS_FALLBACK_PATHS):
            url = f"{_repo_url(owner, repo)}/contents/{candidate}/{safe_name}"
            resp = await client.get(url, headers=_headers(t), params={"ref": branch})
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            data = resp.json()
            return base64.b64decode(data["content"]).decode("utf-8")
    raise FileNotFoundError(f"Application model '{safe_name}' not found in any known path.")


# ---- Write -----------------------------------------------------------------

async def create_branch(
    branch_name: str = "",
    from_branch: Optional[str] = None,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
) -> dict:
    """Create a new branch from *from_branch* (defaults to main)."""
    t = await _token()
    from_branch = from_branch or settings.github_default_branch
    base = _repo_url(owner, repo)
    url = f"{base}/git/ref/heads/{from_branch}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(t))
        resp.raise_for_status()
        sha = resp.json()["object"]["sha"]

        resp = await client.post(
            f"{base}/git/refs",
            headers=_headers(t),
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
        )
        resp.raise_for_status()
    return resp.json()


async def write_file(
    path: str = "",
    content: str = "",
    branch: str = "",
    message: str = "",
    sha: Optional[str] = None,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
) -> dict:
    """Create or update a file via the Contents API."""
    t = await _token()
    url = f"{_repo_url(owner, repo)}/contents/{path}"
    body: dict = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    async with httpx.AsyncClient() as client:
        resp = await client.put(url, headers=_headers(t), json=body)
        resp.raise_for_status()
    return resp.json()


async def create_pull_request(
    branch: str = "",
    title: str = "",
    body: str = "",
    base: Optional[str] = None,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
) -> dict:
    """Create a pull request from *branch* into *base*."""
    t = await _token()
    base = base or settings.github_default_branch
    url = f"{_repo_url(owner, repo)}/pulls"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers=_headers(t),
            json={"title": title, "body": body, "head": branch, "base": base},
        )
        resp.raise_for_status()
    return resp.json()


# ---- Compare / diff --------------------------------------------------------

async def compare_branches(
    base: str = "",
    head: str = "",
    owner: Optional[str] = None,
    repo: Optional[str] = None,
) -> dict:
    """Return the comparison (diff) between two branches."""
    t = await _token()
    url = f"{_repo_url(owner, repo)}/compare/{base}...{head}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(t))
        resp.raise_for_status()
    return resp.json()
