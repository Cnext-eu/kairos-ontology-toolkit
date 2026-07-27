# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Explicit, reviewable regeneration path for ``fixtures/dbt_artifact_baseline.json``.

``fixtures/dbt_artifact_baseline.json`` is the byte-identity oracle asserted
by ``test_scenario_dbt_characterization.py`` — it pins the complete
generated artifact set as a single ordered ``artifact_keys`` sequence
(file artifacts and non-file ``__``-prefixed facts interleaved exactly as
``generate_dbt_artifacts`` emitted them — splitting these into separate
lists would lose their relative interleaving), plus a SHA-256 hash of every
artifact's bytes, for the ``acme-hub`` client/invoice/logistics scenarios.
It must never be regenerated to silently paper over an unintended output
change.

This module is intentionally **not** named ``test_*.py`` / ``*_test.py``, so
pytest's default collection (``testpaths = ["tests"]`` with the default
``python_files`` pattern, see ``pyproject.toml``) never picks it up. It only
ever runs when invoked directly, and never writes the baseline unless
``--write`` is passed explicitly.

Usage
-----
Preview what would change, without writing anything (safe, read-only;
exits with status 1 if any domain would change so it is CI/script-friendly).
Run from the repository root, either directly or as a module — both work
without an installed ``tests`` package or ambient ``PYTHONPATH``:

    uv run python tests\\scenarios\\regenerate_dbt_artifact_baseline.py
    uv run python -m tests.scenarios.regenerate_dbt_artifact_baseline

Regenerate the baseline after reviewing the diff above and confirming the
output change is deliberate:

    uv run python tests\\scenarios\\regenerate_dbt_artifact_baseline.py --write
    uv run python -m tests.scenarios.regenerate_dbt_artifact_baseline --write

After writing, review the diff key-by-key before committing — a passing
semantic check is not sufficient, byte stability is the contract:

    git diff tests/scenarios/fixtures/dbt_artifact_baseline.json

Then re-run the characterization suite to confirm it is green against the
freshly written baseline:

    uv run pytest tests/scenarios/test_scenario_dbt_characterization.py -q

The hashing/ordering logic here is imported directly from
``test_scenario_dbt_characterization`` (not reimplemented) so the baseline
this script writes and the baseline that module reads are always produced
by the exact same, deterministic logic.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Running this file directly (``python tests\scenarios\regenerate_...py``) puts
# the script's own directory, not the repository root, on ``sys.path[0]``, so
# ``tests`` (a real package, see tests/__init__.py) would not be importable.
# Insert the repository root explicitly, matching the pattern used by
# tests/test_scaffold_sync.py, so the exact same command works whether invoked
# directly or via ``-m`` — no installed ``tests`` package or ambient
# ``PYTHONPATH`` required.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.scenarios import conftest as _conftest  # noqa: E402
from tests.scenarios.test_scenario_dbt_characterization import (  # noqa: E402
    BASELINE_PATH,
    _hash_artifacts,
)


def _client_artifacts() -> dict:
    from kairos_ontology.core.projections.medallion_dbt_projector import (
        generate_dbt_artifacts,
    )

    graph, namespace, classes = _conftest._load_ontology("client")
    gold_ext = _conftest.EXTENSIONS_DIR / "client-gold-ext.ttl"
    silver_ext = _conftest.EXTENSIONS_DIR / "client-silver-ext.ttl"
    return generate_dbt_artifacts(
        classes=classes,
        graph=graph,
        template_dir=_conftest.TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=_conftest.SHAPES_DIR,
        ontology_name="client",
        ontology_metadata={
            "iri": "https://acme.example/ontology/client",
            "version": "1.0.0",
        },
        bronze_dir=_conftest.SOURCES_DIR,
        sources_dir=_conftest.SOURCES_DIR,
        mappings_dir=_conftest.MAPPINGS_DIR,
        gold_ext_path=gold_ext if gold_ext.exists() else None,
        silver_ext_path=silver_ext if silver_ext.exists() else None,
    )


def _invoice_artifacts() -> dict:
    from kairos_ontology.core.projections.medallion_dbt_projector import (
        generate_dbt_artifacts,
    )

    graph, namespace, classes = _conftest._load_ontology("invoice")
    gold_ext = _conftest.EXTENSIONS_DIR / "invoice-gold-ext.ttl"
    silver_ext = _conftest.EXTENSIONS_DIR / "invoice-silver-ext.ttl"
    client_silver_ext = _conftest.EXTENSIONS_DIR / "client-silver-ext.ttl"
    peer_exts = [client_silver_ext] if client_silver_ext.exists() else []
    return generate_dbt_artifacts(
        classes=classes,
        graph=graph,
        template_dir=_conftest.TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=_conftest.SHAPES_DIR,
        ontology_name="invoice",
        ontology_metadata={
            "iri": "https://acme.example/ontology/invoice",
            "version": "1.0.0",
        },
        bronze_dir=_conftest.SOURCES_DIR,
        sources_dir=_conftest.SOURCES_DIR,
        mappings_dir=_conftest.MAPPINGS_DIR,
        gold_ext_path=gold_ext if gold_ext.exists() else None,
        silver_ext_path=silver_ext if silver_ext.exists() else None,
        peer_ext_paths=peer_exts,
    )


def _logistics_artifacts() -> dict:
    from kairos_ontology.core.projections.medallion_dbt_projector import (
        generate_dbt_artifacts,
    )

    graph, namespace, classes = _conftest._load_ontology_with_imports("logistics")
    silver_ext = _conftest.EXTENSIONS_DIR / "logistics-silver-ext.ttl"
    return generate_dbt_artifacts(
        classes=classes,
        graph=graph,
        template_dir=_conftest.TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=_conftest.SHAPES_DIR,
        ontology_name="logistics",
        sources_dir=_conftest.SOURCES_DIR,
        mappings_dir=_conftest.MAPPINGS_DIR,
        silver_ext_path=silver_ext if silver_ext.exists() else None,
    )


_DOMAIN_BUILDERS = {
    "client": _client_artifacts,
    "invoice": _invoice_artifacts,
    "logistics": _logistics_artifacts,
}


def _compute_current_hashes() -> dict[str, dict]:
    return {label: _hash_artifacts(build()) for label, build in _DOMAIN_BUILDERS.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the freshly computed hashes to fixtures/dbt_artifact_baseline.json. "
        "Without this flag, only a diff summary is printed (nothing is written).",
    )
    args = parser.parse_args(argv)

    existing = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    current = _compute_current_hashes()

    changed = False
    for label in _DOMAIN_BUILDERS:
        old = existing.get(label, {})
        new = current[label]
        if old.get("artifact_keys") != new["artifact_keys"]:
            changed = True
            print(f"[{label}] artifact_keys changed (set, order, and/or file/meta interleaving).")
        old_hashes = old.get("hashes", {})
        drifted = sorted(
            key for key in new["hashes"] if old_hashes.get(key) != new["hashes"][key]
        )
        if drifted:
            changed = True
            print(f"[{label}] byte content changed for: {drifted}")

    if not changed:
        print("No drift detected — baseline already matches current output.")
        return 0

    if not args.write:
        print(
            "\nDrift detected above. Re-run with --write to regenerate the baseline "
            "ONLY if this change is deliberate and reviewed."
        )
        return 1

    BASELINE_PATH.write_text(
        json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"\nWrote {BASELINE_PATH}. Review the diff before committing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
