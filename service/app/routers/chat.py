# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Chat router — SSE streaming AI chat for the web viewer.

Uses the GitHub Models API (OpenAI-compatible, no Copilot subscription needed)
with any valid GitHub PAT or OAuth token.
"""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Cookie, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from kairos_ontology.ontology_ops import parse_ontology_content

from ..config import get_github_service, settings
from ..services import models_service
from .auth import get_user_token, _oauth_enabled

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    messages: list[dict]  # [{"role": "user", "content": "..."}]
    domain: Optional[str] = None  # optional domain to inject as context


@router.post("")
async def chat(
    req: ChatRequest,
    authorization: str = Header(default=None, alias="Authorization"),
    repo_owner: Optional[str] = Header(None, alias="X-Kairos-Repo-Owner"),
    repo_name: Optional[str] = Header(None, alias="X-Kairos-Repo-Name"),
    kairos_session: Optional[str] = Cookie(None),
):
    """SSE-streaming chat endpoint for the Ontology Hub web viewer.

    Token resolution order:
      1. Per-user OAuth session token (cookie)
      2. Authorization header token
      3. DEV_GITHUB_TOKEN setting
      4. gh CLI token (gh auth token) — dev fallback
      5. 401
    """
    # Try OAuth session token first, then fall back to Authorization header
    token = get_user_token(kairos_session)

    if not token and authorization:
        token = _extract_token(authorization)

    if not token:
        if _oauth_enabled():
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required. Please login via GitHub OAuth."},
            )
        elif settings.dev_github_token:
            token = settings.dev_github_token
        else:
            # Try gh CLI as last resort (dev machines with `gh auth login`)
            token = await _gh_cli_token()
        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "No GitHub token available. Set DEV_GITHUB_TOKEN in .env or run `gh auth login`."},
            )

    # Build ontology context
    ontology_context = await _build_ontology_context(
        req.domain, repo_owner=repo_owner, repo_name=repo_name,
    )

    # Extract last user message and build conversation history (cap at last 10 turns)
    last_user_msg = ""
    history_parts: list[str] = []
    for msg in req.messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            last_user_msg = content
        if role in ("user", "assistant"):
            prefix = "User" if role == "user" else "Assistant"
            history_parts.append(f"[{prefix}]: {content}")

    # Keep only the last 10 turns before the current message to stay within token limits
    MAX_HISTORY_TURNS = 10
    prior_history = history_parts[:-1]
    if len(prior_history) > MAX_HISTORY_TURNS:
        prior_history = prior_history[-MAX_HISTORY_TURNS:]

    conversation_history = ""
    if prior_history:
        conversation_history = "\n\n".join(prior_history)

    if not last_user_msg:
        last_user_msg = "(no message)"

    async def event_generator():
        async for event in models_service.stream_chat(
            user_message=last_user_msg,
            github_token=token,
            ontology_context=ontology_context,
            conversation_history=conversation_history,
            repo_owner=repo_owner,
            repo_name=repo_name,
            model=settings.chat_model,
        ):
            yield {"data": json.dumps(event)}

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAX_ONTOLOGY_CONTEXT_CHARS = 12_000  # ~3 000 tokens — leave room for history + response


async def _build_ontology_context(
    domain: Optional[str],
    repo_owner: Optional[str] = None,
    repo_name: Optional[str] = None,
) -> str:
    """Load ontology domain(s) as text context for the system prompt.

    When a specific domain is selected, returns the raw TTL truncated to
    ``_MAX_ONTOLOGY_CONTEXT_CHARS``.  When no domain is selected, returns a
    compact class-list summary (never raw TTL) to keep the payload small.
    """
    gh_svc = get_github_service()
    if domain:
        file_path = _domain_to_path(domain)
        try:
            content = await gh_svc.read_file(file_path, owner=repo_owner, repo=repo_name)
            if len(content) > _MAX_ONTOLOGY_CONTEXT_CHARS:
                content = content[:_MAX_ONTOLOGY_CONTEXT_CHARS] + "\n... (truncated)"
            return content
        except Exception:
            return f"(Could not load domain: {domain})"

    # No domain selected — build a compact summary (class names only, no raw TTL)
    try:
        files = await gh_svc.list_ttl_files(owner=repo_owner, repo=repo_name)
        parts = []
        for f in files:
            try:
                content = await gh_svc.read_file(f["path"], owner=repo_owner, repo=repo_name)
                info = parse_ontology_content(content)
                classes = ", ".join(c.name for c in info.classes)
                parts.append(f"Domain {f['name']}: classes=[{classes}]")
            except Exception:
                parts.append(f"Domain {f['name']}: (could not parse)")
        return "\n".join(parts)
    except Exception:
        return "(Could not load ontology files)"


def _extract_token(authorization: str) -> str:
    if authorization.lower().startswith("bearer "):
        return authorization[7:]
    return authorization


async def _gh_cli_token() -> Optional[str]:
    """Try to get a token from the gh CLI (dev machines with `gh auth login`)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "auth", "token",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        token = stdout.decode().strip()
        return token if token else None
    except Exception:
        return None


def _domain_to_path(domain: str) -> str:
    # Sanitise: strip path separators to prevent traversal
    safe = domain.replace("/", "").replace("\\", "").replace("..", "")
    name = safe if "." in safe else f"{safe}.ttl"
    return f"{settings.github_ontologies_path}/{name}"
