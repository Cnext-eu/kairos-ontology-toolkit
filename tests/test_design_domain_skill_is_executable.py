# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The kairos-design-domain skill's own commands must actually work (#322).

The root cause of #322 was a skill that read correctly and could not be executed:
`core/catalog_test.py` states that only ``init --domain`` registers a domain, and
the skill never mentioned it, while its guard-scope step allowed a single path and
its anti-pattern list forbade writing anything else. Following the document made
registering a domain impossible.

A test asserting ``"init --domain" in SKILL.md`` would pass the moment the string
is typed and prove nothing about whether following the document works — which is
the same class of defect. So these tests **extract the command lines from the
skill file itself** and execute them. A future re-word that breaks the instruction
fails the build.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from kairos_ontology.cli.main import cli

_SKILL = (
    Path(__file__).resolve().parents[1] / ".github" / "skills" / "kairos-design-domain" / "SKILL.md"
)

_DOMAIN = "order"
_COMPANY = "example.test"


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _extract_command(pattern: str) -> str:
    """Return the single skill command line matching *pattern*, placeholders intact."""
    matches = [
        line.strip()
        for line in _skill_text().splitlines()
        if re.search(pattern, line) and "kairos-ontology" in line
    ]
    assert matches, f"no command line in SKILL.md matching {pattern!r}"
    return matches[0]


def _argv(command_line: str, substitutions: dict[str, str]) -> list[str]:
    """Turn a skill command line into argv, substituting ``<placeholder>`` tokens.

    Placeholder names may contain hyphens (``<company-domain>``), so they are passed
    as a mapping rather than as keyword arguments.
    """
    for name, value in substitutions.items():
        command_line = command_line.replace(f"<{name}>", value)
    argv = shlex.split(command_line)
    # Drop the ``uv run kairos-ontology`` prefix; CliRunner invokes the group directly.
    while argv and argv[0] in {"uv", "run", "kairos-ontology"}:
        argv.pop(0)
    assert "<" not in " ".join(argv), f"unsubstituted placeholder in {argv}"
    return argv


def _write_domain_ttl(hub: Path, domain: str) -> None:
    """A minimal domain ontology, the artifact step 9 registers."""
    (hub / "model" / "ontologies" / f"{domain}.ttl").write_text(
        f"""@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <https://{_COMPANY}/ont/{domain}#> .

<https://{_COMPANY}/ont/{domain}> a owl:Ontology ;
    rdfs:label "Order"@en ;
    rdfs:comment "Minimal domain for the skill-executability test."@en ;
    owl:versionInfo "0.1.0" .

:Order a owl:Class ;
    rdfs:label "Order"@en ;
    rdfs:comment "A commercial order."@en .
""",
        encoding="utf-8",
    )


def test_the_skills_registration_command_registers_the_domain(tmp_path):
    """The `init --domain` line the skill publishes must map the domain in the catalog.

    Extracted from SKILL.md rather than retyped: this is what couples the prose to
    executed behaviour.
    """
    command_line = _extract_command(r"init --domain")
    runner = CliRunner()

    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            bootstrap = runner.invoke(
                cli,
                ["init", "--company-domain", _COMPANY, "--skip-refmodels"],
            )
            assert bootstrap.exit_code == 0, bootstrap.output

            hub = Path("ontology-hub")
            _write_domain_ttl(hub, _DOMAIN)

            # Step 9, exactly as the skill publishes it.
            argv = _argv(
                command_line,
                {"domain": _DOMAIN, "company-domain": _COMPANY},
            )
            argv += ["--skip-refmodels"]
            result = runner.invoke(cli, argv)
            assert result.exit_code == 0, result.output

            catalog = (hub / "catalog-v001.xml").read_text(encoding="utf-8")
            assert f"model/ontologies/{_DOMAIN}.ttl" in catalog, catalog
            assert f"https://{_COMPANY}/ont/{_DOMAIN}" in catalog, catalog


def test_the_skills_pre_registration_validate_all_command_runs_clean(tmp_path):
    """The step-9 `validate --all --domain <domain>` line must execute and pass.

    Regex is `validate --all`, NOT bare `validate` — the extractor takes the first
    match and a bare pattern would pick Gate 5's `validate --syntax` line. On this
    no-refmodels fixture hub the run must exit 0: DD-155's resolvability
    short-circuit skips the Managed Import Completeness section entirely when no
    reference models are present.
    """
    command_line = _extract_command(r"validate --all")
    runner = CliRunner()

    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            bootstrap = runner.invoke(
                cli,
                ["init", "--company-domain", _COMPANY, "--skip-refmodels"],
            )
            assert bootstrap.exit_code == 0, bootstrap.output

            hub = Path("ontology-hub")
            _write_domain_ttl(hub, _DOMAIN)
            # `validate` hard-gates on discovery evidence (DD-148); a minimal
            # authored (non-template) glossary satisfies "discovery ran".
            (hub / "businessdiscovery" / "glossary.ttl").write_text(
                """@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
<https://example.test/glossary#order> a skos:Concept ;
    skos:prefLabel "Order"@en .
""",
                encoding="utf-8",
            )
            register = runner.invoke(
                cli,
                [
                    "init",
                    "--domain",
                    _DOMAIN,
                    "--company-domain",
                    _COMPANY,
                    "--skip-refmodels",
                ],
            )
            assert register.exit_code == 0, register.output

            # Step 9's pre-registration full run, exactly as the skill publishes it.
            argv = _argv(command_line, {"domain": _DOMAIN})
            result = runner.invoke(cli, argv)
            assert result.exit_code == 0, result.output


def test_the_skills_guard_scope_allow_globs_match_the_paths_it_permits(tmp_path):
    """The published `--allow` globs must match the repo-root-relative paths git reports.

    #329: the globs were hub-relative while `guard-scope` reports repo-root-relative
    paths, so the guard flagged the file the skill had just authored — and the skill
    then instructs restoring the pre-patch content. Extracting the globs from the
    file is what stops that recurring.
    """
    import fnmatch

    command_line = _extract_command(r"guard-scope --check-since")
    globs = re.findall(r'--allow\s+"([^"]+)"', command_line)
    assert globs, f"no --allow globs found in: {command_line}"

    resolved = [glob.replace("<domain>", _DOMAIN) for glob in globs]

    # The paths git actually reports for a domain authored in a hub subdirectory.
    reported = [
        f"ontology-hub/model/ontologies/{_DOMAIN}.ttl",
        "ontology-hub/catalog-v001.xml",
        "ontology-hub/model/ontologies/_master.ttl",
    ]

    for path in reported:
        assert any(fnmatch.fnmatch(path, glob) for glob in resolved), (
            f"no published --allow glob matches {path!r}; globs are {resolved}. "
            "A hub-relative glob does not match repo-root-relative porcelain output "
            "(#329) — use a leading '*'."
        )


def test_both_skill_copies_publish_the_same_commands():
    """The scaffold copy ships to hubs; drift would mean users read different advice."""
    scaffold = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "kairos_ontology"
        / "scaffold"
        / "skills"
        / "kairos-design-domain"
        / "SKILL.md"
    )
    assert scaffold.read_text(encoding="utf-8") == _skill_text()
