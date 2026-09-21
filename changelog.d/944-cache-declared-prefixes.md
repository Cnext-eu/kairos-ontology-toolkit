### Performance
- **`compile <domain>` is roughly 2.5x faster.** `_declared_prefixes` stats, reads and
  regex-scans a whole Turtle file on every call, and one domain's plan build called it
  13,464 times against 36 distinct files — each file read about 374 times, over the
  vendored reference-model corpus. That was the largest single entry in the profile,
  ~3.7s of self time in an 11.4s build. The parse is now cached on file identity, taking
  the same build from 8.6s to 3.3s. `compile --all` pays this per domain, so the saving
  multiplies by the domain count.

  Cached on `(path, mtime_ns, size)` rather than path alone, so a file rewritten in the
  same process is re-read and neither a test that edits a fixture nor a long-lived
  process can be served a stale answer. The `stat` that produces the key replaces the
  `is_file()` check the function already made.
