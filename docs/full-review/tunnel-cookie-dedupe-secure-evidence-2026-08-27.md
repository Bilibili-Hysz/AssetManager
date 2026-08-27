# Visitor Cookie Dedupe and Secure Flag Evidence (2026-08-27)

## Scope
Finding `COOKIE-DUP-SECURE-46-01`: two open gaps around `am_quota_id` — (a) a response that already carries a route-issued visitor cookie could get a second same-name `Set-Cookie` from the middleware, silently replacing the route's identity; (b) `apply_visitor_cookie` never set `Secure`, so HTTPS-terminated tunnel visitors received a non-Secure credential.

## Change
`tunnel_identity.apply_visitor_cookie(response, token, *, secure=False)` passes the flag through to `set_cookie`. `security.py` defers minting to the attach point and skips attachment when the response already contains `am_quota_id`; the fresh cookie uses `secure=bool(request.secure)` so plain loopback HTTP keeps working.

## Verification
- Isolation file re-run **13 passed** including: preset-cookie handler keeps its own value (exactly one morsel survives), `apply_visitor_cookie(secure=True)` produces a Secure morsel while default does not; anti-farming tests above still pass on the shared attach path.
- Final serial suite green (see batch-series summary report): **4097 passed, 16 skipped, 20 deselected, 2 warnings**.

## Boundaries
Status is `fixed-unverified`. Browser-level Set-Cookie merge behavior across hops/proxies, HSTS interplay, and real HTTPS edge validation are not covered by loopback mocks.
