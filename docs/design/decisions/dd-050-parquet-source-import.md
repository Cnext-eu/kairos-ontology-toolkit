# DD-050: Parquet Source Import

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `import_flatfile.py`, `cli/main.py` (`import-flatfile`), `pyproject.toml`, `kairos-design-source` skill (both copies)
**Implementation:** `src/kairos_ontology/import_flatfile.py` (`_arrow_type_to_sql`, `read_parquet_table`, `run_import_flatfile` dispatch), `tests/test_import_flatfile.py`

### Context

The flat-file importer (`import-flatfile`) supported CSV and Excel only. Several
source systems (warehouse/logistics exports in particular) deliver data as
**Parquet** files, which previously had to be converted to CSV first — losing the
reliable typed schema Parquet carries.

### Decision

Add native Parquet support to `import-flatfile`:

1. **`read_parquet_table()`** reads a single `.parquet` file into the same table
   data dict shape as `read_csv_table()`. Like CSV/Excel, it reads **only sample
   data** — at most `max_rows` rows via a single
   `ParquetFile.iter_batches(batch_size=max_rows)` batch — and never materialises
   the full file. ~~`row_count` reflects the rows actually read.~~ *(Amended
   2026-08-15, see below: `row_count` is now the true cardinality from the file
   metadata; the window is recorded as `rows_sampled`.)*
2. **Direct Arrow→SQL type mapping** (`_arrow_type_to_sql()`): because Parquet
   carries a reliable typed schema, column data types are mapped directly to the
   SQL-like vocabulary (`bigint`/`int`/`decimal`/`date`/`datetime`/`bit`/
   `varchar(max)`) rather than inferred from stringified values. Sample/distinct
   values are still stringified to match the YAML output format.
3. **Optional `parquet` dependency-group** (`pyarrow`), lazy-imported with a clear
   `ImportError` pointing at `pip install kairos-ontology-toolkit[parquet]`,
   mirroring the openpyxl/`[flatfile]` pattern. CI installs it via
   `uv sync --all-groups`.
4. `.parquet` is wired into both the single-file and directory dispatch in
   `run_import_flatfile()`; directories may freely mix CSV/Excel/Parquet.

### Consequences

- Parquet files import with one command, producing the standard
  `_manifest.yaml` + per-table YAML + samples that feed `import-source`.
- Type fidelity is higher for Parquet than CSV (schema-driven, not heuristic).
- pyarrow (~26 MB) is opt-in; CSV-only users are unaffected.
- Downstream post-read logic (technical-column detection, exclusion) applies to
  Parquet automatically.
- Tests in `tests/test_import_flatfile.py` cover the type mapping, the reader
  (nullability, sampling cap, date/timestamp), single-file + mixed-directory
  imports, and the missing-pyarrow `ImportError`.

### Amendment (2026-08-15): `row_count` from file metadata, window as `rows_sampled` (#422, DD-156)

"`row_count` reflects the rows actually read" is struck. It made `row_count`
mean *window size* on this path while the warehouse path recorded a full-table
`COUNT(*)` under the same field name — the dual meaning DD-156 removes.
`read_parquet_table` now takes the true cardinality from
`ParquetFile.metadata.num_rows` (free — footer metadata, no body read; it also
fixes a latent undercount where only the **first** batch of a multi-row-group
file was reported) and records the profiling window separately as
`rows_sampled`. Everything derived from the read rows (nullability, distinct
counts, sample slicing) still uses the window size. The reading strategy —
sample-only, one batch, never the whole file — is unchanged.
