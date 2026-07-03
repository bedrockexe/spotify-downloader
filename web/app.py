"""Flask front-end with "Log in with Spotify" (OAuth) for playlist support.

Run from the project root:  python -m web.app
Then open http://127.0.0.1:5000

Spotify blocks playlist tracks for app-only access, so downloading a playlist
requires logging in. Single tracks and albums work with or without a login.

IMPORTANT: add this exact redirect URI to your app at
https://developer.spotify.com/dashboard  ->  Settings  ->  Redirect URIs:
    http://127.0.0.1:5000/callback
"""

import json
import os
import queue
import sys
import threading
import uuid
from pathlib import Path

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from spotipy import Spotify
from spotipy.cache_handler import FlaskSessionCacheHandler
from spotipy.oauth2 import SpotifyOAuth

# Allow "python web/app.py" as well as "python -m web.app".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import get_spotify_credentials  # noqa: E402
from core.packaging import zip_folder  # noqa: E402
from core.paths import cleanup, make_workspace  # noqa: E402
from core.pipeline import download_single, download_tracks  # noqa: E402
from core.sanitize import sanitize_filename  # noqa: E402
from core.spotify_client import fetch_tracks, make_client_credentials  # noqa: E402

REDIRECT_URI = "http://127.0.0.1:5000/callback"
# Read the user's own private/collaborative playlists too (public ones are
# readable once logged in without extra scope).
SCOPE = "playlist-read-private playlist-read-collaborative"

app = Flask(__name__)
# Signs the session cookie that holds the OAuth token. Stable so a server
# restart keeps you logged in. Override via FLASK_SECRET_KEY if you like.
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "spotify-downloader-local-dev")

# In-memory job registry. Fine for a personal, single-machine tool.
_jobs = {}


def _auth_manager():
    client_id, client_secret = get_spotify_credentials()
    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_handler=FlaskSessionCacheHandler(session),
        show_dialog=True,
    )


def _user_token():
    """Return a valid user access token from the session, or None."""
    manager = _auth_manager()
    token = manager.cache_handler.get_cached_token()
    if not manager.validate_token(token):  # refreshes if needed
        return None
    return manager.cache_handler.get_cached_token()["access_token"]


@app.route("/")
def index():
    token = _user_token()
    display_name = None
    if token:
        try:
            display_name = Spotify(auth=token).me().get("display_name")
        except Exception:
            display_name = None
    return render_template(
        "index.html", logged_in=bool(token), display_name=display_name
    )


@app.route("/login")
def login():
    return redirect(_auth_manager().get_authorize_url())


@app.route("/callback")
def callback():
    if request.args.get("error"):  # user denied access
        return redirect(url_for("index"))
    code = request.args.get("code")
    if code:
        _auth_manager().get_access_token(code)  # stores token in the session
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


def _spotify_client():
    """Prefer the logged-in user's token (required for playlists); otherwise
    fall back to app-only access, which is fine for tracks and albums."""
    token = _user_token()
    if token:
        return Spotify(auth=token)
    return make_client_credentials(*get_spotify_credentials())


def _discard_job(job_id):
    """Drop a job and delete its workspace (best effort)."""
    job = _jobs.pop(job_id, None)
    if job and job.get("workspace"):
        cleanup(job["workspace"])


