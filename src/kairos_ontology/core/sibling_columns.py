# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Sibling columns: a deferred column that completes a field its table already binds (#1068).

A reviewer binds a table, then fills it out. The cheapest, most obvious next step into
Silver is a deferred column sitting next to a bound field that it completes: the unit of
a bound weight, the currency of a bound amount, the description of a bound code, the
volume next to a bound weight, the actual date next to a bound estimated one. This module
finds those pairs, per table, so the DD-251 backlog can put them first.

It is a ranking aid, never a decision. Nothing here writes the ledger or proposes a
disposition: a sibling is a *field suggestion* for the binding author (the mapping skill or
``generate-bindings``), because a ledger ``bound`` row for a column no binding maps would
silence the DD-169 gate while nothing reached Silver (#881), and DD-248 refuses to turn a
lexical match into a mapping without a model or a human.

The rules are deliberately narrow, and each is backed by evidence beyond the name:

* **The pair is in one table.** Siblings are only looked for among the bound fields of
  the same ``(system, table)``: a ``source.relation`` binding's ``fields:``, a ledger
  ``bound`` row, or a column a dbtModel chain names (#1077; assembled by
  ``deferred_backlog._sibling_fields``).
* **A unit, currency or description pairs by stem.** ``JZ_WeightUQ`` pairs with
  ``JZ_Weight`` because removing the unit token leaves exactly the bound column's name.
  Token-subset matching was measured on this corpus at 62% precision
  (``scaffold_binding._candidate_keys``), with "four distinct currency foreign keys
  collapsing onto ``currency``" as the characteristic error. So a currency with no exact
  stem match pairs only when the table binds exactly one amount.
* **The profile vetoes a shape mismatch.** When the DD-189 profile has the column, a unit
  or currency tagged ``measure-like`` is dropped, and a measure or amount tagged
  anything but ``measure-like`` is dropped (``JR_A9_CostVATClass`` is a code, not an
  amount). Without a profile the name rule stands alone.
* **Dates are "sibling dates", not quartet members.** The temporal-quartet pattern names
  ontology properties and bans ``eta``/``ata`` on them; source columns are ETA and ATA by
  nature. A date next to a bound date is a sibling date, nothing more.
* **Statistics only sink, never rank up.** ``empty`` and ``const`` profile tags push a
  column to the end; distinct-ratio cutoffs proved unreliable in both directions
  (``column_coverage_audit``), so they are not used as a signal of value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

#: The sibling kinds, in the order a reviewer usually wants them.
KINDS = ("unit", "currency", "description", "measure", "amount", "date")

_UNIT = frozenset({"uq", "uom", "unit", "units", "um"})
_CURRENCY = frozenset({"currency", "curr", "ccy", "cur"})
_DESCRIPTION = frozenset({"desc", "description", "descr", "text", "label", "name"})
_CODE = frozenset({"code", "cd", "id", "type", "key", "no", "nr", "num"})
_MEASURE = frozenset({
    "weight", "wt", "volume", "vol", "qty", "quantity", "length", "width", "height",
    "depth", "dimension", "dim", "pieces", "pcs", "packages", "pkgs", "count", "teu", "cbm",
    "ldm", "area",
})
_AMOUNT = frozenset({
    "amount", "amt", "total", "price", "cost", "charge", "fee", "tax", "vat", "value",
    "balance", "outstanding",
})
_DATE = frozenset({"date", "dt", "time", "timestamp", "datetime", "eta", "etd", "ata", "atd"})
#: A last token that makes a column a classifier of a measure, not the measure itself.
_QUALIFIER = frozenset({
    "class", "type", "code", "cd", "flag", "group", "indicator", "ind", "status", "id",
    "key", "no", "nr",
}) | _UNIT | _CURRENCY | _DESCRIPTION
_SINK_TAGS = frozenset({"empty", "const"})

_TOKEN_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def tokens(name: str) -> tuple[str, ...]:
    """Lower-cased word tokens of a column name: ``JZ_WeightUQ`` -> ``(jz, weight, uq)``."""
    return tuple(t.lower() for t in _TOKEN_RE.findall(name))


@dataclass(frozen=True, slots=True)
class Sibling:
    """One deferred column's bound neighbour."""

    kind: str
    #: The bound column, as the binding's expression names it, that this column completes.
    of_column: str
    #: The property token(s) the bound column fills, from the binding's ``fields:``.
    of_property: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "of_column": self.of_column, "of_property": self.of_property}


