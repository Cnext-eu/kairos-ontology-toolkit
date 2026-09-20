# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The gate registry, its enforcement modes, and the escape ledger (DD-234).

The test that earns its keep is :class:`TestNoUnclassifiedEscape`. Everything else here
checks behaviour that is visible when it breaks; that one checks a property that is
invisible when it breaks -- a new ``--skip-something`` flag landing on a command with
nobody having decided whether an unattended run may pass it. The registry is only worth
having if it cannot quietly go out of date, and an AST scan over the CLI is the only
thing that makes that true.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.core.gates import (
    GATES,
    MODE_ENV_VAR,
    UNGATED_FLAGS,
    EnforcementMode,
    active_mode,
    enforcement_provenance,
    escape_permitted,
    escapes_used,
    gate_by_id,
    gate_for_escape,
    record_escape,
    refusal_message,
    reset_enforcement_state,
    set_active_mode,
)

_CLI_DIR = Path(__file__).resolve().parent.parent / "src" / "kairos_ontology" / "cli"

#: Flag shapes that read as "get past a check". Deliberately generous: a false positive
#: costs one line in UNGATED_FLAGS with a reason, and a false negative costs an
#: unaccountable escape hatch, which is the whole defect.
_ESCAPE_SHAPED = re.compile(r"^--(no|skip|allow|without|force|degraded|unsafe|ignore|bypass)(-|$)")


@pytest.fixture(autouse=True)
def _clean_enforcement_state():
    """Mode and the escape ledger are process-global; no test may leak either."""
    reset_enforcement_state()
    yield
    reset_enforcement_state()


def _plain_click_option_flags() -> list[tuple[str, str]]:
    """Every ``click.option`` string argument in the CLI that looks like an escape.

    Reads the source rather than the built commands, because the thing under test is
    how a flag was *declared*: a gate escape declared with ``escape_option`` is bound to
    the registry and enforced, and an identical-looking ``click.option`` is not.
    """
    found: list[tuple[str, str]] = []
    for path in sorted(_CLI_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name != "option":
                continue
            for arg in node.args:
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and _ESCAPE_SHAPED.match(arg.value)
                ):
                    found.append((arg.value, path.name))
    return found


class TestNoUnclassifiedEscape:
    """An escape-shaped flag is registered, or listed as gating nothing, with a reason."""

    def test_every_escape_shaped_flag_is_classified(self):
        unclassified = [
            f"{flag} in cli/{module}"
            for flag, module in _plain_click_option_flags()
            if flag not in UNGATED_FLAGS
        ]
        assert not unclassified, (
            "escape-shaped flags declared with a plain click.option and classified "
            "nowhere. Either declare them with escape_option(<gate id>, ...) so the "
            "mode policy applies, or add them to UNGATED_FLAGS with the reason they "
            "cost a reviewer nothing:\n  " + "\n  ".join(unclassified)
        )

    def test_a_registered_escape_is_not_also_declared_as_a_plain_option(self):
        """Both spellings of one flag would mean it is enforced on some commands only."""
        registered = {gate.escape for gate in GATES if gate.escape}
        leaked = [
            f"{flag} in cli/{module}"
            for flag, module in _plain_click_option_flags()
            if flag in registered
        ]
        assert not leaked, (
            "these flags escape a registered gate on one command and are declared as "
            "a plain option on another, so the mode policy applies unevenly:\n  "
            + "\n  ".join(leaked)
        )

    def test_ungated_flags_each_carry_a_reason(self):
        """The list is a set of claims, and a claim with no argument is not reviewable."""
        thin = [flag for flag, reason in UNGATED_FLAGS.items() if len(reason.strip()) < 30]
        assert not thin, f"UNGATED_FLAGS entries with no real justification: {thin}"


