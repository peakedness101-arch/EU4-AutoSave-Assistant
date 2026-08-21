from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QWidget

LOGGER = logging.getLogger("eu4_assistant.hotkeys")

_IS_WINDOWS = os.name == "nt"

WM_HOTKEY = 0x0312

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

_USER32 = ctypes.WinDLL("user32", use_last_error=True) if _IS_WINDOWS else None
if _USER32 is not None:
    _USER32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
    _USER32.RegisterHotKey.restype = wintypes.BOOL
    _USER32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _USER32.UnregisterHotKey.restype = wintypes.BOOL

_VK_BY_KEY = {
    Qt.Key.Key_Space: 0x20,
    Qt.Key.Key_Tab: 0x09,
    Qt.Key.Key_Backspace: 0x08,
    Qt.Key.Key_Return: 0x0D,
    Qt.Key.Key_Enter: 0x0D,
    Qt.Key.Key_Escape: 0x1B,
    Qt.Key.Key_Delete: 0x2E,
    Qt.Key.Key_Insert: 0x2D,
    Qt.Key.Key_Home: 0x24,
    Qt.Key.Key_End: 0x23,
    Qt.Key.Key_PageUp: 0x21,
    Qt.Key.Key_PageDown: 0x22,
    Qt.Key.Key_Left: 0x25,
    Qt.Key.Key_Up: 0x26,
    Qt.Key.Key_Right: 0x27,
    Qt.Key.Key_Down: 0x28,
}


def _qt_key_to_vk(key: Qt.Key) -> int | None:
    value = int(key)
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return value
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return value
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35:
        return 0x70 + (value - int(Qt.Key.Key_F1))
    return _VK_BY_KEY.get(key)


def sequence_to_registration(sequence: QKeySequence) -> tuple[int, int] | None:
    """Return ``(modifiers, virtual_key)`` for a single-combination sequence."""
    if sequence.isEmpty():
        return None
    combination = sequence[0]
    modifiers = combination.keyboardModifiers()
    key = combination.key()
    mods = 0
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        mods |= MOD_CONTROL
    if modifiers & Qt.KeyboardModifier.AltModifier:
        mods |= MOD_ALT
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        mods |= MOD_SHIFT
    if modifiers & Qt.KeyboardModifier.MetaModifier:
        mods |= MOD_WIN
    vk = _qt_key_to_vk(key)
    if vk is None:
        return None
    return mods, vk


class GlobalHotkeyManager(QWidget):
    """Registers Windows system-wide hotkeys and re-emits them as Qt signals."""

    triggered = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self._by_id: dict[int, tuple[int, int]] = {}
        self._next_id = 1
        self._native_window = False
        self.last_error_code: int | None = None
        self.last_error_message = ""

    def _ensure_native_window(self) -> bool:
        if self._native_window:
            return True
        if not _IS_WINDOWS:
            return False
        if int(self.winId()) == 0:
            return False
        self._native_window = True
        return True

    def register(self, sequence: QKeySequence) -> int | None:
        """Register a hotkey; returns its id or ``None`` when unusable."""
        self.last_error_code = None
        self.last_error_message = ""
        registration = sequence_to_registration(sequence)
        if registration is None:
            self.last_error_message = "快捷键为空或包含不支持的按键"
            return None
        if not self._ensure_native_window():
            self.last_error_message = "无法创建快捷键原生窗口"
            LOGGER.warning("无法创建热键原生窗口，全局快捷键未注册")
            return None
        mods, vk = registration
        hotkey_id = self._next_id
        self._next_id += 1
        if not _IS_WINDOWS:
            return None
        ctypes.set_last_error(0)
        result = _USER32.RegisterHotKey(
            int(self.winId()), hotkey_id, mods | MOD_NOREPEAT, vk
        )
        if not result:
            self.last_error_code = ctypes.get_last_error()
            if self.last_error_code == ERROR_HOTKEY_ALREADY_REGISTERED:
                self.last_error_message = "已被其它程序或另一个快捷键占用"
            else:
                self.last_error_message = f"Windows 错误 {self.last_error_code or '未知'}"
            LOGGER.warning(
                "全局快捷键注册失败：%s（%s）",
                sequence.toString(),
                self.last_error_message,
            )
            return None
        self._by_id[hotkey_id] = (mods, vk)
        return hotkey_id

    def unregister(self, hotkey_id: int) -> None:
        if hotkey_id not in self._by_id:
            return
        if _IS_WINDOWS:
            _USER32.UnregisterHotKey(int(self.winId()), hotkey_id)
        del self._by_id[hotkey_id]

    def clear(self) -> None:
        for hotkey_id in list(self._by_id):
            self.unregister(hotkey_id)

    def nativeEvent(self, event_type, message):  # noqa: N802 - Qt naming
        if self._native_window and _IS_WINDOWS:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self.triggered.emit(int(msg.wParam))
                return True, 0
        return super().nativeEvent(event_type, message)
