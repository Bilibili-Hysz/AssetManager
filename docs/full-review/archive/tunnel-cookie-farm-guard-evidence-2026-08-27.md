# Tunnel Visitor-Cookie Farming Guard Evidence (2026-08-27)

## Scope
Finding `TUNNEL-COOKIE-FARM-43-01`: under the tunnel limiter, every middleware-rejected answer (blacklist/whitelist 403, general/browse/auth_strict 429) previously carried a freshly minted `am_quota_id`, letting a denied client farm identities from failed attempts and later enter isolated `tunnel:<id>` buckets.

## Change
`security.py` now attaches the minted cookie only to successful handler responses; rejection paths return bare error responses and discard the candidate token. The docstring contract states this explicitly.

## Verification
- Focused tunnel + anonymous-quota subset: **12 passed, 230 deselected**, plus final-state isolation-file re-run: **13 passed** (shared artifact log).
- Updated regressions assert tampered-cookie 429, exhausted-shared-bucket 429, auth_strict lockout 429, and blacklist 403 all carry no new identity cookie; the first successful cookieless response still mints.

## Boundaries
Status is `fixed-unverified`. This closes the zero-cost farming path only; an attacker with many real browsers/devices still obtains legitimate per-device buckets. No Cloudflare edge E2E, soak, or distributed test was performed.
