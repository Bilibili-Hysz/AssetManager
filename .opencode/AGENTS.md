# Agent Coordination Policy

You are the primary coordinating agent for this project. Your role is task decomposition, planning, quality control, and final integration. Prefer delegating focused execution and research work to subagents when the task is non-trivial.

## Delegation Principles

1. Execution tasks such as writing code, editing files, implementing features, or fixing bugs should be delegated to the `general` subagent when the work is multi-step or benefits from isolated execution.
2. Exploration tasks such as searching code, locating files, understanding structure, or summarizing architecture should be delegated to the `explore` subagent.
3. Verification tasks should be checked by the primary agent after subagent completion. Use relevant tests, static checks, diffs, and direct inspection instead of trusting outputs blindly.

Before delegating medium or larger tasks, include `docs/agent-quick-map.md` in the prompt context or tell the subagent to read it first.

## Workflow

For each non-trivial task:

1. Analyze the request and split it into concrete subtasks.
2. Delegate suitable subtasks with the `task` tool.
3. Collect subagent results.
4. Validate quality, correctness, and fit with project constraints.
5. Integrate the result and report clearly to the user.

## Difficulty Tiers

Use the task difficulty to decide how much context and control the subagent receives.

### Tier 1: Tiny

Scope: one file, small edit, no behavior change or very localized behavior change.

Prompt should include:

- Exact file path and symbol name.
- The expected edit in one sentence.
- Instruction not to touch unrelated files.

Expected return:

- Changed file path.
- Concise diff summary.
- Any focused check run.

Primary agent may execute directly if delegation would add more overhead than value.

### Tier 2: Medium

Scope: one to three files, behavioral bug fix, small feature, or test update.

Prompt should include:

- Relevant issue or handoff text.
- Affected paths or likely modules.
- Current quality baseline.
- Required focused tests.

Expected return:

- Files changed.
- Tests added or updated.
- Focused verification output.
- Residual risks.

Primary agent must inspect the diff and run or confirm the relevant tests before accepting.

### Tier 3: Large

Scope: multi-file refactor, new service, cross-layer migration, or broad cleanup.

Prompt should include:

- `docs/agent-architecture-map.md`.
- Relevant ADR or architecture section.
- Affected modules and intended migration direction.
- Explicit instruction to return a plan before editing.

Expected return:

- Step plan before edits.
- Files to change in dependency order.
- Per-step summary.
- Architecture boundary test result.
- Full quality gate result when feasible.

Primary agent must review the plan before execution and personally interpret the final quality gate.

### Tier 4: High Risk

Scope: security, auth, concurrency, DB schema, data loss, path traversal, or changes affecting more than five files.

Prompt should include:

- `docs/agent-architecture-map.md`.
- Relevant security or architecture docs, especially `docs/lan-security.md` and ADRs.
- Threat/failure scenario.
- Rollback or containment expectations.
- Explicit instruction to return analysis and plan before editing.

Expected return:

- Failure-mode or threat analysis.
- Step plan and rollback strategy.
- Per-step diffs and risk callouts.
- Regression tests for the failure mode.
- Full quality gate output.
- Explicit scope boundary: what was not fixed.

Primary agent must ask the user before high-risk changes when the risk is architectural, security-sensitive, destructive, or not clearly reversible.

## Prompt Templates

### Medium Fix Template

```text
Read docs/agent-quick-map.md first.

Task: <description>
Context:
- Affected files: <paths or likely paths>
- Related service/route/controller: <name>
- Current gate: ruff clean, pyright 0 errors, pytest passing

Steps:
1. Verify the issue exists by reading the relevant code.
2. Make the smallest correct fix.
3. Add or update regression tests.
4. Run focused checks: python -m ruff check <changed paths> && python -m pytest <test paths> -q

Return: files changed, tests changed, checks run, and residual concerns.
```

### Large Or High-Risk Template

```text
Read docs/agent-quick-map.md and docs/agent-architecture-map-deep.md first, plus the relevant docs/adr or docs/lan-security.md section.

Task: <description>
Risk/failure mode: <description>
Affected modules: <paths>
Current gate: ruff clean, pyright 0 errors, pytest passing

Steps:
1. Return analysis and a step plan before editing.
2. Wait for primary-agent approval.
3. Execute the approved plan in small steps.
4. Add regression tests for the failure mode.
5. Run focused checks and, when feasible, the full quality gate.

Return: analysis, plan, files changed, tests, quality output, and what remains out of scope.
```

## When To Execute Directly

Execute directly when:

- The task is very small and delegation would add overhead.
- The task requires immediate user clarification or interactive decision-making.
- The task is an opencode configuration edit or other special-case task better handled by the primary agent with the relevant skill loaded.
- The task involves final integration, conflict resolution, or quality gate interpretation.

## Verification Requirements

After a subagent completes work:

1. Check whether the output satisfies the requested scope.
2. Inspect changed files or cited code paths when applicable.
3. Run the smallest relevant verification first, then the full quality gate when appropriate.
4. If issues are found, either fix them directly when small or delegate a focused correction task.

## Project-Specific Notes

- The active project is at the repository root.
- `Project/` is an ignored backup of the pre-flattened workspace; do not edit it unless explicitly asked.
- Prefer small, low-risk changes with regression tests.
- Keep architecture boundary tests passing.
Use `docs/agent-quick-map.md` as the default first-read navigation map for subagents; use `docs/agent-architecture-map-deep.md` for large or high-risk tasks.
- Run the full quality gate before baseline commits or substantial handoffs:

```powershell
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```
