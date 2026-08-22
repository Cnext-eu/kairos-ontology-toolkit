# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Cross-domain alignment coverage, with a reason code per unmapped column (DD-168).

``propose-alignment`` already records, per table, which columns aligned to a
reference-model property and which fell through to ``custom_columns`` — with a rationale
and a recommended disposition on each. It records it *per domain file*, though, so the
question a reviewer actually asks has no answer anywhere: **across the whole hub, which
real business signal is still not represented in the domain model?**

Counting unmapped columns is not that answer. Most unmapped columns *should* be
unmapped: a ``created_at`` audit stamp, a ``Column7`` vendor placeholder, an all-null
field. Reporting 1,400 unmapped columns is as unhelpful as reporting none, because it
buries the fifty that matter. So every unmapped column is bucketed by *why*, and only
one bucket is a gap in the domain model:

* :data:`REASON_OPERATIONAL` — audit/system column. Correctly unmapped.
* :data:`REASON_VENDOR_SLOT` — generic placeholder (``Column7``). Correctly unmapped.
* :data:`REASON_NO_EVIDENCE` — no sample values, so nothing could be judged.
* :data:`REASON_LOW_CONFIDENCE` — a property was suggested but not trusted.
* :data:`REASON_NO_REFERENCE_PROPERTY` — **the gap.** Real, populated business data that
  the reference model has no home for. These are the columns that force a decision:
  extend the hub locally, register the concept (DD-164), or file a blueprint gap.

Classification reuses ``propose_alignment``'s own operational/vendor-slot predicates
rather than a bespoke list, so a column this report calls operational is the same one
the aligner declined to map for that reason.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ._cache import compute_entry_hash
from ._provenance import ai_attribution_note
from .ai_provider import ROLE_ALIGNMENT

SCHEMA_VERSION = 1

REASON_OPERATIONAL = "operational"
REASON_VENDOR_SLOT = "vendor-slot"
REASON_NO_EVIDENCE = "no-sample-evidence"
REASON_LOW_CONFIDENCE = "low-confidence-suggestion"
REASON_NO_REFERENCE_PROPERTY = "no-reference-property"

#: Ordered worst-last so a report reads from "needs a decision" down to "expected".
REASON_ORDER: tuple[str, ...] = (
    REASON_NO_REFERENCE_PROPERTY,
    REASON_LOW_CONFIDENCE,
    REASON_NO_EVIDENCE,
    REASON_VENDOR_SLOT,
    REASON_OPERATIONAL,
)

#: Human-facing explanation and the action each bucket implies.
REASON_GUIDANCE: dict[str, str] = {
    REASON_NO_REFERENCE_PROPERTY: (
        "Real business data with no reference-model property. Close the gap: model it "
        "in the owning domain, register it with 'register-concept', or record it as a "
        "blueprint-gap disposition."
    ),
    REASON_LOW_CONFIDENCE: (
        "A property was suggested but not trusted. Cheapest to review by hand — the "
        "candidate is already named."
    ),
    REASON_NO_EVIDENCE: (
        "No sample values, so neither the model nor a human can judge it. Re-import "
        "with samples, or accept that the column carries no observable signal."
    ),
    REASON_VENDOR_SLOT: (
        "Generic vendor placeholder (Column1, Field3). Carry to Silver as a "
        "passthrough; there is nothing canonical to map."
    ),
    REASON_OPERATIONAL: ("Audit/system column (created, updated, guid, hash). Correctly unmapped."),
}

#: Buckets that represent a genuine hole in the domain model.
GAP_REASONS: frozenset[str] = frozenset({REASON_NO_REFERENCE_PROPERTY, REASON_LOW_CONFIDENCE})


@dataclass(frozen=True)
class UnmappedColumn:
    system: str
    table: str
    column: str
    data_type: str
    reason: str
    suggestion: str = ""
    recommended_disposition: str = ""
    #: DD-186: the domain this column's table was aligned in. A disposition
    #: decision is domain-scoped — the same column name can be a modelled fact in
    #: one domain and a gap in another — so grouping must not cross the boundary.
    domain: str = ""
    #: DD-170 hub-local property the aligner proposes for this column, when it could
    #: state one. Never a reference IRI — the hub mints that at design time.
    proposal: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "table": self.table,
            "column": self.column,
            "data_type": self.data_type,
            "reason": self.reason,
            "suggestion": self.suggestion,
            "recommended_disposition": self.recommended_disposition,
            "proposed_local_property": self.proposal or None,
        }


#: Anchor statuses that mean the table has no reference class (DD-180).
#:
#: ``unmatched`` is the model declining to force-fit: it was shown every class the
#: domain imports and said none of them is what this table is. ``rejected`` is the
#: model naming a class that does not exist, with no valid fallback. Both leave the
#: table with no frame.
UNANCHORED_STATUSES: frozenset[str] = frozenset({"unmatched", "rejected"})


