#!/usr/bin/env python3
"""Patch the prebuilt Now Playing APK's visualizer host.

The prebuilt APK contains the placeholder host ``192.168.01.20`` (13 chars,
same as 192.168.1.20).  Android/Java resolves the leading-zero octet as a
normal IPv4 address.  Replace it with your HA host and re-sign the APK.

Usage:
    python patch_host.py --host 192.168.01.20

The host must be exactly 13 characters.  If your HA IP is shorter, pad one
octet with a leading zero, e.g. 192.168.1.20 -> 192.168.01.20.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import tempfile
import zipfile
import zlib
from pathlib import Path

PLACEHOLDER = b"192.168.01.20"
HERE = Path(__file__).resolve().parent
DEFAULT_APK = HERE.parent / "apk" / "nowplaying.apk"
KEYSTORE = HERE.parent / "remote" / "app" / "debug.keystore"


def fix_dex(dex: bytearray) -> None:
    dex[12:32] = hashlib.sha1(dex[32:]).digest()
    checksum = zlib.adler32(bytes(dex[12:])) & 0xFFFFFFFF
    dex[8:12] = struct.pack("<I", checksum)


def rebuild(src: Path, dst: Path, host: bytes) -> None:
    with zipfile.ZipFile(src, "r") as zin:
        entries = {info.filename: (info, zin.read(info.filename)) for info in zin.infolist()}
    info, dex = entries["classes.dex"]
    if dex.count(PLACEHOLDER) == 0:
        raise SystemExit("placeholder host not found in classes.dex")
    dex = bytearray(dex.replace(PLACEHOLDER, host))
    fix_dex(dex)
    entries["classes.dex"] = (info, bytes(dex))
    with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name, (info, data) in entries.items():
            if name.startswith("META-INF/") and name.upper().endswith(
                (".SF", ".RSA", ".DSA", ".MF")
            ):
                continue
            zout.writestr(name, data)


def find_tool(name: str) -> str | None:
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if sdk:
        root = Path(sdk) / "build-tools"
        if root.is_dir():
            suffixes = ("", ".exe", ".bat") if os.name == "nt" else ("",)
            for version in sorted(root.iterdir(), reverse=True):
                for suffix in suffixes:
                    candidate = version / (name + suffix)
                    if candidate.exists():
                        return str(candidate)
    return shutil.which(name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True, help="13-character IPv4 host")
    parser.add_argument("--apk", type=Path, default=DEFAULT_APK)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    host = args.host.encode()
    if len(host) != len(PLACEHOLDER):
        raise SystemExit(
            f"host must be {len(PLACEHOLDER)} characters, got {len(host)}: {args.host}"
        )
    out = args.out or (HERE / f"nowplaying-{args.host}.apk")
    unsigned = Path(tempfile.gettempdir()) / "nabustation-nowplaying-unsigned.apk"
    aligned = Path(tempfile.gettempdir()) / "nabustation-nowplaying-aligned.apk"
    rebuild(args.apk, unsigned, host)

    zipalign = find_tool("zipalign")
    apksigner = find_tool("apksigner")
    if not zipalign or not apksigner:
        print(f"Unsigned APK: {unsigned}")
        print("Set ANDROID_HOME or install build-tools to sign it.")
        return
    subprocess.run([zipalign, "-f", "4", str(unsigned), str(aligned)], check=True)
    subprocess.run(
        [
            apksigner,
            "sign",
            "--ks",
            str(KEYSTORE),
            "--ks-key-alias",
            "androiddebugkey",
            "--ks-pass",
            "pass:android",
            "--key-pass",
            "pass:android",
            "--out",
            str(out),
            str(aligned),
        ],
        check=True,
    )
    print(f"Signed APK: {out}")


if __name__ == "__main__":
    main()