class TestRegistryIsInternallyConsistent:
    def test_ids_are_unique(self):
        ids = [gate.id for gate in GATES]
        assert len(ids) == len(set(ids))

    def test_every_gate_has_a_summary_in_operator_terms(self):
        assert not [gate.id for gate in GATES if len(gate.summary) < 20]

    def test_an_escape_is_permitted_somewhere_or_is_not_an_escape(self):
        """A flag permitted in no mode is dead code pretending to be an option."""
        assert not [gate.id for gate in GATES if gate.escape and not gate.escape_modes]

    def test_an_escapable_gate_says_why_the_escape_exists(self):
        """Without the rationale the classification cannot be reviewed, only obeyed."""
        assert not [gate.id for gate in GATES if gate.escape and not gate.escape_rationale]

    def test_gate_lookup_by_id_and_by_escape_agree(self):
        for gate in GATES:
            assert gate_by_id(gate.id) is gate
            if gate.escape:
                assert gate_for_escape(gate.escape) is not None

    def test_the_gates_that_guard_silver_declare_the_evidence_they_read(self):
        """DD-234's whole point: these two are only as good as their inputs."""
        for gate_id in ("alignment.gap-column-undecided", "alignment.table-unanchored"):
            gate = gate_by_id(gate_id)
            assert gate is not None and gate.requires
            assert gate.on_missing_evidence == "fail"


class TestModeResolution:
    def test_the_default_is_interactive(self, monkeypatch):
        monkeypatch.delenv(MODE_ENV_VAR, raising=False)
        assert active_mode() is EnforcementMode.INTERACTIVE

    def test_the_environment_selects_a_mode(self, monkeypatch):
        monkeypatch.setenv(MODE_ENV_VAR, "ci")
        assert active_mode() is EnforcementMode.CI

    def test_an_explicit_mode_beats_the_environment(self, monkeypatch):
        monkeypatch.setenv(MODE_ENV_VAR, "ci")
        set_active_mode(EnforcementMode.AUTOPILOT)
        assert active_mode() is EnforcementMode.AUTOPILOT

    def test_a_typo_falls_back_to_interactive_rather_than_raising(self, monkeypatch):
        """Loose is the safe direction here.

        A typo resolving to the current default cannot silently tighten a pipeline into
        failing, and cannot take down a command that would otherwise have worked. The
        opposite choice trades a real outage for a theoretical one.
        """
        monkeypatch.setenv(MODE_ENV_VAR, "autopiolt")
        assert active_mode() is EnforcementMode.INTERACTIVE


class TestEscapePolicy:
    def test_a_grounding_escape_is_refused_to_an_unattended_run(self):
        for mode in (EnforcementMode.AUTOPILOT, EnforcementMode.CI):
            assert not escape_permitted("--without-discovery", mode)
            assert not escape_permitted("--without-anchors", mode)
            assert not escape_permitted("--allow-unresolved", mode)

    def test_a_human_may_still_use_every_escape(self):
        for gate in GATES:
            if gate.escape:
                assert escape_permitted(gate.escape, EnforcementMode.INTERACTIVE)

    def test_a_recovery_escape_survives_an_unattended_run(self):
        """Pinning back to a known-good version is legitimate wherever it happens."""
        assert escape_permitted("--allow-downgrade", EnforcementMode.AUTOPILOT)

    def test_an_operational_escape_is_allowed_in_ci_but_not_autopilot(self):
        """CI config is authored by a human once; an autopilot delivery is not."""
        assert escape_permitted("--skip-protection", EnforcementMode.CI)
        assert not escape_permitted("--skip-protection", EnforcementMode.AUTOPILOT)

    def test_a_flag_answering_for_two_gates_is_as_strict_as_the_stricter(self):
        """--degraded opens both the closure gate and the DD-233 evidence gate."""
        from kairos_ontology.core.gates import gates_for_escape

        assert len(gates_for_escape("--degraded")) == 2
        assert not escape_permitted("--degraded", EnforcementMode.CI)

    def test_an_unregistered_flag_is_not_this_modules_business(self):
        assert escape_permitted("--no-cache", EnforcementMode.CI)

    def test_the_refusal_names_the_gate_and_the_way_out(self):
        message = refusal_message("--without-discovery", EnforcementMode.AUTOPILOT)
        assert "discovery.glossary-required" in message
        assert "DD-171" in message
        assert "interactive" in message
        # A hard stop that does not say how to clear it is an obstacle, not a control.
        assert "Resolve the gate itself" in message


