from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import CountrySnapshot
from .assets import country_flag_pixmap, game_interface_pixmap

_ICON_CANDIDATES = {
    "treasury": ["icon_gold.dds"],
    "income": ["icon_diplomacy_economy.dds", "vassal_income.dds"],
    "expense": ["root_out_corruption.dds", "icon_gold.dds"],
    "interest": ["icon_gold.dds"],
    "army": ["icon_army.dds", "icon_manpower.dds"],
    "manpower": ["icon_manpower.dds", "development_button_manpower.dds"],
    "navy": ["button_navy.dds", "big_ship_icon_small.dds"],
    "sailors": ["icon_sailors.dds", "icon_sailors2.dds"],
}

_STAT_ROWS = [
    ("treasury", "国库"),
    ("income", "上月收入"),
    ("expense", "上月支出"),
    ("interest", "上月利息"),
    ("army", "陆军数量"),
    ("manpower", "陆军人力"),
    ("navy", "船只数量"),
    ("sailors", "水手数量"),
]

_IS_WINDOWS = os.name == "nt"
_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_LAYERED = 0x00080000
_WS_EX_NOACTIVATE = 0x08000000
_HWND_TOPMOST = -1
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020
_USER32 = ctypes.WinDLL("user32", use_last_error=True) if _IS_WINDOWS else None
if _USER32 is not None:
    _USER32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _USER32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _USER32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _USER32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _USER32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    _USER32.SetWindowPos.restype = wintypes.BOOL


