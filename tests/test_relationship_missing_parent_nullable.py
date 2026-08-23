# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Regression coverage for #609.

A relationship's ``missingParent: null`` policy allows an unresolved foreign key: the
generated dbt SQL does a genuine ``left join`` and the resulting ``_sk`` column can be a
real SQL ``NULL`` when there is no match. ``core/compiler/kernel.py::_wire_relationships``
already computed the correct ``nullable``/``tests`` for this FK ``ColumnSpec``, but the
Silver authority builder (``core/projections/dbt/policy_normalize.py``) re-derived role
and nullability from scratch: it never recognized the wired column as a
``FOREIGN_KEY`` (matching only by local-join-column name, never the emitted ``_sk``
column), so it fell through to ``SURROGATE_JOIN_KEY``, which is unconditionally hard-coded
``NOT NULL`` regardless of the relationship's actual missing-parent policy.

This was invisible for the common ``missingParent: error`` case, since that happens to
land on ``NOT NULL`` via the broken path too -- the divergence only surfaces once a
relationship actually declares ``missingParent: null``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from kairos_ontology.core.compiler import CompileMode, compile_domain

from .test_relationship_fk_collision import _hub_with_colliding_relationship


def test_missing_parent_null_renders_nullable_fk_ddl_and_schema(tmp_path: Path) -> None:
    """#609: missingParent: null must emit a nullable `_sk` column, matching the
    dbt `left join` runtime behavior, in both the DDL analysis file and schema.yml."""
    hub = _hub_with_colliding_relationship(tmp_path)
    result = compile_domain(hub, "party", CompileMode.EMIT)
    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    artifacts = result.artifact_dict()

    ddl = artifacts["analyses/party/party-ddl.sql"]
    fk_line = next(
        line
        for line in ddl.splitlines()
        if line.strip().startswith("secondary_country_country_sk")
    )
    assert "NOT NULL" not in fk_line

    schema = yaml.safe_load(artifacts["models/silver/party/_party__models.yml"])
    customer = next(model for model in schema["models"] if model["name"] == "customer")
    column = next(c for c in customer["columns"] if c["name"] == "secondary_country_country_sk")
    assert column["meta"]["silver_role"] == "foreign-key"
    assert column["meta"]["nullable"] == "true"
    assert "not_null" not in column.get("tests", ())


def test_missing_parent_error_still_renders_not_null_fk_ddl_and_schema(tmp_path: Path) -> None:
    """Companion no-regression check: missingParent: error (the pre-existing
    party:country relationship) must keep emitting NOT NULL / not_null."""
    hub = _hub_with_colliding_relationship(tmp_path)
    result = compile_domain(hub, "party", CompileMode.EMIT)
    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    artifacts = result.artifact_dict()

    ddl = artifacts["analyses/party/party-ddl.sql"]
    fk_line = next(
        line for line in ddl.splitlines() if line.strip().startswith("country_country_sk")
    )
    assert "NOT NULL" in fk_line

    schema = yaml.safe_load(artifacts["models/silver/party/_party__models.yml"])
    customer = next(model for model in schema["models"] if model["name"] == "customer")
    column = next(c for c in customer["columns"] if c["name"] == "country_country_sk")
    assert column["meta"]["silver_role"] == "foreign-key"
    assert column["meta"]["nullable"] == "false"
    assert "not_null" in column.get("tests", ())
