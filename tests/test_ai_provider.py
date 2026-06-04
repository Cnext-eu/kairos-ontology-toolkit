# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for AI provider abstraction."""

import os
from unittest.mock import patch, MagicMock

import pytest

from kairos_ontology.ai_provider import (
    resolve_provider_config,
    get_ai_client,
    GITHUB_MODELS_ENDPOINT,
    DEFAULT_MODEL,
)


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

    def test_error_no_config(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(EnvironmentError, match="No AI provider configured"):
                resolve_provider_config()

    def test_error_unknown_provider(self):
        with patch.dict(os.environ, {"KAIROS_AI_PROVIDER": "invalid"}, clear=True):
            with pytest.raises(EnvironmentError, match="Unknown KAIROS_AI_PROVIDER"):
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


class TestDefaultModel:
    """Verify the default model is gpt-5.4-mini."""

    def test_default_model_value(self):
        assert DEFAULT_MODEL == "gpt-5.4-mini"
