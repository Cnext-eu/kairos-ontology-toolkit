# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Column-level bound state derived from EntityBindings (DD-250, #1062).

#973 made a *table* an EntityBinding reads count as decided for the DD-180 gate: the binding
is the decision, and the ledger refuses a ``bound`` row because "authoring the binding is
what states it". The DD-169 column gate never learned the same lesson. It read the alignment
files and the ledger only, so a column a binding already mapped to Silver was still listed
as a gap, and the only way to clear it was a hand-written column-grain ``bound`` row. On one
hub that put 575 columns in front of a reviewer who could not tell a false gap from a real
one without reading SQL.

Two authored forms bind a column, and they are not equally strong evidence:

* A ``source.relation`` binding names its columns outright, in ``fields[].expression``,
  the identity keys, the grain, a relationship join, a quality rule or the incremental
  load. That is a fact: the column reaches Silver. It is **decided**, derived here and
  never written to the ledger (:meth:`BoundColumns.decided_by_binding`).
* A ``source.dbtModel`` binding selects a contracted model whose ``ref()`` chain reads the
  table. No column lineage exists at design time -- dbt's manifest carries model-level
  edges only and is not present before a build -- and the mapping is often not
  name-preserving (a code map, a sign applied to an amount). What can be read is whether
  the column's *name* appears as an identifier in the SQL of the model that calls
  ``source()`` on its table, or of any closure model downstream of it (the three-layer
  rule, #949: ``stg_`` reads with ``select *``, ``int_`` names the columns). That is
  **evidence, not a decision**: it is offered as ``read_by`` on the gate output and the
  decision sheet, where it becomes a ``bound`` proposal a reviewer or ``--accept-proposals``
  records. A table read with ``select *`` that nothing downstream names is
  ``lineage unconfirmed``: the column may already reach Silver, so a rule must not draft
  ``deferred`` or ``not-business-data`` for it, but nothing clears it either.

Every error here falls toward reporting: a binding the compiler cannot parse, a ``ref()``
that matches no model or several, a column list a Jinja loop generates, a column named
like a SQL keyword -- each leaves the column a gap rather than retiring it silently, which
is the #881 failure mode this module must not reintroduce.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

import yaml

if TYPE_CHECKING:  # the compiler is imported lazily: `validate` and `next` read this too
    from .compiler.bindings import EntityBinding

_Columns = Mapping[str, frozenset[str]]

#: ``select *``, ``select distinct *`` and ``select s.*`` -- the direct reader passes the
#: whole table on, so a column's absence from its SQL says nothing about its fate.
_SELECT_STAR_RE = re.compile(r"\bselect\s+(?:distinct\s+)?(?:[A-Za-z_][\w$]*\.)?\*", re.IGNORECASE)
#: ``{{ dbt_utils.star(...) }}`` and ``{{ star(...) }}`` expand to a column list at render time.
_STAR_MACRO_RE = re.compile(r"\b(?:dbt_utils\.)?star\s*\(", re.IGNORECASE)
_JINJA_BLOCK_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
_STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")
#: Quoted identifiers in the three common dialect forms, then bare ones. The lookbehind
#: keeps ``1e5`` from yielding ``e5`` while still reading ``s.sailing_date`` after its dot.
_IDENTIFIER_RE = re.compile(
    r'"([^"]+)"|\[([^\]]+)\]|`([^`]+)`|(?<![\w$])([A-Za-z_][A-Za-z0-9_$]*)'
)
#: Words that are SQL, not columns. Deliberately short: a column that happens to be named
#: ``order`` or ``status`` is a real case, and the cost of missing it is one un-suggested
#: column, while the cost of a long stoplist is a suggestion that never appears.
_SQL_KEYWORDS: frozenset[str] = frozenset(
    {
        "select", "from", "where", "join", "left", "right", "inner", "outer", "full",
        "cross", "on", "as", "and", "or", "not", "null", "is", "in", "case", "when",
        "then", "else", "end", "group", "by", "order", "having", "limit", "union", "all",
        "distinct", "with", "using", "true", "false", "cast", "over", "partition", "desc",
        "asc", "between", "like", "exists", "coalesce", "nullif", "count", "sum", "min",
        "max", "avg", "row_number", "lower", "upper", "trim", "concat", "try_cast",
    }
)


@dataclass(frozen=True)
class BoundColumns:
    """What the hub's bindings say about each source column, keyed by ``(system, table)``.

    Column names are lower-cased on both sides of every lookup: the bronze vocabulary and
    a binding's authored expressions are two surfaces with no shared casing contract.
    The mappings are read-only views; the memoized instance is shared between callers.
    """

    #: Relation bindings: column -> binding file names whose expressions, keys or rules
    #: name it. A hit here is a decision.
    named: Mapping[tuple[str, str], _Columns]
    #: dbtModel chains: column -> model stems whose SQL names it. A hit here is evidence.
    read_by: Mapping[tuple[str, str], _Columns]
    #: Tables a chain model reads with ``select *`` (or a star macro): those model stems.
    unconfirmed: Mapping[tuple[str, str], frozenset[str]]

    def decided_by_binding(self, system: str, table: str, column: str) -> frozenset[str]:
        """Binding files that name *column* outright -- non-empty means decided."""
        return self.named.get((system, table), {}).get(column.lower(), frozenset())

    def read_by_models(self, system: str, table: str, column: str) -> frozenset[str]:
        """Chain model stems whose SQL names *column* -- evidence for a ``bound`` proposal."""
        return self.read_by.get((system, table), {}).get(column.lower(), frozenset())

    def unconfirmed_readers(self, system: str, table: str, column: str) -> frozenset[str]:
        """Model stems that read the table with ``select *`` when nothing names *column*.

        Empty once a downstream model names the column: that is the stronger evidence.
        """
        if self.read_by_models(system, table, column):
            return frozenset()
        return self.unconfirmed.get((system, table), frozenset())

    @property
    def empty(self) -> bool:
        return not (self.named or self.read_by or self.unconfirmed)


EMPTY_BOUND_COLUMNS = BoundColumns(
    MappingProxyType({}), MappingProxyType({}), MappingProxyType({})
)


def is_gap_column_decided(
    recorded: dict[tuple[str, str, str], dict[str, Any]],
    bound: BoundColumns,
    system: str,
    table: str,
    column: str,
) -> str:
    """Why one gap column is decided: ``"ledger"``, ``"binding"`` or ``""`` (undecided).

    The one predicate the DD-169 gate, the decision sheet, ``--auto`` and ``--apply``
    share (#948: two definitions of "decided" once let the sheet say 0 while the gate
    blocked). The ledger is consulted first because it is the explicit record; a binding
    that names the column decides it without a row (DD-250). A dbtModel chain never
    decides here -- its evidence reaches the reviewer through
    :meth:`BoundColumns.read_by_models` instead.

    One exception to ledger-first: a column-grain ``deferred`` row is retired by a binding
    that names the column (DD-251, #1069). ``deferred`` means "model it later"; once a
    binding maps it, it has been modelled, so the answer is ``"binding"``.
    """
    from .source_disposition import column_decision

    entry = column_decision(recorded, system, table, column)
    if entry is not None and not retired_by_binding(entry, bound, system, table, column):
        return "ledger"
    if bound.decided_by_binding(system, table, column):
        return "binding"
    return ""


def retired_by_binding(
    entry: Mapping[str, Any],
    bound: BoundColumns,
    system: str,
    table: str,
    column: str,
) -> bool:
    """Whether a ledger *entry* for one column is a ``deferred`` a binding has retired.

    Only a column-grain ``deferred`` retires (DD-251): it is the one disposition that says
    "not modelled yet". A ruled-out column a binding still names is a contradiction for a
    reviewer, not something to resolve here. Only a ``source.relation`` binding counts; a
    dbtModel chain's ``read_by`` stays evidence (DD-250).
    """
    return (
        bool(column)
        and str(entry.get("column") or "") == column
        and str(entry.get("disposition") or "") == "deferred"
        and bool(bound.decided_by_binding(system, table, column))
    )


def binding_referenced_columns(binding: EntityBinding) -> set[str]:
    """Every source column *binding* references anywhere, lower-cased.

    ``fields``, ``technicalFields``, ``identity.sourceKey``/``businessKey``,
    ``grain.columns``, ``relationships[].join[].local``, ``quality[].columns`` and every
    ``load.incremental`` column -- the last group is easy to miss and was omitted from the
    column-coverage audit's own first draft: ``source_updated_at`` is frequently exactly
    one of the audit-trail timestamps that audit would otherwise flag as an orphan.
    Moved here from ``column_coverage_audit`` (#353) so the gate and the audit read one
    definition.
    """
    from .compiler.adapter import _expression_columns

    refs: set[str] = set()
    for f in binding.fields:
        refs.update(_expression_columns(f.expression))
    for tf in binding.technical_fields:
        refs.update(_expression_columns(tf.expression))
    refs.update(binding.identity.source_key)
    refs.update(binding.identity.business_key)
    refs.update(binding.grain.columns)
    for rel in binding.relationships:
        for join in rel.on:
            refs.add(join.local)
    for q in binding.quality:
        refs.update(q.columns)
    incremental = binding.load.incremental
    if incremental is not None:
        refs.update(incremental.merge_identity)
        refs.update(incremental.canonical_hash_inputs)
        refs.add(incremental.cdc_operation.column)
        for col in (
            incremental.source_updated_at,
            incremental.business_effective_at,
            incremental.ingested_at,
        ):
            if col:
                refs.add(col)
        refs.update(incremental.total_order)
    return {c.lower() for c in refs if c}


def reads_star(text: str) -> bool:
    """Whether *text* passes a whole relation on: ``select *`` or a star macro."""
    from .compiler.dbt_source import strip_jinja_comments, strip_sql_comments

    rendered = strip_jinja_comments(text)
    if _STAR_MACRO_RE.search(rendered):
        return True
    return bool(_SELECT_STAR_RE.search(strip_sql_comments(rendered)))


def sql_identifiers(text: str) -> frozenset[str]:
    """Lower-cased identifiers *text* names, with Jinja, comments and literals removed.

    Jinja blocks go first: ``source('tms', 'shipment')`` would otherwise read as a column
    named ``shipment``. String literals go next so ``where status = 'eta'`` does not read
    ``eta``. What remains is scanned for quoted and bare identifiers; SQL keywords and the
    commonest function names are dropped. Aliases and table names survive the scan, so a
    column that shares a name with the table it sits on reads as named -- a false
    *suggestion*, never a false decision.
    """
    from .compiler.dbt_source import strip_jinja_comments, strip_sql_comments

    rendered = _JINJA_BLOCK_RE.sub(" ", strip_jinja_comments(text))
    rendered = _STRING_LITERAL_RE.sub(" ", strip_sql_comments(rendered))
    names: set[str] = set()
    for match in _IDENTIFIER_RE.finditer(rendered):
        name = next(group for group in match.groups() if group is not None)
        lowered = name.strip().lower()
        if lowered and lowered not in _SQL_KEYWORDS:
            names.add(lowered)
    return frozenset(names)


def load_bound_columns(bindings_dir: Path, hub_root: Path) -> BoundColumns:
    """The hub's :class:`BoundColumns`, memoized per hub state.

    Shaped like ``load_bound_relations`` (#598, #973): a hit is trusted only after every
    file the answer was read from -- each binding, every model SQL the ``ref()`` walk
    opened -- re-hashes to the same digest and the listing of files that *could* be read
    is unchanged, so an edited or added binding or model is a miss. Bypassed entirely when
    ``ontology_loader.CACHE_ENABLED`` is off (``compile --no-cache``).
    """
    from . import ontology_loader
    from .source_disposition import _files_unchanged, _inputs_listing

    key = (str(Path(bindings_dir).resolve()), str(Path(hub_root).resolve()))
    listing = _inputs_listing(bindings_dir, hub_root)
    if ontology_loader.CACHE_ENABLED:
        hit = _BOUND_COLUMNS_CACHE.get(key)
        if hit is not None and hit[2] == listing and _files_unchanged(hit[1]):
            return hit[0]
    read: dict[Path, str] = {}
    bound = _load_bound_columns_uncached(bindings_dir, hub_root, read)
    _BOUND_COLUMNS_CACHE.clear()  # one hub state at a time is all a run needs
    _BOUND_COLUMNS_CACHE[key] = (bound, read, listing)
    return bound


#: ``load_bound_columns`` results: key -> (answer, {file read: sha256}, input listing).
_BOUND_COLUMNS_CACHE: dict[tuple[str, str], tuple[BoundColumns, dict[Path, str], tuple[str, ...]]] = {}


def _load_bound_columns_uncached(
    bindings_dir: Path, hub_root: Path, read: dict[Path, str]
) -> BoundColumns:
    """The implementation :func:`load_bound_columns` memoizes; *read* collects inputs."""
    from .compiler.bindings import load_entity_binding
    from .source_disposition import _digest, _model_index

    if not bindings_dir.is_dir():
        return EMPTY_BOUND_COLUMNS
    named: dict[tuple[str, str], dict[str, set[str]]] = {}
    read_by: dict[tuple[str, str], dict[str, set[str]]] = {}
    unconfirmed: dict[tuple[str, str], set[str]] = {}
    model_index: dict[str, list[Path]] | None = None
    for path in sorted(bindings_dir.glob("*.yaml")):
        read[path] = _digest(path)
        try:
            text = path.read_text(encoding="utf-8")
            payload = yaml.safe_load(text)
        except Exception:  # defensive: a malformed binding is the compiler's problem
            continue
        if not isinstance(payload, dict):
            continue
        raw_source = payload.get("source")
        source: dict[str, Any] = raw_source if isinstance(raw_source, dict) else {}
        relation = source.get("relation")
        if isinstance(relation, str) and "." in relation:
            system, _, table = relation.partition(".")
            try:
                binding = load_entity_binding(text, path=str(path))
            except Exception:  # a binding compile rejects decides nothing (fail to report)
                continue
            columns = named.setdefault((system.strip(), table.strip()), {})
            for column in binding_referenced_columns(binding):
                columns.setdefault(column, set()).add(path.name)
        model = source.get("dbtModel")
        if isinstance(model, dict):
            if model_index is None:
                model_index = _model_index(hub_root)
            _collect_chain_reads(model, hub_root, model_index, read, read_by, unconfirmed)
    return BoundColumns(
        named=_freeze(named),
        read_by=_freeze(read_by),
        unconfirmed=MappingProxyType({k: frozenset(v) for k, v in unconfirmed.items()}),
    )


def _freeze(
    columns: dict[tuple[str, str], dict[str, set[str]]],
) -> Mapping[tuple[str, str], _Columns]:
    return MappingProxyType(
        {
            key: MappingProxyType({column: frozenset(who) for column, who in names.items()})
            for key, names in columns.items()
            if names
        }
    )


def _collect_chain_reads(
    model: dict[str, Any],
    hub_root: Path,
    model_index: dict[str, list[Path]],
    read: dict[Path, str],
    read_by: dict[tuple[str, str], dict[str, set[str]]],
    unconfirmed: dict[tuple[str, str], set[str]],
) -> None:
    """Record what one ``source.dbtModel`` binding's ``ref()`` closure says about columns.

    Walks the closure as ``source_disposition._dbt_model_source_pairs`` does (a ``ref()``
    matching no model or several ends that branch), then, for every table a closure model
    reads with ``source()``, attributes the identifiers of that model *and of every
    closure model downstream of it* to the table's columns. Downstream matters under the
    three-layer rule: the ``stg_`` model that reads the table says ``select *`` and the
    ``int_`` model above it is where the column is named.
    """
    from .compiler.dbt_source import extract_refs, extract_source_pairs
    from .source_disposition import _digest

    sql_path = model.get("sqlPath")
    if not isinstance(sql_path, str) or not sql_path.strip():
        return
    models: dict[Path, tuple[str, str, frozenset[tuple[str, str]], frozenset[str]]] = {}
    pending = [Path(hub_root) / sql_path]
    while pending:
        path = pending.pop()
        read[path] = _digest(path)  # recorded before the read: a missing-then-present path is a miss
        try:
            key = path.resolve()
            text = path.read_text(encoding="utf-8")
        except Exception:  # defensive: an unresolvable path is the compiler's problem
            continue
        if key in models:
            continue
        refs = extract_refs(text)
        models[key] = (path.stem, text, extract_source_pairs(text), refs)
        for ref_name in refs:
            matches = model_index.get(ref_name, [])
            if len(matches) == 1:
                pending.append(matches[0])
    if not models:
        return
    # Reverse the ref() graph inside the closure: who reads whom.
    parents: dict[Path, set[Path]] = {key: set() for key in models}
    for key, (_stem, _text, _pairs, refs) in models.items():
        for ref_name in refs:
            matches = model_index.get(ref_name, [])
            if len(matches) == 1:
                child = matches[0].resolve()
                if child in parents:
                    parents[child].add(key)
    identifiers: dict[Path, frozenset[str]] = {}
    for key, (stem, text, pairs, _refs) in models.items():
        if not pairs:
            continue
        readers = {key}
        frontier = [key]
        while frontier:
            current = frontier.pop()
            for parent in parents[current]:
                if parent not in readers:
                    readers.add(parent)
                    frontier.append(parent)
        star = reads_star(text)
        for pair in pairs:
            columns = read_by.setdefault(pair, {})
            for reader in readers:
                if reader not in identifiers:
                    identifiers[reader] = sql_identifiers(models[reader][1])
                for name in identifiers[reader]:
                    columns.setdefault(name, set()).add(models[reader][0])
            if star:
                unconfirmed.setdefault(pair, set()).add(stem)
