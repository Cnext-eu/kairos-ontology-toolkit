### Fixed
- **Emit now waits out a Windows antivirus or indexer scan instead of failing after five
  seconds.** The staged directory swap that every `compile --emit` and `emit-gold` ends with
  retried a sharing violation (WinError 5/32/145) for only about five seconds in total. When
  thousands of files were written just before, as with `compile --all --emit`, `project` and then
  `emit-gold`, scanners kept a large Gold tree busy for minutes, and the emit failed until it was
  re-run by hand, sometimes more than a dozen times. After the short backoff, the swap now keeps
  retrying every five seconds for up to three minutes, and logs a warning naming the held path
  once it starts waiting. Set `KAIROS_EMIT_SWAP_TIMEOUT` (seconds) to change the budget; `0`
  restores the old short behaviour, for when an open `.pbip` in Power BI Desktop is the likelier
  holder. A failed swap still leaves the previous output untouched and reports the same hint.
