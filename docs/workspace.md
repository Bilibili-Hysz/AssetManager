# Workspace Layout

Date: 2026-06-16

The active project now lives at the repository root.

## Active Root

- `AssetsManager/` — application package.
- `tests/` — unit, integration, desktop, LAN, core, and performance tests.
- `docs/` — current architecture, development, testing, migration, and handoff docs.
- `Plugins/` — bundled plugin examples and plugin docs.
- `assets/` — packaged static assets.
- `main.py`, `run.py`, `build.py` — entry/build scripts.
- `requirements*.txt`, `pytest.ini`, `pyrightconfig.json` — project tooling configuration.

## Backup Copy

`Project/` is retained as a complete backup of the pre-flattened workspace. It is ignored by the new Git repository and should not be edited during normal work.

The active refactor source was copied from `Project/AssetsManager_Python_Rewrite_refactor/` into the repository root. New work should target root-level paths such as `AssetsManager/`, `tests/`, and `docs/`.

For subagents, `docs/agent-quick-map.md` is the first navigation doc to read for non-trivial work.

## Git Baseline

The old repository metadata was removed and a new Git repository was initialized at the flattened root. At the time of this layout change, no initial commit has been created yet.

Before committing a new baseline, run the full quality gate:

```powershell
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

Latest verified result after flattening:

- Ruff: passed
- Pyright: `0 errors, 0 warnings, 0 informations`
- Compileall: passed
- Pytest: `607 passed, 1577 warnings in 17.48s`
