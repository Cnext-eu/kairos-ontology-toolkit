# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""AI provider abstraction for LLM-powered analysis commands.

Supports multiple AI backends via environment variable configuration:
- GitHub Models (default): uses GITHUB_TOKEN
- Azure AI Foundry: uses AZURE_AI_ENDPOINT + AZURE_AI_KEY
- Microsoft Foundry: uses AZURE_FOUNDRY_ENDPOINT + azure-ai-projects SDK

Additionally supports per-role endpoint/model overrides (issue #182) so the
``alignment`` (propose-alignment) and ``judgment`` (archetype conformance)
steps can use independent endpoints/models via ``KAIROS_AI_{ROLE}_ENDPOINT`` /
``_KEY`` / ``_MODEL``. ``analyse-sources`` used to have its own ``affinity``
role; issue #562 collapsed it into ``alignment`` — one configured provider,
the strongest one, for every pre-modeling LLM call (see ``ROLE_ALIGNMENT``).

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

from dotenv import dotenv_values, load_dotenv

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exception hierarchy (DD-159)
# ---------------------------------------------------------------------------


class AIProviderError(EnvironmentError):
    """Base error for all AI provider configuration / connectivity failures.

    Subclasses :class:`EnvironmentError` so every existing ``except EnvironmentError``
    and ``pytest.raises(EnvironmentError, match=...)`` keeps passing unchanged.
    """


class NotConfigured(AIProviderError):
    """No provider is configured at all (missing env vars)."""


class Misconfigured(AIProviderError):
    """A provider is partially configured (e.g. endpoint set but no key)."""


class Unreachable(AIProviderError):
    """The provider endpoint cannot be reached (network / DNS / TLS)."""

# ---------------------------------------------------------------------------
# .env auto-loading
# ---------------------------------------------------------------------------


def _clear_stale_empty_env_vars(env_file: Path) -> None:
    """Treat a pre-existing empty-string env var as unset before `load_dotenv`.

    `load_dotenv(..., override=False)` only checks *presence* in `os.environ`, not
    truthiness (python-dotenv's `DotEnv.set_as_environment_variables`). A shell
    profile, CI runner, or a sourced `.env.example` full of blank placeholders
    (e.g. `AZURE_FOUNDRY_API_KEY=`) can leave a var set to `""` in the process
    environment, which then silently and permanently wins over a real value in
    the hub's .env -- with no error, no log line, nothing pointing at the cause
    (issue #188). Every var this loader is responsible for is an
    endpoint/token/key/model-or-version string; none has a meaningful empty
    value, so an empty pre-existing value is treated the same as absent for
    every key this specific .env file defines.
    """
    for key in dotenv_values(env_file):
        if os.environ.get(key) == "":
            del os.environ[key]


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
            _clear_stale_empty_env_vars(env_file)
            load_dotenv(env_file, override=False)
            logger.debug("Loaded .env from %s", env_file)
            global LOADED_DOTENV_PATH
            LOADED_DOTENV_PATH = str(env_file)
            return


LOADED_DOTENV_PATH: str | None = None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_load_dotenv_from_hub()

# ---------------------------------------------------------------------------
# Constants (continued)
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

#: Every environment variable name this module reads for AI provider configuration.
#: Used by test isolation to guarantee a clean state (DD-159).
AI_ENV_VAR_NAMES: frozenset[str] = frozenset(
    {
        ENV_PROVIDER,
        ENV_GITHUB_TOKEN,
        ENV_AZURE_ENDPOINT,
        ENV_AZURE_KEY,
        ENV_FOUNDRY_ENDPOINT,
        ENV_FOUNDRY_API_KEY,
        "KAIROS_AI_SEED",
        "KAIROS_AI_REASONING_EFFORT",
    }
    | {
        f"KAIROS_AI_{role.upper()}_{suffix}"
        for role in ("alignment", "judgment")
        for suffix in ("ENDPOINT", "KEY", "MODEL", "SEED", "REASONING_EFFORT")
    }
)

# ---------------------------------------------------------------------------
# Per-role endpoint overrides (issue #182; role collapse issue #562)
# ---------------------------------------------------------------------------
# There used to be a separate "affinity" role for analyse-sources (coarse
# table -> domain classification), reasoned as high-volume-so-cheap-model-is-
# fine. Issue #562 collapsed it into "alignment": running two configured
# providers/models for what is, on every real hub measured, the same
# closed-vocabulary reasoning problem at two different granularities added
# operational surface (two things to configure, two things that can silently
# drift apart) for a savings that never showed up as a real accuracy or cost
# win worth defending. One role, the strongest configured model, for every
# pre-modeling LLM call. This is a deliberate behavior change, not a rename:
# analyse-sources now inherits alignment's reasoning-effort default (medium,
# up from affinity's low) and any KAIROS_AI_ALIGNMENT_* tuning also governs
# it — cost and latency for that high-volume call go up by design.
#
# "alignment" (propose-alignment, and now analyse-sources too) may point at
# its own OpenAI-compatible endpoint via ``KAIROS_AI_ALIGNMENT_ENDPOINT``
# (+ ``_KEY`` + ``_MODEL``). When not set, it falls back to the global
# provider configuration above, with an optional
# ``KAIROS_AI_ALIGNMENT_MODEL`` model override.
ROLE_ALIGNMENT = "alignment"
#: Archetype-conformance judgment (DD-167). A third role because the work differs
#: again: ~174 one-shot judgments against a closed outcome vocabulary, where a
#: wrong "conforms" silently certifies a concept the hub never models. Accuracy
#: matters more than cost here, so it gets its own endpoint/model knobs.
ROLE_JUDGMENT = "judgment"


def _role_env(role: str | None, suffix: str) -> str:
    """Read a per-role env var ``KAIROS_AI_{ROLE}_{SUFFIX}`` (empty if unset/no role)."""
    if not role:
        return ""
    return os.environ.get(f"KAIROS_AI_{role.upper()}_{suffix}", "").strip()


def resolve_role_model(role: str | None, default: str = DEFAULT_MODEL) -> str:
    """Return the model configured for ``role`` (``KAIROS_AI_{ROLE}_MODEL``) or ``default``."""
    return _role_env(role, "MODEL") or default


#: Default sampling seed for every LLM-backed pipeline stage (DD-174).
#:
#: The pipeline's LLM stages are *analysis* steps, not creative ones: the same
#: evidence should produce the same proposal on Tuesday as it did on Monday, or
#: a re-run silently changes the model a human already reviewed.  ``temperature``
#: cannot deliver that on the reasoning tier — those models reject the parameter
#: outright (see ``create_chat_completion``), so the only lever the API offers is
#: a fixed seed.  Measured on this provider: 3/3 byte-identical completions with
#: a seed, 3/3 different without.
#:
#: Seeding is best-effort by design of the underlying APIs: it removes *sampling*
#: noise, not the effect of a changed prompt, a changed model, or a provider-side
#: backend change.  This provider returns no ``system_fingerprint``, so a backend
#: change cannot be detected from the response — which is why the seed is recorded
#: alongside the model in generated-artifact provenance rather than assumed.
DEFAULT_AI_SEED = 20260101


def resolve_ai_seed(role: str | None = None) -> int | None:
    """Return the sampling seed for ``role``.

    Resolution order: ``KAIROS_AI_{ROLE}_SEED`` → ``KAIROS_AI_SEED`` →
    :data:`DEFAULT_AI_SEED`.  Setting either variable to an empty value or to
    ``off`` disables seeding entirely (returns ``None``), which is the escape
    hatch for deliberately sampling variation — e.g. running the same stage
    several times to see how much the model actually disagrees with itself.

    A non-integer value is a configuration error and raises, rather than
    silently falling back to unseeded output that looks stable but is not.
    """
    for name in (f"KAIROS_AI_{role.upper()}_SEED" if role else "", "KAIROS_AI_SEED"):
        if not name:
            continue
        raw = os.environ.get(name)
        if raw is None:
            continue
        value = raw.strip()
        if not value or value.lower() in {"off", "none", "random"}:
            return None
        try:
            return int(value)
        except ValueError:
            raise ValueError(
                f"{name}={value!r} is not an integer. Use an integer seed, "
                f"or 'off' to disable seeding."
            ) from None
    return DEFAULT_AI_SEED


#: Reasoning-effort tiers the provider accepts, cheapest first.
REASONING_EFFORTS = ("minimal", "low", "medium", "high")

#: Default reasoning effort per role (DD-176).
#:
#: Alignment and judgment are closed-vocabulary reasoning over a large
#: candidate set, where a wrong answer is silently wrong, so both get the
#: middle tier rather than the cheapest. Analyse-sources's table-classification
#: call used to run under its own "affinity" role at the cheapest tier
#: (high-volume, one call per table, judged least helped by extended
#: reasoning); issue #562 collapsed that role into alignment, so that call now
#: inherits alignment's tier too — deliberately, not an oversight.
#:
#: These are defaults, not findings: effort trades latency against recall, and
#: recall is the weak axis here (a quarter of source columns map). Change them
#: from measurement, not from intuition.
DEFAULT_REASONING_EFFORT: dict[str, str] = {
    ROLE_ALIGNMENT: "medium",
    ROLE_JUDGMENT: "medium",
}


def resolve_reasoning_effort(role: str | None = None) -> str | None:
    """Return the reasoning effort for ``role``, or ``None`` to leave it to the model.

    Resolution order: ``KAIROS_AI_{ROLE}_REASONING_EFFORT`` →
    ``KAIROS_AI_REASONING_EFFORT`` → the per-role default. ``off`` (or ``default``)
    sends no ``reasoning_effort`` at all, which is also what a non-reasoning model
    needs — though that case is handled anyway, since such a model rejects the
    parameter by name and ``create_chat_completion`` drops it.

    An unrecognised tier raises rather than being passed through, so a typo fails
    at the first call instead of silently reverting to the model's own default.
    """
    for name in (
        f"KAIROS_AI_{role.upper()}_REASONING_EFFORT" if role else "",
        "KAIROS_AI_REASONING_EFFORT",
    ):
        if not name:
            continue
        raw = os.environ.get(name)
        if raw is None:
            continue
        value = raw.strip().lower()
        if not value or value in {"off", "none", "default"}:
            return None
        if value not in REASONING_EFFORTS:
            raise ValueError(
                f"{name}={raw.strip()!r} is not a reasoning effort. "
                f"Use one of {', '.join(REASONING_EFFORTS)}, or 'off'."
            )
        return value
    return DEFAULT_REASONING_EFFORT.get(role or "", None)


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

    When ``role`` is given (``"alignment"`` / ``"judgment"``) and a per-role
    endpoint is configured (``KAIROS_AI_{ROLE}_ENDPOINT``), that OpenAI-compatible
    endpoint wins, letting each role use independent endpoints/models (issue
    #182). Otherwise the global provider is resolved and, if set, the
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
        role_key = _role_env(role, "KEY")
        if not role_key:
            raise Misconfigured(
                f"KAIROS_AI_{role.upper()}_ENDPOINT is set but KAIROS_AI_{role.upper()}_KEY "
                f"is missing. Set the key, or use KAIROS_AI_{role.upper()}_KEY=none "
                f"for a keyless local endpoint (e.g. vLLM/Ollama)."
            )
        api_key = "" if role_key.lower() == "none" else role_key
        return AIProviderConfig(
            provider=f"endpoint:{role}",
            endpoint=role_endpoint,
            api_key=api_key,
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
        raise Misconfigured(
            f"Unknown KAIROS_AI_PROVIDER value: '{explicit_provider}'. "
            f"Supported values: 'github', 'azure', 'foundry'."
        )
    else:
        raise NotConfigured(
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
        raise NotConfigured(
            f"{ENV_GITHUB_TOKEN} environment variable is required for GitHub Models provider. "
            "Set it to a GitHub personal access token with Models API access."
        )
    return AIProviderConfig(
        provider="github",
        endpoint=GITHUB_MODELS_ENDPOINT,
        api_key=token,
        model=model,
    )


def foundry_openai_base_url(endpoint: str) -> str:
    """Derive the OpenAI-compatible base URL from a Foundry endpoint.

    Accepts either shape a user may have configured and normalises both to
    ``https://<resource>.services.ai.azure.com/openai/v1``:

    * the project endpoint the SDK path wants --
      ``https://<resource>.services.ai.azure.com/api/projects/<project>``
    * the bare resource URL -- ``https://<resource>.services.ai.azure.com``

    The project segment is dropped deliberately: it scopes the *projects* API, while an
    API key authenticates the resource-level inference surface.
    """
    base = endpoint.strip().rstrip("/")
    marker = "/api/projects/"
    if marker in base:
        base = base.split(marker, 1)[0]
    if base.endswith("/openai/v1"):
        return base
    return f"{base}/openai/v1"


def _extra_install_hint(extra: str) -> str:
    """Uv-native remediation text for a missing optional-dependency extra (issue #553).

    Every hub this toolkit scaffolds is uv-managed and already declares each
    extra under ``[project.optional-dependencies]``, so ``uv sync --extra
    <name>`` installs it without hand-editing anything. ``pip install
    kairos-ontology-toolkit[...]`` only works when the toolkit itself is
    pip-installed, which no scaffolded hub is.
    """
    return f"uv sync --extra {extra}"


def _resolve_azure(model: str) -> AIProviderConfig:
    """Resolve Azure AI Foundry configuration."""
    endpoint = os.environ.get(ENV_AZURE_ENDPOINT)
    if not endpoint:
        raise NotConfigured(
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
        raise NotConfigured(
            f"Neither {ENV_AZURE_KEY} is set nor azure-identity is installed. "
            f"Install with: {_extra_install_hint('azure')}"
        )
    except Exception as e:
        raise Misconfigured(
            f"Azure managed identity authentication failed: {e}. "
            f"Set {ENV_AZURE_KEY} explicitly or check your Azure identity configuration."
        )


def _resolve_foundry(model: str) -> AIProviderConfig:
    """Resolve Microsoft Foundry configuration using azure-ai-projects SDK."""
    endpoint = os.environ.get(ENV_FOUNDRY_ENDPOINT)
    if not endpoint:
        raise NotConfigured(
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
        role: Optional role (``"alignment"`` / ``"judgment"``) selecting a
            per-role endpoint override when configured (issue #182).

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

    return _create_client_from_config(config)


def _create_client_from_config(config: AIProviderConfig):
    """Create an OpenAI-compatible client from an already-resolved config.

    Shared between :func:`get_ai_client` (normal operation) and the preflight
    probe (issue #463) so the Foundry SDK path is identical in both.
    """
    if config.provider == "foundry":
        return _create_foundry_client(config)

    return _openai_class()(
        base_url=config.endpoint,
        api_key=config.api_key,
    )


def _openai_class():
    """Return the ``OpenAI`` class, Langfuse-instrumented when tracing is on (DD-184).

    Langfuse ships a drop-in replacement that records model, token usage and the
    ``generation`` observation type without the call sites knowing. Preferring it
    over hand-rolled spans is the documented guidance, and it is why nothing in
    ``create_chat_completion`` has to know tracing exists.

    Falls back to the plain client whenever tracing is off or the package is
    missing, so an unconfigured hub is byte-for-byte unchanged.
    """
    from .tracing import get_tracing_client

    if get_tracing_client() is not None:
        try:
            from langfuse.openai import OpenAI as TracedOpenAI

            return TracedOpenAI
        except Exception as exc:  # noqa: BLE001 - tracing must never fail a run
            logger.info("Langfuse OpenAI wrapper unavailable (%s); using plain client.", exc)

    from openai import OpenAI

    return OpenAI


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
        raise NotConfigured(
            "The azure-ai-projects package is required for the Foundry provider. "
            f"Install with: {_extra_install_hint('foundry')}"
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

    def _openai_key_client(cfg):
        # DD-184: via _openai_class so the Foundry key path is instrumented too.
        # This is the path this deployment actually takes, so importing OpenAI
        # directly here silently excluded every real call from tracing.
        return _openai_class()(
            base_url=foundry_openai_base_url(cfg.endpoint), api_key=cfg.api_key
        )

    if config.api_key:
        # Key auth does not go through AIProjectClient at all. That SDK path calls
        # credential.get_token(), which AzureKeyCredential does not implement -- and it
        # does so *lazily*, when the returned client is first used, so the previous
        # AttributeError fallback here never fired: the error surfaced later, at the
        # call site, as an opaque "endpoint unreachable".
        #
        # A Foundry resource serves an OpenAI-compatible surface at
        # <resource>/openai/v1, which is exactly what an API key authenticates against.
        # Talk to it directly.
        return _openai_key_client(config)

    token_credential = _build_token_credential()
    if token_credential is None:
        raise NotConfigured(
            f"Neither {ENV_FOUNDRY_API_KEY} is set nor azure-identity is installed. "
            f"Install with: {_extra_install_hint('foundry')}"
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


#: Per-model request parameters the provider has already rejected this process.
#: Populated only from a provider rejection that named the parameter — never
#: guessed from a model name, so a newly-shipped model is discovered, not assumed.
_UNSUPPORTED_PARAMS_BY_MODEL: dict[str, set[str]] = {}


def reset_unsupported_param_cache() -> None:
    """Forget every remembered per-model parameter rejection (test seam)."""
    _UNSUPPORTED_PARAMS_BY_MODEL.clear()


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
    param_fallbacks: dict[str, Any] | None = None,
    trace_name: str = "",
    trace_metadata: dict[str, Any] | None = None,
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

    A model's rejection is remembered for the rest of the process, so a stage
    that makes one call per source table pays the discovery round-trip once
    instead of once per table.

    ``param_fallbacks`` maps a parameter name to a weaker value to substitute
    when the model rejects it, instead of dropping it outright. A strict
    ``response_format`` schema falls back to plain JSON mode this way: a model
    that cannot honour the schema should still be asked for JSON, rather than
    silently losing the constraint the caller already had.
    """
    # ``None`` means "not configured" for the optional tuning parameters
    # (``seed``, ``reasoning_effort``): the caller resolves them unconditionally
    # and a disabled one must be absent from the request, not sent as null.
    request_kwargs = {k: v for k, v in request_kwargs.items() if v is not None}
    fallbacks = param_fallbacks or {}

    # DD-184: the Langfuse OpenAI wrapper consumes `name`/`metadata` and strips them
    # before the provider call. A plain client would reject them as unknown
    # parameters, so they are attached only when tracing is actually live.
    from .tracing import get_tracing_client

    if get_tracing_client() is not None:
        if trace_name:
            request_kwargs["name"] = trace_name
        if trace_metadata:
            request_kwargs["metadata"] = trace_metadata

    known_unsupported = _UNSUPPORTED_PARAMS_BY_MODEL.get(model, frozenset())
    if known_unsupported:
        request_kwargs = {
            k: (fallbacks[k] if k in fallbacks else v)
            for k, v in request_kwargs.items()
            if k not in known_unsupported or k in fallbacks
        }
    try:
        return client.chat.completions.create(model=model, messages=messages, **request_kwargs)
    except Exception as exc:  # noqa: BLE001 — inspected below, re-raised if not a match
        param = _unsupported_request_param(str(exc))
        if not param or param not in request_kwargs:
            raise
        _UNSUPPORTED_PARAMS_BY_MODEL.setdefault(model, set()).add(param)
        if param in fallbacks:
            logger.info(
                "Model %s rejected request parameter '%s'; retrying with the weaker "
                "fallback value (for the rest of this run).",
                model,
                param,
            )
            retry_kwargs = dict(request_kwargs)
            retry_kwargs[param] = fallbacks[param]
        else:
            logger.info(
                "Model %s rejected request parameter '%s'; retrying once without it "
                "(and omitting it for the rest of this run).",
                model,
                param,
            )
            retry_kwargs = {k: v for k, v in request_kwargs.items() if k != param}
        return client.chat.completions.create(model=model, messages=messages, **retry_kwargs)
