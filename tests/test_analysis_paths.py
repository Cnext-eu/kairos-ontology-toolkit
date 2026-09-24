# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""`_analysis/` file names say what they are about (src-/dom-/hub. convention).

The old names mixed three keyings in one flat directory: ``tms-affinity.yaml`` is about a
source system, ``booking-alignment.yaml`` about an ontology domain, ``table-anchors.yaml``
about the whole hub. These pin the new names, the one-release fallback to the old ones,
and the rename ``update`` performs.
"""

from __future__ import annotations

import pytest

from kairos_ontology.core import analysis_paths as ap


class TestNames:
    def test_each_scope_is_visible_in_the_name(self, tmp_path):
        assert ap.keyed_path(tmp_path, ap.AFFINITY, "tms").name == "src-tms.affinity.yaml"
        assert (
            ap.keyed_path(tmp_path, ap.TABLE_DISPOSITIONS, "tms").name
            == "src-tms.table-dispositions.yaml"
        )
        assert ap.keyed_path(tmp_path, ap.ALIGNMENT, "booking").name == "dom-booking.alignment.yaml"
        assert ap.hub_path(tmp_path, ap.TABLE_ANCHORS).name == "hub.table-anchors.yaml"
        assert ap.hub_path(tmp_path, ap.GAP_DECISIONS).name == "hub.gap-decisions.yaml"

    def test_a_scope_mismatch_is_refused(self, tmp_path):
        with pytest.raises(ValueError):
            ap.hub_path(tmp_path, ap.AFFINITY)
        with pytest.raises(ValueError):
            ap.keyed_path(tmp_path, ap.TABLE_ANCHORS, "x")

    @pytest.mark.parametrize("key", ["tms", "acme-erp", "a.b"])
    def test_a_key_round_trips_under_both_conventions(self, tmp_path, key):
        new = ap.keyed_path(tmp_path, ap.AFFINITY, key)
        old = ap.legacy_keyed_path(tmp_path, ap.AFFINITY, key)
        assert ap.key_of(new, ap.AFFINITY) == key
        assert ap.key_of(old, ap.AFFINITY) == key

    def test_the_two_name_families_do_not_match_each_others_globs(self, tmp_path):
        """A new file must never be read a second time as a legacy one, and vice versa."""
        ap.keyed_path(tmp_path, ap.AFFINITY, "tms").write_text("{}", encoding="utf-8")
        assert list(tmp_path.glob("*-affinity.yaml")) == []
        ap.legacy_keyed_path(tmp_path, ap.AFFINITY, "erp").write_text("{}", encoding="utf-8")
        assert [p.name for p in tmp_path.glob("src-*.affinity.yaml")] == ["src-tms.affinity.yaml"]


class TestLegacyRead:
    def test_both_conventions_are_read_and_the_new_name_wins(self, tmp_path):
        ap.legacy_keyed_path(tmp_path, ap.ALIGNMENT, "booking").write_text("old", encoding="utf-8")
        ap.legacy_keyed_path(tmp_path, ap.ALIGNMENT, "party").write_text("old", encoding="utf-8")
        ap.keyed_path(tmp_path, ap.ALIGNMENT, "booking").write_text("new", encoding="utf-8")

        found = dict(ap.iter_keyed(tmp_path, ap.ALIGNMENT))

        assert set(found) == {"booking", "party"}
        assert found["booking"].name == "dom-booking.alignment.yaml"
        assert found["party"].name == "party-alignment.yaml"

    def test_a_hub_file_falls_back_to_its_old_name(self, tmp_path):
        assert ap.find_hub(tmp_path, ap.TABLE_ANCHORS) is None
        ap.legacy_hub_path(tmp_path, ap.TABLE_ANCHORS).write_text("x", encoding="utf-8")
        assert ap.read_hub_path(tmp_path, ap.TABLE_ANCHORS).name == "table-anchors.yaml"

    def test_writing_the_new_name_retires_the_old_twin(self, tmp_path):
        old = ap.legacy_keyed_path(tmp_path, ap.AFFINITY, "tms")
        old.write_text("old", encoding="utf-8")
        ap.keyed_path(tmp_path, ap.AFFINITY, "tms").write_text("new", encoding="utf-8")

        ap.retire_legacy_keyed(tmp_path, ap.AFFINITY, "tms")

        assert not old.exists()

    def test_retiring_never_removes_the_only_copy(self, tmp_path):
        old = ap.legacy_hub_path(tmp_path, ap.GAP_DECISIONS)
        old.write_text("only copy", encoding="utf-8")
        ap.retire_legacy_hub(tmp_path, ap.GAP_DECISIONS)
        assert old.exists()

    def test_a_missing_directory_reads_as_empty(self, tmp_path):
        assert ap.iter_keyed(tmp_path / "absent", ap.AFFINITY) == []


class TestUpdateRename:
    def _hub(self, tmp_path):
        (tmp_path / "model" / "ontologies").mkdir(parents=True)
        directory = ap.analysis_dir(tmp_path)
        directory.mkdir(parents=True)
        for name in (
            "tms-affinity.yaml",
            "booking-alignment.yaml",
            "booking-unresolved-anchors.yaml",
            "table-anchors.yaml",
            "gap-decisions.yaml",
            "affinity-matrix.yaml",
        ):
            (directory / name).write_text(name, encoding="utf-8")
        return tmp_path, directory

    def test_check_reports_and_changes_nothing(self, tmp_path, capsys):
        from kairos_ontology.cli.operations import _migrate_analysis_file_names

        hub, directory = self._hub(tmp_path)
        before = sorted(p.name for p in directory.iterdir())

        _migrate_analysis_file_names(hub, check=True)

        assert sorted(p.name for p in directory.iterdir()) == before
        out = capsys.readouterr().out
        assert "6 _analysis/ file(s)" in out
        assert "tms-affinity.yaml -> src-tms.affinity.yaml" in out

    def test_update_renames_every_file_and_keeps_content(self, tmp_path):
        from kairos_ontology.cli.operations import _migrate_analysis_file_names

        hub, directory = self._hub(tmp_path)

        _migrate_analysis_file_names(hub, check=False)

        assert sorted(p.name for p in directory.iterdir()) == [
            "dom-booking.alignment.yaml",
            "dom-booking.unresolved-anchors.yaml",
            "hub.affinity-matrix.yaml",
            "hub.gap-decisions.yaml",
            "hub.table-anchors.yaml",
            "src-tms.affinity.yaml",
        ]
        assert (directory / "src-tms.affinity.yaml").read_text(encoding="utf-8") == (
            "tms-affinity.yaml"
        )

    def test_a_second_run_is_silent(self, tmp_path, capsys):
        from kairos_ontology.cli.operations import _migrate_analysis_file_names

        hub, _directory = self._hub(tmp_path)
        _migrate_analysis_file_names(hub, check=False)
        capsys.readouterr()

        _migrate_analysis_file_names(hub, check=False)

        assert capsys.readouterr().out == ""

    def test_both_names_present_is_reported_and_left_alone(self, tmp_path, capsys):
        from kairos_ontology.cli.operations import _migrate_analysis_file_names

        hub, directory = self._hub(tmp_path)
        (directory / "src-tms.affinity.yaml").write_text("regenerated", encoding="utf-8")

        _migrate_analysis_file_names(hub, check=False)

        assert (directory / "tms-affinity.yaml").exists()
        assert (directory / "src-tms.affinity.yaml").read_text(encoding="utf-8") == "regenerated"
        assert "Both tms-affinity.yaml and src-tms.affinity.yaml exist" in capsys.readouterr().out


class TestUpdateSplitsTheLedger:
    """`update` splits the single ledger per source system (#943)."""

    def _hub(self, tmp_path):
        import yaml

        from kairos_ontology.core.source_disposition import DISPOSITIONS_RELPATH

        (tmp_path / "model" / "ontologies").mkdir(parents=True)
        path = tmp_path / DISPOSITIONS_RELPATH
        path.parent.mkdir(parents=True)
        path.write_text(yaml.safe_dump({"schema_version": 1, "tables": [
            {"system": "tms", "table": "a", "disposition": "deferred"},
            {"system": "tms", "table": "b", "column": "c", "disposition": "blueprint-gap"},
            {"system": "erp", "table": "x", "disposition": "not-business-data"},
        ]}), encoding="utf-8")
        return tmp_path, path

    def test_check_reports_the_split_and_changes_nothing(self, tmp_path, capsys):
        from kairos_ontology.cli.operations import _migrate_analysis_file_names

        hub, legacy = self._hub(tmp_path)
        _migrate_analysis_file_names(hub, check=True)

        assert legacy.exists()
        out = capsys.readouterr().out
        assert "will be split" in out and "3 entr(y/ies)" in out
        assert "tms: 2 -> src-tms.table-dispositions.yaml" in out

    def test_update_splits_and_keeps_every_entry(self, tmp_path):
        from kairos_ontology.cli.operations import _migrate_analysis_file_names
        from kairos_ontology.core.source_disposition import ledger_path, load_dispositions

        hub, legacy = self._hub(tmp_path)
        before = load_dispositions(hub)

        _migrate_analysis_file_names(hub, check=False)

        assert not legacy.exists()
        assert ledger_path(hub, "tms").is_file() and ledger_path(hub, "erp").is_file()
        assert load_dispositions(hub) == before
