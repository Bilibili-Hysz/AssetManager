# ADR 0003: Library Runtime Ownership and LAN Composition

> 维护状态:**LIVING** · updated: 2026-08-27 · 决策仍有效;实现演化(懒投影代数/关闭编排)见 overview §12。

## Status

Accepted target decision; the Windows implementation, cross-surface acceptance
and Linux directory-symlink platform gate are evidenced. The current-state
report and recalibration report are authoritative:

- [`desktop-lan-webui-architecture-migration.md`](../archive/2026-09/compose-reports/desktop-lan-webui-architecture-migration.md)
- [`desktop-lan-webui-architecture-recalibration.md`](../archive/2026-09/compose-reports/desktop-lan-webui-architecture-recalibration.md)
- [`a3-service-assembly-2026-08-02.md`](../archive/2026-09/compose-reports/a3-service-assembly-2026-08-02.md)
- [`b1-runtime-sharing-2026-08-03.md`](../archive/2026-09/compose-reports/b1-runtime-sharing-2026-08-03.md)
- [`2026-07-21-desktop-lan-webui-architecture-recalibration.md`](../compose/distilled/2026-07-21-architecture-recalibration.md)(原 compose/plans 副本已归档,见 archive INDEX)

## Decision

`ApplicationBootstrap` owns application-service construction. For each live
`LibrarySession`, `ApplicationBootstrap.runtime_for(session)` creates and
caches one `LibraryRuntime` with one eager, frozen `LibraryScopedServices`
snapshot object. The snapshot eagerly owns the Desktop/shared session,
Metadata, Tag, Thumbnail, FileOperation, Undo, Plugin and AssetIndex fields. A
private holder inside that same snapshot materializes one frozen
`LanRuntimeServices` projection (Asset, Project and Search) only when LAN is
composed. This projection is not a second Runtime or a second application
composition root.

`LibraryService` acquires a per-library Qt `QLockFile` before opening the
database. The lock name is derived from the normalized library root and lives
under `RuntimeData/Shared`; different libraries remain parallelizable, while a
second process opening the same library is rejected. Same-process service
objects share the underlying lock lease for compatibility with existing
session-identity tests.

`ApplicationBootstrap` also creates and owns one frozen
`RuntimeSharingServices` bundle per live Runtime/session. It generates one
non-persisted `token_secret`, constructs `AuthService` and `ShareService` with
the same session DB connection and secret, and idempotently initializes the
Auth/Share tables during Runtime creation inside the session operation lease.
LAN stop/start reuses this bundle; session close makes its secret and tokens
invalid. Different libraries have different sessions, connections, Runtime
bundles, secrets and databases. LAN UI API tokens do not use the Runtime secret directly: LAN derives `local_ui_auth_secret` from it plus `access_key/password/auth_mode`; unchanged stop/start is stable, while auth configuration changes invalidate old tokens. The public `LanServer.token_secret` is only a compatibility alias; `runtime_token_secret` names the Runtime-owned value.

`LanServer` receives the `LibraryRuntime`, prefers its canonical
`services_snapshot`, and performs the complete LAN projection inside one
session operation lease. It materializes the snapshot's LAN-only bundle,
validates common, LAN-only and sharing provider/session/cache identity, and
atomically publishes one `LanScopedServices` bundle before route registration.
It consumes Runtime-owned Auth/Share services and never constructs a second
LAN-owned pair. A temporary `.services` fallback exists only for legacy
runtime-shaped test doubles when `services_snapshot` is statically absent; a
present snapshot that returns `None` or raises never falls back.
`LanScopedServices.runtime_services` continues to reference the canonical
`LibraryScopedServices` snapshot. The LAN route helper
`get_services(request)` remains a direct lookup of `lan.services`; it never
constructs or caches application services. Missing composition fails loudly.

## Lifecycle and teardown

LAN-only materialization is generation-based single-flight. A successful result is cached permanently; one failed generation invokes the factory once and is observed by every waiter, while a later caller may retry. Recursive access fails explicitly. Construction and final LAN publication are protected by `LibrarySession.operation()` plus an atomic publication gate, so close either follows a completed publication or prevents the result from being published. Closing a Runtime that never materialized the LAN bundle must not create it for cleanup; the current Asset/Project/Search services own no closeable resources.

LAN server stop closes websocket/site and scanner resources when supported. It
does not close an injected `LibraryRuntime`, `LibrarySession`, or database
connection. Runtime
adapters and the database connection are intended to be closed by the
`ApplicationBootstrap`/`LibraryService` session lifecycle, with adapters
stopped before the session releases caches or the database connection. The required order is `session._begin_close()` → closing listeners and `Runtime.close_adapters()` (LAN stop) → operation drain → session-close listeners and `Runtime.close()` → database close. The
library lock is released only after that close path commits; initialization or
failure paths release the newly acquired lock, while close failures retain the
lock for a later retry path.
The current implementation covers the explicit pre-close barrier, retryable
failure semantics, restart-generation ownership and the Windows cross-surface
acceptance matrix. The Linux directory-symlink gate passed in Ubuntu WSL, so
this ADR records the delivered architecture for the recalibrated scope.

## Public construction boundary

The instance-level `asset_service`, `project_service`, and `search_service` accessors remain compatibility read-throughs to the same `lan_services` object. A3 does not preserve the previous dataclass constructor signature or reflection shape for those fields; callers must consume a Runtime snapshot rather than constructing `LibraryScopedServices` directly.

`LanServer`, `ShareManager`, and desktop LAN sharing accept a canonical
`LibraryRuntime` on the primary production path. The route-level raw
connection assembly has been removed. Task D also removed the
`ApplicationBootstrap.for_library()` and `cleanup_library()` composition
helpers, and the browser bearer-token compatibility state is no longer part of
the WebUI contract. The recalibration report records the completed lifecycle
and cross-surface acceptance evidence; no release gate remains open for that
scope, and there is no second Runtime composition path.

## Rejected alternative

Raw LAN service construction in route helpers is rejected. It duplicates
application ownership, can bind services to the wrong connection/session, and
delays configuration errors until the first request.

Desktop share creation is the direct `ShareCreationTask` → Runtime
`ShareService` path and does not require a running LAN server. LAN HTTP
management remains available through `/api/shares/*`, and remote links remain
under `/s/{id}`. The endpoint and generated-link scheme is `http://` unless
both certificate and key are configured, in which case it is `https://`.
