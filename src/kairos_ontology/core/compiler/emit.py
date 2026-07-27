# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic, manifest-owned artifact emission for the v5 compiler.

The emitter prepares a complete sibling tree before changing the selected target.  Commit
uses a target-to-backup, stage-to-target swap so a failed second move can restore the
previous tree.  This is intentionally a best-effort portable transaction: replacing a
non-empty directory is not atomically available on every supported Windows filesystem.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Final

EMIT_MANIFEST_NAME: Final = ".kairos-compile-manifest.json"
EMIT_MANIFEST_SCHEMA: Final = "kairos.eu/compiler-emit-manifest/v1"
_LOCK_SUFFIX: Final = ".kairos-emit.lock"
_WINDOWS_RESERVED_NAMES: Final = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)
_WINDOWS_INVALID_CHARACTERS: Final = frozenset('<>:"|?*')


class EmissionError(RuntimeError):
    """Base error for an artifact emission failure."""


class ArtifactPathError(EmissionError, ValueError):
    """An artifact path is unsafe or non-canonical."""


class ArtifactCollisionError(ArtifactPathError):
    """Two artifacts, or an artifact and an unowned path, collide."""


class ManifestError(EmissionError, ValueError):
    """The existing ownership manifest is malformed or unsafe."""


class EmissionBusyError(EmissionError):
    """Another emitter owns the target's exclusive lock."""


class EmissionRollbackError(EmissionError):
    """The swap failed and the previous target could not be restored."""

    def __init__(self, message: str, *, backup_path: Path):
        self.backup_path = backup_path
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PlannedArtifact:
    """One canonical artifact path and its immutable bytes."""

    path: str
    content: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class EmissionPlan:
    """A fully validated in-memory artifact and manifest plan."""

    artifacts: tuple[PlannedArtifact, ...]
    manifest: bytes

    @property
    def paths(self) -> tuple[str, ...]:
        """Return owned artifact paths in canonical order."""
        return tuple(artifact.path for artifact in self.artifacts)


@dataclass(frozen=True, slots=True)
class EmissionResult:
    """Summary of a committed emission."""

    target_dir: Path
    manifest_path: Path
    written: tuple[str, ...]
    removed: tuple[str, ...]


def _canonical_artifact_path(raw_path: str) -> str:
    if not isinstance(raw_path, str):
        raise ArtifactPathError("artifact paths must be strings")
    if not raw_path or "\x00" in raw_path:
        raise ArtifactPathError("artifact paths must be non-empty and contain no NUL bytes")
    if raw_path.startswith("__"):
        raise ArtifactPathError("render metadata keys are not artifact paths")

    windows = PureWindowsPath(raw_path)
    normalized_input = raw_path.replace("\\", "/")
    posix = PurePosixPath(normalized_input)
    parts = normalized_input.split("/")
    if windows.drive or windows.is_absolute() or posix.is_absolute():
        raise ArtifactPathError(f"artifact path must be relative: {raw_path!r}")
    if any(part in {"", ".", ".."} for part in parts):
        raise ArtifactPathError(f"artifact path must be canonical and traversal-free: {raw_path!r}")
    for part in parts:
        stem = part.split(".", maxsplit=1)[0].upper()
        if (
            part.endswith((" ", "."))
            or stem in _WINDOWS_RESERVED_NAMES
            or any(character in _WINDOWS_INVALID_CHARACTERS for character in part)
            or any(ord(character) < 32 for character in part)
        ):
            raise ArtifactPathError(f"artifact path is not Windows-safe: {raw_path!r}")

    canonical = posix.as_posix()
    if canonical.casefold() == EMIT_MANIFEST_NAME.casefold():
        raise ArtifactCollisionError(
            f"artifact path {canonical!r} is reserved for the compiler manifest"
        )
    return canonical


def _content_bytes(path: str, content: object) -> bytes:
    if isinstance(content, str):
        return content.encode("utf-8")
    if isinstance(content, bytes):
        return content
    raise TypeError(f"artifact {path!r} content must be str or bytes")


def _collision_key(path: str) -> str:
    return path.casefold()


