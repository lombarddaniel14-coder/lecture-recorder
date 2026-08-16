# Lecture Recorder

Press one key. It records the whole lecture. Press it again. A few minutes
later there's a folder with your audio, a clean readable transcript, and a set
of study notes.

No cloud recording, no subscription. The recording and the transcription both
happen on your laptop. Only the note-writing step talks to the internet.

---

## Setup (do this once)

### 1. Install Python

If you've never installed Python:

1. Go to **https://www.python.org/downloads/**
2. Click the big yellow "Download Python" button
3. Run the installer
4. **On the first screen, tick the box that says "Add python.exe to PATH."**
   This matters. If you miss it, nothing else works.
5. Click "Install Now" and let it finish

### 2. Run setup

Double-click **`setup.bat`** in this folder.

A black window opens and downloads everything the app needs. It takes about
five minutes the first time. When it says "Setup finished," close it.

If it says something failed: close the window, right-click `setup.bat`, and
choose **Run as administrator**.

### 3. Add your Anthropic API key (optional but recommended)

Open **`config.json`** in Notepad and put your key between the quotes:

```json
"anthropic_api_key": "sk-ant-...",
```

Save and close.

Without a key everything still works — you just get the audio and the raw
transcript, and the AI-written notes are skipped.

---

## Using it

Double-click **`Launch Lecture Recorder.bat`**. A small window appears and
stays on top of everything else.

**Start and stop a recording two ways:**

- Press **Ctrl + Alt + R** — works from anywhere, even while you're typing in
  Word or scrolling in Chrome. You never have to click back into the app.
- Or click the big button.

**When you stop**, a box asks which class that was. Type it (or pick from the
dropdown — it remembers the classes you've used). Hit Save.

Then leave it alone. It will:

1. Save the untouched recording
2. Strip out background noise and even out the volume
3. Transcribe the whole thing locally
4. Send the transcript to Claude to write your notes

The status line at the bottom tells you what it's doing. **A one-hour lecture
takes roughly 10-20 minutes to process** on a ThinkPad — most of that is the
transcription. You can start recording your next class while the last one is
still processing.

---

## Where your lectures end up

```
C:\Users\Daniel\OneDrive - Bentley University\Claude Stuff\School\Lectures\
    ACC 131\
        2026-09-08\
            notes.md              <- study notes: outline, key concepts,
                                     definitions, what's on the exam, homework
            transcript-clean.md   <- the FULL lecture, word for word, just
                                     readable: no "um", real punctuation,
                                     paragraphs, timestamps
            transcript-raw.txt    <- exactly what the transcriber heard
            audio.wav             <- the original recording, untouched
            audio-clean.wav       <- noise-filtered version
```

`notes.md` is for studying. `transcript-clean.md` is for when the notes skipped
something and you need to find what the professor actually said.

---

## Settings

Everything lives in **`config.json`**. Open it in Notepad, change a value, save,
and restart the app.

| Setting | What it does |
|---|---|
| `hotkey` | The global shortcut. `"ctrl+alt+r"`, `"ctrl+shift+l"`, `"f9"`, etc. |
| `model_size` | Transcription accuracy vs. speed. `"base.en"` (fastest), `"small.en"` (default), `"medium.en"` (best, noticeably slower) |
| `storage_root` | Where lectures get filed |
| `classes` | Your class list for the dropdown. It fills itself in as you use it |
| `anthropic_api_key` | Your Claude API key |
| `chunk_minutes` | How often audio gets flushed to disk. Lower = less lost if the laptop dies mid-lecture |
| `noise_reduction` | Set to `false` to skip noise filtering |
| `keep_chunks` | Set to `true` to keep the intermediate audio pieces |

---

## When something goes wrong

**"No microphone"** — Windows doesn't see an input device. Check
Settings > System > Sound > Input and make sure your mic is set as the default.

**The hotkey does nothing** — Some apps (games, remote desktop) grab the
keyboard. The button in the window always works. You can also try a different
hotkey in `config.json`; `"f9"` tends to be safest.

**Your mic gets unplugged mid-lecture** — the app notices, says so, and keeps
retrying to reconnect. Everything recorded before the unplug is already safe on
disk, and it picks up again once the mic is back.

**It says "Processing failed"** — your audio is still saved. The status line
tells you which folder. There'll be an `error.log` in there with the details.

**Notes were skipped** — usually a missing or wrong API key, or no internet.
Look for `NOTES-SKIPPED.txt` in the lecture folder. The audio and transcript
are still complete.

**The first transcription is slow to start** — it's downloading the speech
model (about 500 MB for `small.en`). That happens once, then it's cached.

---

## What's happening under the hood

- `app.py` — the window, the hotkey, and the orchestration
- `recorder.py` — microphone capture, streamed to disk in 5-minute pieces
- `audio_processing.py` — spectral-gate noise reduction + normalize
- `transcriber.py` — local speech-to-text via faster-whisper
- `notes.py` — the two Claude passes (study notes, readable transcript)
- `storage.py` — the class/date folder layout
- `config.py` — settings
- `hotkey.py` — global hotkey registration
