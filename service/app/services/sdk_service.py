"""Copilot SDK session service — creates agentic chat sessions.

Uses the official GitHub Copilot SDK (``github-copilot-sdk``).
The SDK bundles the Copilot CLI and communicates via JSON-RPC.
Custom tools defined in ``copilot_tools`` let the agent perform
ontology CRUD, validation, and projection operations.
"""

import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator

from .copilot_tools import make_tools

logger = logging.getLogger(__name__)

# Resolve .github/skills directory for SDK skill loading
_SKILLS_DIR = Path(__file__).resolve().parents[3] / ".github" / "skills"

# System prompt appended to Copilot's default instructions
_SYSTEM_APPEND = """\
You are an expert ontology assistant for the Kairos platform.
You help business analysts understand and modify OWL/Turtle ontologies.

Available tools:
- query_ontology: search classes, properties, relationships
- propose_change: generate a TTL modification with diff preview
- validate_ontology: run SHACL / syntax validation
- generate_projection: generate dbt / neo4j / azure-search / a2ui / prompt artifacts
- apply_change: commit proposed changes to a feature branch and open a PR
- scaffold_hub: create a new ontology hub (starter TTL + SHACL placeholder + PR)
- create_domain: generate a complete starter ontology from a structured description
- explain_ontology: produce a human-readable summary of a domain
- suggest_improvements: analyze a domain and return actionable suggestions

IDENTITY:
You are a single ontology assistant (not a multi-agent system).
When the user asks about your capabilities, agents, or what you can do,
describe the tools listed above in plain English. Do NOT attempt to look
up or list agents via any API — just describe yourself.

RULES:
- Always output valid Turtle syntax when proposing changes.
- Never modify the main branch directly — always use feature branches.
- Explain changes in plain English before showing TTL.
- When the user asks to apply a change, always call propose_change first to show
  a diff, then ask for confirmation before calling apply_change.
- Do not try to access external APIs or list agents. You are self-contained.

GUIDED WORKFLOWS:

## Set up a new ontology hub
When the user wants to create a new ontology domain from scratch:
1. Ask for domain name, description, and optional namespace.
2. Call scaffold_hub to create the hub structure on a feature branch.
3. Explain what was created and share the PR link.

## Create a new domain ontology
When the user describes classes and properties they want:
1. Gather structured requirements: class names, properties, types.
2. Call create_domain to generate the TTL and validate it.
3. Show the generated TTL and validation results.
4. If approved, call apply_change to commit it.

## Explain this ontology
When the user asks "what is this?" or "explain domain X":
1. Call explain_ontology to get the structured summary.
2. Present classes, properties, and relationships in plain English.
3. Offer to suggest improvements or generate projections.

## Improve this ontology
When the user asks for improvement suggestions:
1. Call suggest_improvements on the domain.
2. Present findings grouped by severity (warning > info).
3. For each actionable suggestion, offer to call propose_change.
"""


