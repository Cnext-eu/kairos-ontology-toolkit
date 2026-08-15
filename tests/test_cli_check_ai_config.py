# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for check-ai-config CLI command (DD-159)."""

import json

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.inspection import check_ai_config_cmd


class TestCheckAIConfigNoConfig:
    """With no provider configured, check-ai-config exits 1."""

    def test_text_output_not_configured(self):
        runner = CliRunner()
        result = runner.invoke(check_ai_config_cmd, ["--no-probe"])
        assert result.exit_code == 1
        assert "not_configured" in result.output
        assert "affinity" in result.output
        assert "alignment" in result.output

    def test_json_output_not_configured(self):
        runner = CliRunner()
        result = runner.invoke(check_ai_config_cmd, ["--no-probe", "--format", "json"])
        assert result.exit_code == 1
        # stdout must be valid JSON
        data = json.loads(result.output)
        assert data["schema_version"] == 1
        assert "api_key" not in data
        for role in data["roles"]:
            assert role["status"] == "not_configured"
            assert "api_key" not in role

    def test_warn_only_exits_zero(self):
        runner = CliRunner()
        result = runner.invoke(check_ai_config_cmd, ["--no-probe", "--warn-only"])
        assert result.exit_code == 0

    def test_single_role_affinity(self):
        runner = CliRunner()
        result = runner.invoke(check_ai_config_cmd, ["--no-probe", "--role", "affinity"])
        assert result.exit_code == 1
        assert "affinity" in result.output
        assert "alignment" not in result.output.split("\n")[1]


class TestCheckAIConfigWithProvider:
    """With a configured provider (no probe), check-ai-config exits 0."""

    def test_unprobed_exits_zero(self, github_provider_env):
        runner = CliRunner()
        result = runner.invoke(check_ai_config_cmd, ["--no-probe"])
        assert result.exit_code == 0
        assert "unprobed" in result.output

    def test_json_no_secret(self, github_provider_env, monkeypatch):
        """A ghp_-shaped token set in env must not appear in output."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_SECRET123456")
        runner = CliRunner()
        result = runner.invoke(
            check_ai_config_cmd, ["--no-probe", "--format", "json"]
        )
        assert result.exit_code == 0
        assert "ghp_SECRET" not in result.output
        data = json.loads(result.output)
        assert "api_key" not in data
        for role in data["roles"]:
            assert "api_key" not in role

    def test_json_only_output(self, github_provider_env):
        """JSON mode must produce only JSON on stdout (no extra text lines)."""
        runner = CliRunner()
        result = runner.invoke(
            check_ai_config_cmd, ["--no-probe", "--format", "json"]
        )
        # The entire stdout must parse as JSON
        data = json.loads(result.output)
        assert data["schema_version"] == 1


class TestCheckAIConfigStrict:
    """--strict makes unprobed exit non-zero."""

    def test_strict_unprobed_exits_one(self, github_provider_env):
        runner = CliRunner()
        result = runner.invoke(check_ai_config_cmd, ["--no-probe", "--strict"])
        assert result.exit_code == 1
