# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Optional TMDL structural validation via the Microsoft TOM SDK (issue #619 feature request).

Runs the bundled ``tmdl_validator_tool/`` .NET console app
(``Microsoft.AnalysisServices.Tabular``'s ``TmdlSerializer.DeserializeDatabaseFromFolder``)
against the TMDL files ``render_powerbi_artifacts`` produced -- the same engine Power BI
Desktop and Fabric use to open a TMDL model -- so a syntax/structure error is caught at
projection time with an exact file and line, instead of only surfacing as a cryptic
dialog when a human opens the PBIP.

Requires the .NET SDK (``dotnet`` on PATH). Never a build or runtime dependency of the
toolkit itself: nothing calls this by default, and when ``dotnet`` is unavailable every
result comes back ``status="unavailable"`` rather than raising, since most toolkit
installs will never have a .NET SDK. Never talks to a live Power BI workspace or Fabric
tenant -- this is a pure local file-structure/syntax check, verified against the real
TOM SDK: it correctly parses a valid TMDL tree and rejects a genuinely malformed one
with the exact file/line/detail TmdlFormatException carries.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .gold_specs import GoldContractError

#: Governance rule for optional TMDL structural validation (#619 feature request).
TMDL_VALIDATION_RULE_ID = "DD-113-tmdl-validation"

_TOOL_DIR = Path(__file__).resolve().parent / "tmdl_validator_tool"
_TOOL_FILES = ("TmdlValidator.csproj", "Program.cs")
_DEFINITION_MARKER = "/definition"
_SUBPROCESS_TIMEOUT_SECONDS = 180
_BUILD_TIMEOUT_SECONDS = 300
_BUILD_LOCK_TIMEOUT_SECONDS = 300

# Every call shares one build across the whole machine (keyed by tool source content),
# instead of a fresh `dotnet run` cold build per call -- faster, and avoids concurrent
# builds (e.g. under pytest-xdist) racing on the TOM SDK's native asset extraction,
# which surfaced as a spurious TypeInitializationException on some platforms.
_BUILD_CACHE_ROOT = Path(tempfile.gettempdir()) / "kairos-tmdl-validator-build"


@dataclass(frozen=True, slots=True)
class TmdlValidationResult:
    """One TMDL ``.../definition`` folder's validation outcome."""

    definition_root: str
    status: str  # "pass" | "fail" | "unavailable"
    message: str


def _definition_roots(artifacts: dict[str, str]) -> dict[str, dict[str, str]]:
    """Group every ``.tmdl`` artifact by its ``.../definition`` root path.

    Never materializes the PBIP wrapper JSON, dbt/DDL/DAX/ERD artifacts, or anything
    else render_powerbi_artifacts returns -- only the TMDL tree the TOM SDK needs.
    """
    roots: dict[str, dict[str, str]] = {}
    marker = f"{_DEFINITION_MARKER}/"
    for path, content in artifacts.items():
        if not path.endswith(".tmdl"):
            continue
        idx = path.find(marker)
        if idx == -1:
            continue
        root = path[: idx + len(_DEFINITION_MARKER)]
        rel = path[idx + len(marker) :]
        roots.setdefault(root, {})[rel] = content
    return roots


def _tool_source_hash() -> str:
    digest = hashlib.sha256()
    for name in _TOOL_FILES:
        digest.update((_TOOL_DIR / name).read_bytes())
    return digest.hexdigest()[:16]


def _ensure_built() -> Path:
    """Build the bundled validator once, cached by tool-source content hash.

    Content-hashed so a change to Program.cs/the .csproj invalidates the cache
    automatically. Cross-process/cross-worker lock file (not fcntl/msvcrt, so it works
    identically on Windows and Linux) serializes the one build so pytest-xdist workers
    -- or any other concurrent callers -- don't race the TOM SDK's native asset
    extraction, which is what produced a spurious TypeInitializationException under
    concurrent cold starts.
    """
    build_dir = _BUILD_CACHE_ROOT / _tool_source_hash()
    dll_path = build_dir / "bin" / "Debug" / "net8.0" / "TmdlValidator.dll"
    if dll_path.is_file():
        return dll_path

    build_dir.mkdir(parents=True, exist_ok=True)
    lock_path = build_dir / ".build.lock"
    deadline = time.monotonic() + _BUILD_LOCK_TIMEOUT_SECONDS
    acquired = False
    while time.monotonic() < deadline:
        try:
            os.close(os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            acquired = True
            break
        except FileExistsError:
            if dll_path.is_file():
                return dll_path
            time.sleep(0.5)

    try:
        if dll_path.is_file():
            return dll_path
        for name in _TOOL_FILES:
            shutil.copy2(_TOOL_DIR / name, build_dir / name)
        subprocess.run(
            ["dotnet", "build", "--configuration", "Debug", str(build_dir / "TmdlValidator.csproj")],
            capture_output=True,
            text=True,
            timeout=_BUILD_TIMEOUT_SECONDS,
            check=True,
        )
        return dll_path
    finally:
        if acquired:
            lock_path.unlink(missing_ok=True)


def _run_validator(folder: Path) -> tuple[str, str]:
    """Run the bundled validator against *folder*; return (status, message)."""
    try:
        dll_path = _ensure_built()
        completed = subprocess.run(
            ["dotnet", str(dll_path), str(folder)],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "unavailable", f"dotnet invocation failed: {exc}"

    stdout_lines = completed.stdout.strip().splitlines()
    try:
        payload = json.loads(stdout_lines[-1])
    except (json.JSONDecodeError, IndexError):
        detail = completed.stderr.strip() or completed.stdout.strip()
        return "unavailable", (
            f"TmdlValidator produced no parseable output (exit {completed.returncode}): {detail}"
        )
    status = payload.get("status")
    if status == "pass":
        return "pass", ""
    if status not in {"fail", "unavailable"}:
        status = "unavailable"
    return status, f"{payload.get('error_type', 'TmdlFormatException')}: {payload.get('message', '')}"


def validate_tmdl_artifacts(
    artifacts: dict[str, str],
    *,
    required: bool = False,
) -> tuple[TmdlValidationResult, ...]:
    """Validate every TMDL ``definition`` tree found in *artifacts* with the real TOM SDK.

    Returns one result per definition root found (empty tuple if *artifacts* has no
    TMDL files at all). *required* raises ``GoldContractError("gold.tmdl-validation-failed",
    ...)`` if any result is not ``"pass"`` -- including ``"unavailable"``, since if you
    require validation, ``dotnet`` not being present is itself a failure to validate.
    Left ``False`` by default so this stays safe to call from any environment.
    """
    roots = _definition_roots(artifacts)
    if not roots:
        return ()

    if shutil.which("dotnet") is None:
        results = tuple(
            TmdlValidationResult(root, "unavailable", "dotnet SDK not found on PATH")
            for root in roots
        )
    else:
        collected: list[TmdlValidationResult] = []
        for root, files in roots.items():
            staging = Path(tempfile.mkdtemp(prefix="kairos-tmdl-staging-"))
            try:
                for rel, content in files.items():
                    target = staging / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
                status, message = _run_validator(staging)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
            collected.append(TmdlValidationResult(root, status, message))
        results = tuple(collected)

    if required:
        failures = tuple(item for item in results if item.status != "pass")
        if failures:
            detail = "; ".join(f"{item.definition_root}: {item.message}" for item in failures)
            raise GoldContractError(
                "gold.tmdl-validation-failed",
                f"TMDL structural validation failed for {len(failures)} model(s): {detail}",
                rule_id=TMDL_VALIDATION_RULE_ID,
            )
    return results
