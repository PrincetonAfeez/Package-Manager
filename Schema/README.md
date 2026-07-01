# PyPM Lab Schema Folder

This folder contains simple JSON Schema files for the main PyPM Lab data contracts.
They are intended as documentation and validation helpers; they were created locally
and were not pushed to GitHub.

## Files

- `common-definitions.schema.json` — shared definitions for package names, versions, constraints, integrity values, dependency maps, and safe relative paths.
- `project-manifest.schema.json` — project `package.json` used by `pypm init`, `pypm add`, and `pypm remove`.
- `archive-package-manifest.schema.json` — `package.json` embedded inside an inert package archive.
- `registry-index.schema.json` — local `registry/index.json` with package versions, archive paths, integrity values, and dependencies.
- `lockfile.schema.json` — `pypm-lock.json` with exact resolved versions, roots, integrity values, and dependency edges.
- `installed-records.schema.json` — `.pypm/installed.json` store record.
- `graph-export-json.schema.json` — JSON output from `pypm graph --format json`.
- `install-plan.schema.json` — topological install order data shape.

## Notes

- PyPM Lab package names are normalized lowercase strings using letters, numbers, dots, underscores, and dashes.
- Versions are strict `major.minor.patch` strings.
- Integrity values use `sha256:<64 hex chars>`.
- The schemas intentionally keep version constraints as strings because PyPM Lab supports multiple constraint syntaxes, including exact versions, comparators, comma ranges, caret, and tilde.
