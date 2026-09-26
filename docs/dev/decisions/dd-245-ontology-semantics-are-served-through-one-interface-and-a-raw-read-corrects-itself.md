# DD-245: Ontology semantics are served through one interface, and a raw read corrects itself

**Status:** Accepted
**Date:** 2026-09-26
**Affects:** the hub scaffold (`.mcp.json`, `.vscode/mcp.json`, `.claude/settings.json`), `kairos-ontology mcp serve`, `kairos-ontology hook read-context`, the `[mcp]` extra, the managed skills
**Issue:** #937 (context)
**Implementation:** `cli/mcp_server.py`, `cli/hook.py`, `scaffold/mcp.json`, `scaffold/vscode-mcp.json`, `scaffold/claude-settings.json`, `cli/shared.py` (settings generations), `cli/setup.py`, `cli/operations.py`

### Context

DD-243 and DD-244 made the toolkit's own code and prompts read the `owl:imports` closure. The
agent working in a hub is the remaining reader. It has a `Read` tool, the domain `.ttl` is on
its disk, and it must stay readable: #659 showed that denying `Read` on `model/ontologies/**`
makes authoring impossible, because `Edit` needs a prior `Read`. So the question is not how to
stop the read but how to stop the *conclusion* drawn from it.

Two things decide what an agent does after a read. First, which path is easiest: today the
closure-aware path is `uv run kairos-ontology explain-term <IRI> --domain <d>` with an
environment variable set, typed into a shell, against a one-call `Read` of a visible file;
models take the low-friction path, and skill prose fights that uphill. Second, what the model
is told immediately after the read; nothing is, today.

An API that serves the OWL and hides the files would not change either fact while the hub is
a git repository the agent edits. It would add deployment, authentication, availability and
version skew for no one yet outside the repository who needs it.

### Decision

1. **The closure-aware inspection commands are also MCP tools.** `kairos-ontology mcp serve`
   starts a stdio server (`cli/mcp_server.py`, official `mcp` SDK, optional `[mcp]` extra)
   exposing `show_class_inventory`, `list_class_properties`, `explain_term`,
   `resolve_ontology`, `compile_check`, `compile_explain` and `logs_show`, wrapping the same
   core functions the CLI uses. Every tool description states the closure fact — the `.ttl`
   file does not contain the inherited properties — because tool choice follows descriptions.
   Every payload carries the profile's `coverage` map (DD-243). Stateless; nothing is served
   that a CLI command does not already print.
2. **The scaffold registers the server for both IDE agents.** `.mcp.json` (Claude Code, one
   one-time trust prompt) and `.vscode/mcp.json` (Copilot agent mode) run
   `uv run kairos-ontology mcp serve` from the hub's own environment. `init`, `new-repo` and
   `update` create them when absent and never overwrite them.
3. **A raw domain read corrects itself, on Claude Code.** The scaffold's
   `.claude/settings.json` gains `PreToolUse` and `PostToolUse` hooks on `Read` that run
   `kairos-ontology hook read-context`. After a read of `model/ontologies/<d>.ttl` the model
   receives one paragraph: the file's imports, which of its classes carry inherited
   properties that are not in the file, and the tool to call before concluding. Before a
   read of a reference-model file — never authored — the read is denied with the same
   pointer. The hook never blocks on its own failure (`{}`, exit 0). This is a new
   generation of the settings file, registered in `_KNOWN_CLAUDE_SETTINGS_GENERATIONS` with
   the outgoing generation vendored, so hubs on the shipped file receive it on `update` and
   a hand-edited file gets an advisory.
4. **The skills say "call the tool"** where the server is registered, and the CLI command
   otherwise; `kairos-help` lists the tools.
5. **The tool signatures are the interface a hosted service would serve.** That step waits
   for a consumer outside the repository (a dataplatform, BI or another team needing "what
   does class X mean" without cloning the hub); until then it is deployment cost for no one.

### Consequences

- The layers, and what each honestly does: DD-243's tests keep the toolkit's own code on the
  closure; DD-244 keeps prompts honest about cuts; the skills make the right path the
  default; MCP makes it the easiest path on both IDEs; the hook makes a raw read
  self-correcting on Claude Code. None is a wall, and a hosted API would not be one either
  while the files are on disk. Copilot has no hook mechanism, so there it is MCP plus the
  instructions file.
- The `[mcp]` extra pulls the `mcp` SDK (MIT) and its dependencies into hubs that opt in.
  Without it, `mcp serve` says how to install it and nothing else changes.
- Each domain read on Claude Code costs one closure load in the hook (an in-process cache
  miss, since the hook is its own process): about the cost of `explain-term`, which is what
  the model should have run.
- Rejected: denying `Read` again (#659). Rejected: a hosted API first (no consumer, real
  operational cost, and it would not prevent the read). Rejected: a hook that blocks domain
  reads unless "in an authoring step" — a hook cannot see intent.
