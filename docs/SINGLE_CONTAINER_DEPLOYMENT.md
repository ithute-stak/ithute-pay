# Single application container deployment

Ithute Pay Bridge now publishes one application image:

```text
ghcr.io/ithutesolhub-sketch/ithute-pay-bridge:latest
```

The `app` container runs all application processes:

- FastAPI on port `8001`
- Next.js on port `3001`
- Celery worker
- Celery beat
- Alembic migration before services start

PostgreSQL and Redis remain separate infrastructure containers so their data lifecycle is independent from the application image.

## VPS topology

```text
Host Nginx :8081
  ├── /api, /docs, /health, /api/v1/ws -> ithute-pay-bridge:8001
  └── everything else                  -> ithute-pay-bridge:3001

Docker
  ├── app       (one GHCR image)
  ├── postgres
  └── redis
```

LoanHub can continue using host port `80`; Ithute Pay Bridge uses `8081`.

## Upgrade

```bash
cd /opt/ithute-pay-bridge/source
git pull
docker compose -f compose.vps.yaml pull ithute-pay-bridge
docker compose -f compose.vps.yaml up -d postgres redis
docker compose -f compose.vps.yaml up -d --force-recreate ithute-pay-bridge
docker compose -f compose.vps.yaml ps
curl http://127.0.0.1:8001/health
```

Do not use `docker compose down -v` for routine updates.
