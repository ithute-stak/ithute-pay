# Batlokoa → IthutePay: Stage 2, inactive application

This step creates one **inactive**, test-environment application under the registered IthutePay master merchant. It does not enable a money-moving integration, generate API credentials, change provider configuration or configure fee rules.

Verified identifiers (from user-provided production inspection on 2026-11-04):

| Object | Identifier |
| --- | --- |
| LoanHub company, Batlokoa Financial Services | `4236a21f-5164-48aa-90f3-a35eccd23ae2` |
| IthutePay master merchant | `3cc13734-5cd3-4ab4-9e4b-d378b715fa3f` |
| Production M-PESA gateway configuration | `78e8842f-2f7b-4fd7-a113-7c6ca8798c51` |
| M-PESA master provider shortcode | `38542` |

## Operator procedure

1. Review PR, pass checks, merge and deploy the approved Docker image with the existing image-only release helper. Confirm PostgreSQL backup and app health.
2. Preview (no writes):

```bash
sudo docker exec -i -w /app/backend ithute-pay-ithute-pay-bridge-1 \
  python -m scripts.bootstrap_loanhub_application \
  --company-id 4236a21f-5164-48aa-90f3-a35eccd23ae2
```

3. Verify the output identifies master merchant `3cc13734-5cd3-4ab4-9e4b-d378b715fa3f`, production shortcode `38542`, action `create_inactive_application` and payment routing disabled. If those differ, do **not** apply.
4. Apply once, with authorization:

```bash
sudo docker exec -i -w /app/backend ithute-pay-ithute-pay-bridge-1 \
  python -m scripts.bootstrap_loanhub_application --apply \
  --company-id 4236a21f-5164-48aa-90f3-a35eccd23ae2
```

5. Confirm the returned application ID and inactive state. Rerunning is idempotent.

## Following stages (not in this PR)

- Implement a server-side, immutable mapping from authenticated LoanHub company ID to merchant and application; protect against metadata spoofing and cross-company requests.
- Use least-privilege credentials for a signed, read-only integration handshake; don't expose credentials to browsers or client devices.
- Add zero IthutePay-platform-fee policy, accounting tests and operational controls. Provider charges are independent.
- Complete provider-account-holder authorization for shared use of 38542, callback verification, idempotency and reconciliation. Review the earlier M-PESA sandbox getSession HTTP 400.
- Only then separately enable scoped financial routes and background workers.

LoanHub's own-shortcode paths and IthutePay's direct M-PESA provider remain unchanged. Golink stays optional.
