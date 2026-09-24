### Changed
- **`_analysis/` file names now say what they are about (DD-235).** Files under
  `integration/sources/_analysis/` put their scope in the name. Before, you could not
  tell whether `booking-alignment.yaml` was about a source system or an ontology domain.

  | before | after |
  |---|---|
  | `tms-affinity.yaml` | `src-tms.affinity.yaml` |
  | `booking-alignment.yaml` | `dom-booking.alignment.yaml` |
  | `booking-unresolved-anchors.yaml` | `dom-booking.unresolved-anchors.yaml` |
  | `table-anchors.yaml` | `hub.table-anchors.yaml` |
  | `gap-decisions.yaml` | `hub.gap-decisions.yaml` |
  | `affinity-matrix.yaml` | `hub.affinity-matrix.yaml` |

  Commands write the new names and still read the old ones for this minor release; where
  both exist, the new one wins.

### Notes
- **`update` renames existing files.** It uses `git mv`, so history follows the file.
  `update --check` lists the renames without making them. If a file exists under both
  names, `update` reports the pair and leaves both alone. Delete the old one once you have
  checked it.
- Scripts or CI that reference the old file names need updating. The skills and the CLI
  reference already use the new names.
