# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Optional TOM SDK TMDL validation (issue #619 feature request).

Real end-to-end coverage against the actual Microsoft.AnalysisServices TOM SDK when
``dotnet`` is available (skipped otherwise, matching this suite's existing pattern for
optional external tools -- see test_cr3_macros.py's dbt_project fixture).
"""

from __future__ import annotations

import shutil

import pytest

from kairos_ontology.core.projections.dbt.gold_specs import GoldContractError
from kairos_ontology.core.projections.dbt.tmdl_validate import validate_tmdl_artifacts

_HAS_DOTNET = shutil.which("dotnet") is not None

_VALID_DEFINITION = {
    "party/Party.SemanticModel/definition/database.tmdl": (
        "database\n\tcompatibilityLevel: 1702\n\tcompatibilityMode: powerBI\n\tlanguage: 1033\n"
    ),
    "party/Party.SemanticModel/definition/model.tmdl": (
        "model Model\n\tculture: en-US\n\tref table customer\n\n"
    ),
    "party/Party.SemanticModel/definition/tables/customer.tmdl": (
        "table customer\n\tlineageTag: 00000000-0000-0000-0000-000000000001\n\n"
        "\tcolumn customer_id\n\t\tdataType: string\n"
        "\t\tlineageTag: 00000000-0000-0000-0000-000000000002\n"
        "\t\tsourceColumn: customer_id\n\t\tsummarizeBy: none\n\n"
        "\tpartition customer = m\n\t\tmode: import\n\t\tsource =\n"
        "\t\t\tlet\n\t\t\t\tSource = \"placeholder\"\n\t\t\tin\n\t\t\t\tSource\n"
    ),
}

_INVALID_DEFINITION = {
    **_VALID_DEFINITION,
    "party/Party.SemanticModel/definition/model.tmdl": (
        "model Model\n\tculture: en-US\nthis is not valid tmdl syntax {{{\n"
    ),
}


def test_no_tmdl_files_returns_no_results():
    assert validate_tmdl_artifacts({"party/some-file.sql": "select 1"}) == ()


def test_unavailable_when_dotnet_missing(monkeypatch):
    monkeypatch.setattr("kairos_ontology.core.projections.dbt.tmdl_validate.shutil.which", lambda _: None)

    results = validate_tmdl_artifacts(_VALID_DEFINITION)

    assert len(results) == 1
    assert results[0].status == "unavailable"
    assert "dotnet SDK not found" in results[0].message


def test_required_raises_when_dotnet_missing(monkeypatch):
    monkeypatch.setattr("kairos_ontology.core.projections.dbt.tmdl_validate.shutil.which", lambda _: None)

    with pytest.raises(GoldContractError, match="tmdl-validation-failed"):
        validate_tmdl_artifacts(_VALID_DEFINITION, required=True)


def _skip_if_sdk_unavailable(result) -> None:
    # "unavailable" here (dotnet present, but the SDK itself failed to initialize --
    # e.g. a native-hosting TypeInitializationException under a platform/environment
    # this SDK build doesn't fully support) is an environment limitation, not a real
    # test failure; skip rather than fail the build on it.
    if result.status == "unavailable":
        pytest.skip(f"TOM SDK unavailable in this environment: {result.message}")


@pytest.mark.skipif(not _HAS_DOTNET, reason="dotnet SDK not installed; TOM SDK validation is best-effort")
def test_valid_tmdl_passes_real_tom_sdk_validation():
    results = validate_tmdl_artifacts(_VALID_DEFINITION)

    assert len(results) == 1
    _skip_if_sdk_unavailable(results[0])
    assert results[0].status == "pass"
    assert results[0].message == ""


@pytest.mark.skipif(not _HAS_DOTNET, reason="dotnet SDK not installed; TOM SDK validation is best-effort")
def test_malformed_tmdl_fails_real_tom_sdk_validation_with_detail():
    results = validate_tmdl_artifacts(_INVALID_DEFINITION)

    assert len(results) == 1
    _skip_if_sdk_unavailable(results[0])
    assert results[0].status == "fail"
    assert "TmdlFormatException" in results[0].message
    assert "Line Number - 3" in results[0].message


@pytest.mark.skipif(not _HAS_DOTNET, reason="dotnet SDK not installed; TOM SDK validation is best-effort")
def test_required_raises_on_malformed_tmdl():
    with pytest.raises(GoldContractError, match="tmdl-validation-failed"):
        validate_tmdl_artifacts(_INVALID_DEFINITION, required=True)
