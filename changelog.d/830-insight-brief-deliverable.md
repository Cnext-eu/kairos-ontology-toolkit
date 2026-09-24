### Decisions
- **The insight brief is the report deliverable; the emitted report stays blank (DD-236,
  #830).** `emit-gold` writes a `.Report` with one empty page, only so the project opens in
  Desktop. That is now a decision rather than an unfinished feature. The toolkit will not
  generate pages or visuals, and will not vendor Power BI's visual-container schemas.
  `<product>-insight-brief.md` is what a BI engineer, or Fabric Copilot, builds the report
  from. Build the report as a separate Fabric item bound to the deployed model. The
  `emit-gold` help, the `kairos-design-gold` skill and the Gold how-to now say so.
