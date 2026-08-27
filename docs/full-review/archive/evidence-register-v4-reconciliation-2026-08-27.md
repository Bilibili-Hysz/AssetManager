# Register v4 reconciliation (2026-08-27)

Finding id: `EVID-REGISTER-V4-RECON-2026-08-27`.

## Method

Three parallel read-only agents verified every source ID not promoted by register v1: 104 unique IDs across performance(30), quality/gov(35), crossmodule+scan(39). Codes R/O/S as in slices.

## Totals

| slice | total | R | O | S |
|---|---|---|---|---|
| performance | 30 | 1 | 2 | 27 |
| quality-gov | 35 | 10 | 8 | 17 |
| crossmodule+scan | 39 | 18 | 5 | 16 |
| total | 104 | 29 | 15 | 60 |

## Errata

- v3 flipped EVID-04 wholesale; GOV-02..07 remain open (slice-B), so this pass reverts EVID-04 to conditional.
- Performance family stays almost entirely S (28/30): measurement-gated since inception; PT-01 fully consumed.
- P2 tail open density high (frontend/media edges); 5 partially absorbed.

Full per-ID tables live verbatim in the three input slices.