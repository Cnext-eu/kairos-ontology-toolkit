### Fixed
- **A model that rejects `temperature` no longer floods the terminal with `Error code: 400`
  lines.** On gpt-5.5, `analyse-sources` printed one bare 400 per call already in flight when
  the first rejection was learnt, 16 with the default worker pool. The rejections were
  handled and every table was still classified, but they read as failures. Two changes:
  the first call for a model now runs alone, so the rest of the pool sends the corrected
  request and a run pays for one rejection instead of one per worker; and the Langfuse
  tracing wrapper's echo of a parameter rejection the toolkit handles is no longer printed.
  The single `ℹ … handled` line remains. Capability is still learnt from the provider's own
  rejection, not from a model-name table, because a Foundry deployment name need not be the
  model's name (DD-174) (#1041).
