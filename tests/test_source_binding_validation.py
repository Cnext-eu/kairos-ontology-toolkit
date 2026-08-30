# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for DD-206 §5 structural fail-closed source-binding validation (Group B).

Covers the core validator (``core/source_binding_validation.py``) directly, plus an
end-to-end CLI invocation of ``validate-source-bindings``. Deliberately does not
exercise staleness detection -- that is explicitly out of scope for this module.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.source_binding_validation import (
    FINDING_DUPLICATE,
    FINDING_MISSING,
    FINDING_UNKNOWN,
    SourceBindingDiscoveryError,
    validate_source_bindings,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def _declared_catalog(
    project_root: Path,
    *,
    package_name: str = "customer_ontology_hub",
    source_name: str = "crm",
    tables: tuple[str, ...] = ("customers",),
) -> Path:
    """Write one hub-package emitted ``_{source}__sources.yml`` catalog.

    Mirrors the real emitted shape (``sources.yml.jinja2`` /
    ``dbt.shape._source_catalogs``): ``name``, ``description``, ``tables: [{name}]``.
    A logical-sources-only catalog (the normal dataplatform-facing case) carries no
    database/schema at all -- this module must not depend on them being present.
    """
    path = (
        project_root
        / "dbt_packages"
        / package_name
        / "models"
        / "silver"
        / f"_{source_name}__sources.yml"
    )
    lines = [
        "version: 2",
        "",
        "sources:",
        f"  - name: {source_name}",
        f'    description: "Bronze source: {source_name}"',
        "    # Physical database/schema binding is defined in the dataplatform repo's "
        "_sources.yml.",
        "    tables:",
    ]
    for table in tables:
        lines.append(f"      - name: {table}")
        lines.append(f'        description: "{table}"')
    _write(path, "\n".join(lines) + "\n")
    return path


def _binding_file(
    project_root: Path,
    relative_path: str,
    *,
    source_name: str = "crm",
    database: str = "raw",
    schema: str = "dbo",
    tables: tuple[str, ...] = ("customers",),
) -> Path:
    """Write one dataplatform-owned physical source-binding YAML file."""
    path = project_root / relative_path
    lines = [
        "version: 2",
        "",
        "sources:",
        f"  - name: {source_name}",
        f'    description: "Bronze source: {source_name}"',
        f'    database: "{database}"',
        f'    schema: "{schema}"',
        "    tables:",
    ]
    for table in tables:
        lines.append(f"      - name: {table}")
    _write(path, "\n".join(lines) + "\n")
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A minimal dataplatform project root with dbt_packages/ and models/ present."""
    (tmp_path / "dbt_packages").mkdir()
    (tmp_path / "models").mkdir()
    return tmp_path


def test_fully_valid_case_reports_zero_findings(project):
    _declared_catalog(project, tables=("customers",))
    _binding_file(project, "models/_sources.yml", tables=("customers",))

    report = validate_source_bindings(project)

    assert report.passed
    assert report.findings == ()
    assert report.declared_pairs == 1
    assert report.bound_pairs == 1
    assert report.validated_pairs == 1
    assert report.declared_files == ("dbt_packages/customer_ontology_hub/models/silver/_crm__sources.yml",)
    assert report.binding_files == ("models/_sources.yml",)


def test_missing_binding_is_reported(project):
    _declared_catalog(project, tables=("customers", "orders"))
    _binding_file(project, "models/_sources.yml", tables=("customers",))

    report = validate_source_bindings(project)

    assert not report.passed
    assert report.validated_pairs == 1
    missing = [f for f in report.findings if f.kind == FINDING_MISSING]
    assert len(missing) == 1
    assert missing[0].source_name == "crm"
    assert missing[0].table_name == "orders"
    assert "no physical binding entry" in missing[0].message


def test_unknown_extra_binding_is_reported(project):
    _declared_catalog(project, tables=("customers",))
    _binding_file(project, "models/_sources.yml", tables=("customers", "invoices"))

    report = validate_source_bindings(project)

    assert not report.passed
    assert report.validated_pairs == 1
    unknown = [f for f in report.findings if f.kind == FINDING_UNKNOWN]
    assert len(unknown) == 1
    assert unknown[0].source_name == "crm"
    assert unknown[0].table_name == "invoices"
    assert "does not use it" in unknown[0].message


def test_duplicate_binding_with_conflicting_values_is_reported(project):
    _declared_catalog(project, tables=("customers",))
    _binding_file(
        project,
        "models/_sources.yml",
        database="raw",
        schema="dbo",
        tables=("customers",),
    )
    _binding_file(
        project,
        "models/_sources_override.yml",
        database="raw2",
        schema="dbo2",
        tables=("customers",),
    )

    report = validate_source_bindings(project)

    assert not report.passed
    duplicates = [f for f in report.findings if f.kind == FINDING_DUPLICATE]
    assert len(duplicates) == 1
    assert duplicates[0].source_name == "crm"
    assert duplicates[0].table_name == "customers"
    assert "conflicting database/schema" in duplicates[0].message
    # A conflicting duplicate must not also double-count as validated or missing.
    assert report.validated_pairs == 0
    assert not any(f.kind == FINDING_MISSING for f in report.findings)


def test_duplicate_binding_with_consistent_values_is_not_an_error(project):
    """Repeating the identical (database, schema) across files/blocks is not a conflict."""
    _declared_catalog(project, tables=("customers",))
    _binding_file(project, "models/_sources.yml", database="raw", schema="dbo", tables=("customers",))
    _binding_file(
        project, "models/_sources_dup.yml", database="raw", schema="dbo", tables=("customers",)
    )

    report = validate_source_bindings(project)

    assert report.passed
    assert report.validated_pairs == 1


@pytest.mark.parametrize(
    "database,schema",
    [
        ("", "dbo"),
        ("raw", ""),
        ("your_bronze_database", "your_bronze_schema"),
        ("{DATABASE}", "{SCHEMA}"),
        ("<CONFIRM_DATABASE>", "dbo"),
    ],
)
def test_placeholder_or_empty_database_schema_is_treated_as_missing(project, database, schema):
    _declared_catalog(project, tables=("customers",))
    _binding_file(project, "models/_sources.yml", database=database, schema=schema, tables=("customers",))

    report = validate_source_bindings(project)

    assert not report.passed
    assert report.validated_pairs == 0
    missing = [f for f in report.findings if f.kind == FINDING_MISSING]
    assert len(missing) == 1
    assert "placeholder" in missing[0].message or "empty" in missing[0].message


def test_bindings_split_across_multiple_files_are_merged(project):
    """A user splitting bindings per source system across several models/*.yml files."""
    _declared_catalog(project, source_name="crm", tables=("customers",))
    _declared_catalog(
        project,
        package_name="customer_ontology_hub",
        source_name="dtb",
        tables=("bookings",),
    )
    _binding_file(project, "models/_sources_crm.yml", source_name="crm", tables=("customers",))
    _binding_file(project, "models/_sources_dtb.yml", source_name="dtb", tables=("bookings",))

    report = validate_source_bindings(project)

    assert report.passed
    assert report.declared_pairs == 2
    assert report.validated_pairs == 2
    assert set(report.binding_files) == {"models/_sources_crm.yml", "models/_sources_dtb.yml"}


def test_non_sources_yaml_files_under_models_are_ignored(project):
    """A model properties YAML (models:, not sources:) must not be treated as a binding."""
    _declared_catalog(project, tables=("customers",))
    _binding_file(project, "models/_sources.yml", tables=("customers",))
    _write(
        project / "models" / "silver" / "_party__models.yml",
        """\
        version: 2
        models:
          - name: dim_party
            description: "Party dimension"
        """,
    )

    report = validate_source_bindings(project)

    assert report.passed
    assert report.validated_pairs == 1


def test_missing_dbt_packages_dir_raises_discovery_error(tmp_path):
    (tmp_path / "models").mkdir()
    _binding_file(tmp_path, "models/_sources.yml", tables=("customers",))

    with pytest.raises(SourceBindingDiscoveryError, match="dbt deps"):
        validate_source_bindings(tmp_path)


def test_missing_models_dir_raises_discovery_error(tmp_path):
    (tmp_path / "dbt_packages").mkdir()
    _declared_catalog(tmp_path, tables=("customers",))

    with pytest.raises(SourceBindingDiscoveryError):
        validate_source_bindings(tmp_path)


def test_empty_declared_and_bound_is_a_clean_pass(project):
    """No sources at all (e.g. a brand-new hub) is not itself an error."""
    report = validate_source_bindings(project)

    assert report.passed
    assert report.declared_pairs == 0
    assert report.bound_pairs == 0
    assert report.validated_pairs == 0


def _json_payload(output: str) -> dict:
    """Extract the trailing JSON report from mixed stdout/stderr CLI output.

    ``_emit`` writes ``json.dumps(..., indent=2)`` as the last thing the command
    prints, after every human-readable ``click.echo(..., err=True)`` diagnostic
    line; its first line is a bare ``{``, which no diagnostic line collides with.
    """
    lines = output.splitlines()
    start = max(i for i, line in enumerate(lines) if line == "{")
    return json.loads("\n".join(lines[start:]))


# --- CLI-level end-to-end tests ---------------------------------------------------


def test_cli_reports_success_and_exit_zero_for_valid_project(project):
    _declared_catalog(project, tables=("customers",))
    _binding_file(project, "models/_sources.yml", tables=("customers",))

    result = CliRunner().invoke(
        cli, ["validate-source-bindings", "--project-dir", str(project)]
    )

    assert result.exit_code == 0, result.output
    assert "validated" in result.output
    payload = _json_payload(result.output)
    assert payload["passed"] is True
    assert payload["validated_pairs"] == 1


def test_cli_fails_closed_and_exits_nonzero_for_missing_binding(project):
    _declared_catalog(project, tables=("customers", "orders"))
    _binding_file(project, "models/_sources.yml", tables=("customers",))

    result = CliRunner().invoke(
        cli, ["validate-source-bindings", "--project-dir", str(project)]
    )

    assert result.exit_code != 0
    assert "missing" in result.output
    payload = _json_payload(result.output)
    assert payload["passed"] is False
    assert any(f["kind"] == FINDING_MISSING for f in payload["findings"])


def test_cli_raises_clean_error_when_dbt_deps_not_run(tmp_path):
    (tmp_path / "models").mkdir()
    _binding_file(tmp_path, "models/_sources.yml", tables=("customers",))

    result = CliRunner().invoke(
        cli, ["validate-source-bindings", "--project-dir", str(tmp_path)]
    )

    assert result.exit_code != 0
    assert "dbt deps" in result.output
