### Fixed
- **A freshly scaffolded hub can now parse the package the toolkit emits for it (issue
  #789).** The v5 Silver path emits generic-test config under the dbt 1.10+ `arguments:`
  key, while the scaffold pinned `dbt-core>=1.9,<1.10` — so `validate-dbt` failed at parse
  with `macro '...' takes no keyword argument 'arguments'`, a message about the macro
  rather than the version. The scaffolded pins now start at the floor the emitter actually
  requires.
- **The hub and the dataplatform no longer resolve different dbt versions.** The
  dataplatform built its own `>=1.9.0,<2.0.0` adapter pin, independent of the hub's, so
  each hid what the other would catch — deprecations emitted *by the hub* were only
  observable *in the dataplatform*, where nobody was looking. Both now read one
  declaration.

### Added
- **The supported dbt stack is declared as toolkit config** (`core.adapters`), instead of
  existing only as pins copied into templates and rediscovered by trial. `DBT_CORE_FLOOR`
  is what the emitted package requires of its consumer; `DBT_CORE_REQUIREMENT` is the
  narrower intersection a hub installs so every supported adapter agrees on one dbt-core;
  `DBT_ADAPTER_REQUIREMENTS` and `DBT_PACKAGE_REQUIREMENTS` cover the adapters and the dbt
  packages the emitter hard-codes call sites against. Each records *why* both ends of its
  range exist. A test binds every surface that repeats them to the declaration.
- **The emitted dbt package declares `require-dbt-version`.** A consumer on an
  incompatible dbt now gets a dbt-native version error first, rather than a macro error
  several steps removed from the cause. Deliberately the floor only: the ceiling is one
  hub's offline-gate concern and would wrongly reject a dataplatform on a newer dbt with a
  different adapter.

### Known issues
- `dbt-fabric` is pinned to exactly `1.10.0`. 1.10.1 replaced pyodbc with mssql-python,
  which parses the connection string eagerly and rejects the `Authority Id` keyword the
  offline validation profile produces, so the offline gate cannot pass on any later
  release. The constant records this; lifting it is tracked separately.
