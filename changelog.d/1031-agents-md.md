### Changed
- **`AGENTS.md` now carries the agent instructions in hubs and dataplatforms;
  `.github/copilot-instructions.md` becomes a short pointer (DD-246).** `AGENTS.md` is read by
  Copilot (coding agent, CLI, VS Code), Claude Code, Codex, Cursor and Gemini CLI. Before this,
  Claude Code sessions in a hub read no always-on rules at all. Hubs also stop receiving the
  toolkit-developer rules the old file carried.
  - The toolkit owns only the block between the `managed-begin` / `managed-end` markers in
    `AGENTS.md`. Text outside the block is yours and `update` never touches it.
  - `update --check` reports drift inside the block only; `--test-ref` / `--restore` cover
    the file.
  - **Upgrade:** run `update`. It adds `AGENTS.md`; an `AGENTS.md` you already have keeps its
    text below the new block. It also shortens `copilot-instructions.md`. If you keep a
    `CLAUDE.md`, add the line `@AGENTS.md` to it: Claude Code reads `AGENTS.md` only when no
    `CLAUDE.md` exists. `update` prints a reminder until you do, without failing `--check`.
