# Claim Cap LRU Refresh Evidence (2026-08-27)

## Scope
Finding `CLAIM-INSERTION-ORDER-56-01`: the share-claim capacity eviction keyed on dict insertion order, but `setdefault` never refreshed an existing identity's position — so the earliest-inserted identity (even if still actively failing) was the first evicted at capacity.

## Change
`delivery._reserve_claim_attempt` now removes and re-inserts the identity on every admitted attempt, making insertion order an approximate LRU: refreshing an active identity moves it to the newest slot, and capacity eviction drops the longest-idle identity. Budget/slot counting and the over-budget rejection path are unchanged.

## Verification
New regression `test_claim_active_identity_refresh_is_lru_preserved` (cap=3, refresh id-0, insert id-3 → idle id-1 evicted, refreshed id-0 survives). Claim + delivery-isolation + line-budget gates: **97 passed**; `delivery.py` trimmed back to the 350-line budget. Final serial suite **4117 passed, 16 skipped, 20 deselected, 2 warnings**.

## Boundaries
Status `fixed-unverified`. LRU is approximate (dict insertion order), not a timestamp-precise policy; the map remains single-process in-memory.