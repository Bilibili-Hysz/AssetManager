# Tunnel/Quota Identity Parity and Assembly Contract Evidence (2026-08-27)

## Scope
Coverage-only batch closing two long-recorded test gaps: the quota↔tunnel visitor-cookie trust (same name, shared secret precedence incl. random fallback, identical client-id extraction) had zero pinned tests, and production `_LanServerImpl._build_app` wiring was always mocked.

## Change
No production bytes. Two new test modules:
- `test_tunnel_quota_identity_parity.py` — name/format equality, secret equality on configured and bare lan objects (shared `_quota_cookie_secret` fallback), bidirectional token validation via each module's validator plus client-id agreement.
- `test_server_assembly_contract.py` — drives the real `_build_app` on a skeleton impl: LAN_APP_KEY identity, ZIP executor app-key injection, security middleware first in the chain, production resolver decoding a quota-minted cookie, production minter producing tokens accepted by the quota validator.

## Verification
Finding ID for this batch: `TUNNEL-QUOTA-PARITY-ASSEMBLY-51-01`.
Parity + assembly + tunnel-isolation focused run: **14 passed**. Final serial suite: **4112 passed, 16 skipped, 20 deselected, 2 warnings**, exit 0. README doc-stats converged to `python_test_files=283` via the governed fix path.

## Boundaries
Status is `fixed-unverified` at loopback-mock depth: no cloudflared tunnel process, no Cloudflare edge TLS, no live browser — the contract pins code-level trust, not production network behavior.
