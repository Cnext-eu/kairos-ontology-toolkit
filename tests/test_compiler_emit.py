# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for deterministic, manifest-owned v5 compiler emission."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

from kairos_ontology.core.compiler import (
    EMIT_MANIFEST_NAME,
    EMIT_MANIFEST_SCHEMA,
    ArtifactCollisionError,
    ArtifactPathError,
    EmissionBusyError,
    EmissionError,
    EmissionRollbackError,
    ManifestError,
    emit_artifacts,
    plan_emission,
)

emit_module = importlib.import_module("kairos_ontology.core.compiler.emit")


def _manifest(target: Path) -> dict:
    return json.loads((target / EMIT_MANIFEST_NAME).read_text(encoding="utf-8"))


def test_plan_is_deterministic_sorted_and_ignores_render_metadata():
    first = plan_emission(
        {
            "models/z.sql": "select 2\n",
            "__render_metadata__": {"generated_at": "ignored"},
            "__anything": object(),
            "models/a.sql": "select 1\n",
        }
    )
    second = plan_emission(
        {
            "models/a.sql": "select 1\n",
            "models/z.sql": "select 2\n",
        }
    )

    assert first == second
    assert first.paths == ("models/a.sql", "models/z.sql")
    document = json.loads(first.manifest)
    assert document["schema"] == EMIT_MANIFEST_SCHEMA
    assert [item["path"] for item in document["files"]] == list(first.paths)
    assert "generated_at" not in first.manifest.decode()
    assert first.manifest.endswith(b"\n")


@pytest.mark.parametrize(
    "path",
    [
        "",
        ".",
        "..",
        "../outside.sql",
        "models/../outside.sql",
        "models/./customer.sql",
        "models//customer.sql",
        "/absolute.sql",
        r"C:\outside.sql",
        r"\\server\share\outside.sql",
        "models/customer.sql/",
        "models/\x00customer.sql",
        EMIT_MANIFEST_NAME,
        EMIT_MANIFEST_NAME.upper(),
        "models/customer.sql:stream",
        "models/customer?.sql",
        "models/customer.sql.",
        "models/customer.sql ",
        "models/NUL.txt",
        "models/com1",
    ],
)
def test_plan_rejects_unsafe_or_reserved_paths(path: str):
    with pytest.raises(ArtifactPathError):
        plan_emission({path: "content"})


@pytest.mark.parametrize(
    "rendered",
    [
        {"models/customer.sql": "a", r"models\customer.sql": "b"},
        {"models/Customer.sql": "a", "models/customer.sql": "b"},
        {"models/customer": "a", "models/customer/schema.yml": "b"},
    ],
)
def test_plan_rejects_cross_platform_and_file_directory_collisions(rendered):
    with pytest.raises(ArtifactCollisionError):
        plan_emission(rendered)


def test_plan_rejects_non_file_content_but_not_metadata_content():
    with pytest.raises(TypeError, match="must be str or bytes"):
        plan_emission({"models/customer.sql": {"sql": "select 1"}})

    assert plan_emission({"__metadata__": {"any": object()}}).paths == ()


def test_emit_writes_artifacts_and_deterministic_manifest(tmp_path: Path):
    target = tmp_path / "dbt" / "party"
    result = emit_artifacts(
        {
            "models/silver/party/customer.sql": "select 1\n",
            "models/silver/party/schema.yml": b"version: 2\n",
            "__render_metadata__": {"ignored": True},
        },
        target,
    )

    assert result.target_dir == target.resolve()
    assert result.written == (
        "models/silver/party/customer.sql",
        "models/silver/party/schema.yml",
    )
    assert result.removed == ()
    assert (target / "models/silver/party/customer.sql").read_text() == "select 1\n"
    assert not (target / "__render_metadata__").exists()
    manifest_before = result.manifest_path.read_bytes()
    assert _manifest(target)["files"][0]["path"] == "models/silver/party/customer.sql"

    emit_artifacts(
        {
            "models/silver/party/schema.yml": b"version: 2\n",
            "models/silver/party/customer.sql": "select 1\n",
        },
        target,
    )
    assert result.manifest_path.read_bytes() == manifest_before


def test_emit_can_own_one_contained_subtree_below_output_root(tmp_path: Path):
    output_root = tmp_path / "output"
    unrelated = output_root / "invoice" / "user.txt"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("outside selected target", encoding="utf-8")

    result = emit_artifacts(
        {"models/customer.sql": "select 1"},
        output_root,
        owned_subtree="party",
    )

    assert result.target_dir == (output_root / "party").resolve()
    assert (output_root / "party/models/customer.sql").is_file()
    assert unrelated.read_text(encoding="utf-8") == "outside selected target"


