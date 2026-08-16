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
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
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


@dataclass
class ClassCatalog:
    """The one-line-per-class view of every reference class the hub can resolve."""

    text: str
    #: name -> every copy of that name: [{"module": str, "uri": str}, ...].
    #: A list, deliberately: the same class name exists in several modules
    #: (``Consignment`` in bsp/commercial AND mmt/consignment), and keeping one
    #: arbitrary copy derived ownership from the wrong module on the live run.
    index: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    #: module uri (no trailing #) -> owning domain ids
    owners: dict[str, list[str]] = field(default_factory=dict)
    #: class uri -> domain ids declaring a bridge TO that class
    bridged_from: dict[str, list[str]] = field(default_factory=dict)


def _first_sentence(text: str) -> str:
    return (text or "").replace("\n", " ").split(". ")[0][:130]


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

    index: dict[str, list[dict[str, str]]] = {}
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
    path = Path(analysis_dir) / "table-dispositions.yaml"
    if not path.is_file():
        return set()
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - advisory input
        return set()
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


def build_source_outline(
    sources_dir: Path,
    excluded_columns: set[tuple[str, str, str]] | None = None,
) -> list[tuple[str, str, list[str]]]:
    """Return ``(system, table, column_names)`` for every source table.

    Column *names only* — no sample values. Tested: samples cost accuracy here
    (5/6 vs 6/6) and ~7k tokens. Anchoring reads the grain from the schema;
    values are stage-2 evidence for column mapping.

    Columns in *excluded_columns* are left out entirely, so the model cannot
    build a grain or key on a column the hub has ruled non-business — a SaaS
    tenant id looks exactly like a composite-key member until someone says
    otherwise, and on the live run the model keyed every qargo table on it.
    """
    excluded = excluded_columns or set()
    outline: list[tuple[str, str, list[str]]] = []
    for vocab_file in sorted(Path(sources_dir).glob("*/vocabulary/*.vocabulary.ttl")):
        system = vocab_file.parts[-3]
        for table, columns in sorted(parse_source_vocabulary(vocab_file).items()):
            names = [
                str(c.get("name", ""))
                for c in columns
                if not _is_excluded(excluded, system, table, str(c.get("name", "")))
            ]
            outline.append((system, table, names))
    return outline


def build_anchor_prompt(
    chunk: list[tuple[str, str, list[str]]],
    catalog: ClassCatalog,
    n_classes: int,
) -> str:
    """One prompt: every table in *chunk* against the whole catalog."""
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
{_PATTERN_RULES}
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
    verdict = {
        "type": "object",
        "properties": {
            "anchor": {"type": ["string", "null"]},
            "alternate": {"type": ["string", "null"]},
            "confidence": {"type": "number"},
            "grain_columns": {"type": "array", "items": {"type": "string"}},
            "natural_key": {"type": "array", "items": {"type": "string"}},
            "load_hint": {"type": ["string", "null"], "enum": ["event-append", "scd", None]},
        },
        "required": [
            "anchor",
            "alternate",
            "confidence",
            "grain_columns",
            "natural_key",
            "load_hint",
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


def load_affinity_domains(analysis_dir: Path) -> dict[tuple[str, str], str]:
    """Read ``(system, table) -> primary_domain`` from the affinity artifacts."""
    out: dict[tuple[str, str], str] = {}
    for path in sorted(Path(analysis_dir).glob("*-affinity.yaml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 - advisory prior only
            continue
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
) -> Path:
    """Run the global anchor call(s) and write ``table-anchors.yaml``."""
    say = report or (lambda *_a, **_k: None)
    catalog = build_class_catalog(catalog_path, ref_models_dir, accelerator)
    excluded = load_excluded_columns(analysis_dir)
    if excluded:
        say(f"  ⚓ {len(excluded)} column exclusion(s) from the disposition ledger")
    outline = build_source_outline(sources_dir, excluded_columns=excluded)
    affinity = load_affinity_domains(analysis_dir)
    n_classes = catalog.text.count("\n") + 1 if catalog.text else 0
    say(f"  ⚓ Anchoring {len(outline)} table(s) against {n_classes} class(es)")

    session = new_session_id("anchor")
    raw: dict[str, dict[str, Any]] = {}
    for start in range(0, len(outline), MAX_TABLES_PER_ANCHOR_CALL):
        chunk = outline[start : start + MAX_TABLES_PER_ANCHOR_CALL]
        keys = [f"{s}.{t}" for s, t, _ in chunk]
        response = create_chat_completion(
            client,
            model=model,
            messages=[{"role": "user", "content": build_anchor_prompt(chunk, catalog, n_classes)}],
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
    invented = 0
    for system, table, cols in outline:
        verdict = raw.get(f"{system}.{table}") or {}
        anchor = verdict.get("anchor")
        note = ""
        if anchor and anchor not in catalog.index:
            # Never silently keep an invented name: null it, keep the evidence.
            invented += 1
            note = f"model proposed unknown class '{anchor}'"
            anchor = None
        if not anchor:
            unanchored.append(
                {"system": system, "table": table, "columns": len(cols), "note": note}
            )
            continue
        domain, basis, owner_ids, bridge_ids = derive_domain(
            anchor, catalog, affinity.get((system, table), "")
        )
        # Among duplicate copies of the name, record the URI whose module the
        # chosen domain owns; else the first owned copy; else the first.
        copies = catalog.index[anchor]
        chosen = next(
            (c for c in copies if domain in catalog.owners.get(c["module"], [])),
            next((c for c in copies if catalog.owners.get(c["module"])), copies[0]),
        )
        tables.append(
            {
                "system": system,
                "table": table,
                "columns": len(cols),
                "anchor": anchor,
                "anchor_uri": chosen["uri"],
                "alternate": verdict.get("alternate"),
                "confidence": round(float(verdict.get("confidence") or 0.0), 3),
                "domain": domain,
                "domain_basis": basis,
                "owners": owner_ids,
                "bridged_from": bridge_ids,
                "grain_columns": list(verdict.get("grain_columns") or []),
                "natural_key": list(verdict.get("natural_key") or []),
                "load_hint": verdict.get("load_hint"),
            }
        )

    unowned = sum(1 for t in tables if t["domain_basis"] == "unowned")
    say(
        f"  ⚓ Anchored {len(tables)}/{len(outline)} — "
        f"{unowned} on unowned classes (blueprint gaps), "
        f"{len(unanchored)} unanchored, {invented} invented name(s) rejected"
    )

    payload = {
        "schema_version": 1,
        "generated_by": "anchor-tables",
        "table_count": len(outline),
        "tables": tables,
        "unanchored": unanchored,
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
    if not path.is_file():
        return {}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - a broken artifact must not fail alignment
        logger.warning("Could not parse %s; ignoring global anchors.", path)
        return {}
    return {
        (str(t.get("system") or ""), str(t.get("table") or "")): t
        for t in doc.get("tables") or []
        if isinstance(t, dict)
    }
