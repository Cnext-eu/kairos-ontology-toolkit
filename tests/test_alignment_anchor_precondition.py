# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Anchoring is a precondition of alignment, and absence is no longer silent.

``propose_alignment.py`` read the anchors artifact and then said ``if global_anchors:``
with **no else branch**. ``load_table_anchors`` returns an empty mapping when the file is
absent, so a hub that never ran ``anchor-tables`` skipped the whole DD-185 regrouping
block in total silence and the run looked entirely normal.

What was lost is in the code's own comment at that line: *"this is what makes affinity a
prior rather than a constraint: a misplaced table is aligned in the domain whose classes
it actually needs."* Without anchors, affinity becomes a hard constraint. On the hub that
prompted this guard, 18 of 68 tables ended with an empty ``ref_class`` and **every** domain
with empty anchors scored 0% mapped.

The same file also carries the ``excluded`` block, so its absence silently disabled the
schema-catalogue screen too -- one missing file, two features quietly inert.

Modelled on ``--without-discovery``: refuse by default, proceed loudly when asked.
These tests also pin the three-way artifact signal, because a *corrupt* artifact needs
different advice from an absent one -- re-running ``anchor-tables`` would overwrite it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kairos_ontology.core.anchor_tables import (
    ArtifactState,
    MalformedLedgerError,
    load_affinity_domains,
    load_excluded_columns,
    load_excluded_tables,
    load_table_anchors,
    load_table_dispositions,
    probe_anchors,
)

ANCHORS = "table-anchors.yaml"
DISPOSITIONS = "table-dispositions.yaml"


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        payload if isinstance(payload, str) else yaml.safe_dump(payload),
        encoding="utf-8",
    )
    return path


class TestProbeAnchors:
    """The signal the guard is built on: *why* there are no anchors."""

    def test_missing_when_never_written(self, tmp_path):
        assert probe_anchors(tmp_path) == (ArtifactState.MISSING, 0)

    def test_present_with_a_count(self, tmp_path):
        _write(
            tmp_path / ANCHORS,
            {"tables": [{"system": "a", "table": "t1"}, {"system": "a", "table": "t2"}]},
        )
        assert probe_anchors(tmp_path) == (ArtifactState.PRESENT, 2)

    def test_empty_when_the_file_holds_no_tables(self, tmp_path):
        """Ran anchoring, anchored nothing -- different from never having run it."""
        _write(tmp_path / ANCHORS, {"tables": []})
        assert probe_anchors(tmp_path) == (ArtifactState.EMPTY, 0)

    def test_unparseable_is_distinct_from_missing(self, tmp_path):
        _write(tmp_path / ANCHORS, "tables: [oops: :\n  - broken")
        state, count = probe_anchors(tmp_path)
        assert state is ArtifactState.UNPARSEABLE
        assert count == 0

    def test_a_yaml_scalar_is_not_a_valid_artifact(self, tmp_path):
        """Parses fine as YAML, but a bare string has no tables to read."""
        _write(tmp_path / ANCHORS, "just a string")
        assert probe_anchors(tmp_path)[0] is ArtifactState.UNPARSEABLE


class TestUnparseableArtifactsWarn:
    """Three of these loaders swallowed a parse failure in total silence."""

    @pytest.mark.parametrize(
        "loader, filename",
        [
            (load_table_anchors, ANCHORS),
            (load_excluded_tables, ANCHORS),
        ],
    )
    def test_advisory_loaders_warn_and_degrade(self, tmp_path, caplog, loader, filename):
        _write(tmp_path / filename, "{{{ not yaml")
        with caplog.at_level("WARNING"):
            assert loader(tmp_path) == {}
        assert "Could not parse" in caplog.text

    def test_affinity_priors_warn_per_file(self, tmp_path, caplog):
        """Was a bare ``continue``: a corrupt affinity file vanished without trace."""
        _write(tmp_path / "alpha-affinity.yaml", "{{{ not yaml")
        with caplog.at_level("WARNING"):
            assert load_affinity_domains(tmp_path) == {}
        assert "Could not parse" in caplog.text

    def test_absent_files_are_quiet(self, tmp_path, caplog):
        """Absence is the normal case and must not warn -- only corruption does."""
        with caplog.at_level("WARNING"):
            assert load_table_anchors(tmp_path) == {}
            assert load_excluded_tables(tmp_path) == {}
            assert load_affinity_domains(tmp_path) == {}
            assert load_table_dispositions(tmp_path) == {}
            assert load_excluded_columns(tmp_path) == set()
        assert caplog.text == ""


