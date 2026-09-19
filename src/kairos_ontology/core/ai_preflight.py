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
    - :func:`preflight_all_roles`   — convenience over the configured pre-modeling role(s).
    - :func:`require_ai_provider`    — raising wrapper commands call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from kairos_ontology.core.ai_provider import (
    AIProviderConfig,
    AIProviderError,
    DEFAULT_MODEL,
    NotConfigured,
    Misconfigured,
    Unreachable,
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
#: A required SDK package is missing (issue #553) -- distinct from
#: STATUS_NOT_CONFIGURED (no env vars set) and STATUS_UNREACHABLE (a reachable
#: endpoint that failed for a network/auth reason). Before this status existed,
#: _probe_client caught the NotConfigured a missing package raises under a
#: generic except Exception and rewrapped it as Unreachable, so a missing
#: dependency was reported with "verify network connectivity" -- the real,
#: actionable "uv sync --extra <name>" hint only survived buried in the
#: wrapped error text.
STATUS_MISSING_DEPENDENCY = "missing_dependency"
STATUS_UNPROBED = "unprobed"

#: The one-line next command a user should run for a given role.
_REMEDIATION = {
    STATUS_NOT_CONFIGURED: "Set GITHUB_TOKEN, or configure a per-role endpoint "
    "(KAIROS_AI_{{ROLE}}_ENDPOINT + KAIROS_AI_{{ROLE}}_KEY).",
    STATUS_MISCONFIGURED: "Check the endpoint URL and key/credential for the "
    "configured provider, or run: kairos-ontology check-ai-config --role {role}",
    STATUS_UNREACHABLE: "Verify network connectivity and the endpoint URL, or "
    "run: kairos-ontology check-ai-config --role {role} --probe",
    # STATUS_MISSING_DEPENDENCY has no template here: the raised exception's own
    # message already IS the actionable line (e.g. "...Install with: uv sync
    # --extra foundry"), so preflight_ai_provider uses it directly instead.
}


# ---------------------------------------------------------------------------
# Per-role result
# ---------------------------------------------------------------------------


#: Model families that reason before answering. Matched on the numeric part rather than a
#: fixed list, so a future `gpt-5.6` is recognised without an edit here.
_REASONING_MODEL_RE = re.compile(r"gpt-(\d+)\.(\d+)", re.IGNORECASE)

#: The model tier `--high-accuracy` selects for alignment. Mirrors
#: `propose_alignment.HIGH_ACCURACY_MODEL`, which cannot be imported here: that module
#: imports this package's provider layer, and a module-scope import would cycle. Pinned
#: by test instead.
HIGH_ACCURACY_MODEL = "gpt-5.4"

#: The tier each role's own documentation asks for, and why. Alignment is deterministic
#: closed-vocabulary matching, so a reasoning model adds latency and cost without benefit
#: -- `.env.example` and `HIGH_ACCURACY_MODEL` both say so, and nothing surfaced it when an
#: operator configured otherwise (#545).
_PREFERRED_TIER: dict[str, tuple[str, str]] = {
    ROLE_ALIGNMENT: (
        "non-reasoning",
        "alignment is deterministic closed-vocabulary matching, so a reasoning model "
        "adds latency and cost without benefit",
    ),
}


def _is_reasoning_model(model: str) -> bool:
    """Whether *model* is a reasoning-tier model (gpt-5.5 and above)."""
    match = _REASONING_MODEL_RE.search(model or "")
    if match is None:
        return False
    return (int(match.group(1)), int(match.group(2))) >= (5, 5)


def tier_advisory(role: str, model: str) -> str:
    """Return a note when *model* is the wrong tier for *role*, else "".

    The mismatch this catches is quiet and expensive to diagnose: an operator set
    `KAIROS_AI_ALIGNMENT_MODEL=gpt-5.5`, `check-ai-config` reported `ok` with no caveat,
    and the artifact then recorded `model_used: gpt-5.4` -- which reads as a silent
    downgrade to a weaker model. It was not: `--high-accuracy` selects the tier this role
    prefers, and the configured value was the one at odds with the toolkit's own advice.
    Reconstructing that took reading `ai_provider.py` (#545).

    DD-159 wants this caught at pre-flight, which is where this runs.
    """
    preferred = _PREFERRED_TIER.get(role)
    if preferred is None or not model:
        return ""
    tier, reason = preferred
    if tier == "non-reasoning" and _is_reasoning_model(model):
        return (
            f"this role prefers a {tier} model ({HIGH_ACCURACY_MODEL}) -- {reason}. "
            f"`--high-accuracy` will use {HIGH_ACCURACY_MODEL} regardless, so an artifact "
            f"recording it is the preferred tier being applied, not a downgrade."
        )
    return ""


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
    #: Non-blocking note about model *tier* fit for this role (#545). Empty when the
    #: configured model is the tier the role asks for.
    advisory: str = ""

    @property
    def is_ok(self) -> bool:
        return self.status == STATUS_OK

    @property
    def is_blocking(self) -> bool:
        return self.status in (
            STATUS_NOT_CONFIGURED,
            STATUS_MISCONFIGURED,
            STATUS_UNREACHABLE,
            STATUS_MISSING_DEPENDENCY,
        )

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
        if self.advisory:
            d["advisory"] = self.advisory
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
    except NotConfigured:
        # A missing SDK package (issue #553) is not an unreachable endpoint --
        # let it propagate with its own actionable message intact rather than
        # rewrapping it under the generic "verify network connectivity" text.
        raise
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
    except NotConfigured as exc:
        # remediation == error deliberately: the exception message already IS
        # the actionable line (e.g. "...Install with: uv sync --extra foundry"),
        # so there is nothing a template would add.
        return AIRolePreflight(
            role=role,
            status=STATUS_MISSING_DEPENDENCY,
            provider=config.provider,
            model=config.model,
            endpoint=_safe_endpoint(config.endpoint),
            error=str(exc),
            remediation=str(exc),
        )
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
        # Reachable and authenticated is not the same as well chosen (#545).
        advisory=tier_advisory(role, config.model),
    )


def preflight_all_roles(
    *,
    roles: tuple[str, ...] = (ROLE_ALIGNMENT,),
    model: str | None = None,
    probe: bool = False,
    timeout_s: float = 10.0,
) -> AIPreflightReport:
    """Preflight-check all configured roles and return an aggregate report.

    Default is the single pre-modeling role left after issue #562 collapsed
    the separate ``affinity`` role into ``alignment``.
    """
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
