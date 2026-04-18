"""Tests for the chat router (/api/chat)."""

from unittest.mock import AsyncMock, patch


class TestChat:
    def test_chat_streams_response(self, client, auth_header, mock_github):
        """Verify chat endpoint returns SSE stream from mocked SDK."""

        async def fake_stream(**kwargs):
            for text in ["Hello", " world"]:
                yield {"type": "delta", "content": text}

        with patch("service.app.routers.chat.sdk_service") as mock_sdk:
            mock_sdk.stream_chat = fake_stream
            resp = client.post(
                "/api/chat",
                headers=auth_header,
                json={"messages": [{"role": "user", "content": "list classes"}]},
            )
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            # SSE body should contain the streamed chunks as JSON
            body = resp.text
            assert "Hello" in body
            assert "world" in body

    def test_chat_with_domain(self, client, auth_header, mock_github):
        """Chat with domain context should build ontology context."""

        async def fake_stream(**kwargs):
            yield {"type": "delta", "content": kwargs.get("ontology_context", "no-context")}

        with patch("service.app.routers.chat.sdk_service") as mock_sdk:
            mock_sdk.stream_chat = fake_stream
            resp = client.post(
                "/api/chat",
                headers=auth_header,
                json={
                    "messages": [{"role": "user", "content": "describe customer"}],
                    "domain": "customer",
                },
            )
            assert resp.status_code == 200
            # The ontology context should have been loaded
            body = resp.text
            assert "Customer" in body or "kairos" in body.lower()

    def test_chat_missing_auth(self, client, mock_github, monkeypatch):
        # Ensure dev mode is off so missing auth returns 401
        from service.app import config
        monkeypatch.setattr(config.settings, "dev_mode", False)
        monkeypatch.setattr(config.settings, "dev_github_token", "")
        resp = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
        assert resp.status_code == 401

    def test_chat_empty_messages(self, client, auth_header, mock_github):
        """Empty messages list should still work (falls back to '(no message)')."""

        async def fake_stream(**kwargs):
            yield {"type": "delta", "content": kwargs.get("user_message", "")}

        with patch("service.app.routers.chat.sdk_service") as mock_sdk:
            mock_sdk.stream_chat = fake_stream
            resp = client.post(
                "/api/chat",
                headers=auth_header,
                json={"messages": []},
            )
            assert resp.status_code == 200
