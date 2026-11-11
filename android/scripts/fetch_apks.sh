#!/usr/bin/env bash
# Download the NabuStation Android APKs from the GitHub release.
#
#   ./android/scripts/fetch_apks.sh
#
# Override with:
#   NABUSTATION_REPO=user/repo NABUSTATION_VERSION=v1.0.0 ./fetch_apks.sh
set -euo pipefail

ANDROID_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEST="${1:-$ANDROID_DIR/apk}"
REPO="${NABUSTATION_REPO:-qwikly3/NabuStation}"
TAG="${NABUSTATION_VERSION:-v1.0.0}"
BASE="https://github.com/$REPO/releases/download/$TAG"

ASSETS="nowplaying.apk station-remote-modes.apk tvlauncher.apk snapcast.apk smarttube-32.68.apk lite-tv-launcher-v1.0.apk"

mkdir -p "$DEST"
echo "Release: $BASE"
curl -fL --retry 3 --retry-delay 2 "$BASE/SHA256SUMS" -o "$DEST/SHA256SUMS"
# Keep checksum parsing portable even if the asset was uploaded with CRLF.
tr -d '\r' < "$DEST/SHA256SUMS" > "$DEST/SHA256SUMS.lf"
mv "$DEST/SHA256SUMS.lf" "$DEST/SHA256SUMS"

for asset in $ASSETS; do
  if [ -f "$DEST/$asset" ]; then
    echo "  exists $asset"
  else
    echo "  download $asset"
    curl -fL --retry 3 --retry-delay 2 "$BASE/$asset" -o "$DEST/$asset"
  fi
done

echo "Verifying checksums"
if command -v sha256sum >/dev/null 2>&1; then
  (cd "$DEST" && sha256sum -c SHA256SUMS)
elif command -v shasum >/dev/null 2>&1; then
  (cd "$DEST" && shasum -a 256 -c SHA256SUMS)
else
  echo "sha256sum/shasum not found; skipped checksum verification." >&2
fi
echo "APKs ready in $DEST"
