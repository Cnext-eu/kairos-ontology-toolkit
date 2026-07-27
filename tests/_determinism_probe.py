# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Determinism probe for a v5 governed-hub ``CompilePlan``.

Run as a standalone script (see ``tests/test_determinism.py``).  The whole point
is to execute in a *fresh* process so we can vary ``PYTHONHASHSEED`` and prove the
generated artifact map is byte-stable.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from kairos_ontology.core.compiler import build_compile_plan, render_compile_plan

HUB_ROOT = Path(__file__).parent / "scenarios" / "v5-governed-hub"


def build_artifacts() -> dict[str, str]:
    return dict(render_compile_plan(build_compile_plan(HUB_ROOT, "party")))


def artifact_hash(artifacts: dict) -> str:
    canonical = _canonical(artifacts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical(artifacts: dict) -> str:
    import json

    return json.dumps(artifacts, sort_keys=True, ensure_ascii=False, default=str)


if __name__ == "__main__":
    print(artifact_hash(build_artifacts()))
