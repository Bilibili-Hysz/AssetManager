# Quota Preflight Fast-Deny Evidence (2026-08-27)

## Scope
Finding `QUOTA-PREFLIGHT-FAST-DENY-48-01`: exhausted identities still paid for size estimation, full file reads, and ZIP creation before the authoritative consume rejected them.

## Change
`downloads.py` gains `_preflight_exhausted_response(request)` — a read-only `info()` gate. Any store failure or a non-exhausted verdict keeps the legacy flow untouched; only `enabled && remaining==0` short-circuits with the canonical exhausted 429 (identity cookie attached). Insert points: single-file after successful read (missing files still 404 without touching quota), directory and batch immediately before `mkstemp` so denied requests create zero temp files. Interval rate-limiting is deliberately not predicted here.

## Verification
Finding ID for this batch: `QUOTA-PREFLIGHT-FAST-DENY-48-01`.
Focused quota matrix: **28 passed** including three new deny regressions asserting no `mkstemp` artifact, no consume invocation, byte-identical legacy fallback when `info()` raises, plus full existing 429/ZIP-cleanup suites.

Final serial suite: **4112 passed, 16 skipped, 20 deselected, 2 warnings**, exit 0.

## Boundaries
Status is `fixed-unverified`. This closes resource amplification, not authorization: a racing writer could still let one over-budget request slip through preflight (the post-preparation consume remains authoritative). No refund/reservation model, no production soak.
