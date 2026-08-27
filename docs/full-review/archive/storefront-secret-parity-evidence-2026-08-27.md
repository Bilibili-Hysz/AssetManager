# Storefront Analytics Secret Parity Evidence (2026-08-27)

## Scope
Finding `STOREFRONT-SECRET-PARITY-52-01`: the storefront analytics visitor cookie was a third independent copy of the signing-secret precedence logic, with its own fallback attribute (`_storefront_analytics_cookie_secret`) diverging from the shared `_quota_cookie_secret` used by quota and the tunnel limiter — so a bare/unconfigured lan object carried two unrelated random keys, and `quota.py`'s docstring claim of "same secret sourcing" was not literally true.

## Change
- `storefront_analytics._cookie_signing_secret(lan)` now delegates to `tunnel_identity.signing_secret(lan)`; its stricter b64-canonicalization validation and 24h `/api/shop` cookie contract are untouched, and the 202-without-cookie failure path is unchanged.
- `quota._quota_cookie_signing_secret(lan)` delegates the same way; private names (`_new_quota_cookie_token`, `_valid_quota_cookie_token`, `_quota_cookie_id`) are preserved for the parity/assembly contract tests.
- Two distinct cookies intentionally remain (shopping-visit 24h dedup vs quota identity 30d) — merging them would couple rate-limit identity with browsing statistics.

## Verification
Focused matrix **30 passed, 233 deselected**: three-way secret equality on configured and bare lan objects, shared fallback attribute agreement, full `shop_store_visit` morsel attributes, 202-no-cookie failure contract, plus existing anonymous-quota/assembly suites. Final serial Python suite **4117 passed, 16 skipped, 20 deselected, 2 warnings**; full Ruff/compileall/diff-check/governance and WebUI typecheck green.

## Boundaries
Status `fixed-unverified`. No real Cloudflare edge/TLS loop; the change only affects unconfigured (test/bare) lan objects — production always takes the configured-secret branch.