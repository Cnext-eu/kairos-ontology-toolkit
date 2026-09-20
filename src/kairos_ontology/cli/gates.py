# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The ``gates`` command and the escape-flag decorator (DD-234).

:func:`escape_option` is the reason the registry cannot drift. A gate escape is
declared by naming its gate, not by writing a plain ``click.option`` and hoping
somebody remembers to register it -- so the flag and its classification are the same
edit, and a flag declared without one fails ``tests/test_gate_registry.py``.
"""

from __future__ import annotations

import json

import click

from ..core.gates import (
    GATES,
    MODE_ENV_VAR,
    UNGATED_FLAGS,
    EnforcementMode,
    active_mode,
    escape_permitted,
    gate_by_id,
    record_escape,
    refusal_message,
)


def escape_option(gate_id: str, *param_decls: str, **kwargs: object) -> object:
    """Declare a flag that escapes a registered gate.

    Wraps :func:`click.option` with a parse-time callback that refuses the flag in a
    mode the gate does not permit, and records it for the artifact provenance block
    either way. The flag's own ``help`` is left to the caller -- it is written for the
    operator meeting it in ``--help``, and the registry entry is written for a reviewer
    auditing what can be bypassed. Those are different readers.

    Raises at import time for an unregistered *gate_id*, because a typo would otherwise
    produce a flag that is silently unenforced -- exactly the state this exists to end.
    """
    gate = gate_by_id(gate_id)
    if gate is None:
        raise ValueError(f"escape_option: no gate registered with id {gate_id!r}")
    flag = next((decl for decl in param_decls if decl.startswith("--")), "")
    if gate.escape and flag and flag != gate.escape:
        raise ValueError(
            f"escape_option: gate {gate_id!r} declares escape {gate.escape!r}, "
            f"but the option is {flag!r}"
        )

    def _enforce(ctx: click.Context, param: click.Parameter, value: object) -> object:
        if not value:
            return value
        used = flag or f"--{param.name}"
        record_escape(used)
        if not escape_permitted(used):
            raise click.UsageError(refusal_message(used), ctx=ctx)
        return value

    kwargs.setdefault("is_flag", True)
    kwargs.setdefault("default", False)
    kwargs["callback"] = _enforce
    return click.option(*param_decls, **kwargs)  # type: ignore[arg-type]


@click.command(name="gates")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format (JSON is emitted clean on stdout).",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Also print why each escape exists and what evidence each gate reads.",
)
def gates_cmd(output_format: str, verbose: bool) -> None:
    """List every gate, the evidence it reads, and the flag that bypasses it (DD-234).

    Answers the question the CLI could not previously answer at all: what can block this
    pipeline, and what can get past it? Reading sixteen option declarations across eight
    files was the only way to find out.
    """
    mode = active_mode()
    if output_format == "json":
        click.echo(
            json.dumps(
                {
                    "mode": mode.value,
                    "gates": [
                        {
                            "id": gate.id,
                            "rule_id": gate.rule_id,
                            "summary": gate.summary,
                            "commands": list(gate.commands),
                            "escape": gate.escape,
                            "escape_modes": [m.value for m in gate.escape_modes],
                            "escape_permitted_here": (
                                escape_permitted(gate.escape, mode) if gate.escape else None
                            ),
                            "requires": list(gate.requires),
                            "on_missing_evidence": gate.on_missing_evidence,
                            "escape_rationale": gate.escape_rationale,
                        }
                        for gate in GATES
                    ],
                    "ungated_flags": UNGATED_FLAGS,
                },
                indent=2,
            )
        )
        return

    click.echo(f"Enforcement mode: {mode.value}")
    if mode is EnforcementMode.INTERACTIVE:
        click.echo(
            f"  Set --mode or {MODE_ENV_VAR} to refuse escapes an unattended run "
            "should not be making."
        )
    click.echo("")
    for gate in GATES:
        rule = f"  [{gate.rule_id}]" if gate.rule_id else ""
        click.echo(f"{gate.id}{rule}")
        click.echo(f"    {gate.summary}")
        if gate.commands:
            click.echo(f"    commands: {', '.join(gate.commands)}")
        if gate.escape:
            allowed = escape_permitted(gate.escape, mode)
            verdict = "permitted here" if allowed else "REFUSED here"
            click.echo(
                f"    escape:   {gate.escape}  "
                f"({', '.join(m.value for m in gate.escape_modes)} — {verdict})"
            )
        else:
            click.echo("    escape:   none — resolve it or it blocks")
        if verbose:
            if gate.requires:
                click.echo(f"    reads:    {', '.join(gate.requires)}")
                click.echo(f"    missing evidence: {gate.on_missing_evidence}")
            if gate.escape_rationale:
                click.echo(f"    why:      {gate.escape_rationale}")
        click.echo("")

    if verbose:
        click.echo("Escape-shaped flags that gate nothing:")
        for flag, reason in sorted(UNGATED_FLAGS.items()):
            click.echo(f"  {flag}: {reason}")