@dataclass(frozen=True)
class UnanchoredTable:
    """A source table alignment could not attach to any reference class (DD-180).

    The anchor is the frame for everything else. Step 1 of alignment decides which
    class the *table* is; step 2 maps its columns to properties of that class. With
    no anchor, step 2 is choosing from the whole pool with nothing to constrain it,
    which is measurably where the output stops being reproducible: on the live
    corpus, anchored tables held 60-67% run-to-run stability and unanchored ones
    30-44%, swinging between 26 and 8 mapped columns for the same input.
    """

    domain: str
    system: str
    table: str
    columns: int
    status: str
    likely_entity: str = ""
    rejected_class: str = ""
    #: Classes elsewhere in the reference models that plausibly fit this table,
    #: as ``(class_name, module_uri, importing_domain)``. Empty when nothing matched.
    candidates: tuple[tuple[str, str, str], ...] = ()

    @property
    def has_candidate_elsewhere(self) -> bool:
        """True when the class this table needs exists but the domain cannot see it."""
        return bool(self.candidates)


@dataclass
class DomainCoverage:
    domain: str
    tables: int = 0
    columns: int = 0
    mapped: int = 0
    by_alignment: dict[str, int] = field(default_factory=dict)
    unmapped: list[UnmappedColumn] = field(default_factory=list)
    unanchored: list[UnanchoredTable] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return round(self.mapped / self.columns, 4) if self.columns else 1.0

    def reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for column in self.unmapped:
            counts[column.reason] = counts.get(column.reason, 0) + 1
        return counts

    @property
    def gap_columns(self) -> list[UnmappedColumn]:
        return [c for c in self.unmapped if c.reason in GAP_REASONS]


@dataclass
class AlignmentReport:
    schema_version: int = SCHEMA_VERSION
    domains: list[DomainCoverage] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)

    @property
    def columns(self) -> int:
        return sum(d.columns for d in self.domains)

    @property
    def mapped(self) -> int:
        return sum(d.mapped for d in self.domains)

    @property
    def coverage(self) -> float:
        return round(self.mapped / self.columns, 4) if self.columns else 1.0

    def reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for domain in self.domains:
            for reason, count in domain.reason_counts().items():
                counts[reason] = counts.get(reason, 0) + count
        return counts

    @property
    def unanchored(self) -> list[UnanchoredTable]:
        """Every table with no reference class, worst (widest) first."""
        tables = [t for d in self.domains for t in d.unanchored]
        return sorted(tables, key=lambda t: (-t.columns, t.domain, t.table))

    @property
    def unanchored_columns(self) -> int:
        """Columns sitting under an unanchored table — the size of the blind spot."""
        return sum(t.columns for t in self.unanchored)

    @property
    def gap_columns(self) -> list[UnmappedColumn]:
        return [c for d in self.domains for c in d.gap_columns]

    def gaps_by_table(self) -> list[tuple[str, int]]:
        """Tables ranked by how much unmapped real signal they hold."""
        counts: dict[str, int] = {}
        for column in self.gap_columns:
            key = f"{column.system}.{column.table}"
            counts[key] = counts.get(key, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "totals": {
                "domains": len(self.domains),
                "columns": self.columns,
                "mapped": self.mapped,
                "unmapped": self.columns - self.mapped,
                "coverage": self.coverage,
                "gap_columns": len(self.gap_columns),
            },
            "by_reason": self.reason_counts(),
            "domains": [
                {
                    "domain": d.domain,
                    "tables": d.tables,
                    "columns": d.columns,
                    "mapped": d.mapped,
                    "coverage": d.coverage,
                    "by_alignment": d.by_alignment,
                    "by_reason": d.reason_counts(),
                }
                for d in self.domains
            ],
            "gap_columns": [c.to_dict() for c in self.gap_columns],
            "notices": list(self.notices),
        }


#: Positional placeholder names: ``Column7``, ``Field12``, ``col_3``, ``unnamed_4``.
#:
#: Broader than ``propose_alignment.is_generic_vendor_slot``, which matches only
#: ``cf``-prefixed vendor custom-field slots (``cf1``, ``cfx12``). That predicate does
#: not cover the shape a real hub actually produced — a CWEB checklist export whose
#: columns are literally ``Column2`` through ``Column18``. Left un-detected they land in
#: the ``no-reference-property`` bucket and read as unmapped business signal, which is
#: precisely the noise this report exists to remove.
#:
#: Kept local rather than widening the shared predicate: that one also drives
#: ``recommend_disposition`` inside the aligner, and broadening it would change mapping
#: behaviour as a side effect of adding a report.
_POSITIONAL_PLACEHOLDER_RE = re.compile(
    r"^(?:column|col|field|fld|unnamed|untitled)[\s_-]*\d+$", re.IGNORECASE
)


def classify_unmapped(
    entry: dict[str, Any], column_name: str, *, has_samples: bool | None = None
) -> str:
    """Return the reason code for one unmapped column.

    Order matters: a column can be both operational and evidence-free, and the
    operational answer is the more useful one because it needs no action.

    *has_samples* must come from the **source vocabulary**, not from *entry*. A
    ``custom_columns`` record carries no ``example_values`` key at all, so inferring
    "no evidence" from its absence marks every unmapped column evidence-free and empties
    the gap bucket entirely — a report that says "0 gaps" because it cannot see any.
    ``None`` means the source was not consulted, in which case the default is the gap:
    the column reached ``custom_columns`` precisely because the aligner assessed it and
    found no property, and silence about evidence is not evidence of silence.
    """
    from .propose_alignment import _is_operational_column, is_generic_vendor_slot

    if _is_operational_column(column_name) or (entry.get("recommended_disposition") == "skip"):
        return REASON_OPERATIONAL
    if is_generic_vendor_slot(column_name) or _POSITIONAL_PLACEHOLDER_RE.match(
        (column_name or "").strip()
    ):
        return REASON_VENDOR_SLOT
    if entry.get("suggested_property"):
        return REASON_LOW_CONFIDENCE
    if has_samples is False:
        return REASON_NO_EVIDENCE
    return REASON_NO_REFERENCE_PROPERTY


