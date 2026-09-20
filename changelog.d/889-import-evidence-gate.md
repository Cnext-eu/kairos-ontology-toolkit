### Added
- **`.import/powerbi/` is scaffolded, and staged business evidence nothing consumed now
  fails `validate` (DD-233).** `.import/` holds the two inputs the pipeline cannot
  re-derive for itself: the client's own documents and their Power BI models. Nothing
  checked that any of it was used. `discovery-status` reported on
  `.import/businessdiscovery/` alone and said "nothing to check" for an empty directory,
  which reads identically whether the client sent no documents or sent thirty to a
  directory no command looks in — and there was no scaffolded home for a Power BI export
  at all, so hubs invented one and every command then failed to find it. `init` and
  `new-repo` now create `.import/powerbi/` with a README covering both export shapes, and
  `validate` reports three kinds of unused evidence as blocking errors: a discovery
  document with no extraction, a Power BI export with no engineering pack, and a business
  document filed outside every directory a command reads. `--degraded` downgrades them to
  warnings.
