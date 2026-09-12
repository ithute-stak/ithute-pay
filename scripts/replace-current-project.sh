#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-/home/selemela/Documents/GitHub/PayBridgeGateway}"
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$TARGET"
BACKUP="$TARGET/.source-backups/$STAMP"
mkdir -p "$BACKUP"

for path in apps/backend apps/frontend deploy packages docs .github; do
  if [[ -e "$TARGET/$path" ]]; then
    mkdir -p "$BACKUP/$(dirname "$path")"
    cp -a "$TARGET/$path" "$BACKUP/$path"
  fi
done

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
for f in apps/backend/.env apps/frontend/.env.local .env deploy/vps/.env; do
  if [[ -f "$TARGET/$f" ]]; then
    mkdir -p "$TMP/$(dirname "$f")"
    cp "$TARGET/$f" "$TMP/$f"
  fi
done

rm -rf \
  "$TARGET/apps/backend" \
  "$TARGET/apps/frontend" \
  "$TARGET/deploy" \
  "$TARGET/packages" \
  "$TARGET/docs" \
  "$TARGET/.github"

mkdir -p "$TARGET/apps"
rsync -a "$SOURCE/apps/backend/" "$TARGET/apps/backend/"
rsync -a "$SOURCE/apps/frontend/" "$TARGET/apps/frontend/"
rsync -a "$SOURCE/deploy/" "$TARGET/deploy/"
rsync -a "$SOURCE/packages/" "$TARGET/packages/"
rsync -a "$SOURCE/docs/" "$TARGET/docs/"
rsync -a "$SOURCE/.github/" "$TARGET/.github/"

for f in README.md RELEASE_NOTES.md Makefile pnpm-workspace.yaml compose.yaml compose.vps.yaml .env.example .gitignore; do
  [[ -e "$SOURCE/$f" ]] && cp -a "$SOURCE/$f" "$TARGET/$f"
done

for f in apps/backend/.env apps/frontend/.env.local .env deploy/vps/.env; do
  if [[ -f "$TMP/$f" ]]; then
    mkdir -p "$TARGET/$(dirname "$f")"
    cp "$TMP/$f" "$TARGET/$f"
  fi
done

printf '\nInstalled clean Ithute Pay Bridge source into:\n  %s\n' "$TARGET"
printf 'Previous source snapshot:\n  %s\n\n' "$BACKUP"
