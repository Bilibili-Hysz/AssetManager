# Evidence Register v2 (2026-08-25)

## 1. Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `evidence-register-v2-evidence-2026-08-25` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; global evidence register refresh and bounded promotion batch |
| Baseline status SHA-256 | `e3260f5172f464d7910347496d398a1c73dd968ef65496689b821a7eced0a1a6` |
| Baseline diff SHA-256 | `5887d69622b6115fa89530f06226dd0783f539b81c0b3b19c09def44b6fcc7f0` |
| Baseline tracked / untracked entries | `145 / 135` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This is a new dated register snapshot. It does not rewrite any historical report or manifest; all corrections below are recorded here as the canonical errata/supersession layer going forward. The machine-readable companion is [audit-manifest-evidence-register-v2-evidence-2026-08-25.json](audit-manifest-evidence-register-v2-evidence-2026-08-25.json).

## 2. Census

Across 53 valid manifests: **109 unique finding IDs, 121 records** — 1 verified-fixed, 101 fixed-unverified, 10 confirmed, 3 conditional (pre-batch). Severity: 113 P1 records, 8 P2 records. No finding uses `superseded`; supersession lives in manifest-level relations.

Domain census: C-series reconciliation/min fixes 50; Thumbnail chain 23; Import hardening 10 (+ this batch's promotions); Desktop/LAN/final-open/recovery/reparse 8; Auth/WS revocation 5; Plugin/ProjectService 5; EVID baseline declarations 13 (with overlaps).

## 3. Batch promotion (register rule applied)

The Canonical Register requires a later manifest carrying command/result artifacts for promotion to `verified-fixed`. Seven findings from the 2026-08-23→25 chain satisfy it: each has a focused matrix command **and** a full serial suite command with exit code 0 recorded in a later-or-capture manifest, and every anchor line remains within current file bounds. This manifest re-registers them as `verified-fixed`, keeping their original boundary language intact:

| ID | Note |
|---|---|
| IMPORT-COPY-NO-OVERWRITE-28A-01 | Fact-chain exemption: its own full-suite run was red solely due to the unrelated transaction-boundary failure that batch 29 later fixed and verified; six subsequent full-suite runs (4021→4043 passed) include its contract tests green. |
| IMPORT-ANCESTOR-LINK-ADMISSION-28B-01 | — |
| IMPORT-COPY-REPLAY-IDEMPOTENCY-28C-01 | — |
| IMPORT-FSQ-COMPENSATION-28D-01 | — |
| IMPORT-SOURCE-CONSISTENCY-28E-01 | — |
| RECOVERY-MIDPHASE-KILL-29C-01 | — |
| REPARSE-DETECTION-CONSISTENCY-30C-01 | — |

Promotion scope qualifier: verification is single-platform (Windows host) with capability-gated POSIX skips; boundary statements in each original report remain binding. Older C-series/thumbnail/auth IDs keep `fixed-unverified` in this pass — many have regression/hardening artifacts and are candidates for a future bulk review, but per-ID anchor revalidation was not performed here.

## 4. EVID takeover registration (explicit)

The baseline manifest records EVID-01/02/07/08 as `confirmed` and EVID-09/10 as `conditional`; later implementation manifests record the same IDs as `fixed-unverified`. Current truth: those six were taken over by their fix batches — treat the later status as authoritative; the baseline entries are capture-point history. Remaining without any fix declaration: EVID-03/04/05/06/11/12 (`confirmed`) and EVID-13 (`conditional`); they stay open work items.

## 5. Errata / supersession pointers (append-only corrections)

Per the append-only convention these are recorded here rather than by editing history:

1. "Full-suite transaction-boundary failure remains open" (import-no-overwrite-atomic-copy report): resolved by batch 29 (`BATCH-MOVE-TRANSACTION-BOUNDARY-29-01`, verified-fixed, full suite 4018 passed).
2. "Fingerprint-to-copy TOCTOU remains open" (import-hardening-convergence §4; also listed unqualified in 28-C/28-D boundaries): narrowed by `IMPORT-SOURCE-CONSISTENCY-28E-01` handle-level guard; residual = same-size in-place rewrites within mtime granularity plus cross-platform zero-race proof.
3. "recover() mid-phase windows only monkeypatch-level" (28-D report; convergence §4): elevated to real subprocess kills by `RECOVERY-MIDPHASE-KILL-29C-01`; remaining limits are single-platform scope.
4. Pre-existing ancestor-link escape (28-A boundary): closed for pre-existing links by 28-B admission; post-open replacement races remain with 28-A.
5. 28-C deferred replay gaps (update exceptions, finish compensation, claim-race determinism, replay index sync): compensated by 28-D.
6. Old broad statements that Project/tree containment and final-open cover "reparse" generally: detection gaps (DirEntry junction miss; broken-junction fail-open) were closed by 30-C.

Not stale (do not close): between-checks replacement races; cross-system atomicity; restore_backup admission; power-loss/exactly-once; completed-with-pending-items bookkeeping semantics.

## 6. Housekeeping census (no code changed in this batch)

Of nine explicit TODO items investigated: four already resolved in code (auth_repository bare excepts gone; six zero-consumer widgets deleted in commit `300093b`; orphan AdminManagement.test.tsx deleted in `183c1d0`; gallery fsync fix committed in `41ccf86` — the audit text saying "uncommitted" is outdated). One half-resolved: storefront analytics prunes itself (2-day retention inline), free-download quota still lacks cross-identity pruning of expired windows (low risk). Two technically valid but low-risk: `_size_cache_ts` in MetadataService never evicts; share/delivery failure-count dicts prune per-key on access but never globally (bounded by restart). Two decision items: DeepSeek Docs migration (recommended option A: freeze-banner note; option B selective migration needs owner approval since it touches the do-not-modify directory) and `.pytest-tmp` empty scratch directory (removed locally in this batch; gitignored, no repo impact).

## 7. Verification

Focused import matrix executed for this snapshot: **58 passed, 2 skipped**, exit 0 → `artifacts/evidence/2026-08-25/evidence-register-v2/focused.stdout.log`. Static governance chain and the independent audit validator are recorded under the same artifact directory / validator console output.

## 8. Non-goals

No historical file bytes were modified; no bulk promotion beyond the seven qualifying IDs; no code changes for the housekeeping items; power-loss/exactly-once/cross-system atomicity/E2E/LAN/CVE/performance/release/clean-checkout remain out of scope everywhere. No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
