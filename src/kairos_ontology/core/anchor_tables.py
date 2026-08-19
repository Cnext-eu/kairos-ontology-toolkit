# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Global table anchoring: every source table against the whole class catalog (DD-185).

The per-table pipeline decides a table's anchor from inside one domain's view:
affinity guesses the domain, a lexical shortlist picks twelve candidate classes,
and the model chooses from those. Measured on the live corpus, the shortlist
ranked ``TradeParty`` #24 for a table of companies (``Address`` won on column
overlap, 44:20), ~40% of tables needed a second 70KB full-inventory call to
recover, and a plausible-but-wrong shortlist anchor passes both retry thresholds
silently.

Anchoring is a *grain* question — what is one row? — and it needs the widest
possible view with almost no detail: every table's column names against every
class's one-line description fit in a single ~35k-token call. Tested on the live
corpus that call scored 6/6 on human-reviewed anchors, nulled the metadata junk
tables, invented zero class names, and reproduced the hand-crafted hub's grain
columns 9/9 as a secondary output.

The domain then *falls out of the anchor* — the blueprint says who owns each
class — instead of being an upstream guess that constrains what the model may
see. Derivation is bridge-aware: a table whose anchor is owned elsewhere but
reachable through a declared cross-domain bridge (DD-181) stays in the bridging
domain rather than being moved to the owner, because moving it would trade an
anchor gap for a grain error.

