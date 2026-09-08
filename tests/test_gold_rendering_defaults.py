# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Semantic-model rendering defaults (issue #744, DD-221).

The emitted TMDL used to hand a report author every column flat: surrogate keys, load
audit timestamps and FK match counts sat in the field list beside real business data, no
column was marked as the table's key, and the ontology's `rdfs:comment` -- the single
best piece of documentation the hub owns -- never reached the model at all.

None of that is authored policy, so none of it was fixable in a hub. These are the
projection's defaults, and this module pins them.

Everything here runs the v5 lane (`build_compile_plan` -> `generate_gold_from_compile_plan`),
which is what `emit-gold` calls. The legacy `generate_gold_artifacts` harness in
`test_gold_projector` builds from the ontology rather than a compiled Silver registry, so
it carries neither the generated technical columns nor the column descriptions this
module is about.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kairos_ontology.core.compiler.kernel import build_compile_plan
from kairos_ontology.core.projections.medallion_gold_projector import (
    generate_gold_from_compile_plan,
)

_V5_HUB = Path(__file__).parent / "scenarios" / "v5-hub"

_GOLD_EXT = """
@prefix party: <https://example.test/ontology/party#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

<https://example.test/ontology/party>
  kairos-ext:goldSchema "gold" ;
{extra}  kairos-ext:goldProductProfile "dimensional-powerbi-v1" .

party:Customer
  kairos-ext:goldTableType "dimension" ;
  kairos-ext:goldTableName "dim_customer" ;
  kairos-ext:goldSourceModel "customer" ;
  kairos-ext:goldSourceVersion "1.0.0" ;
  kairos-ext:dimensionExposure "current-only" ;
  kairos-ext:dimensionVersionBinding "current" .
"""


def _plan(tmp_path: Path, *, extra: str = ""):
    """Compile the `party` domain with *extra* authored on the Gold extension."""
    hub = tmp_path / "hub"
    shutil.copytree(_V5_HUB, hub)
    ext_dir = hub / "model" / "extensions"
    ext_dir.mkdir(parents=True, exist_ok=True)
    (ext_dir / "party-gold-ext.ttl").write_text(_GOLD_EXT.format(extra=extra), encoding="utf-8")
    return build_compile_plan(hub, "party")


def _emit(tmp_path: Path, *, extra: str = "") -> str:
    """Return the concatenated TMDL of the `party` Gold product."""
    artifacts = generate_gold_from_compile_plan(_plan(tmp_path, extra=extra))
    return "\n".join(content for name, content in artifacts.items() if name.endswith(".tmdl"))


def _blocking_message(tmp_path: Path, *, extra: str) -> str:
    """Return the rendered error diagnostics of a compile blocked by *extra*.

    A Gold contract failure reaches a caller as a blocked plan carrying the `gold.*` code
    of the `GoldContractError` that fired (#752; before that it was flattened into
    `safety.type-incompatible` with the code inside the message). Asserting on the raised
    `GoldContractError` would test the projector in isolation and miss the path an
    author actually hits, so this reads the plan's diagnostics as `--check` renders them.
    """
    plan = _plan(tmp_path, extra=extra)
    assert plan.blocked, "expected the authored value to block the compile"
    return "\n".join(
        diagnostic.render()
        for diagnostic in plan.diagnostics.ordered
        if str(getattr(diagnostic, "severity", "")).lower().endswith("error")
    )


def _hidden(*values: str) -> str:
    return "".join(f'  kairos-ext:goldHideColumn "{value}" ;\n' for value in values)


def _column_block(tmdl: str, name: str) -> str:
    """Return the lines of one ``column <name>`` block, up to its blank separator."""
    lines = tmdl.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == f"column {name}":
            block: list[str] = []
            for item in lines[index + 1 :]:
                if not item.strip():
                    break
                block.append(item.strip())
            return "\n".join(block)
    raise AssertionError(f"no column {name!r} in the emitted TMDL")


@pytest.fixture(scope="module")
def tmdl(tmp_path_factory) -> str:
    """The default emit, built once: a compile plan per test is needlessly slow."""
    return _emit(tmp_path_factory.mktemp("defaults"))


