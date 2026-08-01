# Subagent Dispatch Rules

Use this document as the default model-routing and quality-gate policy when dispatching subagents.

For this Session, CustomProvidor is "AhriAPI".

The routing goal is cost efficiency: use the lowest reasoning strength that can reliably complete the task. The primary agent model is intentionally not fixed by this project; the user selects it. These rules apply to dispatched subagents: use Luna high for ordinary work, Luna max for deep but bounded investigation, Sol medium for cross-module synthesis, and Sol xhigh only for decisions where a wrong answer can create a serious or irreversible failure.

Terra is intentionally not used. Sol and Luna cover every tier Terra would otherwise fill: Sol medium replaces Terra for balanced integration, and Luna high/max replace Terra for everyday and deep work.

## Model Routing

| Task type | Model | Variant | Typical work |
|---|---|---|---|
| Mechanical search, file location, simple verification, and narrow log inspection | `CustomProvider/gpt-5.6-luna` | `high` | Find symbols, read a bounded file set, run a focused command, summarize direct evidence |
| Routine implementation, debugging, focused diagnosis, and bounded review | `CustomProvider/gpt-5.6-luna` | `high` | Clearly specified edits, one feature or error path, focused tests, bounded diff review |
| Deep but still bounded investigation or difficult local reasoning | `CustomProvider/gpt-5.6-luna` | `max` | Ambiguous local behavior, second-pass analysis, difficult algorithmic reasoning without system-boundary risk |
| Balanced multi-file implementation or diagnosis | `CustomProvider/gpt-5.6-sol` | `medium` | Cross-module changes with a clear contract, integration work, nontrivial but reversible tradeoffs |
| Complex cross-boundary implementation or synthesis | `CustomProvider/gpt-5.6-sol` | `medium` | Several modules and competing constraints, unresolved integration behavior, substantial test diagnosis |
| Important decision or high-risk review | `CustomProvider/gpt-5.6-sol` | `xhigh` | Architecture, protocol contracts, concurrency, persistence, security, release, data-loss risk, irreversible design choices |

UEScene and other protocol work follow this same routing. Do not use a special model exception solely because a task concerns UEScene.

## Selecting a Model

Use `CustomProvider/gpt-5.6-luna` with variant `high` by default when the task is bounded, reversible, and independently verifiable. Luna high is the normal working tier for both mechanical and ordinary reasoning. Examples include:

- Locate files, symbols, call sites, strings, configuration values, or log evidence.
- Implement a clearly specified change with limited coupling.
- Run a focused build, static assertion, formatting check, or behavior test.
- Diagnose one feature, one error path, or one provider integration.
- Review a bounded diff with an explicit contract and no architecture decision.
- Prepare a first-pass analysis that can be escalated if uncertainty remains.

Use Luna `max` only when high reasoning has insufficient evidence, the local algorithm is unusually difficult, or a second-pass analysis is warranted but the task is still bounded. Do not use Luna `max` automatically for every subagent call.

Use `CustomProvider/gpt-5.6-sol` at `medium` when the task needs balanced judgment across multiple modules or concerns. Sol medium replaces Terra entirely for integration and synthesis work. Examples include:

- A change spans several files or modules but has a clear local contract.
- Diagnosis crosses application, provider, UI, filesystem, or test boundaries.
- Several valid implementations require performance, maintainability, and compatibility tradeoffs.
- An integration failure needs end-to-end tracing but does not risk data loss or a release boundary.
- Luna reports uncertainty, conflicting evidence, or a result that needs a second layer of synthesis.

Sol `medium` is the normal integration and synthesis tier. Do not reserve Sol for high-risk work only; use it whenever the task spans modules.

Use `CustomProvider/gpt-5.6-sol` at `xhigh` only for important decisions and high-risk review. Examples include:

