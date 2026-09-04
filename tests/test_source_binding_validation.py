# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for DD-206 §5 fail-closed source-binding validation (Group B).

Covers the core validator (``core/source_binding_validation.py``) directly -- both
the structural checks (missing/unknown/duplicate) and staleness (opt-in via
``current_hub_sha``) -- plus ``stamp_verified_bindings()``, and end-to-end CLI
invocations of ``validate-source-bindings`` including ``--hub-sha``/auto-read from
``packages.yml`` and ``--confirm``.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import _rewrite_hub_package_pin, cli
from kairos_ontology.core.projections.dbt.specs import HUB_DBT_PACKAGE_NAME
from kairos_ontology.core.source_binding_validation import (
    FINDING_DUPLICATE,
    FINDING_MISSING,
    FINDING_MISSING_OVERRIDE,
    FINDING_STALE,
    FINDING_UNKNOWN,
    SourceBindingDiscoveryError,
    stamp_verified_bindings,
    validate_source_bindings,
)

SHA_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SHA_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


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
    verified_hub_sha: str | None = None,
    overrides: str | None = HUB_DBT_PACKAGE_NAME,
) -> Path:
    """Write one dataplatform-owned physical source-binding YAML file.

    *verified_hub_sha*, when given, adds the DD-206 §5 staleness-tracking
    ``meta.kairos.verified_hub_sha`` key at the source level (native dbt ``meta:``,
    just a new key read from under it -- see ``_sources.yml.template``'s header).

    *overrides* defaults to the hub package name because that is what a correctly
    authored binding carries: without it dbt does not rebind the package's source at
    all (#701). Pass ``None`` to reproduce the inert shape.
    """
    path = project_root / relative_path
    lines = [
        "version: 2",
        "",
        "sources:",
        f"  - name: {source_name}",
        f'    description: "Bronze source: {source_name}"',
    ]
    if overrides is not None:
        lines.append(f"    overrides: {overrides}")
    lines += [
        f'    database: "{database}"',
        f'    schema: "{schema}"',
    ]
    if verified_hub_sha is not None:
        lines += [
            "    meta:",
            "      kairos:",
            f'        verified_hub_sha: "{verified_hub_sha}"',
        ]
    lines.append("    tables:")
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


def test_a_rebinding_source_without_overrides_is_reported(project):
    """#701: the gate could be fully green while the pipeline pointed at nothing.

    dbt needs `overrides: <package>` to *redirect* a package's source. Without it a
    same-named root-project source is a second, unrelated node: `dbt parse` passes, the
    hub's models keep resolving to the values the hub itself declared, DD-206 §5
    name-matching is satisfied, and the first symptom is a missing relation at
    `dbt run`, far from the cause. Measured on a real pair as 34 tables silently
    resolving to a database holding no data.
    """
    _declared_catalog(project, tables=("customers",))
    _binding_file(project, "models/_sources.yml", tables=("customers",), overrides=None)

    report = validate_source_bindings(project)

    assert not report.passed
    findings = [f for f in report.findings if f.kind == FINDING_MISSING_OVERRIDE]
    assert len(findings) == 1
    assert findings[0].source_name == "crm"
    assert "overrides: kairos_medallion_project" in findings[0].message
    # Not counted as validated: the binding does not take effect.
    assert report.validated_pairs == 0


def test_a_correctly_overridden_source_reports_nothing(project):
    """Non-vacuity guard for the check above."""
    _declared_catalog(project, tables=("customers",))
    _binding_file(project, "models/_sources.yml", tables=("customers",))

    report = validate_source_bindings(project)

    assert report.passed
    assert not [f for f in report.findings if f.kind == FINDING_MISSING_OVERRIDE]


def test_a_source_the_package_does_not_use_needs_no_overrides(project):
    """Scoped to sources that actually shadow a package source.

    A dataplatform declaring its own Bronze catalogs for its own models is ordinary and
    must not be told to add `overrides:` to them.
    """
    _declared_catalog(project, tables=("customers",))
    _binding_file(project, "models/_sources.yml", tables=("customers",))
    _binding_file(
        project,
        "models/own/_local.yml",
        source_name="local_raw",
        tables=("events",),
        overrides=None,
    )

    report = validate_source_bindings(project)

    assert not [f for f in report.findings if f.kind == FINDING_MISSING_OVERRIDE]


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


