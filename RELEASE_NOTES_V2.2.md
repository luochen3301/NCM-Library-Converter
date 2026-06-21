# V2.2

V2.2 focuses on product readiness for the desktop app. It keeps the upstream NCM conversion core unchanged and improves the first-run experience, conversion completion feedback, failure recovery, UI consistency, and release handoff.

## Highlights

- Added a richer first-run workspace with three clear steps: choose a library, review output settings, and scan/convert.
- Added a conversion summary panel after each queue run with success, failed, skipped, duration, output location, and quick actions.
- Added failure grouping on the queue page so failed files are grouped by likely cause, with copy, retry, and reveal actions per group.
- Refined table and menu behavior with visible sort indicators, stronger failed/missing row treatment, and grouped context menus.
- Restored the MIT `LICENSE` file for GitHub publication and release packaging.
- Updated README and distribution notes for V2.2 release preparation.

## Validation

- Run `python -m unittest discover -s tests`.
- Run syntax validation for `gui.py`, `web.py`, and `ncmdump` modules.
- Run a Qt offscreen startup check and confirm the app initializes with `obsidian` and five sidebar pages.

## Release Checklist

- Build `NCM Converter.exe` with PyInstaller.
- Package `NCM Converter.exe`, `VERSION`, `LICENSE`, `RELEASE_NOTES_V2.2.md`, and `DISTRIBUTION_README_V2.2.txt`.
- Name the Windows archive `NCM-Library-Converter-V2.2-windows.zip`.
- Verify the README preview image renders on GitHub before publishing.
