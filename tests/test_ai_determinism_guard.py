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
    # Issue #562 collapsed the separate "affinity" role into "alignment".
    "analyse_sources.py": "ROLE_ALIGNMENT",
    "conformance_judge.py": "ROLE_JUDGMENT",
    # DD-185: global anchoring reuses the alignment role's model/seed/effort —
    # it is STEP 1 of alignment, extracted to where it can see the whole corpus.
    "anchor_tables.py": "ROLE_ALIGNMENT",
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
def test_stage_sets_reasoning_effort(filename):
    """Effort is a per-role knob, not the model's default (DD-176)."""
    tree = ast.parse((_CORE / filename).read_text(encoding="utf-8"))
    for call in [c for c in _calls(tree) if _is_wrapper_call(c)]:
        effort = next((kw for kw in call.keywords if kw.arg == "reasoning_effort"), None)
        assert effort is not None, (
            f"{filename}:{call.lineno} sends no reasoning_effort. Pass "
            f"resolve_reasoning_effort(role) — it returns None where the tier "
            f"should be left to the model, and None is dropped from the request."
        )
        assert isinstance(effort.value, ast.Call) and getattr(
            effort.value.func, "id", ""
        ) == "resolve_reasoning_effort", (
            f"{filename}:{call.lineno} must resolve effort via "
            f"resolve_reasoning_effort() rather than hard-coding a tier."
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


class TestPromptInputDeterminism:
    """DD-175: a seed cannot stabilise an answer when the question keeps changing."""

    def test_stable_value_prefers_english_then_lexical(self):
        from rdflib import Graph, Literal, RDFS, URIRef

        from kairos_ontology.core.ontology_loader import stable_value

        subj = URIRef("http://example.org/C")
        g = Graph()
        for text, lang in (("zzz", "en"), ("aaa", "de"), ("mmm", None)):
            g.add((subj, RDFS.comment, Literal(text, lang=lang)))
        # English wins even though it sorts last lexically.
        assert str(stable_value(g, subj, RDFS.comment)) == "zzz"

    def test_stable_value_is_order_independent(self):
        """Same triples inserted in any order must yield the same pick."""
        import itertools

        from rdflib import Graph, Literal, RDFS, URIRef

        from kairos_ontology.core.ontology_loader import stable_value

        subj = URIRef("http://example.org/C")
        texts = ["Source: ISO 4217", "Open code list of currency codes", "Restricted list"]
        picks = set()
        for order in itertools.permutations(texts):
            g = Graph()
            for t in order:
                g.add((subj, RDFS.comment, Literal(t)))
            picks.add(str(stable_value(g, subj, RDFS.comment)))
        assert len(picks) == 1, f"pick depends on insertion order: {picks}"

    def test_stable_value_returns_none_when_absent(self):
        from rdflib import Graph, RDFS, URIRef

        from kairos_ontology.core.ontology_loader import stable_value

        assert stable_value(Graph(), URIRef("http://example.org/C"), RDFS.comment) is None

    def test_reference_terms_are_ordered_reproducibly(self):
        """_sorted_terms pins the order the prompt renders."""
        from kairos_ontology.core.propose_alignment import _sorted_terms

        terms = [
            {"name": "beta", "uri": "http://x/b"},
            {"name": "alpha", "uri": "http://x/a2"},
            {"name": "alpha", "uri": "http://x/a1"},
        ]
        names = [(t["name"], t["uri"]) for t in _sorted_terms(terms)]
        assert names == [
            ("alpha", "http://x/a1"),
            ("alpha", "http://x/a2"),
            ("beta", "http://x/b"),
        ]
        # Order of the input must not matter.
        assert _sorted_terms(list(reversed(terms))) == _sorted_terms(terms)

    def test_semantic_index_uses_the_deterministic_picker(self):
        """The canonical loader must not fall back to Graph.value for annotations."""
        import ast
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent / "src" / "kairos_ontology" / "core"
        tree = ast.parse((src / "semantic_index.py").read_text(encoding="utf-8"))

        # OWL restriction structures are functional by OWL semantics, so an
        # arbitrary pick is safe there; annotations are the multi-valued ones.
        annotation_preds = {"label", "comment"}
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute) and fn.attr == "value"):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Attribute) and arg.attr in annotation_preds:
                    offenders.append(node.lineno)
        assert not offenders, (
            f"semantic_index.py lines {offenders} read a multi-valued annotation via "
            f"Graph.value(), which picks arbitrarily. Use stable_value() — see DD-175."
        )
