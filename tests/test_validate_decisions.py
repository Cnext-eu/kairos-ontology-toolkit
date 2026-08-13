# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Decision-log validation integration tests."""

from pathlib import Path

import pytest

from kairos_ontology.core.validator import (
    propose_lifecycle_state,
    render_validation_markdown,
    run_validation,
)


def _make_hub(tmp_path: Path) -> tuple[Path, Path, Path]:
    ontologies_path = tmp_path / "ontologies"
    shapes_path = tmp_path / "shapes"
    decisions_path = tmp_path / "decisions"
    ontologies_path.mkdir()
    decisions_path.mkdir()
    return ontologies_path, shapes_path, decisions_path


def _write_valid_record(decisions_path: Path) -> None:
    (decisions_path / "HUB-DD-20260728-a1.md").write_text(
        """---
type: Decision Record
id: HUB-DD-20260728-a1
title: T
domain: d
status: stable
decision_state: Accepted
materiality: [evidence-conflict]
generated: { by: kairos-ontology-toolkit/9.9.9, at: 2026-07-28T21:00:00Z }
sources:
  - { resource: https://example.com/x }
---

# Alternatives rejected

| opt | why |
""",
        encoding="utf-8",
    )


def _write_invalid_record(decisions_path: Path) -> None:
    (decisions_path / "HUB-DD-20260728-b1.md").write_text(
        """---
type: Decision Record
id: HUB-DD-20260728-b1
title: T
domain: d
status: stable
decision_state: Accepted
generated: { by: kairos-ontology-toolkit/9.9.9, at: 2026-07-28T21:00:00Z }
---

# Alternatives rejected

| opt | why |
""",
        encoding="utf-8",
    )


def test_run_validation_fails_when_decision_bundle_has_errors(tmp_path: Path) -> None:
    ontologies_path, shapes_path, decisions_path = _make_hub(tmp_path)
    _write_invalid_record(decisions_path)

    with pytest.raises(SystemExit):
        run_validation(
            ontologies_path=ontologies_path,
            shapes_path=shapes_path,
            catalog_path=None,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False,
            decisions_path=decisions_path,
        )


def test_run_validation_passes_when_decision_bundle_is_valid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``_make_hub`` yields an empty ``ontologies_path`` (issue #309's vacuous-set
    case) alongside a valid decision bundle: the run must not fail (no
    ``SystemExit``, no decision-bundle error), but with zero domain ontology
    files present it must report the "nothing was validated" wording rather
    than the unconditional "All validations passed!" a hub with real, passing
    content would earn."""
    ontologies_path, shapes_path, decisions_path = _make_hub(tmp_path)
    _write_valid_record(decisions_path)

    run_validation(
        ontologies_path=ontologies_path,
        shapes_path=shapes_path,
        catalog_path=None,
        do_syntax=True,
        do_shacl=False,
        do_consistency=False,
        decisions_path=decisions_path,
    )

    out = capsys.readouterr().out
    assert "❌ Validation failed" not in out
    assert "nothing was validated" in out
    assert "All validations passed!" not in out


def test_run_validation_skips_absent_decision_bundle(tmp_path: Path) -> None:
    ontologies_path = tmp_path / "ontologies"
    ontologies_path.mkdir()

    run_validation(
        ontologies_path=ontologies_path,
        shapes_path=tmp_path / "missing-shapes",
        catalog_path=None,
        do_syntax=True,
        do_shacl=False,
        do_consistency=False,
        decisions_path=None,
    )


def test_lifecycle_proposal_counts_decision_failures() -> None:
    proposal = propose_lifecycle_state(
        {
            "syntax": {"failed": 0},
            "imports": {"failed": 0},
            "shacl": {"failed": 0},
            "consistency": {"failed": 0},
            "decisions": {"failed": 2},
        },
        do_syntax=True,
        do_shacl=True,
    )

    assert proposal.achieved is False


def test_markdown_report_includes_decision_findings(tmp_path: Path) -> None:
    markdown = render_validation_markdown(
        {
            "syntax": {"passed": 0, "failed": 0, "errors": []},
            "imports": {"passed": 0, "failed": 0, "errors": [], "warnings": []},
            "shacl": {"passed": 0, "failed": 0, "errors": []},
            "consistency": {"passed": 0, "failed": 0, "errors": []},
            "decisions": {
                "passed": 0,
                "failed": 1,
                "errors": [
                    {
                        "level": "error",
                        "category": "kairos_decision",
                        "code": "missing_sources",
                        "message": "missing sources",
                        "file": "HUB-DD-20260728-b1.md",
                    }
                ],
                "warnings": [],
            },
        },
        toolkit_version="9.9.9",
        ontologies_path=tmp_path / "ontologies",
        shapes_path=tmp_path / "shapes",
        catalog_path=None,
        ref_models_dir=None,
        accelerator=None,
        do_syntax=True,
        do_shacl=False,
        do_consistency=False,
        degraded=False,
        ontology_files=[],
    )

    assert "| decisions |" in markdown
    assert "### Decisions errors" in markdown
