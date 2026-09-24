# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The Kairos-owned Power BI Best Practice Analyzer profile (DD-238, issue #976).

Microsoft's BPA rule set (``BPARules.json`` in microsoft/Analysis-Services) is what the BI
community measures a semantic model against. Running it wholesale in hub CI does not work:
Tabular Editor 2's CLI is Windows-only, the cross-platform ``te`` CLI is a paid preview,
Semantic Link Labs only reads a *deployed* model, and about a third of the rules either do
not apply to Direct Lake or DirectQuery, need VertiPaq statistics a generator cannot see,
or contradict a decision this toolkit already made (DD-221, DD-226).

So the toolkit owns a curated profile instead. Every upstream rule ID gets exactly one
disposition per target, with a reason:

* ``by-construction`` -- the emitter cannot produce a violation;
* ``compile-diagnostic`` -- ``compile --check`` reports it with a stable code;
* ``render-assert`` -- ``gold_assert`` refuses to emit a model that breaks it;
* ``post-deploy-advisory`` -- only a deployed model with data can answer it, so the
  dataplatform's advisory Semantic Link Labs run reports it and never blocks;
* ``not-applicable:<target>`` -- the rule cannot fire on that storage mode;
* ``rejected:<DD>`` -- it contradicts a recorded decision.

The upstream file is vendored at a pinned commit, the same pattern as ``fabric_schema/``,
so compile stays offline and deterministic (DD-133). It is not a versioned package -- it
lives on ``master`` with no releases -- so it is refreshed **by hand**: re-vendor the
file, update ``UPSTREAM_COMMIT``/``UPSTREAM_REFRESHED``, and triage whatever
``tests/test_bpa_profile.py`` then reports. Each rule's digest is recorded below, so a
rule Microsoft *changes* fails the suite exactly like a rule it adds.

Regenerate the guide after editing this file::

    uv run python scripts/generate_bpa_profile.py
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from functools import cache
from pathlib import Path

#: Where the vendored rules came from. The file on ``master`` has no releases, so the
#: commit is the only stable identity it has.
UPSTREAM_REPOSITORY = "microsoft/Analysis-Services"
UPSTREAM_PATH = "BestPracticeRules/BPARules.json"
UPSTREAM_COMMIT = "50e8ce5028dd7046e73974ec69cb79af225e41b0"
#: When that commit landed upstream, and when it was last vendored and triaged here.
UPSTREAM_COMMITTED = "2026-01-21"
UPSTREAM_REFRESHED = "2026-09-24"

#: Bumped whenever a disposition changes, so a provenance sidecar (DD-218) says which
#: profile judged the model it describes.
PROFILE_VERSION = "1"

#: The vendored copy. Line endings are normalised to LF by ``.gitattributes``; the
#: per-rule digests are over parsed JSON, so that is not a change to any rule.
RULES_PATH = Path(__file__).parent / "bpa_rules" / "BPARules.json"

#: The TMDL annotation Tabular Editor and Semantic Link Labs both honour.
IGNORE_ANNOTATION = "BestPracticeAnalyzer_IgnoreRules"


class Target(str, Enum):
    """The two storage modes a Kairos Gold semantic model is emitted for."""

    #: Direct Lake over OneLake Delta tables.
    FABRIC = "fabric"
    #: DirectQuery over ``Databricks.Catalogs``, published to a Power BI workspace.
    DATABRICKS = "databricks"


def target_for_semantic_mode(semantic_mode: str) -> Target:
    """Map a physical plan's ``semantic_mode`` to its profile target."""
    return Target.FABRIC if semantic_mode == "directLake" else Target.DATABRICKS


class DispositionKind(str, Enum):
    BY_CONSTRUCTION = "by-construction"
    COMPILE_DIAGNOSTIC = "compile-diagnostic"
    RENDER_ASSERT = "render-assert"
    POST_DEPLOY_ADVISORY = "post-deploy-advisory"
    NOT_APPLICABLE = "not-applicable"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class Disposition:
    kind: DispositionKind
    reason: str
    #: The decision a ``rejected`` rule contradicts, e.g. ``DD-221``.
    decision: str = ""
    #: The diagnostic code or assertion that enforces it, when there is one.
    enforced_by: str = ""
    #: Only high-precision checks block (DD-163); everything else warns or advises.
    blocking: bool = False

    def label(self, target: Target) -> str:
        if self.kind is DispositionKind.REJECTED:
            return f"rejected:{self.decision}"
        if self.kind is DispositionKind.NOT_APPLICABLE:
            return f"not-applicable:{target.value}"
        return self.kind.value


@dataclass(frozen=True, slots=True)
class RuleProfile:
    rule_id: str
    #: First 12 hex digits of the sha256 of the upstream rule's canonical JSON. Empty
    #: for a Kairos-owned rule, which has no upstream definition.
    upstream_digest: str
    fabric: Disposition
    databricks: Disposition

    def disposition(self, target: Target) -> Disposition:
        return self.fabric if target is Target.FABRIC else self.databricks


