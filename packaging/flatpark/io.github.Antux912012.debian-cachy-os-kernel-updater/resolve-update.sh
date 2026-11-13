#!/usr/bin/env bash
set -euo pipefail

REPO="Antux912012/debian-cachy-os-kernel-updater"
API_URL="https://api.github.com/repos/${REPO}/releases/latest"

RELEASE_JSON=$(curl -fsSL -H "Accept: application/vnd.github+json" "$API_URL")
ASSET_URL=$(printf '%s' "$RELEASE_JSON" | python3 -c '
import json, sys, re
data = json.load(sys.stdin)
for a in data.get("assets", []):
    if re.search(r"cachy-kernel-updater_.*_all\.deb$", a.get("name", "")):
        print(a["browser_download_url"])
        break
')

if [[ -z "$ASSET_URL" ]]; then
    echo "No matching .deb release asset found for ${REPO}" >&2
    exit 1
fi

TMP_DEB=$(mktemp /tmp/cachy-updater-XXXXXX.deb)
trap 'rm -f "$TMP_DEB"' EXIT
curl -fsSL -o "$TMP_DEB" "$ASSET_URL"

SHA256=$(sha256sum "$TMP_DEB" | awk '{print $1}')
SIZE=$(stat -c%s "$TMP_DEB")

printf 'url=%s\nsha256=%s\nsize=%s\n' "$ASSET_URL" "$SHA256" "$SIZE"