Two things the live run proved the stage also has to do (#519):

* **Resolve duplicate class names by property overlap, not by read order.**
  ``bookings`` and ``shipments`` resolved to ``onerecord/cargo#Booking`` and
  ``#Shipment``, which the closure gives ZERO properties, while the identically
  named ``dcsa/booking`` copies carry the 23 and 13 properties alignment then
  proposed. Both modules are owned by the same domain, so ownership could not
  separate them and whichever copy the catalog read first won. A 0.98-confidence
  anchor over 90 columns produced no class at all.
* **Route the source's own schema catalogue out before anchoring.** A flatfile
  import of a "Tables Columns Info" workbook profiles the source's description of
  its own schema as if it were business data. Anchoring a table that lists tables
  costs a domain assignment, an alignment pass, and — when the workbook also
  carries a sample extract of a real table — a duplicate-mapping refusal.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from ._provenance import ai_attribution, provenance_comment
from .ai_provider import (
    ROLE_ALIGNMENT,
    create_chat_completion,
    resolve_ai_seed,
    resolve_reasoning_effort,
)
from .analyse_sources import (
    load_cross_domain_bridges,
    load_data_domains,
    parse_source_vocabulary,
)
from .class_anchoring import read_reference_terms
from .tracing import call_metadata, flush_tracing, new_session_id

logger = logging.getLogger(__name__)

#: Output artifact, alongside the affinity and alignment files.
ANCHORS_FILENAME = "table-anchors.yaml"

#: Sheet review statuses (DD-190). ``proposed`` is machine-written; humans move
#: an entry to ``confirmed``/``edited`` (both pin it) or ``rejected`` (re-anchor
#: next run). ``stale-confirmed`` is machine-written when a pinned entry's
#: source schema changed underneath it: values kept, pin released.
SHEET_PINNED_STATUSES = frozenset({"confirmed", "edited"})

#: Flags the model may set on a sheet entry; anything else is dropped.
ALLOWED_SHEET_FLAGS = frozenset(
    {"unowned-anchor", "extension-candidate", "code-list", "no-data-evidence", "versioned"}
)


def sheet_schema_hash(columns: list[str]) -> str:
    """Stable identity of a table's schema for sticky-entry comparison (DD-190).

    Sorted raw column names only — the same inputs the anchoring outline is
    built from. A confirmed entry pins exactly as long as this matches; any
    column change releases the pin (``stale-confirmed``) because human
    stickiness must be bounded by evidence identity.
    """
    import hashlib

    return hashlib.sha256("\n".join(sorted(columns)).encode("utf-8")).hexdigest()[:16]

#: The human-governed table/column ledger (DD-164).
DISPOSITIONS_FILENAME = "table-dispositions.yaml"


class MalformedLedgerError(RuntimeError):
    """A human-governed ledger exists but cannot be read.

    Distinct from an absent ledger, which is the normal case. This one is fatal on
    purpose: :func:`load_table_dispositions` is what stops the schema-catalogue
    heuristic from overruling a recorded decision, so returning an empty mapping for a
    file the operator believes is in force lets the heuristic quietly overrule them.
    Erasing human governance while reporting success is worse than refusing to run --
    the same reasoning ``registered_concepts`` already applies to a malformed
    registration file.
    """


class ArtifactState(str, Enum):
    """Why a pipeline artifact yielded nothing -- absence is not emptiness.

    Every loader below collapsed three distinguishable situations into an empty
    result: the file was never written, it exists but cannot be parsed, or it parsed
    and genuinely holds no entries. Callers could not tell "you have not run
    ``anchor-tables``" from "anchoring found nothing", which is why
    ``propose-alignment`` skipped the whole DD-185 regrouping block in silence.
    """

    MISSING = "missing"
    UNPARSEABLE = "unparseable"
    EMPTY = "empty"
    PRESENT = "present"


def _read_yaml_artifact(path: Path, *, what: str) -> tuple[ArtifactState, dict[str, Any]]:
    """Read a YAML artifact, reporting *why* it is empty rather than only that it is.

    A parse failure always warns. Three of these loaders used to swallow it in total
    silence -- not even a log line -- so a corrupt artifact was indistinguishable from
    a clean run.
    """
    if not path.is_file():
        return ArtifactState.MISSING, {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 - the caller decides whether this is fatal
        logger.warning("Could not parse %s (%s); ignoring %s.", path, exc, what)
        return ArtifactState.UNPARSEABLE, {}
    if not isinstance(payload, dict):
        logger.warning("%s is not a YAML mapping; ignoring %s.", path, what)
        return ArtifactState.UNPARSEABLE, {}
    return (ArtifactState.PRESENT if payload else ArtifactState.EMPTY), payload


def probe_anchors(analysis_dir: Path) -> tuple[ArtifactState, int]:
    """Return ``(state, anchored_table_count)`` for the anchors artifact.

    The precondition ``propose-alignment`` needs: it must be able to say "run
    ``anchor-tables`` first" instead of silently aligning without anchors.
    """
    state, payload = _read_yaml_artifact(
        Path(analysis_dir) / ANCHORS_FILENAME, what="global anchors"
    )
    tables = payload.get("tables") or []
    count = sum(1 for t in tables if isinstance(t, dict))
    if state is ArtifactState.PRESENT and count == 0:
        return ArtifactState.EMPTY, 0
    return state, count

#: Below this confidence an anchor is advisory only: it is recorded but never
#: applied as an alignment override, so a hesitant guess cannot silently pin a
#: table to the wrong class.
ANCHOR_CONFIDENCE_FLOOR = 0.6

#: Tables per model call. One call sees the whole corpus when it fits; a corpus
#: larger than this is chunked with the full catalog repeated per chunk, which
#: trades tokens for keeping every chunk's candidate view complete.
MAX_TABLES_PER_ANCHOR_CALL = 150

#: Anchoring-relevant rules from the pattern library. Deliberately the small
#: subset that changes *anchor* decisions; mapping-time and binding-time rules
#: keep their existing enforcement points (coded guards, compile gates).
_PATTERN_RULES = """
ANCHORING RULES FROM THE PATTERN LIBRARY:
- subclass-identity-by-role: when a table's rows are parties/organisations carrying
  role FLAGS (is_customer, is_subcontractor, archived_customer...), anchor to the
  neutral party class - NEVER to a role subclass (Customer, Buyer, Shipper). A row's
  roles are assignments, not identity.
- governed-code-list: a table whose rows are code+description pairs anchors to a
  code-list/reference concept, not to the entity the codes describe.
- grain: anchor to the class matching ONE ROW. A line-items table anchors to the
  LINE class, not the header; an events table to the EVENT class, not the subject.
"""

#: Column names that only occur in a description of a schema — the
#: ``INFORMATION_SCHEMA.COLUMNS`` family, plus the BigQuery/Snowflake extras the
#: live workbook carried. Matched on the normalised name, so ``TABLE_NAME``,
#: ``tableName`` and ``Table Name`` all count as one hit.
_CATALOGUE_COLUMNS = frozenset(
    {
        "table_name",
        "table_schema",
        "table_catalog",
        "table_type",
        "schema_name",
        "column_name",
        "column_default",
        "column_type",
        "data_type",
        "field_name",
        "field_type",
        "ordinal_position",
        "is_nullable",
        "is_partitioning_column",
        "clustering_ordinal_position",
        "collation_name",
        "character_maximum_length",
        "numeric_precision",
        "numeric_scale",
        "constraint_name",
        "index_name",
    }
)

#: A table is its own proof of being a schema catalogue when it carries at least
#: this many distinct catalogue columns AND they dominate its column list. Both
#: halves matter: three hits alone would catch a business table that happens to
#: record a ``data_type``, and a share alone would catch a two-column lookup.
_CATALOGUE_COLUMN_HITS = 3
_CATALOGUE_COLUMN_SHARE = 0.6

#: The other proof: a column whose values ARE the names of other profiled tables.
#: Deliberately steep — five distinct matches covering four fifths of the sampled
#: values, and only on a narrow table. A polymorphic ``entity_type`` column on a
#: wide audit or comment table can legitimately hold table names; a table whose
#: entire content is a list of table names cannot be anything else.
_CATALOGUE_SAMPLE_MATCHES = 5
_CATALOGUE_SAMPLE_SHARE = 0.8
_CATALOGUE_NARROW_COLUMNS = 4

#: ``import-source`` names a flatfile sheet ``<workbook>__<sheet>``.
_SHEET_SEPARATOR = "__"

#: A workbook name is catalogue-ish only when it says *table* AND says what about
#: the tables. "Qargo Tables Columns Info" qualifies; "Average Margins 08-2025"
#: and "Shipping Routes Table" do not.
_CATALOGUE_CONTAINER_SUBJECTS = frozenset({"table", "tables"})
_CATALOGUE_CONTAINER_ASPECTS = frozenset(
    {
        "column",
        "columns",
        "schema",
        "schemas",
        "metadata",
        "dictionary",
        "catalog",
        "catalogue",
        "ddl",
        "datatypes",
    }
)

#: Tokens too generic to evidence that a column and a property mean the same
#: thing. Without them ``id``/``name``/``code`` match nearly every class.
_GENERIC_TOKENS = frozenset(
    {
        "and",
        "code",
        "codes",
        "date",
        "datetime",
        "for",
        "from",
        "has",
        "identifier",
        "ids",
        "name",
        "names",
        "number",
        "ref",
        "status",
        "the",
        "time",
        "type",
        "types",
        "value",
        "values",
    }
)


@dataclass
class ClassCatalog:
    """The one-line-per-class view of every reference class the hub can resolve."""

    text: str
    #: name -> every copy of that name:
    #: ``[{"module": str, "uri": str, "properties": [str, ...]}, ...]``.
    #: A list, deliberately: the same class name exists in several modules
    #: (``Consignment`` in bsp/commercial AND mmt/consignment), and keeping one
    #: arbitrary copy derived ownership from the wrong module on the live run.
    #: ``properties`` is that copy's own+inherited property local names in the
    #: resolved closure — the only thing that tells ``Booking`` in a vocabulary
    #: which defines none from ``Booking`` in the one which defines 23 (#519).
    index: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    #: module uri (no trailing #) -> owning domain ids
    owners: dict[str, list[str]] = field(default_factory=dict)
    #: class uri -> domain ids declaring a bridge TO that class
    bridged_from: dict[str, list[str]] = field(default_factory=dict)


def _first_sentence(text: str) -> str:
    return (text or "").replace("\n", " ").split(". ")[0][:130]


def _normalise(name: str) -> str:
    """``TABLE_NAME``, ``tableName`` and ``Table Name`` all to ``table_name``."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(name or ""))
    return re.sub(r"[^a-z0-9]+", "_", spaced.lower()).strip("_")


def _tokens(name: str) -> set[str]:
    """Meaning-bearing words in an identifier, generic ones dropped."""
    return {
        part
        for part in _normalise(name).split("_")
        if len(part) > 2 and part not in _GENERIC_TOKENS
    }


def _class_property_names(catalog_path: Path, modules: set[str]) -> dict[str, list[str]]:
    """``class uri -> property local names``, from the resolved closure.

    A second pass over the modules :func:`read_reference_terms` just read, because
    that loader flattens classes and properties into one list and drops the link
    between them, and it lives in a module this one only imports. The repeat parse
    costs ~10s on a 109-module hub against a stage that then spends minutes in the
    model — cheap for the thing it buys, which is knowing that a candidate anchor
    class cannot carry a single column.

    Advisory: a failure degrades the tie-break to ownership order rather than
    failing the run.
    """
    if not modules:
        return {}
    try:
        # Local import: propose_alignment imports this module.
        from .propose_alignment import extract_ref_model_inventory

        inventory = extract_ref_model_inventory(sorted(modules), Path(catalog_path))
    except Exception:  # noqa: BLE001 - enrichment only; anchoring must still run
        logger.warning("Could not resolve class properties; anchor tie-break degraded.")
        return {}
    return {
        str(cls.get("uri")): [
            str(p.get("name")) for p in cls.get("properties") or [] if p.get("name")
        ]
        for cls in inventory
        if cls.get("uri")
    }


def build_class_catalog(
    catalog_path: Path,
    ref_models_dir: Path | None,
    accelerator: str | None,
) -> ClassCatalog:
    """Render every resolvable class as one line, marked with blueprint ownership.

    The ownership mark is not decoration: without it the tested call picked ONE
    Record's thin ``Company`` over UN/CEFACT's ``TradeParty`` for a companies
    table (5/6 known answers); with it, 6/6. A name match in a foreign vocabulary
    must not outrank the class the blueprint governs.

    Each copy of a name additionally carries its property local names in the
    closure. The rendered line stays one-per-name — the model reads grain from
    descriptions, not property lists — but the resolver needs per-copy properties
    to break a name collision on something better than read order (#519).
    """
    owners: dict[str, list[str]] = {}
    bridged: dict[str, list[str]] = {}
    if ref_models_dir is not None and accelerator:
        domains = load_data_domains(Path(ref_models_dir), accelerator=accelerator)
        for dom_id, meta in sorted(domains.items()):
            for uri in meta.get("uris") or []:
                owners.setdefault(str(uri).rstrip("#"), []).append(dom_id)
        for bridge in load_cross_domain_bridges(Path(ref_models_dir), accelerator):
            rng = str(bridge.get("range_class_uri") or "")
            src = str(bridge.get("source_domain") or "")
            if rng and src:
                bridged.setdefault(rng, []).append(src)

    index: dict[str, list[dict[str, Any]]] = {}
    comments: dict[str, str] = {}
    for term in read_reference_terms(Path(catalog_path)):
        if term.kind != "class":
            continue
        module = str(term.module).rstrip("#")
        index.setdefault(term.name, []).append({"module": module, "uri": str(term.uri)})
        # Keep the richest description across copies — the point of the line.
        text = _first_sentence(term.comment) or str(term.label or "")
        if len(text) > len(comments.get(term.name, "")):
            comments[term.name] = text

    properties = _class_property_names(
        Path(catalog_path), {copy["module"] for copies in index.values() for copy in copies}
    )
    for copies in index.values():
        for copy in copies:
            copy["properties"] = list(properties.get(copy["uri"], ()))

    # One line per NAME, ownership merged across every copy. Rendering each copy
    # separately gave the model contradictory lines ("Contact [owned by 'party']"
    # and "Contact [UNOWNED]") and left the resolver guessing which was meant.
    lines: list[str] = []
    for name in index:
        owner_ids = sorted(
            {dom for copy in index[name] for dom in owners.get(copy["module"], [])}
        )
        mark = f"owned by domain '{'/'.join(owner_ids)}'" if owner_ids else "UNOWNED"
        lines.append(f"- {name} [{mark}]: {comments.get(name, '')}")
    return ClassCatalog(text="\n".join(lines), index=index, owners=owners, bridged_from=bridged)


def load_excluded_columns(analysis_dir: Path) -> set[tuple[str, str, str]]:
    """Columns the disposition ledger (DD-164) marks as not business data.

    ``(system, table, column)`` triples, plus ``(system, "", column)`` wildcards
    for a column excluded across a whole source system — a SaaS tenant
    discriminator appears in every table the vendor ships, and thirty identical
    per-table entries is how a ledger stops being read.

    The ledger is the governed home for this knowledge: durable, reviewed, and
    now consumed by the prompt builders rather than living in someone's memory.
    """
    path = Path(analysis_dir) / DISPOSITIONS_FILENAME
    state, payload = _read_yaml_artifact(path, what="the column exclusions")
    if state is ArtifactState.UNPARSEABLE:
        raise MalformedLedgerError(
            f"{path} exists but could not be parsed. It is the governed home for "
            "column exclusions (DD-164), so continuing would silently ignore every "
            "exclusion recorded in it. Fix the YAML, or move the file aside to run "
            "without it."
        )
    excluded: set[tuple[str, str, str]] = set()
    for entry in payload.get("tables") or []:
        if not isinstance(entry, dict) or not entry.get("column"):
            continue
        if str(entry.get("disposition") or "") == "not-business-data":
            excluded.add(
                (
                    str(entry.get("system") or ""),
                    str(entry.get("table") or ""),
                    str(entry.get("column") or ""),
                )
            )
    return excluded


def _is_excluded(
    excluded: set[tuple[str, str, str]], system: str, table: str, column: str
) -> bool:
    return (system, table, column) in excluded or (system, "", column) in excluded


def read_source_tables(sources_dir: Path) -> list[tuple[str, str, list[dict[str, Any]]]]:
    """``(system, table, column dicts)`` for every profiled source table.

    The single parse pass behind both the anchor outline and the schema-catalogue
    screen. Keeps the full column dicts — profiling metadata such as
    ``samples`` never reaches the prompt, but the screen needs it to see that a
    column's values are the names of other tables.
    """
    tables: list[tuple[str, str, list[dict[str, Any]]]] = []
    for vocab_file in sorted(Path(sources_dir).glob("*/vocabulary/*.vocabulary.ttl")):
        system = vocab_file.parts[-3]
        for table, columns in sorted(parse_source_vocabulary(vocab_file).items()):
            tables.append((system, table, list(columns)))
    return tables


def build_source_outline(
    sources_dir: Path,
    excluded_columns: set[tuple[str, str, str]] | None = None,
    tables: list[tuple[str, str, list[dict[str, Any]]]] | None = None,
) -> list[tuple[str, str, list[str]]]:
    """Return ``(system, table, column_names)`` for every source table.

    Column *names only* — no sample values. Tested: samples cost accuracy here
    (5/6 vs 6/6) and ~7k tokens. Anchoring reads the grain from the schema;
    values are stage-2 evidence for column mapping.

    Columns in *excluded_columns* are left out entirely, so the model cannot
    build a grain or key on a column the hub has ruled non-business — a SaaS
    tenant id looks exactly like a composite-key member until someone says
    otherwise, and on the live run the model keyed every qargo table on it.

    Pass *tables* (from :func:`read_source_tables`) to render an already-parsed,
    already-screened set of tables instead of re-reading *sources_dir*.
    """
    excluded = excluded_columns or set()
    parsed = read_source_tables(Path(sources_dir)) if tables is None else tables
    outline: list[tuple[str, str, list[str]]] = []
    for system, table, columns in parsed:
        names = [
            str(c.get("name", ""))
            for c in columns
            if not _is_excluded(excluded, system, table, str(c.get("name", "")))
        ]
        outline.append((system, table, names))
    return outline


def load_table_dispositions(analysis_dir: Path) -> dict[tuple[str, str], str]:
    """``(system, table) -> disposition`` for the table-grain ledger entries (DD-164).

    The override for the schema-catalogue screen: any recorded disposition other
    than ``not-business-data`` is someone having already decided the table IS in
    scope, and a heuristic must not overrule that.
    """
    path = Path(analysis_dir) / DISPOSITIONS_FILENAME
    state, payload = _read_yaml_artifact(path, what="the table dispositions")
    if state is ArtifactState.UNPARSEABLE:
        raise MalformedLedgerError(
            f"{path} exists but could not be parsed. Every disposition other than "
            "not-business-data is someone having decided the table IS in scope, and "
            "this function is what stops the schema-catalogue heuristic overruling "
            "them -- so continuing would let a heuristic silently overrule a recorded "
            "human decision. Fix the YAML, or move the file aside to run without it."
        )
    decided: dict[tuple[str, str], str] = {}
    for entry in payload.get("tables") or []:
        if not isinstance(entry, dict) or entry.get("column") or not entry.get("table"):
            continue
        decided[(str(entry.get("system") or ""), str(entry["table"]))] = str(
            entry.get("disposition") or ""
        )
    return decided


def load_excluded_tables(analysis_dir: Path) -> dict[tuple[str, str], str]:
    """``(system, table) -> evidence`` for tables the anchoring screen routed out.

    Reads back the ``excluded`` block :func:`run_anchor_tables` writes into
    ``table-anchors.yaml``. The companion to :func:`load_excluded_columns` one
    grain up: that one reads a human-governed ledger, this one reads what the
    schema-catalogue screen decided on the last anchoring run.

    An entry here is a pipeline-level fact — "this table is not business data at
    all" — so a stage that enumerates source columns and does not consult it is
    reporting on rows that describe another table's columns. Nothing read the key
    between #519 writing it and #528: 24% of the disposition conflicts on the live
    hub were columns of two sheets of a "Tables Columns Info" workbook.

    The evidence string is kept rather than reduced to a set of keys, because the
    screen is a heuristic: a stage that honours an exclusion should be able to say
    which table it dropped and on what grounds instead of making rows vanish.
    """
    path = Path(analysis_dir) / ANCHORS_FILENAME
    _state, payload = _read_yaml_artifact(path, what="the schema-catalogue screen")
    excluded: dict[tuple[str, str], str] = {}
    for entry in payload.get("excluded") or []:
        if not isinstance(entry, dict) or not entry.get("table"):
            continue
        excluded[(str(entry.get("system") or ""), str(entry["table"]))] = str(
            entry.get("reason") or ""
        )
    return excluded


def _is_catalogue_container(container: str) -> bool:
    """Does this workbook name claim to describe a schema rather than hold data?"""
    tokens = set(_normalise(container).split("_"))
    return bool(tokens & _CATALOGUE_CONTAINER_SUBJECTS) and bool(
        tokens & _CATALOGUE_CONTAINER_ASPECTS
    )


def _catalogue_evidence(
    system: str,
    table: str,
    columns: list[dict[str, Any]],
    other_tables: set[str],
) -> str:
    """Direct evidence that *table* describes a schema, or ``""``.

    Two independent proofs, both steep on purpose. A false positive here deletes a
    real business table from the pipeline before anyone sees it, which is strictly
    worse than leaving a metadata table in for a human to dispose of.
    """
    names = [str(c.get("name") or "") for c in columns]
    if not names:
        return ""
    hits = {n for n in (_normalise(x) for x in names) if n in _CATALOGUE_COLUMNS}
    if len(hits) >= _CATALOGUE_COLUMN_HITS and len(hits) >= _CATALOGUE_COLUMN_SHARE * len(names):
        return (
            f"{len(hits)} of {len(names)} columns are information-schema fields "
            f"({', '.join(sorted(hits)[:4])})"
        )
    if len(names) > _CATALOGUE_NARROW_COLUMNS:
        return ""
    for column in columns:
        sampled = {_normalise(s) for s in column.get("samples") or [] if str(s).strip()}
        sampled.discard("")
        matched = {s for s in sampled if s in other_tables or s.rsplit("_", 1)[-1] in other_tables}
        if (
            len(matched) >= _CATALOGUE_SAMPLE_MATCHES
            and len(matched) >= _CATALOGUE_SAMPLE_SHARE * len(sampled)
        ):
            return (
                f"column '{column.get('name')}' holds the names of {len(matched)} "
                f"other tables profiled in {system}"
            )
    return ""


def detect_schema_catalogue_tables(
    tables: list[tuple[str, str, list[dict[str, Any]]]],
    decided: dict[tuple[str, str], str] | None = None,
) -> list[dict[str, Any]]:
    """Tables that describe the source's own schema, to route out before anchoring.

    A table listing tables is not business data and cannot be anchored to a
    business concept, but it looks like an ordinary narrow lookup to the model: on
    the live run all four sheets of a "Qargo Tables Columns Info" workbook were
    anchored and assigned to the ``booking`` domain, and the sheet holding a
    sample extract of the real ``orders`` table went on to cause a 21-column
    duplicate-mapping refusal downstream.

    Flagged three ways, in decreasing directness:

    1. the table's own columns are dominated by information-schema fields;
    2. the table is narrow and one column's values are the names of other tables
       profiled in the same source system;
    3. the table is a sheet of a workbook whose *name* claims to describe a schema
       AND at least one sibling sheet was flagged by (1) or (2). This is what
       catches the sample-extract sheets, whose own columns look like business
       data — nothing about them is suspicious except the company they keep.

    Rule (3) never chains: a sheet flagged by (3) is not evidence for its
    siblings, so one proven catalogue sheet is required per workbook.

    Any table carrying a ledger disposition other than ``not-business-data`` is
    left alone — a heuristic does not overrule a recorded decision.

    Returns one entry per excluded table, each with the evidence that excluded it,
    for the caller to record and report. Nothing is dropped silently.
    """
    recorded = decided or {}
    names_by_system: dict[str, set[str]] = {}
    for system, table, _ in tables:
        names_by_system.setdefault(system, set()).add(_normalise(table))

    direct: dict[tuple[str, str], str] = {}
    for system, table, columns in tables:
        others = names_by_system.get(system, set()) - {_normalise(table)}
        evidence = _catalogue_evidence(system, table, columns, others)
        if evidence:
            direct[(system, table)] = evidence

    flagged = dict(direct)
    for system, table, _ in tables:
        if (system, table) in flagged:
            continue
        container, separator, sheet = str(table).partition(_SHEET_SEPARATOR)
        if not separator or not sheet or not _is_catalogue_container(container):
            continue
        siblings = sorted(
            key[1]
            for key in direct
            if key[0] == system and key[1].partition(_SHEET_SEPARATOR)[0] == container
        )
        if siblings:
            flagged[(system, table)] = (
                f"sheet of '{container}', shown to be a schema catalogue by "
                f"sibling sheet '{siblings[0]}'"
            )

    excluded: list[dict[str, Any]] = []
    for system, table, columns in tables:
        evidence = flagged.get((system, table))
        if not evidence:
            continue
        disposition = recorded.get((system, table), "")
        if disposition and disposition != "not-business-data":
            logger.info(
                "%s.%s looks like a schema catalogue (%s) but the ledger records "
                "'%s'; keeping it.",
                system,
                table,
                evidence,
                disposition,
            )
            continue
        excluded.append(
            {
                "system": system,
                "table": table,
                "columns": len(columns),
                "disposition": "not-business-data",
                "reason": evidence,
            }
        )
    return excluded


def build_anchor_prompt(
    chunk: list[tuple[str, str, list[str]]],
    catalog: ClassCatalog,
    n_classes: int,
    profile_legend: str = "",
) -> str:
    """One prompt: every table in *chunk* against the whole catalog.

    *profile_legend* is non-empty when the outline carries DD-189 profile
    annotations (``name[unique,id-like,fk?->…]``); it explains the tag
    vocabulary so the model weighs measured data facts over name impressions.
    """
    tables_text = "\n".join(
        f"TABLE {system}.{table} ({len(cols)} columns): {', '.join(cols)}"
        for system, table, cols in chunk
    )
    return f"""You are an expert ontologist. For EVERY source table below, decide which single
reference-model class the table's ROWS are instances of (its anchor). Also propose the
table's grain and natural key from its column names.
Rules:
- The anchor is what one row IS - not a class the table merely references.
- PREFER a class owned by a hub domain over an UNOWNED one when both genuinely fit;
  pick an UNOWNED class only when no owned class fits, and put near-miss owned
  classes in "alternate".
- Exact class names from the catalog; null if nothing fits. Do not skip any table.
- grain_columns: the column(s) that make one row unique. natural_key: the business
  key a target system would merge on. load_hint: "event-append" if rows are immutable
  occurrences, "scd" if rows are mutable master/transactional data.
- relationships: for each column that references another table's rows (prefer fk?->
  profile evidence, then matching key names), emit {{"to_table", "local_column",
  "evidence": "fk-inclusion"|"name"}}. Only tables in THIS estate. Empty array if none.
  A const or low-card column WITH fk?-> evidence is still a relationship (e.g. a tenant
  or status dimension FK) — record it, but NEVER use it as a grain or key member.
- secondary_entities: if the table embeds a DIFFERENT canonical entity at its OWN grain,
  emit {{"class": <catalog class name>, "grain_columns": [...], "columns": [...]}} per
  embedded entity. HARD RULE: the secondary entity's grain_columns must be DIFFERENT
  from the table's primary grain_columns and must identify the embedded entity itself
  (e.g. customer_id for an embedded customer on an orders table). A column cluster at
  the SAME grain as the primary (measures, addresses, descriptions of the primary row)
  is properties of the primary, NOT a secondary entity. Empty array if none.
- flags: any of ["unowned-anchor","extension-candidate","code-list","no-data-evidence",
  "versioned"] that apply; empty array if none. Also flag "extension-candidate" when the
  best anchor is a GENERIC class but the table's columns or name clearly indicate a
  consistent specialization the catalog lacks (e.g. a purchase_invoices table anchored
  to a generic Invoice: the purchase/sales split is real in the source but missing in
  the catalog).
{_PATTERN_RULES}
{profile_legend}
SOURCE TABLES ({len(chunk)}):
{tables_text}

REFERENCE CLASS CATALOG ({n_classes} classes):
{catalog.text}"""


def anchor_response_schema(keys: list[str]) -> dict[str, Any]:
    """Strict schema keyed by table, every key required (the DD-177 shape).

    Omitting a table is a schema violation, so "the model skipped it" cannot
    happen. Class names are free strings — 1,275 candidates exceed the provider's
    1,000-value enum budget (DD-177) — and are validated after the fact instead.
    """
    relationship = {
        "type": "object",
        "properties": {
            "to_table": {"type": "string"},
            "local_column": {"type": "string"},
            "evidence": {"type": "string", "enum": ["fk-inclusion", "name"]},
        },
        "required": ["to_table", "local_column", "evidence"],
        "additionalProperties": False,
    }
    secondary = {
        "type": "object",
        "properties": {
            "class": {"type": "string"},
            "grain_columns": {"type": "array", "items": {"type": "string"}},
            "columns": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["class", "grain_columns", "columns"],
        "additionalProperties": False,
    }
    verdict = {
        "type": "object",
        "properties": {
            "anchor": {"type": ["string", "null"]},
            "alternate": {"type": ["string", "null"]},
            "confidence": {"type": "number"},
            "grain_columns": {"type": "array", "items": {"type": "string"}},
            "natural_key": {"type": "array", "items": {"type": "string"}},
            "load_hint": {"type": ["string", "null"], "enum": ["event-append", "scd", None]},
            "relationships": {"type": "array", "items": relationship},
            "secondary_entities": {"type": "array", "items": secondary},
            "flags": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "anchor",
            "alternate",
            "confidence",
            "grain_columns",
            "natural_key",
            "load_hint",
            "relationships",
            "secondary_entities",
            "flags",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "table_anchors",
            "strict": True,
            "schema": {
                "$defs": {"Verdict": verdict},
                "type": "object",
                "properties": {
                    "anchors": {
                        "type": "object",
                        "properties": {k: {"$ref": "#/$defs/Verdict"} for k in keys},
                        "required": keys,
                        "additionalProperties": False,
                    }
                },
                "required": ["anchors"],
                "additionalProperties": False,
            },
        },
    }


def derive_domain(
    anchor_name: str,
    catalog: ClassCatalog,
    affinity_domain: str = "",
) -> tuple[str, str, list[str], list[str]]:
    """Return ``(domain, basis, owners, bridged_from)`` for an anchored table.

    Candidates are the domains that own the anchor's module plus the domains
    declaring a bridge to the anchor class (DD-181). Affinity's opinion is kept
    as a tie-break *within* the candidates — a useful prior, no longer a
    constraint. Bridge-awareness is what keeps ``stops`` in ``consignment``
    (which bridges to ``TransportCall``) instead of moving it to
    ``route-schedule`` (which owns it): moving a table to the class's owner
    trades an anchor gap for a grain error.

    An anchor whose module no domain owns keeps the affinity domain and is
    flagged ``unowned`` — the extension worklist, surfaced up front instead of
    discovered table by table (DD-180).

    Aggregated across *every* copy of the name: duplicate class names span
    modules, and deriving from one arbitrary copy put ``consignments`` in
    ``commercial`` on the live run.
    """
    copies = catalog.index.get(anchor_name) or []
    owner_ids = list(
        dict.fromkeys(
            dom for copy in copies for dom in catalog.owners.get(copy.get("module", ""), [])
        )
    )
    bridge_ids = list(
        dict.fromkeys(
            dom for copy in copies for dom in catalog.bridged_from.get(copy.get("uri", ""), [])
        )
    )
    candidates = list(dict.fromkeys([*owner_ids, *bridge_ids]))

    if affinity_domain and affinity_domain in candidates:
        basis = "owner+affinity" if affinity_domain in owner_ids else "bridge+affinity"
        return affinity_domain, basis, owner_ids, bridge_ids
    if owner_ids:
        return owner_ids[0], "owner", owner_ids, bridge_ids
    if bridge_ids:
        return bridge_ids[0], "bridge", owner_ids, bridge_ids
    return affinity_domain, "unowned", owner_ids, bridge_ids


def column_property_overlap(columns: list[str], copy: dict[str, Any]) -> int:
    """Distinct meaning-bearing words shared by a table's columns and a class's properties.

    Word overlap rather than name equality: measured on the live corpus, exact
    matching between snake_case source columns and ontology property names scored
    1 across 77 ``bookings`` columns against the *right* class and 0 against every
    other candidate — too sparse to break a tie. Word overlap separated the same
    candidates 5/2/0.
    """
    props = copy.get("properties") or ()
    if not props or not columns:
        return 0
    column_words: set[str] = set().union(*(_tokens(c) for c in columns))
    property_words: set[str] = set().union(*(_tokens(p) for p in props))
    return len(column_words & property_words)


def choose_class_copy(
    copies: list[dict[str, Any]],
    catalog: ClassCatalog,
    domain: str,
    columns: list[str],
) -> dict[str, Any]:
    """Pick which copy of a duplicate class name the anchor URI points at.

    Ownership decides the tier — a name match in a foreign vocabulary must not
    outrank the class the blueprint governs — and *within* the tier the copy whose
    properties actually overlap the table's columns wins, with the richer class
    breaking a remaining tie.

    That second key is the #519 fix. ``shipments`` (90 columns, 0.98 confidence)
    resolved to ``onerecord/cargo#Shipment``, which the closure gives zero
    properties, over ``dcsa/booking#Shipment``, which carries the 13 alignment
    then proposed. Both modules are owned by ``booking``, so the ownership tier
    could not separate them and the first copy the catalog read won. No proposed
    property survived against the anchor, and a large, clean entity produced no
    class at all.
    """
    if not copies:
        return {}
    owned_by_domain = [c for c in copies if domain in catalog.owners.get(c.get("module", ""), [])]
    owned = [c for c in copies if catalog.owners.get(c.get("module", ""))]
    tier = owned_by_domain or owned or list(copies)
    # max() keeps the first maximal element, so an all-zero tier preserves the
    # existing order and this stays a tie-break rather than a re-ranking.
    return max(
        tier,
        key=lambda c: (column_property_overlap(columns, c), len(c.get("properties") or ())),
    )


def load_affinity_domains(analysis_dir: Path) -> dict[tuple[str, str], str]:
    """Read ``(system, table) -> primary_domain`` from the affinity artifacts."""
    out: dict[tuple[str, str], str] = {}
    for path in sorted(Path(analysis_dir).glob("*-affinity.yaml")):
        _state, doc = _read_yaml_artifact(path, what="this affinity prior")
        system = str(doc.get("system") or path.stem.removesuffix("-affinity"))
        for table in doc.get("tables") or []:
            if isinstance(table, dict) and table.get("table"):
                out[(system, str(table["table"]))] = str(table.get("domain") or "")
    return out


def run_anchor_tables(
    *,
    client: Any,
    model: str,
    sources_dir: Path,
    catalog_path: Path,
    ref_models_dir: Path | None,
    accelerator: str | None,
    analysis_dir: Path,
    report=None,
    screen_schema_catalogues: bool = True,
) -> Path:
    """Run the global anchor call(s) and write ``table-anchors.yaml``.

    Tables that describe the source's own schema are screened out first and
    recorded under ``excluded`` with the evidence that excluded them; anchored
    tables carry ``anchor_properties`` and ``anchor_column_overlap``, and one with
    no properties in the closure carries a ``warning`` and is reported (#519).

    Set *screen_schema_catalogues* false to anchor every profiled table. The screen
    is a heuristic and a false positive drops a real business table out of the
    pipeline, so there has to be a way to say "no, that one is real" without
    waiting for a code change; the durable answer is a table-grain ledger entry
    (``source-disposition set --table ... --disposition deferred``), which the
    screen already respects.
    """
    say = report or (lambda *_a, **_k: None)
    catalog = build_class_catalog(catalog_path, ref_models_dir, accelerator)
    excluded = load_excluded_columns(analysis_dir)
    if excluded:
        say(f"  ⚓ {len(excluded)} column exclusion(s) from the disposition ledger")

    source_tables = read_source_tables(sources_dir)
    catalogue = (
        detect_schema_catalogue_tables(source_tables, load_table_dispositions(analysis_dir))
        if screen_schema_catalogues
        else []
    )
    if not screen_schema_catalogues:
        say("  ⚓ Schema-catalogue screen disabled — every profiled table is anchored")
    skip = {(e["system"], e["table"]) for e in catalogue}
    if catalogue:
        say(
            f"  ⚓ {len(catalogue)} schema-catalogue table(s) routed to "
            "not-business-data before anchoring (they describe the source's own "
            "schema, not its business):"
        )
        for entry in catalogue:
            say(f"       {entry['system']}.{entry['table']} — {entry['reason']}")
        say(
            "       recorded under 'excluded' in table-anchors.yaml and honoured by "
            "the disposition-conflict check; if one of these is real business data, "
            "re-run with --no-schema-catalogue-screen or record a table-grain "
            "disposition for it"
        )
    outline = build_source_outline(
        sources_dir,
        excluded_columns=excluded,
        tables=[t for t in source_tables if (t[0], t[1]) not in skip],
    )
    # DD-190 sticky sheet semantics: a human-confirmed/edited entry whose
    # source schema is unchanged is PINNED — preserved verbatim and excluded
    # from the model call (true delta mode). A pinned entry whose schema
    # changed releases its pin: the old values are kept under `previous`, the
    # fresh proposal is recorded, and status becomes `stale-confirmed` so it
    # re-enters review. Stickiness is bounded by evidence identity, never by
    # table name alone.
    existing = load_table_anchors(analysis_dir)
    hashes = {(s, t): sheet_schema_hash(cols) for s, t, cols in outline}
    pinned: dict[tuple[str, str], dict[str, Any]] = {}
    stale_prev: dict[tuple[str, str], dict[str, Any]] = {}
    for key, old in existing.items():
        if str(old.get("status") or "") not in SHEET_PINNED_STATUSES:
            continue
        if key not in hashes:
            continue  # table gone from the estate; entry simply ages out
        if old.get("schema_hash") == hashes[key]:
            pinned[key] = old
        else:
            stale_prev[key] = old
    estate_keys = {f"{s}.{t}" for s, t, _ in outline}
    call_outline = [item for item in outline if (item[0], item[1]) not in pinned]
    if pinned:
        say(
            f"  ⚓ {len(pinned)} confirmed sheet entr{'y' if len(pinned) == 1 else 'ies'} "
            "pinned (schema unchanged) — excluded from the model call"
        )
    if stale_prev:
        say(
            f"  ⚓ {len(stale_prev)} confirmed entr{'y' if len(stale_prev) == 1 else 'ies'} "
            "have a CHANGED schema — pin released, re-proposed as stale-confirmed"
        )

    # DD-189: annotate with deterministic profile tags where a profile
    # artifact exists. Additive evidence — systems without a profile pass
    # through untouched, and empty-column omission applies only under a
    # declared production-maturity profile. The annotated outline feeds the
    # PROMPT only; anchor resolution below keeps the raw column names, so
    # tag text never pollutes `column_property_overlap` word matching.
    from .profile_sources import PROFILE_LEGEND, annotate_outline

    prompt_outline, profiled = annotate_outline(call_outline, sources_dir, report=say)
    profile_legend = PROFILE_LEGEND if profiled else ""
    if profiled:
        say("  ⚓ Profile annotations applied to the anchoring outline (DD-189)")
    affinity = load_affinity_domains(analysis_dir)
    n_classes = catalog.text.count("\n") + 1 if catalog.text else 0
    say(f"  ⚓ Anchoring {len(call_outline)} table(s) against {n_classes} class(es)")

    session = new_session_id("anchor")
    raw: dict[str, dict[str, Any]] = {}
    for start in range(0, len(call_outline), MAX_TABLES_PER_ANCHOR_CALL):
        chunk = prompt_outline[start : start + MAX_TABLES_PER_ANCHOR_CALL]
        keys = [f"{s}.{t}" for s, t, _ in chunk]
        response = create_chat_completion(
            client,
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": build_anchor_prompt(
                        chunk, catalog, n_classes, profile_legend=profile_legend
                    ),
                }
            ],
            seed=resolve_ai_seed(ROLE_ALIGNMENT),
            reasoning_effort=resolve_reasoning_effort(ROLE_ALIGNMENT),
            response_format=anchor_response_schema(keys),
            param_fallbacks={"response_format": {"type": "json_object"}},
            trace_name="anchor-tables",
            trace_metadata=call_metadata(
                session, "anchoring", tables=len(chunk), classes=n_classes
            ),
        )
        raw.update(json.loads(response.choices[0].message.content or "{}").get("anchors") or {})

    tables: list[dict[str, Any]] = []
    unanchored: list[dict[str, Any]] = []
    propertyless: list[dict[str, Any]] = []
    invented = 0
    dropped_rels = dropped_secondary = 0
    for system, table, cols in outline:
        key = (system, table)
        if key in pinned:
            tables.append(pinned[key])
            continue
        verdict = raw.get(f"{system}.{table}") or {}
        anchor = verdict.get("anchor")
        note = ""
        if anchor and anchor not in catalog.index:
            # Never silently keep an invented name: null it, keep the evidence.
            invented += 1
            note = f"model proposed unknown class '{anchor}'"
            anchor = None
        if not anchor:
            if key in stale_prev:
                # The confirmed values survive the failed re-proposal; only the
                # pin is released. A human decision never silently evaporates.
                entry = dict(stale_prev[key])
                entry["status"] = "stale-confirmed"
                entry["schema_hash"] = hashes[key]
                entry["note"] = (
                    "schema changed and the re-proposal produced no anchor; "
                    "previous confirmed values kept for review"
                )
                tables.append(entry)
                continue
            unanchored.append(
                {"system": system, "table": table, "columns": len(cols), "note": note}
            )
            continue
        domain, basis, owner_ids, bridge_ids = derive_domain(
            anchor, catalog, affinity.get((system, table), "")
        )
        # Among duplicate copies of the name, ownership picks the tier and
        # column/property overlap picks within it (#519).
        chosen = choose_class_copy(catalog.index[anchor], catalog, domain, cols)
        n_properties = len(chosen.get("properties") or ())
        entry = {
            "system": system,
            "table": table,
            "columns": len(cols),
            "anchor": anchor,
            "anchor_uri": chosen["uri"],
            "anchor_properties": n_properties,
            "anchor_column_overlap": column_property_overlap(cols, chosen),
            "alternate": verdict.get("alternate"),
            "confidence": round(float(verdict.get("confidence") or 0.0), 3),
            "domain": domain,
            "domain_basis": basis,
            "owners": owner_ids,
            "bridged_from": bridge_ids,
            "grain_columns": list(verdict.get("grain_columns") or []),
            "natural_key": list(verdict.get("natural_key") or []),
            "load_hint": verdict.get("load_hint"),
            "schema_hash": hashes[key],
            "status": "proposed",
        }
        # DD-190 sheet outputs, validated deterministically — the model
        # proposes, the estate/catalog decide what is even representable.
        col_set = set(cols)
        relationships = []
        for rel in verdict.get("relationships") or []:
            if (
                isinstance(rel, dict)
                and rel.get("to_table") in estate_keys
                and rel.get("to_table") != f"{system}.{table}"
                and rel.get("local_column") in col_set
            ):
                relationships.append(
                    {
                        "to_table": rel["to_table"],
                        "local_column": rel["local_column"],
                        "evidence": rel.get("evidence") or "name",
                    }
                )
            else:
                dropped_rels += 1
        grain_set = set(entry["grain_columns"])
        secondary = []
        for sec in verdict.get("secondary_entities") or []:
            sec_grain = list((sec or {}).get("grain_columns") or [])
            if (
                isinstance(sec, dict)
                and sec.get("class") in catalog.index
                and sec_grain
                and set(sec_grain) != grain_set
                and set(sec_grain) <= col_set
            ):
                secondary.append(
                    {
                        "class": sec["class"],
                        "grain_columns": sec_grain,
                        "columns": [c for c in sec.get("columns") or [] if c in col_set],
                    }
                )
            else:
                # Same-grain clusters are properties of the primary, invented
                # classes are not representable — both dropped, both counted.
                dropped_secondary += 1
        entry["relationships"] = relationships
        entry["secondary_entities"] = secondary
        entry["flags"] = sorted(set(verdict.get("flags") or []) & ALLOWED_SHEET_FLAGS)
        if key in stale_prev:
            entry["status"] = "stale-confirmed"
            prev = stale_prev[key]
            entry["previous"] = {
                f: prev.get(f)
                for f in ("anchor", "anchor_uri", "domain", "grain_columns",
                          "natural_key", "status", "schema_hash")
            }
        if cols and not n_properties:
            entry["warning"] = (
                f"{chosen['uri']} has no properties in the resolved closure, so no "
                f"column of this {len(cols)}-column table can map to it"
            )
            propertyless.append(entry)
        tables.append(entry)

    unowned = sum(1 for t in tables if t.get("domain_basis") == "unowned")
    say(
        f"  ⚓ Anchored {len(tables)}/{len(outline)} — "
        f"{unowned} on unowned classes (blueprint gaps), "
        f"{len(unanchored)} unanchored, {invented} invented name(s) rejected"
    )
    if dropped_rels or dropped_secondary:
        say(
            f"  ⚓ Sheet validation dropped {dropped_rels} relationship(s) "
            "(unknown table / self / non-column) and "
            f"{dropped_secondary} secondary entit{'y' if dropped_secondary == 1 else 'ies'} "
            "(invented class or same-grain-as-primary)"
        )
    if propertyless:
        # Almost never right for a table with columns: alignment has nothing to
        # propose against the anchor, so the entity is lost rather than mismapped.
        say(
            f"  ⚓ WARNING: {len(propertyless)} anchor(s) resolve to a class with NO "
            "properties in the closure — alignment cannot map any column to them:"
        )
        for t in propertyless:
            say(f"       {t['system']}.{t['table']} ({t['columns']} cols) → {t['anchor_uri']}")
            logger.warning(
                "Anchor %s for %s.%s has no properties in the resolved closure.",
                t["anchor_uri"],
                t["system"],
                t["table"],
            )

    payload = {
        # v2 (DD-190): entries carry schema_hash, status, relationships,
        # secondary_entities, flags; pinned entries survive re-runs verbatim.
        "schema_version": 2,
        "generated_by": "anchor-tables",
        "table_count": len(outline),
        "tables": tables,
        "unanchored": unanchored,
        "excluded": catalogue,
    }
    header = provenance_comment(
        "anchor-tables",
        extra=ai_attribution(
            model=model,
            role="anchoring",
            seed=resolve_ai_seed(ROLE_ALIGNMENT),
            reasoning_effort=resolve_reasoning_effort(ROLE_ALIGNMENT),
        ),
        ai_generated=True,
    )
    out_path = Path(analysis_dir) / ANCHORS_FILENAME
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        header + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    flush_tracing()
    return out_path


def regroup_by_anchor(
    domain_tables: dict[str, list[dict[str, Any]]],
    anchors: dict[tuple[str, str], dict[str, Any]],
    domain_uris_by_id: dict[str, list[str]],
    *,
    floor: float = ANCHOR_CONFIDENCE_FLOOR,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
    """Move tables to their anchor-derived domain before alignment (DD-185).

    This is the half of the inversion that makes affinity *derived*: without it,
    a table affinity misplaced is aligned inside the wrong domain's class pool
    and its (correct) anchor is merely reported as outside that pool. Observed
    live: fresh affinity moved ``stops`` from consignment to events between two
    runs, and events cannot see ``TransportCall`` — the exact table the anchor
    stage fixed was the one the old grouping still broke.

    Conservative by construction: a table moves only when its anchor clears the
    confidence floor, derives a real domain, and that domain's module URIs are
    known (no URIs would mean an empty class pool — strictly worse than the
    wrong one). Everything else stays where affinity put it. Returns the new
    grouping and the moves, each ``{system, table, from, to, anchor}``.
    """
    regrouped: dict[str, list[dict[str, Any]]] = {}
    moves: list[dict[str, str]] = []
    for current_domain, tables in domain_tables.items():
        for entry in tables:
            key = (str(entry.get("system") or ""), str(entry.get("table") or ""))
            anchor = anchors.get(key) or {}
            target = str(anchor.get("domain") or "")
            if (
                target
                and target != current_domain
                and float(anchor.get("confidence") or 0.0) >= floor
                and domain_uris_by_id.get(target)
            ):
                moved = dict(entry)
                moved["domain_uris"] = list(domain_uris_by_id[target])
                regrouped.setdefault(target, []).append(moved)
                moves.append(
                    {
                        "system": key[0],
                        "table": key[1],
                        "from": current_domain,
                        "to": target,
                        "anchor": str(anchor.get("anchor") or ""),
                    }
                )
            else:
                regrouped.setdefault(current_domain, []).append(entry)
    return regrouped, moves


def load_table_anchors(analysis_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Read the anchors artifact, keyed ``(system, table)``. Empty when absent."""
    path = Path(analysis_dir) / ANCHORS_FILENAME
    _state, doc = _read_yaml_artifact(path, what="global anchors")
    return {
        (str(t.get("system") or ""), str(t.get("table") or "")): t
        for t in doc.get("tables") or []
        if isinstance(t, dict)
    }