class TestEnforcementProvenance:
    def test_a_clean_interactive_run_records_nothing(self):
        """So an unaffected artifact stays byte-identical to the previous version's."""
        assert enforcement_provenance() == {}

    def test_an_escape_is_recorded_with_the_mode(self):
        record_escape("--without-discovery")
        assert enforcement_provenance() == {
            "mode": "interactive",
            "escapes_used": ["--without-discovery"],
        }

    def test_a_non_default_mode_alone_is_worth_recording(self):
        set_active_mode(EnforcementMode.CI)
        assert enforcement_provenance() == {"mode": "ci"}

    def test_the_ledger_does_not_double_count_a_repeated_flag(self):
        record_escape("--degraded")
        record_escape("--degraded")
        assert escapes_used() == ("--degraded",)

    def test_an_unregistered_flag_is_still_recorded(self):
        """What was passed is a more durable fact than how it is currently classified."""
        record_escape("--no-cache")
        assert "--no-cache" in escapes_used()


class TestEscapeOptionBinding:
    def test_an_unknown_gate_id_fails_at_declaration(self):
        """A typo would otherwise produce a flag that is silently unenforced."""
        from kairos_ontology.cli.gates import escape_option

        with pytest.raises(ValueError, match="no gate registered"):
            escape_option("alignment.no-such-gate", "--nope")

    def test_a_flag_that_disagrees_with_its_gate_fails_at_declaration(self):
        from kairos_ontology.cli.gates import escape_option

        with pytest.raises(ValueError, match="declares escape"):
            escape_option("discovery.glossary-required", "--something-else")

    def test_the_flag_is_refused_at_parse_time_in_a_strict_mode(self):
        """Before the command body runs, so no partial work precedes the refusal."""
        import click

        from kairos_ontology.cli.gates import escape_option

        @click.command()
        @escape_option("discovery.glossary-required", "--without-discovery")
        def cmd(without_discovery):  # pragma: no cover - must not be reached
            click.echo("body ran")

        set_active_mode(EnforcementMode.AUTOPILOT)
        result = CliRunner().invoke(cmd, ["--without-discovery"])

        assert result.exit_code != 0
        assert "body ran" not in result.output
        assert "refused in autopilot mode" in result.output

    def test_the_flag_passes_and_is_recorded_in_interactive_mode(self):
        import click

        from kairos_ontology.cli.gates import escape_option

        @click.command()
        @escape_option("discovery.glossary-required", "--without-discovery")
        def cmd(without_discovery):
            click.echo("body ran")

        set_active_mode(EnforcementMode.INTERACTIVE)
        result = CliRunner().invoke(cmd, ["--without-discovery"])

        assert result.exit_code == 0
        assert "body ran" in result.output
        assert escapes_used() == ("--without-discovery",)

    def test_not_passing_the_flag_records_nothing(self):
        import click

        from kairos_ontology.cli.gates import escape_option

        @click.command()
        @escape_option("discovery.glossary-required", "--without-discovery")
        def cmd(without_discovery):
            click.echo("body ran")

        assert CliRunner().invoke(cmd, []).exit_code == 0
        assert escapes_used() == ()


class TestGatesCommand:
    def test_it_lists_every_registered_gate(self):
        from kairos_ontology.cli.gates import gates_cmd

        result = CliRunner().invoke(gates_cmd, [])

        assert result.exit_code == 0
        for gate in GATES:
            assert gate.id in result.output

    def test_it_says_which_escapes_this_mode_refuses(self):
        from kairos_ontology.cli.gates import gates_cmd

        set_active_mode(EnforcementMode.AUTOPILOT)
        result = CliRunner().invoke(gates_cmd, [])

        assert "REFUSED here" in result.output

    def test_json_is_machine_readable_and_complete(self):
        import json

        from kairos_ontology.cli.gates import gates_cmd

        result = CliRunner().invoke(gates_cmd, ["--format", "json"])
        payload = json.loads(result.output)

        assert len(payload["gates"]) == len(GATES)
        assert payload["mode"] == "interactive"
        assert payload["ungated_flags"] == UNGATED_FLAGS