_BC = DispositionKind.BY_CONSTRUCTION
_CD = DispositionKind.COMPILE_DIAGNOSTIC
_RA = DispositionKind.RENDER_ASSERT
_PD = DispositionKind.POST_DEPLOY_ADVISORY
_NA = DispositionKind.NOT_APPLICABLE
_RJ = DispositionKind.REJECTED


def _rule(rule_id: str, digest: str, fabric: Disposition, databricks: Disposition | None = None):
    return RuleProfile(rule_id, digest, fabric, databricks if databricks is not None else fabric)


def _d(kind: DispositionKind, reason: str, **kwargs) -> Disposition:
    return Disposition(kind, reason, **kwargs)


_NO_CALCULATED = (
    "The emitter never writes calculated columns or calculated tables; Direct Lake does "
    "not support them and every Gold column is a Silver column."
)
_VERTIPAQ = (
    "Needs VertiPaq statistics that only exist once the model is deployed and refreshed, "
    "so it runs in the dataplatform's advisory Semantic Link Labs step."
)
_AUTHORED_DAX = (
    "A property of authored DAX the compiler does not parse. Reported by the advisory "
    "post-deploy run; the fix is an edit to the measure in the hub, never in the "
    "deployed model (DD-206, DD-224)."
)
_STATIC_ADVISORY = (
    "Checkable statically, but not a defect often enough to gate on (DD-163). Reported by "
    "the advisory post-deploy run so a reviewer can decide."
)

