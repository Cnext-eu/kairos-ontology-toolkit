"""Copilot SDK session service — creates agentic chat sessions.

Uses the official GitHub Copilot SDK (``github-copilot-sdk``).
The SDK bundles the Copilot CLI and communicates via JSON-RPC.
Custom tools defined in ``copilot_tools`` let the agent perform
ontology CRUD, validation, and projection operations.
"""

import asyncio
from typing import AsyncIterator

from .copilot_tools import make_tools

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

RULES:
- Always output valid Turtle syntax when proposing changes.
- Never modify the main branch directly — always use feature branches.
- Explain changes in plain English before showing TTL.
- When the user asks to apply a change, always call propose_change first to show
  a diff, then ask for confirmation before calling apply_change.
"""


async def stream_chat(
    user_message: str,
    github_token: str,
    ontology_context: str = "",
    conversation_history: str = "",
) -> AsyncIterator[str]:
    """Create a Copilot SDK session and yield streamed response chunks.

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
    """
    from copilot import CopilotClient, SubprocessConfig
    from copilot.session import PermissionHandler

    tools = make_tools(github_token)

    system_text = _SYSTEM_APPEND
    if ontology_context:
        system_text += f"\n\nONTOLOGY CONTEXT:\n{ontology_context}"
    if conversation_history:
        system_text += f"\n\nPRIOR CONVERSATION:\n{conversation_history}"

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    error_holder: list[BaseException] = []

    async def _run() -> None:
        try:
            async with CopilotClient(
                SubprocessConfig(github_token=github_token)
            ) as client:
                done = asyncio.Event()

                async with await client.create_session(
                    on_permission_request=PermissionHandler.approve_all,
                    tools=tools,
                    streaming=True,
                    system_message={"append": system_text},
                ) as session:
                    def on_event(event):
                        evt = event.type.value if hasattr(event.type, "value") else str(event.type)
                        if evt == "assistant.message_delta":
                            delta = getattr(event.data, "delta_content", None) or ""
                            if delta:
                                queue.put_nowait(delta)
                        elif evt == "session.idle":
                            done.set()

                    session.on(on_event)
                    await session.send(user_message)
                    await done.wait()
        except Exception as exc:
            error_holder.append(exc)
            await queue.put(f"\n\n⚠ SDK error: {exc}")
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
) -> str:
    """Non-streaming convenience wrapper — returns the full response text."""
    parts: list[str] = []
    async for chunk in stream_chat(
        user_message=user_message,
        github_token=github_token,
        ontology_context=ontology_context,
    ):
        parts.append(chunk)
    return "".join(parts)
