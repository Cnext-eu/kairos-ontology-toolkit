# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""AI provider preflight checks (DD-159).

Policy/reporting module that inspects AI provider configuration and optionally
probes reachability without importing the OpenAI SDK at module level (so tests
can intercept the probe path).

Public surface:
    - :class:`AIRolePreflight`  — per-role status and remediation.
    - :class:`AIPreflightReport` — aggregate over one or more roles.
    - :func:`preflight_ai_provider` — config + optional probe for one role.
    - :func:`preflight_all_roles`   — convenience over both roles.
    - :func:`require_ai_provider`    — raising wrapper commands call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kairos_ontology.core.ai_provider import (
    AIProviderConfig,
    AIProviderError,
    DEFAULT_MODEL,
    NotConfigured,
    Misconfigured,
    Unreachable,
    ROLE_AFFINITY,
    ROLE_ALIGNMENT,
    resolve_provider_config,
)


# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------

STATUS_OK = "ok"
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_MISCONFIGURED = "misconfigured"
STATUS_UNREACHABLE = "unreachable"
STATUS_UNPROBED = "unprobed"

#: The one-line next command a user should run for a given role.
_REMEDIATION = {
    STATUS_NOT_CONFIGURED: "Set GITHUB_TOKEN, or configure a per-role endpoint "
    "(KAIROS_AI_{{ROLE}}_ENDPOINT + KAIROS_AI_{{ROLE}}_KEY).",
    STATUS_MISCONFIGURED: "Check the endpoint URL and key/credential for the "
    "configured provider, or run: kairos-ontology check-ai-config --role {role}",
    STATUS_UNREACHABLE: "Verify network connectivity and the endpoint URL, or "
    "run: kairos-ontology check-ai-config --role {role} --probe",
}


# ---------------------------------------------------------------------------
# Per-role result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AIRolePreflight:
    """Preflight result for a single AI role."""

    role: str
    status: str
    provider: str = ""
    model: str = ""
    endpoint: str = ""
    error: str = ""
    remediation: str = ""

    @property
    def is_ok(self) -> bool:
        return self.status == STATUS_OK

    @property
    def is_blocking(self) -> bool:
        return self.status in (STATUS_NOT_CONFIGURED, STATUS_MISCONFIGURED, STATUS_UNREACHABLE)

    @property
    def has_warnings(self) -> bool:
        return self.status == STATUS_UNPROBED

    def to_dict(self) -> dict[str, Any]:
        d = {
            "role": self.role,
            "status": self.status,
        }
        if self.provider:
            d["provider"] = self.provider
        if self.model:
            d["model"] = self.model
        if self.endpoint:
            d["endpoint"] = self.endpoint
        if self.error:
            d["error"] = self.error
        if self.remediation:
            d["remediation"] = self.remediation
        # No api_key field — never populated, never echoed.
        return d


# ---------------------------------------------------------------------------
# Aggregate report
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class AIPreflightReport:
    """Aggregate preflight report over one or more roles."""

    roles: tuple[AIRolePreflight, ...] = ()
    schema_version: int = SCHEMA_VERSION

    @property
    def is_blocking(self) -> bool:
        return any(r.is_blocking for r in self.roles)

    @property
    def has_warnings(self) -> bool:
        return any(r.has_warnings for r in self.roles)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "roles": [r.to_dict() for r in self.roles],
            "is_blocking": self.is_blocking,
            "has_warnings": self.has_warnings,
        }


# ---------------------------------------------------------------------------
# Preflight logic
# ---------------------------------------------------------------------------


def _is_not_found(exc: Exception) -> bool:
    """True when *exc* is an HTTP 404, however the provider SDK reports it."""
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status == 404:
        return True
    return type(exc).__name__ in {"NotFoundError", "ResourceNotFoundError"}


def _is_output_limit_reached(exc: Exception) -> bool:
    """True when inference reached the model but exhausted the probe's tiny output budget."""
    body = getattr(exc, "body", None)
    body_message = ""
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict):
            body_message = str(error.get("message", ""))
    message = f"{body_message} {exc}".lower()
    limit_named = "max_tokens" in message or "model output limit" in message
    return limit_named and ("reached" in message or "exceeded" in message)


