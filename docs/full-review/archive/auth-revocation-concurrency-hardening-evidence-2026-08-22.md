# Auth Revocation 并发与跨进程一致性 Hardening 证据（2026-08-22）

## 1. Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `auth-revocation-concurrency-hardening-evidence-2026-08-22` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; baseline captured before this report and manifest were added |
| Baseline status SHA-256 | `3cbe4c5aea26f5329838203a32fec8da5f1ef15d8a0b4bd0145c5d401b7075cf` |
| Baseline diff SHA-256 | `67d25a237ddb87dcd3efc3dd3ae31560f793a1d967af9f5f73ce751b61155732` |
| Baseline tracked / untracked entries | `119 / 54` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This is an append-only dated snapshot. Earlier 2026-08-22 Auth/Plugin/WebSocket evidence remains unchanged. The machine-readable companion is [audit-manifest-auth-revocation-concurrency-hardening-evidence-2026-08-22.json](audit-manifest-auth-revocation-concurrency-hardening-evidence-2026-08-22.json).

## 2. Finding convergence

### `P1-10` / `EVID-02` — durable revocation is now concurrency-aware

The registry now protects `_revoked_tokens` and `_revoked_loaded` while allowing synchronous database work to run outside the state lock. Initial durable loading is serialized, failed loads remain retryable, and positive-cache eviction does not make a durable revocation disappear because a cache miss performs a durable lookup (`AssetsManager/lan/token_revocations.py:38-165`).

The middleware preserves revocation checks for legacy hosts that expose an in-memory revoked-token table while avoiding an unnecessary worker hop for hosts with no revocation capability (`AssetsManager/lan/server.py:1542-1556`, `AssetsManager/lan/server.py:1619-1634`).

### `P1-10` — transaction and schema lifecycle

The revocation repository lazily creates its table under a schema lock and savepoint. `add()` and `prune_expired()` do not commit a caller-owned transaction (`AssetsManager/repositories/revoked_token_repository.py:20-62`, `AssetsManager/repositories/revoked_token_repository.py:63-118`). AuthService lazy repository creation is also synchronized (`AssetsManager/application/auth_service.py:300-327`).

### `XAUTH-01` / `EVID-02` — logout and existing WebSockets

Logout durable work remains off the event loop, evicts matching existing WebSockets, and clears the authentication cookie even when durable persistence returns the retryable 503 contract (`AssetsManager/lan/routes/auth.py:104-139`, `AssetsManager/lan/ws.py:467-486`).

## 3. Executed verification

### Focused regression

```text
python -m pytest -n 0 --basetemp=.zcode/pytest-auth-revocation-focused -q tests/lan/test_token_revocations.py tests/unit/test_revoked_token_repository.py tests/unit/test_auth_service_revocations.py tests/lan/test_l2_rate_input_cpu.py tests/lan/test_public_commerce_auth.py tests/lan/test_runtime_realtime.py tests/lan/test_websocket_auth_offload.py tests/lan/test_lan_api.py -k "auth or logout or share or websocket or revocation"
```

Result: **164 passed, 0 failed**, exit code 0, 16.70 seconds, 152 deselected.

The focused contract coverage includes concurrent first load, bounded positive cache with durable miss lookup, caller-owned transaction preservation, legacy in-memory middleware revocation, and logout cookie deletion on persistence failure (`tests/lan/test_token_revocations.py:43-147`, `tests/lan/test_l2_rate_input_cpu.py:123-180`).

### Full Python suite

```text
python -m pytest --basetemp=.zcode/pytest-revocation-full -n 0 -q
```

Result: **3912 passed, 12 skipped, 17 deselected, 0 failed, 2 warnings**, exit code 0, 611.54 seconds. Windows-limited skips include symlink/reparse privilege, POSIX flock, and nondeterministic process-termination cases. Existing warnings were the Qt signal disconnect warning and duplicate ZIP entry warning.

### Static and governance gates

The following commands all exited 0. Their stdout/stderr and baseline artifacts are stored under `artifacts/evidence/2026-08-22/auth-revocation-concurrency-final/`:

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

## 4. Status and remaining limits

This snapshot keeps the revocation finding status **`fixed-unverified`**. Local Windows evidence does not prove independent POSIX multi-process behavior, cross-process SQLite writer races under real deployment, power-loss recovery, or clean-checkout reproducibility.

The following remain separate deferred workstreams:

- descriptor-backed final-open/TOCTOU atomicity for downloads, shares, thumbnails, and ZIP consumers;
- plugin discovery/load concurrency and refresh of already-open UI filter controls;
- browser E2E, real-backend LAN acceptance, dependency/CVE scan, performance benchmarks, package/release execution, and independent Windows/POSIX platform validation.

No commit, push, release, revert, reset, clean, or worktree overwrite was performed.
