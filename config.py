"""Configuration loading/saving for Lecture Recorder.

Everything the user can tweak lives in config.json next to this file.
Missing keys fall back to DEFAULTS, and the file is rewritten with the
merged result so the user always sees every available option.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"

DEFAULTS = {
    # Global hotkey that starts/stops recording. Examples:
    #   "ctrl+alt+r", "ctrl+shift+l", "f9"
    "hotkey": "ctrl+alt+r",

    # faster-whisper model. Bigger = more accurate but slower on a laptop CPU.
    #   "base.en"   -> fastest, decent
    #   "small.en"  -> recommended default
    #   "medium.en" -> most accurate, noticeably slower
    "model_size": "small.en",

    # CPU quantization for faster-whisper. "int8" is the right answer on a
    # ThinkPad. "int8_float32" or "float32" are slower but slightly better.
    "compute_type": "int8",

    # Where finished lectures get filed:
    #   <storage_root>\<Class>\<YYYY-MM-DD>\
    # Override with the LECTURE_STORAGE_ROOT environment variable.
    "storage_root": os.environ.get(
        "LECTURE_STORAGE_ROOT", str(Path.home() / "Lectures")
    ),

    # Remembered class names, shown in the dropdown when a recording stops.
    "classes": [],

    # Anthropic API key. Leave blank to use the ANTHROPIC_API_KEY environment
    # variable instead. If neither is set, audio + transcript still get saved;
    # only the AI notes are skipped.
    "anthropic_api_key": "",

    "claude_model": "claude-opus-4-8",

    # Recording settings. 16 kHz mono is what Whisper wants anyway.
    "sample_rate": 16000,

    # Audio is streamed to disk in pieces this many minutes long, so a crash
    # can never cost you more than one piece.
    "chunk_minutes": 5,

    # Run noise reduction + normalize after recording stops.
    "noise_reduction": True,

    # Keep the raw per-chunk .wav pieces after they are stitched together.
    "keep_chunks": False,

    # Language hint for transcription ("en" or null to auto-detect).
    "language": "en",
}


def _deep_merge(defaults: dict, loaded: dict) -> dict:
    merged = dict(defaults)
    for key, value in loaded.items():
        merged[key] = value
    return merged


def load_config() -> dict:
    """Read config.json, filling in anything missing from DEFAULTS."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if not isinstance(loaded, dict):
                loaded = {}
        except (json.JSONDecodeError, OSError):
            loaded = {}
    else:
        loaded = {}

    config = _deep_merge(DEFAULTS, loaded)

    # Normalize a few fields so the rest of the app can trust them.
    if not isinstance(config.get("classes"), list):
        config["classes"] = []
    config["classes"] = [str(c) for c in config["classes"] if str(c).strip()]

    try:
        config["sample_rate"] = int(config["sample_rate"])
    except (TypeError, ValueError):
        config["sample_rate"] = DEFAULTS["sample_rate"]

    try:
        config["chunk_minutes"] = max(1, int(config["chunk_minutes"]))
    except (TypeError, ValueError):
        config["chunk_minutes"] = DEFAULTS["chunk_minutes"]

    save_config(config)
    return config


def save_config(config: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
    except OSError:
        # A read-only folder shouldn't take down a recording in progress.
        pass


def remember_class(config: dict, class_name: str) -> None:
    """Push a class name to the front of the remembered list and persist it."""
    name = class_name.strip()
    if not name:
        return
    classes = [c for c in config.get("classes", []) if c.lower() != name.lower()]
    classes.insert(0, name)
    config["classes"] = classes[:20]
    save_config(config)


def get_api_key(config: dict) -> str:
    key = (config.get("anthropic_api_key") or "").strip()
    if key:
        return key
    return (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