def _check_plan_collisions(paths: tuple[str, ...]) -> None:
    seen: dict[str, str] = {}
    for path in paths:
        key = _collision_key(path)
        previous = seen.get(key)
        if previous is not None:
            raise ArtifactCollisionError(
                f"artifact paths collide on a case-insensitive filesystem: "
                f"{previous!r} and {path!r}"
            )
        seen[key] = path

    path_set = set(seen)
    for path in paths:
        parts = path.split("/")
        for index in range(1, len(parts)):
            parent = "/".join(parts[:index])
            if _collision_key(parent) in path_set:
                raise ArtifactCollisionError(
                    f"artifact path is both a file and a directory: {parent!r}"
                )


def _manifest_bytes(artifacts: tuple[PlannedArtifact, ...]) -> bytes:
    document = {
        "files": [{"path": artifact.path, "sha256": artifact.sha256} for artifact in artifacts],
        "schema": EMIT_MANIFEST_SCHEMA,
    }
    return (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def plan_emission(rendered: Mapping[str, object]) -> EmissionPlan:
    """Validate renderer output and build a deterministic in-memory emission plan.

    Renderer metadata keys beginning with ``__`` are deliberately ignored.  All other keys
    are treated as file paths and must be canonical, relative, and collision-free.
    """

    planned: list[PlannedArtifact] = []
    for raw_path, raw_content in rendered.items():
        if isinstance(raw_path, str) and raw_path.startswith("__"):
            continue
        path = _canonical_artifact_path(raw_path)
        content = _content_bytes(path, raw_content)
        planned.append(
            PlannedArtifact(
                path=path,
                content=content,
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )

    artifacts = tuple(sorted(planned, key=lambda artifact: artifact.path))
    _check_plan_collisions(tuple(artifact.path for artifact in artifacts))
    return EmissionPlan(artifacts=artifacts, manifest=_manifest_bytes(artifacts))


def _target_path(
    target_dir: str | os.PathLike[str],
    owned_subtree: str | None,
) -> Path:
    root = Path(target_dir).expanduser().resolve(strict=False)
    if owned_subtree is None:
        target = root
    else:
        relative = _canonical_artifact_path(owned_subtree)
        target = _contained_path(root, relative, error_type=ArtifactPathError).resolve(strict=False)
    if not target.name:
        raise ArtifactPathError("the filesystem root cannot be an emission target")
    return target


def _contained_path(root: Path, relative: str, *, error_type: type[EmissionError]) -> Path:
    candidate = root.joinpath(*relative.split("/"))
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, ValueError) as exc:
        raise error_type(f"path escapes the selected target: {relative!r}") from exc
    return candidate


def _parse_manifest(target: Path) -> dict[str, str]:
    manifest_path = target / EMIT_MANIFEST_NAME
    if not manifest_path.exists() and not manifest_path.is_symlink():
        return {}
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ManifestError(f"compiler manifest is not a regular file: {manifest_path}")

    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read compiler manifest {manifest_path}: {exc}") from exc
    if not isinstance(document, dict) or document.get("schema") != EMIT_MANIFEST_SCHEMA:
        raise ManifestError(f"unsupported compiler manifest schema in {manifest_path}")
    if set(document) != {"files", "schema"} or not isinstance(document["files"], list):
        raise ManifestError(f"malformed compiler manifest {manifest_path}")

    owned: dict[str, str] = {}
    collision_keys: set[str] = set()
    for item in document["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise ManifestError(f"malformed file entry in compiler manifest {manifest_path}")
        try:
            path = _canonical_artifact_path(item["path"])
        except (ArtifactPathError, TypeError) as exc:
            raise ManifestError(f"unsafe file entry in compiler manifest {manifest_path}") from exc
        digest = item["sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ManifestError(f"invalid sha256 for {path!r} in compiler manifest")
        collision_key = _collision_key(path)
        if collision_key in collision_keys:
            raise ManifestError(f"colliding paths in compiler manifest: {path!r}")
        collision_keys.add(collision_key)
        owned[path] = digest
    try:
        _check_plan_collisions(tuple(owned))
    except ArtifactCollisionError as exc:
        raise ManifestError(f"colliding paths in compiler manifest {manifest_path}") from exc
    return owned


def _path_kind(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if path.is_file():
        return "file"
    if path.is_dir():
        return "directory"
    return "missing"


def _validate_target_collisions(
    target: Path,
    artifacts: tuple[PlannedArtifact, ...],
    previously_owned: Mapping[str, str],
) -> None:
    owned_keys = {_collision_key(path) for path in previously_owned}
    for artifact in artifacts:
        parts = artifact.path.split("/")
        for index in range(1, len(parts)):
            relative = "/".join(parts[:index])
            parent = _contained_path(target, relative, error_type=ArtifactPathError)
            kind = _path_kind(parent)
            if kind == "symlink":
                raise ArtifactPathError(f"artifact parent must not be a symlink: {relative!r}")
            if kind == "file" and _collision_key(relative) not in owned_keys:
                raise ArtifactCollisionError(f"artifact parent is an unowned file: {relative!r}")

        destination = _contained_path(target, artifact.path, error_type=ArtifactPathError)
        kind = _path_kind(destination)
        is_owned = _collision_key(artifact.path) in owned_keys
        if kind == "directory":
            raise ArtifactCollisionError(
                f"artifact destination collides with a directory: {artifact.path!r}"
            )
        if kind in {"file", "symlink"} and not is_owned:
            raise ArtifactCollisionError(
                f"artifact destination collides with an unowned path: {artifact.path!r}"
            )

    for relative in previously_owned:
        existing = _contained_path(target, relative, error_type=ManifestError)
        if existing.is_dir() and not existing.is_symlink():
            raise ManifestError(f"manifest-owned file became a directory: {relative!r}")


def _remove_owned_file(stage: Path, relative: str) -> None:
    path = _contained_path(stage, relative, error_type=ManifestError)
    if path.is_dir() and not path.is_symlink():
        raise ManifestError(f"manifest-owned file became a directory: {relative!r}")
    if path.exists() or path.is_symlink():
        path.unlink()

    parent = path.parent
    while parent != stage:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def _write_stage(
    stage: Path,
    plan: EmissionPlan,
    previously_owned: Mapping[str, str],
) -> None:
    for relative in sorted(previously_owned, key=lambda item: (-item.count("/"), item)):
        _remove_owned_file(stage, relative)

    manifest_path = stage / EMIT_MANIFEST_NAME
    if manifest_path.exists() or manifest_path.is_symlink():
        manifest_path.unlink()

    for artifact in plan.artifacts:
        destination = _contained_path(stage, artifact.path, error_type=ArtifactPathError)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(artifact.content)
    manifest_path.write_bytes(plan.manifest)


def _validate_stage(stage: Path, plan: EmissionPlan) -> None:
    if (stage / EMIT_MANIFEST_NAME).read_bytes() != plan.manifest:
        raise EmissionError("staged compiler manifest does not match the in-memory plan")
    for artifact in plan.artifacts:
        destination = _contained_path(stage, artifact.path, error_type=ArtifactPathError)
        try:
            content = destination.read_bytes()
        except OSError as exc:
            raise EmissionError(f"cannot validate staged artifact {artifact.path!r}") from exc
        if hashlib.sha256(content).hexdigest() != artifact.sha256:
            raise EmissionError(f"staged artifact hash mismatch: {artifact.path!r}")


def _best_effort_remove(path: Path | None) -> None:
    if path is None:
        return
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)
    except OSError:
        # Open handles can temporarily prevent cleanup on Windows. The committed target is
        # already valid, so a uniquely named stage/backup may safely remain for later cleanup.
        pass


class _TargetLock:
    def __init__(self, target: Path):
        self.path = target.parent / f".{target.name}{_LOCK_SUFFIX}"
        self._held = False

    def __enter__(self) -> "_TargetLock":
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            if not _stale_lock(self.path):
                raise EmissionBusyError(f"another emission is active for {self.path}") from exc
            try:
                self.path.unlink()
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except (FileExistsError, OSError) as retry_error:
                raise EmissionBusyError(
                    f"another emission is active for {self.path}"
                ) from retry_error
        try:
            os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        finally:
            os.close(descriptor)
        self._held = True
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._held:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                # A lock cleanup failure must not invalidate a successfully swapped target.
                pass
            self._held = False


def _stale_lock(path: Path) -> bool:
    try:
        text = path.read_text(encoding="ascii").strip()
        pid = int(text)
    except (OSError, UnicodeError, ValueError):
        try:
            return time.time() - path.stat().st_mtime > 60
        except OSError:
            return False
    if os.name == "nt":
        import ctypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return True
        ctypes.windll.kernel32.CloseHandle(process)
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OSError):
        return False
    return False


def _recover_interrupted_emit(target: Path) -> None:
    backups = tuple(sorted(target.parent.glob(f".{target.name}.kairos-backup-*")))
    stages = tuple(sorted(target.parent.glob(f".{target.name}.kairos-stage-*")))
    if not target.exists() and backups:
        if len(backups) != 1:
            raise EmissionError(
                f"cannot recover interrupted emission for {target}: multiple backups exist"
            )
        try:
            os.replace(backups[0], target)
        except OSError as exc:
            raise EmissionError(f"cannot restore interrupted emission backup for {target}") from exc
        backups = ()
    if target.exists():
        for path in (*backups, *stages):
            _best_effort_remove(path)


def _unique_backup_path(target: Path) -> Path:
    while True:
        candidate = target.parent / f".{target.name}.kairos-backup-{uuid.uuid4().hex}"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate


def _commit_stage(stage: Path, target: Path) -> Path | None:
    backup: Path | None = None
    previous_moved = False
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_dir():
            raise EmissionError(f"emission target must be a directory: {target}")
        backup = _unique_backup_path(target)
        try:
            os.replace(target, backup)
            previous_moved = True
        except OSError as exc:
            raise EmissionError(f"could not move emission target to backup: {target}") from exc

    try:
        os.replace(stage, target)
    except OSError as swap_error:
        if previous_moved and backup is not None:
            try:
                os.replace(backup, target)
            except OSError as rollback_error:
                raise EmissionRollbackError(
                    "emission swap failed and rollback was incomplete; "
                    f"the previous target remains at {backup}",
                    backup_path=backup,
                ) from rollback_error
        raise EmissionError(f"could not swap staged artifacts into {target}") from swap_error
    return backup


def emit_artifacts(
    rendered: Mapping[str, object],
    target_dir: str | os.PathLike[str],
    *,
    owned_subtree: str | None = None,
) -> EmissionResult:
    """Emit renderer artifacts into one manifest-owned target subtree.

    The complete plan is validated before filesystem mutation.  A sibling stage on the same
    volume preserves unowned target files, removes stale manifest-owned files, and receives
    the new plan.  When ``owned_subtree`` is supplied, only that relative subtree below
    ``target_dir`` is selected.  Commit swaps the previous target to a backup and the stage
    into place; failures restore the backup whenever the platform permits.
    """

    plan = plan_emission(rendered)
    target = _target_path(target_dir, owned_subtree)
    target.parent.mkdir(parents=True, exist_ok=True)

    stage: Path | None = None
    backup: Path | None = None
    with _TargetLock(target):
        _recover_interrupted_emit(target)
        if target.exists() and not target.is_dir():
            raise EmissionError(f"emission target must be a directory: {target}")
        previously_owned = _parse_manifest(target) if target.exists() else {}
        _validate_target_collisions(target, plan.artifacts, previously_owned)
        stale = tuple(sorted(set(previously_owned) - set(plan.paths)))

        try:
            stage = Path(
                tempfile.mkdtemp(prefix=f".{target.name}.kairos-stage-", dir=target.parent)
            )
            if target.exists():
                shutil.copytree(target, stage, dirs_exist_ok=True, symlinks=True)
            _write_stage(stage, plan, previously_owned)
            _validate_stage(stage, plan)
            backup = _commit_stage(stage, target)
            stage = None
        except EmissionError:
            raise
        except OSError as exc:
            raise EmissionError(f"could not stage artifacts for {target}") from exc
        finally:
            _best_effort_remove(stage)

        _best_effort_remove(backup)
        return EmissionResult(
            target_dir=target,
            manifest_path=target / EMIT_MANIFEST_NAME,
            written=plan.paths,
            removed=stale,
        )
