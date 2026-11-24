# M-PESA production callback and live-dispatch release gate

Status: **UNVERIFIED — draft PR #88 must not be merged or deployed solely on green CI.**

## Production findings (2026-11-24)

- A database-managed M-PESA gateway was active with production/live mode while the application environment had `MPESA_ENABLED=false` and `MPESA_MODE=simulator`. These settings do not disable every database-gateway client creation path.
- `PROVIDER_CALLBACK_TOKEN` was absent from the production application container environment at inspection time.
- The API is forwarded publicly through the shared Caddy edge at `api.pay.ithute.co.ls`; localhost-bound Docker ports do **not** make the API private.
- Existing callback handlers used a conditional token check and correlation checks. Correlation alone is not reliable callback-source authentication.
- Seven financial tables queried during the deployment audit had no rows at that time. This **does not** prove the provider has no outstanding financial transactions.

## Changes proposed in this PR

- An independent `MPESA_LIVE_DISPATCH_ENABLED` setting defaults to false. It guards production/live M-PESA client factories even when a DB gateway is active. It is separate from `MPESA_ENABLED` and separate from experimental pass-through approvals.
- Live M-PESA payment/payout catalogue entries are withheld while that setting is false.
- Production M-PESA callbacks now require `PROVIDER_CALLBACK_TOKEN` to be set; otherwise handlers respond 503. Provided tokens are compared securely, without relying on a CORS or host-header check.
- Regression tests cover disabled production routing, tenant shortcode routing, registry selection, catalogues, unauthorized results and timeouts.

## Blockers: independent provider and operational evidence required

1. Obtain **Vodacom Lesotho Open API documentation or written support confirmation** covering authentication for callback, result and timeout notifications, including permitted request headers, signed payloads, possible provider IP ranges, network trust boundaries and retry semantics. Do not assume the provider sets `X-Provider-Callback-Token`. The publicly accessible onboarding/developer pages do not verify this.
2. Select and implement only a provider-compatible callback authentication mechanism. If Vodacom cannot send a custom header, the current proposed callback change MUST be revised before deployment. Do not ask Vodacom to echo IthutePay API credentials.
3. Test the actual delivery contract from an authorized Vodafone/Vodacom sandbox or controlled provider setup, including legitimate result, timeout, retries, duplicates, rejected/forged payloads, unknown conversation IDs and correlation mismatches. Never use an unverified callback alone as settlement proof.
4. Complete a trace of all money-changing routes (collections, payouts, transfers, reversals, authorizations, direct-debit operations, admin live testing, partner portal, LoanHub funding, tenant shortcode routes and pass-through) for the live authorization gate. A guarded provider factory is a safety layer, **not** evidence that all flows are covered.
5. Confirm pending/unmatched external M-PESA operations and reconcile against provider-side records. Plan recovery for callbacks arriving during a deployment. Confirm no money-changing scenario silently becomes simulator-only in production.
6. Provision secrets using the supported secret manager or protected deployment configuration. Never print token values or put them in GitHub. Protect the shared Caddy edge without changing routing for other products.
7. Run CI for the final candidate commit, an isolated staging release rehearsal, and document the approvals of the payment owner, security reviewer and deployment owner. Release only after an explicit direct-live authorization decision.
8. Keep Golink optional and do not enable or certify live pass-through as a side effect of this PR.

## Release and rollback risks

- Deploying as-is while `PROVIDER_CALLBACK_TOKEN` is missing will reject inbound production M-PESA callback/result/timeout requests with HTTP 503.
- Deploying as-is while `MPESA_LIVE_DISPATCH_ENABLED=false` will block production/live direct M-PESA provider construction (intended fail-closed), even if the database gateway remains active.
- Those behaviors may interrupt previously approved M-PESA transactions, even though CI is green.
- Do not flip either setting simply to make tests pass. A live enablement must follow the approved provider authentication contract.
- Do not replay an uncertain payment as a health check. Verify status against Vodacom and reconcile using immutable provider references.
- Do not merge or run `pull pay latest` for this PR until the independent evidence and a non-disruptive cutover/rollback plan exist.

## Evidence record (complete before merge)

- Provider callback authentication specification/version: **missing**
- Provider confirmation for custom callback header: **missing**
- Provider retry and delivery guarantee: **missing**
- Sandbox end-to-end results: **missing**
- Real provider reconciliation during maintenance: **missing**
- Security reviewer approval: **missing**
- Payment operations owner approval: **missing**
- Safe release/rollback rehearsal: **missing**
