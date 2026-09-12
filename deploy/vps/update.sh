#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

COMPOSE=(docker compose -f compose.vps.yaml)

"${COMPOSE[@]}" pull ithute-pay-bridge
"${COMPOSE[@]}" up -d postgres redis
"${COMPOSE[@]}" up -d --force-recreate ithute-pay-bridge
"${COMPOSE[@]}" ps

printf '\nIthute Pay Bridge health:\n'
curl -fsS http://127.0.0.1:8001/health || true
printf '\n'