def source_sample_presence(hub_root: Path) -> dict[tuple[str, str, str], bool]:
    """Map ``(system, table, column)`` -> whether the source captured any sample value.

    Read from ``integration/sources/<system>/<table>.yaml``, which is where the evidence
    actually lives; the alignment files do not carry it for unmapped columns.
    """
    import yaml

    presence: dict[tuple[str, str, str], bool] = {}
    sources = Path(hub_root) / "integration" / "sources"
    if not sources.is_dir():
        return presence
    for system_dir in sorted(sources.iterdir()):
        if not system_dir.is_dir() or system_dir.name.startswith((".", "_")):
            continue
        for path in sorted(system_dir.glob("*.yaml")):
            if path.name.endswith(".samples.yaml") or path.name == "_manifest.yaml":
                continue
            try:
                document = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception:  # defensive: a broken source file must not skew the report
                continue
            if not isinstance(document, dict):
                continue
            table = str(document.get("name") or path.stem)
            for column in document.get("columns") or ():
                if not isinstance(column, dict):
                    continue
                presence[(system_dir.name, table, str(column.get("name") or ""))] = bool(
                    column.get("samples")
                )
    return presence


#: Sidecar cache file name (under ``<hub>/.cache/``) for the resolved reference-class
#: index. One entry only: the key covers every input, so a superseded entry is dead.
_REFERENCE_INDEX_CACHE = "reference-index"


def _hub_catalog_path(hub_root: Path) -> Path | None:
    """Locate the hub catalog the reference corpus resolves through."""
    catalog = Path(hub_root) / "ontology-hub" / "catalog-v001.xml"
    if catalog.exists():
        return catalog
    catalog = Path(hub_root) / "catalog-v001.xml"
    return catalog if catalog.exists() else None


def _reference_corpus_fingerprint(catalog_path: Path) -> str | None:
    """Fingerprint the *effective* reference corpus, or ``None`` if it cannot be read.

    Deliberately not the reference-models distribution version. The corpus is not a
    function of the wheel: a hub can point ``<uri>`` entries at its own TTLs (anything
    resolving outside ``<hub>/model/ontologies/`` counts as reference material, see
    ``class_anchoring._is_reference``), chain further catalogs with ``<nextCatalog>``,
    add ``rewriteURI`` rules, or replace the corpus wholesale via
    ``KAIROS_REFMODELS_ROOT``. A version-keyed cache would serve a stale index in every
    one of those cases.

    So the key is content: every catalog mapping with its target's ``(path, mtime, size)``,
    the rewrite rules, the env override, and the distribution version as a backstop.
    Building the resolver parses XML only -- negligible against the Turtle parse this
    exists to avoid.
    """
    try:
        from .catalog_utils import CatalogResolver

        resolver = CatalogResolver.with_reference_models(Path(catalog_path))
    except Exception:  # defensive: a broken catalog must not fail the report
        return None

    stamped: list[list[Any]] = []
    for uri, target in sorted(resolver.mappings.items()):
        try:
            stat = Path(target).stat()
            stamped.append([uri, str(target), stat.st_mtime_ns, stat.st_size])
        except OSError:  # a dangling entry is itself part of the state
            stamped.append([uri, str(target), None, None])

    try:
        from importlib.metadata import version as _distribution_version

        refmodels_version = _distribution_version("kairos-ontology-referencemodels")
    except Exception:
        refmodels_version = ""

    return compute_entry_hash(
        {
            "mappings": stamped,
            "rewrites": sorted(
                [str(prefix), str(replacement), str(base)]
                for prefix, replacement, base in getattr(resolver, "_rewrite_rules", ())
            ),
            "refmodels_root": os.environ.get("KAIROS_REFMODELS_ROOT", ""),
            "refmodels_version": refmodels_version,
        }
    )


