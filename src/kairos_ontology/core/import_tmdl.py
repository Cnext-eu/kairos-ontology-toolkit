# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Import-TMDL orchestration — detect input type, extract, parse, generate outputs.

This module coordinates the full import-tmdl workflow:
1. Detect whether input is a ZIP, Fabric git-integration pointer file, folder,
   or standalone file
2. Extract ZIP (or resolve pointer artifacts) and locate SemanticModel
   definition folders
3. Parse TMDL content using the tmdl_parser module
4. Generate Engineering Pack (markdown) and Concept Mapping (YAML)
"""

from __future__ import annotations

import json
import logging
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml

from .hub_utils import resolve_hub_output_dir
from .tmdl_parser import TmdlModel, parse_model_folder, parse_tmdl_content

logger = logging.getLogger(__name__)

# Declared home for Power BI demand evidence, relative to the hub root. Scaffolded
# by init/new-repo and read back from the hub root by draft-model-report and
# design-landscape, so writer and readers must agree on the anchor (issue #296).
_BI_DISCOVERY_RELPATH = Path("integration") / "discovery" / "bi"


def _is_pbip_pointer_file(path: Path) -> bool:
    """Best-effort sniff for a Fabric git-integration ``.pbip`` pointer file.

    A modern Fabric ``.pbip`` is not a ZIP archive at all — it's a small JSON
    document with an ``artifacts`` list pointing at sibling ``<name>.Report/``
    and ``<name>.SemanticModel/`` folders on disk (issue #387). Any failure to
    read/parse, or JSON that doesn't look like a pointer file, means "not a
    pointer" — the caller falls through to the legacy zip-suffix/magic-byte
    handling unchanged, so legitimate legacy zip-format ``.pbip`` files are
    never affected by this sniff.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return False
    return isinstance(data, dict) and isinstance(data.get("artifacts"), list)


def detect_input_type(path: Path) -> Literal["zip", "pointer", "folder", "file"]:
    """Detect the type of TMDL input.

    Returns:
        "zip"     — a ZIP/PBIP archive
        "pointer" — a Fabric git-integration ``.pbip`` pointer file (JSON
                    referencing sibling ``.Report``/``.SemanticModel`` folders,
                    not a zip archive — issue #387)
        "folder"  — a SemanticModel/definition/ directory (or parent)
        "file"    — a standalone .tmdl file
    """
    if path.is_file():
        if path.suffix.lower() == ".pbip" and _is_pbip_pointer_file(path):
            return "pointer"
        if path.suffix.lower() in (".zip", ".pbip"):
            return "zip"
        if path.suffix.lower() == ".tmdl":
            return "file"
        # Try to detect ZIP by magic bytes
        try:
            if zipfile.is_zipfile(path):
                return "zip"
        except OSError:
            pass
        return "file"
    elif path.is_dir():
        return "folder"
    else:
        raise FileNotFoundError(f"Input path does not exist: {path}")


def find_definition_dirs(base: Path) -> list[Path]:
    """Find all SemanticModel definition/ directories under a base path.

    Looks for directories matching the pattern:
        **/?.SemanticModel/definition/  or  **/definition/ (with model.tmdl)
    """
    results = []

    # Direct: base IS a definition dir
    if (base / "model.tmdl").exists():
        results.append(base)
        return results

    # Direct: base is a SemanticModel dir
    if base.name.endswith(".SemanticModel") and (base / "definition").is_dir():
        results.append(base / "definition")
        return results

    # Search recursively for definition dirs containing model.tmdl
    for model_file in base.rglob("model.tmdl"):
        parent = model_file.parent
        if parent.name == "definition":
            results.append(parent)

    return sorted(set(results))


def extract_pbip_zip(zip_path: Path, dest: Path) -> list[Path]:
    """Extract a PBIP/ZIP archive and return definition directory paths.

    Args:
        zip_path: Path to the ZIP file
        dest: Destination directory for extraction

    Returns:
        List of definition/ directory paths found after extraction
    """
    dest.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest)

    return find_definition_dirs(dest)


