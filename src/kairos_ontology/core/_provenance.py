# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Provenance comment headers for toolkit-generated Turtle (DD-072).

When the toolkit deterministically writes a ``.ttl`` artifact (source vocabulary,
SKOS glossary, scaffold starter ontology) the file carries no trace of what
produced it.  This module emits a small, non-intrusive **Turtle comment header**
stamping the toolkit version, a UTC generation timestamp, the generator name and a
short edit-policy note.

The header is plain ``#`` comments prepended to the serialized Turtle: it adds no
RDF triples, so it never affects parsing, SHACL validation or projection logic
(``rdflib`` simply ignores comments when it re-parses a file).

The same helper is exposed so hand-authored ontology/SHACL files (written by the
design skills) can adopt the identical convention.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Marker that delimits a toolkit-managed provenance block.  ``prepend_provenance``
# uses it to strip a previous header before stamping a fresh one, so regenerating a
# file never stacks multiple headers.
_MARKER = "kairos-ontology-toolkit"
_RULE = "# " + "-" * 70

_EDIT_NOTE_GENERATED = "Do not edit by hand — regenerate via the CLI/skill."
_EDIT_NOTE_EDITABLE = "Scaffolded starting point — safe to edit and extend."

#: Disclaimer stamped on any artifact whose content an LLM proposed (DD-178).
#:
#: Deliberately about *provenance and review status*, not about liability: the
#: reader needs to know which statements were machine-proposed and that a human
#: has not necessarily confirmed them. An ontology reads as authoritative — that
#: is the point of one — so an artifact that is partly a model's suggestion has
#: to say so on its face, where anyone opening the file will see it, rather than
#: only in a run log nobody keeps.
_AI_DISCLAIMER_LINES = (
    "AI-ASSISTED: content below was proposed by the language model named above,",
    "from source evidence, and is a proposal for human review — not a verified",
    "statement of fact. Record acceptance in the decision log.",
)


def ai_attribution(
    *,
    model: str,
    role: str = "",
    seed: int | None = None,
    reasoning_effort: str | None = None,
    provider: str = "",
) -> dict[str, str]:
    """Build the ``extra`` lines identifying the model behind a generated artifact.

    Records what would be needed to re-run the generation and get a comparable
    answer: the model, the pipeline role it played, and the sampling settings.
    Seeding is best-effort at this size (DD-177), so these are an audit trail of
    what was *asked for*, not a promise the output can be reproduced byte for byte.

    Empty and ``None`` values are omitted, so an artifact generated without a
    seed does not claim one.
    """
    fields = {
        "AI model": model,
        "AI role": role,
        "AI provider": provider,
        "AI seed": str(seed) if seed is not None else "",
        "AI effort": reasoning_effort or "",
    }
    return {k: v for k, v in fields.items() if v}


def ai_attribution_note(role: str) -> str:
    """One-line AI attribution for a Markdown artifact (DD-178).

    The comment-block form suits a Turtle or YAML file; a report needs a
    sentence a reader will actually read, above the numbers it qualifies.
    Resolves the live configuration for *role* rather than taking it as an
    argument, so a report cannot claim a model the run did not use.
    """
    from .ai_provider import resolve_ai_seed, resolve_reasoning_effort, resolve_role_model

    parts = [f"model `{resolve_role_model(role)}`"]
    effort = resolve_reasoning_effort(role)
    if effort:
        parts.append(f"reasoning effort `{effort}`")
    seed = resolve_ai_seed(role)
    if seed is not None:
        parts.append(f"seed `{seed}`")
    return (
        f"**AI-assisted:** figures below count mappings proposed by {', '.join(parts)}. "
        f"They are proposals for human review, not verified statements of fact."
    )


def _toolkit_version() -> str:
    """Return the running toolkit version (lazy import avoids a cycle)."""
    try:
        from kairos_ontology import __version__

        return __version__
    except Exception:  # pragma: no cover - defensive only
        return "unknown"


def provenance_comment(
    generator: str,
    *,
    generated_at: datetime | None = None,
    editable: bool = False,
    extra: dict[str, str] | None = None,
    ai_generated: bool = False,
) -> str:
    """Build a Turtle ``#``-comment provenance header.

    Args:
        generator: Short name of the producer (e.g. ``"build-glossary"``).
        generated_at: Generation time; defaults to ``datetime.now(timezone.utc)``.
            Inject a fixed value in tests for deterministic output.
        editable: ``True`` stamps a "safe to edit" note (scaffold starters);
            ``False`` (default) stamps a "do not edit — regenerate" note.
        extra: Optional ordered ``label -> value`` lines rendered after the header.
            Pass :func:`ai_attribution` here for a model-generated artifact.
        ai_generated: Stamp the AI-assistance disclaimer (DD-178). Set this
            whenever a language model proposed any of the content, so the
            artifact carries its own review status.

    Returns:
        The comment block as a string ending with a trailing newline.
    """
    ts = generated_at or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts = ts.astimezone(timezone.utc)
    stamp = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    note = _EDIT_NOTE_EDITABLE if editable else _EDIT_NOTE_GENERATED

    lines = [
        _RULE,
        f"# Generated by {_MARKER} v{_toolkit_version()}",
        f"# Generator : {generator}",
        f"# Generated : {stamp} (UTC)",
    ]
    for label, value in (extra or {}).items():
        lines.append(f"# {label} : {value}")
    if ai_generated:
        # Wrapped by hand rather than by textwrap: the width must stay stable so
        # a regenerated artifact does not produce a spurious diff.
        lines.append("#")
        for chunk in _AI_DISCLAIMER_LINES:
            lines.append(f"# {chunk}")
        lines.append("#")
    lines.append(f"# {note}")
    lines.append(_RULE)
    return "\n".join(lines) + "\n"


def strip_provenance(ttl: str) -> str:
    """Remove a leading toolkit provenance header from *ttl*, if present.

    Only strips a block at the very top of the document delimited by the rule
    lines and containing the toolkit marker, so user comments are never touched.
    """
    lines = ttl.splitlines()
    if not lines or lines[0].strip() != _RULE:
        return ttl
    # Find the closing rule line of the header block.
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _RULE:
            block = "\n".join(lines[: idx + 1])
            if _MARKER not in block:
                return ttl  # not our header — leave it alone
            rest = lines[idx + 1 :]
            # Drop a single blank separator line if present.
            if rest and rest[0].strip() == "":
                rest = rest[1:]
            return "\n".join(rest) + ("\n" if ttl.endswith("\n") else "")
    return ttl


def prepend_provenance(
    ttl: str,
    generator: str,
    *,
    generated_at: datetime | None = None,
    editable: bool = False,
    extra: dict[str, str] | None = None,
    ai_generated: bool = False,
) -> str:
    """Return *ttl* with a fresh provenance header prepended.

    Idempotent: any existing toolkit header at the top of *ttl* is stripped first,
    so regenerating a file never stacks multiple headers.
    """
    header = provenance_comment(
        generator,
        generated_at=generated_at,
        editable=editable,
        extra=extra,
        ai_generated=ai_generated,
    )
    body = strip_provenance(ttl).lstrip("\n")
    return f"{header}\n{body}"