def _reference_class_modules(hub_root: Path) -> dict[str, str]:
    """Map every reference-model class name to the module URI that declares it.

    Cached on disk under ``<hub>/.cache/`` (#598). Resolving this walks the whole
    reference corpus -- ~17s on a 14-domain hub, and identical for every domain -- so
    the in-process memo on :func:`build_alignment_report` removes repeats within one
    command but every fresh process still paid it.

    **The cache is read by every command but written only by ``--emit``.** DD-133
    Decision 2 is explicit that ``--check``/``--explain`` never write hub files, so
    writes are gated on ``ontology_loader.CACHE_WRITE_ENABLED`` -- the flag
    ``compile_cmd`` turns on solely inside ``cache_write_scope`` for ``--emit``, the one
    place DD-133/140 already permit hub writes. The honest consequence: a read-only
    command gets the speedup only after some ``--emit`` has warmed the cache, and a hub
    that never emits sees no change. That is the price of not owning machine-level
    state, which DD-158 rejected for the reference models for the same reasons.
    """
    from . import ontology_loader
    from ._cache import open_cache

    catalog = _hub_catalog_path(hub_root)
    if catalog is None:
        return {}
    if not ontology_loader.CACHE_ENABLED:
        return _reference_class_modules_uncached(catalog)

    fingerprint = _reference_corpus_fingerprint(catalog)
    cache = None
    if fingerprint is not None:
        try:
            cache = open_cache(Path(hub_root), _REFERENCE_INDEX_CACHE)
            hit = cache.get(fingerprint)
            if isinstance(hit, dict):
                return {str(name): str(module) for name, module in hit.items()}
        except Exception:  # an unreadable cache is a miss, never an error
            cache = None

    modules = _reference_class_modules_uncached(catalog)

    if (
        cache is not None
        and fingerprint is not None
        and modules  # never persist the empty defensive result
        and ontology_loader.CACHE_WRITE_ENABLED
    ):
        try:
            cache.clear()
            cache.put(fingerprint, modules)
            cache.flush()
        except Exception:  # a cache we cannot write is not a compile failure
            pass
    return modules


def _reference_class_modules_uncached(catalog: Path) -> dict[str, str]:
    """Resolve the reference-class index live. See :func:`_reference_class_modules`.

    Resolves through the DD-173 canonical path, so it reflects what the hub can
    actually reach rather than a snapshot. Returns empty on any failure: the
    unanchored tables are still worth reporting without the pointer.
    """
    try:
        from .class_anchoring import read_reference_terms

        modules: dict[str, str] = {}
        for term in read_reference_terms(catalog):
            if getattr(term, "kind", "") != "class":
                continue
            uri = str(getattr(term, "uri", ""))
            # Module URI is the namespace: everything up to and including the '#'.
            module = uri.split("#")[0] + "#" if "#" in uri else uri.rsplit("/", 1)[0] + "/"
            modules.setdefault(str(getattr(term, "name", "")), module)
        return modules
    except Exception:  # defensive: the report must survive a resolver problem
        return {}


def domain_imports(hub_root: Path) -> dict[str, set[str]]:
    """Map each hub domain to the module URIs its ontology imports.

    Read straight from the domain TTLs rather than the blueprint, because what
    constrains alignment is what the domain *actually* imports, which is the thing
    that can drift from what the blueprint intended.
    """
    imports: dict[str, set[str]] = {}
    ontologies = Path(hub_root) / "ontology-hub" / "model" / "ontologies"
    if not ontologies.is_dir():
        ontologies = Path(hub_root) / "model" / "ontologies"
    if not ontologies.is_dir():
        return imports
    pattern = re.compile(r"owl:imports\s+<([^>]+)>")
    for path in sorted(ontologies.glob("*.ttl")):
        text = path.read_text(encoding="utf-8", errors="replace")
        # Skip commented-out example imports, which the scaffold ships by default.
        found = {
            match.group(1)
            for line in text.splitlines()
            if not line.lstrip().startswith("#")
            for match in [pattern.search(line)]
            if match
        }
        if found:
            imports[path.stem] = found
    return imports


def _table_name_tokens(*values: str) -> set[str]:
    """Lowercase singular-ish tokens from a table name or candidate entity."""
    tokens: set[str] = set()
    for value in values:
        cleaned = re.sub(r"[^A-Za-z0-9]+", " ", str(value or ""))
        cleaned = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", cleaned)
        for raw in cleaned.split():
            token = raw.lower()
            if len(token) < 3:
                continue
            tokens.add(token)
            if token.endswith("s") and len(token) > 3:
                tokens.add(token[:-1])  # stops -> stop
    return tokens


def find_anchor_candidates(
    table_name: str,
    likely_entity: str,
    *,
    reference_classes: dict[str, str],
    imports_by_domain: dict[str, set[str]],
    own_domain: str,
    limit: int = 4,
) -> tuple[tuple[str, str, str], ...]:
    """Find classes elsewhere that would anchor this table (DD-180).

    *reference_classes* maps class name to its module URI, across every reference
    model available to the hub — not merely the ones this domain imports.

    This is the difference between a report saying "the model could not anchor
    ``stops``" and one saying "``TransportCall`` exists in ``dcsa/transport-call#``,
    which ``route-schedule`` imports and ``consignment`` does not". The first is an
    observation; the second is the fix.

    Matching is on shared name tokens, singularised, which is deliberately blunt:
    the output is a pointer for a human, not an automatic re-anchor, so a false
    suggestion costs a moment's reading and a missed one costs a silent blind spot.
    """
    wanted = _table_name_tokens(table_name, likely_entity)
    if not wanted:
        return ()

    scored: list[tuple[int, int, str, str, str]] = []
    for class_name, module_uri in reference_classes.items():
        class_tokens = _table_name_tokens(class_name)
        overlap = wanted & class_tokens
        if not overlap:
            continue
        # Tokens the class carries that the table did not ask for. `TransportCall`
        # and `BargeTransportCall` overlap equally with a table whose candidate
        # entity is "TransportCall"; the unqualified one is the better suggestion,
        # and a modal specialisation is a refinement for the modeller to choose.
        surplus = len(class_tokens - wanted)
        importers = sorted(
            domain
            for domain, uris in imports_by_domain.items()
            if domain != own_domain and module_uri in uris
        )
        # A class the domain already imports is not the explanation for a failed
        # anchor — the model saw it and declined it.
        if module_uri in imports_by_domain.get(own_domain, set()):
            continue
        scored.append(
            (len(overlap), surplus, class_name, module_uri, importers[0] if importers else "")
        )

    # Rank a module some *other* domain already imports above one nothing imports.
    # The first is a boundary mismatch — the hub decided this concept belongs
    # somewhere, and the table landed elsewhere — which is both the likelier
    # diagnosis and the cheaper fix. The second is often vocabulary coincidence:
    # "empty-units" matching `ConversionFactorBetweenUnits` in an OMG units module
    # no domain uses.
    scored.sort(key=lambda row: (0 if row[4] else 1, -row[0], row[1], row[2]))
    return tuple((name, uri, importer) for _, _, name, uri, importer in scored[:limit])


