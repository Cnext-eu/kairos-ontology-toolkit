# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""What documentation a scaffolded repo receives, and whether it can ever be fixed.

Three properties, none of which had a test before:

* maintainer-only skills stay out of client repos;
* per-directory guidance is *managed*, so a wrong instruction can be corrected in hubs
  that already exist rather than only in ones created after the fix;
* the two runtime-owned ``index.md`` files stay *unmanaged*, because managing either
  would have ``update`` overwrite a hub's own decision or feedback log.
"""

from __future__ import annotations

import re

import pytest

from kairos_ontology.cli.shared import (
    _SCAFFOLD_DIR,
    _managed_dataplatform_map,
    _managed_scaffold_map,
)

#: Tokens `cli/setup.py` substitutes when it renders a scaffold template. A *managed*
#: file is copied verbatim by `_copy_managed`, so any of these surviving in one reaches
#: the client as literal text -- which is how `{ORG}` shipped inside the dataplatform's
#: CICD.md.
_SUBSTITUTION_TOKENS = frozenset(
    {
        "{company_name}",
        "{company_domain}",
        "{repo_name}",
        "{description}",
        "{adapter}",
        "{domain}",
        "{label}",
        "{toolkit_ref}",
        "{toolkit_version}",
        "{toolkit_channel}",
        "{refmodels_ref}",
        "{refmodels_version}",
        "{PROJECT_NAME}",
        "{ORG}",
        "{HUB_REPO}",
        "{HUB_VERSION}",
        "{DATABASE}",
        "{SCHEMA}",
        "{DBT_ADAPTER}",
        "{DBT_CI_PROFILE_YAML}",
    }
)

#: Regenerated from the hub's own records by `kairos-ontology decision` / `... feedback`.
#: The scaffold ships a seed; the hub owns it from then on.
_RUNTIME_OWNED = (
    "ontology-hub/decisions/index.md",
    "import/modeling/feedback/index.md",
)

_MAINTAINER_ONLY_SKILLS = ("kairos-toolkit-dev", "kairos-toolkit-dogfood")

#: Cnext-internal or not-yet-live, so equally not client-facing, but for different
#: reasons than the two above -- kept separate so the reason survives in the test name.
_NOT_CLIENT_FACING_SKILLS = ("SC-merge-pr", "SC-document", "kairos-design-mdm")


def _managed_docs() -> dict[str, object]:
    combined = {**_managed_scaffold_map(), **_managed_dataplatform_map()}
    return {dest: src for dest, src in combined.items() if "/skills/" not in dest}


class TestMaintainerSkills:
    @pytest.mark.parametrize("name", _MAINTAINER_ONLY_SKILLS)
    def test_are_not_shipped_to_client_repos(self, name):
        """Aimed at *this* repository, and dogfood is explicitly adversarial.

        Shipping them put 314 lines of irrelevant instruction in every client hub and,
        worse, left them selectable by an agent working there.
        """
        assert not (_SCAFFOLD_DIR / "skills" / name).exists()

    @pytest.mark.parametrize("name", _MAINTAINER_ONLY_SKILLS)
    def test_are_excluded_from_the_sync(self, name):
        """Absence must be enforced, not merely current -- `sync_dev_skills` would
        otherwise copy them straight back on the next run."""
        from scripts.sync_dev_skills import _UNMANAGED_SKILL_DIRS

        assert name in _UNMANAGED_SKILL_DIRS

    @pytest.mark.parametrize("name", _NOT_CLIENT_FACING_SKILLS)
    def test_non_client_skills_are_not_shipped(self, name):
        """`SC-*` are Cnext-internal; `kairos-design-mdm` authors policy nothing runs.

        MDM is designed but not adopted (docs/mdm/README.md), so shipping its authoring
        skill invited an agent to write policy no hub consumes. Restore it when MDM goes
        live -- the CLI surface stayed.
        """
        from scripts.sync_dev_skills import _UNMANAGED_SKILL_DIRS

        assert not (_SCAFFOLD_DIR / "skills" / name).exists()
        assert name in _UNMANAGED_SKILL_DIRS

    def test_toolkit_ops_is_still_shipped(self):
        """The counter-case: clients do use it to upgrade their toolkit pin."""
        assert (_SCAFFOLD_DIR / "skills" / "kairos-toolkit-ops" / "SKILL.md").is_file()


class TestManagedDocumentation:
    def test_per_directory_guidance_is_managed(self):
        """Otherwise a wrong instruction can only be fixed in hubs created after the fix.

        These were write-once: written at `init` and frozen, which left half the
        scaffold's documentation lines permanently unreachable in existing hubs.
        """
        managed = set(_managed_scaffold_map())
        expected = {
            "ontology-hub/.input/README.md",
            "ontology-hub/businessdiscovery/README.md",
            "ontology-hub/businessdiscovery/_extractions/README.md",
            "ontology-hub/integration/bindings/README.md",
            "ontology-hub/integration/discovery/bi/README.md",
            "ontology-hub/integration/sources/README.md",
            "ontology-hub/integration/sources/source-system-template/README.md",
            "ontology-hub/integration/transforms/dbt/README.md",
            "ontology-hub/model/ontologies/README.md",
            "ontology-hub/model/shapes/README.md",
            ".import/businessdiscovery/README.md",
        }
        assert expected <= managed, sorted(expected - managed)

    @pytest.mark.parametrize("rel_path", _RUNTIME_OWNED)
    def test_runtime_owned_indexes_are_never_managed(self, rel_path):
        """`update` force-replaces managed files.

        `decisions/index.md` is regenerated from the hub's own decision records, so
        managing it would replace an accumulated log with the scaffold's empty table.
        """
        destinations = set(_managed_scaffold_map()) | set(_managed_dataplatform_map())
        assert rel_path not in destinations
        assert rel_path.replace("import/", ".import/", 1) not in destinations

    def test_no_managed_doc_carries_an_unsubstituted_token(self):
        """Managed files are copied verbatim, so a substitution token reaches the client.

        `{ORG}` shipped this way inside the dataplatform's CICD.md, telling readers to
        pin `https://github.com/{ORG}/kairos-ontology-toolkit`.
        """
        offenders = []
        for destination, source in _managed_docs().items():
            text = source.read_text(encoding="utf-8")
            for token in sorted(_SUBSTITUTION_TOKENS):
                if token in text:
                    offenders.append(f"{destination}: {token}")
        assert not offenders, "unsubstituted tokens in verbatim-copied files:\n" + "\n".join(
            offenders
        )

    def test_managed_docs_are_markdown_the_marker_can_live_in(self):
        """The managed marker is an HTML comment; it is only invisible in Markdown."""
        for destination in _managed_docs():
            assert re.search(r"\.md(\.template)?$", destination), destination


class TestFreshHubIsSelfConsistent:
    """A hub `init` just created must satisfy `update --check` immediately.

    `managed-check.yml` runs `update --check` on every pull request, so anything the
    scaffold writes in a state the checker rejects turns a brand-new hub red on its
    first PR. Promoting the per-directory READMEs to managed did exactly that until
    `init` learned to stamp them: the bulk `ontology-hub/` copy writes them unstamped,
    and the checker reported ten files as "unmanaged" plus one missing.
    """

    def test_init_then_update_check_is_clean(self, tmp_path):
        from unittest import mock

        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli

        runner = CliRunner()
        with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)
            with runner.isolated_filesystem(temp_dir=tmp_path):
                created = runner.invoke(cli, ["init", "--company-domain", "acme.example"])
                assert created.exit_code == 0, created.output

                checked = runner.invoke(cli, ["update", "--check"])

        assert checked.exit_code == 0, checked.output
        assert "unmanaged" not in checked.output, checked.output

    def test_init_does_not_clobber_an_operator_authored_managed_file(self, tmp_path):
        """The stamping pass must recognise content that is not the scaffold's.

        Without the identity check it rewrote any unstamped managed path, including a
        `CICD.md` the operator had written themselves -- `--force` is the only route in.
        """
        from unittest import mock

        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli

        runner = CliRunner()
        with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)
            with runner.isolated_filesystem(temp_dir=tmp_path):
                from pathlib import Path as _Path

                _Path("ontology-hub/model/ontologies").mkdir(parents=True)
                mine = _Path("ontology-hub/model/ontologies/README.md")
                mine.write_text("# Our own notes\n", encoding="utf-8")

                result = runner.invoke(cli, ["init", "--company-domain", "acme.example"])
                assert result.exit_code == 0, result.output
                assert mine.read_text(encoding="utf-8") == "# Our own notes\n"