# --- staleness detection (DD-206 §5's fourth finding type) -------------------------


def test_no_staleness_checking_when_current_hub_sha_is_omitted(project):
    """Default (current_hub_sha=None) is fully backward compatible: no stale findings."""
    _declared_catalog(project, tables=("customers",))
    _binding_file(project, "models/_sources.yml", tables=("customers",))  # no verified_hub_sha

    report = validate_source_bindings(project)

    assert report.passed
    assert not any(f.kind == FINDING_STALE for f in report.findings)


def test_matching_verified_hub_sha_is_not_stale(project):
    _declared_catalog(project, tables=("customers",))
    _binding_file(
        project, "models/_sources.yml", tables=("customers",), verified_hub_sha=SHA_A
    )

    report = validate_source_bindings(project, current_hub_sha=SHA_A)

    assert report.passed
    assert not any(f.kind == FINDING_STALE for f in report.findings)


def test_mismatched_verified_hub_sha_is_stale(project):
    _declared_catalog(project, tables=("customers",))
    _binding_file(
        project, "models/_sources.yml", tables=("customers",), verified_hub_sha=SHA_A
    )

    report = validate_source_bindings(project, current_hub_sha=SHA_B)

    assert not report.passed
    stale = [f for f in report.findings if f.kind == FINDING_STALE]
    assert len(stale) == 1
    assert stale[0].source_name == "crm"
    assert stale[0].table_name == ""  # once per source, not per table
    assert SHA_B in stale[0].message


def test_missing_verified_hub_sha_is_stale_only_when_current_hub_sha_given(project):
    _declared_catalog(project, tables=("customers",))
    _binding_file(project, "models/_sources.yml", tables=("customers",))  # no meta at all

    without_check = validate_source_bindings(project)
    assert not any(f.kind == FINDING_STALE for f in without_check.findings)

    with_check = validate_source_bindings(project, current_hub_sha=SHA_A)
    stale = [f for f in with_check.findings if f.kind == FINDING_STALE]
    assert len(stale) == 1
    assert stale[0].source_name == "crm"
    assert "never recorded" in stale[0].message


def test_stale_finding_reported_once_per_source_not_per_table(project):
    _declared_catalog(project, tables=("customers", "orders"))
    _binding_file(
        project,
        "models/_sources.yml",
        tables=("customers", "orders"),
        verified_hub_sha=SHA_A,
    )

    report = validate_source_bindings(project, current_hub_sha=SHA_B)

    stale = [f for f in report.findings if f.kind == FINDING_STALE]
    assert len(stale) == 1


def test_source_with_no_bindings_at_all_cannot_be_stale(project):
    """A declared-but-unbound source is `missing`, never additionally `stale`."""
    _declared_catalog(project, tables=("customers",))
    # No binding file at all for this source.

    report = validate_source_bindings(project, current_hub_sha=SHA_A)

    assert not any(f.kind == FINDING_STALE for f in report.findings)
    assert any(f.kind == FINDING_MISSING for f in report.findings)


# --- stamp_verified_bindings --------------------------------------------------------


def test_stamp_verified_bindings_adds_meta_when_absent(project):
    path = _binding_file(project, "models/_sources.yml", tables=("customers",))
    original = path.read_text(encoding="utf-8")

    report = stamp_verified_bindings(project, SHA_A)

    assert report.hub_sha == SHA_A
    assert report.stamped_sources == ("crm",)
    assert report.updated_files == ("models/_sources.yml",)
    rewritten = path.read_text(encoding="utf-8")
    assert rewritten != original
    parsed = yaml.safe_load(rewritten)
    assert parsed["sources"][0]["meta"]["kairos"]["verified_hub_sha"] == SHA_A
    # Everything else is preserved.
    assert parsed["sources"][0]["database"] == "raw"
    assert parsed["sources"][0]["schema"] == "dbo"
    assert parsed["sources"][0]["tables"] == [{"name": "customers"}]


