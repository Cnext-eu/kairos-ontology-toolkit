# Historical `claude-settings.json` generations

Every superseded generation registered in `_KNOWN_CLAUDE_SETTINGS_GENERATIONS`, stored verbatim
with **LF** line endings.

These are vendored rather than resolved from git history on purpose (issue #684). CI checks out at
`fetch-depth: 1`, so `git show <old-sha>:...` is unavailable there — a test that reached for history
passed locally and failed only in CI. Vendoring also makes the fixtures readable: the diff between
`03-` and `04-` *is* the twelve `Read(...)` denies that #659 removed.

Add a file here whenever a generation is registered, and keep them LF: the hash the toolkit
registers is of the LF-normalized bytes, and a CRLF fixture would silently re-introduce exactly the
bug these files exist to pin.
