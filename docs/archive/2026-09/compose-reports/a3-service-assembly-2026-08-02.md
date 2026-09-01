---
feature: a3-service-assembly-2026-08-02
status: delivered
as_of: 2026-08-02
branch: master
base_commit: 4e2a3d7
code_commit: 7b9532d05c66b84f1526870ae349ff022f1b268a
remote: none configured
---

# A3 Service Assembly Closure — 2026-08-02

## 1. Outcome

A3 is delivered. Opening a Desktop library still creates one canonical `LibraryRuntime` and one frozen `LibraryScopedServices` snapshot, but it no longer constructs the LAN-only Asset, Project, or Search services. Those three services materialize once, on demand, from a private holder when a LAN server is composed.

This change does not implement B1. AuthService, ShareService, the random `token_secret`, Auth/Share table initialization, and Desktop direct share creation remain LAN-owned or future work.

## Postscript — B1 follow-up (2026-08-03)

The paragraph above is the historical A3 boundary as of 2026-08-02 and remains accurate for that A3 checkpoint. B1 was delivered subsequently in the current working tree: `ApplicationBootstrap` now owns the frozen `RuntimeSharingServices` bundle; LAN reuses its Auth/Share services and secret; and Desktop creates shares asynchronously through `ShareCreationTask` without requiring a running LAN server. The authoritative details are in [`b1-runtime-sharing-2026-08-03.md`](b1-runtime-sharing-2026-08-03.md).

The current B1-focused verification slice is `392 passed` when run with an external writable pytest base directory. This is focused evidence, not the final full-Python or Chromium release count; those gates remain separately tracked.

## 2. Reference matrix and plan calibration

The production reference scan found these Desktop dependencies:

- required: Metadata, Tag, Thumbnail, FileOperation, Undo, session and performance recorder;
- retained shared/stateless services: Plugin and AssetIndex;
- no Desktop production use: Asset, Project and Search;
- LAN-owned boundary: Auth and Share.

The original DeepSeek A3 plan proposed removing ThumbnailService from the Desktop package. That assumption is no longer valid: B2 changed ThumbnailLoader to consume the scoped ThumbnailService through the immutable Runtime snapshot. A3 therefore keeps Thumbnail eager and delays only Asset/Project/Search.

## 3. Final ownership model

```text
ApplicationBootstrap.runtime_for(session)
  -> LibraryRuntime                         # one per canonical live session
     -> services / services_snapshot        # same frozen object
        -> LibraryScopedServices            # eager object
           -> eager Desktop/shared fields
              session, Metadata, Tag, Thumbnail, FileOperation, Undo,
              Plugin, AssetIndex, PerformanceRecorder
           -> private single-flight holder
              -> LanRuntimeServices         # materialized only for LAN
                 Asset, Project, Search

_LanServerImpl(runtime)
  -> canonical services_snapshot
  -> common services + one LanRuntimeServices instance
  -> LAN-owned Auth/Share/activity/presence
  -> one eagerly attached LanScopedServices route projection
```

There is no second Runtime, no route-level application-service factory, and no LAN-owned duplicate of the common services.

## 4. Concurrency and lifecycle contract

The lazy holder uses a `Condition`, generation identity and builder-thread identity:

1. a successful generation publishes one immutable `LanRuntimeServices` value permanently;
2. one failed generation invokes the factory once, and every waiter that joined that generation observes that failure;
3. a later caller may start one new generation; failure does not poison the Runtime;
4. recursive access fails explicitly instead of deadlocking;
5. construction runs inside `LibrarySession.operation()`;
6. publication is atomic against session close; if close wins, no lazy value or partial LAN binding is published;
7. closing an unmaterialized Runtime does not construct LAN services for cleanup.

`LibrarySession._closed` is excluded from compare/hash semantics, so session and snapshot hashes remain stable across close. The lazy holder is excluded from snapshot repr/equality/hash.

## 5. Canonical LAN composition and compatibility

- `services_snapshot` always wins when present. A present getter returning `None` or raising is rejected and never falls back.
- `.services` fallback is limited to legacy runtime-shaped test doubles where `services_snapshot` is statically absent. Its deletion condition is migration of those fixtures to the canonical contract.
- Canonical Metadata, Tag, Thumbnail, Project and Project-internal services must bind the exact Runtime session. Search must bind the same provider; Asset DirectoryCache must hold the same DB connection.
- The eager and lazy packages reuse the exact same bound `session.connection_for` object, preserving the established provider identity contract.
- Instance reads through `snapshot.asset_service`, `project_service`, and `search_service` remain compatible and return the fields of the same lazy bundle.
- The former dataclass constructor signature, positional order, `dataclasses.fields()`, `asdict()`, `replace()`, `__match_args__`, repr and equality shape for those three former fields are not compatibility guarantees.

## 6. Changed files

- `AssetsManager/application/bootstrap.py` — eager snapshot, lazy bundle, single-flight holder and provider capture.
- `AssetsManager/application/context.py` — atomic session-bound publication and stable lifecycle hash semantics.
- `AssetsManager/application/__init__.py` — exports `LanRuntimeServices`.
- `AssetsManager/lan/server.py` — strict snapshot selection, leased composition, deep binding validation and atomic final projection.
- `tests/unit/test_bootstrap.py` — lazy construction, two-generation concurrency, retry, recursion, close race, identity and hash/value semantics.
- `tests/lan/test_lan_api.py` — snapshot preference/fallback, provider/session/cache identity, B1 boundary and final server publication race.
- `tests/unit/test_architecture_boundaries.py` — Bootstrap-only LAN application-service assembly and no LAN reassembly.

## 7. Verification

| Gate | Result |
|---|---|
| A3 Bootstrap/Runtime/LAN/architecture focused matrix | `347 passed` |
| Task D Runtime/Desktop matrix | `431 passed` |
| Current Desktop/LAN/Chromium matrix | `190 passed` |
| Full Python suite | `1695 passed, 1 skipped` |
| Windows platform skip | directory symlink unavailable; existing Ubuntu WSL gate is `1 passed, 23 deselected` |
| Ruff on changed production/tests | passed |
| py_compile / compileall | passed |
| `git diff --check` | passed |

The browser, Windows spawn lifecycle and recycle-bin gates were run outside the restricted sandbox with an explicit external `--basetemp`; their sandbox failures were reproduced as environment restrictions and then passed in the unrestricted gate.

## 8. Independent review

Two review rounds were required. The first rejected a simple lazy-cache design and required generation-based failure sharing, operation leases, strict snapshot fallback, frozen-dataclass isolation and deep provider validation. The second found unstable snapshot hashing and canonical `_session=None` acceptance; both were fixed. A final pass required a test that reached the server publication window after LAN services were already materialized. After that test and the provider-identity compatibility fix, the final review reported:

- P0: none
- P1: none
- P2: none
- P3: none
- decision: Go

## 9. Task state and next entry

A1, A2 and A3 are delivered as independent service-boundary checkpoints. The next service-boundary task is B1, which must be planned separately around Runtime-owned Auth/Share, a shared `token_secret`, table lifetime and Desktop direct calls. B1 must not introduce a second Runtime or undo A3 service identity and close-order contracts.
