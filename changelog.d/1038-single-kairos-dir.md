### Changed
- **Run logs now live in the repository root's `.kairos/logs/`, beside
  `upgrade-refresh.log`.** A scaffolded hub had two `.kairos` folders: `update` wrote its
  refresh transcript at the repository root, and `compile --emit`, `emit-gold`, `project`
  and `package-powerbi-release` wrote their run logs inside `ontology-hub/`, where nobody
  looked. Both now resolve the managed repository root; a flat-layout hub is its own root,
  so nothing moves there. `logs show` (and the MCP `logs_show` tool) read the new folder and
  still read logs an older toolkit kept under `ontology-hub/.kairos/logs/`, and now work from
  any folder inside the repository, not only from its root or the hub. `compile` keeps no
  run log when it is run outside a hub. The `.kairos/` folder ignores itself in git, which
  covers dataplatforms, whose `.gitignore` did not list it; new dataplatforms list it too
  (#1038).
