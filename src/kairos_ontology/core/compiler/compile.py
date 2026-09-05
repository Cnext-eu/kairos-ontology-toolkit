# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Stateless orchestration for the v5 ``compile`` command (DD-133).

Exactly one mode runs per invocation: ``check`` (diagnostics only), ``explain`` (structured
plan, no writes), or ``emit`` (atomic artifact emission). The full orchestration — scope
resolution, binding adapter, safety kernel, dbt-phase reuse, and atomic emission — is
implemented in the ``v5-compiler-kernel``, ``v5-emit-contract``, and ``v5-compile-cli``
phases. This module fixes the closed mode surface now.
"""

from __future__ import annotations

from enum import Enum


class CompileMode(str, Enum):
    """The three mutually exclusive ``compile`` modes."""

    CHECK = "check"
    EXPLAIN = "explain"
    EMIT = "emit"
