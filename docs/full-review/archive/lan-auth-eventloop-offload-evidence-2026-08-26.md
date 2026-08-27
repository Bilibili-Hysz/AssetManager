# LAN Auth Event-Loop Offload Evidence (2026-08-26)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `lan-auth-eventloop-offload-evidence-2026-08-26` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded login/register/share-password offload batch |
| Baseline status SHA-256 | `9de2ecc3df68345e44cf0bafccba328ac0086fa1fefe8ed8e8088c3c7d9b5feb` |
| Baseline diff SHA-256 | `ba233751b7455f41123a184988ac293a4e5784ead9f9078ed8013a7864d95ad7` |
| Baseline tracked / untracked entries | `163 / 155` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot moves the remaining synchronous PBKDF2-heavy LAN calls off the event loop, closing the confirmed P1 responsiveness gap. The machine-readable companion is [audit-manifest-lan-auth-eventloop-offload-evidence-2026-08-26.json](audit-manifest-lan-auth-eventloop-offload-evidence-2026-08-26.json).

## Implemented contract

Five call sites now run through `await asyncio.to_thread(...)`, mirroring the access-key precedent in the same file:

- `routes/auth.py` user-mode login (`authenticate_user`: DB lookup + PBKDF2-600k verify + optional legacy cost re-hash);
- `routes/auth.py` password-mode login (`verify_password`);
- `routes/auth.py` registration (`register_user` with its 600k hash) and the immediate follow-up verification — up to two full hashes per registration;
- `routes/shares.py` share-password verification (`ShareService.verify_password`, full PBKDF2 on both failure and success paths).

Deliberately unchanged: the brute-force gate, failure recording, and success reset around share verification (cheap, lock-guarded, order-sensitive); cookie issuance and activity logging; and `_auth_middleware`'s per-request `verify_user_token` (5-second cache hit path is HMAC-cheap — a per-request thread hop would cost more than it saves; recorded as residual). Thread-safety basis from the read-only audit: the shared SQLite connection is designed for cross-thread use (`locked_read`/`db_write_lock`), service singletons guard mutable state with locks, and `session_operation` leases are thread-safe.

## Verification

### Focused matrices

```text
python -m pytest -n 0 -q tests/lan/test_login_share_verify_offload.py tests/lan/test_websocket_auth_offload.py tests/lan/test_l2_rate_input_cpu.py
```

Result: **18 passed**, exit code 0. Raw output: `focused-offload.stdout.log`.

```text
python -m pytest -n 0 -q tests/lan/test_lan_api.py -k "login or register or verify or share_verify or lockout"
```

Result: **25 passed, 211 deselected**, exit code 0. Raw output: `focused-behavior.stdout.log`. The existing behavioral net (status codes, cookies, expired-share 410, brute-force lockout 4×401→429 with Retry-After, success reset, per-share isolation) passes through real PBKDF2 on the awaited paths.

New regressions use a parked-recording fake: the fake `to_thread` records `(function, args, kwargs)`, sets a started event, and parks until released; a bystander task ticks only after that signal. A synchronous regression fails fast on an empty call list (deterministic, no hang), while the passing path proves the loop stayed schedulable with zero sleeps. Four tests pin password-mode login, user-mode login, register (both offloaded steps plus kwargs), and share verification (single offloaded call with blocked→verify→reset ordering preserved on-loop).

### Full Python suite

```text
python -m pytest -n 0 -q
```

Result: **4073 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0, 609.83 seconds. Raw output: `full.stdout.log`. README's governed `python_test_files` statistic was updated 278→279 for the new test module (doc-stats gate verified after the update). Skips remain capability/platform-gated; warnings pre-existing.

### Static and repository gates

Targeted Ruff, full Ruff, targeted compileall, full compileall, `git diff --check`, and the six governance scripts all exited 0. The independent audit-manifest validator runs after this report/manifest/index are written; its result is retained separately.

## Finding and boundaries

- `LAN-AUTH-EVENTLOOP-OFFLOAD-37-01` is **fixed-unverified**: call-routing regressions plus the behavioral net pass on Windows. No wall-clock latency benchmark, no production E2E, and no load test were executed.
- Residuals recorded: per-request user-token verification and `_has_active_users` remain synchronous by design (cache-hit fast paths); `_record_activity` stays on-loop; `handle_register` invite/duplicate DB statements are covered only as part of the whole-function offload.
- The frozen `DeepSeek Docs/` directory and ignored `.worktrees/grid-zoom-interpolation-fix` directory were not modified. No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