def test_emit_can_own_domain_manifests_in_one_unified_target(tmp_path: Path):
    target = tmp_path / "output" / "medallion" / "dbt"
    party = ".kairos-compile-manifest.party.json"
    billing = ".kairos-compile-manifest.billing.json"

    emit_artifacts(
        {
            "models/silver/party/obsolete.sql": "old",
            "models/silver/party/customer.sql": "select 1",
        },
        target,
        manifest_name=party,
    )
    emit_artifacts(
        {"models/silver/billing/account.sql": "select 2"},
        target,
        manifest_name=billing,
    )
    result = emit_artifacts(
        {"models/silver/party/customer.sql": "select 3"},
        target,
        manifest_name=party,
    )

    assert result.removed == ("models/silver/party/obsolete.sql",)
    assert (target / "models/silver/party/customer.sql").read_text() == "select 3"
    assert (target / "models/silver/billing/account.sql").read_text() == "select 2"
    assert (target / party).is_file()
    assert (target / billing).is_file()


def test_emit_can_replace_declared_shared_unowned_paths(tmp_path: Path):
    target = tmp_path / "output" / "medallion" / "dbt"
    target.mkdir(parents=True)
    shared = target / "dbt_project.yml"
    shared.write_text("name: old_project\n", encoding="utf-8")

    emit_artifacts(
        {"dbt_project.yml": "name: kairos_medallion_project\n"},
        target,
        manifest_name=".kairos-compile-manifest.shared.json",
        replace_unowned_paths=("dbt_project.yml",),
    )

    assert shared.read_text(encoding="utf-8") == "name: kairos_medallion_project\n"


@pytest.mark.parametrize("subtree", ["../party", "/party", r"C:\party", "party/../invoice"])
def test_emit_rejects_escaping_owned_subtree(tmp_path: Path, subtree: str):
    with pytest.raises(ArtifactPathError):
        emit_artifacts({"models/customer.sql": "select 1"}, tmp_path, owned_subtree=subtree)


def test_reemit_removes_only_stale_owned_files_and_preserves_unowned(tmp_path: Path):
    target = tmp_path / "party"
    emit_artifacts(
        {
            "models/old.sql": "old",
            "models/keep.sql": "first",
        },
        target,
    )
    unowned = target / "README.md"
    unowned.write_text("maintained by a user\n", encoding="utf-8")

    result = emit_artifacts(
        {
            "models/keep.sql": "second",
            "models/new.sql": "new",
        },
        target,
    )

    assert result.removed == ("models/old.sql",)
    assert not (target / "models/old.sql").exists()
    assert (target / "models/keep.sql").read_text() == "second"
    assert (target / "models/new.sql").read_text() == "new"
    assert unowned.read_text(encoding="utf-8") == "maintained by a user\n"
    assert [item["path"] for item in _manifest(target)["files"]] == [
        "models/keep.sql",
        "models/new.sql",
    ]


def test_empty_plan_removes_all_previously_owned_files(tmp_path: Path):
    target = tmp_path / "party"
    emit_artifacts({"models/customer.sql": "owned"}, target)
    (target / "user.txt").write_text("unowned", encoding="utf-8")

    result = emit_artifacts({"__render_metadata__": {}}, target)

    assert result.written == ()
    assert result.removed == ("models/customer.sql",)
    assert not (target / "models").exists()
    assert (target / "user.txt").read_text() == "unowned"
    assert _manifest(target)["files"] == []


def test_next_emit_recovers_orphaned_backup_and_stale_lock(tmp_path: Path):
    target = tmp_path / "party"
    emit_artifacts({"models/customer.sql": "previous"}, target)
    backup = tmp_path / ".party.kairos-backup-interrupted"
    os.replace(target, backup)
    lock = tmp_path / ".party.kairos-emit.lock"
    lock.write_text("99999999\n", encoding="ascii")

    result = emit_artifacts({"models/customer.sql": "replacement"}, target)

    assert result.target_dir == target
    assert (target / "models/customer.sql").read_text() == "replacement"
    assert not backup.exists()
    assert not lock.exists()


def test_emit_rejects_collision_with_unowned_file_without_changes(tmp_path: Path):
    target = tmp_path / "party"
    target.mkdir()
    destination = target / "models" / "customer.sql"
    destination.parent.mkdir()
    destination.write_text("user content", encoding="utf-8")

    with pytest.raises(ArtifactCollisionError, match="unowned"):
        emit_artifacts({"models/customer.sql": "generated"}, target)

    assert destination.read_text(encoding="utf-8") == "user content"
    assert not (target / EMIT_MANIFEST_NAME).exists()


def test_emit_rejects_unowned_parent_file_without_changes(tmp_path: Path):
    target = tmp_path / "party"
    target.mkdir()
    parent = target / "models"
    parent.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ArtifactCollisionError, match="parent"):
        emit_artifacts({"models/customer.sql": "generated"}, target)

    assert parent.read_text(encoding="utf-8") == "not a directory"


