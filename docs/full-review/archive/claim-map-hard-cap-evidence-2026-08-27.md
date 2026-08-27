# Claim Failure Map Hard Cap Evidence (2026-08-27)

## Scope
Finding `CLAIM-MAP-CAP-45-01`: `_claim_failures` had no key-count bound, so unique identities within an active window could grow the dict without limit while the per-record sweep stayed O(N).

## Change
The same reservation lock enforces `_CLAIM_MAX_ACTIVE_KEYS = 5000`. On insert at capacity, the oldest-inserted key is evicted. Per-window expiry pruning is unchanged and now operates on a bounded map.

## Verification
- Regression drives the cap down via monkeypatch (50 keys) and verifies size stays ≤ 50, earliest identities are evicted first (insertion-order policy), and the newest reservation survives. Included in the final-state claim matrix (**18 passed, 78 deselected**).

## Boundaries
Status is `fixed-unverified`. Eviction is insertion-order approximation, not exact LRU; long-lived windows can still hold up to the cap simultaneously, and cross-process memory is out of scope by design.
