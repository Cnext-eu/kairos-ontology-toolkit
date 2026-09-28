### Fixed
- **Emit no longer fails when the target folder itself is held open.** On Windows, a
  terminal whose current directory is the emission target, or a tool watching exactly that
  folder, holds the folder but none of its children. The staged swap renames the whole
  folder, so every emit failed with `could not move emission target to backup` until the
  holder closed, even after the full retry budget. Emit now retries the folder rename for
  the short backoff only (about five seconds), then swaps the folder's contents in place:
  the previous children move to a backup, the staged children move in, and any failure
  moves both back, so the previous output stays whole.
