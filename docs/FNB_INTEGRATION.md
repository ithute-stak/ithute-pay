# FNB provider configuration

Ithute Pay Bridge supports FNB as a database-configured gateway provider.

## Current supported mode

- **Simulator:** available for safe application development and routing tests.
- **Live:** configuration can be captured, but payment requests are deliberately
  locked until the contracted FNB Lesotho integration pack is installed.

The lock prevents guessed endpoints or payloads from reaching a bank.

## Configuration payload

Create or update the provider through the existing gateway provider administration
endpoint using a payload shaped like:

```json
{
  "provider": "fnb",
  "environment": "sandbox",
  "mode": "simulator",
  "enabled": true,
  "active": true,
  "base_url": "",
  "country": "LES",
  "currency": "LSL",
  "client_id": "",
  "client_secret": "",
  "account_id": "",
  "certificate_reference": "",
  "supported_currencies": ["LSL"],
  "capabilities": {
    "collections": false,
    "payouts": false,
    "transfers": false,
    "status": false,
    "reversals": false,
    "reconciliation": false
  },
  "operation_paths": {}
}
```

The client secret is encrypted using the gateway's existing local secret service.
Only presence flags—not secret values—are returned by the configuration API.

## Live activation requirements

Live mode refuses activation unless all of these are supplied:

- Official FNB base URL
- Client ID
- Encrypted client secret
- Contracted account identifier
- Certificate/keystore secret reference
- Official operation paths

Even after activation data is present, the adapter returns
`FNB_ADAPTER_PENDING_SPEC` without sending a network request. Replace that guard
only after the official FNB Lesotho authentication, signing, payload, callback and
error schemas have been received and covered by contract tests.

Do not paste private keys or certificates into metadata. Store them in the
deployment secret manager and put only the secret reference in
`certificate_reference`.
