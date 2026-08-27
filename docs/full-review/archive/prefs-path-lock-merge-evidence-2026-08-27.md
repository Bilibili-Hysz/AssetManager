# Plugin Preference Path Lock and Merge Evidence (2026-08-27)

## Scope
Finding `PREFS-PATH-LOCK-MERGE-49-01`: `PluginPreferenceBag.set()` rewrote the whole JSON from an instance snapshot with no synchronization, so two same-path bags (fresh bags per `_preferences_for`, direct-import bypass) silently dropped each other's writes.

## Change
`preferences.py` adds a path-keyed `RLock` registry (guard lock + capped LRU of 1024, mirroring `asset_index_service`) keyed by the resolved file path — never the plugin id, whose sanitization can collide. `set()` now holds the path lock, re-reads peer writes from disk, shallow-merges `{**disk, **self._data}`, then performs the unchanged atomic `mkstemp + os.replace`. Corrupt/absent files degrade exactly as before; `get()/as_dict()` semantics are untouched.

## Verification
Finding ID for this batch: `PREFS-PATH-LOCK-MERGE-49-01`.
Plugin suites: **54 passed**, headlined by a Barrier-synchronized four-bag regression where 100 distinct keys across threads all survive in the final file, alongside permission-enforcement, dual-host round-trip, tracker concurrency, and plugin v2 contracts.

Final serial suite: **4112 passed, 16 skipped, 20 deselected, 2 warnings**, exit 0.

## Boundaries
Status is `fixed-unverified`. Same-process guarantee only: cross-process writers need an OS-level lock/merge strategy in the preferences layer; unload does not revoke already-issued bags; merge is shallow for nested values. No multi-process soak was run.
