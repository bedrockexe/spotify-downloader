"""Zip the finished audio folder for delivery."""

import zipfile
from pathlib import Path


def zip_folder(folder, zip_path):
    """Zip everything in ``folder`` (audio + .lrc + errors.txt) into ``zip_path``."""
    folder = Path(folder)
    zip_path = Path(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(folder.rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(folder))
    return str(zip_path)
