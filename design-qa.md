# NCM 音乐库转换器 V4.0 — Design QA

## Review target

- Source reference: `C:\Users\zzk90\.codex\visualizations\2026\09\01\01a05cda-d8f6-7f82-9b5e-30697926a3c7\ncmdump-audit\selected.png`
- Implemented reference: `K:\软件项目\ncmdump-1.0.0\outputs\qa-v4\100pct-1280x820-library.png`
- Side-by-side comparison: `K:\软件项目\ncmdump-1.0.0\outputs\qa-v4\comparison-v3-v4-library.png`
- Reference viewport/state: 1280 x 820, dark theme, Library page with populated table.

## Focused comparison history

1. Replaced the legacy Widgets surface with a QML shell and centralized Graphite/Teal tokens.
2. Tightened the 44 px title bar, 196 px navigation rail, page header, metric cards, filters, table, and batch footer to keep the default viewport free of horizontal scrolling.
3. Replaced placeholder/text glyphs with a consistent Lucide Outline SVG subset and Qt-tinted icon controls.
4. Checked hierarchy, spacing, truncation, status contrast, empty states, disabled states, focus behavior, and light-theme parity against the selected reference.
5. Final side-by-side inspection found no unresolved P0, P1, or P2 visual defects.

## Visual matrix

- Pages: Library, Tasks, History, Settings, Language classification, FLAC to MP3.
- Sizes: 960 x 640, 1280 x 820, 1600 x 900.
- Scale factors: 100%, 125%, 150%, 175%, 200%.
- Theme/state additions: all six pages at 1280 x 820 in light theme, plus a deterministic empty-library state.
- Result: all captures completed with zero QML warnings. Narrow layouts retain the full column set and expose horizontal table scrolling only when required.

## Interaction and runtime checks

- Keyboard navigation, focus rings, shortcuts, menus, drag/drop surfaces, empty and disabled states were exercised by the QML interaction suite.
- Native Windows package opened at 1280 x 820, maximized to 2560 x 1392, restored, minimized/restored, resized to 1100 x 700, and exited cleanly through both the system close path and Alt+F4.
- Pointer-driven title-bar movement and border-drag injection could not be completed by the available automation driver; the same native move/resize paths were validated through Windows window-state automation and the QML implementation uses `startSystemMove()` / `startSystemResize()`.
- The host exposes one 96-DPI monitor, so live cross-monitor DPI migration was unavailable. The five-factor DPI render matrix covers layout scaling, but does not claim a physical multi-monitor migration test.

## Performance

- Dataset: 4,155 records.
- Model initialization: 414.54 ms.
- Search: 8.65 ms.
- Sort: 7.96 ms.
- Twelve animated page switches: 2,949.74 ms total.
- Scroll and frame grab: 154.33 ms.
- QML warnings: 0.
- Machine-readable report: `K:\软件项目\ncmdump-1.0.0\outputs\qa-v4\performance-4155.json`.

## Packaging

- PyInstaller one-file archive contains the application QML, Qt Quick Controls plugins, SVG plugins, libsndfile, and lameenc.
- Archive validation rejects the incompatible root-level `icuuc.dll`/`icudt78.dll` that caused the original QtCore import failure.
- A clean-directory packaged launch initialized its database, remained responsive, and exited without a stale process tree.

final result: passed