class TestTheArtifactRecordsHowItWasEnforced:
    """DD-234 §6. A ``*-alignment.yaml`` written under ``--without-discovery`` was
    afterwards indistinguishable from a grounded one: the flag was printed to a
    terminal and written into no artifact.
    """

    @staticmethod
    def _alignment(**kwargs):
        from kairos_ontology.core.propose_alignment import DomainAlignment

        return DomainAlignment(
            domain="roro",
            domain_uris=["https://acme.com/ont/roro"],
            generated_at="2026-09-20T00:00:00+00:00",
            model_used="gpt-5.4",
            **kwargs,
        )

    def test_a_clean_run_writes_no_enforcement_block(self):
        """So an unaffected artifact is byte-identical to the previous version's."""
        from kairos_ontology.core.propose_alignment import alignment_to_dict

        assert "enforcement" not in alignment_to_dict(self._alignment())

    def test_an_escaped_run_names_the_mode_and_the_flag(self):
        from kairos_ontology.core.propose_alignment import alignment_to_dict

        data = alignment_to_dict(
            self._alignment(
                enforcement={"mode": "interactive", "escapes_used": ["--without-discovery"]}
            )
        )

        assert data["enforcement"] == {
            "mode": "interactive",
            "escapes_used": ["--without-discovery"],
        }

    def test_the_serializer_stays_pure(self):
        """It is documented as touching no filesystem and reading no global state.

        The enforcement block is carried on the dataclass and populated where the run
        builds it, rather than read from the process ledger at write time, so this
        property survives.
        """
        from kairos_ontology.core.propose_alignment import alignment_to_dict

        set_active_mode(EnforcementMode.CI)
        record_escape("--without-anchors")

        assert "enforcement" not in alignment_to_dict(self._alignment())


class TestTheLedgerDoesNotLeakBetweenInvocations:
    """One process is normally one invocation. It is not when a test or an embedder
    drives the CLI in-process -- which is exactly where one run's escape turning up in
    the next run's artifact would be hardest to notice.
    """

    def test_the_root_group_clears_a_previous_runs_escapes(self):
        from kairos_ontology.cli.main import cli

        record_escape("--without-discovery")
        CliRunner().invoke(cli, ["gates"])

        assert escapes_used() == ()

    def test_the_root_group_clears_a_previous_runs_mode(self, monkeypatch):
        from kairos_ontology.cli.main import cli

        monkeypatch.delenv(MODE_ENV_VAR, raising=False)
        set_active_mode(EnforcementMode.AUTOPILOT)
        CliRunner().invoke(cli, ["gates"])

        assert active_mode() is EnforcementMode.INTERACTIVE

    def test_the_root_mode_flag_reaches_a_subcommands_escape(self):
        """End to end: --mode on the group refuses a flag parsed by the subcommand."""
        from kairos_ontology.cli.main import cli

        result = CliRunner().invoke(
            cli, ["--mode", "autopilot", "anchor-tables", "--without-discovery"]
        )

        assert result.exit_code != 0
        assert "refused in autopilot mode" in result.output


class TestUngatedFlagsAreRealFlags:
    """A classification of a flag that does not exist is not a classification.

    Written after two speculative entries (``--no-verify``, ``--skip-empty``) were found
    in the list describing flags this CLI has never had. The AST scan stops the registry
    going stale in one direction; this stops the exemption list going stale in the other.
    """

    def test_every_exempt_flag_is_declared_somewhere_in_the_cli(self):
        declared = {flag for flag, _module in _plain_click_option_flags()}
        dead = sorted(set(UNGATED_FLAGS) - declared)
        assert not dead, (
            "UNGATED_FLAGS claims these gate nothing, but no CLI command declares "
            f"them: {dead}"
        )
