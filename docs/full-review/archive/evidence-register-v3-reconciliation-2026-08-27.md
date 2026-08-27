# 证据登记册 v3 对账报告（2026-08-27）

本批对应 finding 标识：`EVID-REGISTER-V3-RECON-2026-08-27`。

## 范围与方法

`audit-manifest-2026-08-20.json` 登记的 13 条 canonical finding（EVID-01..13）长期停留在
confirmed/conditional，其 `next_action` 所指的字母批次（S/C/PC/G 系列）与性能证据已在后续
dated 批次落地但登记行从未翻转。本次以人工映射 + 每条 grep 核验的方式统一翻转为
`superseded`，并逐条指向后继证据文件；不新增代码，不改历史报告正文，不动对应实施批次
的原有结论。唯一例外是保留批次 55 引入的数量上限删除语义说明（见 65/50 报告）。

## 对账结果

| 登记项 | 后继证据 | 处置叙述 |
|---|---|---|
| EVID-01 | docs/full-review/s1-s5-s2-min-implementation-evidence-2026-08-21.md | Resolved by S1 share-preview parity (authorized preview routed through serve_verified_image with blur/bounded output; focused 15 passed). Later tunnel/share-preview batches extend the policy. |
| EVID-02 | docs/full-review/lan-auth-eventloop-offload-evidence-2026-08-26.md | S2 synchronous-chain completion: websocket/session-token offloads (2026-08-22), desktop scoped-service migration, and the final PBKDF2 login/register/share offload (final suite green). Token-cache fast paths intentionally retained. |
| EVID-03 | tests/integration/test_library_lock_posix_recovery.py | Lock recovery now implements POSIX stale-lock takeover with serialized guard and integration tests; capability skipped on Windows hosts, so a hosted POSIX proof lane remains an open verification item rather than missing code. |
| EVID-04 | docs/full-review/c6-c10-security-boundary-hardening-evidence-2026-08-21.md | Release/dependency provenance hardening (GOV family) delivered by the c6-c10 security-boundary batch alongside workflow permission tightening. |
| EVID-05 | docs/full-review/c2-c3-min-session-transaction-evidence-2026-08-21.md | After-commit event ordering established by C3-01 rollback/write-scope oracle. |
| EVID-06 | docs/full-review/c2-c3-min-session-transaction-evidence-2026-08-21.md | Session-bound persistence normalized across the C-series (c2-c3 connections, c4-b savepoint migrations, c7 durable external-watch rescan, c8 import lifetime, c9 terminal cleanup, c10 restart recovery). |
| EVID-07 | docs/full-review/c1-min-contract-implementation-evidence-2026-08-21.md | C1 typed errors, Gallery home union, timestamp/DTO parity delivered. |
| EVID-13 | docs/full-review/c1-min-contract-implementation-evidence-2026-08-21.md | HTTP exception consistency covered by C1-03 canonical JSON error envelope slices. |
| EVID-08 | docs/full-review/desktop-async-implementation-evidence-2026-08-21.md | PC-2 drag-drop worker truthfulness: every accepted drop yields an explicit result-or-failure payload; desktop regressions pinned. |
| EVID-09 | docs/full-review/desktop-async-implementation-evidence-2026-08-21.md | PC-1 cover callbacks migrated to QObject queued bridge (_event_bridge pattern); offscreen Qt verified. Windows-lifecycle CI lane remains open. |
| EVID-10 | docs/full-review/desktop-async-implementation-evidence-2026-08-21.md | PC-3 BoundedPool.close timed drain + daemon reaper; blocked-worker lifecycle tests added. Release-grade Windows CI coverage noted as still required. |
| EVID-11 | docs/full-review/evidence-convergence-2026-08-20.md | Claim corrected in convergence report; external_watch unsupported-by-incremental fallback replaced by durable rescan (c7-min-watcher-durable-rescan). Wide-tree magnitude benchmark remains accepted verification debt. |
| EVID-12 | docs/full-review/evidence-convergence-2026-08-20.md | Suppression scope narrowed per corrected claim; decode pipeline subsequently reworked by thumbnail/loader batches. Throughput benchmark remains accepted debt. |

## 未随之关闭的事项（如实列出）

- EVID-03 / EVID-09 / EVID-10 的宿主级 Windows CI 验证车道仍缺失（代码与本地测试在档）。
- EVID-11 / EVID-12 的吞吐量级基准仍为接受的验证债（加速图谱已定性主因）。
- `next_action` 中非本链的外部项（`bg_effects.py` ICN001）由其引入方处理。

## 校验与边界

- 更新仅触及 `audit-manifest-2026-08-20.json` 的机器可读字段（status/next_action/
  supersession_notes），未改任何报告正文。
- 本方法属登记册维护批，non-code change；验证即独立 manifest 校验器全绿加下表哈希一致性，
  不存在运行时行为变化可测。