class TestMalformedLedgerIsFatal:
    """The disposition ledger is human governance -- it must never be silently ignored.

    ``load_table_dispositions`` returned an empty mapping on a parse failure with no log
    line at all. Its docstring says every disposition other than ``not-business-data`` is
    someone having decided the table IS in scope, and that the function exists so a
    heuristic cannot overrule them -- so degrading to empty let the schema-catalogue
    screen quietly overrule a recorded human decision.
    """

    def test_table_dispositions_raises(self, tmp_path):
        _write(tmp_path / DISPOSITIONS, "tables: [: :")
        with pytest.raises(MalformedLedgerError, match="could not be parsed"):
            load_table_dispositions(tmp_path)

    def test_column_exclusions_raises(self, tmp_path):
        _write(tmp_path / DISPOSITIONS, "tables: [: :")
        with pytest.raises(MalformedLedgerError, match="could not be parsed"):
            load_excluded_columns(tmp_path)

    def test_the_error_says_what_to_do(self, tmp_path):
        _write(tmp_path / DISPOSITIONS, "tables: [: :")
        with pytest.raises(MalformedLedgerError) as exc:
            load_table_dispositions(tmp_path)
        message = str(exc.value)
        assert DISPOSITIONS in message
        assert "Fix the YAML" in message
        assert "move the file aside" in message

    def test_a_well_formed_ledger_still_reads(self, tmp_path):
        _write(
            tmp_path / DISPOSITIONS,
            {"tables": [{"system": "a", "table": "t1", "disposition": "deferred"}]},
        )
        assert load_table_dispositions(tmp_path) == {("a", "t1"): "deferred"}

    def test_an_absent_ledger_is_the_normal_case(self, tmp_path):
        assert load_table_dispositions(tmp_path) == {}
        assert load_excluded_columns(tmp_path) == set()


class TestAlignmentRefusesWithoutAnchors:
    """The guard itself, at the ``_propose_alignments`` boundary."""

    def _message(self, tmp_path, state_setup=None):
        from kairos_ontology.core.propose_alignment import _missing_anchors_message

        if state_setup:
            state_setup(tmp_path)
        state, _ = probe_anchors(tmp_path)
        return state, _missing_anchors_message(tmp_path, state)

    def test_missing_artifact_message_says_run_anchor_tables(self, tmp_path):
        state, message = self._message(tmp_path)
        assert state is ArtifactState.MISSING
        assert "never written" in message
        assert "kairos-ontology anchor-tables" in message
        assert "--without-anchors" in message

    def test_unparseable_message_does_not_say_re_run(self, tmp_path):
        """Re-running would overwrite the file, so the advice has to differ."""
        state, message = self._message(
            tmp_path, lambda p: _write(p / ANCHORS, "{{{ not yaml")
        )
        assert state is ArtifactState.UNPARSEABLE
        assert "could not be parsed" in message

    def test_empty_message_names_the_emptiness(self, tmp_path):
        state, message = self._message(
            tmp_path, lambda p: _write(p / ANCHORS, {"tables": []})
        )
        assert state is ArtifactState.EMPTY
        assert "no anchored tables" in message

    def test_the_message_explains_the_consequence_not_just_the_rule(self, tmp_path):
        """A refusal an operator cannot act on is a worse defect than the silence."""
        _, message = self._message(tmp_path)
        assert "hard constraint" in message
        assert "0% mapped" in message


class TestCliExposesTheOptOut:
    def test_flag_is_documented(self):
        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli

        out = CliRunner().invoke(cli, ["propose-alignment", "--help"]).output
        assert "--without-anchors" in out
        # Click hard-wraps help text, so collapse whitespace before matching a phrase.
        flat = " ".join(out.split())
        # The help text has to say why refusing is the default, or the flag reads as
        # an arbitrary obstacle and gets pasted into every command line.
        assert "anchor-tables has not been run" in flat
        assert "full class catalog" in flat
