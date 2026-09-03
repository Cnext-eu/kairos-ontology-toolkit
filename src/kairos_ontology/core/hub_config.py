# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""One reader for the hub's ``kairos.yaml`` (DD-215).

Seven call sites each did their own ``yaml.safe_load`` plus ``isinstance(dict)`` dance,
which is how ``adapter`` came to be validated against a different literal set in each of
them. This module is the single parse.

It deliberately does **not** impose one failure policy. The existing policies differ on
purpose -- the compile kernel fails closed because an unknown adapter must never produce
artifacts, while :func:`kairos_ontology.core.validator` documents that a malformed
``kairos.yaml`` must not break ontology validation, which has nothing to do with the
config. Flattening those into one rule would be a behaviour change disguised as a
refactor, so ``strict`` is the caller's decision.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .adapters import UnsupportedAdapterError, resolve_adapter

#: The hub-wide configuration file, relative to the hub root.
CONFIG_FILENAME = "kairos.yaml"


class HubConfigError(ValueError):
    """Raised by :func:`load_hub_config` in strict mode when the file cannot be used."""


def config_path(hub_root: Path) -> Path:
    return Path(hub_root) / CONFIG_FILENAME


def load_hub_config(hub_root: Path, *, strict: bool = False) -> dict[str, Any]:
    """Parse ``kairos.yaml`` into a mapping.

    With ``strict=False`` (the default) a missing, unreadable, malformed, or non-mapping
    file yields ``{}`` -- for callers reading an optional setting, where absence and
    garbage are equally "not configured". With ``strict=True`` each of those raises
    :class:`HubConfigError`, for callers that must not proceed on a guess.
    """
    path = config_path(hub_root)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        if strict:
            raise HubConfigError(f"{path} could not be read: {exc}") from exc
        return {}
    if raw is None:
        if strict:
            raise HubConfigError(f"{path} is empty")
        return {}
    if not isinstance(raw, dict):
        if strict:
            raise HubConfigError(f"{path} must contain a mapping, not {type(raw).__name__}")
        return {}
    return raw


def configured_adapter(hub_root: Path) -> str | None:
    """Return the hub's canonical adapter id, or ``None`` when absent or unsupported.

    Deprecated spellings resolve; see :func:`kairos_ontology.core.adapters.resolve_adapter`.
    Callers that need to *report* why an adapter was rejected should resolve it themselves
    so they can surface the reason -- this accessor deliberately collapses every failure
    into ``None`` for the read-only status paths that only need to know whether one is set.
    """
    value = load_hub_config(hub_root).get("adapter")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        canonical, _ = resolve_adapter(value)
    except UnsupportedAdapterError:
        return None
    return canonical
