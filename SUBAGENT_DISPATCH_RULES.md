# Subagent Dispatch Rules

Use this document as the default model-routing and quality-gate policy when dispatching subagents.

For this Session, CustomProvidor is "AhriAPI".

The routing goal is cost efficiency: use the lowest reasoning strength that can reliably complete the task. The primary agent model is intentionally not fixed by this project; the user selects it. These rules apply to dispatched subagents: use Luna for most work, Terra when several concerns must be balanced, and Sol only for decisions where a wrong answer can create a serious or irreversible failure.

## Model Routing

| Task type | Model | Variant | Typical work |
|---|---|---|---|
| Mechanical search, file location, simple verification, and narrow log inspection | `CustomProvider/gpt-5.6-luna` | `low` | Find symbols, read a bounded file set, run a focused command, summarize direct evidence |
| Routine implementation, debugging, focused diagnosis, and bounded review | `CustomProvider/gpt-5.6-luna` | `medium` | Clearly specified edits, one feature or error path, focused tests, bounded diff review |
| Deep but still bounded investigation or difficult local reasoning | `CustomProvider/gpt-5.6-luna` | `max` | Ambiguous local behavior, second-pass analysis, difficult algorithmic reasoning without system-boundary risk |
| Balanced multi-file implementation or diagnosis | `CustomProvider/gpt-5.6-terra` | `medium` | Cross-module changes with a clear contract, integration work, nontrivial but reversible tradeoffs |
| Complex cross-boundary implementation or synthesis | `CustomProvider/gpt-5.6-terra` | `high` | Several modules and competing constraints, unresolved integration behavior, substantial test diagnosis |
| Important decision or high-risk review | `CustomProvider/gpt-5.6-sol` | `high` | Architecture, protocol contracts, concurrency, persistence, security, release, data-loss risk, irreversible design choices |

UEScene and other protocol work follow this same routing. Do not use a special model exception solely because a task concerns UEScene.

## Selecting a Model

Use `CustomProvider/gpt-5.6-luna` by default when the task is bounded, reversible, and independently verifiable. Start at `low` for mechanical work and `medium` for ordinary reasoning. Examples include:

- Locate files, symbols, call sites, strings, configuration values, or log evidence.
- Implement a clearly specified change with limited coupling.
- Run a focused build, static assertion, formatting check, or behavior test.
- Diagnose one feature, one error path, or one provider integration.
- Review a bounded diff with an explicit contract and no architecture decision.
- Prepare a first-pass analysis that can be escalated if uncertainty remains.

Use Luna `max` only when low or medium reasoning has insufficient evidence, the local algorithm is unusually difficult, or a second-pass analysis is cheaper than escalating to Terra. Do not use Luna `max` automatically for every subagent call.

Use `CustomProvider/gpt-5.6-terra` at `medium` when the task needs balanced judgment but is still well-bounded. Upgrade to `high` only when the task has substantial cross-module coupling or competing constraints. Examples include:

- A change spans several files or modules but has a clear local contract.
- Diagnosis crosses application, provider, UI, filesystem, or test boundaries.
- Several valid implementations require performance, maintainability, and compatibility tradeoffs.
- An integration failure needs end-to-end tracing but does not risk data loss or a release boundary.
- Luna reports uncertainty, conflicting evidence, or a result that needs a second layer of synthesis.

Terra `medium` is the normal integration setting. Terra `high` is an escalation setting, not the default.

Use `CustomProvider/gpt-5.6-sol` only for important decisions and high-risk review. Examples include:

- A change crosses application, provider, UI, filesystem, or publish boundaries.
- A behavior depends on timing, cancellation, shared mutable state, persistence, process restart, or compatibility guarantees.
- A protocol has multiple producers/readers or an external contract.
- An incorrect decision can lose user data, corrupt output, expose sensitive data, silently change semantics, or make a release unusable.
- The task chooses an architecture, migration strategy, security boundary, concurrency model, or public API contract.
- Terra cannot resolve conflicting evidence or explicitly recommends a high-risk escalation.

Do not send ordinary work to Sol merely because it is multi-file. Start with Luna, use Terra for synthesis, and use Sol only when the failure cost justifies it.

## Dispatch Workflow

