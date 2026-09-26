### Fixed
- **`update` no longer installs hub-only agent files into dataplatform repos.** It used to
  create `.claude/settings.json` and the MCP server registrations (`.mcp.json`,
  `.vscode/mcp.json`) in dataplatforms, which `init-dataplatform` never installs.
  - In a dataplatform, every Claude Code file read started `kairos-ontology hook read-context`
    twice, for no benefit.
  - The registered `kairos` MCP server has no hub to serve there and normally cannot start.
  - `update --check` told dataplatform operators to install the settings file.
  - Files an earlier `update` already created are left in place. Delete them by hand if you
    have not extended them.
