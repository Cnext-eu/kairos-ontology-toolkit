### Changed
- **The dataplatform's post-deploy BPA notebook pins Semantic Link Labs 0.18.1 (was 0.17.1).**
  Every call the notebook makes is unchanged in 0.18.1, and its Best Practice Analyzer rules
  are identical, so findings read the same. It needs `semantic-link-sempy` 0.14.3 or later,
  which the notebook's `%pip install` brings in. The previous notebook is recorded, so
  existing dataplatforms pick up the new pin on their next `kairos-ontology update`.
