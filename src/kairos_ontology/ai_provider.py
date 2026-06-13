# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""AI provider abstraction for LLM-powered analysis commands.

Supports multiple AI backends via environment variable configuration:
- GitHub Models (default): uses GITHUB_TOKEN
- Azure AI Foundry: uses AZURE_AI_ENDPOINT + AZURE_AI_KEY
- Microsoft Foundry: uses AZURE_FOUNDRY_ENDPOINT + azure-ai-projects SDK

Both providers return an OpenAI-compatible client instance.
Automatically loads .env from the hub root (or CWD) if present.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# .env auto-loading
# ---------------------------------------------------------------------------


def _load_dotenv_from_hub():
    """Load .env file from repo root or hub subfolder (whichever is found first)."""
    cwd = Path.cwd()
    candidates: list[Path] = [cwd / ".env"]

    hub_dir: Path | None = None
    # Walk up to detect either:
    # 1) we're inside ontology-hub itself (has model/ontologies), or
    # 2) we're in repo root (has ontology-hub/ child)
    for parent in [cwd] + list(cwd.parents)[:5]:
        if (parent / "model" / "ontologies").is_dir():
            hub_dir = parent
            break
        if (parent / "ontology-hub").is_dir():
            hub_dir = parent / "ontology-hub"
            break

    if hub_dir is not None:
        candidates.append(hub_dir / ".env")
        candidates.append(hub_dir.parent / ".env")

    ordered_candidates: list[Path] = []
    seen: set[Path] = set()
    for env_file in candidates:
        if env_file in seen:
            continue
        seen.add(env_file)
        ordered_candidates.append(env_file)

    for env_file in ordered_candidates:
        if env_file.is_file():
            load_dotenv(env_file, override=False)
            logger.debug("Loaded .env from %s", env_file)
            return


_load_dotenv_from_hub()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"
DEFAULT_MODEL = "gpt-5.4-mini"

# Environment variable names
ENV_PROVIDER = "KAIROS_AI_PROVIDER"
ENV_GITHUB_TOKEN = "GITHUB_TOKEN"
ENV_AZURE_ENDPOINT = "AZURE_AI_ENDPOINT"
ENV_AZURE_KEY = "AZURE_AI_KEY"
ENV_FOUNDRY_ENDPOINT = "AZURE_FOUNDRY_ENDPOINT"
ENV_FOUNDRY_API_KEY = "AZURE_FOUNDRY_API_KEY"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class AIProviderConfig:
    """Resolved AI provider configuration."""
    provider: str  # "github", "azure", or "foundry"
    endpoint: str
    api_key: str
    model: str


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------


def resolve_provider_config(model: str = DEFAULT_MODEL) -> AIProviderConfig:
    """Resolve AI provider configuration from environment variables.

    Detection order:
    1. KAIROS_AI_PROVIDER env var (explicit: "github", "azure", or "foundry")
    2. If AZURE_AI_ENDPOINT is set → azure
    3. If AZURE_FOUNDRY_ENDPOINT is set → foundry
    4. If GITHUB_TOKEN is set → github
    5. Error if nothing is configured

    Returns:
        AIProviderConfig with provider, endpoint, api_key, model.

    Raises:
        EnvironmentError: If no valid configuration is found.
    """
    explicit_provider = os.environ.get(ENV_PROVIDER, "").lower().strip()

    if explicit_provider == "azure" or (
        not explicit_provider and os.environ.get(ENV_AZURE_ENDPOINT)
    ):
        return _resolve_azure(model)
    elif explicit_provider == "foundry" or (
        not explicit_provider and os.environ.get(ENV_FOUNDRY_ENDPOINT)
    ):
        return _resolve_foundry(model)
    elif explicit_provider == "github" or (
        not explicit_provider and os.environ.get(ENV_GITHUB_TOKEN)
    ):
        return _resolve_github(model)
    elif explicit_provider:
        raise EnvironmentError(
            f"Unknown KAIROS_AI_PROVIDER value: '{explicit_provider}'. "
            f"Supported values: 'github', 'azure', 'foundry'."
        )
    else:
        raise EnvironmentError(
            "No AI provider configured. Set one of:\n"
            f"  - {ENV_GITHUB_TOKEN} (for GitHub Models)\n"
            f"  - {ENV_AZURE_ENDPOINT} + {ENV_AZURE_KEY} (for Azure AI Foundry)\n"
            f"  - {ENV_FOUNDRY_ENDPOINT} (for Microsoft Foundry)\n"
            f"  - {ENV_PROVIDER}=github|azure|foundry (explicit provider selection)"
        )


