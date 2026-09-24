# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""One YAML loader for hot paths: libyaml's C loader when available (#943, #968).

``yaml.safe_load`` is the pure-Python implementation. On a real hub a 0.99 MB ledger took
0.88 s with it and 0.09 s with ``CSafeLoader``, for the same value, and ``compile --all``
spent 47% of its time in it. Both loaders are safe loaders; the C one is chosen only
when PyYAML was built with libyaml.
"""

from __future__ import annotations

from typing import IO, Any

import yaml

_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def safe_load(stream: str | bytes | IO[str] | IO[bytes]) -> Any:
    """``yaml.safe_load``, using the C safe loader when PyYAML has it."""
    return yaml.load(stream, Loader=_LOADER)  # noqa: S506 - a SafeLoader either way
