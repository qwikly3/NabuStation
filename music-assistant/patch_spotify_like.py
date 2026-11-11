"""Add a precise Spotify liked-songs API command to Music Assistant.

Music Assistant's Spotify provider already exposes library_add/library_remove,
but the public "remove from library" API deletes the MA library item as well.
For voice control we only want to change Spotify 'Liked Songs', leaving the
queue and the MA library item alone.  This patch registers a small
`spotify/set_liked` websocket command on the provider instance.

Idempotent: running it twice does nothing.
"""
from __future__ import annotations

import glob
import py_compile
import shutil
from pathlib import Path

_CANDIDATES = (
    glob.glob(
        "/app/venv/lib/python*/site-packages/music_assistant/providers/spotify/provider.py"
    )
    + glob.glob(
        "/usr/local/lib/python*/site-packages/music_assistant/providers/spotify/provider.py"
    )
)
if not _CANDIDATES:
    raise SystemExit(
        "Music Assistant Spotify provider.py not found. "
        "Run this script inside the music-assistant container."
    )
PATH = Path(_CANDIDATES[0])
BACKUP = Path("/data/provider.py.bak-spotify-like")

METHOD = '''    async def set_liked(self, track_id: str, liked: bool) -> None:
        """Set Spotify 'Liked Songs' state for one track only."""
        uri = f"spotify:track:{track_id}"
        if liked:
            await self._put_data("me/library", uris=uri)
        else:
            await self._delete_data("me/library", uris=uri)

'''

REGISTER = '''        self._unregister_set_liked = self.mass.register_api_command(
            "spotify/set_liked", self.set_liked
        )

'''

UNREGISTER = '''        if unregister := getattr(self, "_unregister_set_liked", None):
            unregister()
            self._unregister_set_liked = None
'''

ANCHOR_METHOD = "    async def add_playlist_tracks(self, prov_playlist_id: str, prov_track_ids: list[str]) -> None:\n"
ANCHOR_REGISTER = "            await asyncio.to_thread(self._remove_unused_playback_credentials)\n        except BaseException:\n"
ANCHOR_REGISTER_END = "                await self.backend.unload()\n            raise\n\n    async def unload(self, is_removed: bool = False) -> None:\n"
ANCHOR_UNLOAD = '    async def unload(self, is_removed: bool = False) -> None:\n        """Handle close/cleanup of the provider."""\n        try:\n'


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    if "async def set_liked" in text:
        print("already patched")
        return
    if not BACKUP.exists():
        shutil.copy2(PATH, BACKUP)
        print("backup", BACKUP)
    for anchor in (ANCHOR_METHOD, ANCHOR_REGISTER, ANCHOR_REGISTER_END, ANCHOR_UNLOAD):
        if text.count(anchor) != 1:
            raise SystemExit(f"anchor count {text.count(anchor)} for {anchor[:60]!r}")
    text = text.replace(ANCHOR_METHOD, METHOD + ANCHOR_METHOD, 1)
    # Register after the successful try/except block, at the end of handle_async_init.
    text = text.replace(
        ANCHOR_REGISTER_END,
        "                await self.backend.unload()\n            raise\n\n"
        + REGISTER
        + "    async def unload(self, is_removed: bool = False) -> None:\n",
        1,
    )
    text = text.replace(
        ANCHOR_UNLOAD,
        '    async def unload(self, is_removed: bool = False) -> None:\n'
        '        """Handle close/cleanup of the provider."""\n'
        + UNREGISTER
        + "        try:\n",
        1,
    )
    PATH.write_text(text, encoding="utf-8")
    py_compile.compile(str(PATH), doraise=True)
    print("patched", PATH)


if __name__ == "__main__":
    main()