- A change crosses application, provider, UI, filesystem, or publish boundaries.
- A behavior depends on timing, cancellation, shared mutable state, persistence, process restart, or compatibility guarantees.
- A protocol has multiple producers/readers or an external contract.
- An incorrect decision can lose user data, corrupt output, expose sensitive data, silently change semantics, or make a release unusable.
- The task chooses an architecture, migration strategy, security boundary, concurrency model, or public API contract.
- Sol `medium` cannot resolve conflicting evidence or explicitly recommends a high-risk escalation.

Do not send ordinary work to Sol merely because it is multi-file. Start with Luna high, escalate to Luna max for deep bounded work, use Sol medium for synthesis, and use Sol xhigh only when the failure cost justifies it.

## Dispatch Workflow

1. Classify the task before dispatching.
2. Do not override the primary agent's model or variant; the user controls it.
3. Default to `CustomProvider/gpt-5.6-luna` with variant `high` for mechanical or ordinary work.
4. Upgrade Luna from `high` to `max` only when local ambiguity remains and the task is still bounded.
5. Move to Sol `medium` when the task spans modules or requires synthesis.
6. Upgrade Sol from `medium` to `xhigh` only when the task meets the high-risk criteria above.
7. Give the subagent a self-contained prompt:
   - workspace path
   - exact goal and scope
   - files allowed or expected
   - behavior that must remain unchanged
   - verification commands and evidence required
   - whether editing is allowed
8. For implementation, require a failing reproduction or explicit justification when no practical harness exists.
9. After implementation, independently inspect the diff and run verification.
10. Run an independent review before accepting high-risk or multi-file changes.

### Escalation Rules

- Luna may perform the first pass on any task that is not obviously high-risk.
- Use Luna `high` for direct lookup, ordinary work, and focused review; use Luna `max` only after evidence shows that more reasoning is needed while the task stays bounded.
- Prefer increasing the variant on the current model before moving to a more expensive model, provided the risk tier does not change.
- Escalate Luna to Sol `medium` when it encounters cross-module behavior, conflicting evidence, unclear ownership, or more than one plausible design.
- Escalate Sol `medium` to Sol `xhigh` when the decision affects architecture, protocols, persistence, concurrency, security, release safety, or data integrity.
- Do not restart the task from scratch at a higher tier unless the lower-tier result is incomplete or the risk boundary changed; pass the existing findings and evidence into the escalation prompt.
- A reviewer must use the same or stronger model tier than the implementation when the change is high-risk.

## Review Gates

Use a Sol `xhigh` review when any of these apply:

- architecture, protocol, persistence, concurrency, security, release packaging, or data-loss risk
- a change spans several components or repository boundaries
- a review must reason about behavior not fully expressed by a narrow unit test

Use a Sol `medium` review for a balanced multi-file implementation after the design and risk boundaries are established.

Use a Luna `max` review for a difficult but bounded implementation or diff. Use Luna `high` for a bounded implementation, focused diff, or purely mechanical verification. A Luna review must still report concrete file/line evidence and actionable findings, not general approval language.

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
Use CustomProvider/gpt-5.6-sol with variant xhigh. Perform a deep read-only diagnosis in <workspace>.
Trace <symptom> across <components>. Identify root causes with file:line evidence,
distinguish pre-existing behavior from local changes, and do not edit. Report only
actionable findings and residual verification gaps.
```

### Sol: Balanced Multi-File Implementation

```text
Use CustomProvider/gpt-5.6-sol with variant medium. Implement <goal> in <workspace>.
Allowed files: <paths>. Preserve <invariants>. First establish a failing
reproduction or state why no practical harness exists. Make the minimal change,
run <commands>, inspect the diff, and do not commit.
```

### Luna: Mechanical Exploration

```text
Use CustomProvider/gpt-5.6-luna with variant high. Read-only search in <workspace>.
Find every definition and caller of <symbol>. Return file:line locations and a
one-sentence role for each. Do not edit.
```

### Luna: Independent Bounded Review

```text
Use CustomProvider/gpt-5.6-luna with variant max. Review the current diff in <files> against this contract:
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
