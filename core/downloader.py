"""Download native audio with yt-dlp — no ffmpeg, no transcoding.

We grab YouTube's native ``m4a`` (AAC) audio stream and keep it as-is. That
means no ffmpeg dependency, no CPU-heavy re-encode, and slightly better quality
than converting to MP3. See the README for the trade-off vs .mp3.
"""

import time

import yt_dlp


class _Silent:
    """Swallow yt-dlp's console chatter; progress comes from the pipeline."""

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


def download_audio(url, out_path_no_ext, attempts=3):
    """Download ``url`` to ``out_path_no_ext`` + real extension. Returns the path.

    YouTube throttles rapid/parallel requests and occasionally returns HTTP 403
    on a media URL. Re-extracting fetches fresh signed URLs, which usually clears
    it, so we retry a few times with backoff before giving up.
    """
    options = {
        # Prefer the native m4a audio stream; fall back to whatever is best.
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": f"{out_path_no_ext}.%(ext)s",
        "postprocessors": [],  # explicitly none -> ffmpeg is never invoked
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _Silent(),
        # yt-dlp's own retry knobs for transient network/HTTP errors.
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "file_access_retries": 3,
    }
    last_error = None
    for attempt in range(attempts):
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)
        except Exception as error:
            last_error = error
            if attempt < attempts - 1:
                time.sleep(2 * (attempt + 1))  # back off, then re-extract
    raise last_error
