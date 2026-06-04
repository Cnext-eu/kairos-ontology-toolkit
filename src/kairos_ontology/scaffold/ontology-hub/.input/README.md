# Import Input Folder

Drop CSV, Excel (.xlsx), or other flat files here before importing them as
source schemas into the ontology hub.

## Usage

1. Place your files in this folder (or in a subfolder per source system).
2. Run the import command:

   ```
   kairos-ontology import-flatfile --from .input/<your-folder> --system <system-name>
   ```

3. Follow up with `import-source` to generate the bronze vocabulary TTL.

## Note

This folder is tracked in git. Avoid committing sensitive or very large
data files — consider using Git LFS for large datasets.
