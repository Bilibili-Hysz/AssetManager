# ADR 0003: Library Runtime Ownership and LAN Composition

## Status

Accepted — Phase 5 Task 17.

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
adapters and the database connection are closed by the
`ApplicationBootstrap`/`LibraryService` session lifecycle, after the LAN
server has stopped, preventing routes or background work from using a closed
session.

## Public construction boundary

`LanServer`, `ShareManager`, and desktop LAN sharing accept only a canonical
`LibraryRuntime`. The removed migration factories and request-user dictionary
adapters are not compatibility boundaries. Tests that need low-level route
fixtures must build a runtime-shaped session fixture explicitly; production
code never assembles LAN application services from raw connections.

## Rejected alternative

Raw LAN service construction in route helpers is rejected. It duplicates
application ownership, can bind services to the wrong connection/session, and
delays configuration errors until the first request.
