# ADR 0004: Order State Machine Placement (Repository-Adjacent CAS)

> 维护状态:**LIVING** · updated: 2026-08-28 · 记录"订单状态机住在仓储层"这一取舍的接受理由与重启条件。

## Status

Accepted (2026-08-28, quality-audit session). This ADR records a deliberate
non-move: the order state machine stays next to its CAS implementation in the
repository layer instead of moving into `domain/`.

> **更新 (2026-08-30)**：Commerce/Seller 商城运行时已按
> [`ADR 0005`](0005-commerce-extraction.md) 整体剥离。本文记录的状态机
> 取舍随 `order_repository.py` 一并删除，不再适用于当前代码库；保留本文
> 作为商城运行时的设计依据与剥离回溯参考。

## Context

The declared architecture is `domain ← repositories ← application`, with
`domain/` holding value objects, domain events and the error hierarchy. The
order lifecycle (`ORDER_STATUSES` / `ALLOWED_TRANSITIONS`,
`AssetsManager/repositories/order_repository.py:28-40`) is domain-shaped
business rule, but it is defined in the repository and imported back by
`application/order_service.py`. A 2026-08-28 architecture review classified
this as "anemic domain": business rules are split between the repository
(CAS/state machine) and the application layer (orchestration).

## Decision

**Keep the state machine in `order_repository.py`.** Rationale:

1. **Single-source coupling is the point.** The transition whitelist exists
   so that the repository-level conditional `UPDATE ... WHERE status=?` CAS
   (`transition_status`, same file) and the service-level validation can
   never diverge. Splitting the constants into `domain/` re-creates a second
   import direction (repository → domain is already allowed, but service →
   domain → repository-shaped truth weakens the "CAS and whitelist are one
   artifact" property the comment in the file explicitly documents).
2. **Cost/benefit of the move is poor.** Moving the table to `domain/` is a
   mechanical churn across repositories + services + tests with zero
   behavior change; the domain layer gains no new capability because the
   state machine is the *only* rule of its kind. Anemic-domain debt is
   accepted until a second rule of comparable weight appears.
3. **Guardrails already exist.** The transition table is covered by the
   order/repository tests, and the layer DAG gate
   (`scripts/check_layers.py`) keeps the dependency direction honest.

## Revisit Condition

Move the state machine (and any sibling rule) into `domain/` — with the CAS
SQL kept in the repository referencing the domain table — when either:

- a second state-machine-style domain rule lands (e.g. delivery-token
  lifecycle gaining transition validation), making a domain rules module
  earn its keep, or
- a second application service needs the transition table, making the
  repository import direction awkward.

## Consequences

- `domain/` remains value objects + events + errors only; reviewers should
  not treat "business rule in repository" as a defect **for this specific
  table**.
- The 2026-08-28 audit ledger classifies this item as "needs design
  decision"; this ADR is that decision. Future audits should reference this
  file instead of re-opening the question.
