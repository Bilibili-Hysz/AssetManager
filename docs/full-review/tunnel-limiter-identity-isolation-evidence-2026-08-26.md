# Tunnel Limiter Identity Isolation Evidence (2026-08-26)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `tunnel-limiter-identity-isolation-evidence-2026-08-26` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded tunnel-mode rate-limit identity isolation batch |
| Baseline status SHA-256 | `7df18e0e7435d8672845d8a0f16d485c1bc6f43f9b8b01b3a5fd8325acb1b494` |
| Baseline diff SHA-256 | `0f6cfe7154ea2978b8d14e6ea7165b80a23fa7d1689ccbcc02e710b85adcb2d3` |
| Baseline tracked / untracked entries | `160 / 150` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records per-client rate-limit isolation for cloudflared tunnel visitors, closing the confirmed P1 where all tunneled users shared one loopback bucket (ten failed logins locked out every tunneled user for five minutes). The machine-readable companion is [audit-manifest-tunnel-limiter-identity-isolation-evidence-2026-08-26.json](audit-manifest-tunnel-limiter-identity-isolation-evidence-2026-08-26.json).

## Implemented contract

- New dependency-free leaf module `AssetsManager/lan/tunnel_identity.py` mirrors the quota module's signed anonymous cookie primitives: same cookie name (`am_quota_id`), token format `v1.<32 hex>.<HMAC-SHA256>`, constant-time verification, and identical secret precedence (`local_ui_auth_secret` → `token_secret` → random fallback cached on the shared `_quota_cookie_secret` attribute), so cookies issued by either side verify in both.
- `create_security_middleware()` gains two optional injected callables: `tunnel_identity_resolver(request)` (validated cookie client id or None) and `tunnel_identity_minter()` (fresh `(client_id, cookie_token)` pair). When `tunnel_active()` is true and the normalized peer is loopback — the same double condition the codebase already trusts for the whitelist bypass — the three limiter tiers and the `X-RateLimit-Remaining` header key on `tunnel:<client_id>` instead of the shared loopback IP.
- A request with no valid cookie deliberately stays in the shared loopback bucket: a freshly minted identity never buys immediate isolation, otherwise an attacker could rotate buckets per request to evade limiting entirely. The minted cookie is attached to the response (HttpOnly, SameSite=Lax, path=/, 30 days) so the next request isolates. Tampered cookies are treated as cookieless. Blacklist and whitelist checks remain keyed on the real peer address.
- `_LanServerImpl._build_app()` wires both closures in production; direct LAN traffic is byte-identical to before because the gate requires tunnel-active plus loopback.
- No forwarded headers (`Cf-Connecting-Ip`, XFF) are read anywhere, preserving the repository's zero-header-trust posture. README's governed `python_test_files` statistic was updated 277→278 for the new test module.

## Verification

### Focused matrices

```text
python -m pytest -n 0 -q tests/lan/test_tunnel_rate_limit_isolation.py tests/lan/test_low_batch_security.py
```

Result: **21 passed**, exit code 0.

```text
python -m pytest -n 0 -q tests/lan/test_tunnel_rate_limit_isolation.py tests/lan/test_low_batch_security.py tests/lan/test_l2_rate_input_cpu.py tests/lan/test_route_policy_contract.py tests/lan/test_free_download_quota.py tests/lan/test_tunnel_security.py tests/lan/test_tunnel_unit.py
```

Result: **76 passed**, exit code 0. Raw output: `artifacts/evidence/2026-08-26/tunnel-limiter-isolation/focused.stdout.log`.

The new regressions pin: bucket isolation between two valid-cookie clients sharing peer 127.0.0.1 (including diverging `X-RateLimit-Remaining`); shared-bucket degradation plus minted-cookie issuance for first-contact requests; tampered-cookie fallback without errors; byte-identical IP keying when the tunnel is off; and per-identity auth_strict lockout through a routed login policy.

### Full Python suite

Two runs are recorded honestly:

1. First run (**4063 passed**, exit 0) executed before a cosmetic test-helper cleanup (removing one unused local); it is archived at `full-first-run.stdout.log`.
2. Final run on the shipped state: **4063 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0, 688.33 seconds. Raw output: `full.stdout.log`.

Skips remain capability/platform-gated; the two warnings are the pre-existing Qt signal disconnect and duplicate ZIP member warnings.

### Static and repository gates

Targeted Ruff (one unused-variable finding in the new test was fixed and rerun clean), full Ruff, targeted compileall, full compileall, `git diff --check`, and the six governance scripts all exited 0 after the README statistic update; outputs live under `artifacts/evidence/2026-08-26/tunnel-limiter-isolation/`. The independent audit-manifest validator runs after this report/manifest/index are written and its result is retained separately.

## Finding and boundaries

- `TUNNEL-LIMITER-IDENTITY-ISOLATION-35-01` is **fixed-unverified**. Focused matrices and the final full serial suite pass on Windows. Status remains conservative: no production cloudflared E2E run was performed (mocked loopback peers prove the middleware contract, not Cloudflare edge behavior), and no multi-process/shared-state limiting exists.

Explicitly remaining / not claimed:

- Distributed brute force across many distinct cookies still exhausts the limiter LRU/memory budget by design; isolation prevents collateral lockout, not volumetric attack.
- Cookieless clients (curl without jar) intentionally keep sharing the loopback bucket under tunnel mode.
- `shop/delivery.py`'s claim-failure map still collapses tunnel identities; unchanged in this batch.
- No power-loss/exactly-once/cross-system atomicity claims; no dependency/CVE/release/clean-checkout verification; no production CDN/TLS/browser intermediary behavior claims.

The frozen `DeepSeek Docs/` directory and ignored `.worktrees/grid-zoom-interpolation-fix` directory were not modified. No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
