# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Column-level Gold projection control (issue #703, DD-217).

A Gold dimension mirrored its Silver model's full column set unconditionally, so
directly identifying personal data that reaches Silver for legitimate operational use
also reached the Power BI semantic model with no authorable way to stop it. Every
workaround was worse: unbinding the field removes it from Silver too, dropping the
dimension loses everything else in it, and `securityPolicy` is the right tool for
role-based hiding, not for "this column should never leave Silver".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import test_gold_projector as harness  # noqa: E402

from kairos_ontology.core.projections.dbt.gold_specs import GoldContractError  # noqa: E402

#: Emitted by `dim_client`, and the shape a hub would want kept out of Power BI.
_TARGET = "dim_client.city"


def _with_exclusions(tmp_path: Path, *values: str):
    """Regenerate the client Gold product with `goldExcludeColumn` values authored."""
    lines = "".join(f'    kairos-ext:goldExcludeColumn "{value}" ;\n' for value in values)
    text = harness._gold_text("client").replace(
        '    kairos-ext:goldSchema "gold" ;\n',
        '    kairos-ext:goldSchema "gold" ;\n' + lines,
        1,
    )
    return harness._generate("client", gold_path=harness._write_gold(tmp_path, "client", text))


def _tmdl(artifacts: dict[str, str]) -> str:
    return "\n".join(content for name, content in artifacts.items() if name.endswith(".tmdl"))


class TestGoldExcludeColumn:
    def test_the_column_is_absent_from_the_semantic_model(self, tmp_path):
        baseline = _tmdl(harness._generate("client"))
        assert "sourceColumn: city" in baseline, "fixture must emit the column to begin with"

        excluded = _tmdl(_with_exclusions(tmp_path, _TARGET))

        assert "sourceColumn: city" not in excluded

    def test_the_rest_of_the_dimension_survives(self, tmp_path):
        """The point of a column filter over dropping the whole dimension."""
        excluded = _tmdl(_with_exclusions(tmp_path, _TARGET))
        assert "sourceColumn: client_id" in excluded
        assert "sourceColumn: client_name" in excluded

    def test_matching_is_case_insensitive_on_the_table(self, tmp_path):
        """Mirrors `_table_aliases`, which already folds case."""
        excluded = _tmdl(_with_exclusions(tmp_path, "DIM_CLIENT.city"))
        assert "sourceColumn: city" not in excluded

    def test_several_columns_can_be_excluded(self, tmp_path):
        excluded = _tmdl(_with_exclusions(tmp_path, _TARGET, "dim_client.country"))
        assert "sourceColumn: city" not in excluded
        assert "sourceColumn: country" not in excluded
        assert "sourceColumn: client_id" in excluded

    def test_an_unknown_column_fails_closed(self, tmp_path):
        """A stale entry must not read as "successfully excluded" (#703).

        The whole value of the term is that the column stays out, so a Silver rename or a
        typo has to be reported rather than silently re-exposing the column. Mirrors
        `security.missing-column-binding`.
        """
        with pytest.raises(GoldContractError) as excinfo:
            _with_exclusions(tmp_path, "dim_client.no_such_column")
        assert excinfo.value.code == "gold.unknown-excluded-column"

    def test_an_unknown_table_fails_closed(self, tmp_path):
        with pytest.raises(GoldContractError) as excinfo:
            _with_exclusions(tmp_path, "dim_nowhere.city")
        assert excinfo.value.code == "gold.unknown-excluded-column"

    def test_a_malformed_value_fails_closed(self, tmp_path):
        with pytest.raises(GoldContractError) as excinfo:
            _with_exclusions(tmp_path, "city")
        assert excinfo.value.code == "gold.unknown-excluded-column"

    def test_authoring_nothing_changes_nothing(self, tmp_path):
        """Non-vacuity guard: the filter must be inert until it is authored."""
        assert _tmdl(harness._generate("client")) == _tmdl(_with_exclusions(tmp_path))


def test_the_vocabulary_declares_the_term():
    """The annotation has to exist for a hub to author it against the shipped kairos-ext."""
    from kairos_ontology.cli.shared import _SCAFFOLD_DIR

    text = (_SCAFFOLD_DIR / "kairos-ext.ttl").read_text(encoding="utf-8")
    assert "kairos-ext:goldExcludeColumn a owl:AnnotationProperty" in text
    assert "rdfs:domain owl:Ontology" in text
