# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""One serializer for the shared ``models/silver/_<source>__sources.yml`` catalogs.

A source catalog is rendered per domain and, when several domains map tables from the
same system, unioned into one package-level file. Issue #1009: the first emit wrote the
template's layout and every later emit re-serialized it through the union, so the bytes
depended on whether the file already existed. Both paths now end in
:func:`_dump`, so the bytes are a function of the catalog's content only.
"""

from __future__ import annotations

import yaml


class SourcesUnionError(ValueError):
    """Two shared ``_sources.yml`` renderings disagree on source or table metadata.

    Issues #584/#586 made the union fail closed: dbt allows exactly one definition per
    source name, so silently keeping the first-seen header (or first-seen table entry)
    would let one domain's stale vocabulary quietly win over another's. The caller
    surfaces this as an artifact collision before any file is written.
    """


def _comments(text: str) -> list[str]:
    """Full-line YAML comments, in order and without duplicates.

    A YAML load drops comments, so they are carried over separately and written as a
    header. The template's logical-sources note is the only comment it renders.
    """
    seen: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and stripped not in seen:
            seen.append(stripped)
    return seen


def _dump(document: dict, comments: list[str]) -> str:
    body = yaml.safe_dump(
        document,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    header = "".join(f"{comment}\n" for comment in comments)
    return header + body


def union_sources_yaml(existing: str, incoming: str) -> str:
    """Deterministically union the ``tables`` of two rendered ``_sources.yml`` docs.

    Two domains that map tables from the same source system each emit a
    ``_{system}__sources.yml`` filtered to *their* mapped tables. The package-level
    file must declare the union of those tables exactly once. The source header
    (name/description/database/schema) must be identical for a given system and any
    same-named table entries must be identical; a mismatch raises
    :class:`SourcesUnionError` (fail closed) rather than silently keeping the
    first-seen variant. An empty *existing* canonicalizes *incoming*.
    """
    existing_doc = yaml.safe_load(existing) or {}
    incoming_doc = yaml.safe_load(incoming) or {}
    sources_by_name: dict[str, dict] = {}
    order: list[str] = []
    for doc in (existing_doc, incoming_doc):
        for src in doc.get("sources", []) or []:
            name = src.get("name")
            header = {k: v for k, v in src.items() if k != "tables"}
            if name not in sources_by_name:
                header["_tables"] = {}
                sources_by_name[name] = header
                order.append(name)
            else:
                existing_header = {k: v for k, v in sources_by_name[name].items() if k != "_tables"}
                if existing_header != header:
                    raise SourcesUnionError(
                        f"conflicting source metadata for source {name!r}: "
                        f"{existing_header!r} != {header!r}"
                    )
            tables = sources_by_name[name]["_tables"]
            for tbl in src.get("tables", []) or []:
                table_name = tbl.get("name")
                previous = tables.get(table_name)
                if previous is not None and previous != tbl:
                    raise SourcesUnionError(
                        f"conflicting table entry {table_name!r} in source {name!r}: "
                        f"{previous!r} != {tbl!r}"
                    )
                tables[table_name] = tbl
    merged_sources: list[dict] = []
    for name in order:
        entry = sources_by_name[name]
        table_map = entry.pop("_tables")
        entry["tables"] = [table_map[t] for t in sorted(table_map)]
        merged_sources.append(entry)
    # The current rendering's comments win; a catalog written before comments were
    # carried keeps whatever the incoming side says.
    comments = _comments(incoming) or _comments(existing)
    return _dump(
        {
            "version": existing_doc.get("version", incoming_doc.get("version", 2)),
            "sources": merged_sources,
        },
        comments,
    )


def canonical_sources_yaml(text: str) -> str:
    """Return *text* in the one layout every emit writes."""
    return union_sources_yaml("", text)
