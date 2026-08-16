"""Where recordings live on disk.

    <storage_root>\\<Class>\\<YYYY-MM-DD>\\
        audio.wav             untouched original recording
        audio-clean.wav       denoised + normalized (what got transcribed)
        transcript-raw.txt    exactly what Whisper heard, timestamped
        transcript-clean.md   full transcript, edited for readability
        notes.md              structured study notes
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

_ILLEGAL = r'<>:"/\\|?*'
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_name(name: str, fallback: str = "Unsorted") -> str:
    """Make a class name safe to use as a Windows folder name."""
    cleaned = "".join("-" if ch in _ILLEGAL else ch for ch in (name or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    if not cleaned:
        return fallback
    if cleaned.upper() in _RESERVED:
        cleaned = f"{cleaned}_"
    return cleaned[:80]


def today_string() -> str:
    return _dt.date.today().isoformat()


def session_folder(storage_root: str | Path, class_name: str, date_string: str | None = None) -> Path:
    """Create and return the folder for one lecture, avoiding collisions."""
    date_string = date_string or today_string()
    base = Path(storage_root) / sanitize_name(class_name) / date_string

    folder = base
    suffix = 2
    while folder.exists() and (folder / "audio.wav").exists():
        folder = base.parent / f"{date_string}_{suffix}"
        suffix += 1

    folder.mkdir(parents=True, exist_ok=True)
    return folder


def temp_folder(app_dir: str | Path) -> Path:
    """Scratch space for in-progress chunk files."""
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = Path(app_dir) / "recordings-in-progress" / stamp
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def write_text(path: Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path
