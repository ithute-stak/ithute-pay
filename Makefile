.PHONY: migrate bootstrap test backend frontend worker beat typecheck build docker-up

migrate:
	cd apps/backend && python -m alembic upgrade head

bootstrap:
	cd apps/backend && python -m scripts.bootstrap

test:
	cd apps/backend && PYTHONPATH=. pytest -q

backend:
	cd apps/backend && python -m uvicorn main:app --reload --host 127.0.0.1 --port 8001

frontend:
	cd apps/frontend && pnpm dev --hostname 127.0.0.1 --port 3001

typecheck:
	cd apps/frontend && pnpm typecheck

build:
	cd apps/frontend && pnpm build

worker:
	cd apps/backend && celery -A workers.celery_app.celery_app worker --loglevel=INFO

beat:
	cd apps/backend && celery -A workers.celery_app.celery_app beat --loglevel=INFO

docker-up:
	docker compose up -d --build
