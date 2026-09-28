### Fixed
- **`update` now installs every file a skill ships, not only its `SKILL.md`.** `init` copied a
  skill's whole folder, but `update` refreshed `SKILL.md` alone. A hub that took a skill through
  `update` therefore had a link to a file it never received:
  `kairos-design-gold/report-design-inspiration.md`, the design-domain Turtle exemplars and the
  design-mapping `exemplar-binding.yaml`. Markdown siblings are now managed like `SKILL.md`. The
  exemplar `.ttl` and `.yaml` files are compared by content, ignoring line endings, because a
  managed marker would make them invalid. `update --check` reports any that are missing or edited.
  `init-dataplatform` also installs each skill's whole folder now.
