# One-command VPS release: `pull pay latest`

This command is installed once as `/usr/local/bin/pull` on the existing
IthutePay VPS. It **never runs git pull, host Python, or host pytest**.

The command updates the **combined FastAPI backend + Next.js merchant portal**
from GHCR. Flutter remains on its existing, separate container until an
independent, audited Flutter image release channel is built. No migration
runs in the Flutter service.

## Preflight
- Must run on the approved VPS with the existing Compose overlay files.
- Requires a working `docker` Compose plugin, `flock`, `curl`, and
  `sudo` for elevation.
- Requires registry authorization to pull private GHCR images (if applicable).
- Requires healthy existing PostgreSQL and the existing payment app.
- Existing production Caddy and `public-edge` network must be intact.
- Deploys the **GHCR latest** tag only. It is published by
  `.github/workflows/build-vps-image.yml` from `main` after required
  financial-integrity checks.
- Requires production Alembic migration compatibility. Additive migrations
  should use expand/contract releases; irreversible migrations require
  operator-controlled maintenance.

## First-time installation
After this PR is reviewed, tested and merged to `main`, install once on VPS:

```bash
sudo curl -fLSs https://raw.githubusercontent.com/ithute-stak/ithute-pay/main/deploy/vps/pull-pay-latest \
  -o /usr/local/bin/pull
sudo chmod 755 /usr/local/bin/pull
sudo bash -n /usr/local/bin/pull
```

Then use:

```bash
pull pay latest
```

The helper will request sudo authentication when needed. For automated
execution, pin and verify the helper version during setup; a future
reinstallation should use an audited immutable commit URL.

## Release stages

1. Exclusive `flock` guard and existing service inspection
2. Pull combined GHCR latest image and pin by registry digest
3. Validate **the existing production Compose stack**, adding one temporary
   image override. Prevent accidental migration/worker/provider activation
4. Produce root-only PostgreSQL custom-format dump before database changes
5. Inspect old schema revision and run new image's Alembic migration one-shot
6. Recreate **only** `ithute-pay-bridge` (not PostgreSQL, Redis, Flutter or Caddy)
7. Verify running exact Docker image ID, container health, public API health,
   and merchant portal HTTPS
8. Roll back old image if health fails **and database revision has not changed**

If migrations change the schema and the new image fails, automatic rollback
to old application code may break financial transactions. The helper refuses
unsafe image rollback and reports that human-led recovery is required.
A backup must never be automatically restored over an active financial
database. This is a deliberate fail-safe, not a guarantee of no downtime.

The currently configured payment provider rails remain disabled while
the release process is being tested. Future business activation must
explicitly change the approved rollout policy, never happen simply because
`latest` was pulled.

## Production rollout requirement

Test the script with a disposable production-like PostgreSQL database and
rehearse a migration failure, failing startup, unchanged-schema rollback,
and schema-changed stop before installing it as a production entrypoint.
The script does not yet implement blue/green switching or automatic database
point-in-time recovery; short app interruptions are possible.
