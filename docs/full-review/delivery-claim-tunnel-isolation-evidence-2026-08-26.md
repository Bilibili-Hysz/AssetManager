# Delivery Claim Tunnel Identity Isolation Evidence (2026-08-26)

## Scope
Finding `DELIVERY-CLAIM-TUNNEL-ISOLATION-40-01` covered share-claim brute-force failures still keyed by `request.remote`, collapsing all cloudflared visitors into loopback.

## Changes
- Security middleware publishes its final bucket key on the request.
- Delivery claim limiting reuses that key: valid tunnel visitor cookies use `tunnel:<client_id>`; cookieless or invalid-cookie requests retain the shared normalized peer fallback; direct mode remains IP-scoped.
- IP blacklist/whitelist decisions remain based on the actual peer address and no forwarded headers are trusted.

## Verification
- Claim/tunnel isolation plus existing claim and tunnel matrices: **15 passed**.
- Final serial Python suite: **4089 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0.
- Full Ruff, compileall, diff-check, and repository governance gates passed.

## Boundaries
Status is `fixed-unverified`: no real cloudflared/Cloudflare edge test, distributed multi-process test, token-farming mitigation, or claim check-then-record atomicity proof was performed. Cookieless clients intentionally share the fallback bucket.
