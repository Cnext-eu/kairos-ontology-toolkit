### Added
- **`kairos-ontology mcp serve` — the closure-aware inspection commands as MCP tools (DD-245).**
  `show_class_inventory`, `list_class_properties`, `explain_term`, `resolve_ontology`,
  `compile_check`, `compile_explain` and `logs_show`, over stdio, from the hub's own
  environment. Every description says what the `.ttl` file does not contain, so an agent
  reaches for the tool rather than the file. Needs the new optional `[mcp]` extra
  (`uv sync --extra mcp`); without it the command says so.
- **The hub scaffold registers the server for both IDE agents**: `.mcp.json` (Claude Code)
  and `.vscode/mcp.json` (Copilot agent mode). `init`, `new-repo` and `update` create them
  when absent and never overwrite them.
- **A raw read of a domain `.ttl` corrects itself on Claude Code.** The scaffold's
  `.claude/settings.json` gains `Read` hooks that run `kairos-ontology hook read-context`:
  after the read, the model is told which modules the file imports, which of its classes
  carry inherited properties that are not in the file, and which tool to call before
  concluding; a read of a reference-model file is denied with the same pointer. The file
  stays readable — denying `Read` breaks authoring (#659). This is a new settings generation:
  a hub on the shipped file receives it on `update`; a hand-edited file gets an advisory.
- The managed skills point at the tools where the server is registered; `kairos-help` lists
  them.