#: In-process memo of built reports, keyed on ``(analysis_dir, hub_root)`` ->
#: ``(inputs_fingerprint, report)``. Mirrors Tier A of the compile-perf cache in
#: ``ontology_loader``: process-lifetime only, never persisted, and a hit is only
#: trusted after re-checking that the inputs on disk still look the same.
_REPORT_CACHE: dict[tuple[str, str | None], tuple[str, "AlignmentReport"]] = {}


def reset_alignment_report_cache() -> None:
    """Drop the in-process report memo.

    Module-global caches leak across pytest cases, so the suite clears this between
    tests the same way it clears the per-model parameter cache (DD-174).
    """
    _REPORT_CACHE.clear()


def _report_inputs_fingerprint(analysis_dir: Path, hub_root: Path | None) -> str:
    """Fingerprint the *mutable hub* inputs a report is built from.

    ``(path, mtime_ns, size)`` over the alignment files and the source vocabularies --
    a few dozen small YAML files, stat-only, negligible against the reference-corpus
    parse this memo exists to avoid. Same philosophy as ``_manifest_still_fresh``:
    verify a hit rather than trust the key, so an edit between two calls in one process
    produces a fresh report instead of a stale one.

    Deliberately excludes the reference-model corpus: it ships in a pinned, immutable
    wheel, and a report is never rebuilt after an ontology edit within one process.
    """
    paths: list[Path] = sorted(Path(analysis_dir).glob("*-alignment.yaml"))
    if hub_root is not None:
        sources = Path(hub_root) / "integration" / "sources"
        if sources.is_dir():
            paths.extend(sorted(sources.glob("*/*.yaml")))
    stamped: list[list[Any]] = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:  # vanished between glob and stat; a miss is always safe
            continue
        stamped.append([str(path), stat.st_mtime_ns, stat.st_size])
    return compute_entry_hash(stamped)


def build_alignment_report(analysis_dir: Path, *, hub_root: Path | None = None) -> AlignmentReport:
    """Aggregate every ``*-alignment.yaml`` into one cross-domain coverage picture.

    *hub_root* enables the ``no-sample-evidence`` bucket by consulting the source
    vocabularies. Without it every unmapped column defaults to the gap bucket, which
    over-reports rather than under-reports -- the safer direction for a gate.

    Memoized in-process (#598). Building this resolves the whole reference-model
    vocabulary -- domain-independent work that dominates the cost -- and ``compile``
    alone asked for the same report twice per invocation, once for the DD-180 anchor
    gate and once for the DD-169 column gate. ``domains`` is not part of the key
    because callers filter by scope *after* the report is built, so one build serves
    every scope. Honours ``ontology_loader.CACHE_ENABLED``, so ``compile --no-cache``
    forces a clean rebuild.
    """
    from . import ontology_loader

    if not ontology_loader.CACHE_ENABLED:
        return _build_alignment_report_uncached(analysis_dir, hub_root=hub_root)

    key = (
        str(Path(analysis_dir).resolve()),
        str(Path(hub_root).resolve()) if hub_root is not None else None,
    )
    fingerprint = _report_inputs_fingerprint(Path(analysis_dir), hub_root)
    cached = _REPORT_CACHE.get(key)
    if cached is not None and cached[0] == fingerprint:
        return cached[1]
    report = _build_alignment_report_uncached(analysis_dir, hub_root=hub_root)
    _REPORT_CACHE[key] = (fingerprint, report)
    return report


