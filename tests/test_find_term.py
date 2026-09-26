# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``find-term``: the closure lookup by name, for a person or an agent (DD-248)."""

import json

from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.find_term import find_term

from tests.test_mcp_and_hook import closure_hub  # noqa: F401 - fixture


def test_find_term_reads_the_closure_by_name(closure_hub):  # noqa: F811
    result = find_term(closure_hub, name="EMAIL_ADDRESS", domains=["customer"])

    assert result["normalised"] == "email address"
    [entry] = result["domains"]
    assert entry["domain"] == "customer" and entry["import_complete"] is True
    [hit] = entry["candidates"]
    assert hit == {
        "uri": "urn:base#email", "name": "email", "class_uris": ["urn:base#Party"],
        "match": "near", "score": hit["score"],
    }
    assert 0.0 < hit["score"] < 1.0
    assert find_term(closure_hub, name="name", domains=["customer"])["domains"][0][
        "candidates"
    ][0]["match"] == "exact"


def test_the_command_in_text_and_json(closure_hub, monkeypatch):  # noqa: F811
    monkeypatch.chdir(closure_hub)
    runner = CliRunner()

    text = runner.invoke(cli, ["find-term", "emailAddress", "--domain", "customer"])
    assert text.exit_code == 0, text.output
    assert "urn:base#email" in text.output and "[Party]" in text.output

    as_json = runner.invoke(
        cli, ["find-term", "emailAddress", "--all-domains", "--format", "json", "--limit", "1"]
    )
    assert as_json.exit_code == 0, as_json.output
    payload = json.loads(as_json.output)
    assert [d["domain"] for d in payload["domains"]] == ["customer"]
    assert payload["domains"][0]["candidates"][0]["uri"] == "urn:base#email"

    nothing = runner.invoke(cli, ["find-term", "vesselFlag", "--domain", "customer"])
    assert "no closure property resembles this name" in nothing.output


def test_the_command_needs_a_scope_and_a_real_domain(closure_hub, monkeypatch):  # noqa: F811
    monkeypatch.chdir(closure_hub)
    runner = CliRunner()

    assert runner.invoke(cli, ["find-term", "email"]).exit_code == 2
    missing = runner.invoke(cli, ["find-term", "email", "--domain", "nope"])
    assert missing.exit_code == 1 and "Domain ontology not found" in missing.output
