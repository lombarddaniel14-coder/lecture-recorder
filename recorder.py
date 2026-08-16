"""Microphone capture that streams straight to disk in timed chunks.

Design goals:
  * A 90-minute lecture must never accumulate in RAM.
  * If the laptop dies mid-lecture, everything recorded up to the last
    few seconds is already on disk as finished .wav pieces.
  * If the mic gets unplugged (or Windows swaps the default device),
    keep trying to reopen it instead of silently recording nothing.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

# How long we tolerate silence from the audio callback before assuming the
# device died and trying to reopen it.
_STALL_SECONDS = 6.0
_REOPEN_RETRY_SECONDS = 3.0


class NoMicrophoneError(RuntimeError):
    """Raised when no usable input device exists at start time."""


def default_input_name() -> str:
    """Human-readable name of the current default input device."""
    try:
        info = sd.query_devices(kind="input")
        if isinstance(info, dict):
            return str(info.get("name", "default input"))
        return str(info)
    except Exception:
        return "unknown"


def check_microphone(sample_rate: int) -> None:
    """Raise NoMicrophoneError if we cannot open an input stream right now."""
    try:
        devices = sd.query_devices()
    except Exception as exc:  # PortAudio not initialized / no audio backend
        raise NoMicrophoneError(f"Audio system unavailable: {exc}") from exc

    has_input = any(d.get("max_input_channels", 0) > 0 for d in devices)
    if not has_input:
        raise NoMicrophoneError(
            "No microphone found. Plug one in (or enable the built-in mic in "
            "Windows Settings > System > Sound) and try again."
        )

    try:
        sd.check_input_settings(channels=1, samplerate=sample_rate, dtype="int16")
    except Exception as exc:
        raise NoMicrophoneError(
            f"The default microphone can't record at {sample_rate} Hz mono: {exc}"
        ) from exc


class ChunkedRecorder:
    """Records the default microphone to a series of .wav chunk files."""

    def __init__(
        self,
        out_dir: Path,
        sample_rate: int = 16000,
        chunk_seconds: int = 300,
        status_callback=None,
    ):
        self.out_dir = Path(out_dir)
        self.sample_rate = int(sample_rate)
        self.chunk_seconds = max(30, int(chunk_seconds))
        self._status_callback = status_callback

        self._queue: "queue.Queue[np.ndarray | None]" = queue.Queue(maxsize=512)
        self._stream = None
        self._writer_thread = None
        self._watchdog_thread = None

        self._running = threading.Event()
        self._lock = threading.Lock()

        self._chunk_paths: list[Path] = []
        self._frames_written = 0
        self._last_data_time = 0.0
        self._start_time = 0.0
        self._device_lost = False

    # ---------------------------------------------------------------- status

    def _status(self, message: str) -> None:
        if self._status_callback:
            try:
                self._status_callback(message)
            except Exception:
                pass

    @property
    def device_lost(self) -> bool:
        return self._device_lost

    @property
    def elapsed_seconds(self) -> float:
        if not self._start_time:
            return 0.0
        return time.monotonic() - self._start_time

    @property
    def recorded_seconds(self) -> float:
        with self._lock:
            return self._frames_written / float(self.sample_rate)

    # ----------------------------------------------------------------- start

    def start(self) -> None:
        if self._running.is_set():
            return

        check_microphone(self.sample_rate)
        self.out_dir.mkdir(parents=True, exist_ok=True)

        self._chunk_paths = []
        self._frames_written = 0
        self._device_lost = False
        self._start_time = time.monotonic()
        self._last_data_time = time.monotonic()
        self._running.set()

        self._writer_thread = threading.Thread(
            target=self._writer_loop, name="lr-writer", daemon=True
        )
        self._writer_thread.start()

        self._open_stream()

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, name="lr-watchdog", daemon=True
        )
        self._watchdog_thread.start()

    def _audio_callback(self, indata, frames, time_info, status):  # noqa: ARG002
        self._last_data_time = time.monotonic()
        if status and status.input_overflow:
            # Dropped samples; not fatal, keep going.
            pass
        try:
            self._queue.put_nowait(indata.copy())
        except queue.Full:
            # Disk can't keep up — drop this block rather than block audio.
            pass

    def _open_stream(self) -> None:
        stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=0,
            callback=self._audio_callback,
        )
        stream.start()
        self._stream = stream
        self._last_data_time = time.monotonic()

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    # -------------------------------------------------------------- watchdog

    def _watchdog_loop(self) -> None:
        while self._running.is_set():
            time.sleep(1.0)
            if not self._running.is_set():
                break
            stalled = (time.monotonic() - self._last_data_time) > _STALL_SECONDS
            if not stalled:
                if self._device_lost:
                    self._device_lost = False
                    self._status("Microphone reconnected - still recording.")
                continue

            if not self._device_lost:
                self._device_lost = True
                self._status("Lost the microphone - retrying (audio so far is safe).")

            self._close_stream()
            try:
                sd._terminate()  # noqa: SLF001 - force PortAudio to rescan devices
                sd._initialize()  # noqa: SLF001
            except Exception:
                pass
            try:
                self._open_stream()
            except Exception:
                time.sleep(_REOPEN_RETRY_SECONDS)

    # ---------------------------------------------------------------- writer

    def _new_chunk_path(self) -> Path:
        index = len(self._chunk_paths) + 1
        return self.out_dir / f"chunk_{index:04d}.wav"

    def _writer_loop(self) -> None:
        current = None
        current_frames = 0
        chunk_limit = self.chunk_seconds * self.sample_rate

        try:
            while True:
                try:
                    block = self._queue.get(timeout=0.5)
                except queue.Empty:
                    if not self._running.is_set():
                        break
                    continue

                if block is None:
                    break

                if current is None:
                    path = self._new_chunk_path()
                    current = sf.SoundFile(
                        str(path),
                        mode="w",
                        samplerate=self.sample_rate,
                        channels=1,
                        subtype="PCM_16",
                    )
                    self._chunk_paths.append(path)
                    current_frames = 0

                current.write(block)
                current.flush()
                current_frames += len(block)
                with self._lock:
                    self._frames_written += len(block)

                if current_frames >= chunk_limit:
                    current.close()
                    current = None
        finally:
            if current is not None:
                try:
                    current.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------ stop

    def stop(self) -> list[Path]:
        """Stop recording and return the list of chunk files, in order."""
        if not self._running.is_set():
            return list(self._chunk_paths)

        self._running.clear()
        self._close_stream()

        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

        if self._writer_thread is not None:
            self._writer_thread.join(timeout=15)
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=5)

        return [p for p in self._chunk_paths if p.exists() and p.stat().st_size > 44]


def concatenate_chunks(chunk_paths, destination: Path, sample_rate: int) -> Path:
    """Stitch the chunk files into one .wav without loading it all into RAM."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with sf.SoundFile(
        str(destination),
        mode="w",
        samplerate=sample_rate,
        channels=1,
        subtype="PCM_16",
    ) as out:
        for path in chunk_paths:
            try:
                with sf.SoundFile(str(path)) as src:
                    while True:
                        data = src.read(frames=sample_rate * 30, dtype="int16")
                        if len(data) == 0:
                            break
                        out.write(data)
            except Exception:
                # A truncated final chunk from a crash: skip it, keep the rest.
                continue
    return destination
