# Day 2 Grid Zoom Investigation

## Environment

- Date: 2026-07-21
- Isolated worktree: `.worktrees/grid-zoom-interpolation-fix`
- Branch: `fix/grid-zoom-interpolation`
- HEAD: `0885d77c74baa6caa94f0a6e98b155a5f3fef399`
- Python: `3.14.3`
- pytest: `9.0.2`
- Qt platform: `offscreen` through `tests/desktop/conftest.py`

## Procedure

1. Ran the Day 1 focused node once in the isolated worktree.
2. Read `tests/desktop/test_file_list_grid_widget.py`, `AssetsManager/panels/file_list/_grid_widget.py`, and the FileList zoom-animation caller.
3. Inspected Grid zoom-related history, including the texture-preservation implementation and its interpolation follow-up.
4. Ran the exact target node 20 times in the main worktree and 20 times in this isolated worktree with `-p no:cacheprovider`.
5. Compared Git index blobs, semantic source content, active diffs, pytest configuration, desktop fixtures, and Qt-related environment variables across both worktrees.

## Results

| Check | Result | Evidence |
| --- | --- | --- |
| Initial isolated reproduction | PASS | `python -m pytest tests/desktop/test_file_list_grid_widget.py::test_grid_zoom_interpolates_toward_target_layout -q` passed in `1.33s`. |
| Main-worktree repeated reproduction | PASS | 20/20 executions of `pytest -p no:cacheprovider tests/desktop/test_file_list_grid_widget.py::test_grid_zoom_interpolates_toward_target_layout` passed. |
| Isolated-worktree repeated reproduction | PASS | 20/20 executions of the same command passed. |
| Relevant source comparison | PASS | `_grid_widget.py` and `test_file_list_grid_widget.py` use identical Git index blobs in both worktrees. Filesystem byte hashes differ only from line-ending normalization. |
| Relevant active diff comparison | PASS | Neither investigated source file nor test file appears in either worktree's `git diff --name-only`. |
| Fixture/environment comparison | PASS | Python, pytest, plugins, `QT_QPA_PLATFORM=offscreen`, and relevant pytest/Qt environment variables matched. |

## Root-Cause Investigation

The Day 1 assertion was:

```text
after begin_zoom(180) and set_zoom_thumb_size(128), middle remained equal to start
```

The current implementation has the required source-to-target interpolation path:

```text
begin_zoom(target)
  -> capture source texture rectangles
  -> compute target GridLayout without replacing the active layout
  -> capture target rectangles
set_zoom_thumb_size(current)
  -> update current thumb size and request a frame
_zoom_texture_rect(rect, row)
  -> calculate clamped progress from current/start/target sizes
  -> interpolate x/y/width/height between captured source and target rectangles
paintEvent()
  -> draw cached texture into the interpolated rectangle
```

Key locations:

- `AssetsManager/panels/file_list/_grid_widget.py:185-233` captures source/target geometry and advances the frame.
- `AssetsManager/panels/file_list/_grid_widget.py:930-958` calculates interpolation progress and the intermediate rectangle.
- `AssetsManager/panels/file_list/_grid_widget.py:471-475,521` draws cached textures into the interpolated geometry.
- `AssetsManager/panels/file_list/__init__.py:879,889-893` starts the zoom geometry phase and passes each animation-frame size without relaying out the main grid.
- `tests/desktop/test_file_list_grid_widget.py:1001-1017` asserts the middle geometry changes while the active layout column count stays stable.

History shows `5dc165f` introduced texture preservation without source-to-target geometry interpolation. Commit `9af8061` introduced the current capture/interpolation implementation and the regression test. Both the main worktree and isolated worktree include that correction at HEAD.

## Finding

| Priority | Risk classification | Reproduction | Decision |
| --- | --- | --- | --- |
| Deferred | Historical, currently unreproducible desktop Grid interpolation regression | The Day 1 full-suite result contained one failed Grid interpolation assertion, but the exact node passed in 40/40 later isolated executions across matching source, fixtures, and environment. | No source or test change. Current evidence does not identify a reproducible defect or a concrete condition to repair. Preserve the focused node in later desktop regression runs. |

## Changed Files

- `docs/compose/reports/2026-07-22-grid-zoom-investigation.md`

## Release Impact

No Grid code correction is justified from current evidence. The historical Day 1 failure remains deferred and must be promoted only if the exact focused node fails again with captured output and environment details. This investigation does not establish release readiness; real LAN acceptance and the remaining weekly gates are still required.