def detect_sibling(
    column: str,
    bound_fields: Mapping[str, Iterable[str]],
    *,
    profile: Mapping[str, Any] | None = None,
) -> Sibling | None:
    """The bound field *column* completes on its table, or ``None``.

    *bound_fields* is the table's ``column -> property tokens`` (or evidence labels, when
    the property is not known) in authored casing. *profile* is the column's DD-189
    profile entry (``{"type", "null_ratio", "distinct", "tags"}``) when one exists.
    """
    if not bound_fields or column.lower() in {name.lower() for name in bound_fields}:
        return None
    own = tokens(column)
    if not own:
        return None
    tags = frozenset(str(t) for t in (profile or {}).get("tags", ()) or ())
    bound = {name: tokens(name) for name in sorted(bound_fields)}

    def sibling(kind: str, name: str) -> Sibling:
        return Sibling(kind, name, ", ".join(sorted(bound_fields[name])))

    last, stem = own[-1], own[:-1]
    # Word overlap ignores the table code every column of the table starts with (#1077):
    # ``JZ_WeightUQ`` shares ``jz`` with ``JZ_InvoiceAmount`` and nothing that matters.
    own_words = _meaningful(column, own)
    stem_words = tuple(t for t in stem if t in own_words)
    words = {name: _meaningful(name, parts) for name, parts in bound.items()}
    if last in _UNIT and "measure-like" not in tags:
        match = _stem_match(stem, bound) or _unique(
            name for name, parts in bound.items() if _family(parts, _MEASURE | _AMOUNT)
            and _shares(stem_words, tuple(words[name]))
        )
        if match:
            return sibling("unit", match)
    if last in _CURRENCY and "measure-like" not in tags:
        match = _stem_match(stem, bound) or _unique(
            name for name, parts in bound.items() if _family(parts, _AMOUNT)
        )
        if match:
            return sibling("currency", match)
    if last in _DESCRIPTION:
        match = _unique(
            name for name, parts in bound.items()
            if parts and parts[-1] in _CODE and parts[:-1] == stem and stem
        )
        if match:
            return sibling("description", match)
    if last in _QUALIFIER:
        return None
    shape_ok = not tags or "measure-like" in tags
    for kind, family in (("measure", _MEASURE), ("amount", _AMOUNT)):
        if _family(own, family) and shape_ok:
            match = _closest(own, (n for n, p in bound.items() if _family(p, family)), bound)
            if match:
                return sibling(kind, match)
    if (_family(own, _DATE) or "date-like" in tags) and "measure-like" not in tags:
        match = _closest(
            own, (n for n, p in bound.items() if _family(p, _DATE)), bound
        )
        if match:
            return sibling("date", match)
    return None


def column_profiles(hub_root: Path) -> Callable[[str, str, str], dict[str, Any] | None]:
    """A lookup of one column's DD-189 profile entry, loading each system's file once.

    The profile is advisory evidence: a missing or unreadable file answers ``None``.
    """
    from .profile_sources import load_profile

    sources = hub_root / "integration" / "sources"
    loaded: dict[str, dict[str, Any]] = {}

    def lookup(system: str, table: str, column: str) -> dict[str, Any] | None:
        if system not in loaded:
            try:
                loaded[system] = (load_profile(sources, system) or {}).get("tables") or {}
            except Exception:  # noqa: BLE001 - advisory join; a bad profile ranks nothing
                loaded[system] = {}
        table_profile = loaded[system].get(table)
        if not isinstance(table_profile, dict):
            return None
        entry = (table_profile.get("columns") or {}).get(column)
        return entry if isinstance(entry, dict) else None

    return lookup


def sinks(profile: Mapping[str, Any] | None) -> bool:
    """Whether the profile says the column is empty or constant: rank it last."""
    return bool(_SINK_TAGS & set((profile or {}).get("tags", ()) or ()))


def _family(parts: tuple[str, ...], family: frozenset[str]) -> bool:
    return any(part in family for part in parts)


#: A leading table code (``JZ_``, ``AH_``, ``rc_``): shared by every column of the table, so
#: it says nothing about which bound field a column completes (#1077).
_TABLE_PREFIX_RE = re.compile(r"^[A-Za-z0-9]{2,3}_")


def _meaningful(name: str, parts: tuple[str, ...]) -> frozenset[str]:
    """*parts* without the table-code token *name* starts with."""
    prefix = _TABLE_PREFIX_RE.match(name)
    if prefix and parts and parts[0] == prefix.group(0)[:-1].lower():
        parts = parts[1:]
    return frozenset(parts)


def _shares(stem: tuple[str, ...], parts: tuple[str, ...]) -> bool:
    return bool(set(stem) & set(parts))


def _stem_match(stem: tuple[str, ...], bound: Mapping[str, tuple[str, ...]]) -> str | None:
    if not stem:
        return None
    return _unique(name for name, parts in bound.items() if parts == stem)


def _unique(names: Iterable[str]) -> str | None:
    found = list(dict.fromkeys(names))
    return found[0] if len(found) == 1 else None


def _closest(
    own: tuple[str, ...], names: Iterable[str], bound: Mapping[str, tuple[str, ...]]
) -> str | None:
    """The candidate sharing most tokens with *own*; a tie is broken by name order."""
    ranked = sorted(names, key=lambda name: (-len(set(own) & set(bound[name])), name))
    return ranked[0] if ranked else None