def resolve_pbip_pointer(pointer_path: Path) -> list[Path]:
    """Resolve a Fabric git-integration ``.pbip`` pointer file to artifact folders.

    Reads the pointer JSON, extracts each ``artifacts[].report.path`` /
    ``artifacts[].dataset.path`` entry, and resolves it relative to the
    pointer file's own directory (``pointer_path.parent`` — NOT the current
    working directory, since the pointer is typically opened from elsewhere).

    Individual referenced folders that don't exist on disk are skipped —
    tolerant of partial exports, matching this codebase's existing style (e.g.
    import-flatfile's directory-mode tolerance) — but if the pointer
    references artifacts and *none* of them resolve to an existing folder,
    that's treated as a hard failure rather than a silent empty result, since
    it means the export is missing its actual TMDL/report content entirely.

    Args:
        pointer_path: Path to the ``.pbip`` pointer file.

    Returns:
        List of resolved, existing artifact folder paths (e.g.
        ``<name>.Report``, ``<name>.SemanticModel``).

    Raises:
        ValueError: if the pointer file references one or more artifacts but
            none of the referenced folders exist on disk.
    """
    data = json.loads(pointer_path.read_text(encoding="utf-8"))
    base = pointer_path.parent

    referenced: list[str] = []
    resolved: list[Path] = []

    for artifact in data.get("artifacts", []) or []:
        if not isinstance(artifact, dict):
            continue
        for kind in ("report", "dataset"):
            entry = artifact.get(kind)
            if not isinstance(entry, dict):
                continue
            rel_path = entry.get("path")
            if not rel_path:
                continue
            referenced.append(rel_path)
            candidate = base / rel_path
            if candidate.is_dir():
                resolved.append(candidate)

    if referenced and not resolved:
        listed = ", ".join(sorted(set(referenced)))
        raise ValueError(
            f"PBIP pointer file {pointer_path} references artifact folder(s) "
            f"({listed}) but none of them exist on disk next to the pointer "
            "file. This typically means the export shipped the .pbip pointer "
            "file without the actual '<name>.Report'/'<name>.SemanticModel' "
            "folder contents — re-export with the full project folder "
            "structure, or run import-tmdl directly against the "
            "'<name>.SemanticModel' folder if you already have it."
        )

    return resolved


