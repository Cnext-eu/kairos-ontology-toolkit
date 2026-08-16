# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Guard: every LLM-backed pipeline stage is seeded and capability-aware (DD-174).

Two defects motivate this file, both found by measurement rather than review:

1. ``temperature=0.1`` was passed to the alignment stage for its whole life and
   had *never* taken effect — the reasoning-tier models reject the parameter
   outright, and the provider wrapper silently retried without it.  Measured
   run-to-run variation on one domain was 21-26 columns mapped from identical
   input.  ``seed`` is the only variance lever those models accept.

2. The affinity and judgment stages called ``client.chat.completions.create``
   directly, bypassing the capability-aware wrapper.  They worked only because
   they happened to be pointed at a model that tolerates ``temperature``;
   repointing either at a reasoning model would have been a hard 400.

Both are the kind of defect that reads as correct in review, so they are pinned
here at the source level: a new stage that forgets either one fails this file.
"""

import ast
from pathlib import Path

import pytest


_CORE = Path(__file__).resolve().parent.parent / "src" / "kairos_ontology" / "core"

#: Modules that make a completion call as part of the generation pipeline, and
#: the seed role each must use.  Extend this when a stage is added.
_SEEDED_STAGES = {
    "propose_alignment.py": "ROLE_ALIGNMENT",
    "analyse_sources.py": "ROLE_AFFINITY",
    "conformance_judge.py": "ROLE_JUDGMENT",
}

#: ``ai_preflight`` deliberately calls the client directly: it is the liveness
#: probe that runs *before* any capability is known, so it must not depend on
#: the wrapper's retry behaviour to decide whether a provider is reachable.
_DIRECT_CALL_ALLOWED = {"ai_preflight.py", "ai_provider.py"}


def _calls(tree: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


def _is_direct_completion_call(node: ast.Call) -> bool:
    """Match ``<anything>.chat.completions.create(...)``."""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "create":
        return False
    completions = func.value
    if not isinstance(completions, ast.Attribute) or completions.attr != "completions":
        return False
    chat = completions.value
    return isinstance(chat, ast.Attribute) and chat.attr == "chat"


def _is_wrapper_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Name) and node.func.id == "create_chat_completion"


@pytest.mark.parametrize("filename", sorted(_SEEDED_STAGES))
def test_stage_passes_a_seed(filename):
    """Every completion call in a pipeline stage passes ``seed=resolve_ai_seed(...)``."""
    tree = ast.parse((_CORE / filename).read_text(encoding="utf-8"))
    completion_calls = [c for c in _calls(tree) if _is_wrapper_call(c)]
    assert completion_calls, f"{filename} makes no completion call — update this guard"

    for call in completion_calls:
        seed = next((kw for kw in call.keywords if kw.arg == "seed"), None)
        assert seed is not None, (
            f"{filename}:{call.lineno} calls the model without a seed. "
            f"Unseeded output varies run-to-run; see DD-174."
        )
        assert isinstance(seed.value, ast.Call) and getattr(
            seed.value.func, "id", ""
        ) == "resolve_ai_seed", (
            f"{filename}:{call.lineno} must seed via resolve_ai_seed(), so the "
            f"KAIROS_AI_SEED override and the 'off' escape hatch both apply."
        )


@pytest.mark.parametrize("filename", sorted(_SEEDED_STAGES))
def test_stage_uses_the_capability_aware_wrapper(filename):
    """No stage calls the client directly — the reasoning tier rejects parameters."""
    tree = ast.parse((_CORE / filename).read_text(encoding="utf-8"))
    direct = [c for c in _calls(tree) if _is_direct_completion_call(c)]
    assert not direct, (
        f"{filename}:{direct[0].lineno if direct else '?'} calls "
        f"chat.completions.create directly. Use create_chat_completion() so a "
        f"model that rejects a parameter degrades instead of failing."
    )


def test_no_other_core_module_bypasses_the_wrapper():
    """Catch a *new* module that starts calling the client directly."""
    offenders = []
    for path in sorted(_CORE.rglob("*.py")):
        if path.name in _DIRECT_CALL_ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(_is_direct_completion_call(c) for c in _calls(tree)):
            offenders.append(path.name)
    assert not offenders, (
        f"These modules bypass create_chat_completion: {offenders}. "
        f"Either route them through it or add them to _DIRECT_CALL_ALLOWED "
        f"with a reason."
    )
