"""Turn a raw transcript into the two documents Daniel actually reads.

  1. notes.md            - structured study notes (summarized, organized)
  2. transcript-clean.md - the FULL transcript, just made readable:
                           fillers and false starts removed, punctuation and
                           paragraphs restored, timestamps every few minutes.
                           Nothing is summarized or dropped.

Long lectures are chunked before being sent to Claude, then stitched back
together. Notes use a map-reduce pass so a 3-hour lecture still produces one
coherent outline instead of five disconnected ones.
"""

from __future__ import annotations

from transcriber import Segment, chunk_segments, chunk_to_text, format_timestamp

MODEL_FALLBACK = "claude-opus-4-8"

# Streaming is used for every call (see the SDK guidance on large max_tokens),
# so these can be generous without risking an HTTP timeout.
_MAX_TOKENS_NOTES = 16000
_MAX_TOKENS_CLEAN = 32000


class NotesUnavailable(RuntimeError):
    """Raised when Claude can't be reached; audio + transcript still save."""


def _client(api_key: str):
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - environment issue
        raise NotesUnavailable(
            "The 'anthropic' package isn't installed. Run setup.bat again."
        ) from exc
    return anthropic.Anthropic(api_key=api_key)


def _stream_once(client, kwargs: dict):
    with client.messages.stream(**kwargs) as stream:
        return stream.get_final_message()


