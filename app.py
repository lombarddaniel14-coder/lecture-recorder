"""Lecture Recorder - press one key, it records until you say otherwise,
then it cleans, transcribes, and files the whole thing.

Run me with:  python app.py
"""

from __future__ import annotations

import queue
import shutil
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

import audio_processing
import config as config_module
import notes as notes_module
import recorder as recorder_module
import storage
import transcriber
from hotkey import HotkeyManager

APP_DIR = Path(__file__).resolve().parent

BG = "#14161a"
FG = "#e8eaed"
MUTED = "#9aa0a6"
GO = "#2e7d32"
STOP = "#c62828"


class LectureRecorderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.config = config_module.load_config()

        self.recorder: recorder_module.ChunkedRecorder | None = None
        self.temp_dir: Path | None = None
        self.is_recording = False
        self.active_jobs = 0

        self._ui_queue: "queue.Queue[tuple]" = queue.Queue()

        self._build_ui()
        self._start_hotkey()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self._drain_ui_queue)
        self.root.after(250, self._tick_timer)

    # ------------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        self.root.title("Lecture Recorder")
        self.root.configure(bg=BG)
        self.root.geometry("340x270")
        self.root.minsize(320, 250)
        self.root.attributes("-topmost", True)

        wrapper = tk.Frame(self.root, bg=BG)
        wrapper.pack(fill="both", expand=True, padx=16, pady=14)

        self.timer_label = tk.Label(
            wrapper,
            text="00:00",
            font=("Segoe UI", 34, "bold"),
            bg=BG,
            fg=FG,
        )
        self.timer_label.pack(pady=(0, 4))

        self.button = tk.Button(
            wrapper,
            text="START RECORDING",
            font=("Segoe UI", 13, "bold"),
            bg=GO,
            fg="white",
            activebackground=GO,
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            command=self.toggle,
        )
        self.button.pack(fill="x", ipady=14, pady=(4, 10))

        self.status_label = tk.Label(
            wrapper,
            text="Ready.",
            font=("Segoe UI", 9),
            bg=BG,
            fg=MUTED,
            wraplength=300,
            justify="center",
        )
        self.status_label.pack(fill="x")

        self.hotkey_label = tk.Label(
            wrapper,
            text="",
            font=("Segoe UI", 8),
            bg=BG,
            fg=MUTED,
        )
        self.hotkey_label.pack(side="bottom", pady=(8, 0))

    def set_status(self, message: str) -> None:
        self.status_label.config(text=message)

    def post_status(self, message: str) -> None:
        """Thread-safe status update."""
        self._ui_queue.put(("status", message))

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                kind, payload = self._ui_queue.get_nowait()
                if kind == "status":
                    self.set_status(payload)
                elif kind == "job_done":
                    self.active_jobs = max(0, self.active_jobs - 1)
                    self._refresh_button()
                elif kind == "error":
                    self.set_status(payload)
                elif kind == "toggle":
                    self.toggle()
        except queue.Empty:
            pass
        self.root.after(100, self._drain_ui_queue)

    def _tick_timer(self) -> None:
        if self.is_recording and self.recorder is not None:
            seconds = int(self.recorder.elapsed_seconds)
            hours, remainder = divmod(seconds, 3600)
            minutes, secs = divmod(remainder, 60)
            if hours:
                self.timer_label.config(text=f"{hours}:{minutes:02d}:{secs:02d}")
            else:
                self.timer_label.config(text=f"{minutes:02d}:{secs:02d}")
        self.root.after(250, self._tick_timer)

    def _refresh_button(self) -> None:
        if self.is_recording:
            self.button.config(text="STOP RECORDING", bg=STOP, activebackground=STOP)
        elif self.active_jobs > 0:
            label = "START RECORDING"
            self.button.config(text=label, bg=GO, activebackground=GO)
        else:
            self.button.config(text="START RECORDING", bg=GO, activebackground=GO)

    # -------------------------------------------------------------- hotkey

    def _start_hotkey(self) -> None:
        hotkey = self.config.get("hotkey", "ctrl+alt+r")
        self.hotkeys = HotkeyManager(hotkey, self._hotkey_fired)
        if self.hotkeys.start():
            self.hotkey_label.config(
                text=f"Global hotkey: {hotkey.upper()}  ({self.hotkeys.backend})"
            )
        else:
            self.hotkey_label.config(text="Global hotkey unavailable - use the button")
            self.set_status(
                "Hotkey didn't register. The button still works. "
                "Details: " + (self.hotkeys.error or "unknown")
            )

    def _hotkey_fired(self) -> None:
        # Fires on the hotkey library's own thread; hand it to the UI thread.
        self._ui_queue.put(("toggle", None))

    # -------------------------------------------------------------- control

    def toggle(self) -> None:
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self) -> None:
        if self.is_recording:
            return
        try:
            self.temp_dir = storage.temp_folder(APP_DIR)
            self.recorder = recorder_module.ChunkedRecorder(
                out_dir=self.temp_dir,
                sample_rate=self.config["sample_rate"],
                chunk_seconds=self.config["chunk_minutes"] * 60,
                status_callback=self.post_status,
            )
            self.recorder.start()
        except recorder_module.NoMicrophoneError as exc:
            self.recorder = None
            self.set_status("Can't record - no microphone.")
            messagebox.showerror("No microphone", str(exc))
            return
        except Exception as exc:
            self.recorder = None
            self.set_status(f"Couldn't start recording: {exc}")
            messagebox.showerror("Couldn't start recording", str(exc))
            return

        self.is_recording = True
        self._refresh_button()
        mic = recorder_module.default_input_name()
        self.set_status(f"Recording from: {mic}")

    def stop_recording(self) -> None:
        if not self.is_recording or self.recorder is None:
            return

        self.is_recording = False
        self._refresh_button()
        self.set_status("Finishing the recording...")
        self.root.update_idletasks()

        rec = self.recorder
        temp_dir = self.temp_dir
        self.recorder = None
        self.temp_dir = None

        try:
            chunk_paths = rec.stop()
        except Exception as exc:
            self.set_status(f"Error stopping the recorder: {exc}")
            return

        self.timer_label.config(text="00:00")

        if not chunk_paths:
            self.set_status("Nothing was recorded - no audio captured.")
            messagebox.showwarning(
                "Empty recording",
                "No audio was captured. Check that the right microphone is set as "
                "your Windows default input device.",
            )
            return

        duration = rec.recorded_seconds
        class_name = self._ask_class_name(duration)
        config_module.remember_class(self.config, class_name)

        self.active_jobs += 1
        self._refresh_button()
        self.set_status(f"Processing {class_name}...")

        worker = threading.Thread(
            target=self._process,
            args=(chunk_paths, temp_dir, class_name),
            name="lr-process",
            daemon=True,
        )
        worker.start()

    # ----------------------------------------------------------- class name

    def _ask_class_name(self, duration_seconds: float) -> str:
        classes = self.config.get("classes", [])
        default = classes[0] if classes else ""

        dialog = tk.Toplevel(self.root)
        dialog.title("Which class was that?")
        dialog.configure(bg=BG)
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        dialog.transient(self.root)

        minutes = int(duration_seconds // 60)
        seconds = int(duration_seconds % 60)

        tk.Label(
            dialog,
            text=f"Recorded {minutes}m {seconds:02d}s. Which class?",
            font=("Segoe UI", 10),
            bg=BG,
            fg=FG,
        ).pack(padx=18, pady=(16, 8))

        value = tk.StringVar(value=default)
        combo = ttk.Combobox(dialog, textvariable=value, values=classes, width=32)
        combo.pack(padx=18, pady=(0, 12))
        combo.focus_set()

        result = {"name": default}

        def confirm(_event=None):
            result["name"] = value.get()
            dialog.destroy()

        def cancel(_event=None):
            result["name"] = value.get()
            dialog.destroy()

        buttons = tk.Frame(dialog, bg=BG)
        buttons.pack(padx=18, pady=(0, 16))
        tk.Button(
            buttons, text="Save", command=confirm, width=12,
            bg=GO, fg="white", relief="flat", cursor="hand2",
        ).pack(side="left", padx=4)
        tk.Button(
            buttons, text="Unsorted", command=cancel, width=12,
            bg="#3c4043", fg=FG, relief="flat", cursor="hand2",
        ).pack(side="left", padx=4)

        dialog.bind("<Return>", confirm)
        dialog.bind("<Escape>", cancel)

        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.root.winfo_y() + 60
        dialog.geometry(f"+{max(0, x)}+{max(0, y)}")

        try:
            dialog.grab_set()
        except tk.TclError:
            pass
        self.root.wait_window(dialog)

        name = (result["name"] or "").strip()
        return name or "Unsorted"

    # ------------------------------------------------------------ pipeline

    def _process(self, chunk_paths, temp_dir: Path, class_name: str) -> None:
        session_dir = None
        try:
            date_string = storage.today_string()
            session_dir = storage.session_folder(
                self.config["storage_root"], class_name, date_string
            )

            self.post_status("Saving the recording...")
            audio_path = session_dir / "audio.wav"
            recorder_module.concatenate_chunks(
                chunk_paths, audio_path, self.config["sample_rate"]
            )

            clean_path = session_dir / "audio-clean.wav"
            try:
                audio_processing.clean_audio(
                    audio_path,
                    clean_path,
                    enable_noise_reduction=bool(self.config.get("noise_reduction", True)),
                    status_callback=self.post_status,
                )
                transcribe_source = clean_path
            except Exception as exc:
                self.post_status(f"Audio cleanup failed ({exc}) - using the original.")
                transcribe_source = audio_path

            segments = transcriber.transcribe(
                transcribe_source,
                model_size=self.config.get("model_size", "small.en"),
                compute_type=self.config.get("compute_type", "int8"),
                language=self.config.get("language") or None,
                status_callback=self.post_status,
            )

            storage.write_text(
                session_dir / "transcript-raw.txt",
                transcriber.segments_to_raw_text(segments),
            )

            api_key = config_module.get_api_key(self.config)
            model = self.config.get("claude_model", notes_module.MODEL_FALLBACK)

            if not api_key:
                storage.write_text(
                    session_dir / "NOTES-SKIPPED.txt",
                    "No Anthropic API key was configured, so notes.md and\n"
                    "transcript-clean.md were not generated.\n\n"
                    "Add your key to config.json (\"anthropic_api_key\") or set the\n"
                    "ANTHROPIC_API_KEY environment variable, then re-run.\n"
                    "The audio and the raw transcript in this folder are complete.\n",
                )
                self.post_status("Saved audio + transcript. No API key, so notes were skipped.")
            else:
                try:
                    clean_transcript = notes_module.build_readable_transcript(
                        segments, class_name, date_string, api_key, model,
                        status_callback=self.post_status,
                    )
                    storage.write_text(session_dir / "transcript-clean.md", clean_transcript)
                except notes_module.NotesUnavailable as exc:
                    self.post_status(f"Readable transcript skipped: {exc}")

                try:
                    study_notes = notes_module.build_clean_notes(
                        segments, class_name, date_string, api_key, model,
                        status_callback=self.post_status,
                    )
                    storage.write_text(session_dir / "notes.md", study_notes)
                except notes_module.NotesUnavailable as exc:
                    self.post_status(f"Notes skipped: {exc}")

            if not self.config.get("keep_chunks", False) and temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)

            self.post_status(f"Done - saved to {session_dir}")

        except Exception as exc:
            detail = traceback.format_exc()
            if session_dir is not None:
                try:
                    storage.write_text(session_dir / "error.log", detail)
                except Exception:
                    pass
            self.post_status(
                f"Processing failed: {exc}. Your audio is safe in "
                f"{session_dir or temp_dir}"
            )
        finally:
            self._ui_queue.put(("job_done", None))

    # ---------------------------------------------------------------- close

    def on_close(self) -> None:
        if self.is_recording:
            if not messagebox.askyesno(
                "Still recording",
                "A recording is in progress. Stop it and process it now?",
            ):
                return
            self.stop_recording()

        if self.active_jobs > 0:
            if not messagebox.askyesno(
                "Still working",
                "Notes are still being generated. Quit anyway?\n"
                "(Your audio is already saved either way.)",
            ):
                return

        try:
            self.hotkeys.stop()
        except Exception:
            pass
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    try:
        LectureRecorderApp(root)
    except Exception:
        traceback.print_exc()
        messagebox.showerror("Lecture Recorder", traceback.format_exc())
        return 1
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
