# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Which source columns a hub's imported Power BI models depend on (#942).

``import-tmdl`` records what the hub's consumers actually use -- every fact and dimension
table, its columns, its measures and its relationships -- under
``integration/discovery/bi/``. The DD-169 gap gate, which decides which columns reach
Silver, never read it: a sailing-date column the headline weekly-volume report is built
on was auto-deferred like any other timestamp, and the report became unbuildable with no
diagnostic anywhere.

This module turns the concept mappings into an index keyed by normalised column name,
so a gap column can say "referenced by <model>: f_Volume[SailingDate] (relationship key)"
on its decision row. Matching is by name: a BI model names columns, not source
``system.table.column``, and in Import and Direct Lake models the two usually agree once
case and separators are ignored. A name match is evidence for a human, never a decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .evidence_loaders import BI_DISCOVERY_RELPATH

#: ``Table[Column]`` or a bare ``[Column]`` inside a DAX expression. Quoted table names
#: (``'Sales Order'[Amount]``) are matched too; the table part is optional.
_DAX_COLUMN_RE = re.compile(r"(?:'([^']+)'|([A-Za-z_][\w]*))?\[([^\]]+)\]")

#: Reference kinds, strongest first. A relationship key or a column a measure reads is
#: structural demand; a column merely present in the model is weaker but still demand.
KIND_RELATIONSHIP = "relationship key"
KIND_MEASURE = "measure input"
KIND_COLUMN = "model column"
_KIND_RANK = {KIND_RELATIONSHIP: 0, KIND_MEASURE: 1, KIND_COLUMN: 2}


def normalise(name: str) -> str:
    """Case- and separator-insensitive column key: ``SAILING_DATE`` == ``SailingDate``."""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


@dataclass(frozen=True, slots=True)
class BiReference:
    """One place a BI model uses a column."""

    model: str
    table: str
    column: str
    kind: str
    #: The measure that reads it, for ``KIND_MEASURE``.
    measure: str = ""

    def describe(self) -> str:
        where = f"{self.model}: {self.table}[{self.column}]" if self.table else (
            f"{self.model}: [{self.column}]"
        )
        detail = f"{self.kind} of {self.measure}" if self.measure else self.kind
        return f"{where} ({detail})"


@dataclass(slots=True)
class BiDemand:
    """Every BI reference in the hub, by normalised column name."""

    by_column: dict[str, list[BiReference]] = field(default_factory=dict)
    models: list[str] = field(default_factory=list)

    def references_for(self, column: str) -> list[BiReference]:
        """The references to *column*, strongest first, one per model/table/kind."""
        found = self.by_column.get(normalise(column), [])
        return sorted(set(found), key=lambda r: (_KIND_RANK[r.kind], r.model, r.table, r.measure))

    def describe(self, column: str, *, limit: int = 4) -> list[str]:
        refs = self.references_for(column)
        shown = [r.describe() for r in refs[:limit]]
        if len(refs) > limit:
            shown.append(f"... and {len(refs) - limit} more")
        return shown

    def __bool__(self) -> bool:
        return bool(self.by_column)

    def _add(self, ref: BiReference) -> None:
        key = normalise(ref.column)
        if key:
            self.by_column.setdefault(key, []).append(ref)


def _split_endpoint(endpoint: str) -> tuple[str, str]:
    """``"f_Sales.CustomerKey"`` -> ``("f_Sales", "CustomerKey")``."""
    table, _, column = str(endpoint).rpartition(".")
    return table, column


def load_bi_demand(hub_root: Path) -> BiDemand:
    """Index every imported concept mapping under ``integration/discovery/bi/``.

    Unreadable files are skipped: this is evidence, and a broken worksheet is
    ``design-landscape``'s to report.
    """
    demand = BiDemand()
    directory = Path(hub_root) / BI_DISCOVERY_RELPATH
    if not directory.is_dir():
        return demand
    for path in sorted(directory.glob("*-concept-mapping.yaml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(document, dict):
            continue
        model = str(document.get("model_name") or path.name.removesuffix("-concept-mapping.yaml"))
        demand.models.append(model)
        for table in document.get("tables") or []:
            if not isinstance(table, dict):
                continue
            table_name = str(table.get("tmdl_name") or "")
            for column in table.get("columns") or []:
                demand._add(BiReference(model, table_name, str(column), KIND_COLUMN))
            for measure in table.get("measures") or []:
                if not isinstance(measure, dict):
                    continue
                for quoted, bare, column in _DAX_COLUMN_RE.findall(
                    str(measure.get("expression") or "")
                ):
                    demand._add(
                        BiReference(
                            model, quoted or bare or table_name, column, KIND_MEASURE,
                            measure=str(measure.get("name") or ""),
                        )
                    )
        for relationship in document.get("relationships") or []:
            if not isinstance(relationship, dict):
                continue
            for endpoint in (relationship.get("from"), relationship.get("to")):
                table_name, column = _split_endpoint(str(endpoint or ""))
                if column:
                    demand._add(BiReference(model, table_name, column, KIND_RELATIONSHIP))
    return demand
