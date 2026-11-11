#!/usr/bin/env bash
# Build the NabuStation phone remote APK.
#
# Requirements: Android SDK (platform 34 + build-tools 35), JDK 17+.
#   ANDROID_HOME=/path/to/sdk ./build_apk.sh
set -euo pipefail

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
if [ -z "$SDK" ] || [ ! -d "$SDK" ]; then
  echo "Set ANDROID_HOME to the Android SDK directory." >&2
  exit 1
fi
BUILD_TOOLS=$(find "$SDK/build-tools" -maxdepth 1 -mindepth 1 -type d | sort -V | tail -1)
PLATFORM="$SDK/platforms/android-34/android.jar"
[ -f "$PLATFORM" ] || PLATFORM=$(find "$SDK/platforms" -name android.jar | sort -V | tail -1)
[ -f "$PLATFORM" ] || { echo "android.jar not found" >&2; exit 1; }

AAPT="$BUILD_TOOLS/aapt"
D8="$BUILD_TOOLS/d8"
ZIPALIGN="$BUILD_TOOLS/zipalign"
APKSIGNER="$BUILD_TOOLS/apksigner"
for tool in "$AAPT" "$D8" "$ZIPALIGN" "$APKSIGNER"; do
  [ -x "$tool" ] || { echo "Missing $tool" >&2; exit 1; }
done

BUILD="$HERE/app/build"
rm -rf "$BUILD"
mkdir -p "$BUILD/gen" "$BUILD/classes" "$BUILD/dex"

"$AAPT" package -f -m -J "$BUILD/gen" \
  -M "$HERE/app/AndroidManifest.xml" -S "$HERE/app/res" -I "$PLATFORM" \
  --min-sdk-version 21 --target-sdk-version 23

JAVAC="${JAVAC:-javac}"
"$JAVAC" -source 8 -target 8 -bootclasspath "$PLATFORM" \
  -d "$BUILD/classes" \
  "$BUILD/gen/ru/station/remote/R.java" \
  "$HERE/app/src/ru/station/remote/MainActivity.java"

"$D8" --lib "$PLATFORM" --min-api 21 --output "$BUILD/dex" \
  $(find "$BUILD/classes" -name '*.class')

"$AAPT" package -f -M "$HERE/app/AndroidManifest.xml" -S "$HERE/app/res" \
  -I "$PLATFORM" -F "$BUILD/app-unsigned.apk"
(cd "$BUILD/dex" && "$AAPT" add "$BUILD/app-unsigned.apk" classes.dex)
"$ZIPALIGN" -f 4 "$BUILD/app-unsigned.apk" "$BUILD/app-aligned.apk"
"$APKSIGNER" sign --ks "$HERE/app/debug.keystore" \
  --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android \
  --out "$HERE/app/station-remote-modes.apk" "$BUILD/app-aligned.apk"

echo "Built $HERE/app/station-remote-modes.apk"
