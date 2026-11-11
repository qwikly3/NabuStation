#!/usr/bin/env bash
# Build the Android station-side RemoteDaemon jar (dex in a zip).
#
# Requirements: JDK 17+, Android SDK platform 34 + build-tools.
#   ANDROID_HOME=/path/to/sdk ./build_daemon.sh
set -euo pipefail

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
[ -n "$SDK" ] && [ -d "$SDK" ] || { echo "Set ANDROID_HOME." >&2; exit 1; }
BUILD_TOOLS=$(find "$SDK/build-tools" -maxdepth 1 -mindepth 1 -type d | sort -V | tail -1)
PLATFORM="$SDK/platforms/android-34/android.jar"
[ -f "$PLATFORM" ] || PLATFORM=$(find "$SDK/platforms" -name android.jar | sort -V | tail -1)
D8="$BUILD_TOOLS/d8"
JAVAC="${JAVAC:-javac}"

BUILD="$HERE/build"
rm -rf "$BUILD"
mkdir -p "$BUILD/classes" "$BUILD/dex"

"$JAVAC" -source 8 -target 8 -bootclasspath "$PLATFORM" \
  -d "$BUILD/classes" "$HERE/src/station/RemoteDaemon.java"
"$D8" --lib "$PLATFORM" --min-api 21 --output "$BUILD/dex" \
  $(find "$BUILD/classes" -name '*.class')

mkdir -p "$BUILD/jar"
cp "$BUILD/dex/classes.dex" "$BUILD/jar/classes.dex"
mkdir -p "$BUILD/jar/META-INF"
printf 'Manifest-Version: 1.0\nCreated-By: NabuStation\n\n' > "$BUILD/jar/META-INF/MANIFEST.MF"
(cd "$BUILD/jar" && zip -q -r "$HERE/remote-daemon.jar" .)
echo "Built $HERE/remote-daemon.jar"
