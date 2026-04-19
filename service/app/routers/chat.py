"""Chat router — SSE streaming AI chat for the web viewer.

Uses the GitHub Copilot SDK to create agentic sessions with custom
ontology tools.  The caller authenticates with their GitHub OAuth token,
which the SDK uses for both Copilot API access and repo operations.
"""

import json
from typing import Optional

from fastapi import APIRouter, Header
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from kairos_ontology.ontology_ops import parse_ontology_content

from ..config import get_github_service, settings
from ..services import sdk_service

router = APIRouter()


class ChatRequest(BaseModel):
    messages: list[dict]  # [{"role": "user", "content": "..."}]
    domain: Optional[str] = None  # optional domain to inject as context


@router.post("")
async def chat(
    req: ChatRequest,
    authorization: str = Header(default=None, alias="Authorization"),
):
    """SSE-streaming chat endpoint for the Ontology Hub web viewer.

    Creates a Copilot SDK session with ontology tools, injects domain
    context into the system prompt, and streams the response via SSE.
    In dev mode, falls back to KAIROS_DEV_GITHUB_TOKEN if no valid token
    is provided in the Authorization header.
    """
    token = _extract_token(authorization or "")

    # In dev mode, use configured token if header token looks like a placeholder
    if settings.dev_mode and (not token or token == "dev-token"):
        token = settings.dev_github_token
    if not token:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=401,
            content={"detail": "No GitHub token. Set KAIROS_DEV_GITHUB_TOKEN in .env for dev mode."},
        )

    # Build ontology context
    ontology_context = await _build_ontology_context(token, req.domain)

    # Extract last user message and build conversation history
    last_user_msg = ""
    history_parts: list[str] = []
    for msg in req.messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            last_user_msg = content
        if role in ("user", "assistant"):
            history_parts.append(f"{role}: {content}")

    # Everything except the final user turn is prior context
    conversation_history = ""
    if len(history_parts) > 1:
        conversation_history = "\n".join(history_parts[:-1])

    if not last_user_msg:
        last_user_msg = "(no message)"

    async def event_generator():
        async for event in sdk_service.stream_chat(
            user_message=last_user_msg,
            github_token=token,
            ontology_context=ontology_context,
            conversation_history=conversation_history,
            use_logged_in_user=settings.dev_mode,
        ):
            yield {"data": json.dumps(event)}

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _build_ontology_context(token: str, domain: Optional[str]) -> str:
    """Load ontology domain(s) as text context for the system prompt."""
    gh = get_github_service()
    if domain:
        file_path = _domain_to_path(domain)
        try:
            return await gh.read_file(token, file_path)
        except Exception:
            return f"(Could not load domain: {domain})"

    # Summarise all domains
    try:
        files = await gh.list_ttl_files(token)
        parts = []
        for f in files:
            content = await gh.read_file(token, f["path"])
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
    name = domain if "." in domain else f"{domain}.ttl"
    return f"{settings.github_ontologies_path}/{name}"
