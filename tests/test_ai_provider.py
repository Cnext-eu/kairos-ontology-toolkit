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
        with patch.dict(os.environ, env, clear=True), \
             patch.dict("sys.modules", {"azure": None, "azure.identity": None}):
            with pytest.raises(EnvironmentError):
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
        # Alignment has a dedicated endpoint; affinity falls back to global github.
        env = {
            "GITHUB_TOKEN": "global-token",
            "KAIROS_AI_ALIGNMENT_ENDPOINT": "https://strong.example.com/v1",
        }
        with patch.dict(os.environ, env, clear=True):
            config = resolve_provider_config(role="affinity")
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
        with patch.dict(os.environ, {"KAIROS_AI_AFFINITY_MODEL": "mini-x"}, clear=True):
            assert resolve_role_model("affinity", "fallback") == "mini-x"
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
        real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') \
            else __import__

        def fail_import(name, *args, **kwargs):
            if name == "azure.ai.projects":
                raise ImportError("No module named 'azure.ai.projects'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_import):
            with pytest.raises(EnvironmentError, match="azure-ai-projects"):
                _create_foundry_client(config)

    def test_foundry_with_api_key(self):
        """Foundry with API key uses AzureKeyCredential when the SDK accepts it."""
        from kairos_ontology.core.ai_provider import _create_foundry_client, AIProviderConfig

        mock_project_client = MagicMock()
        mock_openai = MagicMock()
        mock_project_client.get_openai_client.return_value = mock_openai

        mock_projects_module = MagicMock()
        mock_projects_module.AIProjectClient.return_value = mock_project_client

        mock_key_cred_module = MagicMock()

        config = AIProviderConfig(
            provider="foundry",
            endpoint="https://my.ai.azure.com/api/projects/proj",
            api_key="my-foundry-key",
            model="gpt-5.4-mini",
        )

        with patch.dict("sys.modules", {
            "azure.ai.projects": mock_projects_module,
            "azure.core.credentials": mock_key_cred_module,
        }):
            client = _create_foundry_client(config)

        mock_projects_module.AIProjectClient.assert_called_once()
        call_kwargs = mock_projects_module.AIProjectClient.call_args.kwargs
        assert call_kwargs["endpoint"] == config.endpoint
        mock_project_client.get_openai_client.assert_called_once()
        assert client is mock_openai

    def test_foundry_api_key_falls_back_to_token_credential(self):
        """When the Foundry SDK rejects the API key (needs get_token), fall back
        to DefaultAzureCredential and succeed."""
        from kairos_ontology.core.ai_provider import _create_foundry_client, AIProviderConfig

        key_sentinel = object()
        token_sentinel = object()
        mock_openai = MagicMock()

        key_project = MagicMock()
        key_project.get_openai_client.side_effect = AttributeError(
            "'AzureKeyCredential' object has no attribute 'get_token'"
        )
        token_project = MagicMock()
        token_project.get_openai_client.return_value = mock_openai

        def make_client(*, endpoint, credential):
            if credential is key_sentinel:
                return key_project
            return token_project

        mock_projects_module = MagicMock()
        mock_projects_module.AIProjectClient.side_effect = make_client

        mock_key_cred_module = MagicMock()
        mock_key_cred_module.AzureKeyCredential.return_value = key_sentinel

        mock_identity_module = MagicMock()
        mock_identity_module.DefaultAzureCredential.return_value = token_sentinel

        config = AIProviderConfig(
            provider="foundry",
            endpoint="https://my.ai.azure.com/api/projects/proj",
            api_key="my-foundry-key",
            model="gpt-5.4-mini",
        )

        with patch.dict("sys.modules", {
            "azure.ai.projects": mock_projects_module,
            "azure.core.credentials": mock_key_cred_module,
            "azure.identity": mock_identity_module,
        }):
            client = _create_foundry_client(config)

        assert client is mock_openai
        assert mock_projects_module.AIProjectClient.call_count == 2
        mock_identity_module.DefaultAzureCredential.assert_called_once()

    def test_foundry_api_key_fallback_no_identity_raises(self):
        """API key rejected by SDK and azure-identity missing → clear error."""
        from kairos_ontology.core.ai_provider import _create_foundry_client, AIProviderConfig

        key_sentinel = object()
        key_project = MagicMock()
        key_project.get_openai_client.side_effect = AttributeError(
            "'AzureKeyCredential' object has no attribute 'get_token'"
        )
        mock_projects_module = MagicMock()
        mock_projects_module.AIProjectClient.return_value = key_project

        mock_key_cred_module = MagicMock()
        mock_key_cred_module.AzureKeyCredential.return_value = key_sentinel

        config = AIProviderConfig(
            provider="foundry",
            endpoint="https://my.ai.azure.com/api/projects/proj",
            api_key="my-foundry-key",
            model="gpt-5.4-mini",
        )

        real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') \
            else __import__

        def selective_import(name, *args, **kwargs):
            if name == "azure.identity":
                raise ImportError("No module named 'azure.identity'")
            return real_import(name, *args, **kwargs)

        with patch.dict("sys.modules", {
            "azure.ai.projects": mock_projects_module,
            "azure.core.credentials": mock_key_cred_module,
        }):
            with patch("builtins.__import__", side_effect=selective_import):
                with pytest.raises(EnvironmentError, match="azure-identity"):
                    _create_foundry_client(config)

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

        real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') \
            else __import__

        def selective_import(name, *args, **kwargs):
            if name == "azure.identity":
                raise ImportError("No module named 'azure.identity'")
            if name == "azure.ai.projects":
                return mock_projects_module
            return real_import(name, *args, **kwargs)

        with patch.dict("sys.modules", {"azure.ai.projects": mock_projects_module}):
            with patch("builtins.__import__", side_effect=selective_import):
                with pytest.raises(EnvironmentError, match="azure-identity"):
                    _create_foundry_client(config)


class TestDefaultModel:
    """Verify the default model is gpt-5.4-mini."""

    def test_default_model_value(self):
        assert DEFAULT_MODEL == "gpt-5.4-mini"
