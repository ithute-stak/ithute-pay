# Ithute Pay Bridge unified application image.
# FastAPI :8001 + Next.js :3001 + Celery worker + Celery beat run in one app container.

FROM node:22-bookworm-slim AS frontend-deps
WORKDIR /build/frontend
RUN corepack enable
COPY apps/frontend/package.json ./
RUN pnpm install --frozen-lockfile=false

FROM frontend-deps AS frontend-builder
COPY apps/frontend/ ./
ARG BACKEND_INTERNAL_URL=http://127.0.0.1:8001
ARG NEXT_PUBLIC_API_BASE=/api/v1
ARG NEXT_PUBLIC_PARTNER_API_BASE=https://api.pay.ithute.co.ls/api/v1
ARG NEXT_PUBLIC_WS_URL=
ENV BACKEND_INTERNAL_URL=${BACKEND_INTERNAL_URL} \
    NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE} \
    NEXT_PUBLIC_PARTNER_API_BASE=${NEXT_PUBLIC_PARTNER_API_BASE} \
    NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL}
RUN pnpm build

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NODE_ENV=production \
    BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=8001 \
    FRONTEND_PORT=3001 \
    PORT=3001 \
    HOSTNAME=0.0.0.0 \
    BACKEND_INTERNAL_URL=http://127.0.0.1:8001 \
    NEXT_PUBLIC_API_BASE=/api/v1 \
    NEXT_PUBLIC_PARTNER_API_BASE=https://api.pay.ithute.co.ls/api/v1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libgcc-s1 \
        libpq5 \
        libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# Node is copied from the official Node 22 image so Next.js can run beside Python.
COPY --from=frontend-builder /usr/local/bin/node /usr/local/bin/node

# Backend runtime.
COPY apps/backend/requirements.txt /app/backend/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/backend/requirements.txt
COPY apps/backend/ /app/backend/
RUN cd /app/backend \
    && python -m compileall -q api core database routers services integrations utils workers scripts main.py

# Next.js standalone production runtime.
COPY --from=frontend-builder /build/frontend/public /app/frontend/public
COPY --from=frontend-builder /build/frontend/.next/standalone /app/frontend
COPY --from=frontend-builder /build/frontend/.next/static /app/frontend/.next/static

# Unified process supervisor.
COPY deploy/container/run_combined.py /app/run_combined.py

EXPOSE 8001 3001

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8001/health >/dev/null \
      && curl -fsS http://127.0.0.1:3001/ >/dev/null || exit 1

CMD ["python", "/app/run_combined.py"]
