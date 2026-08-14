# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Trace source()/ref() lineage through a hand-authored contracted dbt model tree.

Issue #400: ``field-mapping-report`` excluded every ``source.dbtModel`` binding entirely
(``_binding_source_ref`` only reads ``source.relation``) instead of attributing its fields
to the source systems that actually feed the model via ``source()``/``ref()`` calls. This
resolves that lineage from the model's own physical ``.sql`` text -- the same ``sqlPath``
an EntityBinding already declares -- rather than from dbt's own ``target/manifest.json``,
which is produced by a separate ``dbt compile``/``dbt build`` step external to this
toolkit and is not guaranteed to exist when ``field-mapping-report`` runs during
design/mapping review.
"""

from __future__ import annotations

import re
from pathlib import Path

_REF_RE = re.compile(r"\bref\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")
_SOURCE_RE = re.compile(r"\bsource\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"][^'\"]+['\"]\s*\)")
_TRANSFORMS_MODELS_PARTS = ("integration", "transforms", "dbt", "models")


def _find_model_sql(hub_root: Path, model_name: str) -> Path | None:
    """Return the unique ``<model_name>.sql`` file under the dbt models tree, if any.

    Mirrors ``core.compiler.dbt_source``'s own path-resolution scope (models under
    ``integration/transforms/dbt/models/``); an ambiguous (multiple files with the same
    stem) or missing match is reported to the caller as non-traceable rather than guessed.
    """
    models_dir = hub_root.joinpath(*_TRANSFORMS_MODELS_PARTS)
    if not models_dir.is_dir():
        return None
    matches = list(models_dir.rglob(f"{model_name}.sql"))
    return matches[0] if len(matches) == 1 else None


def resolve_dbt_model_contributing_sources(
    hub_root: Path,
    sql_path: str | Path,
    *,
    _seen: frozenset[str] = frozenset(),
) -> tuple[frozenset[str], bool]:
    """Return ``(contributing source-system ids, is_fully_traceable)`` for one model's SQL.

    Recursively follows ``ref()`` targets to their own ``.sql`` files (found by filename
    under ``integration/transforms/dbt/models/``) and collects every ``source()``-declared
    system directly. ``is_fully_traceable`` is ``False`` when a ``ref()`` target's ``.sql``
    file cannot be uniquely resolved (ambiguous or missing) or the file cannot be read --
    lineage through that branch is reported as ambiguous rather than silently dropped or
    guessed, per issue #400's acceptance criteria.
    """
    hub_root = Path(hub_root)
    candidate = Path(sql_path)
    resolved_path = candidate if candidate.is_absolute() else (hub_root / candidate).resolve()
    if not resolved_path.is_file():
        return frozenset(), False

    model_name = resolved_path.stem
    if model_name in _seen:
        # A dependency cycle is a structural error elsewhere (dbt itself would refuse to
        # compile it); stop recursing rather than looping forever, without claiming
        # falsely that this branch is untraceable.
        return frozenset(), True
    seen = _seen | {model_name}

    try:
        text = resolved_path.read_text(encoding="utf-8")
    except OSError:
        return frozenset(), False

    sources = {match.group(1) for match in _SOURCE_RE.finditer(text)}
    fully_traceable = True
    for ref_name in {match.group(1) for match in _REF_RE.finditer(text)}:
        ref_path = _find_model_sql(hub_root, ref_name)
        if ref_path is None:
            fully_traceable = False
            continue
        nested_sources, nested_traceable = resolve_dbt_model_contributing_sources(
            hub_root, ref_path, _seen=seen
        )
        sources |= nested_sources
        fully_traceable = fully_traceable and nested_traceable

    return frozenset(sources), fully_traceable