class TestTechnicalColumnsAreHidden:
    """Hidden, not excluded: the column stays in the model and keeps working."""

    def test_the_surrogate_key_is_hidden(self, tmdl):
        assert "isHidden" in _column_block(tmdl, "customer_sk")

    @pytest.mark.parametrize("name", ["_loaded_at", "_source_identity_ref"])
    def test_audit_and_source_identity_columns_are_hidden(self, tmdl, name):
        assert "isHidden" in _column_block(tmdl, name)

    def test_the_fk_match_count_diagnostic_is_hidden(self, tmdl):
        name = next(
            line.strip().removeprefix("column ")
            for line in tmdl.splitlines()
            if line.strip().startswith("column _kairos_fk_")
        )
        assert "isHidden" in _column_block(tmdl, name)

    @pytest.mark.parametrize("name", ["customer_id", "customer_name"])
    def test_business_columns_stay_visible(self, tmdl, name):
        assert "isHidden" not in _column_block(tmdl, name)

    def test_a_hidden_column_is_still_emitted(self, tmdl):
        """The distinction from `goldExcludeColumn` (DD-217), which removes it."""
        assert "sourceColumn: _loaded_at" in tmdl


class TestMappedForeignKeysStayVisible:
    """The compiler gives one role to two kinds of column; provenance separates them.

    The DD-133 generated `{target}_sk` and the DD-107 mapped column its join reads from
    are both `foreign-key`. Hiding the mapped one would take a business-readable code out
    of the field list -- the exact over-reach a role-only rule would cause.
    """

    def test_a_generated_surrogate_foreign_key_is_hidden(self, tmdl):
        assert "isHidden" in _column_block(tmdl, "country_sk")

    def test_the_mapped_column_it_joins_on_stays_visible(self, tmdl):
        assert "isHidden" not in _column_block(tmdl, "country_code")


class TestIsKey:
    def test_a_dimension_surrogate_key_is_marked(self, tmdl):
        assert "isKey" in _column_block(tmdl, "customer_sk")

    @pytest.mark.parametrize("name", ["customer_id", "customer_name", "country_code", "_loaded_at"])
    def test_no_other_column_is_marked(self, tmdl, name):
        """Power BI rejects a non-unique `isKey` at refresh, in the workspace, not in CI.

        `_primary_key` falls back to "first non-nullable column, else first column" when a
        table has no surrogate, so the marker is restricted to the case that is provably
        unique rather than trusting that fallback.
        """
        assert "isKey" not in _column_block(tmdl, name)


class TestColumnDescriptions:
    def test_the_ontology_comment_reaches_the_model(self, tmdl):
        """`///` is how TMDL carries a description into Desktop's field-list tooltip."""
        lines = tmdl.splitlines()
        index = lines.index("\tcolumn customer_sk")
        assert lines[index - 1].strip().startswith("///")

    def test_a_column_without_a_comment_gets_no_empty_marker(self, tmdl):
        assert "/// \n" not in tmdl
        assert not any(line.strip() == "///" for line in tmdl.splitlines())


class TestGoldHideColumn:
    """The authored escape hatch for a business-looking column this product won't browse."""

    def test_an_authored_column_is_hidden(self, tmdl, tmp_path):
        assert "isHidden" not in _column_block(tmdl, "customer_name")

        hidden = _emit(tmp_path, extra=_hidden("dim_customer.customer_name"))

        assert "isHidden" in _column_block(hidden, "customer_name")

    def test_the_column_is_still_emitted(self, tmp_path):
        hidden = _emit(tmp_path, extra=_hidden("dim_customer.customer_name"))
        assert "sourceColumn: customer_name" in hidden

    def test_matching_is_case_insensitive_on_the_table(self, tmp_path):
        hidden = _emit(tmp_path, extra=_hidden("DIM_CUSTOMER.customer_name"))
        assert "isHidden" in _column_block(hidden, "customer_name")

    def test_an_unknown_column_fails_closed(self, tmp_path):
        """A stale value must not read as "successfully hidden" after a Silver rename."""
        message = _blocking_message(tmp_path, extra=_hidden("dim_customer.no_such_column"))
        assert "gold.unknown-hidden-column" in message

    def test_hiding_an_already_excluded_column_fails_closed(self, tmp_path):
        """Two annotations fighting over one column: the author should hear about it."""
        message = _blocking_message(
            tmp_path,
            extra=(
                '  kairos-ext:goldExcludeColumn "dim_customer.customer_name" ;\n'
                '  kairos-ext:goldHideColumn "dim_customer.customer_name" ;\n'
            ),
        )
        assert "gold.unknown-hidden-column" in message
