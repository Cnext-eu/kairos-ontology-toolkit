# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for AI provider abstraction."""

import os
from unittest.mock import patch, MagicMock

import pytest

from kairos_ontology.core.ai_provider import (
    resolve_provider_config,
    get_ai_client,
    GITHUB_MODELS_ENDPOINT,
    DEFAULT_MODEL,
    _load_dotenv_from_hub,
)


class TestDotenvAutoLoad:
    def test_loads_repo_root_env_when_running_from_ontology_hub(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        hub_dir = repo_root / "ontology-hub"
        (hub_dir / "model" / "ontologies").mkdir(parents=True)
        root_env = repo_root / ".env"
        root_env.write_text("AZURE_AI_ENDPOINT=https://example\n", encoding="utf-8")

        monkeypatch.chdir(hub_dir)
        with patch("kairos_ontology.core.ai_provider.load_dotenv") as load_dotenv_mock:
            _load_dotenv_from_hub()

        load_dotenv_mock.assert_called_once_with(root_env, override=False)

    def test_prefers_cwd_env_over_repo_root(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        hub_dir = repo_root / "ontology-hub"
        (hub_dir / "model" / "ontologies").mkdir(parents=True)
        root_env = repo_root / ".env"
        root_env.write_text("AZURE_AI_ENDPOINT=https://root\n", encoding="utf-8")
        hub_env = hub_dir / ".env"
        hub_env.write_text("AZURE_AI_ENDPOINT=https://hub\n", encoding="utf-8")

        monkeypatch.chdir(hub_dir)
        with patch("kairos_ontology.core.ai_provider.load_dotenv") as load_dotenv_mock:
            _load_dotenv_from_hub()

        load_dotenv_mock.assert_called_once_with(hub_env, override=False)

    def test_no_env_files_does_not_call_load(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        hub_dir = repo_root / "ontology-hub"
        (hub_dir / "model" / "ontologies").mkdir(parents=True)

        monkeypatch.chdir(hub_dir)
        with patch("kairos_ontology.core.ai_provider.load_dotenv") as load_dotenv_mock:
            _load_dotenv_from_hub()

        load_dotenv_mock.assert_not_called()

    # -- Issue #188: a pre-existing empty-string env var must not permanently
    # -- shadow a real value in the hub's .env. These tests do NOT mock
    # -- load_dotenv -- they exercise the real python-dotenv interaction so the
    # -- fix (_clear_stale_empty_env_vars) is actually under test.

    def test_stale_empty_credential_is_overridden_by_real_hub_value(
        self, tmp_path, monkeypatch
    ):
        repo_root = tmp_path / "repo"
        hub_dir = repo_root / "ontology-hub"
        (hub_dir / "model" / "ontologies").mkdir(parents=True)
        hub_env = hub_dir / ".env"
        hub_env.write_text("AZURE_FOUNDRY_API_KEY=real-secret\n", encoding="utf-8")

        monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "")
        monkeypatch.chdir(hub_dir)

        _load_dotenv_from_hub()

        assert os.environ["AZURE_FOUNDRY_API_KEY"] == "real-secret"

    def test_genuinely_set_non_empty_value_is_preserved(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        hub_dir = repo_root / "ontology-hub"
        (hub_dir / "model" / "ontologies").mkdir(parents=True)
        hub_env = hub_dir / ".env"
        hub_env.write_text(
            "AZURE_AI_ENDPOINT=https://hub-configured-value\n", encoding="utf-8"
        )

        monkeypatch.setenv("AZURE_AI_ENDPOINT", "https://pre-set-real-value")
        monkeypatch.chdir(hub_dir)

        _load_dotenv_from_hub()

        assert os.environ["AZURE_AI_ENDPOINT"] == "https://pre-set-real-value"

    def test_unset_key_is_loaded_normally(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        hub_dir = repo_root / "ontology-hub"
        (hub_dir / "model" / "ontologies").mkdir(parents=True)
        hub_env = hub_dir / ".env"
        hub_env.write_text("AZURE_AI_KEY=fresh-value\n", encoding="utf-8")

        monkeypatch.delenv("AZURE_AI_KEY", raising=False)
        monkeypatch.chdir(hub_dir)

        _load_dotenv_from_hub()

        assert os.environ["AZURE_AI_KEY"] == "fresh-value"

    def test_fix_is_general_not_azure_specific(self, tmp_path, monkeypatch):
        """A non-Azure var this same loader handles (a dbt version specifier)
        must get the same stale-empty-value treatment, proving the fix is not
        special-cased to Azure credential names.
        """
        repo_root = tmp_path / "repo"
        hub_dir = repo_root / "ontology-hub"
        (hub_dir / "model" / "ontologies").mkdir(parents=True)
        hub_env = hub_dir / ".env"
        hub_env.write_text("KAIROS_DBT_CORE_VERSION=>=1.9,<1.10\n", encoding="utf-8")

        monkeypatch.setenv("KAIROS_DBT_CORE_VERSION", "")
        monkeypatch.chdir(hub_dir)

        _load_dotenv_from_hub()

        assert os.environ["KAIROS_DBT_CORE_VERSION"] == ">=1.9,<1.10"


class TestResolveProviderConfig:
    """Test provider configuration resolution."""

    def test_github_from_explicit_provider(self):
        with patch.dict(os.environ, {"KAIROS_AI_PROVIDER": "github", "GITHUB_TOKEN": "tok"}):
            config = resolve_provider_config()
        assert config.provider == "github"
        assert config.endpoint == GITHUB_MODELS_ENDPOINT
        assert config.api_key == "tok"
        assert config.model == DEFAULT_MODEL

    def test_github_from_token_only(self):
        env = {"GITHUB_TOKEN": "my-token"}
        with patch.dict(os.environ, env, clear=True):
            config = resolve_provider_config("custom-model")
        assert config.provider == "github"
        assert config.api_key == "my-token"
        assert config.model == "custom-model"

    def test_azure_from_explicit_provider(self):
        env = {
            "KAIROS_AI_PROVIDER": "azure",
            "AZURE_AI_ENDPOINT": "https://my.azure.com/models",
            "AZURE_AI_KEY": "az-key",
        }
        with patch.dict(os.environ, env, clear=True):
            config = resolve_provider_config()
        assert config.provider == "azure"
        assert config.endpoint == "https://my.azure.com/models"
        assert config.api_key == "az-key"

    def test_azure_from_endpoint_env(self):
        env = {
            "AZURE_AI_ENDPOINT": "https://my.azure.com/models",
            "AZURE_AI_KEY": "az-key",
        }
        with patch.dict(os.environ, env, clear=True):
            config = resolve_provider_config()
        assert config.provider == "azure"

    def test_azure_precedence_over_github(self):
        """When both are set but KAIROS_AI_PROVIDER=azure, use azure."""
        env = {
            "KAIROS_AI_PROVIDER": "azure",
            "GITHUB_TOKEN": "gh-tok",
            "AZURE_AI_ENDPOINT": "https://az.com",
            "AZURE_AI_KEY": "az-key",
        }
        with patch.dict(os.environ, env, clear=True):
            config = resolve_provider_config()
        assert config.provider == "azure"

    def test_foundry_from_explicit_provider(self):
        env = {
            "KAIROS_AI_PROVIDER": "foundry",
            "AZURE_FOUNDRY_ENDPOINT": "https://my.ai.azure.com/api/projects/proj",
            "AZURE_FOUNDRY_API_KEY": "foundry-key",
        }
        with patch.dict(os.environ, env, clear=True):
            config = resolve_provider_config()
        assert config.provider == "foundry"
        assert config.endpoint == "https://my.ai.azure.com/api/projects/proj"
        assert config.api_key == "foundry-key"
        assert config.model == DEFAULT_MODEL

    def test_foundry_from_endpoint_env(self):
        """Auto-detect foundry when AZURE_FOUNDRY_ENDPOINT is set."""
        env = {
            "AZURE_FOUNDRY_ENDPOINT": "https://my.ai.azure.com/api/projects/proj",
        }
        with patch.dict(os.environ, env, clear=True):
            config = resolve_provider_config()
        assert config.provider == "foundry"
        assert config.api_key == ""

    def test_foundry_with_custom_model(self):
        env = {
            "KAIROS_AI_PROVIDER": "foundry",
            "AZURE_FOUNDRY_ENDPOINT": "https://my.ai.azure.com/api/projects/proj",
        }
        with patch.dict(os.environ, env, clear=True):
            config = resolve_provider_config("gpt-5.4-mini")
        assert config.model == "gpt-5.4-mini"

    def test_foundry_without_api_key(self):
        """Foundry without API key should resolve (will use Entra ID at client creation)."""
        env = {
            "KAIROS_AI_PROVIDER": "foundry",
            "AZURE_FOUNDRY_ENDPOINT": "https://my.ai.azure.com/api/projects/proj",
        }
        with patch.dict(os.environ, env, clear=True):
            config = resolve_provider_config()
        assert config.provider == "foundry"
        assert config.api_key == ""

    def test_error_foundry_no_endpoint(self):
        with patch.dict(os.environ, {"KAIROS_AI_PROVIDER": "foundry"}, clear=True):
            with pytest.raises(EnvironmentError, match="AZURE_FOUNDRY_ENDPOINT"):
                resolve_provider_config()

    def test_foundry_precedence_over_github(self):
        """When both foundry and github are set, explicit foundry wins."""
        env = {
            "KAIROS_AI_PROVIDER": "foundry",
            "GITHUB_TOKEN": "gh-tok",
            "AZURE_FOUNDRY_ENDPOINT": "https://my.ai.azure.com/api/projects/proj",
        }
        with patch.dict(os.environ, env, clear=True):
            config = resolve_provider_config()
        assert config.provider == "foundry"

    def test_error_no_config(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(EnvironmentError, match="No AI provider configured"):
                resolve_provider_config()

    def test_error_no_config_mentions_foundry(self):
        """Error message should mention foundry as an option."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(EnvironmentError, match="AZURE_FOUNDRY_ENDPOINT"):
                resolve_provider_config()

    def test_error_unknown_provider(self):
        with patch.dict(os.environ, {"KAIROS_AI_PROVIDER": "invalid"}, clear=True):
            with pytest.raises(EnvironmentError, match="Unknown KAIROS_AI_PROVIDER"):
                resolve_provider_config()

    def test_error_unknown_provider_mentions_foundry(self):
        """Unknown provider error should list foundry as supported."""
        with patch.dict(os.environ, {"KAIROS_AI_PROVIDER": "invalid"}, clear=True):
            with pytest.raises(EnvironmentError, match="foundry"):
                resolve_provider_config()

    def test_error_github_no_token(self):
        with patch.dict(os.environ, {"KAIROS_AI_PROVIDER": "github"}, clear=True):
            with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
                resolve_provider_config()

    def test_error_azure_no_endpoint(self):
        with patch.dict(os.environ, {"KAIROS_AI_PROVIDER": "azure"}, clear=True):
            with pytest.raises(EnvironmentError, match="AZURE_AI_ENDPOINT"):
                resolve_provider_config()

    def test_azure_no_key_no_identity(self):
        """Azure without key and without azure-identity should error."""
        env = {"KAIROS_AI_PROVIDER": "azure", "AZURE_AI_ENDPOINT": "https://az.com"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch.dict("sys.modules", {"azure": None, "azure.identity": None}),
        ):
            with pytest.raises(EnvironmentError, match="uv sync --extra azure"):
                resolve_provider_config()


class TestPerRoleEndpoints:
    """Per-role endpoint/model overrides (issue #182)."""

    def test_role_endpoint_wins_over_global_provider(self):
        env = {
            "GITHUB_TOKEN": "global-token",
            "KAIROS_AI_ALIGNMENT_ENDPOINT": "https://strong.example.com/v1",
            "KAIROS_AI_ALIGNMENT_KEY": "align-key",
            "KAIROS_AI_ALIGNMENT_MODEL": "gpt-5.5",
        }
        with patch.dict(os.environ, env, clear=True):
            config = resolve_provider_config(role="alignment")
        assert config.provider == "endpoint:alignment"
        assert config.endpoint == "https://strong.example.com/v1"
        assert config.api_key == "align-key"
        assert config.model == "gpt-5.5"

    def test_other_role_unaffected_by_role_endpoint(self):
        # Alignment has a dedicated endpoint; judgment falls back to global github.
        env = {
            "GITHUB_TOKEN": "global-token",
            "KAIROS_AI_ALIGNMENT_ENDPOINT": "https://strong.example.com/v1",
        }
        with patch.dict(os.environ, env, clear=True):
            config = resolve_provider_config(role="judgment")
        assert config.provider == "github"
        assert config.endpoint == GITHUB_MODELS_ENDPOINT

    def test_role_model_override_keeps_global_provider(self):
        # Only the model is overridden; the global github provider still resolves.
        env = {"GITHUB_TOKEN": "tok", "KAIROS_AI_ALIGNMENT_MODEL": "gpt-5.5"}
        with patch.dict(os.environ, env, clear=True):
            config = resolve_provider_config(role="alignment")
        assert config.provider == "github"
        assert config.endpoint == GITHUB_MODELS_ENDPOINT
        assert config.model == "gpt-5.5"

    def test_no_role_ignores_role_vars(self):
        env = {"GITHUB_TOKEN": "tok", "KAIROS_AI_ALIGNMENT_MODEL": "gpt-5.5"}
        with patch.dict(os.environ, env, clear=True):
            config = resolve_provider_config()
        assert config.model == DEFAULT_MODEL

    def test_resolve_role_model_helper(self):
        from kairos_ontology.core.ai_provider import resolve_role_model

        with patch.dict(os.environ, {"KAIROS_AI_JUDGMENT_MODEL": "mini-x"}, clear=True):
            assert resolve_role_model("judgment", "fallback") == "mini-x"
            assert resolve_role_model("alignment", "fallback") == "fallback"
            assert resolve_role_model(None, "fallback") == "fallback"

    @patch("openai.OpenAI")
    def test_get_ai_client_uses_role_endpoint(self, mock_openai_cls):
        mock_openai_cls.return_value = MagicMock()
        env = {
            "GITHUB_TOKEN": "global-token",
            "KAIROS_AI_ALIGNMENT_ENDPOINT": "https://strong.example.com/v1",
            "KAIROS_AI_ALIGNMENT_KEY": "align-key",
        }
        with patch.dict(os.environ, env, clear=True):
            get_ai_client(role="alignment")
        mock_openai_cls.assert_called_once_with(
            base_url="https://strong.example.com/v1",
            api_key="align-key",
        )


class TestGetAiClient:
    """Test client factory."""

    @patch("openai.OpenAI")
    def test_creates_openai_client(self, mock_openai_cls):
        mock_openai_cls.return_value = MagicMock()
        env = {"GITHUB_TOKEN": "test-token"}
        with patch.dict(os.environ, env, clear=True):
            client = get_ai_client()

        mock_openai_cls.assert_called_once_with(
            base_url=GITHUB_MODELS_ENDPOINT,
            api_key="test-token",
        )
        assert client is not None

    @patch("kairos_ontology.core.ai_provider.logger")
    @patch("openai.OpenAI")
    def test_logs_sanitized_endpoint(self, mock_openai_cls, mock_logger):
        mock_openai_cls.return_value = MagicMock()
        env = {
            "KAIROS_AI_ALIGNMENT_ENDPOINT": "https://user:pass@strong.example.com/v1?key=secret",
            "KAIROS_AI_ALIGNMENT_KEY": "align-key",
        }
        with patch.dict(os.environ, env, clear=True):
            get_ai_client(role="alignment")

        assert mock_logger.info.called
        info_args = mock_logger.info.call_args.args
        assert info_args[2] == "https://strong.example.com"

    @patch("kairos_ontology.core.ai_provider._create_foundry_client")
    def test_foundry_delegates_to_create_foundry_client(self, mock_create):
        mock_create.return_value = MagicMock()
        env = {
            "KAIROS_AI_PROVIDER": "foundry",
            "AZURE_FOUNDRY_ENDPOINT": "https://my.ai.azure.com/api/projects/proj",
            "AZURE_FOUNDRY_API_KEY": "fkey",
        }
        with patch.dict(os.environ, env, clear=True):
            client = get_ai_client()

        mock_create.assert_called_once()
        assert client is not None


class TestCreateFoundryClient:
    """Test Foundry client creation."""

    def test_foundry_missing_sdk_raises(self):
        """Missing azure-ai-projects package should raise EnvironmentError."""
        from kairos_ontology.core.ai_provider import _create_foundry_client, AIProviderConfig

        config = AIProviderConfig(
            provider="foundry",
            endpoint="https://my.ai.azure.com/api/projects/proj",
            api_key="key",
            model="gpt-5.4-mini",
        )
        # Simulate ImportError for azure.ai.projects
        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def fail_import(name, *args, **kwargs):
            if name == "azure.ai.projects":
                raise ImportError("No module named 'azure.ai.projects'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_import):
            with pytest.raises(EnvironmentError, match="azure-ai-projects") as exc_info:
                _create_foundry_client(config)
        assert "uv sync --extra foundry" in str(exc_info.value)

    def test_foundry_with_api_key_uses_the_openai_surface_directly(self):
        """An API key must NOT go through AIProjectClient.

        That SDK path calls ``credential.get_token()``, which ``AzureKeyCredential``
        does not implement -- and it does so lazily, when the client is first used, so
        the old ``AttributeError`` fallback never fired and the failure surfaced at the
        call site as "endpoint unreachable". Verified against a live Foundry resource:
        both configured models answer over ``<resource>/openai/v1`` with key auth.
        """
        from kairos_ontology.core.ai_provider import AIProviderConfig, _create_foundry_client

        config = AIProviderConfig(
            provider="foundry",
            endpoint="https://my.services.ai.azure.com/api/projects/proj",
            api_key="my-foundry-key",
            model="gpt-5.4-mini",
        )

        mock_openai_module = MagicMock()
        mock_projects_module = MagicMock()
        with patch.dict(
            "sys.modules",
            {"openai": mock_openai_module, "azure.ai.projects": mock_projects_module},
        ):
            client = _create_foundry_client(config)

        mock_projects_module.AIProjectClient.assert_not_called()
        mock_openai_module.OpenAI.assert_called_once_with(
            base_url="https://my.services.ai.azure.com/openai/v1",
            api_key="my-foundry-key",
        )
        assert client is mock_openai_module.OpenAI.return_value

    def test_foundry_without_api_key_still_uses_token_credential(self):
        """Entra ID auth is unchanged: no key means AIProjectClient + a TokenCredential."""
        from kairos_ontology.core.ai_provider import AIProviderConfig, _create_foundry_client

        config = AIProviderConfig(
            provider="foundry",
            endpoint="https://my.services.ai.azure.com/api/projects/proj",
            api_key="",
            model="gpt-5.4-mini",
        )

        mock_openai = MagicMock()
        project_client = MagicMock()
        project_client.get_openai_client.return_value = mock_openai
        mock_projects_module = MagicMock()
        mock_projects_module.AIProjectClient.return_value = project_client
        mock_identity_module = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "azure.ai.projects": mock_projects_module,
                "azure.identity": mock_identity_module,
            },
        ):
            client = _create_foundry_client(config)

        mock_projects_module.AIProjectClient.assert_called_once()
        assert (
            mock_projects_module.AIProjectClient.call_args.kwargs["endpoint"]
            == config.endpoint
        )
        assert client is mock_openai

    def test_foundry_no_key_no_identity_raises(self):
        """Foundry without API key and without azure-identity should error."""
        from kairos_ontology.core.ai_provider import _create_foundry_client, AIProviderConfig

        config = AIProviderConfig(
            provider="foundry",
            endpoint="https://my.ai.azure.com/api/projects/proj",
            api_key="",
            model="gpt-5.4-mini",
        )
        mock_projects_module = MagicMock()

        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def selective_import(name, *args, **kwargs):
            if name == "azure.identity":
                raise ImportError("No module named 'azure.identity'")
            if name == "azure.ai.projects":
                return mock_projects_module
            return real_import(name, *args, **kwargs)

        with patch.dict("sys.modules", {"azure.ai.projects": mock_projects_module}):
            with patch("builtins.__import__", side_effect=selective_import):
                with pytest.raises(EnvironmentError, match="azure-identity") as exc_info:
                    _create_foundry_client(config)
        assert "uv sync --extra foundry" in str(exc_info.value)


class TestDefaultModel:
    """Verify the default model is gpt-5.4-mini."""

    def test_default_model_value(self):
        assert DEFAULT_MODEL == "gpt-5.4-mini"


class TestCreateClientFromConfig:
    """_create_client_from_config dispatches by provider (issue #463 refactor)."""

    def test_dispatches_non_foundry_to_openai(self):
        from kairos_ontology.core.ai_provider import _create_client_from_config, AIProviderConfig

        config = AIProviderConfig(
            provider="github",
            endpoint="https://models.github.ai",
            api_key="gho_test",
            model="gpt-5.4-mini",
        )
        client = _create_client_from_config(config)
        assert client is not None

    def test_dispatches_foundry_to_foundry_factory(self):
        from kairos_ontology.core.ai_provider import _create_client_from_config, AIProviderConfig

        mock_openai = MagicMock()
        mock_project = MagicMock()
        mock_project.get_openai_client.return_value = mock_openai
        mock_projects = MagicMock()
        mock_projects.AIProjectClient.return_value = mock_project

        config = AIProviderConfig(
            provider="foundry",
            endpoint="https://my.ai.azure.com/api/projects/proj",
            api_key="",
            model="gpt-5.4-mini",
        )

        with patch.dict("sys.modules", {"azure.ai.projects": mock_projects}):
            with patch.dict("os.environ", {"AZURE_FOUNDRY_API_KEY": ""}):
                client = _create_client_from_config(config)
        assert client is mock_openai


class TestSanitizeProviderError:
    """Alignment-reliability: redacted, length-capped, safe-to-persist errors."""

    def test_redacts_api_key_like_content(self):
        from kairos_ontology.core.ai_provider import sanitize_provider_error

        exc = RuntimeError("failed: api_key=sk-abcdefgh12345678 rejected")
        msg = sanitize_provider_error(exc)
        assert "sk-abcdefgh12345678" not in msg
        assert "[redacted]" in msg
        assert msg.startswith("RuntimeError:")

    def test_redacts_bearer_token(self):
        from kairos_ontology.core.ai_provider import sanitize_provider_error

        exc = RuntimeError("Authorization: Bearer ghp_1234567890abcdefghij denied")
        msg = sanitize_provider_error(exc)
        assert "ghp_1234567890abcdefghij" not in msg

    def test_caps_length(self):
        from kairos_ontology.core.ai_provider import (
            MAX_SAFE_ERROR_CHARS,
            sanitize_provider_error,
        )

        exc = RuntimeError("x" * 5000)
        msg = sanitize_provider_error(exc)
        assert len(msg) <= MAX_SAFE_ERROR_CHARS
        assert msg.endswith("…")

    def test_plain_message_passthrough(self):
        from kairos_ontology.core.ai_provider import sanitize_provider_error

        exc = ValueError("simple message, no secrets")
        msg = sanitize_provider_error(exc)
        assert msg == "ValueError: simple message, no secrets"


class TestCreateChatCompletion:
    """Alignment-reliability: capability-aware, narrowly-guarded single retry."""

    def _client(self, side_effect=None, return_value=None):
        client = MagicMock()
        if side_effect is not None:
            client.chat.completions.create.side_effect = side_effect
        else:
            client.chat.completions.create.return_value = return_value
        return client

    def test_success_passthrough(self):
        from kairos_ontology.core.ai_provider import create_chat_completion

        client = self._client(return_value="ok")
        result = create_chat_completion(
            client,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.1,
        )
        assert result == "ok"
        client.chat.completions.create.assert_called_once_with(
            model="m", messages=[{"role": "user", "content": "hi"}], temperature=0.1
        )

    def test_retries_once_dropping_unsupported_param(self):
        from kairos_ontology.core.ai_provider import create_chat_completion

        client = self._client(
            side_effect=[
                RuntimeError("Unsupported parameter: 'temperature' is not supported"),
                "ok-without-temperature",
            ]
        )
        result = create_chat_completion(
            client,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        assert result == "ok-without-temperature"
        assert client.chat.completions.create.call_count == 2
        second_call_kwargs = client.chat.completions.create.call_args_list[1].kwargs
        assert "temperature" not in second_call_kwargs
        assert second_call_kwargs["response_format"] == {"type": "json_object"}

    def test_unrelated_error_propagates_unchanged(self):
        from kairos_ontology.core.ai_provider import create_chat_completion

        client = self._client(side_effect=RuntimeError("network timeout"))
        with pytest.raises(RuntimeError, match="network timeout"):
            create_chat_completion(
                client,
                model="m",
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.1,
            )
        client.chat.completions.create.assert_called_once()

    def test_unsupported_param_not_actually_sent_propagates(self):
        """A rejection naming a param we never sent must not trigger a retry."""
        from kairos_ontology.core.ai_provider import create_chat_completion

        client = self._client(
            side_effect=RuntimeError("Unsupported parameter: 'top_p' is not supported")
        )
        with pytest.raises(RuntimeError, match="top_p"):
            create_chat_completion(
                client,
                model="m",
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.1,
            )
        client.chat.completions.create.assert_called_once()

    def test_second_failure_after_retry_propagates(self):
        """The retry is attempted exactly once — a second failure is not retried again."""
        from kairos_ontology.core.ai_provider import create_chat_completion

        client = self._client(
            side_effect=[
                RuntimeError("Unsupported parameter: 'temperature' is not supported"),
                RuntimeError("Unsupported parameter: 'temperature' is not supported"),
            ]
        )
        with pytest.raises(RuntimeError):
            create_chat_completion(
                client,
                model="m",
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.1,
            )
        assert client.chat.completions.create.call_count == 2

    def test_rejection_is_remembered_for_later_calls_to_same_model(self):
        """A per-table stage pays the discovery round-trip once, not once per table."""
        from kairos_ontology.core.ai_provider import create_chat_completion

        client = self._client(
            side_effect=[
                RuntimeError("Unsupported parameter: 'temperature' is not supported"),
                "ok-1",
                "ok-2",
                "ok-3",
            ]
        )
        for _ in range(3):
            create_chat_completion(
                client,
                model="m",
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.1,
                seed=7,
            )
        # 1 rejected + 1 retry for the first call, then 2 clean calls: 4, not 6.
        assert client.chat.completions.create.call_count == 4
        for call in client.chat.completions.create.call_args_list[1:]:
            assert "temperature" not in call.kwargs
            assert call.kwargs["seed"] == 7, "the supported parameter must survive"

    def test_rejection_is_remembered_per_model_not_globally(self):
        """One model rejecting a parameter must not strip it for a different model."""
        from kairos_ontology.core.ai_provider import create_chat_completion

        client = self._client(
            side_effect=[
                RuntimeError("Unsupported parameter: 'temperature' is not supported"),
                "ok-reasoning",
                "ok-other",
            ]
        )
        create_chat_completion(
            client, model="reasoning", messages=[], temperature=0.1
        )
        create_chat_completion(client, model="other", messages=[], temperature=0.1)
        assert client.chat.completions.create.call_args_list[-1].kwargs["temperature"] == 0.1


class TestResolveAISeed:
    """DD-174: seeding is the only variance lever the reasoning tier accepts."""

    def test_defaults_to_the_fixed_seed(self):
        from kairos_ontology.core.ai_provider import DEFAULT_AI_SEED, resolve_ai_seed

        assert resolve_ai_seed("alignment") == DEFAULT_AI_SEED
        assert resolve_ai_seed(None) == DEFAULT_AI_SEED

    def test_global_override(self):
        from kairos_ontology.core.ai_provider import resolve_ai_seed

        with patch.dict(os.environ, {"KAIROS_AI_SEED": "99"}):
            assert resolve_ai_seed("alignment") == 99

    def test_role_override_beats_global(self):
        from kairos_ontology.core.ai_provider import resolve_ai_seed

        with patch.dict(
            os.environ, {"KAIROS_AI_SEED": "99", "KAIROS_AI_ALIGNMENT_SEED": "7"}
        ):
            assert resolve_ai_seed("alignment") == 7
            assert resolve_ai_seed("judgment") == 99

    @pytest.mark.parametrize("value", ["off", "none", "random", "", "  "])
    def test_seeding_can_be_disabled(self, value):
        """The escape hatch for deliberately measuring run-to-run variation."""
        from kairos_ontology.core.ai_provider import resolve_ai_seed

        with patch.dict(os.environ, {"KAIROS_AI_SEED": value}):
            assert resolve_ai_seed("alignment") is None

    def test_non_integer_raises_rather_than_silently_unseeding(self):
        """A typo must not produce output that looks reproducible but is not."""
        from kairos_ontology.core.ai_provider import resolve_ai_seed

        with patch.dict(os.environ, {"KAIROS_AI_SEED": "cheese"}):
            with pytest.raises(ValueError, match="not an integer"):
                resolve_ai_seed("alignment")


class TestFoundryOpenAIBaseUrl:
    """DD: derive the OpenAI-compatible surface from either configured shape."""

    @pytest.mark.parametrize(
        "endpoint",
        [
            "https://res.services.ai.azure.com/api/projects/proj",
            "https://res.services.ai.azure.com/api/projects/proj/",
            "https://res.services.ai.azure.com",
            "https://res.services.ai.azure.com/",
            "https://res.services.ai.azure.com/openai/v1",
        ],
    )
    def test_all_configured_shapes_normalise_to_one_base(self, endpoint: str) -> None:
        from kairos_ontology.core.ai_provider import foundry_openai_base_url

        assert foundry_openai_base_url(endpoint) == "https://res.services.ai.azure.com/openai/v1"

    def test_project_segment_is_dropped_not_appended(self) -> None:
        """The project scopes the projects API; a key authenticates the resource."""
        from kairos_ontology.core.ai_provider import foundry_openai_base_url

        assert "projects" not in foundry_openai_base_url(
            "https://res.services.ai.azure.com/api/projects/kairos-ontology"
        )


class TestResolveReasoningEffort:
    """DD-176: effort is a per-role knob, resolved the same way as the seed."""

    def test_per_role_defaults(self):
        from kairos_ontology.core.ai_provider import resolve_reasoning_effort

        # "affinity" is no longer a registered role (#562 collapsed it into
        # "alignment") -- it now behaves like any other unrecognized role.
        assert resolve_reasoning_effort("affinity") is None
        assert resolve_reasoning_effort("alignment") == "medium"
        assert resolve_reasoning_effort("judgment") == "medium"

    def test_unknown_role_leaves_it_to_the_model(self):
        from kairos_ontology.core.ai_provider import resolve_reasoning_effort

        assert resolve_reasoning_effort("something-else") is None

    def test_role_override_beats_global(self):
        from kairos_ontology.core.ai_provider import resolve_reasoning_effort

        with patch.dict(
            os.environ,
            {
                "KAIROS_AI_REASONING_EFFORT": "high",
                "KAIROS_AI_ALIGNMENT_REASONING_EFFORT": "low",
            },
        ):
            assert resolve_reasoning_effort("alignment") == "low"
            assert resolve_reasoning_effort("judgment") == "high"

    @pytest.mark.parametrize("value", ["off", "default", "none", ""])
    def test_can_be_disabled(self, value):
        from kairos_ontology.core.ai_provider import resolve_reasoning_effort

        with patch.dict(os.environ, {"KAIROS_AI_ALIGNMENT_REASONING_EFFORT": value}):
            assert resolve_reasoning_effort("alignment") is None

    def test_unknown_tier_raises(self):
        """A typo must fail loudly, not silently revert to the model default."""
        from kairos_ontology.core.ai_provider import resolve_reasoning_effort

        with patch.dict(os.environ, {"KAIROS_AI_ALIGNMENT_REASONING_EFFORT": "lowish"}):
            with pytest.raises(ValueError, match="not a reasoning effort"):
                resolve_reasoning_effort("alignment")

    def test_none_valued_kwargs_are_not_sent(self):
        """A disabled knob must be absent from the request, not sent as null."""
        from kairos_ontology.core.ai_provider import create_chat_completion

        client = MagicMock()
        client.chat.completions.create.return_value = "ok"
        create_chat_completion(
            client, model="m", messages=[], seed=None, reasoning_effort=None, temperature=0.1
        )
        kwargs = client.chat.completions.create.call_args.kwargs
        assert "seed" not in kwargs
        assert "reasoning_effort" not in kwargs
        assert kwargs["temperature"] == 0.1
