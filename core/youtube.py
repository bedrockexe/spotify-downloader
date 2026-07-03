"""Resolve a Spotify track to a YouTube Music URL via ytmusicapi search."""

import threading

from ytmusicapi import YTMusic

_yt = None
_yt_lock = threading.Lock()


def _client():
    """Lazily create a single shared YTMusic client (searches are read-only)."""
    global _yt
    if _yt is None:
        with _yt_lock:
            if _yt is None:
                _yt = YTMusic()
    return _yt


def _first_playable(results):
    for result in results:
        if result.get("resultType") in ("song", "video") and result.get("videoId"):
            return f"https://music.youtube.com/watch?v={result['videoId']}"
    return None


def find_audio_url(title, artist):
    """Return the best-matching YouTube Music watch URL, or None."""
    yt = _client()
    query = f"{title} {artist}".strip()
    # Prefer official "song" results, then fall back to a broad search.
    url = _first_playable(yt.search(query, filter="songs"))
    if url:
        return url
    return _first_playable(yt.search(query))
