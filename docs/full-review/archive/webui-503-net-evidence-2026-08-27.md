# WebUI ServiceUnavailable(503) Regression Net Evidence (2026-08-27)

## Scope
Finding `WEBUI-503-NET-54-01`: `client.ts` already classified 503→`ServiceUnavailableError` and retried idempotent GETs, and `errors.ts` shipped an `isServiceUnavailableError` guard — but zero tests exercised any of it (`grep unavailable` returned nothing).

## Change
Production code untouched; test-only coverage added:
- `webui/src/api/client.test.ts`: GET receives 503 — retried through both backoff sleeps, terminal rejection carries the parsed body (`name/status/body/message` match), and exactly 3 fetch calls occur (initial + 2 retries); non-GET 503 throws `ServiceUnavailableError` without retrying (1 call). Mock returns a fresh `Response` per attempt (a Response body is single-use).
- `errors.test.ts` already guarded `isServiceUnavailableError`; kept in the run.

## Verification
`cd webui && npm test -- --run src/api/client.test.ts src/api/errors.test.ts` → **22 passed**; `npm run typecheck` (`tsc --noEmit`) clean; full WebUI vitest run green alongside. Python side unaffected.

## Boundaries
Status `fixed-unverified`. This pins classification/retry behavior only; a global 503/429 toast or Retry-After countdown UI remains an unclaimed interaction-design backlog item, as recorded.