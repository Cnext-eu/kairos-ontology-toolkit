# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Contract tests for source-design AI provider selection guidance."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "path",
    [
        REPO_ROOT / ".claude" / "skills" / "kairos-design-source" / "SKILL.md",
        REPO_ROOT
        / "src"
        / "kairos_ontology"
        / "scaffold"
        / "skills"
        / "kairos-design-source"
        / "SKILL.md",
    ],
    ids=["claude", "scaffold"],
)
def test_source_skill_defers_provider_choice_until_analysis(path):
    text = " ".join(path.read_text(encoding="utf-8").split()).lower()

    assert "when semantic source analysis is requested" in text
    assert "immediately before the call" in text
    assert "invocation-scoped consent" in text
    assert "`analyse-sources`" in text
    assert "never secret values" in text
    assert "preserve deterministic imports when ai analysis is skipped" in text
    # A5: DD-159 preflight before LLM call.
    assert "check-ai-config --role alignment" in text
    assert "never auto-degrade" in text


@pytest.mark.parametrize(
    "path",
    [
        REPO_ROOT / ".claude" / "skills" / "kairos-design-source" / "SKILL.md",
        REPO_ROOT
        / "src"
        / "kairos_ontology"
        / "scaffold"
        / "skills"
        / "kairos-design-source"
        / "SKILL.md",
    ],
    ids=["claude", "scaffold"],
)
def test_documented_check_ai_config_role_is_one_the_cli_accepts(path):
    """Pin the skill's `--role` against the live Click choices, not a literal (#689).

    #562 folded the `affinity` role into `alignment` (DD-203) and updated the command
    but not the skill, so the documented DD-159 preflight exited 2 with a usage error.
    The natural reaction to that is to skip the preflight and run `analyse-sources`
    anyway -- the exact silent degradation DD-159 exists to prevent. The previous
    assertion here spelled the stale role out, so it *enforced* the bug instead of
    catching it; reading the accepted values off the command means the next rename
    fails here rather than in a client hub.
    """
    import re

    from click import Choice

    from kairos_ontology.cli.inspection import check_ai_config_cmd

    accepted = set()
    for param in check_ai_config_cmd.params:
        if "--role" in getattr(param, "opts", []) and isinstance(param.type, Choice):
            accepted.update(param.type.choices)
    assert accepted, "check-ai-config no longer declares a --role choice"

    documented = set(
        re.findall(r"check-ai-config --role ([a-z-]+)", path.read_text(encoding="utf-8"))
    )
    assert documented, "the skill no longer documents the DD-159 preflight"
    assert documented <= accepted, (
        f"skill documents --role {sorted(documented - accepted)}, "
        f"but the CLI accepts only {sorted(accepted)}"
    )


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
