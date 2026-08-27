# Plugin Lifecycle Concurrency and Live Category Refresh Evidence (2026-08-22)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `plugin-lifecycle-category-refresh-evidence-2026-08-22` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; baseline captured before this report and manifest were added |
| Baseline status SHA-256 | `2bf23ef7ced42c764425112705bf5e8bf7ef74a0f6722b572872752fc524421b` |
| Baseline diff SHA-256 | `35900040b21e530884e02e7669a5f68ca91fa6a8517b4a47000541cbd8505f5e` |
| Baseline tracked / untracked entries | `123 / 60` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3 |

This append-only dated snapshot records the plugin lifecycle concurrency and open file-list category-refresh batch. Earlier evidence remains unchanged. Its machine-readable companion is [audit-manifest-plugin-lifecycle-category-refresh-evidence-2026-08-22.json](audit-manifest-plugin-lifecycle-category-refresh-evidence-2026-08-22.json).

## Implemented contracts

### `PLUGIN-LIFECYCLE-CONC-01` - serialized lifecycle and discovery publication

`PluginManagerService` tracks record transitions, runs lifecycle callbacks outside its manager lock, serializes callbacks sharing a `PluginHostContext`, rejects callback-originated lifecycle recursion, and publishes discovery outcomes with monotonic request revisions. Explicit disable intent is persisted before releasing its transition, while in-flight discovery retains the latest descriptor or removal outcome (`AssetsManager/core/plugins/manager.py:87-170`, `AssetsManager/core/plugins/manager.py:185-260`, `AssetsManager/core/plugins/manager.py:302-337`).

Plugin tests now use a per-test in-memory `AppSettings` substitute. This preserves the test-local durable-disable contract while preventing xdist workers and repeated test runs from writing synthetic plugin IDs into the user's shared settings file (`tests/conftest.py:442-463`, `tests/plugins/conftest.py:1-9`, `tests/plugins/test_manager_lifecycle_concurrency.py:608-647`). Production persistence behavior is unchanged.

### `PLUGIN-CATEGORY-REFRESH-01` - live category refresh stays at the presentation boundary

The application category registry now publishes complete-snapshot changes through a lock-safe, non-Qt subscription API after rebuilding its public registries (`AssetsManager/application/asset_filters.py:15-55`, `AssetsManager/application/asset_filters.py:111-154`). `CategoryRegistrySubscription` bridges that callback into a queued Qt signal only in `panels`, so plugin reload from a worker thread cannot update widgets off the GUI thread (`AssetsManager/panels/_event_bridge.py:39-62`).

`FileListPanel` owns and closes the bridge before loader/model shutdown. Existing selected categories retain their canonical key, membership changes reapply the model filter, and removed categories fall back to `all` (`AssetsManager/panels/file_list/_base.py:49-69`, `AssetsManager/panels/file_list/_base.py:145-154`, `AssetsManager/panels/file_list/_base_layout.py:344-384`).

The category registry still does not provide one atomic generation spanning all legacy public globals. Consumers that separately read category map and label structures can observe different generations; that broader shared-snapshot architecture remains deferred.

## Executed verification

### Focused plugin, UI, and architecture regression

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-plugin-settings-evidence -q tests/plugins tests/integration/test_plugin_service.py tests/unit/test_file_list_category_refresh.py tests/desktop/test_domain_event_bridge.py tests/unit/test_architecture_boundaries.py
```

Result: **249 passed, 0 failed**, exit code 0, 31.91 seconds. The command covers lifecycle/discovery interleavings, test-local durable intent, application-layer Qt boundary enforcement, worker-originated queued category refresh, membership changes, selected-category removal, and shutdown behavior. Raw output is stored at `artifacts/evidence/2026-08-22/plugin-lifecycle-category-final/focused.stdout.log`.

### Full Python suite

```text
python -m pytest --basetemp=.zcode/pytest-plugin-concurrency-full-isolated -n 0 -q
```

Result: **3942 passed, 12 skipped, 17 deselected, 0 failed, 2 warnings**, exit code 0, 629.08 seconds. Windows-limited skips cover unavailable symlink privileges, POSIX flock recovery, and nondeterministic abrupt process termination. The two warnings are the existing share-dialog signal disconnect warning and the duplicate ZIP entry validation warning. Raw output is stored at `artifacts/evidence/2026-08-22/plugin-lifecycle-category-final/full.stdout.log`.

### Static and governance gates

The following gate chain exited 0 and its raw output is stored at `artifacts/evidence/2026-08-22/plugin-lifecycle-category-final/static.stdout.log`:

- `python scripts/check_audit_reports.py`
- `python scripts/check_doc_stats.py`
- `python scripts/check_boundaries.py`
- `python scripts/check_style_sources.py`
- `python scripts/check_route_capabilities.py`
- `python scripts/check_frontend_data_fetch.py`
- `python scripts/check_layers.py`
- `python -m ruff check AssetsManager tests scripts run.py`
- `python -m compileall AssetsManager -q`
- `git diff --check`

## Status and remaining limits

Both findings remain **`fixed-unverified`**. Local focused and full Python regression proves neither browser E2E nor a real LAN backend/plugin ecosystem, independent Windows/POSIX lifecycle behavior, power-loss recovery, dependency/CVE state, performance characteristics, package/release execution, or clean-checkout reproducibility.

This batch does not implement descriptor-backed final-open/TOCTOU protection. It also does not solve atomic cross-object category generations for legacy consumers such as the grid renderer and info controller.

No commit, push, release, revert, reset, clean, or overwrite of existing dirty-worktree changes was performed.
