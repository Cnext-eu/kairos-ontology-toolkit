"""Tests for models_service — GitHub Models API chat backend."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.service.conftest import SAMPLE_TTL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(content=None, tool_name=None, tool_id=None, tool_args=None, index=0):
    """Build a minimal OpenAI streaming chunk mock."""
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = None

    if tool_name is not None:
        tc = MagicMock()
        tc.index = index
        tc.id = tool_id
        tc.function = MagicMock()
        tc.function.name = tool_name
        tc.function.arguments = tool_args or ""
        delta.tool_calls = [tc]

    choice = MagicMock()
    choice.delta = delta
    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


async def _async_iter(items):
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# stream_chat tests
# ---------------------------------------------------------------------------

class TestStreamChat:
    @pytest.mark.asyncio
    async def test_yields_delta_events(self):
        """stream_chat yields delta events for text chunks."""
        from service.app.services import models_service

        chunks = [
            _make_chunk(content="Hello"),
            _make_chunk(content=" world"),
        ]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_async_iter(chunks)
        )

        with patch("service.app.services.models_service.AsyncOpenAI", return_value=mock_client):
            events = []
            async for evt in models_service.stream_chat(
                user_message="hi",
                github_token="ghp_test",
            ):
                events.append(evt)

        assert any(e["type"] == "delta" and "Hello" in e["content"] for e in events)
        assert any(e["type"] == "delta" and "world" in e["content"] for e in events)

    @pytest.mark.asyncio
    async def test_yields_tool_events(self):
        """stream_chat yields tool_start and tool_end around tool calls."""
        from service.app.services import models_service

        # First call: model requests a tool
        tool_chunks = [
            _make_chunk(tool_name="suggest_improvements", tool_id="call_1",
                        tool_args='{"domain": "customer"}', index=0),
        ]
        # Second call (after tool result): model responds with text
        text_chunks = [_make_chunk(content="Here are suggestions")]

        call_count = 0

        async def fake_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _async_iter(tool_chunks)
            return _async_iter(text_chunks)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create

        with (
            patch("service.app.services.models_service.AsyncOpenAI", return_value=mock_client),
            patch(
                "service.app.services.models_service._dispatch_tool",
                new=AsyncMock(return_value=json.dumps({"issues": []})),
            ),
        ):
            events = []
            async for evt in models_service.stream_chat(
                user_message="suggest improvements",
                github_token="ghp_test",
            ):
                events.append(evt)

        types = [e["type"] for e in events]
        assert "tool_start" in types
        assert "tool_end" in types
        assert "delta" in types

    @pytest.mark.asyncio
    async def test_falls_back_to_mini_on_403(self):
        """stream_chat falls back to gpt-4o-mini when gpt-4o returns 403."""
        from service.app.services import models_service

        call_models = []

        async def fake_create(**kwargs):
            call_models.append(kwargs.get("model"))
            if kwargs.get("model") == "gpt-4o":
                raise Exception("403 Forbidden")
            return _async_iter([_make_chunk(content="ok")])

        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create

        with patch("service.app.services.models_service.AsyncOpenAI", return_value=mock_client):
            events = []
            async for evt in models_service.stream_chat(
                user_message="hi",
                github_token="ghp_test",
                model="gpt-4o",
            ):
                events.append(evt)

        assert "gpt-4o" in call_models
        assert "gpt-4o-mini" in call_models
        assert any(e["type"] == "delta" for e in events)

    @pytest.mark.asyncio
    async def test_yields_error_event_on_api_failure(self):
        """stream_chat yields an error event when the API call fails entirely."""
        from service.app.services import models_service

        async def fake_create(**kwargs):
            raise Exception("Connection refused")

        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create

        with patch("service.app.services.models_service.AsyncOpenAI", return_value=mock_client):
            events = []
            async for evt in models_service.stream_chat(
                user_message="hi",
                github_token="ghp_test",
                model="gpt-4o-mini",  # no fallback when already mini
            ):
                events.append(evt)

        assert any(e["type"] == "error" for e in events)

    @pytest.mark.asyncio
    async def test_ontology_context_injected_in_system_prompt(self):
        """Ontology context is included in the system message."""
        from service.app.services import models_service

        captured_messages = []

        async def fake_create(**kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            return _async_iter([_make_chunk(content="done")])

        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create

        with patch("service.app.services.models_service.AsyncOpenAI", return_value=mock_client):
            async for _ in models_service.stream_chat(
                user_message="hi",
                github_token="ghp_test",
                ontology_context="ONTOLOGY: Customer has name, email",
            ):
                pass

        system_msg = next(m for m in captured_messages if m["role"] == "system")
        assert "Customer has name, email" in system_msg["content"]


# ---------------------------------------------------------------------------
# Tool dispatch tests
# ---------------------------------------------------------------------------

class TestToolDispatch:
    @pytest.mark.asyncio
    async def test_suggest_improvements_finds_missing_label(self):
        """suggest_improvements flags a class without rdfs:label."""
        from service.app.services import models_service

        # TTL with a class missing rdfs:label
        ttl_no_label = """\
@prefix : <http://test.example/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

:MyOntology a owl:Ontology ; rdfs:label "Test" .

:Widget a owl:Class ;
    rdfs:comment "A widget" .
"""
        with patch(
            "service.app.services.models_service.gh.list_ttl_files",
            new=AsyncMock(return_value=[{"name": "widget.ttl", "path": "ontologies/widget.ttl"}]),
        ), patch(
            "service.app.services.models_service.gh.read_file",
            new=AsyncMock(return_value=ttl_no_label),
        ):
            result = await models_service._tool_suggest_improvements("ghp_test", "widget")

        data = json.loads(result)
        issues = data["issues"]
        assert any(i["issue"] == "Missing rdfs:label" for i in issues)

    @pytest.mark.asyncio
    async def test_validate_ontology_returns_syntax_result(self):
        """_tool_validate_ontology returns a dict with 'syntax' key."""
        from service.app.services import models_service

        with patch(
            "service.app.services.models_service.gh.read_file",
            new=AsyncMock(return_value=SAMPLE_TTL),
        ):
            result = await models_service._tool_validate_ontology("ghp_test", "customer")

        data = json.loads(result)
        assert "syntax" in data

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool_returns_error(self):
        """_dispatch_tool returns a JSON error for unknown tool names."""
        from service.app.services import models_service

        result = await models_service._dispatch_tool("nonexistent_tool", {}, "ghp_test", None, None)
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_query_ontology_filters_by_search_term(self):
        """query_ontology returns only classes matching the search term."""
        from service.app.services import models_service

        with patch(
            "service.app.services.models_service.gh.list_ttl_files",
            new=AsyncMock(return_value=[{"name": "customer.ttl", "path": "ontologies/customer.ttl"}]),
        ), patch(
            "service.app.services.models_service.gh.read_file",
            new=AsyncMock(return_value=SAMPLE_TTL),
        ):
            result = await models_service._tool_query_ontology(
                "ghp_test", domain=None, search="customer"
            )

        data = json.loads(result)
        assert len(data) == 1
        classes = data[0]["classes"]
        assert all("customer" in c["name"].lower() for c in classes)