@app.route("/preview", methods=["POST"])
def preview():
    """Fetch a link's track list (with cover art) so the UI can show it before
    downloading. Stores the tracks under a job id that /start reuses."""
    url = (request.form.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Please paste a Spotify link."}), 400

    try:
        sp = _spotify_client()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    try:
        name, tracks = fetch_tracks(url, sp)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    if not tracks:
        return jsonify({"error": "No downloadable tracks found for that link."}), 400

    # Single-user tool: clear out any finished jobs so temp files don't pile up.
    for old_id in [i for i, j in _jobs.items() if not j.get("running")]:
        _discard_job(old_id)

    job_id = uuid.uuid4().hex
    _jobs[job_id] = {
        "events": queue.Queue(),
        "zip": None,
        "name": name,
        "tracks": tracks,
        "workspace": None,  # created on first download
        "status": {},  # index -> "done" | "failed"
        "running": False,
    }
    return jsonify(
        {
            "job_id": job_id,
            "name": name,
            "count": len(tracks),
            "tracks": [
                {
                    "title": t.title,
                    "artist": t.artist,
                    "album": t.album,
                    "cover_url": t.cover_url,
                    "duration_ms": t.duration_ms,
                }
                for t in tracks
            ],
        }
    )


def _run_job(job, job_id, indexes):
    """Download the given track indexes into the job's workspace, then (re)zip.

    Runs in a background thread and streams events over the job's queue. Used for
    both the initial "download all" and a "retry failed" subset.
    """
    events = job["events"]
    tracks = job["tracks"]

    if job["workspace"] is None:
        job["workspace"] = make_workspace()
    audio_dir = job["workspace"] / "audio"

    def on_progress(message, current, total, meta=None):
        event = {"message": message, "current": current, "total": total}
        if meta:
            event.update(meta)
        events.put(event)

    def worker():
        try:
            results, _ = download_tracks(tracks, audio_dir, indexes=indexes, on_progress=on_progress)
            job["status"].update(results)

            # Rewrite errors.txt from everything still failing across all runs.
            failed = sorted(i for i, s in job["status"].items() if s == "failed")
            errors_file = audio_dir / "errors.txt"
            if failed:
                errors_file.write_text(
                    "\n".join(f"{tracks[i].title} - {tracks[i].artist}" for i in failed),
                    encoding="utf-8",
                )
            elif errors_file.exists():
                errors_file.unlink()

            events.put({"message": "Packaging into a zip file...", "current": len(indexes), "total": len(indexes)})
            job["zip"] = zip_folder(audio_dir, job["workspace"] / f"{sanitize_filename(job['name'])}.zip")

            events.put(
                {
                    "done": True,
                    "download": f"/download/{job_id}",
                    "failures": len(failed),
                    "failed_indexes": failed,
                }
            )
        except Exception as exc:
            events.put({"error": str(exc), "done": True})
        finally:
            job["running"] = False
            events.put(None)  # sentinel: closes the SSE stream

    job["running"] = True
    threading.Thread(target=worker, daemon=True).start()


@app.route("/start", methods=["POST"])
def start():
    # /start runs a list already fetched by /preview, so no second Spotify call.
    # An optional comma-separated "indexes" downloads just those tracks (retry).
    job_id = request.form.get("job_id") or ""
    job = _jobs.get(job_id)
    if not job or not job.get("tracks"):
        return jsonify({"error": "Session expired — paste the link again."}), 400
    if job.get("running"):
        return jsonify({"error": "A download is already running for this link."}), 409

    count = len(job["tracks"])
    indexes_raw = request.form.get("indexes")
    if indexes_raw:
        try:
            indexes = [int(x) for x in indexes_raw.split(",") if x.strip() != ""]
        except ValueError:
            return jsonify({"error": "Invalid track selection."}), 400
        indexes = [i for i in indexes if 0 <= i < count]
        if not indexes:
            return jsonify({"error": "Nothing to download."}), 400
    else:
        indexes = list(range(count))

    _run_job(job, job_id, indexes)
    return jsonify({"job_id": job_id})


@app.route("/track/<job_id>/<int:index>")
def track_download(job_id, index):
    """Download and stream a single track as a standalone .m4a file."""
    job = _jobs.get(job_id)
    if not job or index < 0 or index >= len(job["tracks"]):
        return "Not found", 404

    track = job["tracks"][index]
    workspace = make_workspace()  # throwaway, independent of the batch workspace
    try:
        audio_file = download_single(track, workspace / "audio")
    except Exception as exc:
        cleanup(workspace)
        return jsonify({"error": str(exc)}), 500

    response = send_file(
        audio_file, as_attachment=True, download_name=os.path.basename(audio_file)
    )

    @response.call_on_close
    def _cleanup():
        cleanup(workspace)

    return response


@app.route("/progress/<job_id>")
def progress(job_id):
    job = _jobs.get(job_id)
    if not job:
        return "Unknown job", 404

    def stream():
        while True:
            item = job["events"].get()
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"

    return Response(stream(), mimetype="text/event-stream")


@app.route("/download/<job_id>")
def download(job_id):
    # No cleanup here: the workspace stays so the zip can be re-downloaded and
    # failed tracks retried. It's freed by /discard or the next /preview.
    job = _jobs.get(job_id)
    if not job or not job.get("zip"):
        return "Not ready", 404
    return send_file(job["zip"], as_attachment=True, download_name=f"{job['name']}.zip")


@app.route("/discard/<job_id>", methods=["POST"])
def discard(job_id):
    """Called by "Convert another" — free the workspace for a finished job."""
    _discard_job(job_id)
    return "", 204


if __name__ == "__main__":
    # use_reloader=False keeps the friendly debug error pages without the
    # double-process reloader (which confuses managed launchers/preview).
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)