def _resolve_github(model: str) -> AIProviderConfig:
    """Resolve GitHub Models configuration."""
    token = os.environ.get(ENV_GITHUB_TOKEN)
    if not token:
        raise EnvironmentError(
            f"{ENV_GITHUB_TOKEN} environment variable is required for GitHub Models provider. "
            "Set it to a GitHub personal access token with Models API access."
        )
    return AIProviderConfig(
        provider="github",
        endpoint=GITHUB_MODELS_ENDPOINT,
        api_key=token,
        model=model,
    )


def _resolve_azure(model: str) -> AIProviderConfig:
    """Resolve Azure AI Foundry configuration."""
    endpoint = os.environ.get(ENV_AZURE_ENDPOINT)
    if not endpoint:
        raise EnvironmentError(
            f"{ENV_AZURE_ENDPOINT} environment variable is required for Azure AI Foundry. "
            "Set it to your Azure AI Foundry endpoint URL."
        )

    api_key = os.environ.get(ENV_AZURE_KEY)
    if not api_key:
        # Try managed identity
        api_key = _get_azure_managed_identity_token()

    return AIProviderConfig(
        provider="azure",
        endpoint=endpoint,
        api_key=api_key,
        model=model,
    )


def _get_azure_managed_identity_token() -> str:
    """Attempt to get a token via Azure managed identity."""
    try:
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
        token = credential.get_token("https://cognitiveservices.azure.com/.default")
        return token.token
    except ImportError:
        raise EnvironmentError(
            f"Neither {ENV_AZURE_KEY} is set nor azure-identity is installed. "
            f"Install with: pip install kairos-ontology-toolkit[azure]"
        )
    except Exception as e:
        raise EnvironmentError(
            f"Azure managed identity authentication failed: {e}. "
            f"Set {ENV_AZURE_KEY} explicitly or check your Azure identity configuration."
        )


def _resolve_foundry(model: str) -> AIProviderConfig:
    """Resolve Microsoft Foundry configuration using azure-ai-projects SDK."""
    endpoint = os.environ.get(ENV_FOUNDRY_ENDPOINT)
    if not endpoint:
        raise EnvironmentError(
            f"{ENV_FOUNDRY_ENDPOINT} environment variable is required for Microsoft Foundry. "
            "Set it to your Foundry project endpoint URL.\n"
            "Format: https://<resource>.services.ai.azure.com/api/projects/<project>"
        )

    api_key = os.environ.get(ENV_FOUNDRY_API_KEY, "")
    return AIProviderConfig(
        provider="foundry",
        endpoint=endpoint,
        api_key=api_key,
        model=model,
    )


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


def get_ai_client(model: str = DEFAULT_MODEL):
    """Create an OpenAI-compatible client for the configured AI provider.

    Args:
        model: The model name to use. Stored in config for reference.

    Returns:
        An OpenAI client instance configured for the resolved provider.

    Raises:
        EnvironmentError: If no valid provider configuration is found.
    """
    config = resolve_provider_config(model)

    logger.info("Using AI provider: %s (endpoint: %s)", config.provider, config.endpoint)

    if config.provider == "foundry":
        return _create_foundry_client(config)

    from openai import OpenAI
    return OpenAI(
        base_url=config.endpoint,
        api_key=config.api_key,
    )


def _create_foundry_client(config: AIProviderConfig):
    """Create an OpenAI-compatible client via the Microsoft Foundry SDK."""
    try:
        from azure.ai.projects import AIProjectClient
    except ImportError:
        raise EnvironmentError(
            "The azure-ai-projects package is required for the Foundry provider. "
            "Install with: pip install kairos-ontology-toolkit[foundry]"
        )

    if config.api_key:
        from azure.core.credentials import AzureKeyCredential
        credential = AzureKeyCredential(config.api_key)
    else:
        try:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
        except ImportError:
            raise EnvironmentError(
                f"Neither {ENV_FOUNDRY_API_KEY} is set nor azure-identity is installed. "
                "Install with: pip install kairos-ontology-toolkit[foundry]"
            )

    project_client = AIProjectClient(
        endpoint=config.endpoint,
        credential=credential,
    )
    return project_client.get_openai_client()
