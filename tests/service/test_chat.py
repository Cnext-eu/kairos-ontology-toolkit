"""Tests for the chat router (/api/chat)."""

from unittest.mock import AsyncMock, patch


class TestChat:
    def test_chat_streams_response(self, client, auth_header, mock_github):
        """Chat endpoint returns SSE stream from mocked models_service."""

        async def fake_stream(**kwargs):
            yield {"type": "delta", "content": "Hello"}
            yield {"type": "delta", "content": " world"}

        with patch("service.app.routers.chat.models_service") as mock_svc:
            mock_svc.stream_chat = fake_stream
            resp = client.post(
                "/api/chat",
                headers=auth_header,
                json={"messages": [{"role": "user", "content": "list classes"}]},
            )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        assert "Hello" in resp.text
        assert "world" in resp.text

    def test_chat_with_domain(self, client, auth_header, mock_github):
        """Chat with domain= injects ontology context into stream_chat call."""
        captured = {}

        async def fake_stream(**kwargs):
            captured.update(kwargs)
            yield {"type": "delta", "content": "ok"}

        with patch("service.app.routers.chat.models_service") as mock_svc:
            mock_svc.stream_chat = fake_stream
            resp = client.post(
                "/api/chat",
                headers=auth_header,
                json={
                    "messages": [{"role": "user", "content": "describe"}],
                    "domain": "customer",
                },
            )
        assert resp.status_code == 200
        assert "ontology_context" in captured

    def test_chat_missing_auth(self, client, mock_github, monkeypatch):
        """Missing auth with no fallbacks returns 401."""
        from service.app import config
        monkeypatch.setattr(config.settings, "dev_github_token", "")
        monkeypatch.setattr(config.settings, "oauth_client_id", "")

        # _gh_cli_token must also return None so we reach the 401
        with patch("service.app.routers.chat._gh_cli_token", new=AsyncMock(return_value=None)):
            resp = client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "hello"}]},
            )
        assert resp.status_code == 401

    def test_chat_empty_messages(self, client, auth_header, mock_github):
        """Empty messages list falls back to '(no message)'."""
        captured = {}

        async def fake_stream(**kwargs):
            captured.update(kwargs)
            yield {"type": "delta", "content": "ok"}

        with patch("service.app.routers.chat.models_service") as mock_svc:
            mock_svc.stream_chat = fake_stream
            resp = client.post(
                "/api/chat",
                headers=auth_header,
                json={"messages": []},
            )
        assert resp.status_code == 200
        assert captured.get("user_message") == "(no message)"

    def test_chat_tool_events_passed_through(self, client, auth_header, mock_github):
        """tool_start / tool_end events are forwarded in the SSE stream."""

        async def fake_stream(**kwargs):
            yield {"type": "tool_start", "name": "suggest_improvements", "intent": ""}
            yield {"type": "tool_end", "name": "suggest_improvements"}
            yield {"type": "delta", "content": "Done"}

        with patch("service.app.routers.chat.models_service") as mock_svc:
            mock_svc.stream_chat = fake_stream
            resp = client.post(
                "/api/chat",
                headers=auth_header,
                json={"messages": [{"role": "user", "content": "suggest"}]},
            )
        assert resp.status_code == 200
        assert "tool_start" in resp.text
        assert "suggest_improvements" in resp.text

