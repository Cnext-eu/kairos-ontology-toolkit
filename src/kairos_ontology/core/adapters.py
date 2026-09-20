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


# ---------------------------------------------------------------------------
# The dbt stack this toolkit emits into (#789)
# ---------------------------------------------------------------------------
# These constraints were previously undeclared: they existed only as pins copied into
# the scaffolded ``pyproject.toml`` and were rediscovered by trial whenever a hub or a
# dataplatform broke. Both ends of the range are load-bearing and neither is arbitrary.
#
# FLOOR -- ``dbt-core>=1.10``. The v5 Silver path emits generic-test config under the
# dbt 1.10+ ``arguments:`` key (``projections/dbt/shape.py``'s ``_generic_test``). On dbt
# 1.9 that fails at parse with "macro '...' takes no keyword argument 'arguments'", so a
# hub pinned below 1.10 cannot parse the package this toolkit emits for it. That
# contradiction shipped: the scaffold pinned ``>=1.9,<1.10`` while the emitter had
# already moved.
#
# CEILING -- ``dbt-fabric==1.10.0``, exactly. 1.10.1 replaced pyodbc with mssql-python,
# which parses the connection string eagerly and rejects the ``Authority Id`` keyword
# that dbt-fabric derives from the ``ActiveDirectoryServicePrincipal`` auth mode used by
# ``dbt_validation._offline_profile``. pyodbc accepted the string and failed later at
# connect, which ``validate-dbt`` tolerates as ``environment-blocked``; mssql-python
# fails at parse, so the offline gate cannot pass on any dbt-fabric >= 1.10.1.
# Lifting this means changing the offline profile's auth mode -- tracked separately.
#
# The dbt-core range is the intersection that satisfies *both* adapters, so a hub and the
# dataplatform consuming its output can agree on one dbt-core. dbt-databricks pins
# dbt-core tightly and moves fast (1.10.19 requires ``dbt-core<1.10.20,>=1.10.1``), which
# is what sets the upper bound here rather than anything about dbt itself.
#
# Verify against PyPI metadata when changing these, never by assumption.
#
#: What the *emitted package* requires of whoever installs it. Floor only: the floor is
#: a property of the SQL and YAML this toolkit generates, whereas the ceiling below is
#: a property of one hub's offline validation gate. Putting the ceiling in the emitted
#: `require-dbt-version` would reject a dataplatform running a newer dbt with a
#: different adapter, which is none of this package's business.
#: Spelled with all three components on purpose. require-dbt-version is parsed by
#: dbt's own semver, not by pip's: a two-part >=1.10 is a valid pip specifier and an
#: invalid dbt one, and dbt rejects the whole project file with ">=1.10" is not a valid
#: semantic version" before it reads anything else. Every emitted project failed
#: dbt deps on that line (#888).
DBT_CORE_FLOOR = ">=1.10.0"

#: What a *scaffolded hub* installs: the intersection that satisfies every supported
#: adapter at once, so a hub and the dataplatform consuming its output can agree on one
#: dbt-core. Narrower than the floor by necessity, not by preference.
DBT_CORE_REQUIREMENT = ">=1.10.1,<1.10.20"

#: Canonical id -> the version specifier for its dbt adapter distribution.
DBT_ADAPTER_REQUIREMENTS: dict[str, str] = {
    AdapterName.FABRIC_WAREHOUSE.value: "==1.10.0",
    AdapterName.DATABRICKS.value: ">=1.10.19,<1.11",
}

#: dbt package -> version range emitted into the generated ``packages.yml``. The emitter
#: hard-codes call sites against these packages' APIs (``dbt_utils`` argument shapes, for
#: one), so the range is part of the toolkit's contract rather than a suggestion.
DBT_PACKAGE_REQUIREMENTS: dict[str, tuple[str, str]] = {
    "dbt-labs/dbt_utils": (">=1.0.0", "<2.0.0"),
    "metaplane/dbt_expectations": (">=0.10.0", "<1.0.0"),
}


def dbt_adapter_requirement(adapter: str) -> str:
    """Return the ``pip`` requirement string for one canonical adapter id."""
    canonical, _ = resolve_adapter(adapter)
    return f"{DBT_ADAPTER_PACKAGES[canonical]}{DBT_ADAPTER_REQUIREMENTS[canonical]}"


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