def test_stamp_verified_bindings_updates_only_the_sha_field(project):
    path = _binding_file(
        project, "models/_sources.yml", tables=("customers",), verified_hub_sha=SHA_A
    )
    original_lines = path.read_text(encoding="utf-8").splitlines()

    stamp_verified_bindings(project, SHA_B)

    new_lines = path.read_text(encoding="utf-8").splitlines()
    assert len(new_lines) == len(original_lines)
    changed = [
        (old, new) for old, new in zip(original_lines, new_lines, strict=True) if old != new
    ]
    assert len(changed) == 1
    old_line, new_line = changed[0]
    assert SHA_A in old_line
    assert SHA_B in new_line
    # Only the value differs -- same key, same indentation.
    assert old_line.replace(SHA_A, "") == new_line.replace(SHA_B, "")


def test_stamp_verified_bindings_is_idempotent_and_leaves_file_untouched_when_current(project):
    path = _binding_file(
        project, "models/_sources.yml", tables=("customers",), verified_hub_sha=SHA_A
    )
    before = path.read_text(encoding="utf-8")

    report = stamp_verified_bindings(project, SHA_A)

    after = path.read_text(encoding="utf-8")
    assert after == before
    assert report.updated_files == ()  # nothing rewritten -- already current
    assert report.stamped_sources == ("crm",)  # still reported as covered


def test_stamp_verified_bindings_covers_every_source_across_split_files(project):
    _binding_file(project, "models/_sources_crm.yml", source_name="crm", tables=("customers",))
    _binding_file(project, "models/_sources_dtb.yml", source_name="dtb", tables=("bookings",))

    report = stamp_verified_bindings(project, SHA_A)

    assert set(report.stamped_sources) == {"crm", "dtb"}
    assert len(report.updated_files) == 2


def test_stamp_verified_bindings_rejects_non_sha_input(project):
    _binding_file(project, "models/_sources.yml", tables=("customers",))

    with pytest.raises(ValueError, match="40-character"):
        stamp_verified_bindings(project, "v1.0.0")


def test_stamp_then_validate_round_trip_is_no_longer_stale(project):
    _declared_catalog(project, tables=("customers",))
    _binding_file(project, "models/_sources.yml", tables=("customers",), verified_hub_sha=SHA_A)

    stamp_verified_bindings(project, SHA_B)
    report = validate_source_bindings(project, current_hub_sha=SHA_B)

    assert report.passed
    assert not any(f.kind == FINDING_STALE for f in report.findings)


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


# --- CLI: --hub-sha / auto-read from packages.yml / --confirm ---------------------


_PLACEHOLDER_PACKAGES_YML = (
    "packages:\n"
    '  # - git: "https://github.com/acme/customer-ontology-hub.git"\n'
    '  #   revision: "v1.0.0"\n'
    "  #   subdirectory: ontology-hub-publish/medallion/dbt\n"
)


def _write_packages_yml(project_root: Path, sha: str | None) -> Path:
    """Write a packages.yml with the hub package pinned to *sha* (or still a placeholder tag).

    ``_parse_hub_package_pin`` reads ``previous_revision`` regardless of whether the
    block is commented out, so the placeholder (pre-``bump-hub``) form is exercised
    as-is when *sha* is ``None`` -- no need to uncomment it.
    """
    content = (
        _rewrite_hub_package_pin(_PLACEHOLDER_PACKAGES_YML, sha)
        if sha is not None
        else _PLACEHOLDER_PACKAGES_YML
    )
    path = project_root / "packages.yml"
    path.write_text(content, encoding="utf-8")
    return path


def test_cli_reports_stale_finding_via_explicit_hub_sha(project):
    _declared_catalog(project, tables=("customers",))
    _binding_file(
        project, "models/_sources.yml", tables=("customers",), verified_hub_sha=SHA_A
    )

    result = CliRunner().invoke(
        cli,
        ["validate-source-bindings", "--project-dir", str(project), "--hub-sha", SHA_B],
    )

    assert result.exit_code != 0
    assert "stale" in result.output
    payload = _json_payload(result.output)
    assert any(f["kind"] == FINDING_STALE for f in payload["findings"])


