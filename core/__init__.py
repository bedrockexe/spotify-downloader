"""Reusable, UI-agnostic core for the Spotify -> M4A downloader.

Nothing in here knows about Flask or Tkinter. Both front-ends drive the same
`pipeline.run()` and subscribe to its progress callback.
"""
