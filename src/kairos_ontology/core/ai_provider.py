# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""AI provider abstraction for LLM-powered analysis commands.

Supports multiple AI backends via environment variable configuration:
- GitHub Models (default): uses GITHUB_TOKEN
- Azure AI Foundry: uses AZURE_AI_ENDPOINT + AZURE_AI_KEY
- Microsoft Foundry: uses AZURE_FOUNDRY_ENDPOINT + azure-ai-projects SDK

Additionally supports per-role endpoint/model overrides (issue #182) so the
``affinity`` (analyse-sources) and ``alignment`` (propose-alignment) steps can use
independent endpoints/models via ``KAIROS_AI_{ROLE}_ENDPOINT`` / ``_KEY`` /
``_MODEL``.

Both providers return an OpenAI-compatible client instance.
Automatically loads .env from the hub root (or CWD) if present.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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
# Per-role endpoint overrides (issue #182)
# ---------------------------------------------------------------------------
# The two LLM-powered pre-modeling steps have different accuracy/cost profiles:
#
#   * "affinity"  (analyse-sources)   — coarse table → domain classification; the
#     high-volume call (one per table × every source system). A small model
#     (gpt-5.4-mini) is fine.
#   * "alignment" (propose-alignment) — closed-vocabulary reasoning (pick the right
#     ref_class, map every column). Accuracy-sensitive; benefits from a stronger
#     model and may live on a separate deployment/endpoint.
#
# Each role may point at its own OpenAI-compatible endpoint via
# ``KAIROS_AI_{ROLE}_ENDPOINT`` (+ ``_KEY`` + ``_MODEL``). When a role endpoint is
# not set the role falls back to the global provider configuration above, with an
# optional ``KAIROS_AI_{ROLE}_MODEL`` model override.
ROLE_AFFINITY = "affinity"
ROLE_ALIGNMENT = "alignment"


def _role_env(role: str | None, suffix: str) -> str:
    """Read a per-role env var ``KAIROS_AI_{ROLE}_{SUFFIX}`` (empty if unset/no role)."""
    if not role:
        return ""
    return os.environ.get(f"KAIROS_AI_{role.upper()}_{suffix}", "").strip()


def resolve_role_model(role: str | None, default: str = DEFAULT_MODEL) -> str:
    """Return the model configured for ``role`` (``KAIROS_AI_{ROLE}_MODEL``) or ``default``."""
    return _role_env(role, "MODEL") or default


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


def resolve_provider_config(
    model: str = DEFAULT_MODEL, *, role: str | None = None
) -> AIProviderConfig:
    """Resolve AI provider configuration from environment variables.

    When ``role`` is given (``"affinity"`` / ``"alignment"``) and a per-role
    endpoint is configured (``KAIROS_AI_{ROLE}_ENDPOINT``), that OpenAI-compatible
    endpoint wins, letting the two pre-modeling steps use independent endpoints/
    models (issue #182). Otherwise the global provider is resolved and, if set, the
    per-role model override (``KAIROS_AI_{ROLE}_MODEL``) is applied.

    ``config.model`` is the per-role *default*, not an authority: a caller that
    already resolved its own model precedence (e.g. ``propose-alignment``, where
    an explicit ``--model``/``--high-accuracy`` must beat the env override — see
    DD-128) must keep its own model and use this config for provider/endpoint/
    auth only.

    Detection order (global fallback):
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
    # Per-role dedicated endpoint takes precedence when configured.
    role_endpoint = _role_env(role, "ENDPOINT")
    if role_endpoint:
        return AIProviderConfig(
            provider=f"endpoint:{role}",
            endpoint=role_endpoint,
            api_key=_role_env(role, "KEY"),
            model=resolve_role_model(role, model),
        )

    # Otherwise fall back to the global provider, with an optional role model.
    effective_model = resolve_role_model(role, model)
    explicit_provider = os.environ.get(ENV_PROVIDER, "").lower().strip()

    if explicit_provider == "azure" or (
        not explicit_provider and os.environ.get(ENV_AZURE_ENDPOINT)
    ):
        return _resolve_azure(effective_model)
    elif explicit_provider == "foundry" or (
        not explicit_provider and os.environ.get(ENV_FOUNDRY_ENDPOINT)
    ):
        return _resolve_foundry(effective_model)
    elif explicit_provider == "github" or (
        not explicit_provider and os.environ.get(ENV_GITHUB_TOKEN)
    ):
        return _resolve_github(effective_model)
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
            f"  - {ENV_PROVIDER}=github|azure|foundry (explicit provider selection)\n"
            "Or configure a per-role endpoint, e.g. "
            "KAIROS_AI_ALIGNMENT_ENDPOINT + KAIROS_AI_ALIGNMENT_KEY."
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


def get_ai_client(model: str = DEFAULT_MODEL, *, role: str | None = None):
    """Create an OpenAI-compatible client for the configured AI provider.

    Args:
        model: The model name to use. Stored in config for reference.
        role: Optional pre-modeling role (``"affinity"`` / ``"alignment"``) selecting
            a per-role endpoint override when configured (issue #182).

    Returns:
        An OpenAI client instance configured for the resolved provider.

    Raises:
        EnvironmentError: If no valid provider configuration is found.
    """
    config = resolve_provider_config(model, role=role)

    logger.info(
        "Using AI provider: %s (endpoint: %s)",
        config.provider,
        _endpoint_for_log(config.endpoint),
    )

    if config.provider == "foundry":
        return _create_foundry_client(config)

    from openai import OpenAI
    return OpenAI(
        base_url=config.endpoint,
        api_key=config.api_key,
    )


def _endpoint_for_log(endpoint: str) -> str:
    """Return a non-sensitive endpoint representation suitable for logs."""
    parsed = urlsplit(endpoint)
    if not parsed.scheme or not parsed.hostname:
        return "<redacted>"
    if parsed.port:
        return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    return f"{parsed.scheme}://{parsed.hostname}"


def _create_foundry_client(config: AIProviderConfig):
    """Create an OpenAI-compatible client via the Microsoft Foundry SDK.

    Authentication notes:
        ``AIProjectClient.get_openai_client()`` (azure-ai-projects 2.x) acquires an
        AAD bearer token by calling ``credential.get_token(...)``. An
        ``AzureKeyCredential`` built from ``AZURE_FOUNDRY_API_KEY`` has no
        ``get_token`` method, so key auth cannot satisfy that SDK path. We therefore
        *prefer* a real ``TokenCredential`` (``DefaultAzureCredential``); when an API
        key is provided we attempt it first but fall back to token auth when the SDK
        requires a token credential.
    """
    try:
        from azure.ai.projects import AIProjectClient
    except ImportError:
        raise EnvironmentError(
            "The azure-ai-projects package is required for the Foundry provider. "
            "Install with: pip install kairos-ontology-toolkit[foundry]"
        )

    def _build_token_credential():
        try:
            from azure.identity import DefaultAzureCredential

            return DefaultAzureCredential()
        except ImportError:
            return None

    def _openai_from_credential(credential):
        project_client = AIProjectClient(
            endpoint=config.endpoint,
            credential=credential,
        )
        return project_client.get_openai_client()

    if config.api_key:
        try:
            from azure.core.credentials import AzureKeyCredential

            return _openai_from_credential(AzureKeyCredential(config.api_key))
        except AttributeError:
            # azure-ai-projects requires a TokenCredential (get_token); an API key
            # cannot be used on this SDK path. Fall back to DefaultAzureCredential.
            logger.warning(
                "%s is set but the Foundry SDK requires AAD token auth "
                "(AzureKeyCredential has no get_token). Falling back to "
                "DefaultAzureCredential (az login / managed identity).",
                ENV_FOUNDRY_API_KEY,
            )
            token_credential = _build_token_credential()
            if token_credential is None:
                raise EnvironmentError(
                    "The Microsoft Foundry SDK requires AAD token authentication, "
                    f"but {ENV_FOUNDRY_API_KEY} (an API key) cannot provide a token "
                    "and azure-identity is not installed.\n"
                    "Either run `az login` (or use a managed identity) with "
                    "azure-identity installed, or unset the API key.\n"
                    "Install with: pip install kairos-ontology-toolkit[foundry]"
                )
            return _openai_from_credential(token_credential)

    token_credential = _build_token_credential()
    if token_credential is None:
        raise EnvironmentError(
            f"Neither {ENV_FOUNDRY_API_KEY} is set nor azure-identity is installed. "
            "Install with: pip install kairos-ontology-toolkit[foundry]"
        )
    return _openai_from_credential(token_credential)


# ---------------------------------------------------------------------------
# Safe error metadata (alignment-reliability)
# ---------------------------------------------------------------------------

#: Redacted in place of anything that looks like a credential/token in a
#: provider error message before it is persisted (e.g. into a Claim Registry)
#: or printed to the console.
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|authorization|bearer|secret)\b\s*[:=]?\s*\S+"),
    re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
)

#: Cap on the persisted/printed error message so a verbose SDK/HTTP error body
#: cannot bloat generated YAML or terminal output.
MAX_SAFE_ERROR_CHARS = 300


def sanitize_provider_error(exc: BaseException) -> str:
    """Return a redacted, length-capped, safe-to-persist description of *exc*.

    Used to annotate a per-table ``provider_failure`` alignment outcome (issue
    alignment-reliability): the raw exception message may embed request
    metadata (endpoint URLs, occasionally an echoed header) so it is never
    written to a Claim Registry or echoed to the console unredacted.
    """
    message = f"{type(exc).__name__}: {exc}"
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub("[redacted]", message)
    message = " ".join(message.split())
    if len(message) > MAX_SAFE_ERROR_CHARS:
        message = message[: MAX_SAFE_ERROR_CHARS - 1] + "…"
    return message


# ---------------------------------------------------------------------------
# Capability-aware chat completion (alignment-reliability)
# ---------------------------------------------------------------------------

#: Matches a provider's own rejection of one request parameter, e.g.
#: "Unsupported parameter: 'temperature' is not supported with this model."
#: Deliberately generic (no per-model table): different providers/models phrase
#: this differently, but all name the offending parameter.
_UNSUPPORTED_PARAM_RE = re.compile(
    r"[Uu]nsupported (?:parameter|value)[^'\"]*['\"]([A-Za-z_][A-Za-z0-9_.\[\]]*)['\"]"
)


def _unsupported_request_param(message: str) -> str | None:
    """Best-effort extraction of a rejected top-level request-parameter name."""
    match = _UNSUPPORTED_PARAM_RE.search(message or "")
    if not match:
        return None
    # A dotted/indexed name (e.g. "response_format.type") still means the
    # top-level kwarg is the one to drop.
    return match.group(1).split(".")[0].split("[")[0]


def create_chat_completion(
    client,
    *,
    model: str,
    messages: list[dict[str, Any]],
    **request_kwargs: Any,
):
    """Create a chat completion, capability-aware for per-model parameter support.

    Some models reject specific optional request parameters (e.g. a fixed
    ``temperature`` on certain reasoning-tier models, or ``response_format``).
    Rather than hard-coding a model-name → capability table — which goes stale
    the moment a new model ships — this detects *the provider's own rejection
    message*, drops exactly the named parameter, and retries the call exactly
    once without it. Any other failure (auth, network, rate limit, or a
    rejection that does not name one of the parameters actually sent)
    propagates unchanged; this is a single narrowly-guarded retry, not a
    general error-suppression path.
    """
    try:
        return client.chat.completions.create(model=model, messages=messages, **request_kwargs)
    except Exception as exc:  # noqa: BLE001 — inspected below, re-raised if not a match
        param = _unsupported_request_param(str(exc))
        if not param or param not in request_kwargs:
            raise
        logger.info(
            "Model %s rejected request parameter '%s'; retrying once without it.",
            model, param,
        )
        retry_kwargs = {k: v for k, v in request_kwargs.items() if k != param}
        return client.chat.completions.create(model=model, messages=messages, **retry_kwargs)
