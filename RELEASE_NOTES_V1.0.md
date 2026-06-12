# V1.0

Release date: 2026-06-11

This version marks the current NCM Library Converter state after the Task2 continuation work.

## Highlights

- Startup now loads the cached library index first instead of forcing a full scan.
- Added startup behavior options: cache only, background incremental check, and full rescan after launch.
- Regular Rescan now performs an incremental scan.
- Added Force Full Rescan for explicit index rebuilds.
- Incremental scanning skips unchanged files by comparing relative path, file size, and modified time.
- Deleted output files cause matching `.ncm` files to return to pending.
- Missing source files are marked missing instead of being deleted immediately.
- Folder watching uses debounce and delays unstable files.
- UI polish includes updated sidebar icons, top status pill, table sizing, file type badges, status badges, and settings controls.
- Added service tests for startup behavior, incremental scanning, deleted outputs, missing files, and full rescan behavior.

## Verification

- `unittest`: 11 tests passing.
- AST syntax check: passing.

