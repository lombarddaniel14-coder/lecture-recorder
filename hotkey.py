"""Global hotkey registration that works while another app has focus.

Tries the `keyboard` package first (simplest, reliable on Windows). If it
isn't available or fails to bind, falls back to `pynput`. If both fail the
app still runs - the GUI button always works.
"""

from __future__ import annotations

_MODIFIERS = {
    "ctrl": "<ctrl>", "control": "<ctrl>",
    "alt": "<alt>",
    "shift": "<shift>",
    "win": "<cmd>", "windows": "<cmd>", "cmd": "<cmd>", "super": "<cmd>",
}


def _to_pynput(hotkey: str) -> str:
    parts = [p.strip().lower() for p in hotkey.split("+") if p.strip()]
    out = []
    for part in parts:
        if part in _MODIFIERS:
            out.append(_MODIFIERS[part])
        elif len(part) == 1:
            out.append(part)
        else:
            out.append(f"<{part}>")
    return "+".join(out)


class HotkeyManager:
    """Registers one global hotkey and calls `callback` when it fires."""

    def __init__(self, hotkey: str, callback):
        self.hotkey = hotkey
        self.callback = callback
        self.backend = None
        self._keyboard_handle = None
        self._pynput_listener = None
        self.error: str | None = None

    def start(self) -> bool:
        if self._try_keyboard():
            return True
        if self._try_pynput():
            return True
        return False

    def _try_keyboard(self) -> bool:
        try:
            import keyboard
        except Exception as exc:
            self.error = f"keyboard package unavailable ({exc})"
            return False
        try:
            self._keyboard_handle = keyboard.add_hotkey(
                self.hotkey, self.callback, suppress=False
            )
            self.backend = "keyboard"
            return True
        except Exception as exc:
            self.error = f"keyboard couldn't bind '{self.hotkey}' ({exc})"
            return False

    def _try_pynput(self) -> bool:
        try:
            from pynput import keyboard as pk
        except Exception as exc:
            self.error = f"{self.error or ''} / pynput unavailable ({exc})".strip(" /")
            return False
        try:
            combo = _to_pynput(self.hotkey)
            listener = pk.GlobalHotKeys({combo: self.callback})
            listener.daemon = True
            listener.start()
            self._pynput_listener = listener
            self.backend = "pynput"
            return True
        except Exception as exc:
            self.error = f"{self.error or ''} / pynput couldn't bind '{self.hotkey}' ({exc})".strip(" /")
            return False

    def stop(self) -> None:
        if self._keyboard_handle is not None:
            try:
                import keyboard

                keyboard.remove_hotkey(self._keyboard_handle)
            except Exception:
                pass
            self._keyboard_handle = None

        if self._pynput_listener is not None:
            try:
                self._pynput_listener.stop()
            except Exception:
                pass
            self._pynput_listener = None