class MiniCountryWindow(QWidget):
    """Floating, always-on-top HUD showing coarse country economy and forces."""

    switchCountry = Signal(int)
    lockToggled = Signal()
    closeRequested = Signal()

    def __init__(
        self, game_dir: str, mod_dir: str | None = None, parent: QWidget | None = None
    ):
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        super().__init__(parent, flags)
        self.setObjectName("miniWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMinimumWidth(272)
        self._game_dir = game_dir
        self._mod_dir = mod_dir
        self._locked = False
        self._drag_offset = None
        self._build()
        self._apply_style()

    @property
    def is_locked(self) -> bool:
        return self._locked

    def set_game_dir(self, game_dir: str) -> None:
        self._game_dir = game_dir
        self._refresh_resource_art()

    def set_resource_roots(self, game_dir: str, mod_dir: str | None) -> None:
        self._game_dir = game_dir
        self._mod_dir = mod_dir
        self._refresh_resource_art()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)
        self.flag_label = QLabel()
        self.flag_label.setFixedSize(26, 26)
        self.flag_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label = QLabel("未选择国家")
        self.title_label.setObjectName("miniTitle")
        header.addWidget(self.flag_label)
        header.addWidget(self.title_label, 1)
        self.country_switch_buttons: list[QPushButton] = []
        for symbol, direction in (("◀", -1), ("▶", 1)):
            button = QPushButton(symbol)
            button.setFixedSize(28, 28)
            button.clicked.connect(
                lambda _checked=False, step=direction: self.switchCountry.emit(step)
            )
            header.addWidget(button)
            self.country_switch_buttons.append(button)
        self.lock_button = QPushButton("锁定")
        self.lock_button.setObjectName("miniLockButton")
        self.lock_button.setFixedWidth(56)
        self.lock_button.clicked.connect(self._lock_clicked)
        close_button = QPushButton("×")
        close_button.setFixedSize(28, 28)
        close_button.clicked.connect(self.closeRequested.emit)
        header.addWidget(self.lock_button)
        header.addWidget(close_button)
        root.addLayout(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        self.stat_rows: dict[str, QLabel] = {}
        self.icon_labels: dict[str, QLabel] = {}
        for row, (key, label) in enumerate(_STAT_ROWS):
            icon = QLabel()
            icon.setFixedSize(20, 20)
            pixmap = game_interface_pixmap(
                self._game_dir,
                _ICON_CANDIDATES[key],
                (18, 18),
                mod_dir=self._mod_dir,
            )
            if not pixmap.isNull():
                icon.setPixmap(pixmap)
            key_cell = QHBoxLayout()
            key_cell.setSpacing(5)
            key_cell.addWidget(icon)
            key_label = QLabel(label)
            key_label.setObjectName("miniKey")
            key_cell.addWidget(key_label)
            key_cell.addStretch(1)
            value = QLabel("—")
            value.setObjectName("miniValue")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addLayout(key_cell, row, 0)
            grid.addWidget(value, row, 1)
            self.stat_rows[key] = value
            self.icon_labels[key] = icon
        root.addLayout(grid)

        self.lock_hint = QLabel("已锁定：窗口已穿透，防止误触；用快捷键解锁")
        self.lock_hint.setObjectName("miniLockHint")
        self.lock_hint.hide()
        root.addWidget(self.lock_hint)
        self._apply_lock_state()

    def _refresh_resource_art(self) -> None:
        for key, icon in getattr(self, "icon_labels", {}).items():
            pixmap = game_interface_pixmap(
                self._game_dir,
                _ICON_CANDIDATES[key],
                (18, 18),
                mod_dir=self._mod_dir,
            )
            icon.setPixmap(pixmap)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget#miniWindow {
                background: rgba(12, 22, 35, 166);
                border: 1px solid #3f637e;
                border-radius: 8px;
            }
            QLabel { background: transparent; color: #cfe0ec; }
            QLabel#miniTitle { color: white; font-size: 14px; font-weight: 700; }
            QLabel#miniKey { color: #93a9bd; font-size: 12px; }
            QLabel#miniValue { color: white; font-size: 13px; font-weight: 600; }
            QLabel#miniLockHint { color: #fbbf24; font-size: 11px; }
            QPushButton {
                background: rgba(255, 255, 255, 18);
                border: 1px solid #4d6b82; border-radius: 4px;
                color: #d7e6f0; padding: 2px 6px; font-size: 12px;
            }
            QPushButton:hover { border-color: #8ec3e0; color: white; }
            QPushButton#miniLockButton[locked="true"] {
                background: #7f1d1d; border-color: #f59e0b; color: white;
            }
            """
        )

    def set_country(self, country: CountrySnapshot | None) -> None:
        if country is None:
            self.title_label.setText("未选择国家")
            self.flag_label.clear()
            for label in self.stat_rows.values():
                label.setText("—")
            return
        self.title_label.setText(
            f"{country.tag} · {country.player_name or '非玩家国家'}"
        )
        flag = country_flag_pixmap(
            self._game_dir, country.tag, (26, 26), mod_dir=self._mod_dir
        )
        if flag.isNull():
            self.flag_label.setPixmap(QPixmap())
            self.flag_label.setText(country.tag)
        else:
            self.flag_label.setText("")
            self.flag_label.setPixmap(flag)
        values = {
            "treasury": f"{country.treasury:,.2f}",
            "income": f"{country.monthly_income:,.2f}",
            "expense": f"{country.monthly_expense:,.2f}",
            "interest": f"{country.monthly_interest:,.2f}",
            "army": f"{country.army_strength:,.0f} 人（{len(country.armies)} 支）",
            "manpower": (
                f"{country.manpower_people:,.0f}/{country.max_manpower_people:,.0f} 人"
            ),
            "navy": f"{country.ship_count:,} 艘",
            "sailors": f"{country.sailors:,.0f}/{country.max_sailors:,.0f} 人",
        }
        for key, text in values.items():
            self.stat_rows[key].setText(text)

    def set_switching_enabled(self, enabled: bool) -> None:
        for button in self.country_switch_buttons:
            button.setEnabled(enabled)
            button.setToolTip(
                "在多人模式的玩家国家间切换" if enabled else "仅多人模式可切换玩家国家"
            )

    def toggle_lock(self) -> bool:
        self._locked = not self._locked
        self._apply_lock_state()
        return self._locked

    def _lock_clicked(self) -> None:
        self.toggle_lock()
        self.lockToggled.emit()

    def _apply_lock_state(self) -> None:
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, self._locked
        )
        self.lock_button.setText("解锁" if self._locked else "锁定")
        self.lock_button.setProperty("locked", self._locked)
        self.lock_button.style().unpolish(self.lock_button)
        self.lock_button.style().polish(self.lock_button)
        self.lock_hint.setVisible(self._locked)
        self._apply_native_input_style()

    def _apply_native_input_style(self) -> None:
        if not _IS_WINDOWS or not self.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
            return
        hwnd = int(self.winId())
        style = int(_USER32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE))
        style |= _WS_EX_LAYERED | _WS_EX_NOACTIVATE
        if self._locked:
            style |= _WS_EX_TRANSPARENT
        else:
            style &= ~_WS_EX_TRANSPARENT
        ctypes.set_last_error(0)
        _USER32.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE, style)
        _USER32.SetWindowPos(
            hwnd,
            _HWND_TOPMOST,
            0,
            0,
            0,
            0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_FRAMECHANGED,
        )

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._apply_native_input_style()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)
