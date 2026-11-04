# IthutePay multi-tenant staging release gate

This is a **staging plan, not an instruction to change production**. PR #8
remains draft until migration, recovery, tenant isolation and payment-provider
regressions are reviewed.

## Before staging

- Pin the exact tested Git commit and container image digest. Do not deploy
  `latest` or a mutable tag.
- Inventory production volume names, PostgreSQL version, schemas, volumes,
  environment variables, certificates, M-PESA keys and optional Golink config.
  Never copy live secrets into PRs, CI, screenshots or test fixtures.
- Confirm a database backup and a **separate restore verification** with
  integrity checks before any production upgrade. Test on disposable staging
  data only until change approval.
- Run Alembic migration smoke and restoration gates from
  `.github/workflows/financial-integrity.yml`; neither CI test uses production
  credentials, IP addresses or databases.
- Treat the initial ORM-driven migration as a historical compatibility issue;
  do not claim full rollback safety from clean-bootstrap success alone.

## Staging validation sequence

1. Restore a sanitized backup to a **separate** staging PostgreSQL instance.
   Confirm row totals of payment intents, provider transactions, reconciliation
   items, idempotency records, journal entries and tenant memberships **before**
   changing schema. Keep immutable hashes of backup artifacts.
2. Dry-run migrations through `0014_tenant_push_manual_retries` on the staging
   copy. Verify columns, indexes and constraints. Migrations should not change
   payment totals, transaction IDs, provider responses or ledger amounts.
3. Deploy a pinned staging API/UI image only after successful migration.
   Test backend health and authenticated portal flows; validate cookie/CSRF,
   CORS, tenant roles and API-key restrictions from an external test client.
4. Verify own-shortcode routing stays test-only. Check existing **direct
   M-PESA integration** and optional Golink integration separately under
   sandbox/test credentials, including failures, callbacks, idempotency and
   reconciliation. Do not enable live financial actions.
5. For two unrelated tenant merchants test: cross-tenant API reads, URL
   parameter tampering, association of foreign provider references, CSV
   exports, investigator assignment, alert acknowledgement, delivery monitor,
   owner-only policy updates and single manual retry.
6. Confirm the !thute Push worker stays **disabled** until separately
   authorised; check no unexpected dispatch when API or web portal boots.
7. Test a staging restart, database restore, and user-facing error recovery.
   Record actual restoration duration and data verification outcomes rather
   than assuming recovery objectives.
8. Run Playwright or equivalent browser-based end-to-end tests of the business
   portal, including failed API calls and navigation. The existing
   financial-integrity suite alone does not prove browser correctness.

## Current CI gates

- `smoke_migrations_postgres.py` upgrades an isolated local PostgreSQL
  database through the entire migration chain and verifies schema revision.
- `smoke_backup_restore_postgres.py` creates a canary record, performs
  `pg_dump` and `pg_restore` between **two disposable localhost databases**,
  checks the canary, Alembic revision and key push outbox constraints.
- PostgreSQL financial-integrity tests exercise transaction concurrency,
  tenant API isolation, reconciliation casework and guarded notification
  delivery.

These tests are not a substitute for recovery validation of real application
tables with meaningful payment history, a full-volume snapshot, encryption
key recovery, service credentials or a live provider integration test.

## Go/no-go criteria

**NO-GO** if migrations fail; backup restore fails; cross-tenant data appears;
a payment is double-posted; a provider callback is misallocated; an unsafe
credential is exposed; or a staging API unexpectedly initiates live transfer.

**GO for a controlled staging pilot** only with all gates green and reviewed
migration/backup evidence. Production release separately requires approval,
maintenance plan, rollback procedure, credential inventory, financial
reconciliation and post-deploy verification.


## Mandatory staging manifest preflight (no side effects)

The preflight at `apps/backend/scripts/staging_preflight.py` validates only
**non-secret release metadata**. It does not contact the container registry,
GitHub, PostgreSQL, M-PESA or Golink, and passing does **not** deploy anything.

Prepare a **non-secret JSON** manifest with the pinned image by digest, exact
source commit, independently verified CI commit, reviewed staging backup and
migration evidence, and explicitly disabled live-payment, push and automatic
migration switches. Execute:

```bash
cd apps/backend
python scripts/staging_preflight.py /secure/staging-release-manifest.json
```

The validator fails closed when any required gate is absent or false. In
particular, set `RUN_MIGRATIONS_ON_START=false` on staging so the combined
container supervisor does not silently apply schema migrations before the
backup has been restored and the migration has been reviewed. Existing
production startup behaviour is **unchanged** by this PR.

**Important:** PR image builds validate that the Dockerfile compiles but do
not publish a deployable GHCR image. The digest and `image_source_commit`
must be obtained and checked from a separately approved immutable image
publication; never invent them. A metadata manifest is not proof of a tested
backup, registry attestation or actual third-party provider certification.
Before approving staging deployment, independently check the digest/commit
mapping and backup evidence. Keep all secrets in the deployment secret store,
not in the release manifest or GitHub PR.

Even after staging preflight passes, external sandbox certification and
production change approval remain separate gates.


### Closed-schema release manifest

The offline preflight now **rejects every unrecognised field** at the top
level and inside `gates` or `switches`. Values and unknown field names
are never echoed to logs. Only the explicitly documented attestations and
switches are accepted; nested attachments, secret objects or arbitrary
release notes must be kept outside the manifest.

The required disabled switches include `RUN_BACKGROUND_JOBS`,
`GOLINK_COLLECTIONS_ENABLED` and `SANDBOX_TEST_LAB_ENABLED` alongside
the original M-PESA, push, reconciliation and auto-migration controls. These
attestations must match the actual staging Compose/runtime settings. The
validator cannot itself prove those settings were applied in a running
environment. Existing production settings remain unchanged.
