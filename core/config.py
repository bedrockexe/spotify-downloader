"""Credential loading. Keys live in a .env file, never in source."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root first, then fall back to the current dir.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv()


def get_spotify_credentials():
    """Return (client_id, client_secret) from the environment.

    Raises a clear error if they are missing so the UIs can show a helpful
    message instead of a stack trace.
    """
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "Missing Spotify credentials. Copy .env.example to .env and set "
            "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET "
            "(get them at https://developer.spotify.com/dashboard)."
        )
    return client_id, client_secret
