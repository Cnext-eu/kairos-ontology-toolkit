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

    now = int(time.time())
    payload = {
        "iat": now - 60,  # issued at (60s skew)
        "exp": now + (10 * 60),  # expires in 10 minutes
        "iss": settings.github_app_id,
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


def _repo_url() -> str:
    return f"{_BASE}/repos/{settings.github_repo_owner}/{settings.github_repo_name}"


# ---- Read ------------------------------------------------------------------

async def list_ttl_files(
    token: str,
    path: Optional[str] = None,
    branch: Optional[str] = None,
) -> list[dict]:
    """List ontology files (*.ttl, *.rdf) under *path* in the repo."""
    path = path or settings.github_ontologies_path
    branch = branch or settings.github_default_branch
    url = f"{_repo_url()}/contents/{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(token), params={"ref": branch})
        resp.raise_for_status()
    items = resp.json()
    if not isinstance(items, list):
        items = [items]
    return [
        {"name": f["name"], "path": f["path"], "sha": f["sha"], "size": f["size"]}
        for f in items
        if f["name"].endswith((".ttl", ".rdf"))
    ]


async def read_file(
    token: str,
    path: str,
    branch: Optional[str] = None,
) -> str:
    """Read a file's content from the repo (decoded from base64)."""
    branch = branch or settings.github_default_branch
    url = f"{_repo_url()}/contents/{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(token), params={"ref": branch})
        resp.raise_for_status()
    data = resp.json()
    return base64.b64decode(data["content"]).decode("utf-8")


# ---- Write -----------------------------------------------------------------

async def create_branch(token: str, branch_name: str, from_branch: Optional[str] = None) -> dict:
    """Create a new branch from *from_branch* (defaults to main)."""
    from_branch = from_branch or settings.github_default_branch
    # Get the SHA of the source branch
    url = f"{_repo_url()}/git/ref/heads/{from_branch}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(token))
        resp.raise_for_status()
        sha = resp.json()["object"]["sha"]

        # Create the new ref
        resp = await client.post(
            f"{_repo_url()}/git/refs",
            headers=_headers(token),
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
        )
        resp.raise_for_status()
    return resp.json()


async def write_file(
    token: str,
    path: str,
    content: str,
    branch: str,
    message: str,
    sha: Optional[str] = None,
) -> dict:
    """Create or update a file via the Contents API.

    If *sha* is provided the file is updated; otherwise it is created.
    """
    url = f"{_repo_url()}/contents/{path}"
    body: dict = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    async with httpx.AsyncClient() as client:
        resp = await client.put(url, headers=_headers(token), json=body)
        resp.raise_for_status()
    return resp.json()


async def create_pull_request(
    token: str,
    branch: str,
    title: str,
    body: str = "",
    base: Optional[str] = None,
) -> dict:
    """Create a pull request from *branch* into *base*."""
    base = base or settings.github_default_branch
    url = f"{_repo_url()}/pulls"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers=_headers(token),
            json={"title": title, "body": body, "head": branch, "base": base},
        )
        resp.raise_for_status()
    return resp.json()


# ---- Compare / diff --------------------------------------------------------

async def compare_branches(
    token: str,
    base: str,
    head: str,
) -> dict:
    """Return the comparison (diff) between two branches."""
    url = f"{_repo_url()}/compare/{base}...{head}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(token))
        resp.raise_for_status()
    return resp.json()
