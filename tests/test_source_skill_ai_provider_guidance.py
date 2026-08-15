# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Contract tests for source-design AI provider selection guidance."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "path",
    [
        REPO_ROOT / ".github" / "skills" / "kairos-design-source" / "SKILL.md",
        REPO_ROOT
        / "src"
        / "kairos_ontology"
        / "scaffold"
        / "skills"
        / "kairos-design-source"
        / "SKILL.md",
    ],
    ids=["github", "scaffold"],
)
def test_source_skill_defers_provider_choice_until_analysis(path):
    text = " ".join(path.read_text(encoding="utf-8").split()).lower()

    assert "when semantic source analysis is requested" in text
    assert "immediately before the call" in text
    assert "invocation-scoped consent" in text
    assert "`analyse-sources`" in text
    assert "never secret values" in text
    assert "preserve deterministic imports when ai analysis is skipped" in text
    # A5: DD-159 preflight before LLM call
    assert "check-ai-config --role affinity" in text
    assert "never auto-degrade" in text


@pytest.mark.parametrize(
    "path",
    [
        REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / ".env.example",
        REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "ontology-hub" / ".env.example",
    ],
    ids=["repository", "hub"],
)
def test_env_examples_document_azure_identity(path):
    text = path.read_text(encoding="utf-8")

    assert "DefaultAzureCredential" in text
    assert "workload identity" in text
    assert "managed identity" in text
