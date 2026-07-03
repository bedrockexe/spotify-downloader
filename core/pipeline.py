"""The orchestrator: Spotify link in, zip of tagged audio out.

`run()` is UI-agnostic. It reports progress through an ``on_progress(message,
current, total, meta=None)`` callback, so the Flask and Tkinter front-ends can
render the exact same run however they like. ``total`` is 0 while the track list
is still being fetched (indeterminate), then the number of tracks. ``meta`` is
``None`` for phase messages, or ``{"index": i, "status": ...}`` for per-track
events (``status`` is ``"downloading"``, ``"done"`` or ``"failed"``).

The per-track work lives in :func:`download_tracks` / :func:`download_single`, so
a UI can also download the whole list, a subset (retry), or a single track
through the same code path.
"""

import concurrent.futures
import threading
from pathlib import Path

from .downloader import download_audio
from .lyrics import fetch_lyrics, write_lrc
from .metadata import download_cover, embed
from .packaging import zip_folder
from .paths import make_workspace
from .sanitize import sanitize_filename
from .spotify_client import fetch_tracks, make_client_credentials
from .youtube import find_audio_url


def _noop(message, current, total, meta=None):
    pass


def _download_one(track, audio_dir, with_lyrics=True):
    """Fetch, tag and save a single track. Returns the audio path; raises on failure."""
    audio_dir = Path(audio_dir)
    label = f"{track.title} - {track.artist}"
    base = sanitize_filename(label)

    video_url = find_audio_url(track.title, track.artist)
    if not video_url:
        raise RuntimeError("no YouTube match found")

    audio_file = download_audio(video_url, str(audio_dir / base))

    cover = download_cover(track.cover_url)

    plain_lyrics = None
    if with_lyrics:
        synced, plain_lyrics = fetch_lyrics(track.title, track.artist, track.album)
        if synced:
            write_lrc(synced, audio_dir / f"{base}.lrc")

    embed(audio_file, track, cover_bytes=cover, lyrics_text=plain_lyrics)
    return audio_file


def download_single(track, audio_dir, with_lyrics=True):
    """Download one track into ``audio_dir`` (created if needed). Returns its path."""
    audio_dir = Path(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    return _download_one(track, audio_dir, with_lyrics=with_lyrics)


def download_tracks(
    tracks,
    audio_dir,
    indexes=None,
    on_progress=None,
    with_lyrics=True,
    max_workers=3,
):
    """Download ``tracks[i]`` for each ``i`` in ``indexes`` into ``audio_dir``.

    ``indexes`` defaults to every track. Runs a few in parallel, keeps going past
    individual failures, and emits a ``downloading`` then ``done``/``failed`` event
    per track (``index`` is the position in the full ``tracks`` list).

    Returns ``(results, errors)`` where ``results`` maps ``index -> "done"|"failed"``
    and ``errors`` is a list of ``"Title - Artist: reason"`` strings.
    """
    emit = on_progress or _noop
    audio_dir = Path(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)

    if indexes is None:
        indexes = list(range(len(tracks)))
    total = len(indexes)

    results = {}
    errors = []
    counter = {"done": 0}
    lock = threading.Lock()

    def process(index):
        track = tracks[index]
        label = f"{track.title} - {track.artist}"
        emit(
            f"Downloading: {track.title}",
            counter["done"],
            total,
            {"index": index, "status": "downloading"},
        )
        status = "done"
        try:
            _download_one(track, audio_dir, with_lyrics=with_lyrics)
        except Exception as exc:  # keep going; record the failure
            errors.append(f"{label}: {exc}")
            status = "failed"
        finally:
            with lock:
                counter["done"] += 1
                results[index] = status
                emit(
                    f"Downloaded {counter['done']}/{total}: {track.title}",
                    counter["done"],
                    total,
                    {"index": index, "status": status},
                )

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # list() forces all futures to complete before we move on.
        list(executor.map(process, indexes))

    return results, errors


def run(
    url=None,
    client_id=None,
    client_secret=None,
    on_progress=None,
    with_lyrics=True,
    max_workers=3,
    workspace_base=None,
    spotify=None,
    tracks=None,
    name=None,
):
    """Download a Spotify link to a zip of tagged .m4a files.

    Pass either a ready ``spotify`` client (e.g. a logged-in user client, needed
    for playlists) or ``client_id``/``client_secret`` for app-only access.

    If ``tracks`` (and ``name``) are supplied, the already-fetched list is used
    as-is and Spotify is not contacted again.

    Returns ``(zip_path, collection_name, errors)`` where ``errors`` is a list
    of per-track failure strings (the run continues past individual failures).
    """
    emit = on_progress or _noop

    # Reuse a pre-fetched track list when the caller already has one; otherwise
    # fetch it now (needs a Spotify client).
    if tracks is None:
        sp = spotify or make_client_credentials(client_id, client_secret)
        emit("Fetching track list from Spotify...", 0, 0)
        name, tracks = fetch_tracks(url, sp)

    total = len(tracks)
    if total == 0:
        raise RuntimeError("No downloadable tracks found for that link.")
    emit(f"Found {total} track(s) in '{name}'.", 0, total)

    workspace = make_workspace(workspace_base)
    audio_dir = workspace / "audio"

    _, errors = download_tracks(
        tracks,
        audio_dir,
        on_progress=on_progress,
        with_lyrics=with_lyrics,
        max_workers=max_workers,
    )

    if errors:
        (audio_dir / "errors.txt").write_text("\n".join(errors), encoding="utf-8")

    emit("Packaging into a zip file...", total, total)
    zip_path = zip_folder(audio_dir, workspace / f"{sanitize_filename(name)}.zip")

    emit("Done.", total, total)
    return zip_path, name, errors
