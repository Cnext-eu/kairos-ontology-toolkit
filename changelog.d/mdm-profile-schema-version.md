### Added
- **The `mdm-profile` release now emits a `schema_version` field.** `kairos-mdm-runtime`'s
  profile contract already specified `schema_version` and a fail-closed compatibility check
  against it, treating its absence as an undocumented baseline. The toolkit now emits it
  explicitly (`"1.0.0"`, matching that assumed baseline), so runtime readers can check
  compatibility directly instead of inferring it. `schema_version` is covered by
  `content_digest` like the rest of the profile policy, so a `{domain}-mdm-profile.json`
  regenerated from an unchanged reviewed hub state will have a different digest than one
  produced before this change — re-pin dataplatform digests after upgrading.

### Documentation
- Recorded the decision as `MDM-DD-005` in `docs/dev/mdm/mdm-design-decisions.md`.
