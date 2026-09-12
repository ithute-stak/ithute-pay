# Direct Ubuntu deployment alternative

Docker/GHCR is the preferred deployment for this release, but the project can also run directly under systemd.

Application root: `/opt/ithute-pay-bridge`.

## Backend

```bash
cd /opt/ithute-pay-bridge/apps/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m alembic upgrade head
python -m scripts.bootstrap
```

The systemd backend binds `127.0.0.1:8001`.

## Frontend

```bash
cd /opt/ithute-pay-bridge/apps/frontend
pnpm install
cp .env.example .env.production
pnpm typecheck
pnpm build
```

The systemd frontend binds `127.0.0.1:3001`.

## Services

```bash
sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now paybridge-backend paybridge-worker paybridge-beat paybridge-frontend
```

## Nginx

Use `deploy/nginx/host-paybridge.conf`. It listens on port `8081`, so the existing LoanHub Nginx site can continue owning port 80.
