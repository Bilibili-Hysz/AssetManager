# ADR 0003: Library Runtime Ownership and LAN Composition

## Status

Accepted target decision; the Windows implementation, cross-surface acceptance
and Linux directory-symlink platform gate are evidenced. The current-state
report and recalibration report are authoritative:

- [`desktop-lan-webui-architecture-migration.md`](../compose/reports/desktop-lan-webui-architecture-migration.md)
- [`desktop-lan-webui-architecture-recalibration.md`](../compose/reports/desktop-lan-webui-architecture-recalibration.md)
- [`2026-07-21-desktop-lan-webui-architecture-recalibration.md`](../compose/plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md)

## Decision

`ApplicationBootstrap` owns application-service construction. For each live
`LibrarySession`, `ApplicationBootstrap.runtime_for(session)` creates and
caches one `LibraryRuntime` with one eager `LibraryScopedServices` bundle.
The runtime is the ownership boundary for services that are scoped to a
library and its connection provider.

`LanServer` receives the `LibraryRuntime`, validates that it is live and
canonical for its session, and eagerly attaches a `LanScopedServices` bundle
before route registration. The LAN route helper `get_services(request)` is a
direct lookup of `lan.services`; it never constructs, caches, or silently
falls back to application services. Missing runtime/service composition fails
loudly.

## Lifecycle and teardown

LAN server stop closes websocket/site and scanner resources when supported. It
does not close an injected `LibraryRuntime` or `LibrarySession`. Runtime
adapters and the database connection are intended to be closed by the
`ApplicationBootstrap`/`LibraryService` session lifecycle, with adapters
stopped before the session releases caches or the database connection. The
current implementation covers the explicit pre-close barrier, retryable
failure semantics, restart-generation ownership and the Windows cross-surface
acceptance matrix. The Linux directory-symlink gate passed in Ubuntu WSL, so
this ADR records the delivered architecture for the recalibrated scope.

## Public construction boundary

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