def _build_alignment_report_uncached(
    analysis_dir: Path, *, hub_root: Path | None = None
) -> AlignmentReport:
    """Build the report from scratch. See :func:`build_alignment_report`."""
    import yaml

    report = AlignmentReport()
    directory = Path(analysis_dir)
    if not directory.is_dir():
        report.notices.append(f"No analysis directory at {directory}.")
        return report

    presence = source_sample_presence(hub_root) if hub_root is not None else {}
    # DD-180: resolving anchor candidates needs the full reference vocabulary and
    # each domain's real imports. Without a hub root the unanchored tables are still
    # reported — only the "the class exists over here" pointer is unavailable.
    reference_classes = _reference_class_modules(hub_root) if hub_root is not None else {}
    imports_by_domain = domain_imports(hub_root) if hub_root is not None else {}

    files = sorted(directory.glob("*-alignment.yaml"))
    if not files:
        report.notices.append(
            f"No alignment files in {directory}. Run 'kairos-ontology propose-alignment' first."
        )
        return report

    for path in files:
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:  # defensive: one broken file must not sink the report
            report.notices.append(f"Could not read {path.name}; skipped.")
            continue
        if not isinstance(document, dict):
            continue

        coverage = DomainCoverage(domain=str(document.get("domain") or path.stem))
        for table in document.get("tables") or ():
            if not isinstance(table, dict):
                continue
            coverage.tables += 1
            system = str(table.get("system") or "")
            name = str(table.get("table") or "")

            # DD-180: a table with no reference class produces low-value output that
            # is indistinguishable from ordinary output downstream. Record it here,
            # where the whole corpus is in view.
            status = str(table.get("ref_class_status") or "")
            if not str(table.get("ref_class") or "") or status in UNANCHORED_STATUSES:
                likely = str(table.get("likely_entity") or "")
                coverage.unanchored.append(
                    UnanchoredTable(
                        domain=coverage.domain,
                        system=system,
                        table=name,
                        columns=int(table.get("source_column_count") or 0)
                        or len(table.get("columns") or ())
                        + len(table.get("custom_columns") or ()),
                        status=status or "unmatched",
                        likely_entity=likely,
                        rejected_class=str(table.get("rejected_ref_class") or ""),
                        candidates=find_anchor_candidates(
                            name,
                            likely,
                            reference_classes=reference_classes,
                            imports_by_domain=imports_by_domain,
                            own_domain=coverage.domain,
                        ),
                    )
                )

            for column in table.get("columns") or ():
                if not isinstance(column, dict):
                    continue
                coverage.columns += 1
                kind = str(column.get("alignment") or "custom")
                coverage.by_alignment[kind] = coverage.by_alignment.get(kind, 0) + 1
                if column.get("ref_property"):
                    coverage.mapped += 1

            for entry in table.get("custom_columns") or ():
                if not isinstance(entry, dict):
                    continue
                column_name = str(entry.get("column") or "")
                coverage.columns += 1
                reason = classify_unmapped(
                    entry,
                    column_name,
                    has_samples=presence.get((system, name, column_name)),
                )
                coverage.unmapped.append(
                    UnmappedColumn(
                        system=system,
                        table=name,
                        column=column_name,
                        domain=coverage.domain,
                        data_type=str(entry.get("data_type") or ""),
                        reason=reason,
                        suggestion=str(entry.get("suggested_property") or ""),
                        recommended_disposition=str(entry.get("recommended_disposition") or ""),
                        proposal=dict(entry.get("proposed_local_property") or {}),
                    )
                )
        report.domains.append(coverage)

    report.domains.sort(key=lambda d: (-len(d.gap_columns), d.domain))
    return report


