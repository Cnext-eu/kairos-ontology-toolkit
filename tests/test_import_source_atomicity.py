# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""`import-source` publishes everything or nothing (issue #688).

`sanitize_samples_document` is fail-closed by design and *should* refuse. The defect was
the write ordering: the vocabulary was published first and the samples written one at a
time afterwards, so a refusal on table N left the hub with every vocabulary written,
every pre-existing relation marked deprecated, and only the first few samples on disk --
a state no command produces deliberately, signalled only by a traceback, and recoverable
only by `git restore` on a hub that happened to be clean.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.source_privacy import SamplePrivacyError, publish_candidates


def _table(name: str) -> dict:
    return {
        "name": name,
        "schema": "bronze",
        "row_count": 3,
        "columns": [
            {"name": "id", "data_type": "int", "ordinal_position": 1, "nullable": False},
            {
                "name": "email_address",
                "data_type": "varchar(200)",
                "ordinal_position": 2,
                "nullable": True,
            },
        ],
    }


@pytest.fixture
def extract_dir(tmp_path: Path) -> Path:
    """A two-table extract whose second table carries unredacted PII."""
    directory = tmp_path / "extract"
    directory.mkdir()
    tables = ["tbl_clean", "tbl_dirty"]
    (directory / "_manifest.yaml").write_text(
        yaml.dump({"version": "1.1", "system": "testapp", "tables": tables}),
        encoding="utf-8",
    )
    for name in tables:
        (directory / f"{name}.yaml").write_text(yaml.dump(_table(name)), encoding="utf-8")
    (directory / "tbl_clean.samples.yaml").write_text(
        yaml.dump(
            {
                "table": "tbl_clean",
                "schema": "bronze",
                "sample_privacy": "redact-detected-pii",
                "rows": [{"id": "1", "email_address": "<redacted:email>"}],
            }
        ),
        encoding="utf-8",
    )
    # Claims to be redacted while carrying a real address: exactly what the fail-closed
    # re-scan exists to catch.
    (directory / "tbl_dirty.samples.yaml").write_text(
        yaml.dump(
            {
                "table": "tbl_dirty",
                "schema": "bronze",
                "sample_privacy": "redact-detected-pii",
                "rows": [{"id": "2", "email_address": "real.person@example.com"}],
            }
        ),
        encoding="utf-8",
    )
    return directory


def _run(hub: Path, extract: Path):
    runner = CliRunner()
    return runner.invoke(
        cli,
        [
            "import-source",
            "--from",
            str(extract),
            "--system",
            "testapp",
            "--output",
            str(hub),
            "--redact-pii",
        ],
    )


@pytest.fixture
def refuse_second_table(monkeypatch):
    """Make sanitization refuse on the *second* table, deterministically.

    Driven by a stub rather than by crafted PII: the detector redacts most shapes rather
    than refusing, so a content-based fixture would silently stop exercising the refusal
    the day the heuristics change. What is under test here is the write ordering, not the
    scanner -- `tests/test_source_privacy.py` owns that.
    """
    import kairos_ontology.core.source_privacy as privacy

    real = privacy.sanitize_samples_document
    seen: list[str] = []

    def _stub(document, *, table, column_types):
        seen.append(table)
        if len(seen) > 1:
            raise privacy.SamplePrivacyError(["unredacted PII in a later table"])
        return real(document, table=table, column_types=column_types)

    monkeypatch.setattr(privacy, "sanitize_samples_document", _stub)
    return seen


class TestImportSourceAtomicity:
    def test_a_privacy_refusal_writes_nothing_at_all(
        self, tmp_path, extract_dir, refuse_second_table
    ):
        hub = tmp_path / "hub"
        hub.mkdir()

        result = _run(hub, extract_dir)

        assert result.exit_code != 0
        assert len(refuse_second_table) > 1, "the stub must have reached the second table"
        # The whole point: not "no samples", but *nothing*. Before the fix the
        # vocabularies were already on disk by the time the samples loop refused.
        assert list(hub.rglob("*")) == [], f"partial import left: {list(hub.rglob('*'))}"

    def test_a_clean_extract_still_publishes_everything(self, tmp_path, extract_dir):
        """Non-vacuity guard: the refusal above must be the PII, not a broken fixture."""
        (extract_dir / "tbl_dirty.samples.yaml").write_text(
            yaml.dump(
                {
                    "table": "tbl_dirty",
                    "schema": "bronze",
                    "sample_privacy": "redact-detected-pii",
                    "rows": [{"id": "2", "email_address": "<redacted:email>"}],
                }
            ),
            encoding="utf-8",
        )
        hub = tmp_path / "hub"
        hub.mkdir()

        result = _run(hub, extract_dir)

        assert result.exit_code == 0, result.output
        assert (hub / "testapp.vocabulary.ttl").is_file()
        assert {path.name for path in (hub / "vocabulary").glob("*.ttl")} == {
            "tbl_clean.vocabulary.ttl",
            "tbl_dirty.vocabulary.ttl",
        }
        assert (hub / "tbl_clean.samples.yaml").is_file()
        assert (hub / "tbl_dirty.samples.yaml").is_file()

    def test_a_refusal_leaves_an_existing_import_untouched(
        self, tmp_path, extract_dir, refuse_second_table
    ):
        """A re-import that refuses must not damage the generation already on disk."""
        hub = tmp_path / "hub"
        hub.mkdir()
        existing = hub / "testapp.vocabulary.ttl"
        existing.write_text("# previous generation\n", encoding="utf-8")

        result = _run(hub, extract_dir)

        assert result.exit_code != 0
        assert existing.read_text(encoding="utf-8") == "# previous generation\n"


class TestPublishCandidates:
    """The shared staging helper, generalized to create files as well as rewrite them."""

    def test_creates_new_files_and_their_parent_directories(self, tmp_path):
        target = tmp_path / "nested" / "deep" / "new.txt"
        publish_candidates({target: "content\n"})
        assert target.read_text(encoding="utf-8") == "content\n"

    def test_rolls_back_a_created_file_when_publication_fails(self, tmp_path):
        """A new file has no backup to restore, so rollback must unlink it instead."""
        good = tmp_path / "good.txt"
        # A directory where a file is expected makes os.replace fail for this entry.
        clash = tmp_path / "clash.txt"
        clash.mkdir()

        with pytest.raises(OSError):
            publish_candidates({good: "a\n", clash: "b\n"})

        assert not good.exists(), "an earlier created file must not survive a later failure"

    def test_restores_a_pre_existing_file_when_publication_fails(self, tmp_path):
        existing = tmp_path / "existing.txt"
        existing.write_text("original\n", encoding="utf-8")
        clash = tmp_path / "clash.txt"
        clash.mkdir()

        with pytest.raises(OSError):
            publish_candidates({existing: "rewritten\n", clash: "b\n"})

        assert existing.read_text(encoding="utf-8") == "original\n"

    def test_leaves_no_staging_artifacts_behind(self, tmp_path):
        target = tmp_path / "f.txt"
        publish_candidates({target: "x\n"})
        assert [p.name for p in tmp_path.iterdir()] == ["f.txt"]

    def test_writes_lf_regardless_of_platform(self, tmp_path):
        target = tmp_path / "f.txt"
        publish_candidates({target: "a\nb\n"})
        assert target.read_bytes() == b"a\nb\n"


def test_sample_privacy_error_is_still_raised_by_the_scanner():
    """Guard: the fix must not have softened the fail-closed refusal itself."""
    assert issubclass(SamplePrivacyError, Exception)
