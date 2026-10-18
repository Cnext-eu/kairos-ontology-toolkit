### Fixed
- **The toolkit is tested against reference models 1.41.0 again, and the daily pin bump
  works.** The bump job moved only the dependency pin, so its own test run failed every
  day from 2026-09-20 and no bump PR was ever opened. The fallback version a new hub
  scaffold uses when the release list is unreachable must not trail that pin, and nothing
  raised it. The bump now raises both. Pin and fallback move from v1.35.2 to v1.41.0.
