"""Filename sanitization.

The old versions crashed on any track whose title contained a character that
Windows forbids in filenames (e.g. AC/DC, "Song: Reprise", "What?"). This is
the single most common cause of failed downloads, so it lives in one place.
"""

import re

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name, fallback="track", max_length=150):
    """Make ``name`` safe to use as a file name on Windows, macOS and Linux."""
    cleaned = _ILLEGAL.sub("", name or "")
    # Trailing dots/spaces are illegal on Windows.
    cleaned = cleaned.strip().rstrip(". ")
    cleaned = cleaned[:max_length].strip()
    return cleaned or fallback
