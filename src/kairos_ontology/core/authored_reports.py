# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Power BI reports a dataplatform authors itself, beside the hub's archive (DD-253, #1102).

DD-236 settles ownership: the hub emits a blank ``<Product>.Report`` stub, and the report
anyone actually reads is a separate Fabric item the BI side builds against the deployed
semantic model. This module is the other half: where that report's source lives
(``powerbi/reports/`` in the dataplatform), how the deploy binds it to the right model in
each workspace, and one theme every report shares.

The manifest, ``powerbi/reports/reports.yml``, names each report's semantic model by
*display name*. The model's ID differs per workspace, and a report binds by ID, so the
deploy resolves the name in the target workspace and writes the ID into a staged copy of
``definition.pbir`` -- nothing per-environment is committed. Fabric's REST import rejects the
short ``byConnection.connectionString`` form, so the staged binding is always the long one
(:func:`live_connection`).

Nothing here talks to Fabric. The deploy workflow lists the workspace's models and passes
``{display name: id}`` in; everything else is file-level and deterministic.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from .determinism import write_text_lf

#: Where authored reports live in a dataplatform repository.
DEFAULT_REPORTS_DIR = Path("powerbi") / "reports"

#: The manifest, at the root of the reports directory.
MANIFEST_NAME = "reports.yml"

#: Where Power BI keeps a report's own resources, and the package a custom theme joins.
_RESOURCES_DIR = Path("StaticResources") / "RegisteredResources"
_REGISTERED = "RegisteredResources"

_MANIFEST_KEYS = frozenset({"schema_version", "theme", "reports"})
_REPORT_KEYS = frozenset({"folder", "model", "product", "insights", "theme"})


class AuthoredReportsError(ValueError):
    """The authored-reports manifest or a report in it cannot be used."""


@dataclass(frozen=True, slots=True)
class AuthoredReport:
    """One report this repository authors, and the semantic model it reads."""

    folder: str
    model: str
    product: str | None
    insights: tuple[str, ...]
    themed: bool


@dataclass(frozen=True, slots=True)
class ReportsManifest:
    """The parsed ``reports.yml``; ``theme`` is relative to the reports directory."""

    theme: str | None
    reports: tuple[AuthoredReport, ...]


@dataclass(frozen=True, slots=True)
class ReportDiagnostic:
    """One reason the authored reports would not deploy as intended."""

    code: str
    message: str
    path: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "path": self.path}


