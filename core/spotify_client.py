"""Read track lists from Spotify.

Supports playlists, albums and single tracks, and — unlike the old versions —
follows pagination so playlists longer than 100 songs are fully captured.
"""

import logging
import re
from dataclasses import dataclass

import requests
from spotipy import Spotify
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyClientCredentials

# spotipy dumps full HTTP error tracebacks to stderr; we translate failures into
# friendly messages ourselves, so keep its own logger quiet.
logging.getLogger("spotipy").setLevel(logging.CRITICAL)

_URL_RE = re.compile(r"open\.spotify\.com/(playlist|album|track)/([A-Za-z0-9]+)")
_URI_RE = re.compile(r"spotify:(playlist|album|track):([A-Za-z0-9]+)")


@dataclass
class Track:
    title: str
    artist: str
    album: str = ""
    album_artist: str = ""
    year: str = ""
    cover_url: str | None = None
    duration_ms: int = 0


def make_client_credentials(client_id, client_secret):
    """Build an app-only (Client Credentials) Spotify client.

    Good for tracks and albums; Spotify blocks playlist tracks for this token.
    MemoryCacheHandler keeps the token in RAM so no .cache file is written.
    """
    manager = SpotifyClientCredentials(
        client_id, client_secret, cache_handler=MemoryCacheHandler()
    )
    return Spotify(client_credentials_manager=manager)


def _parse(url):
    match = _URL_RE.search(url) or _URI_RE.search(url)
    if not match:
        raise ValueError(
            "That doesn't look like a Spotify link. Paste a playlist, album, or "
            "track link, e.g. https://open.spotify.com/playlist/..."
        )
    return match.group(1), match.group(2)


def _paginate(sp, page):
    """Yield every item across all pages of a Spotify paging object."""
    while page:
        for item in page.get("items", []):
            yield item
        page = sp.next(page) if page.get("next") else None


def _track_from_full(obj):
    """Build a Track from a *full* track object (has an ``album`` field)."""
    album = obj.get("album", {}) or {}
    images = album.get("images") or []
    artists = obj.get("artists") or [{}]
    album_artists = album.get("artists") or [{}]
    return Track(
        title=obj.get("name", "Unknown"),
        artist=artists[0].get("name", "Unknown Artist"),
        album=album.get("name", ""),
        album_artist=album_artists[0].get("name", ""),
        year=(album.get("release_date") or "").split("-")[0],
        cover_url=images[0]["url"] if images else None,
        duration_ms=obj.get("duration_ms", 0) or 0,
    )


def _friendly_spotify_error(exc, kind):
    """Turn a raw SpotifyException into a clear, actionable message."""
    status = getattr(exc, "http_status", None)
    if status == 404:
        if kind == "playlist":
            return (
                "Couldn't open that playlist.\n"
                "Spotify's API can't access Spotify-made playlists — like "
                '"Your Top Songs" / Wrapped, Discover Weekly, Release Radar, and '
                "editorial playlists — or playlists set to private.\n\n"
                "Fix: use a playlist you created yourself. To copy a Spotify one, "
                'open it in the Spotify app -> the "..." menu -> "Add to other '
                'playlist" -> "New playlist", then paste that new link here.'
            )
        return (
            f"Couldn't find that {kind} on Spotify. Make sure the link is correct "
            "and the item is public."
        )
    if status in (401, 403):
        if kind == "playlist":
            return (
                "This playlist's tracks need a Spotify login.\n"
                "Since late 2024, Spotify only returns playlist tracks to a "
                "logged-in user, not to app-only access. Click \"Log in with "
                "Spotify\" and try again.\n\n"
                "(Single-track and album links work without logging in.)"
            )
        return (
            "Spotify rejected the request (unauthorized). Check that "
            "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in your .env are correct "
            "and the app is active in the Spotify dashboard."
        )
    if status == 429:
        return "Spotify is rate-limiting requests. Wait a minute, then try again."
    return f"Spotify returned an error (HTTP {status}). Please try again."


def fetch_tracks(url, sp):
    """Return ``(collection_name, [Track, ...])`` using the given Spotify client.

    ``sp`` may be app-only (Client Credentials) or a logged-in user client.
    """
    kind, spotify_id = _parse(url)
    try:
        return _fetch_by_kind(sp, kind, spotify_id)
    except SpotifyException as exc:
        raise RuntimeError(_friendly_spotify_error(exc, kind)) from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(
            "Couldn't reach Spotify. Check your internet connection and try again."
        ) from exc


def _fetch_by_kind(sp, kind, spotify_id):
    if kind == "track":
        obj = sp.track(spotify_id)
        return obj.get("name", "track"), [_track_from_full(obj)]

    if kind == "album":
        album = sp.album(spotify_id)
        images = album.get("images") or []
        cover = images[0]["url"] if images else None
        year = (album.get("release_date") or "").split("-")[0]
        album_name = album.get("name", "album")
        album_artist = (album.get("artists") or [{}])[0].get("name", "")
        tracks = []
        # Album track items are "simplified" and lack album info, so we fill it
        # in from the album we already fetched.
        for item in _paginate(sp, album["tracks"]):
            artists = item.get("artists") or [{}]
            tracks.append(
                Track(
                    title=item.get("name", "Unknown"),
                    artist=artists[0].get("name", "Unknown Artist"),
                    album=album_name,
                    album_artist=album_artist,
                    year=year,
                    cover_url=cover,
                    duration_ms=item.get("duration_ms", 0) or 0,
                )
            )
        return album_name, tracks

    # playlist
    playlist = sp.playlist(spotify_id)  # metadata (name) is still readable
    name = playlist.get("name", "playlist")
    tracks = []
    # Use the dedicated items endpoint: the playlist object no longer always
    # includes a "tracks" field, and this is the call Spotify now gates behind
    # a user login (returns 401 for app-only tokens).
    page = sp.playlist_items(spotify_id, additional_types=("track",))
    for item in _paginate(sp, page):
        # Spotify returns the track under "track" on most responses but under
        # "item" on newer ones — accept either.
        obj = item.get("track") or item.get("item")
        # Skip removed/unavailable entries and podcast episodes.
        if not obj or not obj.get("artists"):
            continue
        tracks.append(_track_from_full(obj))
    return name, tracks
