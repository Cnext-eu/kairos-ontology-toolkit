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
def test_source_skill_requires_provider_choice_at_every_start(path):
    text = path.read_text(encoding="utf-8")

    assert "Phase 0a — Select AI provider and authentication (mandatory)" in text
    assert "every source-design invocation" in text
    assert "**Use detected `.env` settings (Recommended)**" in text
    assert "first and default choice" in text
    assert "**GitHub Models**" in text
    assert "**Azure AI with API key**" in text
    assert "**Azure AI with Azure identity**" in text
    assert "**Microsoft Foundry with Azure identity**" in text
    assert "**Skip AI analysis for this invocation**" in text
    assert "never silently fall back" in text


@pytest.mark.parametrize(
    "path",
    [
        REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / ".env.example",
        REPO_ROOT
        / "src"
        / "kairos_ontology"
        / "scaffold"
        / "ontology-hub"
        / ".env.example",
    ],
    ids=["repository", "hub"],
)
def test_env_examples_document_azure_identity(path):
    text = path.read_text(encoding="utf-8")

    assert "DefaultAzureCredential" in text
    assert "workload identity" in text
    assert "managed identity" in text