def generate_engineering_pack(model: TmdlModel, source_label: str = "") -> str:
    """Generate an Engineering Pack markdown document from a parsed TMDL model.

    Args:
        model: Parsed TMDL model
        source_label: Human-readable source path label

    Returns:
        Markdown string
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total_columns = sum(len(t.columns) for t in model.tables)
    total_measures = sum(len(t.measures) for t in model.tables)

    lines = [
        f"# {model.name or 'Unnamed Model'} — Ontology Engineering Pack",
        "",
        f"Generated: {now}",
    ]
    if source_label:
        lines.append(f"Source: {source_label}")
    lines.append("")

    # Global inventory
    lines.extend(
        [
            "## Global Inventory",
            f"- Tables: {len(model.tables)}",
            f"- Columns: {total_columns}",
            f"- Measures: {total_measures}",
            f"- Relationships: {len(model.relationships)}",
        ]
    )
    if model.compatibility_level:
        lines.append(f"- Compatibility Level: {model.compatibility_level}")
    if model.default_mode:
        lines.append(f"- Default Mode: {model.default_mode}")
    lines.append("")

    # Table summary
    lines.extend(
        [
            "## Table Summary",
            "| Table | Type | Columns | Measures | Partition |",
            "|---|---|---:|---:|---|",
        ]
    )
    for t in model.tables:
        lines.append(
            f"| {t.name} | {t.table_type} | {len(t.columns)} "
            f"| {len(t.measures)} | {t.partition_type} |"
        )
    lines.append("")

    # Detailed table inventory
    lines.append("## Table and Column Inventory")
    for t in model.tables:
        lines.append(f"### {t.name}")
        if t.description:
            lines.append(f"*{t.description}*")
        if t.is_hidden:
            lines.append("*(hidden)*")
        lines.append("")

        if t.columns:
            lines.append("**Columns:**")
            lines.append("")
            for col in t.columns:
                hidden = " *(hidden)*" if col.is_hidden else ""
                fmt = f" [{col.format_string}]" if col.format_string else ""
                lines.append(f"- `{col.name}` ({col.data_type}{fmt}){hidden}")
            lines.append("")

        if t.measures:
            lines.append("**Measures:**")
            lines.append("")
            for m in t.measures:
                expr_preview = m.expression.split("\n")[0][:60] if m.expression else ""
                if len(m.expression) > 60 or "\n" in m.expression:
                    expr_preview += "..."
                lines.append(f"- `{m.name}` = `{expr_preview}`")
            lines.append("")

    # Relationships
    if model.relationships:
        lines.extend(
            [
                "## Relationships (Ontology Edges)",
                "",
            ]
        )
        for rel in model.relationships:
            active = "" if rel.is_active else " *(inactive)*"
            card = f"{rel.from_cardinality}-to-{rel.to_cardinality}"
            lines.append(
                f"- {rel.from_table}.{rel.from_column} → "
                f"{rel.to_table}.{rel.to_column} | {card}{active}"
            )
        lines.append("")

    return "\n".join(lines)


def generate_concept_mapping(model: TmdlModel) -> str:
    """Generate a Concept Mapping YAML template from a parsed TMDL model.

    The YAML includes pre-filled TMDL information and empty fields for the
    modeler to fill in (reference_model_match, action, notes).

    Returns:
        YAML string
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    data: dict = {
        "schema_version": "1",
        "model_name": model.name or "Unnamed",
        "generated_at": now,
        "tables": [],
        "relationships": [],
    }

    for t in model.tables:
        table_entry: dict = {
            "tmdl_name": t.name,
            "type": t.table_type,
            "columns": [c.name for c in t.columns],
            "measures": [
                {"name": m.name, "expression": m.expression, "format_string": m.format_string}
                for m in t.measures
            ],
            "domain": "",
            "reference_model_match": "",
            "action": "",
            "notes": "",
        }
        if t.is_hidden:
            table_entry["is_hidden"] = True
        data["tables"].append(table_entry)

    for rel in model.relationships:
        rel_entry: dict = {
            "from": f"{rel.from_table}.{rel.from_column}",
            "to": f"{rel.to_table}.{rel.to_column}",
            "cardinality": f"{rel.from_cardinality}-to-{rel.to_cardinality}",
            "domain": "",
            "reference_model_match": "",
        }
        if not rel.is_active:
            rel_entry["is_active"] = False
        data["relationships"].append(rel_entry)

    # Generate YAML with a header comment
    header = (
        "# Auto-generated concept mapping template\n"
        "# Review and fill in 'reference_model_match' and 'action' fields\n"
        "#\n"
        "# action values: use | specialize | new_class | skip\n"
        "#   use        — maps directly to an existing reference model class\n"
        "#   specialize — needs a subclass of a reference model class\n"
        "#   new_class  — no reference model match; create a local class\n"
        "#   skip       — not relevant for ontology (e.g., measure-only table)\n"
        "\n"
    )
    return header + yaml.dump(data, default_flow_style=False, sort_keys=False, width=100)


