### Documentation
- **The BPA profile reaches the people who design and ship the model (DD-238).**
  - `kairos-design-gold` gains a "best practice by design" section. For each measure it asks
    for a display name, a description, a format string and qualified DAX. For each bridge it
    asks which way filters flow. It gives the Direct Lake and DirectQuery differences, and
    says which checks block, which warn and which run after deploy.
  - `kairos-package-dataplatform`, `kairos-setup-dataplatform` and the dataplatform `CICD.md`
    describe the advisory post-deploy run, including the manual check for a Pro workspace. Its
    findings go back to the hub as authoring.
  - `kairos-toolkit-ops` adds the manual release-checklist step to refresh the vendored
    `BPARules.json` and the `semantic-link-labs` pin.
  - The CLI reference lists the new `compile --check` and `emit-gold` codes.
  - `BPA_PROFILE.md` now ships to hubs as `docs/toolkit/BPA_PROFILE.md`.