PROFILE: tuple[RuleProfile, ...] = (
    _rule(
        "AVOID_FLOATING_POINT_DATA_TYPES",
        "e0c7696f3c7e",
        _d(
            _CD,
            "A Gold column of canonical type float64 renders as Double. Warned at compile "
            "time: the fix is the ontology or Silver type, which the author owns.",
            enforced_by="gold.float-column",
        ),
    ),
    _rule(
        "ISAVAILABLEINMDX_FALSE_NONATTRIBUTE_COLUMNS",
        "58d65c7dd369",
        _d(
            _PD,
            "Hidden columns keep IsAvailableInMdx at its default. Turning it off saves "
            "attribute-hierarchy memory but changes every hub's TMDL, so it is reported "
            "rather than rendered until a decision records the model change.",
        ),
    ),
    _rule(
        "AVOID_BI-DIRECTIONAL_RELATIONSHIPS_AGAINST_HIGH-CARDINALITY_COLUMNS",
        "d359568cc1a0",
        _d(_PD, _VERTIPAQ),
    ),
    _rule(
        "REDUCE_USAGE_OF_LONG-LENGTH_COLUMNS_WITH_HIGH_CARDINALITY",
        "6973b1aab4bc",
        _d(_PD, _VERTIPAQ),
    ),
    _rule("SPLIT_DATE_AND_TIME", "7e3096795611", _d(_PD, _VERTIPAQ)),
    _rule(
        "LARGE_TABLES_SHOULD_BE_PARTITIONED",
        "95b6946d4dcc",
        _d(
            _NA,
            "A Direct Lake partition is one entity partition over a Delta table; the table "
            "is partitioned in the lakehouse, not in the model.",
        ),
        _d(
            _NA,
            "A DirectQuery partition holds no data, so model partitioning has nothing to "
            "split; the warehouse table is partitioned in Databricks.",
        ),
    ),
    _rule(
        "REDUCE_USAGE_OF_CALCULATED_COLUMNS_THAT_USE_THE_RELATED_FUNCTION",
        "52797cd36c6b",
        _d(_BC, _NO_CALCULATED),
    ),
    _rule(
        "SNOWFLAKE_SCHEMA_ARCHITECTURE",
        "0295777217b8",
        _d(
            _RJ,
            "Whether a dimension references another is decided by the canonical ontology, "
            "not by the renderer. Flattening is authored (product scope, goldExcludeColumn) "
            "and surplus filter paths are already deactivated by DD-226.",
            decision="DD-238",
        ),
    ),
    _rule(
        "MODEL_SHOULD_HAVE_A_DATE_TABLE",
        "7c66b811ee76",
        _d(
            _RA,
            "Every product with an approved calendar emits dim_date marked as a date table "
            "with its DateTime key; the assertion checks both on the rendered table. A "
            "product with no date role has no calendar to emit.",
            enforced_by="gold.date-table-not-marked",
            blocking=True,
        ),
    ),
    _rule(
        "DATE/CALENDAR_TABLES_SHOULD_BE_MARKED_AS_A_DATE_TABLE",
        "dfd8a2dbd3d1",
        _d(
            _RA,
            "Asserted on the generated dim_date. The rule also matches any table whose "
            "name merely contains DATE (e.g. an 'update' log); such a table is not a "
            "calendar and takes an authored bpaIgnoreRule.",
            enforced_by="gold.date-table-not-marked",
            blocking=True,
        ),
    ),
    _rule(
        "REMOVE_AUTO-DATE_TABLE",
        "4177be473abe",
        _d(
            _BC,
            "Auto date tables are calculated tables, which neither Direct Lake nor "
            "DirectQuery models create, and the emitter never writes one.",
        ),
    ),
    _rule(
        "AVOID_EXCESSIVE_BI-DIRECTIONAL_OR_MANY-TO-MANY_RELATIONSHIPS",
        "0130705c059a",
        _d(
            _PD,
            "A model-wide ratio. Every bidirectional edge the emitter writes is a recorded "
            "DD-238 bridge decision, so a small model with one bridge can cross the 30% "
            "line legitimately; reported for review rather than gated.",
        ),
    ),
    _rule(
        "LIMIT_ROW_LEVEL_SECURITY_(RLS)_LOGIC",
        "c9cb02337da4",
        _d(
            _BC,
            "Emitted RLS filters are the fail-closed FALSE() placeholder; the entitlement "
            "logic is bound in the workspace, not string-built in TMDL.",
        ),
    ),
    _rule(
        "MODEL_USING_DIRECT_QUERY_AND_NO_AGGREGATIONS",
        "5ca701a6ea9e",
        _d(_NA, "Direct Lake tables are not DirectQuery tables."),
        _d(
            _PD,
            "Every Databricks table is DirectQuery and the emitter authors no aggregation "
            "tables. Whether one is worth adding depends on query volume, which only the "
            "deployed model shows.",
        ),
    ),
    _rule(
        "MINIMIZE_POWER_QUERY_TRANSFORMATIONS",
        "78c6dbd24513",
        _d(_NA, "Direct Lake partitions are entity partitions, not M queries."),
        _d(
            _BC,
            "The only M the emitter writes navigates Databricks.Catalogs to one table; "
            "every transformation lives in dbt.",
        ),
    ),
    _rule(
        "AVOID_USING_MANY-TO-MANY_RELATIONSHIPS_ON_TABLES_USED_FOR_DYNAMIC_ROW_LEVEL_SECURITY",
        "a28a84dba9e1",
        _d(
            _BC,
            "The emitter writes no many-to-many relationship: a bridge is two many-to-one "
            "edges (DD-238).",
        ),
    ),
    _rule(
        "UNPIVOT_PIVOTED_(MONTH)_DATA",
        "33fa4045fe5d",
        _d(
            _RJ,
            "Column names come from ontology properties, where a pivoted month layout is a "
            "design defect caught in review. The heuristic also matches any name holding "
            "'jan', 'feb' and 'mar' substrings, such as a 'market' column.",
            decision="DD-238",
        ),
    ),
    _rule(
        "MANY-TO-MANY_RELATIONSHIPS_SHOULD_BE_SINGLE-DIRECTION",
        "9874455c579c",
        _d(
            _BC,
            "No emitted relationship is many-to-many; the bidirectional bridge edge is "
            "many-to-one (DD-238).",
        ),
    ),
    _rule("REDUCE_USAGE_OF_CALCULATED_TABLES", "8a9bbfc2e29a", _d(_BC, _NO_CALCULATED)),
    _rule(
        "REMOVE_REDUNDANT_COLUMNS_IN_RELATED_TABLES",
        "d2ab1d4f1331",
        _d(
            _RJ,
            "Silver lineage and audit columns (_source_system, _loaded_at, ...) are carried "
            "on every table by design and hidden by DD-221. Removing one from Gold is "
            "goldExcludeColumn's job, decided per product.",
            decision="DD-221",
        ),
    ),
    _rule(
        "MEASURES_USING_TIME_INTELLIGENCE_AND_MODEL_IS_USING_DIRECT_QUERY",
        "6f6bf8ddc0a9",
        _d(_NA, "Direct Lake tables are not DirectQuery tables."),
        _d(
            _PD,
            "The emitted Time Intelligence calculation group uses DATESYTD/QTD/MTD, which "
            "cost a warehouse round trip per query in DirectQuery. Whether that is "
            "acceptable depends on query volume, so it is reported, not gated.",
        ),
    ),
    _rule("REDUCE_NUMBER_OF_CALCULATED_COLUMNS", "c908d0ed12a9", _d(_BC, _NO_CALCULATED)),
    _rule(
        "CHECK_IF_BI-DIRECTIONAL_AND_MANY-TO-MANY_RELATIONSHIPS_ARE_VALID",
        "6a01326065de",
        _d(
            _BC,
            "Every bidirectional edge is a DD-238 bridge decision -- the default or an "
            "authored goldRelationshipCrossFilter -- and carries the ignore annotation "
            "recording that it was checked.",
        ),
    ),
    _rule(
        "CHECK_IF_DYNAMIC_ROW_LEVEL_SECURITY_(RLS)_IS_NECESSARY",
        "958c513eb39f",
        _d(_BC, "Emitted RLS filters are FALSE(); none calls USERNAME or USERPRINCIPALNAME."),
    ),
    _rule(
        "DAX_COLUMNS_FULLY_QUALIFIED",
        "7b56e7f14a15",
        _d(
            _CD,
            "An unqualified column reference in a measure resolves against the home table "
            "only by accident of placement. Blocking: the check is exact for bracketed "
            "names the measure declares as column dependencies.",
            enforced_by="gold.dax-column-unqualified",
            blocking=True,
        ),
    ),
    _rule(
        "DAX_MEASURES_UNQUALIFIED",
        "3ed8028e87dd",
        _d(
            _CD,
            "A table-qualified measure reference breaks when the measure moves home table. "
            "Blocking: exact for references to declared measure dependencies.",
            enforced_by="gold.dax-measure-qualified",
            blocking=True,
        ),
    ),
    _rule("AVOID_DUPLICATE_MEASURES", "c2898287143f", _d(_PD, _STATIC_ADVISORY)),
    _rule("USE_THE_TREATAS_FUNCTION_INSTEAD_OF_INTERSECT", "653f78b887e3", _d(_PD, _AUTHORED_DAX)),
    _rule(
        "USE_THE_DIVIDE_FUNCTION_FOR_DIVISION",
        "a76e7fc89e05",
        _d(
            _CD,
            "Warned, never blocking: '/' is correct wherever the denominator cannot be "
            "zero, and the upstream regex cannot tell.",
            enforced_by="gold.dax-division-operator",
        ),
    ),
    _rule("AVOID_USING_THE_IFERROR_FUNCTION", "f73c3c68cc19", _d(_PD, _AUTHORED_DAX)),
    _rule(
        "MEASURES_SHOULD_NOT_BE_DIRECT_REFERENCES_OF_OTHER_MEASURES",
        "818b7634bd0a",
        _d(_PD, _AUTHORED_DAX),
    ),
    _rule("FILTER_COLUMN_VALUES", "98a9f139d708", _d(_PD, _AUTHORED_DAX)),
    _rule("FILTER_MEASURE_VALUES_BY_COLUMNS", "b7ba709300f7", _d(_PD, _AUTHORED_DAX)),
    _rule(
        "INACTIVE_RELATIONSHIPS_THAT_ARE_NEVER_ACTIVATED",
        "49bf31aa3df4",
        _d(
            _RJ,
            "Surplus filter paths are deactivated deliberately and kept for USERELATIONSHIP; "
            "every one is listed in gold_product_report under deactivated_relationships.",
            decision="DD-226",
        ),
    ),
    _rule("AVOID_USING_'1-(X/Y)'_SYNTAX", "24225a88d2d1", _d(_PD, _AUTHORED_DAX)),
    _rule(
        "EVALUATEANDLOG_SHOULD_NOT_BE_USED_IN_PRODUCTION_MODELS",
        "ffed128a541d",
        _d(_PD, _AUTHORED_DAX),
    ),
    _rule(
        "DATA_COLUMNS_MUST_HAVE_A_SOURCE_COLUMN",
        "bc04052a0ac2",
        _d(
            _BC,
            "Every emitted data column names its Silver column as sourceColumn; asserted "
            "on the rendered TMDL.",
            enforced_by="gold.column-source-missing",
        ),
    ),
    _rule(
        "EXPRESSION_RELIANT_OBJECTS_MUST_HAVE_AN_EXPRESSION",
        "91dd01e14b22",
        _d(
            _BC,
            "Only measures past lifecycle 'intent' are emitted, and those require an "
            "expression (DD-113); asserted on the rendered TMDL.",
            enforced_by="gold.measure-expression-missing",
        ),
    ),
    _rule(
        "AVOID_STRUCTURED_DATA_SOURCES_WITH_PROVIDER_PARTITIONS",
        "9ee1033ca285",
        _d(_BC, "The emitter writes no data source objects and no query partitions."),
    ),
    _rule(
        "AVOID_THE_USERELATIONSHIP_FUNCTION_AND_RLS_AGAINST_THE_SAME_TABLE",
        "dacef46f3056",
        _d(_PD, _AUTHORED_DAX),
    ),
    _rule(
        "RELATIONSHIP_COLUMNS_SAME_DATA_TYPE",
        "b065cb2c39ff",
        _d(
            _RA,
            "Direct Lake refuses a relationship between columns of different types, and "
            "DirectQuery joins them with an implicit cast. Blocking on every active "
            "relationship, exact on the rendered column types. An inactive edge left by an "
            "unproven key (#794) is reported by the post-deploy run instead.",
            enforced_by="gold.relationship-type-mismatch",
            blocking=True,
        ),
    ),
    _rule(
        "AVOID_INVALID_NAME_CHARACTERS",
        "a34132690e2c",
        _d(
            _BC,
            "Table and column names are Silver identifiers; a measure display name with a "
            "control character is rejected at compile time.",
            enforced_by="gold.measure-display-name-invalid",
        ),
    ),
    _rule(
        "AVOID_INVALID_DESCRIPTION_CHARACTERS",
        "6dc1564c8736",
        _d(
            _BC,
            "Descriptions pass through the TMDL text escape, which drops control "
            "characters; asserted on the rendered TMDL.",
            enforced_by="gold.description-control-character",
        ),
    ),
    _rule(
        "SET_ISAVAILABLEINMDX_TO_TRUE_ON_NECESSARY_COLUMNS",
        "6f0449400a90",
        _d(_BC, "The emitter never sets IsAvailableInMdx to false."),
    ),
    _rule(
        "UNNECESSARY_COLUMNS",
        "cc69b44a137b",
        _d(
            _RJ,
            "Hidden technical columns are kept on purpose: they carry lineage and can be "
            "bound by a security role. Removal is goldExcludeColumn's decision.",
            decision="DD-221",
        ),
    ),
    _rule(
        "UNNECESSARY_MEASURES",
        "87cc10b11f3c",
        _d(_BC, "The emitter never hides a measure or a table that holds one."),
    ),
    _rule("FIX_REFERENTIAL_INTEGRITY_VIOLATIONS", "b901cd69f518", _d(_PD, _VERTIPAQ)),
    _rule(
        "REMOVE_DATA_SOURCES_NOT_REFERENCED_BY_ANY_PARTITIONS",
        "f3c3fdab5c62",
        _d(_BC, "The emitter writes no data source objects."),
    ),
    _rule(
        "REMOVE_ROLES_WITH_NO_MEMBERS",
        "2afff7c19ca7",
        _d(
            _RJ,
            "Role membership is assigned in the workspace, never in source-controlled "
            "TMDL, so every emitted role has no members by design.",
            decision="DD-238",
        ),
    ),
    _rule("ENSURE_TABLES_HAVE_RELATIONSHIPS", "e45060b534ad", _d(_PD, _STATIC_ADVISORY)),
    _rule(
        "OBJECTS_WITH_NO_DESCRIPTION",
        "82ff9a9dd8c0",
        _d(
            _CD,
            "Measures always carry measureDefinition. A visible column without an ontology "
            "rdfs:comment is warned, because the description is what a report author reads "
            "in the field list. Tables and the calculation group carry no description yet; "
            "the post-deploy run reports those.",
            enforced_by="gold.description-missing",
        ),
    ),
    _rule(
        "PERSPECTIVES_WITH_NO_OBJECTS",
        "a50baf2a4732",
        _d(
            _BC,
            "A perspective is emitted only from the tables that declare it, listing each "
            "table's columns and measures as members.",
        ),
    ),
    _rule(
        "CALCULATION_GROUPS_WITH_NO_CALCULATION_ITEMS",
        "e324115de1df",
        _d(
            _RA,
            "The Time Intelligence group always emits its four items; the calculation-group "
            "assertions check items, ordinals and partition.",
            enforced_by="gold.calculation-group-ordinals",
            blocking=True,
        ),
    ),
    _rule(
        "PARTITION_NAME_SHOULD_MATCH_TABLE_NAME_FOR_SINGLE_PARTITION_TABLES",
        "6e3e116ee84a",
        _d(_BC, "Every emitted partition is named after its table."),
    ),
    _rule(
        "SPECIAL_CHARS_IN_OBJECT_NAMES",
        "7a5cc873d552",
        _d(
            _BC,
            "Identifiers cannot hold tabs or line breaks, and a measure display name that "
            "does is rejected at compile time.",
            enforced_by="gold.measure-display-name-invalid",
        ),
    ),
    _rule(
        "TRIM_OBJECT_NAMES",
        "204181e58d90",
        _d(
            _BC,
            "Identifiers cannot hold spaces; a measure display name with leading or "
            "trailing whitespace is rejected at compile time.",
            enforced_by="gold.measure-display-name-invalid",
        ),
    ),
    _rule(
        "FORMAT_FLAG_COLUMNS_AS_YES/NO_VALUE_STRINGS",
        "74b8cadada2b",
        _d(
            _BC,
            "Flags are Boolean-typed columns, and snake_case names never start with the "
            "capitalised 'Is' the rule matches.",
        ),
    ),
    _rule(
        "OBJECTS_SHOULD_NOT_START_OR_END_WITH_A_SPACE",
        "0976ebe7649f",
        _d(
            _BC,
            "Same guarantee as TRIM_OBJECT_NAMES.",
            enforced_by="gold.measure-display-name-invalid",
        ),
    ),
    _rule(
        "DATECOLUMN_FORMATSTRING",
        "59447eb1fefe",
        _d(
            _RJ,
            "Demands the US 'mm/dd/yyyy' format. Date display follows the model culture, "
            "which comes from the approved calendar's locale.",
            decision="DD-238",
        ),
    ),
    _rule(
        "MONTHCOLUMN_FORMATSTRING",
        "8f3ac5076a96",
        _d(
            _RJ,
            "Demands one fixed English format for any DateTime column whose name contains "
            "'month'; display follows the model culture.",
            decision="DD-238",
        ),
    ),
    _rule(
        "PROVIDE_FORMAT_STRING_FOR_MEASURES",
        "a8b96ecb450d",
        _d(
            _BC,
            "measureFormatString is mandatory past lifecycle 'intent' (DD-113); asserted "
            "on the rendered TMDL.",
            enforced_by="gold.measure-format-missing",
        ),
    ),
    _rule(
        "NUMERIC_COLUMN_SUMMARIZE_BY",
        "02cb267c588d",
        _d(
            _BC,
            "Every visible emitted column, dim_date's included, carries summarizeBy: none; "
            "asserted on the rendered TMDL.",
            enforced_by="gold.column-summarized",
        ),
    ),
    _rule(
        "PERCENTAGE_FORMATTING",
        "bc7c7d7dedc5",
        _d(
            _RJ,
            "A house style for percentages. The format string is an authored business "
            "decision (measureFormatString), not a defect.",
            decision="DD-238",
        ),
    ),
    _rule(
        "INTEGER_FORMATTING",
        "1f2b9fe57208",
        _d(
            _RJ,
            "Despite its name it demands '#,0' or '#,0.0' of every measure that is not "
            "currency or a percentage, decimals included. The format is authored.",
            decision="DD-238",
        ),
    ),
    _rule(
        "RELATIONSHIP_COLUMNS_SHOULD_BE_OF_INTEGER_DATA_TYPE",
        "aad102cfbc6f",
        _d(
            _RJ,
            "Surrogate keys are deterministic hashes (DD-133), and role-playing dates join "
            "dim_date on the date itself. Type equality, which the engine does require, is "
            "asserted by RELATIONSHIP_COLUMNS_SAME_DATA_TYPE.",
            decision="DD-238",
        ),
    ),
    _rule("ADD_DATA_CATEGORY_FOR_COLUMNS", "af48d3317719", _d(_PD, _STATIC_ADVISORY)),
    _rule(
        "HIDE_FOREIGN_KEYS",
        "e59fc5c948a7",
        _d(
            _PD,
            "Generated join keys are hidden by DD-221. A role-playing date column stays "
            "visible because it is the business date on the row; a product that prefers "
            "dim_date hides it with goldHideColumn.",
        ),
    ),
    _rule(
        "MARK_PRIMARY_KEYS",
        "30b8720d3da2",
        _d(
            _RJ,
            "isKey is emitted only where uniqueness is proven. Power BI rejects a "
            "non-unique key at refresh, in the workspace, so an unproven key stays "
            "unmarked.",
            decision="DD-221",
        ),
    ),
    _rule(
        "HIDE_FACT_TABLE_COLUMNS",
        "5e7645ee15e6",
        _d(
            _PD,
            "Whether a fact column aggregated by a measure should leave the field list is "
            "a product decision; the design skill asks it and goldHideColumn records it.",
        ),
    ),
    _rule(
        "FIRST_LETTER_OF_OBJECTS_MUST_BE_CAPITALIZED",
        "040956a8a445",
        _d(
            _RJ,
            "Tables and columns keep their Silver snake_case identifiers, which every "
            "authored DAX expression references. Measures carry an authored display name.",
            decision="DD-221",
        ),
    ),
    _rule(
        "MONTH_(AS_A_STRING)_MUST_BE_SORTED",
        "8a845326b4a6",
        _d(
            _BC,
            "dim_date.month_name sorts by month_number; asserted on the rendered TMDL. A "
            "Silver string column whose name merely contains 'month' takes an authored "
            "bpaIgnoreRule.",
            enforced_by="gold.calendar-unsorted",
        ),
    ),
)

