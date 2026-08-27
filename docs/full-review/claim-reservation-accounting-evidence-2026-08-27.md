# Share-Claim Reservation Accounting Evidence (2026-08-27)

## Scope
Finding `CLAIM-ATOMICITY-44-01`: the claim brute-force gate was check-then-record; concurrent POSTs could all pass the check and exceed the 10-per-300s window before failures were recorded.

## Change
`delivery.py` switches to reservation-based accounting. A module `threading.Lock` guards `_claim_failures`; each admitted POST reserves one timestamped slot *before* body parsing and the service call, a `429` consumes no extra slot, and only a successful claim clears the identity's bucket. Malformed or empty bodies now spend their reserved slot (gate counts attempts), pinned by regression.

## Verification
- Focused share-claim + delivery-isolation + commerce-routes matrix: **36 passed**.
- New threaded regression (25 concurrent failing claims through the real middleware): ≤ 10 receive 404, the remainder exactly 429, total accounted. Final-state subset re-run after line-budget slimming: **18 passed, 78 deselected**.

## Boundaries
Status is `fixed-unverified`. State remains single-process in-memory; concurrent accounting beyond one process, an exact FIFO fairness order among racing threads, and production traffic are not claimed.
