"""Post-recording cleanup: spectral-gate noise reduction plus normalization.

The original recording is never modified. We write a second file
(audio-clean.wav) that the transcriber reads from.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

# Target peak after normalization (about -1 dBFS).
_TARGET_PEAK = 0.891

# How much of the start of the recording to sample as "this is what the
# room sounds like when nobody is talking".
_NOISE_PROFILE_SECONDS = 1.0


def _find_quiet_window(audio: np.ndarray, sample_rate: int, window_seconds: float):
    """Return the quietest window of audio, used as the noise profile.

    We prefer the first second (the professor usually hasn't started yet),
    but if that happens to be loud we scan the first 30 seconds for the
    quietest stretch instead.
    """
    window = int(window_seconds * sample_rate)
    if window <= 0 or len(audio) <= window:
        return audio

    head = audio[:window]
    search_limit = min(len(audio), int(30 * sample_rate))
    step = max(1, window // 2)

    best = head
    best_rms = float(np.sqrt(np.mean(head.astype(np.float64) ** 2)) + 1e-12)

    for start in range(0, max(1, search_limit - window), step):
        candidate = audio[start:start + window]
        rms = float(np.sqrt(np.mean(candidate.astype(np.float64) ** 2)) + 1e-12)
        if rms < best_rms:
            best_rms = rms
            best = candidate

    return best


def _normalize(audio: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak <= 1e-6:
        return audio
    gain = _TARGET_PEAK / peak
    # Don't amplify pure noise into a roar; cap the boost at 20x.
    gain = min(gain, 20.0)
    return np.clip(audio * gain, -1.0, 1.0)


def clean_audio(
    source: Path,
    destination: Path,
    enable_noise_reduction: bool = True,
    status_callback=None,
) -> Path:
    """Write a denoised + normalized copy of `source` to `destination`.

    Falls back to a plain normalized copy if noisereduce isn't installed or
    the reduction fails for any reason. Returns the path actually written.
    """
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    def status(message: str) -> None:
        if status_callback:
            try:
                status_callback(message)
            except Exception:
                pass

    audio, sample_rate = sf.read(str(source), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    if audio.size == 0:
        raise ValueError("The recording is empty - nothing was captured.")

    if enable_noise_reduction:
        try:
            import noisereduce as nr

            status("Filtering out background noise...")
            noise_clip = _find_quiet_window(audio, sample_rate, _NOISE_PROFILE_SECONDS)
            audio = nr.reduce_noise(
                y=audio,
                sr=sample_rate,
                y_noise=noise_clip,
                stationary=True,
                prop_decrease=0.85,
            )
            audio = np.asarray(audio, dtype=np.float32)
        except ImportError:
            status("noisereduce not installed - skipping noise filtering.")
        except Exception as exc:
            status(f"Noise filtering failed ({exc}) - using the raw audio.")

    status("Normalizing volume...")
    audio = _normalize(np.asarray(audio, dtype=np.float32))

    sf.write(str(destination), audio, sample_rate, subtype="PCM_16")
    return destination