#: Checks Kairos adds beyond Microsoft's file. Scoped like upstream rules so an authored
#: exception can name them, but they have no upstream digest.
KAIROS_RULES: tuple[tuple[RuleProfile, frozenset[str]], ...] = (
    (
        _rule(
            "KAIROS_DIRECT_LAKE_GUARDRAILS",
            "",
            _d(
                _PD,
                "Row and file counts against the capacity's Direct Lake guardrails; "
                "sempy_labs.directlake.get_direct_lake_guardrails after deploy.",
            ),
            _d(_NA, "DirectQuery has no Direct Lake guardrails."),
        ),
        frozenset({"Model"}),
    ),
    (
        _rule(
            "KAIROS_DIRECT_LAKE_FALLBACK",
            "",
            _d(
                _PD,
                "A Delta source that is a SQL view, or exceeds a guardrail, silently falls "
                "back to DirectQuery; sempy_labs.directlake.check_fallback_reason after "
                "deploy.",
            ),
            _d(_NA, "DirectQuery has no fallback."),
        ),
        frozenset({"Table"}),
    ),
    (
        _rule(
            "KAIROS_RELY_ON_REFERENTIAL_INTEGRITY",
            "",
            _d(_NA, "relyOnReferentialIntegrity only affects DirectQuery joins."),
            _d(
                _RJ,
                "Assuming referential integrity turns the join into an inner join. A "
                "declared unique key proves the one side, not that every many-side key "
                "resolves: Silver leaves an unmatched foreign key null, and an inner join "
                "would silently drop those fact rows from every total.",
                decision="DD-238",
            ),
        ),
        frozenset({"Relationship"}),
    ),
)


