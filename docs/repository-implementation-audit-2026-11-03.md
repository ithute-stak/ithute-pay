# IthutePay repository implementation audit — 2026-11-03

## Scope and limits
Inventoried the full default-branch Git tree (536 entries, not truncated) and
inspected representative services, models, financial concurrency tests, CI
workflows and direct M-PESA/Golink integration. This is a targeted
implementation and money-movement review, **not** an independent full-code
penetration test or verification of all 536 entries. Current production was
reported healthy on release `38ee9da6f9bc7b160b308d1335d2974af5b1c448`.

## Implemented: do not duplicate
- Direct Vodacom Lesotho M-PESA client and hardened gateway configuration;
  retain it independently of optional Golink.
- Merchant/provider and tenant shortcode routing.
- Ledger, fee, funding, reconciliation and callback structures.
- PostgreSQL migrations through `0007_ithute_central_auth`.
- C2B collection and standard unfunded B2C payout use compare-and-swap
  `created -> processing` with a commit before provider network I/O.
- The opt-in provider-operation reservation service supports scoped
  idempotency, compare-and-swap dispatch, and lifecycle transitions, but
  is not automatically wired into legacy money-movement paths.
- PostgreSQL financial concurrency tests and financial integrity workflow;
  coverage is selective, not a complete production certification.

## Confirmed risk / incomplete integration
1. **B2B transfers**: previously created a provider transaction and assigned
   `processing` without an atomic claim; network timeout handling also did not
   explicitly preserve an `unknown` transfer state. Addressed by this PR.
2. **Settlements**: status checks and new provider-operation creation are
   not atomic against concurrent execution. Prior `processing/unknown`
   operation checks do not alone prevent parallel dispatch.
3. **Reversals**: the execution path creates a new reversal without an atomic
   claim or a demonstrated aggregate cap across prior partial reversals.
4. **Funded payouts**: `_execute_funded_payout` and
   `_start_direct_funding` set processing/funding states but need equivalent
   concurrent-dispatch and unknown-result tests.
5. **Testing/operational controls**: no live-provider certification is
   inferred from successful unit or CI tests; keep real-money tests separate.
   Backup was restore-tested on VPS, but off-host encrypted retention remains
   to be verified. Production checkout previously lagged its deployed image.
6. **Repository hygiene**: tracked `apps/backend/tests/paybridge_test.db`,
   `apps/frontend/frontend.zip`, `apps/frontend/tsconfig.tsbuildinfo`,
   and `apps/frontend/test-results/.last-run.json` deserve review to
   ensure generated artifacts and test data are not accidentally distributed.

## Next ordered work
1. Land transfer claim + timeout regression behind passing isolated CI.
2. Add atomic settlement ownership and repeat/concurrent submission tests.
3. Guard reversals against concurrent over-refunds and test partial reversals.
4. Audit and guard direct-funded and funded payout paths.
5. Exercise callback/query reconciliation after unknown outcomes, with
   replay-safe tests and tenant isolation.
6. Update release checklist, automated gates and off-host backup process.
7. Only then schedule a pinned-digest production deployment with rollback
   and direct M-PESA unchanged.

## Release gate
Do not merge or deploy financial-safety changes until the pull-request
financial-integrity AND image-build checks pass. Do not run test fixtures
against production; `tests/conftest.py` recreates the database schema.
