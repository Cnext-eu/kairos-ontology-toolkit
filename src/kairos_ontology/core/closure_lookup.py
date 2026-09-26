# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic lookup of a source column name in an ontology's import closure (DD-248).

The aligner shows a language model a bounded slice of each reference class, and
``draft-gap-decisions`` shows it none at all, so a column whose property sits past the cut
was labelled "no reference property" and drafted as a hub-local extension (#1051). On a
15-domain hub that produced 204 proposed extensions, of which a lexical check found 50-80
already had a home in the closure.

This module is that check, made one thing every consumer shares: the alignment pass, the
gap sheet, ``validate``'s integrity audit, ``scaffold-extensions``, ``find-term`` and the
MCP tool. It is pure: no RDF parse, no model call, stdlib only. A match here is a
*candidate*, never a verdict -- ``PI_TYPE`` must not become ``typeCode`` -- so the rules
are conservative and the output is ordered so a run is reproducible.

Match rules:

- **exact**: the normalised column name (or label) equals the property's normalised name
  or label. Score 1.0.
- **near**: after dropping structural tokens (``has``, ``of`` ...), one token set is a
  subset of the other with at most two extra tokens on the longer side --
  ``documentTypeCode`` and ``documentType``, ``estimatedDepartureDateTime`` and
  ``estimatedDeparture``. The score is the string similarity, reported for ranking and
  never used as the gate: bare similarity alone accepts ``eventReference`` for
  ``agentReference``.
- **generic guard**: a name made only of generic tokens (``code``, ``typeCode``,
  ``statusCode`` ...) on either side matches exactly or not at all.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping

__all__ = [
    "ABBREVIATIONS",
    "GENERIC_NAMES",
    "STOP_TOKENS",
    "ClosureCandidate",
    "ClosureTermIndex",
    "PropertyTerm",
    "find_candidates",
    "infer_column_prefix",
    "name_tokens",
    "normalise_term",
    "terms_from_index",
    "terms_from_ref_classes",
]

#: Tokens that name a shape, not a concept. A name made only of these (``CODE``,
#: ``typeCode``) matches exactly and nothing else: ``PI_TYPE`` never reaches ``typeCode``,
#: and ``shipmentTypeCode`` never reaches it either.
GENERIC_NAMES: frozenset[str] = frozenset(
    {
        "code", "type", "name", "id", "value", "status", "date", "time", "description",
        "number", "key", "flag", "text", "amount", "count", "reference", "identifier",
        "indicator", "note", "comment",
    }
)

#: Structural tokens a property name carries that a column name never does.
STOP_TOKENS: frozenset[str] = frozenset({"has", "contains", "is", "of", "in", "at", "and", "the"})

#: Source-schema abbreviations expanded before comparison. Kept short and unambiguous:
#: an expansion that is sometimes wrong (``no`` as ``number`` inside ``NOT_VALID``) is
#: applied only to a whole token, never inside one.
ABBREVIATIONS: Mapping[str, str] = {
    "nbr": "number", "no": "number", "num": "number", "ref": "reference", "qty": "quantity",
    "amt": "amount", "desc": "description", "dt": "date", "cd": "code", "nm": "name",
    "addr": "address", "ctry": "country", "curr": "currency", "pct": "percent",
}

#: Most extra tokens the longer side of a near match may carry.
MAX_EXTRA_TOKENS = 2

DEFAULT_LIMIT = 5

# The column-name tokeniser ``draft-gap-decisions`` uses to form families, moved here so
# the lookup and the sheet split a name the same way (``gap_decisions`` imports it back).
_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")
#: A lower-to-upper step, or the last capital of an acronym run before a capitalised word:
#: ``ETLLoadDate`` splits to ``ETL``, ``Load``, ``Date`` rather than ``ETLLoad``, ``Date``,
#: which no vocabulary can match.
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
#: The index of a numbered repeating group, where nothing separates it from the stem:
#: ``EQUIPMENTTYPE14`` is ``equipmenttype`` + ``14``. Only a digit run at the END of a
#: segment counts, and it must follow at least four letters, so ``ISO6346`` and ``A1``
#: keep their shape (#882).
_TRAILING_INDEX_RE = re.compile(r"(?<=[A-Za-z]{4})(?=\d+(?:\s|$))")
_PREFIX_RE = re.compile(r"^([A-Z][A-Z0-9]{1,3}_)")


def name_tokens(text: str) -> list[str]:
    """Lower-case tokens of an identifier: separators, camel steps and trailing indexes."""
    split = _CAMEL_BOUNDARY_RE.sub(" ", _SPLIT_RE.sub(" ", str(text or "")))
    return _TRAILING_INDEX_RE.sub(" ", split).lower().split()


def normalise_term(text: str, *, strip_prefixes: Iterable[str] = ()) -> str:
    """``"XX_CONTRACT_NBR"`` -> ``"contract number"``; ``"contractNumber"`` -> the same."""
    raw = str(text or "")
    for prefix in strip_prefixes:
        if prefix and len(raw) > len(prefix) and raw.upper().startswith(prefix.upper()):
            raw = raw[len(prefix):]
            break
    return " ".join(ABBREVIATIONS.get(token, token) for token in name_tokens(raw))


def infer_column_prefix(column_names: Iterable[str], *, min_share: float = 0.8) -> str:
    """The one vendor prefix (``XX_``) most of a schema's columns share, or ``""``.

    Deterministic and vendor-agnostic: a prefix counts only when at least *min_share* of
    the names carry it, so ``PO_NUMBER`` in a schema of plain names strips nothing.
    """
    names = [str(n) for n in column_names if n]
    if not names:
        return ""
    counts = Counter(m.group(1) for n in names if (m := _PREFIX_RE.match(n)))
    if not counts:
        return ""
    prefix, share = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
    return prefix if share / len(names) >= min_share else ""


@dataclass(frozen=True, slots=True)
class PropertyTerm:
    """One closure property as the matcher sees it."""

    uri: str
    name: str
    label: str
    class_uris: tuple[str, ...]
    kind: str
    norm_name: str
    norm_label: str


@dataclass(frozen=True, slots=True)
class ClosureTermIndex:
    """Every property of one closure, indexed once so a lookup never re-normalises."""

    terms: tuple[PropertyTerm, ...]
    by_norm: Mapping[str, tuple[int, ...]]
    by_token: Mapping[str, tuple[int, ...]]

    def __len__(self) -> int:
        return len(self.terms)


@dataclass(frozen=True, slots=True)
class ClosureCandidate:
    """A closure property whose name resembles a column name."""

    uri: str
    name: str
    class_uris: tuple[str, ...]
    score: float
    match: str  # "exact" | "near"

    def to_entry(self) -> dict[str, Any]:
        """The YAML shape carried on an alignment custom column and a gap-sheet entry."""
        return {
            "uri": self.uri,
            "name": self.name,
            "class": _local(self.class_uris[0]) if self.class_uris else "",
            "score": round(self.score, 2),
            "match": self.match,
        }


def _build(rows: Iterable[tuple[str, str, str, Iterable[str], str]]) -> ClosureTermIndex:
    """Index ``(uri, name, label, class_uris, kind)`` rows, merging duplicates by uri."""
    merged: dict[str, tuple[str, str, set[str], str]] = {}
    for uri, name, label, class_uris, kind in rows:
        key = uri or name
        if not key:
            continue
        current = merged.get(key)
        if current is None:
            merged[key] = (name, label, set(class_uris), kind)
        else:
            current[2].update(class_uris)
            if not current[1] and label:
                merged[key] = (current[0], label, current[2], current[3] or kind)
    terms = tuple(
        sorted(
            (
                PropertyTerm(
                    uri=key,
                    name=name,
                    label=label,
                    class_uris=tuple(sorted(class_uris)),
                    kind=kind,
                    norm_name=normalise_term(name),
                    norm_label=normalise_term(label),
                )
                for key, (name, label, class_uris, kind) in merged.items()
            ),
            key=lambda t: (t.norm_name, t.uri),
        )
    )
    by_norm: dict[str, list[int]] = {}
    by_token: dict[str, list[int]] = {}
    for position, term in enumerate(terms):
        for norm in {term.norm_name, term.norm_label} - {""}:
            by_norm.setdefault(norm, []).append(position)
            for token in _content_tokens(norm):
                by_token.setdefault(token, []).append(position)
    return ClosureTermIndex(
        terms=terms,
        by_norm={k: tuple(v) for k, v in by_norm.items()},
        by_token={k: tuple(v) for k, v in by_token.items()},
    )


def terms_from_ref_classes(ref_classes: Iterable[Mapping[str, Any]]) -> ClosureTermIndex:
    """Index the dict pool :func:`~.propose_alignment.extract_ref_model_inventory` builds.

    A property inherited by several classes is one term owning all of them.
    """

    def rows():
        for cls in ref_classes:
            owner = str(cls.get("uri") or cls.get("name") or "")
            for prop in cls.get("properties") or ():
                if not isinstance(prop, Mapping):
                    continue
                yield (
                    str(prop.get("uri") or ""),
                    str(prop.get("name") or ""),
                    str(prop.get("label") or ""),
                    (owner,) if owner else (),
                    str(prop.get("type") or ""),
                )

    return _build(rows())


def terms_from_index(index: Any) -> ClosureTermIndex:
    """Index a :class:`~.semantic_index.SemanticIndex`'s properties (closure-aware)."""
    return _build(
        (
            str(prop.uri),
            str(prop.name or ""),
            str(prop.label or ""),
            tuple(link.uri for link in prop.domains),
            str(prop.property_type or ""),
        )
        for prop in index.properties
    )


def find_candidates(
    index: ClosureTermIndex,
    column_name: str,
    *,
    label: str = "",
    limit: int = DEFAULT_LIMIT,
    strip_prefixes: Iterable[str] = (),
) -> list[ClosureCandidate]:
    """Closure properties whose name or label resembles *column_name*, best first.

    Ordered by ``(-score, uri)`` and cut at *limit*; an empty list when nothing matches.
    """
    queries: list[str] = []
    for text in (normalise_term(column_name, strip_prefixes=strip_prefixes), normalise_term(label)):
        if text and text not in queries:
            queries.append(text)
    best: dict[int, tuple[float, str]] = {}
    for query in queries:
        for position in index.by_norm.get(query, ()):
            best[position] = (1.0, "exact")
        query_tokens = _content_tokens(query)
        if not query_tokens or _is_generic(query_tokens):
            continue
        positions: set[int] = set()
        for token in query_tokens:
            positions.update(index.by_token.get(token, ()))
        for position in positions:
            if best.get(position, (0.0, ""))[1] == "exact":
                continue
            term = index.terms[position]
            for norm in (term.norm_name, term.norm_label):
                if not norm:
                    continue
                term_tokens = _content_tokens(norm)
                if _is_generic(term_tokens) or not _near(query_tokens, term_tokens):
                    continue
                score = SequenceMatcher(None, query, norm).ratio()
                if score > best.get(position, (0.0, ""))[0]:
                    best[position] = (score, "near")
    candidates = [
        ClosureCandidate(
            uri=index.terms[position].uri,
            name=index.terms[position].name,
            class_uris=index.terms[position].class_uris,
            score=score,
            match=match,
        )
        for position, (score, match) in best.items()
    ]
    candidates.sort(key=lambda c: (-c.score, c.uri))
    return candidates[:limit]


def _content_tokens(norm: str) -> frozenset[str]:
    return frozenset(token for token in norm.split() if token not in STOP_TOKENS)


def _is_generic(tokens: frozenset[str]) -> bool:
    """``code``, ``typeCode``, ``statusCode``: every token names a shape, none a concept."""
    return bool(tokens) and tokens <= GENERIC_NAMES


def _near(a: frozenset[str], b: frozenset[str]) -> bool:
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    return bool(small) and small <= big and len(big) - len(small) <= MAX_EXTRA_TOKENS


def _local(uri: str) -> str:
    return uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
