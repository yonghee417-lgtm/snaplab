"""Hotkey input widget: clicking it captures the next key combo from the user.

Stores the combo in pynput's GlobalHotKeys format, e.g. `<ctrl>+<shift>+a`.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QLineEdit


# Qt key -> pynput token. Only includes keys the user might bind.
_SPECIAL = {
    Qt.Key_Space: "<space>",
    Qt.Key_Tab: "<tab>",
    Qt.Key_Backspace: "<backspace>",
    Qt.Key_Return: "<enter>",
    Qt.Key_Enter: "<enter>",
    Qt.Key_Escape: "<esc>",
    Qt.Key_Left: "<left>",
    Qt.Key_Right: "<right>",
    Qt.Key_Up: "<up>",
    Qt.Key_Down: "<down>",
    Qt.Key_Home: "<home>",
    Qt.Key_End: "<end>",
    Qt.Key_PageUp: "<page_up>",
    Qt.Key_PageDown: "<page_down>",
    Qt.Key_Insert: "<insert>",
    Qt.Key_Delete: "<delete>",
}
for i in range(1, 13):
    _SPECIAL[getattr(Qt, f"Key_F{i}")] = f"<f{i}>"


class HotkeyEdit(QLineEdit):
    """Captures and displays a hotkey combination."""

    hotkey_changed = Signal(str)

    def __init__(self, value: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setPlaceholderText("키 조합 입력")
        self.set_hotkey(value)
        self.setCursor(Qt.IBeamCursor)

    def set_hotkey(self, value: str) -> None:
        self._value = value
        self.setText(_pretty(value))

    def hotkey(self) -> str:
        return self._value

    def focusInEvent(self, e: QFocusEvent) -> None:
        super().focusInEvent(e)
        self.setText("키 조합 입력… (Esc 취소, Backspace 삭제)")
        self.selectAll()

    def focusOutEvent(self, e: QFocusEvent) -> None:
        super().focusOutEvent(e)
        self.setText(_pretty(self._value))

    def mousePressEvent(self, e: QMouseEvent) -> None:
        super().mousePressEvent(e)
        self.setFocus(Qt.MouseFocusReason)
        self.selectAll()

    def keyPressEvent(self, e: QKeyEvent) -> None:
        key = e.key()
        if key == Qt.Key_Escape:
            self.clearFocus()
            e.accept()
            return
        if key == Qt.Key_Backspace:
            self._value = ""
            self.setText("")
            self.hotkey_changed.emit("")
            self.clearFocus()
            e.accept()
            return
        # Ignore lone modifiers; wait for the actual key.
        if key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Meta, Qt.Key_Alt, Qt.Key_AltGr):
            e.accept()
            return

        mods = e.modifiers()
        parts: list[str] = []
        if mods & Qt.ControlModifier:
            parts.append("<ctrl>")
        if mods & Qt.AltModifier:
            parts.append("<alt>")
        if mods & Qt.ShiftModifier:
            parts.append("<shift>")
        if mods & Qt.MetaModifier:
            parts.append("<cmd>")

        token = _key_token(key, e.text())
        if token is None:
            e.accept()
            return
        if not parts and len(token) == 1:
            # Bare character keys are too easy to trigger globally.
            self.setText("Ctrl/Alt/Shift와 함께 입력하세요")
            e.accept()
            return

        parts.append(token)
        combo = "+".join(parts)
        self._value = combo
        self.setText(_pretty(combo))
        self.hotkey_changed.emit(combo)
        self.clearFocus()
        e.accept()


def _key_token(key: int, text: str = "") -> str | None:
    token = _SPECIAL.get(key)
    if token is not None:
        return token
    if int(Qt.Key_A) <= key <= int(Qt.Key_Z):
        return chr(ord("a") + key - int(Qt.Key_A))
    if int(Qt.Key_0) <= key <= int(Qt.Key_9):
        return chr(ord("0") + key - int(Qt.Key_0))
    if text and text.isprintable():
        return text.lower()
    return None


def _pretty(combo: str) -> str:
    """Display form. `<ctrl>+<shift>+a` -> `Ctrl+Shift+A`."""
    if not combo:
        return ""
    out = []
    for token in combo.split("+"):
        token = token.strip().strip("<>")
        if token in {"ctrl", "alt", "shift"}:
            out.append(token.capitalize())
        elif token == "cmd":
            out.append("Cmd")
        elif token.startswith("f") and token[1:].isdigit():
            out.append(token.upper())
        elif len(token) == 1:
            out.append(token.upper())
        else:
            out.append(token.replace("_", " ").title())
    return "+".join(out)
