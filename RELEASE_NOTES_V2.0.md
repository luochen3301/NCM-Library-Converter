# V2.0

V2.0 archives the current desktop UI and service baseline before the next experimental feature release.

## Highlights

- Preserves the PyQt6 desktop interface improvements on the current `codex/task3-ui-ux` branch.
- Includes the current library scanning, incremental state tracking, conversion queue, history, settings, and bilingual UI updates.
- Keeps the V1.0 backend contracts intact while capturing the latest UI responsiveness and interaction polish.

## Validation

- Baseline service tests passed with `.venv-codex\Scripts\python.exe -m unittest discover -s tests`.
- Syntax validation uses a temporary `PYTHONPYCACHEPREFIX` in this environment because the repo-local `__pycache__` directory can be permission restricted.