def test_emit_rejects_corrupt_or_traversing_manifest(tmp_path: Path):
    target = tmp_path / "party"
    target.mkdir()
    manifest_path = target / EMIT_MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(
            {
                "schema": EMIT_MANIFEST_SCHEMA,
                "files": [{"path": "../outside.sql", "sha256": "0" * 64}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ManifestError, match="unsafe"):
        emit_artifacts({"models/customer.sql": "generated"}, target)

    assert json.loads(manifest_path.read_text())["files"][0]["path"] == "../outside.sql"


def test_emit_rejects_file_directory_collisions_in_existing_manifest(tmp_path: Path):
    target = tmp_path / "party"
    target.mkdir()
    manifest_path = target / EMIT_MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(
            {
                "schema": EMIT_MANIFEST_SCHEMA,
                "files": [
                    {"path": "models", "sha256": "0" * 64},
                    {"path": "models/customer.sql", "sha256": "1" * 64},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ManifestError, match="colliding"):
        emit_artifacts({"models/customer.sql": "generated"}, target)


def test_stage_failure_leaves_previous_target_intact(tmp_path: Path, monkeypatch):
    target = tmp_path / "party"
    emit_artifacts({"models/customer.sql": "previous"}, target)
    manifest_before = (target / EMIT_MANIFEST_NAME).read_bytes()

    def fail_write(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(emit_module, "_write_stage", fail_write)
    with pytest.raises(EmissionError, match="could not stage"):
        emit_artifacts({"models/customer.sql": "replacement"}, target)

    assert (target / "models/customer.sql").read_text() == "previous"
    assert (target / EMIT_MANIFEST_NAME).read_bytes() == manifest_before


def test_failed_swap_rolls_back_previous_target(tmp_path: Path, monkeypatch):
    target = tmp_path / "party"
    emit_artifacts({"models/customer.sql": "previous"}, target)
    original_replace = os.replace
    calls = 0

    def fail_second_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated stage swap failure")
        return original_replace(source, destination)

    monkeypatch.setattr(emit_module.os, "replace", fail_second_replace)
    with pytest.raises(EmissionError, match="could not swap"):
        emit_artifacts({"models/customer.sql": "replacement"}, target)

    assert calls == 3
    assert (target / "models/customer.sql").read_text() == "previous"


def test_incomplete_rollback_reports_preserved_backup(tmp_path: Path, monkeypatch):
    target = tmp_path / "party"
    emit_artifacts({"models/customer.sql": "previous"}, target)
    original_replace = os.replace
    calls = 0

    def fail_swap_and_rollback(source, destination):
        nonlocal calls
        calls += 1
        if calls in {2, 3}:
            raise OSError("simulated failure")
        return original_replace(source, destination)

    monkeypatch.setattr(emit_module.os, "replace", fail_swap_and_rollback)
    with pytest.raises(EmissionRollbackError) as excinfo:
        emit_artifacts({"models/customer.sql": "replacement"}, target)

    assert excinfo.value.backup_path.is_dir()
    assert (excinfo.value.backup_path / "models/customer.sql").read_text() == "previous"
    assert not target.exists()


def test_concurrent_emit_is_rejected(tmp_path: Path):
    target = tmp_path / "party"
    lock = target.parent / f".{target.name}.kairos-emit.lock"
    lock.write_text("another process\n", encoding="ascii")

    with pytest.raises(EmissionBusyError, match="another emission"):
        emit_artifacts({"models/customer.sql": "generated"}, target)

    assert lock.exists()
    assert not target.exists()


def test_stage_is_created_as_target_sibling(tmp_path: Path, monkeypatch):
    target = tmp_path / "nested" / "party"
    observed_directories: list[Path] = []
    original_mkdtemp = emit_module.tempfile.mkdtemp

    def record_mkdtemp(*args, **kwargs):
        observed_directories.append(Path(kwargs["dir"]).resolve())
        return original_mkdtemp(*args, **kwargs)

    monkeypatch.setattr(emit_module.tempfile, "mkdtemp", record_mkdtemp)
    emit_artifacts({"models/customer.sql": "generated"}, target)

    assert observed_directories == [target.parent.resolve()]


def test_success_is_not_invalidated_by_best_effort_backup_cleanup(tmp_path: Path, monkeypatch):
    target = tmp_path / "party"
    emit_artifacts({"models/customer.sql": "previous"}, target)

    def leave_cleanup_for_later(path):
        return None

    monkeypatch.setattr(emit_module, "_best_effort_remove", leave_cleanup_for_later)
    result = emit_artifacts({"models/customer.sql": "replacement"}, target)

    assert result.target_dir == target.resolve()
    assert (target / "models/customer.sql").read_text() == "replacement"


# --- DD-215: Windows sharing-violation handling on the staged swap -------------------
#
# There is no Windows CI (ci.yml is ubuntu-only), so the Windows branch had never been
# executed by any test. These force the branch rather than depending on the host platform.
# The switch has to be `sys.platform`, never `os.name`: `os` is one shared module object,
# and `pathlib` reads `os.name` to pick between `PosixPath` and `WindowsPath` on every
# `Path()` call, so patching it makes emit's own path construction raise
# `NotImplementedError: cannot instantiate 'WindowsPath'` on a non-Windows host.


def _sharing_violation(winerror: int) -> OSError:
    error = OSError("simulated sharing violation")
    error.winerror = winerror
    return error


@pytest.mark.parametrize("winerror", [5, 32, 145])
def test_transient_sharing_violation_is_retried_until_it_clears(
    tmp_path: Path,
    monkeypatch,
    winerror: int,
):
    """The reported failure was a handle held for a moment by an external scanner."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(emit_module.time, "sleep", lambda _: None)
    target = tmp_path / "party"
    original_replace = os.replace
    failures = 3

    def fail_then_succeed(source, destination):
        nonlocal failures
        if failures:
            failures -= 1
            raise _sharing_violation(winerror)
        return original_replace(source, destination)

    monkeypatch.setattr(emit_module.os, "replace", fail_then_succeed)
    emit_artifacts({"models/customer.sql": "generated"}, target)

    assert failures == 0
    assert (target / "models/customer.sql").read_text() == "generated"


def test_permanent_error_is_not_retried(tmp_path: Path, monkeypatch):
    """Retrying a permanent failure only adds seconds of sleeping before the same error."""
    monkeypatch.setattr(sys, "platform", "win32")
    slept: list[float] = []
    monkeypatch.setattr(emit_module.time, "sleep", slept.append)
    target = tmp_path / "party"
    original_replace = os.replace
    attempts = 0

    def fail_permanently(source, destination):
        nonlocal attempts
        if str(destination) == str(target):
            attempts += 1
            raise _sharing_violation(2)  # ERROR_FILE_NOT_FOUND
        return original_replace(source, destination)

    monkeypatch.setattr(emit_module.os, "replace", fail_permanently)
    with pytest.raises(EmissionError):
        emit_artifacts({"models/customer.sql": "generated"}, target)

    assert attempts == 1
    assert slept == []


def test_windows_swap_failure_names_the_path_and_the_likely_holder(tmp_path: Path, monkeypatch):
    """The original message named neither, which is what made this expensive to diagnose."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(emit_module.time, "sleep", lambda _: None)
    target = tmp_path / "party"
    original_replace = os.replace

    def always_blocked(source, destination):
        if str(destination) == str(target):
            raise _sharing_violation(32)
        return original_replace(source, destination)

    monkeypatch.setattr(emit_module.os, "replace", always_blocked)
    with pytest.raises(EmissionError) as excinfo:
        emit_artifacts({"models/customer.sql": "generated"}, target)

    message = str(excinfo.value)
    assert "kairos-stage-" in message  # the blocked path, not just the target
    assert "antivirus" in message and "--log-file" in message


def test_emit_rejects_an_unknown_manifest_schema(tmp_path: Path):
    """Fail closed on a manifest this toolkit does not understand.

    Untested until DD-218 weighed extending the manifest instead of emitting a
    sidecar. It is the reason that option was rejected: an older toolkit reading a
    newer publish tree does not degrade to "unowned", it refuses outright, and
    `cli/compile.py` parses *every* domain's manifest -- so one unreadable manifest
    fails an unrelated domain's emit.
    """
    target = tmp_path / "party"
    target.mkdir()
    manifest_path = target / EMIT_MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "kairos.eu/compiler-emit-manifest/v2",
                "files": [{"path": "models/customer.sql", "sha256": "0" * 64}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ManifestError, match="unsupported compiler manifest schema"):
        emit_artifacts({"models/customer.sql": "generated"}, target)


def test_emit_rejects_an_extra_top_level_manifest_key(tmp_path: Path):
    """The manifest has no forward-compatible extension point.

    Even at the *same* schema string, an added key is refused -- which is why DD-218
    puts provenance in its own artifact rather than in here.
    """
    target = tmp_path / "party"
    target.mkdir()
    manifest_path = target / EMIT_MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(
            {
                "schema": EMIT_MANIFEST_SCHEMA,
                "files": [{"path": "models/customer.sql", "sha256": "0" * 64}],
                "inputs": [{"name": "model/ontologies/party.ttl", "sha256": "1" * 64}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ManifestError, match="malformed compiler manifest"):
        emit_artifacts({"models/customer.sql": "generated"}, target)
