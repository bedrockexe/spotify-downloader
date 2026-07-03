"""Fetch lyrics from LRCLIB (free, no API key required).

Returns synced lyrics (LRC, with timestamps) when available plus a plain-text
version. Synced lyrics are written as a sidecar ``.lrc`` file next to the audio;
the plain text is embedded into the tag by ``metadata.embed``.
"""

from pathlib import Path

import requests

_BASE = "https://lrclib.net/api"
_HEADERS = {"User-Agent": "SpotifyDownloader/1.0 (personal use)"}


def fetch_lyrics(title, artist, album=None):
    """Return ``(synced_lrc, plain_text)`` — either may be None."""
    try:
        params = {"track_name": title, "artist_name": artist}
        if album:
            params["album_name"] = album
        response = requests.get(
            f"{_BASE}/get", params=params, headers=_HEADERS, timeout=20
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("syncedLyrics"), data.get("plainLyrics")
    except Exception:
        pass

    # Fall back to a fuzzy search if the exact lookup missed.
    try:
        response = requests.get(
            f"{_BASE}/search",
            params={"track_name": title, "artist_name": artist},
            headers=_HEADERS,
            timeout=20,
        )
        if response.status_code == 200:
            results = response.json()
            if results:
                first = results[0]
                return first.get("syncedLyrics"), first.get("plainLyrics")
    except Exception:
        pass

    return None, None


def write_lrc(synced_lyrics, path):
    """Write an .lrc sidecar file. Returns True if something was written."""
    if not synced_lyrics:
        return False
    Path(path).write_text(synced_lyrics, encoding="utf-8")
    return True