def run_import_tmdl(source: Path, output_dir: Path | None = None) -> list[Path]:
    """Main entry point: detect input, parse, and generate outputs.

    Args:
        source: Path to ZIP, folder, or .tmdl file
        output_dir: Directory to write output files. When ``None``, resolves to
            ``<hub root>/integration/discovery/bi`` via
            :func:`~kairos_ontology.core.hub_utils.resolve_hub_output_dir`; a
            cwd-relative default would create a stray ``integration/`` tree
            outside the hub whenever the command is run from the repo root
            (issue #296).

    Returns:
        List of generated output file paths
    """
    if output_dir is None:
        output_dir, hub_root = resolve_hub_output_dir(_BI_DISCOVERY_RELPATH)
        if hub_root is None:
            logger.warning(
                "Could not detect ontology-hub root (no ontology-hub/ or "
                "model/ontologies/ found). "
                "Writing to relative path: %s. "
                "Use --output to specify an explicit output directory.",
                output_dir,
            )

    input_type = detect_input_type(source)
    generated_files: list[Path] = []

    if input_type == "zip":
        # Extract to a throwaway temp directory, never into output_dir. A PBIP
        # archive carries the whole report — .Report/ definition JSON,
        # .pbi/localSettings.json, expression.tmdl with M queries and server
        # names — and output_dir is a committed hub folder whose contract is two
        # derived artifacts only ("Never commit credentials, connection strings,
        # raw personal data, or proprietary report content", see that folder's
        # README). Extracting in place also accumulated stale members across
        # re-runs, since extractall never prunes (issue #296).
        with tempfile.TemporaryDirectory(prefix="kairos-tmdl-") as tmp:
            definition_dirs = extract_pbip_zip(source, Path(tmp) / source.stem)
            if not definition_dirs:
                logger.warning("No SemanticModel definition/ found in ZIP: %s", source)
                return []
            for def_dir in definition_dirs:
                model = parse_model_folder(def_dir)
                files = _write_outputs(model, output_dir, str(source))
                generated_files.extend(files)

    elif input_type == "pointer":
        # Modern Fabric git-integration .pbip — a JSON pointer to sibling
        # <name>.Report/<name>.SemanticModel folders, not an archive to
        # extract (issue #387). resolve_pbip_pointer() raises a clear error if
        # the pointer references artifacts but none resolve on disk; once
        # resolved, feed each artifact folder into the same
        # find_definition_dirs()/parse_model_folder() pipeline the "folder"
        # branch uses (a .Report folder simply yields no definition dirs).
        artifact_dirs = resolve_pbip_pointer(source)
        definition_dirs = sorted(
            {d for folder in artifact_dirs for d in find_definition_dirs(folder)}
        )
        if not definition_dirs:
            logger.warning("No SemanticModel definition/ found via PBIP pointer: %s", source)
            return []
        for def_dir in definition_dirs:
            model = parse_model_folder(def_dir)
            files = _write_outputs(model, output_dir, str(source))
            generated_files.extend(files)

    elif input_type == "folder":
        definition_dirs = find_definition_dirs(source)
        if not definition_dirs:
            logger.warning("No SemanticModel definition/ found in: %s", source)
            return []
        for def_dir in definition_dirs:
            model = parse_model_folder(def_dir)
            files = _write_outputs(model, output_dir, str(source))
            generated_files.extend(files)

    elif input_type == "file":
        # Single .tmdl file — parse directly
        content = source.read_text(encoding="utf-8")
        items = parse_tmdl_content(content)
        model = TmdlModel(name=source.stem)
        for item in items:
            if hasattr(item, "columns"):
                model.tables.append(item)
            else:
                model.relationships.append(item)
        files = _write_outputs(model, output_dir, str(source))
        generated_files.extend(files)

    return generated_files


def _write_outputs(model: TmdlModel, output_dir: Path, source_label: str) -> list[Path]:
    """Write engineering pack and concept mapping for a model."""
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []

    slug = model.name or "unnamed-model"

    # Engineering Pack
    pack_path = output_dir / f"{slug}-engineering-pack.md"
    pack_content = generate_engineering_pack(model, source_label)
    pack_path.write_text(pack_content, encoding="utf-8")
    generated.append(pack_path)
    logger.info("Generated: %s", pack_path)

    # Concept Mapping
    mapping_path = output_dir / f"{slug}-concept-mapping.yaml"
    mapping_content = generate_concept_mapping(model)
    mapping_path.write_text(mapping_content, encoding="utf-8")
    generated.append(mapping_path)
    logger.info("Generated: %s", mapping_path)

    return generated
