# One-command VPS release: `pull pay latest`

This command is installed once as `/usr/local/bin/pull` on the existing
IthutePay VPS. It **never runs git pull, host Python, or host pytest**.

The command pulls two separately published GHCR images: **combined FastAPI backend + Next.js merchant portal**, and **Flutter web**. Flutter is deployed independently after the combined service is healthy. No database migrations run in the Flutter service. Flutter feature development remains deferred.

## Preflight
- Must run on the approved VPS with the existing Compose overlay files.
- Requires a working `docker` Compose plugin, `flock`, `curl`, and
  `sudo` for elevation.
- Requires registry authorization to pull private GHCR images (if applicable).
- Requires healthy existing PostgreSQL and the existing payment app.
- Existing production Caddy and `public-edge` network must be intact.
- Deploys the **GHCR latest** tags only. The combined release comes from
  `.github/workflows/build-vps-image.yml` and the Flutter image from
  `.github/workflows/publish-flutter-image.yml`. Both images must already
  be published, accessible and validated before the first production use.
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
3. Pull the separate Flutter GHCR image and preserve its old running image
4. Validate **the existing production Compose stack**, adding one temporary
   image override. Prevent accidental migration/worker/provider activation
5. Produce root-only PostgreSQL custom-format dump before database changes
6. Inspect old schema revision and run new image's Alembic migration one-shot
7. Recreate **only** `ithute-pay-bridge` (not PostgreSQL, Redis, Flutter or Caddy)
8. Verify running exact Docker image ID, container health, public API health,
   and merchant portal HTTPS
9. Roll back old image if health fails **and database revision has not changed**

10. Recreate the separate Flutter web service from its pinned GHCR image;
    verify container health and public HTTPS, or restore its previous image
    if that deployment fails. Flutter rollback does not reverse a healthy
    backend/portal release.

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
