# Docker, GitHub and VPS deployment

## Published image

GitHub Actions builds one unified application image:

```text
ghcr.io/<owner>/ithute-pay-bridge:latest
```

A commit SHA tag is also published for rollback.

The one application container runs FastAPI `:8001`, Next.js `:3001`, the Celery worker and Celery beat. PostgreSQL and Redis remain separate data/infrastructure containers.

## VPS layout

Recommended directory: `/opt/ithute-pay-bridge/source`.

Configure `.env` using `deploy/vps/.env.vps.example`, then:

```bash
cd /opt/ithute-pay-bridge/source
docker login ghcr.io
./deploy/vps/update.sh
```

The application container binds:

- FastAPI -> `127.0.0.1:8001`
- Next.js -> `127.0.0.1:3001`
- PostgreSQL and Redis -> Docker network only

Install `deploy/nginx/host-paybridge.conf` to expose `169.255.58.185:8081` while LoanHub remains on port `80`.

```bash
sudo cp deploy/nginx/host-paybridge.conf /etc/nginx/sites-available/ithute-pay-bridge
sudo ln -sf /etc/nginx/sites-available/ithute-pay-bridge /etc/nginx/sites-enabled/ithute-pay-bridge
sudo nginx -t
sudo systemctl reload nginx
```

## Update flow

After GitHub Actions publishes a new image:

```bash
cd /opt/ithute-pay-bridge/source
git pull
./deploy/vps/update.sh
```

The app runs Alembic `upgrade head` at container startup before FastAPI, Next.js and background workers are launched. The update does not destroy database or Redis volumes.
