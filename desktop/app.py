"""Tkinter desktop front-end. Same core engine as the web app.

Run from the project root:  python -m desktop.app

Credentials are read from .env, but you can also type them into the fields
(handy if you haven't set up .env yet). They are kept in memory only.
"""

import os
import queue
import shutil
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.paths import cleanup  # noqa: E402
from core.pipeline import run  # noqa: E402

# Load whatever is in .env so the fields can pre-fill, but don't require it.
try:
    from core.config import get_spotify_credentials

    _env_id, _env_secret = get_spotify_credentials()
except Exception:
    _env_id = os.getenv("SPOTIFY_CLIENT_ID", "")
    _env_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "")


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.result = None  # (zip_path, name)

        root.title("Spotify Downloader")
        root.geometry("560x480")
        root.resizable(False, False)

        pad = {"padx": 16, "pady": 6}

        tk.Label(root, text="Spotify → M4A", font=("Segoe UI", 18, "bold")).pack(pady=(16, 2))
        tk.Label(root, text="Playlist, album, or track link", fg="#666").pack()

        # Credentials
        creds = tk.LabelFrame(root, text="Spotify credentials")
        creds.pack(fill="x", **pad)
        tk.Label(creds, text="Client ID").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.id_entry = tk.Entry(creds, width=48)
        self.id_entry.grid(row=0, column=1, padx=8, pady=4)
        self.id_entry.insert(0, _env_id)
        tk.Label(creds, text="Client Secret").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.secret_entry = tk.Entry(creds, width=48, show="*")
        self.secret_entry.grid(row=1, column=1, padx=8, pady=4)
        self.secret_entry.insert(0, _env_secret)

        # URL
        self.url_entry = tk.Entry(root, width=60)
        self.url_entry.pack(**pad)
        self.url_entry.insert(0, "https://open.spotify.com/playlist/...")

        self.button = tk.Button(root, text="Download", command=self.start, bg="#1db954", fg="black", font=("Segoe UI", 10, "bold"))
        self.button.pack(pady=6)

        self.progress = ttk.Progressbar(root, orient="horizontal", mode="determinate", length=520)
        self.progress.pack(**pad)

        self.status = tk.Label(root, text="", fg="#333")
        self.status.pack()

        self.log = tk.Text(root, height=10, width=66, state="disabled", bg="#0e0e0e", fg="#b3b3b3")
        self.log.pack(**pad)

    def log_line(self, text):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def start(self):
        url = self.url_entry.get().strip()
        client_id = self.id_entry.get().strip()
        client_secret = self.secret_entry.get().strip()
        if not url or url.endswith("..."):
            messagebox.showwarning("Missing link", "Paste a Spotify link first.")
            return
        if not client_id or not client_secret:
            messagebox.showwarning("Missing credentials", "Enter your Spotify Client ID and Secret.")
            return

        self.button.config(state="disabled")
        self.progress["value"] = 0
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

        def on_progress(message, current, total, meta=None):
            # meta carries per-track status for the web UI; the desktop app
            # shows plain text progress, so it is ignored here.
            self.events.put(("progress", message, current, total))

        def worker():
            try:
                zip_path, name, errors = run(url, client_id, client_secret, on_progress=on_progress)
                self.events.put(("done", zip_path, name, len(errors)))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self.poll)

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "progress":
                    _, message, current, total = event
                    self.status.config(text=message)
                    self.log_line(message)
                    self.progress["mode"] = "determinate" if total else "indeterminate"
                    if total:
                        self.progress["maximum"] = total
                        self.progress["value"] = current
                    else:
                        self.progress.start(12)
                elif kind == "done":
                    _, zip_path, name, failures = event
                    self.progress.stop()
                    self.progress["mode"] = "determinate"
                    self.progress["maximum"] = 1
                    self.progress["value"] = 1
                    self.result = (zip_path, name)
                    if failures:
                        self.log_line(f"{failures} track(s) failed (see errors.txt in the zip).")
                    self.status.config(text="Done! Choose where to save.")
                    self.save_zip()
                    self.button.config(state="normal")
                    return
                elif kind == "error":
                    self.progress.stop()
                    messagebox.showerror("Error", event[1])
                    self.status.config(text="Failed.")
                    self.button.config(state="normal")
                    return
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def save_zip(self):
        if not self.result:
            return
        zip_path, name = self.result
        destination = filedialog.asksaveasfilename(
            title="Save playlist as",
            initialfile=f"{name}.zip",
            defaultextension=".zip",
            filetypes=[("Zip files", "*.zip")],
        )
        if destination:
            shutil.copy(zip_path, destination)
            messagebox.showinfo("Saved", f"Saved to:\n{destination}")
        # Clean up the temp workspace either way.
        cleanup(Path(zip_path).parent)
        self.result = None


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
