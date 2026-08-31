# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Registration tests for the decomposed v5 CLI."""

import re

from click.testing import CliRunner

from kairos_ontology.cli.main import cli

RETAINED_COMMANDS = {
    "analyse-sources",
    "profile-sources",
    "generate-bindings",
    "anchor-tables",
    "draft-gap-decisions",
    "audit-silver-samples",
    "audit-column-coverage",
    "build-glossary",
    "bump-hub",
    "catalog-test",
    "check-ai-config",
    "compile",
    "coverage-report",
    "decision",
    "design-landscape",
    "discovery-conformance",
    "discovery-status",
    "emit-gold",
    "apply-gold-connection",
    "register-concept",
    "source-disposition",
    "domain-coverage",
    "draft-model-report",
    "explain-term",
    "extract-schema",
    "feedback",
    "field-mapping-report",
    "fit-report",
    "guard-scope",
    "import-flatfile",
    "import-source",
    "import-tmdl",
    "init",
    "init-dataplatform",
    "inverse-scan",
    "list-class-properties",
    "list-patterns",
    "mdm-validate",
    "migrate",
    "new-repo",
    "next",
    "package-powerbi-release",
    "plan-sources",
    "project",
    "propose-alignment",
    "propose-relationships",
    "resolve-ontology",
    "promote-transform",
    "scaffold-binding",
    "scaffold-staging",
    "scaffold-system",
    "scaffold-mapping",
    "scaffold-silver-ext",
    "scaffold-domain",
    "show-class-inventory",
    "show-source-schema",
    "source-privacy",
    "suggest-shapes",
    "alignment-report",
    "suggest-anchor",
    "suggest-type",
    "update",
    "update-refmodels",
    "validate",
    "validate-dbt",
    "validate-dbt-contracts",
    "validate-mapping",
    "validate-silver-ext",
    "validate-source-bindings",
}

RETIRED_STAGE4_COMMANDS = {
    "status",
    "lifecycle",
    "check-projection",
    "check-release",
    "check-claims",
    "derive-claims",
    "decide-claims",
    "migrate-claims",
    "claims-to-silver-ext",
    "capture-dbt-contract-evidence",
    "check-transformation-readiness",
    "inventory-dbt-candidates",
    "migrate-column-iris",
    "reconstruct-dbt-transformation",
    "sync-dbt-contracts",
}


def test_root_registers_exact_retained_v5_surface():
    assert set(cli.commands) == RETAINED_COMMANDS
    assert set(cli.commands).isdisjoint(RETIRED_STAGE4_COMMANDS)
    assert all(
        command.callback.__module__ != "kairos_ontology.cli.main"
        for command in cli.commands.values()
    )


def test_root_help_lists_retained_commands_only():
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "Commands:" in result.output
    for command in RETAINED_COMMANDS:
        assert re.search(rf"^  {re.escape(command)}\s", result.output, re.MULTILINE)
    for command in RETIRED_STAGE4_COMMANDS:
        assert not re.search(rf"^  {re.escape(command)}\s", result.output, re.MULTILINE)
