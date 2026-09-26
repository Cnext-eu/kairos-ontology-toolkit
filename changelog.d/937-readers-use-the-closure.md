### Fixed
- **Four readers now see the `owl:imports` closure instead of one file (DD-243).** A domain
  `.ttl` carries only its own triples; these read it alone and reported a class with a
  reference-model parent as having no properties.
  - **`project --target report`**: the domain overview lists each class's inherited properties,
    marked `(inherited from <Class>)`, and draws a relationship for every declared domain,
    `owl:unionOf` and `schema:domainIncludes` included. It reuses the closures `project`
    already loaded, and says so when a closure did not fully resolve.
  - **`coverage-report`**: properties include the inherited and union-declared ones, each with
    `origin` and `inherited_from`; the `imported` alignment tier now means the matched
    reference class's module is in the domain's resolved closure, not "the domain imports
    something" (the confirmation DD-144 §6 asked for).
  - **`validate --gdpr`**: with the hub catalog, each domain is scanned through its closure,
    so a PII property inherited from a reference parent is reported on the hub's class,
    as `Customer.email (inherited from Party)`. Reference-model classes themselves are never
    judged against the hub.
  - **`validate`'s reference-model shadowing check**: a local class that repeats the name of a
    class two imports away is flagged too, with a remediation that names the import to add.
    The message no longer claims `owl:equivalentClass` would anchor it (#730).
- **The alignment report reads `owl:imports` as RDF**, so `owl:imports <a>, <b>` on one line
  counts both; the previous regex kept the first.

### Notes
- The two earlier guards for the same rule are retired in favour of the DD-243 inventory,
  which covers the whole package per function with a reason: `tests/test_ttl_access_boundary.py`
  and the module allow-list in `tests/test_semantic_loading_boundary.py` (its legacy-loader
  check stays).
- Three known-gap rows leave the DD-243 parse inventory; `validate_gdpr`'s content-string
  path stays for direct callers and is listed as such.
