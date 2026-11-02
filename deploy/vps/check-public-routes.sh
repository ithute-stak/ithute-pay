#!/usr/bin/env bash
# Read-only production check: returns nonzero on wrong public responses.
set -euo pipefail

PORTAL_URL="${PORTAL_URL:-https://portal.pay.ithute.co.ls/}"
API_URL="${API_URL:-https://api.pay.ithute.co.ls/}"
TIMEOUT="${TIMEOUT:-15}"

check() {
  local label="$1" url="$2" expected="$3" status
  if ! status="$(curl --silent --show-error --output /dev/null --max-time "$TIMEOUT" --write-out '%{http_code}' "$url")"; then
    printf 'FAIL %s: unable to reach %s\n' "$label" "$url" >&2
    return 1
  fi
  case "$status" in
    200|301|302|303|307|308)
      printf 'OK   %s: HTTP %s (%s)\n' "$label" "$status" "$url" ;;
    *)
      printf 'FAIL %s: HTTP %s (%s); expected %s\n' "$label" "$status" "$url" "$expected" >&2
      return 1 ;;
  esac
}

failed=0
check "Merchant portal" "$PORTAL_URL" "200 or redirect" || failed=1
# API root is expected to return HTTP 200 in this production deployment.
api_status="$(curl --silent --show-error --output /dev/null --max-time "$TIMEOUT" --write-out '%{http_code}' "$API_URL")" || api_status="000"
if [[ "$api_status" == "200" ]]; then
  printf 'OK   API: HTTP %s (%s)\n' "$api_status" "$API_URL"
else
  printf 'FAIL API: HTTP %s (%s); expected 200\n' "$api_status" "$API_URL" >&2
  failed=1
fi
exit "$failed"
