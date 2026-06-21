# V2.1

V2.1 adds the experimental language classification workspace and a new premium dark desktop theme.

## Highlights

- Added a separate sidebar page for experimental local language classification.
- Added an `obsidian` theme inspired by modern dark productivity apps, with redesigned surfaces, sidebar selection, cards, buttons, tables, badges, filters, and scrollbars.
- Made `obsidian` the default for new users while preserving existing `dark` and `light` settings.
- Added local Unicode-script language inference for Chinese, English, Japanese, Korean, mixed, other, and unknown tracks.
- Improved Web temp-file handling so same-named uploads no longer overwrite each other.
- Hardened settings loading when legacy or corrupted concurrency values are present.

## Validation

- Syntax validation passed with a temporary `PYTHONPYCACHEPREFIX`.
- Unit tests passed: `18 tests OK`.
- Qt offscreen startup check confirmed the app initializes with `obsidian` and five sidebar pages.
