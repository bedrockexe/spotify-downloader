# Spotify Downloader

Download a Spotify **playlist, album, or track** as tagged audio files —
with cover art, artist/album/year metadata, and synced lyrics. One reusable
core engine, two front-ends (a web app and a desktop app).

> ⚖️ **Personal use only.** Routing Spotify → YouTube audio is against both
> services' Terms of Service. This is a learning project; don't host it publicly.

## Why M4A and not MP3?

Audio is saved as native **`.m4a` (AAC)** — the format YouTube already serves.
That means:

- **No ffmpeg dependency** (nothing to bundle, no ~140 MB binary)
- **No CPU-heavy transcoding** — files are downloaded, not re-encoded
- **Better quality** than converting to MP3 (no lossy-to-lossy re-encode)
- Plays on every phone, computer, browser, and modern car stereo

The only trade-off: very old / cheap dedicated MP3 players may not read `.m4a`.
Metadata + cover art + lyrics all still work via [`mutagen`](https://mutagen.readthedocs.io/)
(pure Python — tagging never needs ffmpeg).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # then edit .env with your Spotify keys
```

Get a **Client ID** and **Client Secret** from the
[Spotify Developer Dashboard](https://developer.spotify.com/dashboard).

## Run

**Web app:**
```bash
python -m web.app
# open http://127.0.0.1:5000
```

**Desktop app:**
```bash
python -m desktop.app
```

## Project structure

```
Spotify Downloader/
├── core/                 # UI-agnostic engine
│   ├── config.py         # loads keys from .env
│   ├── spotify_client.py # playlist / album / track + pagination
│   ├── youtube.py        # ytmusic search -> URL
│   ├── downloader.py     # yt-dlp native m4a (no ffmpeg)
│   ├── metadata.py       # tags + cover art (mutagen)
│   ├── lyrics.py         # synced .lrc via LRCLIB (no API key)
│   ├── sanitize.py       # safe filenames
│   ├── paths.py          # temp workspace + cleanup
│   ├── packaging.py      # zip builder
│   └── pipeline.py       # orchestrator (emits progress events)
├── web/                  # Flask UI (live progress over SSE)
└── desktop/              # Tkinter UI (progress via a queue)
```

The engine reports progress through an `on_progress(message, current, total)`
callback, so both front-ends render the same run — no duplicated logic.

## Notes

- Long playlists (>100 tracks) are fully supported via Spotify pagination.
- Lyrics come from [LRCLIB](https://lrclib.net) (free, no key). Synced lyrics
  are written as a `.lrc` sidecar file and the plain text is embedded in the tag.
- Downloads run a few tracks in parallel; tune `max_workers` in `pipeline.run()`.