def _text(value: object, where: str, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise AuthoredReportsError(f"{where} must be a non-empty string.")
    return value.strip()


def _parse_report(raw: object, index: int) -> AuthoredReport:
    where = f"reports[{index}]"
    if not isinstance(raw, dict):
        raise AuthoredReportsError(f"{where} must be a mapping.")
    unknown = sorted(set(raw) - _REPORT_KEYS)
    if unknown:
        raise AuthoredReportsError(
            f"{where} has unknown key(s) {', '.join(unknown)}; "
            f"allowed: {', '.join(sorted(_REPORT_KEYS))}."
        )
    folder = _text(raw.get("folder"), f"{where}.folder", required=True)
    if "/" in folder or "\\" in folder or not folder.endswith(".Report"):
        raise AuthoredReportsError(
            f"{where}.folder is {folder!r}: name one `<Name>.Report` folder directly in the "
            "reports directory."
        )
    insights = raw.get("insights", [])
    if not isinstance(insights, list) or not all(
        isinstance(item, str) and item.strip() for item in insights
    ):
        raise AuthoredReportsError(f"{where}.insights must be a list of insight ids.")
    ids = tuple(item.strip() for item in insights)
    if len(set(ids)) != len(ids):
        raise AuthoredReportsError(f"{where}.insights lists an insight id twice.")
    themed = raw.get("theme", True)
    if not isinstance(themed, bool):
        raise AuthoredReportsError(
            f"{where}.theme must be `false` (opt out of the shared theme) or omitted."
        )
    return AuthoredReport(
        folder=folder,
        model=_text(raw.get("model"), f"{where}.model", required=True),
        product=_text(raw.get("product"), f"{where}.product", required=False),
        insights=ids,
        themed=themed,
    )


def parse_manifest(text: str) -> ReportsManifest:
    """Parse ``reports.yml``; raise :class:`AuthoredReportsError` when it is unusable."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AuthoredReportsError(f"{MANIFEST_NAME} is not valid YAML: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise AuthoredReportsError(f"{MANIFEST_NAME} must be a mapping.")
    unknown = sorted(set(raw) - _MANIFEST_KEYS)
    if unknown:
        raise AuthoredReportsError(
            f"{MANIFEST_NAME} has unknown key(s) {', '.join(unknown)}; "
            f"allowed: {', '.join(sorted(_MANIFEST_KEYS))}."
        )
    entries = raw.get("reports")
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise AuthoredReportsError("`reports` must be a list.")
    reports = tuple(_parse_report(entry, index) for index, entry in enumerate(entries))
    seen: set[str] = set()
    for report in reports:
        if report.folder in seen:
            raise AuthoredReportsError(f"{report.folder} is listed twice.")
        seen.add(report.folder)
    theme = _text(raw.get("theme"), "theme", required=False)
    if theme is not None and (Path(theme).is_absolute() or ".." in Path(theme).parts):
        raise AuthoredReportsError(
            f"theme is {theme!r}: give a path inside the reports directory, e.g. theme/brand.json."
        )
    return ReportsManifest(theme=theme, reports=reports)


def load_manifest(reports_dir: Path) -> ReportsManifest | None:
    """The manifest in *reports_dir*, or ``None`` when there is none."""
    path = reports_dir / MANIFEST_NAME
    if not path.is_file():
        return None
    return parse_manifest(path.read_text(encoding="utf-8"))


def _report_folders(reports_dir: Path) -> list[Path]:
    if not reports_dir.is_dir():
        return []
    return sorted(p for p in reports_dir.iterdir() if p.is_dir() and p.name.endswith(".Report"))


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _dump_json(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _theme_name(manifest: ReportsManifest) -> str | None:
    return Path(manifest.theme).name if manifest.theme else None


def _theme_diagnostics(
    reports_dir: Path, manifest: ReportsManifest, report: AuthoredReport
) -> list[ReportDiagnostic]:
    name = _theme_name(manifest)
    folder = reports_dir / report.folder
    source = reports_dir / manifest.theme
    rel = f"{report.folder}/definition/report.json"
    fix = "Run `kairos-ontology apply-report-theme` and commit the result."
    report_json = folder / "definition" / "report.json"
    if not report_json.is_file():
        return [ReportDiagnostic("reports.theme-drift", f"No report.json to theme. {fix}", rel)]
    custom = _read_json(report_json).get("themeCollection", {}).get("customTheme", {})
    copied = folder / _RESOURCES_DIR / name
    if custom.get("name") != name or not copied.is_file():
        return [
            ReportDiagnostic(
                "reports.theme-drift",
                f"{report.folder} does not use the shared theme {manifest.theme}. {fix}",
                rel,
            )
        ]
    if copied.read_bytes() != source.read_bytes():
        return [
            ReportDiagnostic(
                "reports.theme-drift",
                f"{report.folder} carries an older copy of {manifest.theme}. {fix}",
                f"{report.folder}/{_RESOURCES_DIR.as_posix()}/{name}",
            )
        ]
    return []


def check_authored_reports(reports_dir: Path) -> list[ReportDiagnostic]:
    """Everything that would make the authored reports deploy wrongly, or not at all."""
    folders = _report_folders(reports_dir)
    try:
        manifest = load_manifest(reports_dir)
    except AuthoredReportsError as exc:
        return [ReportDiagnostic("reports.manifest-invalid", str(exc), MANIFEST_NAME)]
    if manifest is None:
        return [
            ReportDiagnostic(
                "reports.unlisted",
                f"{folder.name} has no entry in {MANIFEST_NAME}, so the deploy cannot tell "
                f"which semantic model it reads. Add `- folder: {folder.name}` with its "
                "`model:` (the model's display name).",
                folder.name,
            )
            for folder in folders
        ]

    diagnostics: list[ReportDiagnostic] = []
    listed = {report.folder for report in manifest.reports}
    models = {report.model for report in manifest.reports}
    for folder in folders:
        if folder.name not in listed:
            diagnostics.append(
                ReportDiagnostic(
                    "reports.unlisted",
                    f"{folder.name} has no entry in {MANIFEST_NAME}; add it with its `model:`.",
                    folder.name,
                )
            )
    if manifest.theme and not (reports_dir / manifest.theme).is_file():
        diagnostics.append(
            ReportDiagnostic(
                "reports.theme-missing",
                f"The shared theme {manifest.theme} does not exist.",
                MANIFEST_NAME,
            )
        )
    for report in manifest.reports:
        folder = reports_dir / report.folder
        if not folder.is_dir():
            diagnostics.append(
                ReportDiagnostic(
                    "reports.folder-missing",
                    f"{MANIFEST_NAME} lists {report.folder}, which does not exist.",
                    MANIFEST_NAME,
                )
            )
            continue
        pbir = folder / "definition.pbir"
        if not pbir.is_file():
            diagnostics.append(
                ReportDiagnostic(
                    "reports.pbir-missing",
                    f"{report.folder} has no definition.pbir; save it from Power BI Desktop "
                    "as a PBIR project.",
                    f"{report.folder}/definition.pbir",
                )
            )
        else:
            reference = _read_json(pbir).get("datasetReference", {})
            if not ({"byConnection", "byPath"} & set(reference)):
                diagnostics.append(
                    ReportDiagnostic(
                        "reports.pbir-unbound",
                        f"{report.folder}/definition.pbir binds to no semantic model.",
                        f"{report.folder}/definition.pbir",
                    )
                )
        platform = folder / ".platform"
        if platform.is_file():
            display = _read_json(platform).get("metadata", {}).get("displayName")
            if display in models:
                diagnostics.append(
                    ReportDiagnostic(
                        "reports.name-collision",
                        f"{report.folder} is named {display!r}, the name of a semantic model. "
                        "The hub republishes a stub report under that name on every release, "
                        "which would overwrite this one (DD-236). Rename it in .platform.",
                        f"{report.folder}/.platform",
                    )
                )
        if manifest.theme and report.themed and (reports_dir / manifest.theme).is_file():
            diagnostics.extend(_theme_diagnostics(reports_dir, manifest, report))
    return diagnostics


def live_connection(model_id: str) -> dict[str, object]:
    """The ``byConnection`` binding Fabric's REST import accepts for a model in the service.

    The short form -- a ``connectionString`` alone -- is rejected with "Required properties
    are missing: pbiServiceModelId, pbiModelVirtualServerName, pbiModelDatabaseName, name,
    connectionType". The model is identified by ``pbiModelDatabaseName``; the two nulls are
    what Power BI Desktop writes for a report bound to a model in the service.
    """
    return {
        "connectionString": None,
        "pbiServiceModelId": None,
        "pbiModelVirtualServerName": "sobe_wowvirtualserver",
        "pbiModelDatabaseName": model_id,
        "name": "EntityDataSource",
        "connectionType": "pbiServiceXmlaStyleLive",
    }


def stage_authored_reports(
    reports_dir: Path, out_dir: Path, model_ids: dict[str, str]
) -> list[tuple[str, str, str]]:
    """Copy the reports to *out_dir*, each bound to its model's ID in the target workspace.

    Returns ``(folder, model, model_id)`` per staged report. The committed tree is never
    written; anything else in *reports_dir* (a hand-authored ``parameter.yml``) is copied
    unchanged, so fabric-cicd still applies it.
    """
    problems = check_authored_reports(reports_dir)
    blocking = [p for p in problems if p.code != "reports.theme-drift"]
    if blocking:
        raise AuthoredReportsError(
            "The authored reports cannot be staged:\n"
            + "\n".join(f"  {p.code}: {p.message}" for p in blocking)
        )
    manifest = load_manifest(reports_dir) or ReportsManifest(theme=None, reports=())
    unknown = sorted({r.model for r in manifest.reports} - set(model_ids))
    if unknown:
        available = ", ".join(sorted(model_ids)) or "none"
        raise AuthoredReportsError(
            f"Semantic model(s) {', '.join(unknown)} are not in the target workspace "
            f"(it has: {available}). Deploy the hub's models first, or fix `model:` in "
            f"{MANIFEST_NAME}."
        )
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(reports_dir, out_dir)
    staged: list[tuple[str, str, str]] = []
    for report in manifest.reports:
        pbir = out_dir / report.folder / "definition.pbir"
        content = _read_json(pbir)
        content["datasetReference"] = {"byConnection": live_connection(model_ids[report.model])}
        write_text_lf(pbir, _dump_json(content))
        staged.append((report.folder, report.model, model_ids[report.model]))
    return staged


def apply_report_theme(reports_dir: Path) -> list[str]:
    """Install the manifest's shared theme into every report that has not opted out.

    Copies the theme into the report's ``StaticResources/RegisteredResources/`` and points
    ``themeCollection.customTheme`` at it, as Power BI Desktop does when a theme is
    imported. Other registered resources -- a logo -- are left alone. Returns the folders
    it changed; a second run changes nothing.
    """
    manifest = load_manifest(reports_dir)
    if manifest is None or not manifest.theme:
        raise AuthoredReportsError(f"{MANIFEST_NAME} declares no `theme:` to apply.")
    source = reports_dir / manifest.theme
    if not source.is_file():
        raise AuthoredReportsError(f"The shared theme {manifest.theme} does not exist.")
    name = source.name
    changed: list[str] = []
    for report in manifest.reports:
        report_json = reports_dir / report.folder / "definition" / "report.json"
        if not report.themed or not report_json.is_file():
            continue
        touched = False
        target = reports_dir / report.folder / _RESOURCES_DIR / name
        if not target.is_file() or target.read_bytes() != source.read_bytes():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            touched = True

        before = json.loads(report_json.read_text(encoding="utf-8-sig"))
        content = json.loads(json.dumps(before))
        themes = content.setdefault("themeCollection", {})
        current = themes.get("customTheme", {})
        if current.get("name") != name or current.get("type") != _REGISTERED:
            custom = {"name": name, "type": _REGISTERED}
            version = themes.get("baseTheme", {}).get("reportVersionAtImport")
            if version is not None:
                custom["reportVersionAtImport"] = version
            themes["customTheme"] = custom
        packages = content.setdefault("resourcePackages", [])
        package = next((p for p in packages if p.get("name") == _REGISTERED), None)
        if package is None:
            package = {"name": _REGISTERED, "type": _REGISTERED, "items": []}
            packages.append(package)
        # One custom theme per report: an earlier theme under another file name is
        # replaced where it stood, never kept beside the new one.
        entry = {"name": name, "path": name, "type": "CustomTheme"}
        items: list[dict] = []
        for item in package.get("items", []):
            if item.get("type") != "CustomTheme":
                items.append(item)
            elif entry not in items:
                items.append(entry)
        if entry not in items:
            items.append(entry)
        package["items"] = items
        # Compared as data, so a report Desktop formatted its own way is not rewritten
        # when nothing about its theme changed.
        if content != before:
            write_text_lf(report_json, _dump_json(content))
            touched = True
        if touched:
            changed.append(report.folder)
    return changed
