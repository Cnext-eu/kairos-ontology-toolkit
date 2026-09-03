# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""One typed reader for kairos.yaml, with the failure policy left to the caller (DD-215)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kairos_ontology.core.hub_config import (
    HubConfigError,
    configured_adapter,
    load_hub_config,
)


def _hub(tmp_path: Path, body: str | None) -> Path:
    if body is not None:
        (tmp_path / "kairos.yaml").write_text(body, encoding="utf-8")
    return tmp_path


def test_reads_a_well_formed_mapping(tmp_path):
    hub = _hub(tmp_path, "version: 5\nadapter: databricks\n")
    assert load_hub_config(hub) == {"version": 5, "adapter": "databricks"}


@pytest.mark.parametrize(
    "body",
    [
        None,  # absent
        "",  # empty
        "just a string",  # not a mapping
        "adapter: [unclosed\n",  # malformed YAML
    ],
    ids=["absent", "empty", "not-a-mapping", "malformed"],
)
def test_lenient_mode_treats_every_failure_as_not_configured(tmp_path, body):
    """Callers reading an optional setting cannot tell absence from garbage apart."""
    assert load_hub_config(_hub(tmp_path, body)) == {}


@pytest.mark.parametrize(
    "body",
    [None, "", "just a string", "adapter: [unclosed\n"],
    ids=["absent", "empty", "not-a-mapping", "malformed"],
)
def test_strict_mode_refuses_to_guess(tmp_path, body):
    """The compile path must not produce artifacts from an unreadable config."""
    with pytest.raises(HubConfigError):
        load_hub_config(_hub(tmp_path, body), strict=True)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("adapter: fabric-warehouse\n", "fabric-warehouse"),
        ("adapter: databricks\n", "databricks"),
        ("adapter: fabric\n", "fabric-warehouse"),  # deprecated spelling resolves
        ("adapter: fabric-lakehouse\n", None),  # recognised but unsupported
        ("adapter: nonsense\n", None),
        ("adapter: '   '\n", None),
        ("adapter: 5\n", None),  # not a string
        ("version: 5\n", None),  # absent
        (None, None),
    ],
)
def test_configured_adapter_resolves_or_reports_nothing(tmp_path, body, expected):
    assert configured_adapter(_hub(tmp_path, body)) == expected
