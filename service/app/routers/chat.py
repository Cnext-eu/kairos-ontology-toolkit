"""Chat router — SSE streaming AI chat for the web viewer.

Uses the GitHub Copilot SDK to create agentic sessions with custom
ontology tools.  The caller authenticates with their GitHub OAuth token,
which the SDK uses for both Copilot API access and repo operations.
"""

import json
from typing import Optional

from fastapi import APIRouter, Cookie, Header
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from kairos_ontology.ontology_ops import parse_ontology_content

from ..config import get_github_service, settings
from ..services import sdk_service
from .auth import get_user_token

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
      1. Per-user OAuth token (from session cookie)
      2. gh CLI auth (use_logged_in_user=True) as fallback
    """
    # Try OAuth session token first
    token = get_user_token(kairos_session)
    use_gh_cli = False

    if not token:
        # No OAuth session — fall back to gh CLI auth which uses
        # the locally authenticated `gh` CLI (needs copilot scope)
        use_gh_cli = True
        token = "gh-cli"  # placeholder — SDK ignores this when use_logged_in_user=True

    # Build ontology context
    ontology_context = await _build_ontology_context(
        token, req.domain, repo_owner=repo_owner, repo_name=repo_name,
    )

    # Extract last user message and build conversation history
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

    # Everything except the final user turn is prior context
    conversation_history = ""
    if len(history_parts) > 1:
        conversation_history = "\n\n".join(history_parts[:-1])

    if not last_user_msg:
        last_user_msg = "(no message)"

    async def event_generator():
        async for event in sdk_service.stream_chat(
            user_message=last_user_msg,
            github_token=token,
            ontology_context=ontology_context,
            conversation_history=conversation_history,
            use_logged_in_user=use_gh_cli,
        ):
            yield {"data": json.dumps(event)}

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _build_ontology_context(
    token: str,
    domain: Optional[str],
    repo_owner: Optional[str] = None,
    repo_name: Optional[str] = None,
) -> str:
    """Load ontology domain(s) as text context for the system prompt."""
    gh = get_github_service()
    if domain:
        file_path = _domain_to_path(domain)
        try:
            return await gh.read_file(
                token, file_path, owner=repo_owner, repo=repo_name,
            )
        except Exception:
            return f"(Could not load domain: {domain})"

    # Summarise all domains
    try:
        files = await gh.list_ttl_files(
            token, owner=repo_owner, repo=repo_name,
        )
        parts = []
        for f in files:
            content = await gh.read_file(
                token, f["path"], owner=repo_owner, repo=repo_name,
            )
            info = parse_ontology_content(content)
            classes = ", ".join(c.name for c in info.classes)
            parts.append(f"Domain {f['name']}: classes=[{classes}]")
        return "\n".join(parts)
    except Exception:
        return "(Could not load ontology files)"


def _extract_token(authorization: str) -> str:
    if authorization.lower().startswith("bearer "):
        return authorization[7:]
    return authorization


def _domain_to_path(domain: str) -> str:
    # Sanitise: strip path separators to prevent traversal
    safe = domain.replace("/", "").replace("\\", "").replace("..", "")
    name = safe if "." in safe else f"{safe}.ttl"
    return f"{settings.github_ontologies_path}/{name}"
