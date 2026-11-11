#!/usr/bin/env bash
# NabuStation: small interactive installer for the HA host.
#
# The station module must run on the station itself:
#   scp -r NabuStation root@<STATION_IP>:/root/
#   ssh root@<STATION_IP> 'cd /root/NabuStation && SNAPCAST_HOST=<HA_IP> ./station/install.sh'
#
# This menu covers the HA-host pieces: voice server, Silero, HA packages,
# MA Spotify patch and diagnostics.
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CONFIG_DIR="${CONFIG_DIR:-/config}"
MA_CONTAINER="${MA_CONTAINER:-music-assistant}"
HA_CONTAINER="${HA_CONTAINER:-homeassistant}"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

say() { printf '\n%s\n' "$*"; }

menu() {
  cat <<'EOF'
NabuStation installer

  1) Station module (print the command to run on the station)
  2) Voice server (this HA host)
  3) Silero TTS (Docker)
  4) Home Assistant packages + custom sentences
  5) Music Assistant Spotify like/unlike patch
  6) Doctor (reachability check)
  0) Exit
EOF
}

copy_ha() {
  if [ ! -d "$CONFIG_DIR" ]; then
    say "No $CONFIG_DIR here. Copy the files manually (see home-assistant/install.md)."
    return
  fi
  mkdir -p "$CONFIG_DIR/packages" "$CONFIG_DIR/custom_sentences/ru" "$CONFIG_DIR/scripts"
  cp "$ROOT/home-assistant/packages/nabustation_helpers.yaml" "$CONFIG_DIR/packages/"
  cp "$ROOT/home-assistant/packages/nabustation_core.yaml" "$CONFIG_DIR/packages/"
  cp "$ROOT/home-assistant/custom_sentences/ru/music_core.yaml" "$CONFIG_DIR/custom_sentences/ru/"
  read -r -p "Install volume package? [y/N]: " ans
  if [ "${ans:-n}" = "y" ] || [ "${ans:-n}" = "Y" ]; then
    cp "$ROOT/home-assistant/packages/nabustation_volume.yaml" "$CONFIG_DIR/packages/"
    cp "$ROOT/home-assistant/custom_sentences/ru/volume.yaml" "$CONFIG_DIR/custom_sentences/ru/"
  fi
  read -r -p "Install Spotify package? [y/N]: " ans
  if [ "${ans:-n}" = "y" ] || [ "${ans:-n}" = "Y" ]; then
    cp "$ROOT/home-assistant/packages/nabustation_spotify.yaml" "$CONFIG_DIR/packages/"
    cp "$ROOT/home-assistant/custom_sentences/ru/music_spotify.yaml" "$CONFIG_DIR/custom_sentences/ru/"
    cp "$ROOT/home-assistant/scripts/music_like.py" "$CONFIG_DIR/scripts/"
    [ -f "$CONFIG_DIR/nabustation.json" ] || cp "$ROOT/home-assistant/nabustation.json.example" "$CONFIG_DIR/nabustation.json"
  fi
  say "Copied. Ensure configuration.yaml has:"
  echo "  homeassistant:"
  echo "    packages: !include_dir_named packages"
  say "Then restart HA (ha core restart)."
}

patch_ma() {
  docker cp "$ROOT/music-assistant/patch_spotify_like.py" "$MA_CONTAINER:/data/patch_spotify_like.py"
  docker exec -i "$MA_CONTAINER" python /data/patch_spotify_like.py
  docker restart "$MA_CONTAINER"
}

while true; do
  menu
  read -r -p "Select: " choice
  case "$choice" in
    1)
      say "On the station:"
      echo "  scp -r NabuStation root@<STATION_IP>:/root/"
      echo "  ssh root@<STATION_IP>"
      echo "  cd /root/NabuStation && SNAPCAST_HOST=<HA_IP> ./station/install.sh"
      ;;
    2) "$ROOT/voice-server/install.sh" ;;
    3) (cd "$ROOT/silero-tts" && docker compose up -d --build) ;;
    4) copy_ha ;;
    5) patch_ma ;;
    6) "$ROOT/tools/doctor.sh" ;;
    0) exit 0 ;;
    *) echo "Unknown choice" ;;
  esac
done
