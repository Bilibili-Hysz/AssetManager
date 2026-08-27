# ADR 0001: Architecture Governance Baseline

Date: 2026-06-13

## Status

Accepted.

> 维护状态:**LIVING** · updated: 2026-08-27 · 决策仍有效;实现演化以 `docs/architecture.md` 与 `docs/overview-2026-08-27.md` 为准。

## Context

AssetManager has moved from a PySide6 desktop monolith into a layered platform with desktop and LAN presentations sharing application services. The codebase is production-usable and has a strong quality gate, but several transitional mechanisms remain from the migration:

- `DatabaseManager` still owns mutable current-library state and shared SQLite connections.
- `core/`, `application/`, repositories, and plugin infrastructure still have a few bidirectional dependencies.
- Qt `SignalBus` and domain `EventBus` coexist.
- Plugins are loaded as in-process Python modules.
- LAN sharing can be local-only or exposed through Cloudflare Tunnel.

This ADR records the current operating model and the governance rules for future changes.

## Decisions

1. The current database model is a transitional shared-connection model.

`DatabaseManager` remains the source of existing per-library SQLite connections for now. New work should prefer explicit `LibraryContext` or service/repository APIs over implicit `DatabaseManager.current` access. `DatabaseManager.connection_for()`, `data_dir_for()`, and `thumb_dir_for()` are the first explicit per-root APIs and should be used by new code. `LibraryService`, thumbnail cache initialization, and metadata migration now use those explicit APIs for their per-root resources. `TagStore` and `ProjectData` also accept an explicit `db_conn`, allowing `LibraryContext` resources to share the same known per-root connection. `ConnectionProvider` is defined in `application.context`; `LibraryContext.connection_for()` implements the scoped provider and rejects mismatched roots. `MetadataService` and `TagService` accept a `ConnectionProvider`, with method-level `db_conn` retaining priority where supported. Desktop library-opened paths now treat scoped services as required for `InfoPanel` and `TagTreePanel`; `FileListPanel` requires scoped runtime when a QApplication bootstrap is present and keeps fallback only for bootstrap-free isolated panel scenarios. ADR 0002 defines `LibrarySession` as the target opened-library boundary that should reduce direct global DB access further.

2. Application and domain events remain synchronous, with Qt bridge adapters for UI subscribers.

`domain.event_bus.EventBus` currently calls handlers synchronously on the publisher thread, returns subscription tokens for explicit cleanup, and supports weak bound-method subscriptions so long-lived buses do not keep UI owners alive. Desktop panels must subscribe through presentation-layer Qt bridges so UI handlers run on the Qt thread when events originate from worker or LAN threads; the bridge uses weak subscriptions and closes EventBus subscription tokens during panel shutdown.

3. Plugins are trusted, in-process extensions.

The plugin system executes Python plugin modules with the same process permissions as AssetManager. The manifest `permissions` field is a host API policy signal, not a sandbox. Third-party plugin distribution requires a new ADR covering isolation, signing, update trust, and permission enforcement.

4. LAN exposure must stay explicit and conservative.

LAN path access must go through `PathGuard`. Cloudflare Tunnel or non-local binds should be treated as higher risk. Query tokens remain supported for compatibility and sharing, but UI flows should prefer cookies or authorization headers where practical.

5. Architecture boundary tests guard growth, not all historical debt.

`tests/unit/test_architecture_boundaries.py` prevents high-risk new dependencies and documents the current exceptions. It also guards desktop presentation code from adding new direct DB/store access outside the documented bootstrap-free fallback allowlist. Existing exceptions should be reduced over time. New exceptions require updating this ADR and explaining why the dependency cannot be inverted.

## Current Transitional Exceptions

- `AssetsManager.core.plugins.manager` imports `AssetsManager.application.asset_filters` to apply plugin-registered categories to shared filter maps.
- `AssetsManager.domain.asset.category_for_extension()` imports `AssetsManager.core.format_utils.CATEGORY_MAP`; this is allowed only until category classification is moved to a domain-owned classifier or injected service.
- `AssetsManager.domain.auth.verify_user_token()` accepts a DB connection to check active users; this should move to `AuthService` or an auth repository.

## Consequences

- New features should enter through application services and repositories, not through UI direct DB access.
- New long-lived service dependencies should be constructor-injected or registered in `ApplicationBootstrap`.
- New migrations must be explicit and tested.
- New plugin capabilities must use host APIs so permissions can be enforced later.
- New LAN routes must avoid desktop presentation imports and must validate user-supplied paths centrally.

## Follow-Up Work

1. Implement ADR 0002 `LibrarySession` incrementally and migrate remaining services away from implicit current DB state.
2. Move auth/share tables into the versioned migration runner or document their separate lifecycle explicitly.
3. Add per-migration transaction/rollback tests.
4. Continue hardening EventBus/UI lifecycle coverage as more panels subscribe to domain events.
5. Move plugin category/theme mutations behind reversible host APIs.
6. Expand Pyright coverage from core/application/LAN into widgets, dialogs, then panels.