def render_markdown(report: AlignmentReport, *, gap_limit: int = 40) -> str:
    """Render the short report a reviewer reads before a design session.

    Carries an AI-attribution note (DD-178): every coverage figure here counts
    decisions a language model made, so the reader is told which model made them
    before reading a single number.
    """
    lines: list[str] = ["# Source alignment coverage", ""]
    lines.append(f"> {ai_attribution_note(ROLE_ALIGNMENT)}")
    lines.append("")
    lines.append(
        f"**{report.mapped:,} of {report.columns:,} source columns** aligned to a "
        f"reference-model property ({report.coverage:.0%}). "
        f"**{len(report.gap_columns):,}** carry real signal with no canonical home."
    )
    lines.append("")

    if report.unanchored:
        lines.append("## Tables with no reference class")
        lines.append("")
        lines.append(
            f"**{len(report.unanchored)} table(s), {report.unanchored_columns:,} columns.** "
            f"Alignment could not decide what these tables *are*, so their columns were "
            f"matched against the whole property pool with nothing to constrain the "
            f"choice. Output for them is low-value and unstable regardless of model or "
            f"settings — fix the anchor, not the prompt."
        )
        lines.append("")
        lines.append("| Domain | Table | Columns | Status | The class exists in |")
        lines.append("|---|---|---:|---|---|")
        for entry in report.unanchored:
            if entry.candidates:
                name, module, importer = entry.candidates[0]
                where = f"`{name}` in `{module}`"
                if importer:
                    where += f" — imported by **{importer}**, not this domain"
            else:
                where = "_no matching class found — genuine blueprint gap_"
            lines.append(
                f"| {entry.domain} | `{entry.table}` | {entry.columns:,} "
                f"| {entry.status} | {where} |"
            )
        lines.append("")
        if any(e.has_candidate_elsewhere for e in report.unanchored):
            lines.append(
                "Where a class is named above, this is a domain-boundary problem, not a "
                "modelling one: either add the module to this domain's `owl:imports`, or "
                "move the table to the domain that already imports it. Record the choice "
                "so the next run does not re-raise it."
            )
            lines.append("")

    lines.append("## Why columns are unmapped")
    lines.append("")
    lines.append("| Reason | Columns | What it means |")
    lines.append("|---|---:|---|")
    counts = report.reason_counts()
    for reason in REASON_ORDER:
        if reason in counts:
            lines.append(f"| `{reason}` | {counts[reason]:,} | {REASON_GUIDANCE[reason]} |")
    lines.append("")

    lines.append("## Coverage by domain")
    lines.append("")
    lines.append("| Domain | Tables | Columns | Mapped | Coverage | Gap columns |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for domain in report.domains:
        lines.append(
            f"| {domain.domain} | {domain.tables} | {domain.columns} | {domain.mapped} "
            f"| {domain.coverage:.0%} | {len(domain.gap_columns)} |"
        )
    lines.append("")

    gaps = report.gaps_by_table()
    if gaps:
        lines.append("## Where the unmapped signal is concentrated")
        lines.append("")
        for table, count in gaps[:15]:
            lines.append(f"- **{table}** — {count} column(s)")
        lines.append("")

    if report.gap_columns:
        lines.append("## Columns needing a decision")
        lines.append("")
        lines.append("| Table | Column | Type | Reason | Suggested |")
        lines.append("|---|---|---|---|---|")
        for column in report.gap_columns[:gap_limit]:
            lines.append(
                f"| {column.system}.{column.table} | `{column.column}` | {column.data_type} "
                f"| `{column.reason}` | {column.suggestion or '—'} |"
            )
        if len(report.gap_columns) > gap_limit:
            lines.append("")
            lines.append(
                f"_…and {len(report.gap_columns) - gap_limit:,} more; "
                "use `--format json` for the full list._"
            )
        lines.append("")

    for notice in report.notices:
        lines.append(f"> {notice}")
    return "\n".join(lines)


#: What a reviewer must choose between for each undecided gap column. Rendered into the
#: gate's failure output, because a hard stop that does not say how to clear it is an
#: obstacle rather than a control.
GAP_RESOLUTIONS: tuple[str, ...] = (
    "model it in the domain that owns it (the reference model lacks it, the business "
    "has it, and a sibling domain is the right home)",
    "register it with 'kairos-ontology register-concept' — real business data outside "
    "the archetype catalog, recorded with its source evidence",
    "record a disposition: 'source-disposition set --system <s> --table <t> --column "
    '<c> --disposition <blueprint-gap|not-business-data|deferred> --rationale "..."\'',
)


def undecided_gap_columns(
    hub_root: Path, *, domains: Iterable[str] | None = None
) -> list[UnmappedColumn]:
    """Return gap columns that carry real signal and have no recorded decision (DD-169).

    This is the pre-binding gate. Alignment is the first stage that can say "this column
    holds business data and the canonical model has nowhere to put it", and Stage 4 is
    where that becomes permanent: an EntityBinding either maps a column or silently
    leaves it behind, and by then the omission looks like a completed mapping.

    Only :data:`GAP_REASONS` columns count. Audit stamps, vendor placeholders and
    evidence-free columns are excluded by construction, so clearing this gate means
    deciding about real signal, not clicking through noise.
    """
    from .source_disposition import load_dispositions

    report = build_alignment_report(
        Path(hub_root) / "integration" / "sources" / "_analysis", hub_root=Path(hub_root)
    )
    scope = set(domains) if domains is not None else None
    recorded = load_dispositions(Path(hub_root))
    decided = {
        (
            str(entry.get("system") or ""),
            str(entry.get("table") or ""),
            str(entry.get("column") or ""),
        )
        for entry in recorded.values()
    }

    undecided: list[UnmappedColumn] = []
    for domain in report.domains:
        if scope is not None and domain.domain not in scope:
            continue
        for column in domain.gap_columns:
            # A table-grain disposition covers every column in it: deciding a whole
            # table is out of scope also decides its columns.
            if (column.system, column.table, "") in decided:
                continue
            if (column.system, column.table, column.column) in decided:
                continue
            undecided.append(column)
    return undecided


def undecided_unanchored_tables(
    hub_root: Path,
    *,
    domains: Iterable[str] | None = None,
) -> list[UnanchoredTable]:
    """Unanchored tables with no recorded disposition (DD-180).

    The companion to :func:`undecided_gap_columns`, one level up. That gate asks
    "this column has real signal and no home — decide"; this one asks "this *table*
    has no home at all — decide", which is the larger and more damaging omission:
    an unanchored table's columns cannot be mapped well no matter what happens
    downstream, and nothing else in the pipeline notices.

    Cleared the same way, by recording a table-grain disposition (DD-164), so
    "this table is genuinely out of scope" is a durable answer rather than an
    absence. A disposition on the table covers it whatever the reason.
    """
    from .source_disposition import load_dispositions

    report = build_alignment_report(
        Path(hub_root) / "integration" / "sources" / "_analysis", hub_root=Path(hub_root)
    )
    scope = set(domains) if domains is not None else None
    decided = {
        (str(entry.get("system") or ""), str(entry.get("table") or ""))
        for entry in load_dispositions(Path(hub_root)).values()
    }
    return [
        table
        for table in report.unanchored
        if (scope is None or table.domain in scope)
        and (table.system, table.table) not in decided
    ]


def render_unanchored_guidance(tables: list[UnanchoredTable]) -> str:
    """Render the actionable next step for each unanchored table (DD-180)."""
    if not tables:
        return ""
    lines = [
        f"{len(tables)} table(s) covering {sum(t.columns for t in tables):,} columns "
        f"have no reference class. Their columns cannot map well until this is fixed:",
        "",
    ]
    for table in tables:
        lines.append(f"  {table.domain} / {table.table}  ({table.columns:,} columns)")
        if not table.candidates:
            lines.append(
                "      No matching class in any reference model — a real blueprint gap. "
                "Register an extension concept, or record the table as out of scope."
            )
            continue
        for name, module, importer in table.candidates:
            owner = f" (imported by {importer})" if importer else " (imported by no domain)"
            lines.append(f"      candidate: {name} in {module}{owner}")
        lines.append(
            f"      Fix: add the module to {table.domain}'s owl:imports, or move the "
            f"table to the domain that already imports it."
        )
    return "\n".join(lines)


@dataclass
class GapGroup:
    """One column name and every table it appears in — a single decision."""

    column: str
    occurrences: list[UnmappedColumn] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.occurrences)

    @property
    def tables(self) -> list[str]:
        return sorted({f"{o.system}.{o.table}" for o in self.occurrences})

    @property
    def data_types(self) -> list[str]:
        return sorted({o.data_type for o in self.occurrences if o.data_type})

    @property
    def proposals(self) -> list[dict[str, str]]:
        """Distinct local-property proposals across this name's occurrences.

        More than one means the aligner read the same column name differently in
        different tables — worth seeing before accepting, not averaging away.
        """
        seen: dict[str, dict[str, str]] = {}
        for occurrence in self.occurrences:
            if occurrence.proposal:
                seen.setdefault(str(occurrence.proposal.get("name") or ""), occurrence.proposal)
        return [p for _, p in sorted(seen.items())]

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "count": self.count,
            "tables": self.tables,
            "data_types": self.data_types,
            "reasons": sorted({o.reason for o in self.occurrences}),
            "proposals": self.proposals,
        }


