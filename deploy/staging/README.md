# Isolated IthutePay staging stack

This is a **non-production, no-provider-egress** Compose stack. Do not combine
`deploy/staging/compose.yaml` with the production `compose.yaml`, do not
mount production volumes, and do not deploy it to the production network.

## Preconditions

1. All required CI checks are green for the **exact** source SHA. PR image
   builds are not published; obtain a separately approved image from GHCR,
   inspect its provenance and source SHA, and pin the **real registry digest**.
2. Create a staging-only secret file **outside the repository** with mode
   0600. Use fresh database and app signing/encryption secrets, not production
   credentials. Set `STAGING_ENV_FILE` to its absolute path. Do not commit,
   log, email or attach that file.
3. Provide a staging-only PostgreSQL password through the operator's shell or
   secrets manager. Avoid URL-reserved characters in this Compose variant,
   because the password is injected into a PostgreSQL connection URL. In
   production prefer secret mounts or structured connection settings.
4. Complete the separate non-secret release manifest check:
   `python apps/backend/scripts/staging_preflight.py /path/to/manifest.json`.
   The manifest requires backup and migration review evidence as explicit
   operator gates; CI cannot assert those on the operator's behalf.

## Review the intended stack (does not start it)

```bash
export STAGING_IMAGE='ghcr.io/ithute-stak/ithute-pay@sha256:<verified-image-digest>'
export STAGING_ENV_FILE='/absolute/path/to/staging-only.env'
# Set STAGING_DB_PASSWORD securely in the operator environment.
docker compose -f deploy/staging/compose.yaml config --quiet
```

The complete stack uses an isolated project and newly created volumes named
under `ithutepay-staging`. It has no shared production networks or containers.
No host ports are exposed. Docker's fully internal bridge prevents access
from the host through published ports and blocks container-to-Internet
payment-provider requests. Run the read-only smoke check via `compose exec`.

## Migration and start (only after change approval)

The application supervisor normally runs Alembic automatically, but staging
explicitly overrides `RUN_MIGRATIONS_ON_START=false`.

On an authorised test host with a clean staging database or a separately
restored, sanitised snapshot, start only database and Redis:

```bash
docker compose -f deploy/staging/compose.yaml up -d --wait --wait-timeout 120 postgres redis
```

Run migrations **explicitly** after review, using the image, Compose
network and *only* the staging database. The migration process must run
from `/app/backend` where the Alembic configuration lives:

```bash
docker compose -f deploy/staging/compose.yaml run --rm --no-deps \
  --workdir /app/backend --entrypoint python app -m alembic upgrade head
```

Start the combined staging app only after migrations succeed:

```bash
docker compose -f deploy/staging/compose.yaml up -d app
docker compose -f deploy/staging/compose.yaml exec -T app python \
  /app/backend/scripts/staging_postdeploy_smoke.py --api-port 8001 --web-port 3001
```

Never pass the staging Compose project name to a production Docker command.
Never run `down -v` until separately approved data destruction is intended.

## Safety limitations

- CI validates Compose structure and interpolation, but does not deploy an
  image or prove a GHCR registry digest exists.
- Staging is intentionally offline. External provider sandbox certification
  requires a **separate** approved environment, controlled credentials and
  recorded transaction/callback evidence.
- Fully isolated staging exposes no ports, not even to the host. The smoke
  probe runs *inside* the app container, so no web access is implied.
- The combined application's production default starts Celery worker and beat;
  this stack explicitly sets `RUN_BACKGROUND_JOBS=false` to suppress both.
  Do not enable scheduled payment settlement or payout recovery on staging.
- Docker network isolation does not replace host firewall and operator access
  controls.


## Read-only post-deployment smoke (after approved deployment)

After the isolated stack is started, execute the test **inside the isolated
app container** from the staging host:

```bash
docker compose -f deploy/staging/compose.yaml exec -T app python \
  /app/backend/scripts/staging_postdeploy_smoke.py --api-port 8001 --web-port 3001
```

The script connects only to `127.0.0.1:8001` and `127.0.0.1:3001`
*inside the container*.
It verifies `GET /` identifies the running API as **staging**, `GET /health`
returns a database-backed healthy response, and the public frontend sign-in page at `/login` returns
HTTP 200 HTML. The root path deliberately redirects to `/dashboard` and
is not a suitable strict 200-only readiness probe. The client never follows redirects, authenticates or sends a
payment request. It uses no secrets and cannot prove financial transactions,
authentication or external provider connectivity. A failure is a **NO-GO**
for staged rollout.

CI runs a separate mock-backed test of the smoke script itself. CI does **not**
claim to have started the pinned staging image or inspected a real staging
server. Record the actual output, image digest, environment and backup review
in the approved release evidence before any deployment decision.


## Automated candidate-image rehearsal in pull requests

The `Build IthutePay VPS image` workflow now loads the **locally built PR
image**, compiles its partner API base as `/api/v1` instead of the production
partner endpoint, creates only disposable CI PostgreSQL/Redis volumes, runs
Alembic explicitly, verifies that the effective database revision matches
Alembic head, checks the running container's disabled payment and background
job switches (including the absence of Celery processes), and exercises the
read-only post-deployment smoke test
against the actual FastAPI/Next.js container. The private Docker bridge blocks
container egress to payment providers. The CI job removes its disposable
volumes and secrets on exit.

This rehearsal uses a temporary **local SHA-tagged candidate**, not a
published/verified GHCR digest. It does not deploy to a VPS, cannot certify
third-party sandboxes, and cannot substitute for the independent
digest/provenance check or the separate operator-approved staging deployment.


## Auditable CI rehearsal evidence

After a successful PR container rehearsal, the VPS image workflow uploads
`ithutepay-pr-staging-rehearsal/rehearsal.json` as a GitHub Actions artifact.
The non-secret report contains the actual checked-out commit, PR head SHA,
local Docker image ID, workflow run ID and explicitly scoped test results.
It is generated **only after** the container smoke test passes, and the
artifact upload must also succeed for the build job to pass.

The Docker image ID in the report is a **local image ID**, not a registry
digest or production deployment artifact. The report explicitly marks
registry publication, external provider certification and an operator staging
deployment as **false**. Operators must independently verify the later
published image digest, build provenance, migration/restore evidence and
provider certification before approving any actual staging or production
release.
