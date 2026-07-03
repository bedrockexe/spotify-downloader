"""Embed tags + cover art using mutagen (pure Python, no ffmpeg).

Tagging only rewrites the container's metadata region; it never touches the
audio stream, which is why it needs no ffmpeg. Handles m4a/mp4 primarily, with
an Opus fallback in case yt-dlp had to serve a .opus stream.
"""

import base64
from pathlib import Path

import requests
from mutagen.flac import Picture
from mutagen.id3 import PictureType
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def download_cover(url, timeout=30):
    """Fetch cover-art bytes, or None on any failure/absence."""
    if not url:
        return None
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response.content
    except Exception:
        return None


def _is_png(data):
    return data[:8] == _PNG_MAGIC


def _embed_mp4(path, track, cover_bytes, lyrics_text):
    audio = MP4(path)
    audio["\xa9nam"] = track.title
    audio["\xa9ART"] = track.artist
    if track.album:
        audio["\xa9alb"] = track.album
    if track.album_artist:
        audio["aART"] = track.album_artist
    if track.year:
        audio["\xa9day"] = str(track.year)
    if lyrics_text:
        audio["\xa9lyr"] = lyrics_text
    if cover_bytes:
        fmt = MP4Cover.FORMAT_PNG if _is_png(cover_bytes) else MP4Cover.FORMAT_JPEG
        audio["covr"] = [MP4Cover(cover_bytes, imageformat=fmt)]
    audio.save()


def _embed_opus(path, track, cover_bytes, lyrics_text):
    audio = OggOpus(path)
    audio["title"] = track.title
    audio["artist"] = track.artist
    if track.album:
        audio["album"] = track.album
    if track.album_artist:
        audio["albumartist"] = track.album_artist
    if track.year:
        audio["date"] = str(track.year)
    if lyrics_text:
        audio["lyrics"] = lyrics_text
    if cover_bytes:
        picture = Picture()
        picture.data = cover_bytes
        picture.type = PictureType.COVER_FRONT
        picture.mime = "image/png" if _is_png(cover_bytes) else "image/jpeg"
        audio["metadata_block_picture"] = [
            base64.b64encode(picture.write()).decode("ascii")
        ]
    audio.save()


def embed(audio_path, track, cover_bytes=None, lyrics_text=None):
    """Write title/artist/album/year + cover + lyrics into ``audio_path``."""
    ext = Path(audio_path).suffix.lower()
    if ext in (".m4a", ".mp4"):
        _embed_mp4(audio_path, track, cover_bytes, lyrics_text)
    elif ext in (".opus", ".ogg"):
        _embed_opus(audio_path, track, cover_bytes, lyrics_text)
    # Any other container is left untagged rather than crashing the run.