1. Classify the task before dispatching.
2. Do not override the primary agent's model or variant; the user controls it.
3. Default to `CustomProvider/gpt-5.6-luna` with variant `low` for mechanical work or `medium` for ordinary work.
4. Upgrade Luna from `low` to `medium` when the task requires reasoning beyond direct inspection.
5. Upgrade Luna from `medium` to `max` only when local ambiguity remains and the task is still bounded.
6. Upgrade to Terra `medium` when the task spans modules or requires synthesis.
7. Upgrade Terra to `high` when the integration has competing constraints or unresolved behavior.
8. Upgrade to Sol `high` only when the task meets the high-risk criteria above.
9. Give the subagent a self-contained prompt:
   - workspace path
   - exact goal and scope
   - files allowed or expected
   - behavior that must remain unchanged
   - verification commands and evidence required
   - whether editing is allowed
10. For implementation, require a failing reproduction or explicit justification when no practical harness exists.
11. After implementation, independently inspect the diff and run verification.
12. Run an independent review before accepting high-risk or multi-file changes.

### Escalation Rules

- Luna may perform the first pass on any task that is not obviously high-risk.
- Use Luna `low` for direct lookup and verification, Luna `medium` for ordinary work, and Luna `max` only after evidence shows that more reasoning is needed.
- Prefer increasing the variant on the current model before moving to a more expensive model, provided the risk tier does not change.
- Escalate Luna to Terra when it encounters cross-module behavior, conflicting evidence, unclear ownership, or more than one plausible design.
- Escalate Terra to Sol when the decision affects architecture, protocols, persistence, concurrency, security, release safety, or data integrity.
- Do not restart the task from scratch at a higher tier unless the lower-tier result is incomplete or the risk boundary changed; pass the existing findings and evidence into the escalation prompt.
- A reviewer must use the same or stronger model tier than the implementation when the change is high-risk.

## Review Gates

Use a Sol review when any of these apply:

- architecture, protocol, persistence, concurrency, security, release packaging, or data-loss risk
- a change spans several components or repository boundaries
- a review must reason about behavior not fully expressed by a narrow unit test

Use a Terra `medium` review for a balanced multi-file implementation after the design and risk boundaries are established. Use Terra `high` only when the review has substantial integration uncertainty.

Use a Luna `medium` review for a bounded implementation or focused diff. Use Luna `low` for a purely mechanical verification and Luna `max` only for a difficult but bounded review. A Luna review must still report concrete file/line evidence and actionable findings, not general approval language.

If a reviewer finds a defect:

1. Fix the defect before continuing.
2. Re-run the relevant verification.
3. Re-review the current code, not the earlier diff.

## Interrupted or Partial Results

Do not treat an interrupted, partial, empty, or unverifiable subagent response as approval.

- Re-dispatch with a narrower prompt or a stronger model.
- Verify the repository state directly.
- For high-risk work, obtain a fresh independent review after any interruption.

## Prompt Examples

### Sol: High-Risk Diagnosis

```text
Use CustomProvider/gpt-5.6-sol with variant high. Perform a deep read-only diagnosis in <workspace>.
Trace <symptom> across <components>. Identify root causes with file:line evidence,
distinguish pre-existing behavior from local changes, and do not edit. Report only
actionable findings and residual verification gaps.
```

### Terra: Balanced Multi-File Implementation

```text
Use CustomProvider/gpt-5.6-terra with variant high. Implement <goal> in <workspace>.
Allowed files: <paths>. Preserve <invariants>. First establish a failing
reproduction or state why no practical harness exists. Make the minimal change,
run <commands>, inspect the diff, and do not commit.
```

### Luna: Mechanical Exploration

```text
Use CustomProvider/gpt-5.6-luna with variant low. Read-only search in <workspace>.
Find every definition and caller of <symbol>. Return file:line locations and a
one-sentence role for each. Do not edit.
```

### Luna: Independent Bounded Review

```text
Use CustomProvider/gpt-5.6-luna with variant medium. Review the current diff in <files> against this contract:
<requirements>. Report only actionable defects with severity and file:line evidence.
Do not edit. If none exist, state that explicitly and list residual test gaps.
```

## Non-Negotiable Practices

- User instructions override this document.
- Never infer success from a subagent report alone.
- Never let an independent reviewer rubber-stamp a result without examining the current files or diff.
- Never use a weak mechanical pass as the only review of high-risk work.
- Do not commit, push, reset, or discard user changes unless explicitly requested.
- Keep the implementation model and reviewer model assignments visible in the dispatch call.
