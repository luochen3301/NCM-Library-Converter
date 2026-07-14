# NCM Library Converter V3.0

V3.0 is a major desktop release focused on predictable interaction, safe background work, and trustworthy conversion results.

## Highlights

- Rebuilt the PyQt6 desktop shell around a compact Library, Tasks, History, and Settings workflow, with Language Lab moved under Tools.
- Removed layout jumps caused by selection actions, long paths, progress updates, and completion summaries.
- Kept library search visible during multi-selection and unified the toolbar and table inside one clean rounded data surface.
- Standardized the search, filter, and batch-action controls at a stable height and radius so selecting a track no longer changes button geometry or compresses the toolbar.
- Separated live task title, current file, metrics, and controls into fixed non-overlapping lanes so changing progress text cannot cover pause or cancel actions.
- Reworked vertical and horizontal scrollbars across tables, settings, lists, and menus with rounded tracks, larger smooth handles, complete hover/pressed/disabled states, and no native dotted page artifacts.
- Cleared the completed batch selection before refreshing converted rows, preventing hidden checked IDs after a pending item leaves the active filter.
- Isolated checked IDs by library and kept unrelated Language Lab selection intact when a conversion batch ends.
- Replaced ambiguous pill-shaped setting controls with accessible track-and-thumb switches for hover, focus, enabled, and disabled states.
- Added a separate FLAC → MP3 tool under Tools with whole-page file/folder drag-and-drop, file/folder batching, 128–320 kbps quality choices, custom output folders, folder-structure preservation, metadata and cover-art copying, existing-output handling, progress, and cancellation.
- Made the FLAC tool a focused standalone workflow by hiding music-library rescan, batch-convert, and global status chrome on that page; converted or skipped rows now expose a right-click action that reveals the actual MP3 file in the platform file manager.
- Bundled the FLAC decoder and LAME encoder runtime so the portable Windows app does not require a system FFmpeg installation; source FLAC files are never deleted by this tool.
- Added a single task state machine so scans and conversions cannot corrupt each other's state.
- Made full scans transactional: cancellation or failure leaves the previous library index untouched.
- Made output writes atomic and cleaned partial files after cancellation or failure.
- Added accurate converted, skipped, failed, and not-processed results with throttled per-file progress.
- Fixed Windows Explorer argument handling so source reveal selects the exact file even when paths contain Unicode, spaces, commas, or use UNC syntax; output-location actions now open the real parent directory.
- Preserved existing V2.x libraries, history, settings, and the public `dump(...) -> str` API.
- Clarified that the NCM workflow still decrypts its original embedded MP3 or FLAC stream without transcoding; transcoding occurs only when the separate FLAC → MP3 tool is explicitly used.

## Validation

- 82 service, reliability, lifecycle, platform, audio-transcoding, drag-and-drop, and Qt interaction tests.
- Qt offscreen interaction and fixed-geometry checks at 960x620, 1280x800, and 1600x900, including 125% and 150% scaling.
- Chinese and English, dark and light visual QA with populated library data.
- Python syntax and dependency checks.
- PyInstaller executable startup smoke test with an isolated SQLite database.
- Streamlit desktop-core compatibility smoke test.

## Upgrade Notes

- Existing SQLite databases are upgraded in place with an idempotent schema migration.
- Legacy `obsidian` and `dark` theme values render with the new professional dark theme.
- The legacy output-format setting remains readable for compatibility but is no longer exposed as a conversion choice.