@cache
def load_upstream_rules() -> tuple[dict, ...]:
    """Return the vendored upstream rules, in file order."""
    return tuple(json.loads(RULES_PATH.read_text(encoding="utf-8-sig")))


def rule_digest(rule: dict) -> str:
    """Return the recorded digest form of one upstream rule definition."""
    canonical = json.dumps(rule, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def all_rules() -> tuple[RuleProfile, ...]:
    return PROFILE + tuple(item for item, _ in KAIROS_RULES)


@cache
def _by_id() -> dict[str, RuleProfile]:
    return {item.rule_id: item for item in all_rules()}


def disposition(rule_id: str, target: Target) -> Disposition:
    """Return *rule_id*'s disposition on *target*; ``KeyError`` for an unknown rule."""
    return _by_id()[rule_id].disposition(target)


@cache
def rule_scopes(rule_id: str) -> frozenset[str]:
    """Return the TOM object types *rule_id* applies to; empty for an unknown rule."""
    for rule in load_upstream_rules():
        if rule["ID"] == rule_id:
            return frozenset(item.strip() for item in rule.get("Scope", "").split(","))
    for item, scopes in KAIROS_RULES:
        if item.rule_id == rule_id:
            return scopes
    return frozenset()


def profile_stamp() -> dict[str, str]:
    """Return what a provenance sidecar records about the profile that judged a model."""
    return {"version": PROFILE_VERSION, "upstreamCommit": UPSTREAM_COMMIT}


def ignore_annotation(rule_ids, *, indent: str) -> list[str]:
    """Render the ``BestPracticeAnalyzer_IgnoreRules`` annotation, or nothing.

    Sorted and de-duplicated so the bytes are a function of the set, not of the order
    the renderer happened to collect it in.
    """
    ids = sorted(set(rule_ids))
    if not ids:
        return []
    payload = json.dumps({"RuleIDs": ids}, separators=(",", ":"), ensure_ascii=False)
    return [f"{indent}annotation {IGNORE_ANNOTATION} = {payload}"]


# ---------------------------------------------------------------------------
# Authored exceptions (kairos-ext:bpaIgnoreRule)
# ---------------------------------------------------------------------------

#: The object an exception is attached to, and the TOM scopes each kind can carry.
IGNORE_OBJECT_SCOPES: dict[str, frozenset[str]] = {
    "model": frozenset({"Model"}),
    "table": frozenset({"Table", "CalculatedTable"}),
    "column": frozenset({"DataColumn", "CalculatedColumn", "CalculatedTableColumn"}),
    "measure": frozenset({"Measure"}),
    "relationship": frozenset({"Relationship"}),
}

_IGNORE = re.compile(
    r"^(?P<rule>\S+)\s+on\s+(?P<kind>model|table|column|measure|relationship)"
    r"(?:\s+(?P<target>[^:]+?))?\s*:\s*(?P<reason>\S.*)$",
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class BpaIgnore:
    """One authored ``kairos-ext:bpaIgnoreRule`` exception, parsed."""

    rule_id: str
    kind: str
    #: Table name, ``table.column``, measure ID or ``T.c -> T.c``; empty for the model.
    target: str
    reason: str
    source: str


class BpaIgnoreError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def parse_bpa_ignore(value: str) -> BpaIgnore:
    """Parse ``"<RULE_ID> on <kind> [<target>]: <reason>"``, failing closed.

    The reason is mandatory. DD-234: an escape from a gate is a registered claim that
    someone looked and decided, not a suppression list, and a claim with no rationale
    is not reviewable.
    """
    match = _IGNORE.match(value.strip())
    if match is None:
        raise BpaIgnoreError(
            "gold.bpa-ignore-malformed",
            (
                f"bpaIgnoreRule {value!r} must read "
                '"<RULE_ID> on <model|table|column|measure|relationship> [<target>]: '
                '<reason>"'
            ),
        )
    rule_id = match.group("rule")
    kind = match.group("kind")
    target = (match.group("target") or "").strip()
    if not rule_scopes(rule_id):
        raise BpaIgnoreError(
            "gold.bpa-unknown-rule",
            f"bpaIgnoreRule {value!r} names {rule_id!r}, which is not a rule in the BPA profile",
        )
    if not rule_scopes(rule_id) & IGNORE_OBJECT_SCOPES[kind]:
        raise BpaIgnoreError(
            "gold.bpa-ignore-wrong-scope",
            (
                f"bpaIgnoreRule {value!r}: {rule_id} applies to "
                f"{', '.join(sorted(rule_scopes(rule_id)))}, never to a {kind}"
            ),
        )
    if (kind == "model") != (not target):
        raise BpaIgnoreError(
            "gold.bpa-ignore-malformed",
            (
                f"bpaIgnoreRule {value!r}: 'model' takes no target and every other kind "
                "names one"
            ),
        )
    return BpaIgnore(rule_id, kind, target, match.group("reason").strip(), value)


# ---------------------------------------------------------------------------
# Generated guide
# ---------------------------------------------------------------------------


def render_profile_markdown() -> str:
    """Render ``docs/guide/BPA_PROFILE.md``. Deterministic: no clock, no environment."""
    upstream = {rule["ID"]: rule for rule in load_upstream_rules()}
    lines = [
        "# Power BI Best Practice Analyzer profile",
        "",
        "<!-- Generated by `python scripts/generate_bpa_profile.py`. Do not edit by hand. -->",
        "",
        "Kairos judges every emitted semantic model against Microsoft's Best Practice "
        "Analyzer rules through this curated profile (DD-238). Each rule has exactly one "
        "disposition per target:",
        "",
        "| Disposition | Meaning |",
        "|---|---|",
        "| `by-construction` | The emitter cannot produce a violation. |",
        "| `compile-diagnostic` | `compile --check` reports it; **blocking** ones fail the plan. |",
        "| `render-assert` | `emit-gold` and `package-powerbi-release` refuse to emit a model "
        "that breaks it. |",
        "| `post-deploy-advisory` | Reported by the dataplatform's advisory Semantic Link Labs "
        "run after deploy; never blocks. |",
        "| `not-applicable:<target>` | Cannot fire on that storage mode. |",
        "| `rejected:<DD>` | Contradicts a recorded decision. |",
        "",
        "Targets: **fabric** is Direct Lake over OneLake; **databricks** is DirectQuery over "
        "`Databricks.Catalogs`, published to a Power BI workspace.",
        "",
        "An exception is authored in the Gold extension on the `owl:Ontology` resource, and "
        "is emitted as the `BestPracticeAnalyzer_IgnoreRules` annotation that Tabular "
        "Editor and Semantic Link Labs honour:",
        "",
        "```turtle",
        '<ontology> kairos-ext:bpaIgnoreRule "DAX_COLUMNS_FULLY_QUALIFIED on measure '
        'sales.margin: reason the rule does not hold here" .',
        "```",
        "",
        "## Snapshot",
        "",
        f"- Upstream: `{UPSTREAM_REPOSITORY}` `{UPSTREAM_PATH}`",
        f"- Commit: `{UPSTREAM_COMMIT}` ({UPSTREAM_COMMITTED})",
        f"- Last refreshed and triaged: {UPSTREAM_REFRESHED}",
        f"- Profile version: {PROFILE_VERSION}",
        f"- Rules: {len(PROFILE)} upstream, {len(KAIROS_RULES)} Kairos-owned",
        "",
        "The snapshot is refreshed by hand; see the `kairos-toolkit-ops` release checklist.",
        "",
        "## Rules",
        "",
        "| Rule | Severity | fabric | databricks | Enforced by | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for item in all_rules():
        rule = upstream.get(item.rule_id)
        severity = str(rule.get("Severity", "")) if rule else "kairos"
        fabric = item.fabric.label(Target.FABRIC)
        databricks = item.databricks.label(Target.DATABRICKS)
        if item.fabric.blocking:
            fabric += " (blocking)"
        if item.databricks.blocking:
            databricks += " (blocking)"
        enforced = {item.fabric.enforced_by, item.databricks.enforced_by} - {""}
        reasons = [item.fabric.reason]
        if item.databricks.reason != item.fabric.reason:
            reasons = [f"fabric: {item.fabric.reason}", f"databricks: {item.databricks.reason}"]
        lines.append(
            "| `{}` | {} | {} | {} | {} | {} |".format(
                item.rule_id,
                severity,
                fabric,
                databricks,
                ", ".join(f"`{code}`" for code in sorted(enforced)),
                " ".join(reasons).replace("|", "\\|"),
            )
        )
    lines.append("")
    return "\n".join(lines)
