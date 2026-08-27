# Plugin Preference Cross-Process Advisory Lock Evidence (2026-08-27)

## Scope
Finding `PREFS-CROSSPROC-LOCK-55-01`: batch 49 gave same-path bags an in-process path lock plus a re-read/merge on save, and its report honestly noted the boundary that "cross-process writers need an OS-level lock in the preferences layer" — this batch closes that boundary with a best-effort advisory lock.

## Change
`preferences.py` adds `_AdvisoryLock`: a sidecar `<target>.preflock` taken with a non-blocking exclusive lock (Windows `msvcrt.locking(LK_NBLCK)`, POSIX `fcntl.flock(LOCK_EX|LOCK_NB)`), bounded short retries with backoff, released immediately after the read-merge-replace window. Lock files are intentionally retained (same keep-marker convention as library locks); unsupported platforms or failed acquisition silently degrade to the unlocked behavior. Module stays stdlib-only (no Qt).

## Verification
Same-process plugin matrices stay green (concurrent four-bag barrier regression intact); the existing "only the two legitimate bag JSON files exist" assertion now filters `*.json` because sidecars are lock artifacts, not preference data. New true cross-process regression spawns two real Python children, each with its own bag writing a distinct key under an artifically widened window → final JSON contains both keys. Final serial suite **4117 passed, 16 skipped, 20 deselected, 2 warnings**.

## Boundaries
Status `fixed-unverified`. This is best-effort mutual exclusion, not a strong cross-process guarantee: if both writers contend the whole window, last-writer-wins may still drop a key; no exactly-once or crash-recovery semantics are claimed.