def group_gaps_by_column(report: AlignmentReport) -> list[GapGroup]:
    """Collapse gap columns to one entry per column name, widest first.

    A reviewer facing 1,096 undecided columns is really facing far fewer *decisions*:
    the same name recurs across tables because the same business fact does.
    Measured on a real hub, 1,096 gap columns reduce to 609 distinct names, and 258 of
    those names account for 745 of the columns — so deciding by name is roughly a
    threefold reduction on the repeated portion, and the widest names clear the most
    ground first.

    Grouping is by exact column name. Deliberately not fuzzy: ``order_id`` and
    ``orderId`` may or may not be the same fact, and a wrong merge would apply one
    decision to two different things silently.
    """
    grouped: dict[str, GapGroup] = {}
    for column in report.gap_columns:
        grouped.setdefault(column.column, GapGroup(column=column.column)).occurrences.append(column)
    return sorted(grouped.values(), key=lambda g: (-g.count, g.column))


def render_gap_groups_markdown(report: AlignmentReport, *, limit: int = 60) -> str:
    """Render the decide-once view: column names ranked by how much they clear."""
    groups = group_gaps_by_column(report)
    total = sum(g.count for g in groups)
    repeated = [g for g in groups if g.count > 1]

    lines = ["# Unmapped signal, grouped by column name", ""]
    lines.append(
        f"**{total:,} gap columns** reduce to **{len(groups):,} distinct names**. "
        f"{len(repeated):,} names recur across tables, covering "
        f"{sum(g.count for g in repeated):,} of them — decide those once."
    )
    lines.append("")
    proposed = [g for g in groups if g.proposals]
    if proposed:
        lines.append(
            f"{len(proposed):,} of them arrive with a proposed hub-local property — "
            "review and accept rather than author from scratch."
        )
        lines.append("")
    lines.append("| Column | Tables | Types | Proposed property | Appears in |")
    lines.append("|---|---:|---|---|---|")
    for group in groups[:limit]:
        shown = ", ".join(group.tables[:3])
        if len(group.tables) > 3:
            shown += f", +{len(group.tables) - 3} more"
        proposal = " / ".join(
            f"`{p.get('name')}`" + (f" on {p['on_class']}" if p.get("on_class") else "")
            for p in group.proposals
        )
        lines.append(
            f"| `{group.column}` | {group.count} | {', '.join(group.data_types) or '—'} "
            f"| {proposal or '—'} | {shown} |"
        )
    if len(groups) > limit:
        lines.append("")
        lines.append(
            f"_…and {len(groups) - limit:,} more names; use `--format json` for the full set._"
        )
    return "\n".join(lines)


def iter_gap_columns(report: AlignmentReport) -> Iterable[UnmappedColumn]:
    """Yield gap columns worst-table-first, for callers driving a review."""
    ranked = {table: index for index, (table, _) in enumerate(report.gaps_by_table())}
    return sorted(
        report.gap_columns,
        key=lambda c: (ranked.get(f"{c.system}.{c.table}", 1 << 30), c.column),
    )
