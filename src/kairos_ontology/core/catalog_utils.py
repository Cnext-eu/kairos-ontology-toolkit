# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""
XML Catalog utilities for resolving FIBO ontology imports.

Provides functions to:
- Parse XML catalog files
- Resolve URIs to local file paths
- Load imported ontologies from local files
"""

import logging
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from rdflib import Graph, OWL, RDF

_logger = logging.getLogger(__name__)


def _is_absolute_uri(uri_path: str) -> bool:
    """Return True when *uri_path* (a catalog ``uri=`` attribute) is an absolute URI/path.

    OASIS catalogs permit the ``uri=`` target itself to be an absolute URI (e.g.
    ``https://spec.edmcouncil.org/...``) rather than a path relative to the catalog
    file. Joining such a value onto ``catalog_dir`` produces a nonsensical local
    path, so callers must detect and skip this case rather than resolve it.
    """
    return bool(urlparse(uri_path).scheme) or Path(uri_path).is_absolute()


@dataclass
class CatalogLoadResult:
    """Result of loading an ontology graph with catalog-based import resolution.

    Attributes:
        graph: The loaded RDF graph (including resolved imports).
        diagnostics: Structured messages collected during loading.
            Each entry is a dict with keys: level ("warning"|"error"|"info"), message (str).
    """

    graph: Graph = field(default_factory=Graph)
    diagnostics: List[Dict[str, str]] = field(default_factory=list)

    def warnings(self) -> List[str]:
        """Return only warning-level diagnostic messages."""
        return [d["message"] for d in self.diagnostics if d["level"] == "warning"]


@dataclass(frozen=True)
class CatalogEntry:
    """One declared ``<uri>`` element, tagged with the catalog file that declared it.

    ``declaring_catalog`` is the resolved path of the catalog file the ``<uri>``
    element was parsed from — the catalog under test itself, or a catalog reached
    by following ``<nextCatalog>`` (e.g. the vendored reference-models catalog).
    This lets an auditor distinguish entries the hub author can actually fix from
    entries owned by an upstream catalog.

    ``absolute`` is True when the ``uri=`` target itself is an absolute URI/path
    (permitted by OASIS catalogs) rather than a path relative to the catalog file;
    ``path`` is not meaningful for dangling checks in that case.
    """

    name: str
    path: Path
    declaring_catalog: Path
    absolute: bool = False


@dataclass(frozen=True)
class CatalogResolution:
    """One catalog lookup, including the resolution strategy and ambiguity."""

    uri: str
    path: Optional[Path]
    method: str
    candidates: Tuple[Path, ...] = ()

    @property
    def ambiguous(self) -> bool:
        """Return whether more than one local source matched the URI."""
        return len(self.candidates) > 1


def _get_rdf_format(file_path: Path) -> str:
    """
    Detect RDF format from file extension.

    Args:
        file_path: Path to the RDF file

    Returns:
        Format string for rdflib.Graph.parse()
    """
    suffix = file_path.suffix.lower()
    format_map = {
        ".ttl": "turtle",
        ".turtle": "turtle",
        ".rdf": "xml",
        ".xml": "xml",
        ".owl": "xml",
        ".n3": "n3",
        ".nt": "nt",
        ".ntriples": "nt",
        ".jsonld": "json-ld",
        ".json": "json-ld",
    }
    return format_map.get(suffix, "turtle")  # Default to turtle


class CatalogResolver:
    """Resolves ontology URIs to local files using XML catalog."""

    CATALOG_NS = "{urn:oasis:names:tc:entity:xmlns:xml:catalog}"

    def __init__(self, catalog_path: Path, extra_catalogs: list[Path] | None = None):
        """
        Initialize resolver with catalog file.

        Args:
            catalog_path: Path to catalog-v001.xml file
            extra_catalogs: Optional list of additional catalog files to overlay
                (e.g. the reference-models package catalog).
        """
        self.catalog_path = catalog_path
        self.mappings: Dict[str, Path] = {}
        self.entries: List[CatalogEntry] = []
        self._rewrite_rules: List[Tuple[str, str, Path]] = []
        self._hash_fallback_used: bool = False
        self._rewrite_fallback_used: bool = False
        self._visited_catalogs: set[Path] = set()
        self.diagnostics: List[Dict[str, str]] = []
        self._load_catalog_file(self.catalog_path)
        for extra in extra_catalogs or []:
            self._load_catalog_file(extra)
        # Re-sort after loading extra catalogs' rewrite rules
        self._rewrite_rules.sort(key=lambda r: len(r[0]), reverse=True)

    @classmethod
    def with_reference_models(cls, catalog_path: Path) -> "CatalogResolver":
        """Create a resolver that overlays the reference-models package catalog.

        Resolution order: ``KAIROS_REFMODELS_ROOT`` env var (explicit override),
        then installed ``kairos-ontology-referencemodels`` package.
        """
        extra: list[Path] = []
        env_root = os.environ.get("KAIROS_REFMODELS_ROOT")
        if env_root:
            env_catalog = Path(env_root) / "catalog-v001.xml"
            if env_catalog.is_file():
                extra.append(env_catalog)
        try:
            from kairos_ontology_referencemodels import refmodels_root

            pkg_catalog = refmodels_root() / "catalog-v001.xml"
            if pkg_catalog.is_file() and pkg_catalog not in extra:
                extra.append(pkg_catalog)
        except ImportError:
            pass
        return cls(catalog_path, extra_catalogs=extra)

    def _load_catalog_file(self, path: Path):
        """Parse a single catalog file, following <nextCatalog> references."""
        path = path.resolve()
        if path in self._visited_catalogs:
            self.diagnostics.append(
                {
                    "level": "warning",
                    "code": "catalog_cycle",
                    "message": f"Catalog cycle detected at: {path}",
                }
            )
            return
        self._visited_catalogs.add(path)
        if not path.exists():
            raise FileNotFoundError(f"Catalog not found: {path}")

        tree = ET.parse(path)
        root = tree.getroot()
        catalog_dir = path.parent

        # Parse all <uri> elements
        for uri_elem in root.findall(f"{self.CATALOG_NS}uri"):
            uri_name = uri_elem.get("name")
            uri_path = uri_elem.get("uri")

            if uri_name and uri_path:
                is_absolute = _is_absolute_uri(uri_path)
                if is_absolute:
                    # OASIS catalogs permit the uri= target to be an absolute URI/path
                    # in its own right (e.g. a remote spec URL). Joining it onto
                    # catalog_dir produces a nonsensical mangled path (e.g.
                    # `<hub>\https:\spec.edmcouncil.org\...`); keep it as-is instead.
                    local_path = Path(uri_path)
                else:
                    local_path = (catalog_dir / uri_path).resolve()

                # Track the raw declared entry (one per <uri> element, no normalized
                # variants) tagged with the declaring catalog file, so callers can
                # audit declared entries, e.g. detect ones whose target file does
                # not exist ("dangling" entries), scoped to the catalog that owns
                # them rather than every catalog reached via <nextCatalog>.
                self.entries.append(CatalogEntry(uri_name, local_path, path, is_absolute))

                # Store exact mapping
                self.mappings[uri_name] = local_path

                # Normalize URI (ensure trailing slash consistency)
                normalized_uri = uri_name.rstrip("/#") + "/"
                self.mappings[normalized_uri] = local_path

                # Also add without trailing slash for flexibility
                self.mappings[normalized_uri.rstrip("/")] = local_path

                # Hash normalization: store both with and without trailing #
                bare = uri_name.rstrip("#")
                self.mappings[bare] = local_path
                self.mappings[bare + "#"] = local_path

        # Follow <nextCatalog> references
        for next_elem in root.findall(f"{self.CATALOG_NS}nextCatalog"):
            next_catalog = next_elem.get("catalog")
            if next_catalog:
                next_path = (catalog_dir / next_catalog).resolve()
                if next_path.exists():
                    self._load_catalog_file(next_path)
                else:
                    self.diagnostics.append(
                        {
                            "level": "warning",
                            "code": "missing_next_catalog",
                            "message": f"Referenced nextCatalog does not exist: {next_path}",
                        }
                    )

        # Parse <rewriteURI> elements
        for rewrite_elem in root.findall(f"{self.CATALOG_NS}rewriteURI"):
            start_string = rewrite_elem.get("uriStartString")
            rewrite_prefix = rewrite_elem.get("rewritePrefix")
            if start_string and rewrite_prefix:
                self._rewrite_rules.append((start_string, rewrite_prefix, catalog_dir))

    def resolve(self, uri: str) -> Optional[Path]:
        """
        Resolve an ontology URI to a local file path.

        Args:
            uri: Ontology URI (e.g., https://spec.edmcouncil.org/fibo/...)

        Returns:
            Local file path if mapping exists, None otherwise
        """
        return self.resolve_detailed(uri).path

    def resolve_detailed(self, uri: str) -> CatalogResolution:
        """Resolve *uri* and disclose the strategy and candidate set."""
        self._hash_fallback_used = False
        self._rewrite_fallback_used = False

        # Try exact match first
        if uri in self.mappings:
            return CatalogResolution(uri, self.mappings[uri], "exact")

        # Try with/without trailing slash
        uri_with_slash = uri.rstrip("/") + "/"
        if uri_with_slash in self.mappings:
            return CatalogResolution(uri, self.mappings[uri_with_slash], "slash_fallback")

        uri_without_slash = uri.rstrip("/")
        if uri_without_slash in self.mappings:
            return CatalogResolution(uri, self.mappings[uri_without_slash], "slash_fallback")

        # Try with/without trailing hash
        uri_with_hash = uri.rstrip("#") + "#"
        if uri_with_hash in self.mappings:
            self._hash_fallback_used = True
            return CatalogResolution(uri, self.mappings[uri_with_hash], "hash_fallback")

        uri_without_hash = uri.rstrip("#")
        if uri_without_hash in self.mappings:
            self._hash_fallback_used = True
            return CatalogResolution(uri, self.mappings[uri_without_hash], "hash_fallback")

        # Try rewriteURI rules (longest-prefix-wins, already sorted)
        return self._resolve_via_rewrite(uri)

    # Extension probe order for rewriteURI fallback
    _EXTENSION_FALLBACK = [".rdf", ".ttl", ".owl"]

    def _resolve_via_rewrite(self, uri: str) -> CatalogResolution:
        """Apply rewriteURI rules with extension fallback.

        Returns the resolved file path, or None if no rule matches or no file exists.
        """
        for start_string, rewrite_prefix, catalog_dir in self._rewrite_rules:
            if not uri.startswith(start_string):
                continue

            # Apply prefix replacement
            suffix = uri[len(start_string) :]
            candidate = (catalog_dir / rewrite_prefix / suffix).resolve()

            # Direct match — rewritten path is an existing file
            if candidate.is_file():
                self._rewrite_fallback_used = False
                return CatalogResolution(uri, candidate, "rewrite")

            # Extension fallback: strip trailing slash/separator, try extensions
            base = str(candidate).rstrip("/\\")
            found: List[Path] = []
            for ext in self._EXTENSION_FALLBACK:
                probe = Path(base + ext)
                if probe.is_file():
                    found.append(probe)

            if found:
                self._rewrite_fallback_used = True
                if len(found) > 1:
                    _logger.warning(
                        "Ambiguous rewriteURI resolution for <%s>: multiple files exist "
                        "(%s). Using first in priority order: %s",
                        uri,
                        ", ".join(p.name for p in found),
                        found[0].name,
                    )
                return CatalogResolution(
                    uri,
                    found[0],
                    "rewrite_extension",
                    tuple(found),
                )

        return CatalogResolution(uri, None, "unresolved")


def load_graph_with_catalog(
    ontology_path: Path,
    catalog_path: Path,
    *,
    quiet: bool = False,
) -> CatalogLoadResult:
    """
    Load an RDF graph and resolve owl:imports using XML catalog.

    Args:
        ontology_path: Path to main ontology file
        catalog_path: Path to catalog-v001.xml
        quiet: Suppress human-readable import progress while retaining diagnostics.

    Returns:
        CatalogLoadResult with the loaded graph and any diagnostics collected
        during import resolution.
    """
    from .ontology_loader import load_ontology

    loaded = load_ontology(
        ontology_path,
        catalog_path=catalog_path,
        degraded=True,
    )
    diagnostics: List[Dict[str, str]] = []
    for diagnostic in loaded.diagnostics:
        if diagnostic.code == "missing_import":
            message = f"No catalog mapping for: {diagnostic.import_uri}"
            level = "warning"
        elif diagnostic.code == "unsupported_file_import":
            message = f"Skipping file:// import (use catalog instead): {diagnostic.import_uri}"
            level = "warning"
        elif diagnostic.code == "import_parse_error":
            message = diagnostic.message
            level = "error"
        else:
            message = diagnostic.message
            level = diagnostic.level
        diagnostics.append({"level": level, "message": message})
        if not quiet:
            prefix = "✗" if level == "error" else "⚠️" if level == "warning" else "ℹ️"
            print(f"{prefix}  {message}")

    loaded_imports = sum(1 for entry in loaded.manifest if entry.import_depth > 0)
    direct_imports = len(list(loaded.graph.objects(predicate=OWL.imports)))
    if not quiet:
        print(f"\n📦 Loaded {loaded_imports}/{direct_imports} imports via catalog")

    return CatalogLoadResult(graph=loaded.graph, diagnostics=diagnostics)


def resolve_import_paths(ontology_path: Path, catalog_path: Path) -> Dict[str, Path]:
    """Resolve direct owl:imports URIs to local file paths.

    This is useful for discovering sibling files (e.g., extension defaults)
    alongside directly imported reference models.

    Args:
        ontology_path: Path to main ontology file
        catalog_path: Path to catalog-v001.xml

    Returns:
        Dict mapping import URI string → resolved local Path (only for
        imports that have a catalog mapping and whose file exists).
    """
    from .ontology_loader import load_ontology

    loaded = load_ontology(
        ontology_path,
        catalog_path=catalog_path,
        degraded=True,
    )
    return {
        entry.import_uri: Path(entry.source_path)
        for entry in loaded.manifest
        if entry.import_uri is not None and entry.import_depth == 1
    }


def _relative_catalog_uri(catalog_path: Path, target_path: Path) -> str:
    """Return a catalog-local URI path using XML-friendly separators."""
    try:
        relative = target_path.resolve().relative_to(catalog_path.parent.resolve())
    except ValueError:
        relative = target_path
    return relative.as_posix()


def _declared_ontology_iri(ontology_ttl_path: Path) -> Optional[str]:
    """Return the first declared owl:Ontology IRI in a Turtle ontology file."""
    graph = Graph()
    graph.parse(ontology_ttl_path, format=_get_rdf_format(ontology_ttl_path))
    for subject in graph.subjects(RDF.type, OWL.Ontology):
        if subject:
            return str(subject).rstrip("/")
    return None


# --- Textual (non-serializing) catalog editing --------------------------------
#
# `sync_domain_catalog_entry` used to round-trip the whole catalog file through
# `xml.etree.ElementTree` (parse, mutate, `ET.indent`, `tree.write(...)`). That
# reformats the *entire* file on every call: it drops the prolog comment that
# precedes the root element (ElementTree doesn't expose comments outside the
# tree unless specially configured, and never re-emits them on write), strips
# blank lines, rewrites the XML declaration's quote/case style, drops the
# trailing newline, and — because insertion always targeted "before the first
# <nextCatalog>" — landed new entries in the wrong section when a catalog also
# chains to a shared reference-models catalog.
#
# The functions below instead treat the catalog as text and only ever touch the
# smallest span necessary: either the exact `<uri .../>` element being updated,
# or a small insertion at a well-defined anchor. Every other byte — comments,
# blank lines, declaration style, trailing newline, line endings — is left
# completely untouched. `lxml` was considered and rejected (see DD notes / issue
# #327): it isn't a dependency of this project, would newly become a hard one
# for every `init --domain` run, and would only fix the comment-loss defect —
# the other four defects come from whole-tree re-serialization regardless of
# which library performs it.
#
# CRITICAL: never do `text.splitlines()` + `"\n".join(...)` here. The real
# template (catalog-v001.xml.template) uses CRLF line endings throughout; a
# split/rejoin with a hardcoded "\n" would silently convert the whole file to
# LF, recreating the exact "giant diff for a tiny change" bug this exists to
# fix. All edits below operate on the raw string via regex/substring search
# and replace only.

_URI_ELEMENT_RE = re.compile(r"<uri\b[^<]*?/>", re.DOTALL)
_URI_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_NEXT_CATALOG_RE = re.compile(r"<nextCatalog\b")
_CLOSE_CATALOG_RE = re.compile(r"</catalog\s*>")
_PREFIXED_NAMESPACE_RE = re.compile(r'xmlns:(\w+)\s*=\s*"[^"]*"')


def _parse_uri_attrs(tag_text: str) -> Dict[str, str]:
    """Extract attribute name/value pairs from a raw ``<uri .../>`` tag string."""
    return dict(_URI_ATTR_RE.findall(tag_text))


def _mask_comments(text: str) -> str:
    """Return *text* with the contents of every ``<!-- ... -->`` blanked out.

    The template ships a commented-out example ``<uri>`` (and a marker comment
    that even mentions ``<uri>`` in its own prose) so a domain named e.g.
    "customer" — the template's own example — must never be matched against
    that commented-out text when looking for a *live* catalog entry. Masking
    replaces every character inside a comment (including the ``<!--``/``-->``
    delimiters) with a space, except line-ending characters, which are kept as-
    is. This preserves both the string length and every character offset, so
    match spans found against the masked text are directly reusable as slice
    indices into the original, unmasked text.
    """

    def _blank(match: "re.Match[str]") -> str:
        return "".join(ch if ch in ("\r", "\n") else " " for ch in match.group(0))

    return _COMMENT_RE.sub(_blank, text)


def _guard_unsupported_catalog_dialect(text: str) -> None:
    """Raise if *text* looks like a namespace-prefixed catalog dialect.

    This codebase has only ever generated (and this function has only ever been
    exercised against) catalogs using the default, unprefixed OASIS XML Catalog
    namespace: bare ``<uri>``/``<nextCatalog>`` elements. A catalog that instead
    declares e.g. ``xmlns:c="..."`` alongside ``<c:uri>`` elements is a shape our
    regex-based editing has never handled; refuse rather than risk silently
    misplacing content by editing a shape we don't understand.
    """
    for match in _PREFIXED_NAMESPACE_RE.finditer(text):
        prefix = match.group(1)
        if re.search(rf"<{re.escape(prefix)}:uri\b", text):
            raise ValueError(
                "Unsupported namespace-prefixed XML catalog dialect detected "
                f'(xmlns:{prefix}="..." with <{prefix}:uri> elements). '
                "sync_domain_catalog_entry only supports the bare (unprefixed) "
                "OASIS XML Catalog element names this toolkit generates."
            )


def _line_start(text: str, pos: int) -> int:
    """Return the index of the start of the line containing *pos*."""
    return text.rfind("\n", 0, pos) + 1


def _detect_newline(text: str) -> str:
    """Return the dominant line ending used in *text* (CRLF if present, else LF)."""
    return "\r\n" if "\r\n" in text else "\n"


def _validate_catalog_text(
    text: str, ontology_iri: str, relative_uri: str, catalog_path: Path
) -> None:
    """Parse *text* purely to confirm it is well-formed XML with the expected entry.

    This is a validation-only check — the parsed tree is discarded immediately
    and never used to serialize output, so it cannot reintroduce any of the
    whole-tree re-serialization defects this module exists to avoid.
    """
    try:
        parsed = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:
        raise ValueError(
            f"Textual catalog edit produced invalid XML for {catalog_path}: {exc}"
        ) from exc

    namespace = ""
    if parsed.tag.startswith("{"):
        namespace = parsed.tag[1:].split("}", 1)[0]
    uri_tag = f"{{{namespace}}}uri" if namespace else "uri"

    for element in parsed.findall(uri_tag):
        if element.get("name") == ontology_iri and element.get("uri") == relative_uri:
            return

    raise ValueError(
        f"Textual catalog edit did not produce the expected <uri name={ontology_iri!r} "
        f"uri={relative_uri!r}/> in {catalog_path}"
    )


def validate_turtle_text(text: str, *, context: Path) -> None:
    """Parse *text* purely to confirm it is well-formed Turtle.

    Mirrors :func:`_validate_catalog_text`'s role for XML catalogs: the parsed
    graph is discarded immediately and never used to extract domain semantics
    or to serialize output, so this is a syntax gate for a proposed textual
    edit before it is written -- not a DD-103 canonical-loader (``core/
    ontology_loader.py``) bypass, since no semantic index is built or consumed
    here. Used by :mod:`kairos_ontology.core.master_ontology` to validate a
    proposed ``_master.ttl`` edit before writing it.
    """
    try:
        Graph().parse(data=text, format="turtle")
    except Exception as exc:  # noqa: BLE001 - rdflib raises many parser-specific types
        raise ValueError(
            f"Proposed textual edit to {context} would not parse as valid Turtle: {exc}"
        ) from exc


def sync_domain_catalog_entry(
    catalog_path: Path,
    ontology_ttl_path: Path,
    *,
    company_domain: Optional[str] = None,
) -> str:
    """Ensure a hub-authored domain ontology is mapped in an XML catalog.

    The ontology IRI is read from the file's ``owl:Ontology`` declaration. If no
    declaration is present, ``company_domain`` supplies the conventional fallback
    ``https://<company_domain>/ont/<stem>``.

    This edits the catalog file textually (never via an ``ElementTree`` write)
    so that everything except the target ``<uri>`` element — the prolog
    comment, blank lines, XML declaration style, trailing newline, and line
    endings — is preserved byte-for-byte. See the module-level comment above
    for why.

    Returns:
        The ontology IRI registered in the catalog.
    """
    ontology_iri = _declared_ontology_iri(ontology_ttl_path)
    if ontology_iri is None:
        if not company_domain:
            raise ValueError(
                "Cannot infer catalog IRI without an owl:Ontology declaration "
                "or company_domain fallback."
            )
        ontology_iri = f"https://{company_domain.rstrip('/')}/ont/{ontology_ttl_path.stem}"

    relative_uri = _relative_catalog_uri(catalog_path, ontology_ttl_path)

    # ``newline=""`` disables Python's universal-newlines translation, which
    # would otherwise silently normalize CRLF -> LF on read (and re-translate
    # LF -> os.linesep on write, making the result depend on the host OS). This
    # is what actually guarantees byte-for-byte line-ending preservation here —
    # not merely avoiding splitlines()/join().
    with catalog_path.open("r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    _guard_unsupported_catalog_dialect(text)
    nl = _detect_newline(text)
    new_uri_tag = f'<uri name="{ontology_iri}" uri="{relative_uri}"/>'

    # Comments (the marker's own "<uri>" prose, the commented-out example, a
    # commented-out <nextCatalog>) must never be mistaken for live elements —
    # e.g. the template's commented example already uses "customer" as its
    # sample domain name, which is also a completely realistic real domain
    # name. Search a masked copy for anything that must only match *live*
    # markup; masking preserves length/offsets so spans are reusable as-is
    # against the original text.
    masked_text = _mask_comments(text)

    # --- Idempotent-update path: an existing *live* entry for this ontology
    # already exists (by IRI or by relative path) — replace only that
    # element's span, collapsing any multi-line form to the canonical single
    # line.
    matched_span = None
    for match in _URI_ELEMENT_RE.finditer(masked_text):
        attrs = _parse_uri_attrs(text[match.start() : match.end()])
        if attrs.get("name") == ontology_iri or attrs.get("uri") == relative_uri:
            matched_span = match.span()
            break

    if matched_span is not None:
        start, end = matched_span
        new_text = text[:start] + new_uri_tag + text[end:]
    else:
        # --- New-entry path: choose an insertion anchor, in priority order. ---
        insert_pos = None
        for comment_match in _COMMENT_RE.finditer(text):
            if "Domain ontologies" in comment_match.group(0):
                insert_pos = comment_match.end()
                break

        if insert_pos is not None:
            # (i) Insert right after the "Domain ontologies" marker comment,
            # before the commented-out example — the actual bug fix.
            new_text = text[:insert_pos] + nl + "  " + new_uri_tag + text[insert_pos:]
        else:
            next_catalog_match = _NEXT_CATALOG_RE.search(masked_text)
            if next_catalog_match is not None:
                # (ii) No marker comment: insert immediately before a *live*
                # <nextCatalog>, matching today's existing behaviour for a
                # catalog with no marker comment.
                line_start = _line_start(text, next_catalog_match.start())
                new_text = text[:line_start] + "  " + new_uri_tag + nl + text[line_start:]
            else:
                # (iii) Last resort: insert immediately before </catalog>.
                close_match = _CLOSE_CATALOG_RE.search(masked_text)
                if close_match is None:
                    raise ValueError(f"Malformed XML catalog (no </catalog> found): {catalog_path}")
                line_start = _line_start(text, close_match.start())
                new_text = text[:line_start] + "  " + new_uri_tag + nl + text[line_start:]

    _validate_catalog_text(new_text, ontology_iri, relative_uri, catalog_path)
    with catalog_path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(new_text)
    return ontology_iri
