### Added
- **`dim_date` has `week_number` and `week_start_date` (#833).** Both follow ISO 8601:
  weeks start on Monday, and week 1 is the week that contains the year's first Thursday.
  On Databricks the week number comes from `weekofyear`; on Fabric it comes from
  `datepart(iso_week, …)`. `week_start_date` is that week's Monday. It sorts and groups
  weeks correctly across a year boundary, which a bare week number does not. Every
  surface that reads the calendar declaration picks both columns up: the dbt model, the
  DDL, the TMDL, `schema.yml`, the ERD and both allowlists. An insight that slices by
  `dim_date.week_number` now resolves.

### Changed
- **`weekPattern` must be `iso-8601` or `iso-8601-monday` (#833).** These are the two
  conventions the calendar implements, and both mean the same ISO weeks. Any other
  value is now rejected in two places:
  - `validate`, through SHACL `sh:in`;
  - compile, with `calendar.unsupported-week-pattern`.

  Before, the value was accepted and copied onto every row even though nothing acted on
  it.
- **Identical calendar profiles in one Gold product are one calendar (#859).** A shared
  conformed domain and a fact domain in the same product can now both declare a
  calendar profile. If every setting matches (bounds, fiscal start, week pattern, locale,
  holiday source, time zone, period closure and approval), the Gold product uses one
  calendar and combines both profiles' role-playing dates. The product report lists the
  other profiles under `calendar.contributing_profiles`.
  `gold.product-calendar-conflict` is now raised only when the settings really differ,
  and its message names the fields that differ.

### Fixed
- **Dropping a shared domain from one Gold product no longer deletes another product's
  provenance sidecar (#860).** `metadata/<domain>-gold.provenance.json` is listed in the
  manifest of every product that uses the domain. When one product stops writing it, the
  file leaves that product's manifest but stays on disk while another manifest in the
  same directory still lists it. The last product to drop the domain removes it, as
  before.
