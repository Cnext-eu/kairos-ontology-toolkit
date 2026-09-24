# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The dataplatform's advisory post-deploy BPA notebook (DD-238, issue #982).

Some Best Practice Analyzer rules can only be answered by a deployed model with data --
cardinality, referential-integrity violations, Direct Lake guardrails and fallback. The
dataplatform deploy workflow publishes this Fabric notebook and runs it after the
semantic model is live. It is read-only over the model (DD-206) and never blocks the
deploy: its findings are authored back in the hub, never fixed in the deployed model.

Semantic Link Labs evaluates its own rule set, keyed by rule *name*, and does not honour
the ``BestPracticeAnalyzer_IgnoreRules`` annotation the emitter writes. So the notebook
carries the Kairos profile with it: it maps each finding to its Microsoft rule ID and
this toolkit's disposition for the model's target, and marks what the model's own
annotations excuse. That map is generated from ``bpa_profile``, so the two cannot drift;
``scripts/generate_bpa_profile.py`` rewrites the template and a test fails when stale.

The ``semantic-link-labs`` pin lives here and moves only with a toolkit release, as part
of the same manual refresh as the vendored rules (DD-238).
"""

from __future__ import annotations

import json
from pathlib import Path

from .bpa_profile import (
    PROFILE,
    PROFILE_VERSION,
    UPSTREAM_COMMIT,
    Target,
    load_upstream_rules,
)

#: Pinned, and bumped only by a toolkit release (DD-238). Verified against 0.17.1:
#: ``run_model_bpa(return_dataframe=, extended=)``, ``directlake.get_direct_lake_guardrails``,
#: ``directlake.check_fallback_reason``, ``tom.connect_semantic_model``,
#: ``save_as_delta_table``, ``format_dax_object_name``, ``create_relationship_name``.
SEMANTIC_LINK_LABS_PIN = "0.17.1"

#: The notebook's Fabric item name, which the deploy workflow looks up after publishing.
NOTEBOOK_DISPLAY_NAME = "Kairos Model BPA"

#: Where the dataplatform keeps it, relative to the repository root.
NOTEBOOK_DIR = "fabric/KairosModelBpa.Notebook"

_SCAFFOLD_DIR = (
    Path(__file__).resolve().parents[3] / "scaffold" / "dataplatform" / "fabric" / "KairosModelBpa.Notebook"
)
NOTEBOOK_TEMPLATE = _SCAFFOLD_DIR / "notebook-content.py.template"
PLATFORM_TEMPLATE = _SCAFFOLD_DIR / ".platform.template"

#: A fixed logicalId: fabric-cicd matches items across workspaces by it, so it must not
#: change between toolkit releases or every refresh would publish a new notebook.
_LOGICAL_ID = "5f1d8c2a-3b7e-4e0a-9c41-6a2b8e7d0f38"


def _normalise(name: str) -> str:
    """Upstream prefixes each name with ``[Category] ``; Semantic Link Labs does not."""
    name = name.strip()
    if name.startswith("[") and "]" in name:
        name = name.split("]", 1)[1]
    return " ".join(name.lower().rstrip(".").split())


def notebook_profile() -> dict:
    """The rule map the notebook embeds: normalised rule name -> ID and dispositions."""
    names = {rule["ID"]: rule["Name"] for rule in load_upstream_rules()}
    return {
        "version": PROFILE_VERSION,
        "upstreamCommit": UPSTREAM_COMMIT,
        "rules": {
            _normalise(names[item.rule_id]): {
                "id": item.rule_id,
                Target.FABRIC.value: item.fabric.label(Target.FABRIC),
                Target.DATABRICKS.value: item.databricks.label(Target.DATABRICKS),
            }
            for item in PROFILE
        },
    }


_META_PYTHON = """# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
"""

_BODY = '''import json

import pandas as pd
import sempy_labs as labs
from sempy_labs import directlake
from sempy_labs.tom import connect_semantic_model

KAIROS_PROFILE = json.loads(r"""__PROFILE__""")
IGNORE = "BestPracticeAnalyzer_IgnoreRules"
target = "fabric" if semantic_mode == "directLake" else "databricks"
workspace = workspace or None


def normalise(name):
    name = name.strip()
    if name.startswith("[") and "]" in name:
        name = name.split("]", 1)[1]
    return " ".join(name.lower().rstrip(".").split())


def excused_by_annotation():
    """(object type, object name, rule ID) the model's own annotations excuse."""
    found = set()
    with connect_semantic_model(dataset=dataset, workspace=workspace, readonly=True) as tom:

        def record(kind, name, obj):
            value = tom.get_annotation_value(object=obj, name=IGNORE)
            for rule in (json.loads(value).get("RuleIDs", []) if value else []):
                found.add((kind, name, rule))

        record("Model", "Model", tom.model)
        for table in tom.model.Tables:
            record("Table", table.Name, table)
        for column in tom.all_columns():
            record("Column", labs.format_dax_object_name(column.Parent.Name, column.Name), column)
        for measure in tom.all_measures():
            record("Measure", measure.Name, measure)
        for rel in tom.model.Relationships:
            name = labs.create_relationship_name(
                rel.FromTable.Name, rel.FromColumn.Name, rel.ToTable.Name, rel.ToColumn.Name
            )
            record("Relationship", name, rel)
    return found