async def stream_chat(
    user_message: str,
    github_token: str,
    ontology_context: str = "",
    conversation_history: str = "",
    use_logged_in_user: bool = False,
) -> AsyncIterator[dict]:
    """Create a Copilot SDK session and yield structured event dicts.

    Each yielded dict has a ``type`` key:

    - ``{"type": "delta", "content": "..."}`` — streamed text chunk (markdown)
    - ``{"type": "tool_start", "name": "...", "intent": "..."}`` — tool invoked
    - ``{"type": "tool_end", "name": "..."}`` — tool finished
    - ``{"type": "thinking"}`` — model is reasoning
    - ``{"type": "error", "message": "..."}`` — error occurred

    Parameters
    ----------
    user_message:
        The latest user message to send.
    github_token:
        GitHub token — used both for Copilot API auth and repo access.
    ontology_context:
        Summary of loaded ontology domains injected into the system prompt.
    conversation_history:
        Formatted prior turns for context continuity.
    use_logged_in_user:
        When True, authenticate via the GitHub CLI instead of a PAT.
        This is recommended for dev mode since ``gh auth`` provides
        the scopes required by the Copilot API.
    """
    from copilot import CopilotClient, SubprocessConfig
    from copilot.session import PermissionHandler

    tools = make_tools(github_token)

    system_text = _SYSTEM_APPEND
    if ontology_context:
        system_text += f"\n\nONTOLOGY CONTEXT:\n{ontology_context}"

    # Build a structured conversation transcript so the model treats
    # prior turns as real dialogue, not background noise.
    if conversation_history:
        system_text += (
            "\n\n─── CONVERSATION HISTORY (you MUST remember and reference this) ───\n"
            "The following is the conversation so far between you and the user.\n"
            "Continue this conversation naturally. Reference earlier messages when relevant.\n\n"
            f"{conversation_history}\n"
            "─── END HISTORY ───"
        )

    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    error_holder: list[BaseException] = []
    _thinking_sent = False

    async def _run() -> None:
        nonlocal _thinking_sent
        try:
            logger.info("Starting CopilotClient session...")
            config = (
                SubprocessConfig(use_logged_in_user=True)
                if use_logged_in_user
                else SubprocessConfig(github_token=github_token)
            )
            async with CopilotClient(config) as client:
                done = asyncio.Event()
                logger.info("CopilotClient connected, creating session...")

                async with await client.create_session(
                    on_permission_request=PermissionHandler.approve_all,
                    tools=tools,
                    streaming=True,
                    system_message={"append": system_text},
                    skill_directories=[str(_SKILLS_DIR)] if _SKILLS_DIR.is_dir() else [],
                ) as session:
                    def on_event(event):
                        nonlocal _thinking_sent
                        evt = event.type.value if hasattr(event.type, "value") else str(event.type)
                        logger.debug("SDK event: %s", evt)

                        if evt == "assistant.message_delta":
                            _thinking_sent = False
                            delta = getattr(event.data, "delta_content", None) or ""
                            if delta:
                                queue.put_nowait({"type": "delta", "content": delta})

                        elif evt == "tool.execution_start":
                            _thinking_sent = False
                            name = getattr(event.data, "tool_name", None) or getattr(event.data, "name", None) or ""
                            args = getattr(event.data, "arguments", None) or {}
                            intent = args.get("intent", "") if isinstance(args, dict) else ""
                            queue.put_nowait({"type": "tool_start", "name": name, "intent": intent})

                        elif evt == "tool.execution_complete":
                            name = getattr(event.data, "tool_name", None) or getattr(event.data, "name", None) or ""
                            queue.put_nowait({"type": "tool_end", "name": name})

                        elif evt == "assistant.reasoning_delta":
                            if not _thinking_sent:
                                _thinking_sent = True
                                queue.put_nowait({"type": "thinking"})

                        elif evt == "session.error":
                            msg = getattr(event.data, "message", "Unknown SDK error")
                            err_type = getattr(event.data, "error_type", None) or ""
                            logger.error("SDK session error [%s]: %s", err_type, msg)
                            # Suppress auth errors from built-in operations —
                            # the agent can still respond from context.
                            if "authentication" in err_type or "authentication" in msg.lower():
                                logger.info("Suppressed auth error — agent will respond from context")
                            else:
                                queue.put_nowait({"type": "error", "message": msg})

                        elif evt == "session.idle":
                            done.set()

                    session.on(on_event)
                    logger.info("Sending message to session: %s", user_message[:80])
                    await session.send(user_message)
                    await done.wait()
                    logger.info("Session idle — stream complete")
        except Exception as exc:
            logger.error("SDK error: %s", exc, exc_info=True)
            error_holder.append(exc)
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put(None)  # sentinel

    task = asyncio.create_task(_run())

    while True:
        chunk = await queue.get()
        if chunk is None:
            break
        yield chunk

    # Propagate task exceptions that weren't caught
    await task


async def oneshot_chat(
    user_message: str,
    github_token: str,
    ontology_context: str = "",
    use_logged_in_user: bool = False,
) -> str:
    """Non-streaming convenience wrapper — returns the full response text."""
    parts: list[str] = []
    async for event in stream_chat(
        user_message=user_message,
        github_token=github_token,
        ontology_context=ontology_context,
        use_logged_in_user=use_logged_in_user,
    ):
        if event.get("type") == "delta":
            parts.append(event.get("content", ""))
    return "".join(parts)
