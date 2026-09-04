# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Canonical target-platform vocabulary for the whole toolkit (DD-215).

Before DD-215 the two-value set ``{"fabric", "databricks"}`` was redeclared independently
in eight places -- two ``click.Choice`` lists, ``SUPPORTED_PLATFORMS``,
``SUPPORTED_ADAPTERS``, an inline set in the compile kernel, and three literal tuples --
none of which imported :class:`AdapterName`. Adding an adapter meant finding all of them.
This module is the one declaration; everything else imports from here.

``fabric`` was also under-specified. Microsoft Fabric offers two engines with different
SQL dialects -- Warehouse (T-SQL) and Lakehouse (Spark SQL) -- and a single ``fabric``
adapter silently gave both the T-SQL profile. The canonical ids are therefore explicit
about the engine, and Fabric Lakehouse is *recognised and rejected* rather than quietly
compiled as T-SQL.

This is a leaf module: it imports nothing from :mod:`kairos_ontology`, so both
``core`` and ``core.projections.dbt`` can depend on it without a cycle.
"""

from __future__ import annotations

from enum import Enum


class AdapterName(str, Enum):
    """One supported compiler adapter, identified by target engine rather than vendor."""

    FABRIC_WAREHOUSE = "fabric-warehouse"
    DATABRICKS = "databricks"

    @classmethod
    def _missing_(cls, value: object) -> AdapterName | None:
        """Resolve deprecated aliases so ``AdapterName("fabric")`` keeps working.

        Hubs are client repositories the toolkit does not control, and every one of them
        was scaffolded with ``adapter: fabric``. Silent resolution here means an upgrade
        cannot break a hub outright; the deprecation is surfaced once, by
        :func:`resolve_adapter`, at the point the value is read from ``kairos.yaml``.
        """
        if isinstance(value, str):
            canonical = ADAPTER_ALIASES.get(value)
            if canonical is not None:
                return cls(canonical)
        return None


#: Deprecated authored spellings that still resolve, and what they resolve to.
ADAPTER_ALIASES: dict[str, str] = {
    "fabric": AdapterName.FABRIC_WAREHOUSE.value,
}

#: Target platforms the toolkit knows about but deliberately does not support. Keeping
#: these distinct from "unknown" is the whole point: a Lakehouse hub must be told that
#: Spark SQL is not implemented, not handed a T-SQL profile that compiles and then fails
#: at run time.
RECOGNIZED_UNSUPPORTED: dict[str, str] = {
    "fabric-lakehouse": (
        "Fabric Lakehouse targets Spark SQL, which has no adapter profile yet; "
        "compiling it as T-SQL would emit SQL the engine cannot run"
    ),
}

#: Every supported canonical id, in declaration order.
SUPPORTED_ADAPTER_IDS: tuple[str, ...] = tuple(item.value for item in AdapterName)

#: Canonical id -> the ``type:`` key dbt itself expects in ``profiles.yml``, and the
#: value the packaged macros branch on as ``target.type``. dbt's vocabulary is not ours:
#: ``dbt-fabric`` calls itself ``fabric`` regardless of which Fabric engine it points at,
#: so this mapping is deliberately not the identity and must not be inlined.
DBT_PROFILE_TYPES: dict[str, str] = {
    AdapterName.FABRIC_WAREHOUSE.value: "fabric",
    AdapterName.DATABRICKS.value: "databricks",
}

#: Canonical id -> the pip distribution that provides its dbt adapter.
DBT_ADAPTER_PACKAGES: dict[str, str] = {
    AdapterName.FABRIC_WAREHOUSE.value: "dbt-fabric",
    AdapterName.DATABRICKS.value: "dbt-databricks",
}


def dbt_profile_type(adapter: str) -> str:
    """Return the ``profiles.yml`` ``type:`` key for one canonical adapter id."""
    canonical, _ = resolve_adapter(adapter)
    return DBT_PROFILE_TYPES[canonical]


def dbt_validate_extra(adapter: str) -> str:
    """Return the hub's optional-dependency extra that installs this dbt adapter.

    Keyed on dbt's vocabulary, not ours: the scaffolded ``pyproject.toml`` declares
    ``dbt-validate-fabric`` because the distribution is ``dbt-fabric``. DD-215 renamed the
    canonical adapter id to ``fabric-warehouse`` without renaming that extra, so composing
    the name as ``dbt-validate-{canonical}`` yields ``dbt-validate-fabric-warehouse``,
    which no hub declares -- and every hub already on disk declares the old spelling, so
    renaming the extra is not available either. Mapping through
    :data:`DBT_PROFILE_TYPES` is what keeps both working.
    """
    return f"dbt-validate-{dbt_profile_type(adapter)}"


#: Every spelling a CLI option accepts: canonical ids plus still-resolving aliases.
ADAPTER_CHOICES: tuple[str, ...] = SUPPORTED_ADAPTER_IDS + tuple(ADAPTER_ALIASES)

#: Convenience aliases for the literal comparisons dialect branches make.
FABRIC_WAREHOUSE = AdapterName.FABRIC_WAREHOUSE.value
DATABRICKS = AdapterName.DATABRICKS.value


class UnsupportedAdapterError(ValueError):
    """Raised for an adapter id that is not supported, with a reason when we have one."""

    def __init__(self, value: str, reason: str | None = None) -> None:
        supported = ", ".join(SUPPORTED_ADAPTER_IDS)
        detail = f": {reason}" if reason else ""
        super().__init__(f"Unsupported adapter {value!r}{detail}. Expected one of: {supported}")
        self.value = value
        self.reason = reason


def resolve_adapter(value: str) -> tuple[str, str | None]:
    """Resolve one authored adapter id to its canonical form.

    Returns ``(canonical_id, deprecation_message_or_None)``. Raises
    :class:`UnsupportedAdapterError` for anything unsupported -- there is no fallback and
    no default, so an unrecognised value can never be treated as Fabric.
    """
    text = str(value).strip()
    if text in SUPPORTED_ADAPTER_IDS:
        return text, None
    canonical = ADAPTER_ALIASES.get(text)
    if canonical is not None:
        return canonical, (
            f"adapter {text!r} is deprecated and now means {canonical!r}; "
            f"set 'adapter: {canonical}' in kairos.yaml to silence this"
        )
    raise UnsupportedAdapterError(text, RECOGNIZED_UNSUPPORTED.get(text))