try:
    findings = labs.run_model_bpa(
        dataset=dataset, workspace=workspace, extended=True, return_dataframe=True
    ).reset_index()
except Exception as exc:  # no XMLA read access, a Pro workspace, a paused capacity
    findings = None
    print("Best Practice Analyzer skipped:", exc)

if findings is not None:
    excused = excused_by_annotation()
    rules = KAIROS_PROFILE["rules"]

    def classify(row):
        entry = rules.get(normalise(row["Rule Name"]))
        rule_id = entry["id"] if entry else ""
        disposition = entry[target] if entry else "unprofiled"
        if rule_id and (row["Object Type"], row["Object Name"], rule_id) in excused:
            disposition = "excused-by-annotation"
        return pd.Series({"Rule ID": rule_id, "Kairos Disposition": disposition})

    findings = findings.join(findings.apply(classify, axis=1))
    findings["Semantic Model"] = dataset
    findings["Kairos Profile"] = KAIROS_PROFILE["version"]
    expected = ("rejected", "not-applicable", "excused")
    actionable = findings[~findings["Kairos Disposition"].str.startswith(expected)]
    print(
        len(findings),
        "finding(s);",
        len(actionable),
        "to review. Fix them in the ontology hub and re-release; never edit the deployed model.",
    )
    display(actionable)
    try:
        labs.save_as_delta_table(
            findings.rename(columns=lambda name: name.lower().replace(" ", "_")),
            "kairos_bpa_findings",
            write_mode="append",
            merge_schema=True,
        )
    except Exception as exc:  # no default lakehouse attached to this run
        print("Findings not persisted to a lakehouse table:", exc)

if semantic_mode == "directLake":
    for label, check in (
        ("guardrails", lambda: directlake.get_direct_lake_guardrails()),
        ("fallback", lambda: directlake.check_fallback_reason(dataset=dataset, workspace=workspace)),
    ):
        try:
            display(check())
        except Exception as exc:
            print("Direct Lake", label, "check skipped:", exc)
'''


def render_notebook_content() -> str:
    """Render ``notebook-content.py`` in Fabric's notebook source format.

    Free of ``{identifier}`` text on purpose: `update --refresh-workflows` reads any such
    token as an unresolved scaffold placeholder and will not install a missing file that
    holds one, which is why the body prints with arguments rather than f-strings.
    """
    profile = json.dumps(notebook_profile(), sort_keys=True, separators=(",", ":"))
    return "\n".join(
        [
            "# Fabric notebook source",
            "",
            "# METADATA ********************",
            "",
            "# META {",
            '# META   "kernel_info": {',
            '# META     "name": "synapse_pyspark"',
            "# META   },",
            '# META   "dependencies": {}',
            "# META }",
            "",
            "# MARKDOWN ********************",
            "",
            "# # Kairos advisory Best Practice Analyzer run",
            "# ",
            "# Generated by the Kairos ontology toolkit (DD-238). Refresh it with",
            "# `kairos-ontology update --refresh-workflows`; do not edit it here.",
            "# ",
            "# Read-only over the semantic model, and never blocks a deploy. Findings are",
            "# advisory: fix them in the ontology hub and re-release.",
            "",
            "# CELL ********************",
            "",
            f"%pip install semantic-link-labs=={SEMANTIC_LINK_LABS_PIN}",
            "",
            _META_PYTHON,
            "# PARAMETERS CELL ********************",
            "",
            'dataset = ""',
            'workspace = ""',
            'semantic_mode = "directLake"',
            "",
            _META_PYTHON,
            "# CELL ********************",
            "",
            _BODY.replace("__PROFILE__", profile),
            _META_PYTHON,
        ]
    )


def render_platform() -> str:
    """Render the notebook item's ``.platform`` file."""
    document = {
        "$schema": (
            "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/"
            "platformProperties/2.0.0/schema.json"
        ),
        "metadata": {"type": "Notebook", "displayName": NOTEBOOK_DISPLAY_NAME},
        "config": {"version": "2.0", "logicalId": _LOGICAL_ID},
    }
    return json.dumps(document, indent=2) + "\n"
