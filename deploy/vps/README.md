# IthutePay VPS: image-only deploy via `pull pay latest`

## Scope and current limitations

The existing GitHub workflow `.github/workflows/build-vps-image.yml` builds and publishes `ghcr.io/ithute-stak/ithute-pay:latest` after tests on `main`. Its Dockerfile combines **FastAPI and Next.js** (and Celery workers); the **Flutter web** application has a separate Dockerfile/image and is **not** included in this release command. No image-only change should overwrite the existing independent Flutter container.

This deployer does **not** perform `git pull`, `docker build`, `pip install`, or `pytest` on the VPS. It leaves PostgreSQL, Redis, environment files, existing volumes, network configuration, payment providers, and Flutter untouched. It does **not** introduce a zero-downtime blue/green router; a Docker Compose recreate can briefly interrupt requests. Never claim uninterrupted payments until an isolated blue/green cutover and idempotent worker handover have been implemented/tested.

## One-time setup on the VPS (review and adapt existing Compose paths first)

The VPS launcher is `/usr/local/bin/pull`, a Bash dispatcher that resolves the exact `main` commit and downloads a single deployment helper. **Keep the existing `ithute` and `loanhub` entries unchanged.** Extend that dispatcher **only after PR approval, staging verification, and merge**. The IthutePay helper lives at `deploy/vps/pull-pay` on `main`. It expects `latest` as its only argument and runs as root, like the LoanHub helper.

After the PR merges and the root-owned configuration below is installed, use this **one-time idempotent patch** on the VPS. This is not part of the regular application deployment; regular `pull pay latest` fetches the exact-commit helper and pulls a GHCR image, not application source.

```bash
sudo python3 - <<'PY'
from pathlib import Path
import shutil
import subprocess
from datetime import datetime, timezone

path = Path("/usr/local/bin/pull")
original = path.read_text()
if '  pay)\n' in original:
    print("pay routing already installed")
    raise SystemExit(0)

# Fail closed if the operator-owned launcher has changed unexpectedly.
expected_ithute = '''  ithute)
    REPO="ithute-stak/ithute"
    HELPER_PATH="scripts/deploy-production-latest.sh"
    HELPER_NAME="deploy-production-latest.sh"
    PREFIX="Ithute"
    ;;
'''
expected_dispatch = '''  loanhub)
    if [ "$(id -u)" -ne 0 ]; then
      echo "[LoanHub] Elevating production deployment launcher"
      exec sudo bash "$helper" latest
    fi
    exec bash "$helper" latest
    ;;
esac
'''
if original.count(expected_ithute) != 1 or original.count(expected_dispatch) != 1:
    raise SystemExit("Existing launcher changed: no patch applied")

updated = original.replace(
    expected_ithute,
    expected_ithute + '''  pay)
    REPO="ithute-stak/ithute-pay"
    HELPER_PATH="deploy/vps/pull-pay"
    HELPER_NAME="pull-pay"
    PREFIX="IthutePay"
    ;;
''',
    1,
).replace(
    expected_dispatch,
    expected_dispatch.replace('esac', '''  pay)
    if [ "$(id -u)" -ne 0 ]; then
      echo "[IthutePay] Elevating production deployment launcher"
      exec sudo bash "$helper" latest
    fi
    exec bash "$helper" latest
    ;;
esac'''),
    1,
).replace('Usage: pull {ithute|loanhub} latest', 'Usage: pull {ithute|loanhub|pay} latest')

temp = path.with_name("pull.candidate")
temp.write_text(updated)
temp.chmod(0o755)
try:
    subprocess.run(["bash", "-n", str(temp)], check=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"pull.backup.{stamp}")
    shutil.copy2(path, backup)
    temp.replace(path)
    print(f"Installed pay route; previous launcher saved at {backup}")
finally:
    temp.unlink(missing_ok=True)
PY
```

Test dispatcher argument rejection without touching running containers:

```bash
pull pay invalid  # must show Usage, must not deploy
pull loanhub invalid  # must show Usage, must not deploy
```

Create an operator-owned configuration file. **Replace the sample paths and public endpoints with the currently deployed, working ones.** File list must include **all** current production Compose overlays, including the existing production network and volumes overlays if applicable; do not create a new Compose project or new DB volumes.

```bash
sudo tee /etc/ithutepay-deploy.conf >/dev/null <<'CONFIG'
PAY_DEPLOY_DIR=/home/administrator/ithute-pay
PAY_ENV_FILE=/home/administrator/ithute-pay/.env
PAY_COMPOSE_FILES='/home/administrator/ithute-pay/compose.yaml /home/administrator/ithute-pay/compose.vps.yaml /home/administrator/ithute-pay/compose.production-networks.yml /home/administrator/ithute-pay/compose.release-networks.yml /home/administrator/ithute-pay/compose.release-image.yml'
PAY_HEALTH_URL=https://api.pay.ithute.co.ls/health
PAY_API_URL=https://api.pay.ithute.co.ls/health
PAY_PORTAL_URL=https://portal.pay.ithute.co.ls/
PAY_BACKUP_DIR=/var/backups/ithutepay
CONFIG
sudo chmod 0600 /etc/ithutepay-deploy.conf
```

**Observed on VPS November 4, 2026:** The running ithute-pay project reports the five Compose files above, in that order; keep all five until an operator verifies the complete effective config. The final temporary Compose overlay explicitly overrides the hard-pinned `compose.release-image.yml` image and sets `RUN_MIGRATIONS_ON_START=false`. Confirm the effective app image, project and volume names against the live stack in a staging rehearsal. **Important:** The paths above are examples; the real VPS might use `.env.production` and/or other Compose files. Preserve the exact production Compose project name and all overlays. Verify `docker compose --env-file ... -f ... config` resolves the existing data volumes and networks before installing this command. `PAY_ENV_FILE` must contain the `DB_PASSWORD` and other values already used by the running stack. The script intentionally refuses initial installation; a currently healthy running app is required.

For a release **with no pending Alembic migrations**, deploy with:

```bash
pull pay latest
```

For a release with pending schema revisions, the command **stops without changing the running application**. First verify all migrations are expand-only and backward-compatible with the previous image, check backup retention and disk space, and have a human approve them. Then:

```bash
sudo env PAY_APPROVE_MIGRATIONS=yes /opt/ithutepay-deploy/pull-pay latest
```

That explicit approval backs up the database with `pg_dump -Fc`, runs `alembic upgrade head` once from the newly downloaded image, checks the Alembic revision, then replaces only the application container. Rollback restores the prior **application image**; a schema downgrade is not automatically safe and is not attempted.

## Release requirements

- Merge reviewed business features to `main`; confirm CI on the **main commit** published `latest`. Pull requests do not publish `latest`.
- Run all automated tests (including commercial quote/onboarding, provider regressions and financial integrity), build, staging-migration rehearsal, smoke checks and required approval in GitHub Actions **before** production.
- Confirm GHCR authentication on the VPS if the package is private, and the exact production Compose image is `IPB_IMAGE`-controlled.
- Test a broken-image rollback and a migration rejection in a **non-production duplicate**, including reverse proxy, worker drain and payment idempotency.
- Take regular off-server/restore-tested backups; `pg_dump` protects PostgreSQL only, not Redis, secrets, or other state.

## Known constraints to address next

The current Compose stack includes API, web and Celery processes in one image; restarting that container also restarts workers. A true zero-downtime financial deployment needs independent worker orchestration, graceful task handover, traffic-switched parallel app slots, explicit database compatibility gates and transaction-safe releases. This updater is a safety-oriented starting point, **not a guarantee of no client disruption**. Flutter requires a separate independently published and verified image path.
