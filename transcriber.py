"""Local speech-to-text with faster-whisper (CTranslate2, CPU-friendly).

faster-whisper downloads the CTranslate2 model from the Hugging Face Hub the
first time a given size is used, then caches it under
%USERPROFILE%\\.cache\\huggingface. No API key, no internet after that.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Sizes that faster-whisper resolves to Systran/faster-whisper-* on the Hub.
VALID_MODELS = {
    "tiny", "tiny.en",
    "base", "base.en",
    "small", "small.en",
    "medium", "medium.en",
    "large-v2", "large-v3", "turbo",
    "distil-small.en", "distil-medium.en", "distil-large-v3",
}


@dataclass
class Segment:
    start: float
    end: float
    text: str


def format_timestamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _cpu_threads() -> int:
    cores = os.cpu_count() or 4
    # Leave a core for the OS so the laptop stays usable while transcribing.
    return max(1, min(8, cores - 1))


def transcribe(
    audio_path: Path,
    model_size: str = "small.en",
    compute_type: str = "int8",
    language: str | None = "en",
    status_callback=None,
) -> list[Segment]:
    """Transcribe a wav file into timestamped segments."""
    from faster_whisper import WhisperModel

    def status(message: str) -> None:
        if status_callback:
            try:
                status_callback(message)
            except Exception:
                pass

    if model_size not in VALID_MODELS:
        status(f"Unknown model '{model_size}' - falling back to small.en.")
        model_size = "small.en"

    status(f"Loading the {model_size} speech model (first run downloads it)...")
    try:
        model = WhisperModel(
            model_size,
            device="cpu",
            compute_type=compute_type,
            cpu_threads=_cpu_threads(),
        )
    except ValueError:
        # Some CPUs don't support the requested quantization.
        status(f"'{compute_type}' unsupported on this CPU - using int8.")
        model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            cpu_threads=_cpu_threads(),
        )

    status("Transcribing (this is the slow part - go get a coffee)...")
    segment_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 700},
        condition_on_previous_text=False,
    )

    total = float(getattr(info, "duration", 0.0) or 0.0)
    segments: list[Segment] = []
    last_reported = -1

    for seg in segment_iter:
        text = (seg.text or "").strip()
        if text:
            segments.append(Segment(start=float(seg.start), end=float(seg.end), text=text))
        if total > 0:
            percent = int((seg.end / total) * 100)
            if percent >= last_reported + 5:
                last_reported = percent
                status(f"Transcribing... {min(percent, 99)}%")

    status(f"Transcribed {len(segments)} segments.")
    return segments


def segments_to_raw_text(segments: list[Segment], stamp_every_seconds: int = 180) -> str:
    """Plain timestamped transcript, exactly as Whisper heard it."""
    if not segments:
        return "(No speech was detected in this recording.)\n"

    lines: list[str] = []
    next_stamp = 0.0
    for seg in segments:
        if seg.start >= next_stamp:
            lines.append("")
            lines.append(f"[{format_timestamp(seg.start)}]")
            while next_stamp <= seg.start:
                next_stamp += stamp_every_seconds
        lines.append(seg.text)

    return "\n".join(lines).strip() + "\n"


def chunk_segments(segments: list[Segment], max_chars: int = 40000) -> list[list[Segment]]:
    """Split segments into groups small enough to send to Claude one at a time.

    ~40k characters is roughly 10k tokens: well inside the context window even
    with the prompt and a long response, and small enough that a 3-hour
    recording still splits into a handful of requests.
    """
    chunks: list[list[Segment]] = []
    current: list[Segment] = []
    current_chars = 0

    for seg in segments:
        seg_chars = len(seg.text) + 1
        if current and current_chars + seg_chars > max_chars:
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(seg)
        current_chars += seg_chars

    if current:
        chunks.append(current)
    return chunks


def chunk_to_text(segments: list[Segment]) -> str:
    """Render one chunk with a timestamp every few minutes, for Claude."""
    return segments_to_raw_text(segments, stamp_every_seconds=180)
