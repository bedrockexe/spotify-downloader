"""Temporary workspace management (cross-platform via pathlib).

Each download gets its own random workspace under the system temp dir so
concurrent runs never collide, and it can be deleted wholesale afterwards.
"""

import secrets
import shutil
import tempfile
from pathlib import Path


def make_workspace(base=None):
    """Create and return a fresh workspace directory with an ``audio`` subdir."""
    root = Path(base) if base else Path(tempfile.gettempdir()) / "spotify-downloader"
    workspace = root / secrets.token_hex(4)
    (workspace / "audio").mkdir(parents=True, exist_ok=True)
    return workspace


def cleanup(path):
    """Best-effort recursive delete of a workspace."""
    shutil.rmtree(Path(path), ignore_errors=True)
