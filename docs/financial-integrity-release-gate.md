# IthutePay financial-integrity release gate

## Verified evidence
- PR #4 financial-integrity run #16 (ID 41473438964) passed against disposable PostgreSQL.
- PR #4 squash-merged to main as `8fe1d6fb5f70db1e94be2ec153818012f1befe22`.
- The main-branch push workflow result has NOT yet been verified with the connected GitHub integration.
- Financial CI exercises selected test modules, not all application functionality or live provider processing.

## Mandatory gates before production
1. Open https://github.com/ithute-stak/ithute-pay/actions/workflows/financial-integrity.yml and verify a SUCCESSFUL main-branch run for the intended release commit.
2. Check all other required build/publish workflows and image digest for the exact intended commit.
3. Confirm direct M-PESA is preserved, Golink remains optional, and provider credentials/config have not changed unexpectedly.
4. Back up PostgreSQL using a validated, encrypted, off-host destination; test restore into a DISPOSABLE database. Never run the test fixture against production.
5. Capture current running Docker image digest, compose configuration, and migration state without printing secrets.
6. Verify pending/unknown payments and reconciliation are accounted for before any switch; never replay unknown payment operations.

## Read-only production preflight
Run these manually on the production host after confirming the host and directory:
```bash
cd /home/administrator/ithute-pay
git rev-parse HEAD
sudo docker compose --env-file .env -f compose.yaml ps
sudo docker inspect --format '{{.Image}} {{.State.Health.Status}}' ithute-pay-ithute-pay-bridge-1
sudo docker image inspect ghcr.io/ithute-stak/ithute-pay:latest --format '{{index .RepoDigests 0}}'
```
Do not substitute a mutable `latest` tag for a recorded immutable image digest in the deployment approval.

## Deployment gate
- Confirm the real production compose override filenames and variable values (do not assume `compose.vps.yml` exists; it was not found in the repository root during review).
- Review `RUN_MIGRATIONS_ON_START=true` from compose.yaml. Migration compatibility and backup/rollback must be reviewed before container restart.
- Verify database backup and a known-good previous image digest.
- Only deploy during an approved maintenance window; changing live payments is a separate decision from merging tests.
- Apply a pinned image digest through the approved deployment path, not an unverified tag.
- Check API and UI health, M-PESA configuration, callback ingestion, payment status consistency, outbox, and reconciliation WITHOUT making real-money test calls.
- If health or accounting checks fail, stop rollout and use the documented application rollback. DB migrations may not be reversible, so restore only following an explicit recovery decision.

## Go/no-go
Do not call this release production-ready unless main CI is verified, migrations and rollback are validated, and non-destructive operational checks pass.