def test_cli_rejects_malformed_hub_sha(project):
    _declared_catalog(project, tables=("customers",))
    _binding_file(project, "models/_sources.yml", tables=("customers",))

    result = CliRunner().invoke(
        cli,
        ["validate-source-bindings", "--project-dir", str(project), "--hub-sha", "not-a-sha"],
    )

    assert result.exit_code != 0
    assert "40-character" in result.output


def test_cli_auto_reads_hub_sha_from_packages_yml(project):
    _declared_catalog(project, tables=("customers",))
    _binding_file(
        project, "models/_sources.yml", tables=("customers",), verified_hub_sha=SHA_A
    )
    _write_packages_yml(project, SHA_B)

    result = CliRunner().invoke(
        cli, ["validate-source-bindings", "--project-dir", str(project)]
    )

    assert result.exit_code != 0
    payload = _json_payload(result.output)
    stale = [f for f in payload["findings"] if f["kind"] == FINDING_STALE]
    assert len(stale) == 1


def test_cli_skips_staleness_when_packages_yml_absent(project):
    """No packages.yml at all (repo hasn't adopted bump-hub-style pinning): not an error."""
    _declared_catalog(project, tables=("customers",))
    _binding_file(project, "models/_sources.yml", tables=("customers",))  # no verified_hub_sha

    result = CliRunner().invoke(
        cli, ["validate-source-bindings", "--project-dir", str(project)]
    )

    assert result.exit_code == 0, result.output
    payload = _json_payload(result.output)
    assert not any(f["kind"] == FINDING_STALE for f in payload["findings"])


def test_cli_skips_staleness_when_packages_yml_not_yet_pinned_to_a_sha(project):
    """A fresh scaffold's packages.yml still pins a placeholder tag, not a commit SHA."""
    _declared_catalog(project, tables=("customers",))
    _binding_file(project, "models/_sources.yml", tables=("customers",))
    _write_packages_yml(project, None)  # revision: "v1.0.0", not a SHA

    result = CliRunner().invoke(
        cli, ["validate-source-bindings", "--project-dir", str(project)]
    )

    assert result.exit_code == 0, result.output
    payload = _json_payload(result.output)
    assert not any(f["kind"] == FINDING_STALE for f in payload["findings"])


def test_cli_confirm_stamps_bindings_and_passes(project):
    _declared_catalog(project, tables=("customers",))
    binding_path = _binding_file(project, "models/_sources.yml", tables=("customers",))

    result = CliRunner().invoke(
        cli,
        [
            "validate-source-bindings",
            "--project-dir",
            str(project),
            "--hub-sha",
            SHA_A,
            "--confirm",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "stamped" in result.output
    assert "crm" in result.output
    parsed = yaml.safe_load(binding_path.read_text(encoding="utf-8"))
    assert parsed["sources"][0]["meta"]["kairos"]["verified_hub_sha"] == SHA_A
    payload = _json_payload(result.output)
    assert payload["passed"] is True


def test_cli_confirm_refuses_when_other_findings_present(project):
    _declared_catalog(project, tables=("customers", "orders"))
    _binding_file(project, "models/_sources.yml", tables=("customers",))  # "orders" missing

    result = CliRunner().invoke(
        cli,
        [
            "validate-source-bindings",
            "--project-dir",
            str(project),
            "--hub-sha",
            SHA_A,
            "--confirm",
        ],
    )

    assert result.exit_code != 0
    assert "resolve missing" in result.output.lower() or "missing" in result.output.lower()


def test_cli_confirm_requires_a_resolvable_hub_sha(project):
    _declared_catalog(project, tables=("customers",))
    _binding_file(project, "models/_sources.yml", tables=("customers",))

    result = CliRunner().invoke(
        cli,
        ["validate-source-bindings", "--project-dir", str(project), "--confirm"],
    )

    assert result.exit_code != 0
    assert "resolvable hub sha" in result.output.lower()