def _call(client, model: str, system: str, user: str, max_tokens: int) -> str:
    """One streamed Claude request; returns the concatenated text blocks."""
    import anthropic

    base = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    # Adaptive thinking + effort are the right settings on claude-opus-4-8, but
    # an older installed SDK may not know those parameter names. Degrade
    # gracefully instead of failing the whole lecture.
    attempts = [
        {**base, "thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}},
        {**base, "thinking": {"type": "adaptive"}},
        base,
    ]

    message = None
    last_type_error: Exception | None = None
    try:
        for kwargs in attempts:
            try:
                message = _stream_once(client, kwargs)
                break
            except TypeError as exc:
                last_type_error = exc
                continue
        if message is None:
            raise NotesUnavailable(
                "The installed 'anthropic' package is too old for this request "
                f"({last_type_error}). Run: pip install --upgrade anthropic"
            )
    except anthropic.AuthenticationError as exc:
        raise NotesUnavailable("Your Anthropic API key was rejected.") from exc
    except anthropic.RateLimitError as exc:
        raise NotesUnavailable("Rate limited by the Anthropic API.") from exc
    except anthropic.APIConnectionError as exc:
        raise NotesUnavailable("Couldn't reach the Anthropic API (no internet?).") from exc
    except anthropic.APIStatusError as exc:
        raise NotesUnavailable(f"Anthropic API error {exc.status_code}.") from exc

    if message.stop_reason == "refusal":
        raise NotesUnavailable("Claude declined to process this transcript.")

    parts = [block.text for block in message.content if block.type == "text"]
    return "\n".join(p for p in parts if p).strip()


# --------------------------------------------------------------- clean notes

_NOTES_SYSTEM = """You are an expert study-notes writer for a university student.
You turn raw lecture transcripts into notes the student can revise from.

Rules:
- Output Markdown only. No preamble, no "here are your notes".
- Never invent content. If the professor didn't say it, it doesn't go in.
- Transcripts come from automatic speech recognition, so expect garbled words
  and misheard technical terms. Correct obvious errors from context; if a term
  is unrecoverable, write it as best you can and mark it with [?].
- Keep the professor's own emphasis. If they said something is on the exam,
  that is the single most important thing to capture."""

_NOTES_CHUNK_PROMPT = """Below is one portion of a lecture transcript from {class_name} on {date}.
This is part {part} of {total}.

Write structured study notes for THIS PORTION ONLY, in Markdown, using these sections
(omit a section entirely if the portion contains nothing for it):

## Topics
Nested bullet outline of what was covered, in the order it was covered.

## Key Concepts
The ideas that matter, explained in 1-3 sentences each.

## Definitions
Term - definition, for every term the professor defined.

## Exam-Relevant
Anything the professor flagged as important, likely to be tested, or worth
memorizing. Quote or closely paraphrase how they said it.

## Homework & Action Items
Assignments, readings, due dates, anything the student must do.

## Open Questions
Things left unresolved, explicitly deferred, or that the student should follow
up on.

Transcript portion:

{text}"""

_NOTES_MERGE_PROMPT = """Below are study notes written separately for consecutive portions of a
single lecture from {class_name} on {date}.

Merge them into ONE clean set of notes for the whole lecture:
- Combine the sections (Topics, Key Concepts, Definitions, Exam-Relevant,
  Homework & Action Items, Open Questions) across all portions.
- Remove duplicates and merge near-duplicates.
- Keep the chronological flow of the Topics outline.
- Do not drop any exam-relevant item, definition, or homework item.
- Do not add anything that isn't in the portions below.

Start the document with:
# {class_name} - {date}

Then the merged sections. Markdown only, no preamble.

Portions:

{text}"""


def build_clean_notes(
    segments: list[Segment],
    class_name: str,
    date_string: str,
    api_key: str,
    model: str = MODEL_FALLBACK,
    status_callback=None,
) -> str:
    def status(message: str) -> None:
        if status_callback:
            try:
                status_callback(message)
            except Exception:
                pass

    if not segments:
        raise NotesUnavailable("No speech was transcribed, so there's nothing to write up.")

    client = _client(api_key)
    chunks = chunk_segments(segments)
    total = len(chunks)

    partials: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        status(f"Writing notes ({index}/{total})...")
        prompt = _NOTES_CHUNK_PROMPT.format(
            class_name=class_name,
            date=date_string,
            part=index,
            total=total,
            text=chunk_to_text(chunk),
        )
        partials.append(_call(client, model, _NOTES_SYSTEM, prompt, _MAX_TOKENS_NOTES))

    if total == 1:
        body = partials[0]
        if not body.lstrip().startswith("#"):
            body = f"# {class_name} - {date_string}\n\n{body}"
        elif not body.lstrip().startswith(f"# {class_name}"):
            body = f"# {class_name} - {date_string}\n\n{body}"
        return body.strip() + "\n"

    status("Merging the notes into one document...")
    joined = "\n\n---\n\n".join(
        f"### Portion {i}\n\n{p}" for i, p in enumerate(partials, start=1)
    )
    merged = _call(
        client,
        model,
        _NOTES_SYSTEM,
        _NOTES_MERGE_PROMPT.format(class_name=class_name, date=date_string, text=joined),
        _MAX_TOKENS_NOTES,
    )
    return merged.strip() + "\n"


# ---------------------------------------------------------- readable "raw"

_CLEAN_SYSTEM = """You clean up raw automatic-speech-recognition transcripts of university
lectures so a student can actually read them.

You are an editor, NOT a summarizer. This is the single most important rule:
every idea, example, aside, and number in the input must survive into your
output. You are only allowed to remove:
  - filler words (um, uh, er, like as filler, you know, I mean, sort of)
  - false starts and self-corrections, keeping the corrected version
  - stutters and immediate word repetitions
  - dead air and transcription noise markers

You must:
  - restore punctuation, capitalization, and sentence boundaries
  - group sentences into readable paragraphs by topic
  - fix obvious speech-recognition errors using context (technical terms,
    names, numbers). If a word is unrecoverable, keep your best guess and
    mark it [?].
  - keep every [HH:MM:SS] timestamp marker exactly where it appears in the
    input, on its own line

Never add commentary, headings, summaries, or bullet points that weren't
spoken. Never compress two spoken sentences into one shorter one. Output the
edited transcript and nothing else."""

_CLEAN_PROMPT = """Clean up this lecture transcript portion ({part} of {total}) following your
instructions. Preserve everything that was said; only remove disfluencies and
fix readability.

{text}"""


def build_readable_transcript(
    segments: list[Segment],
    class_name: str,
    date_string: str,
    api_key: str,
    model: str = MODEL_FALLBACK,
    status_callback=None,
) -> str:
    def status(message: str) -> None:
        if status_callback:
            try:
                status_callback(message)
            except Exception:
                pass

    if not segments:
        raise NotesUnavailable("No speech was transcribed.")

    client = _client(api_key)
    # Smaller chunks here: the model has to reproduce nearly all of the input,
    # so the output budget is the binding constraint, not the input.
    chunks = chunk_segments(segments, max_chars=18000)
    total = len(chunks)

    pieces: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        status(f"Cleaning up the transcript ({index}/{total})...")
        prompt = _CLEAN_PROMPT.format(
            part=index, total=total, text=chunk_to_text(chunk)
        )
        pieces.append(_call(client, model, _CLEAN_SYSTEM, prompt, _MAX_TOKENS_CLEAN))

    duration = format_timestamp(segments[-1].end)
    header = (
        f"# {class_name} - {date_string}\n\n"
        f"Full transcript, cleaned for readability. Length: {duration}.\n"
        f"Nothing has been summarized or removed except filler words and false starts.\n\n"
        f"---\n\n"
    )
    return header + "\n\n".join(pieces).strip() + "\n"