def _probe_client(config, *, timeout_s: float = 10.0) -> None:
    """Attempt a lightweight reachability probe against the provider endpoint.

    Routes through :func:`_create_client_from_config` so the Foundry provider
    uses the same SDK path as normal operation (issue #463). Imported lazily so
    tests can monkey-patch this function to raise (or no-op).
    Raises :class:`Unreachable` on any failure.

    ``models.list()`` is the cheapest authenticated call and is tried first, but a
    **404 from it proves nothing about inference**. An Azure Foundry project exposes
    its OpenAI-compatible surface under ``/openai/v1/`` and need not implement a
    ``GET /models`` listing at all, so a perfectly working endpoint answers 404 there.
    Treating that as "unreachable" is a false negative with real cost: it is the
    reported cause of AP-002/AP-030 on the CLdN hub, where both roles were declared
    unusable for an entire run and a 174-concept judgement pass was done by hand
    against a provider that was, as far as this probe can show, fine.

    So a 404 falls through to a minimal inference call — the capability actually being
    checked. Anything else, including a 401/403, still fails immediately: those are
    real answers from a reachable endpoint about a configuration problem.
    """
    from kairos_ontology.core.ai_provider import _create_client_from_config

    try:
        client = _create_client_from_config(config)
    except Exception as exc:
        raise Unreachable(
            f"Provider endpoint '{config.endpoint}' is unreachable: {type(exc).__name__}: {exc}"
        ) from exc

    try:
        client.models.list()
        return
    except Exception as exc:
        if not _is_not_found(exc):
            raise Unreachable(
                f"Provider endpoint '{config.endpoint}' is unreachable: {type(exc).__name__}: {exc}"
            ) from exc
        listing_error = exc

    try:
        client.chat.completions.create(
            model=config.model,
            messages=[{"role": "user", "content": "ping"}],
            max_completion_tokens=1,
        )
    except Exception as exc:
        if _is_output_limit_reached(exc):
            return
        raise Unreachable(
            f"Provider endpoint '{config.endpoint}' did not answer a model listing "
            f"({type(listing_error).__name__}: 404) and a minimal inference call to "
            f"model '{config.model}' also failed: {type(exc).__name__}: {exc}. "
            "A 404 on both usually means the deployment name is wrong rather than the "
            "endpoint — check the model is deployed under exactly this name."
        ) from exc


def preflight_ai_provider(
    role: str,
    *,
    model: str | None = None,
    probe: bool = False,
    timeout_s: float = 10.0,
) -> AIRolePreflight:
    """Preflight-check one AI role's configuration and (optionally) reachability.

    Never raises for config reasons — returns a status instead.
    Only :func:`require_ai_provider` raises.
    """
    effective_model = model or DEFAULT_MODEL
    try:
        config = resolve_provider_config(effective_model, role=role)
    except NotConfigured as exc:
        return AIRolePreflight(
            role=role,
            status=STATUS_NOT_CONFIGURED,
            error=str(exc),
            remediation=_REMEDIATION[STATUS_NOT_CONFIGURED].format(role=role),
        )
    except Misconfigured as exc:
        return AIRolePreflight(
            role=role,
            status=STATUS_MISCONFIGURED,
            error=str(exc),
            remediation=_REMEDIATION[STATUS_MISCONFIGURED].format(role=role),
        )
    except AIProviderError as exc:
        return AIRolePreflight(
            role=role,
            status=STATUS_MISCONFIGURED,
            error=str(exc),
            remediation=_REMEDIATION[STATUS_MISCONFIGURED].format(role=role),
        )

    if not probe:
        return AIRolePreflight(
            role=role,
            status=STATUS_UNPROBED,
            provider=config.provider,
            model=config.model,
            endpoint=_safe_endpoint(config.endpoint),
        )

    try:
        _probe_client(config, timeout_s=timeout_s)
    except Unreachable as exc:
        return AIRolePreflight(
            role=role,
            status=STATUS_UNREACHABLE,
            provider=config.provider,
            model=config.model,
            endpoint=_safe_endpoint(config.endpoint),
            error=str(exc),
            remediation=_REMEDIATION[STATUS_UNREACHABLE].format(role=role),
        )

    return AIRolePreflight(
        role=role,
        status=STATUS_OK,
        provider=config.provider,
        model=config.model,
        endpoint=_safe_endpoint(config.endpoint),
    )


def preflight_all_roles(
    *,
    roles: tuple[str, ...] = (ROLE_AFFINITY, ROLE_ALIGNMENT),
    model: str | None = None,
    probe: bool = False,
    timeout_s: float = 10.0,
) -> AIPreflightReport:
    """Preflight-check all configured roles and return an aggregate report."""
    results = tuple(
        preflight_ai_provider(role, model=model, probe=probe, timeout_s=timeout_s) for role in roles
    )
    return AIPreflightReport(roles=results)


def require_ai_provider(
    role: str,
    *,
    model: str | None = None,
    probe: bool = False,
) -> AIProviderConfig:
    """Raise :class:`AIProviderError` if the role is not usable; return config if it is.

    The one-line raising wrapper commands call before entering a judgment loop.
    Returns the resolved provider config so callers don't need a separate
    ``resolve_provider_config`` call (which would hit the env a second time).
    """
    result = preflight_ai_provider(role, model=model, probe=probe)
    if result.is_blocking:
        msg = result.error or f"AI provider for role '{role}' is {result.status}"
        # Map status back to the right exception subclass.
        if result.status == STATUS_NOT_CONFIGURED:
            raise NotConfigured(msg)
        elif result.status == STATUS_MISCONFIGURED:
            raise Misconfigured(msg)
        elif result.status == STATUS_UNREACHABLE:
            raise Unreachable(msg)
        raise AIProviderError(msg)
    return resolve_provider_config(model or DEFAULT_MODEL, role=role)


def _safe_endpoint(endpoint: str) -> str:
    """Return a non-sensitive endpoint representation (host only)."""
    from urllib.parse import urlsplit

    parsed = urlsplit(endpoint)
    if not parsed.scheme or not parsed.hostname:
        return "<redacted>"
    if parsed.port:
        return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    return f"{parsed.scheme}://{parsed.hostname}"
