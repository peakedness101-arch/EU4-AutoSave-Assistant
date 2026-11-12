from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from ..timetable import (
    GameDate, MONTH_DAYS, TimetableEntry, TimetableStore, read_timetable, write_timetable,
)


class DateStepper(QWidget):
    """Real buttons avoid platform-style spinbox arrow hitbox differences."""

    def __init__(self, spin: QSpinBox, label: str):
        super().__init__()
        spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        spin.setMinimumWidth(76 if label == "年" else 42)
        self.up = QToolButton()
        self.down = QToolButton()
        for button, symbol, direction in [(self.up, "▲", "增加"), (self.down, "▼", "减少")]:
            button.setText(symbol)
            button.setAccessibleName(f"{direction}{label}")
            button.setToolTip(f"{direction}{label}")
            button.setAutoRepeat(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setFixedSize(28, 20)
            button.setStyleSheet("QToolButton { padding: 0px; }")
        self.up.clicked.connect(spin.stepUp)
        self.down.clicked.connect(spin.stepDown)
        def update_buttons():
            self.up.setEnabled(spin.value() < spin.maximum())
            self.down.setEnabled(spin.value() > spin.minimum())
        spin.valueChanged.connect(update_buttons)
        self.update_buttons = update_buttons
        buttons = QVBoxLayout()
        buttons.setSpacing(0)
        buttons.addWidget(self.up)
        buttons.addWidget(self.down)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        row.addWidget(spin)
        row.addLayout(buttons)
        update_buttons()


class TimetablePanel(QWidget):
    changed = Signal()

    def __init__(self, store: TimetableStore):
        super().__init__()
        self.store = store
        self._draft: tuple[GameDate, str] | None = None
        self._draft_row: int | None = None
        self.date_status = QLabel("判定日期：尚无可用游戏日期")
        self.storage_status = QLabel()
        self.storage_status.setWordWrap(True)
        self.storage_status.setTextFormat(Qt.TextFormat.PlainText)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["事项日期", "注意事项"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.currentCellChanged.connect(self._selection_changed)
        self.year = QSpinBox()
        self.year.setRange(1, 20000)
        self.year.setValue(1444)
        self.month = QSpinBox()
        self.month.setRange(1, 12)
        self.day = QSpinBox()
        self.day.setRange(1, 31)
        self.month.valueChanged.connect(self._constrain_day)
        self.note = QPlainTextEdit()
        self.note.setPlaceholderText("输入注意事项，可换行")
        self.note.setMaximumHeight(150)
        for control in [self.year, self.month, self.day]:
            control.valueChanged.connect(self._sync_draft)
        self.note.textChanged.connect(self._sync_draft)
        self.new_button = QPushButton("新增")
        self.save_button = QPushButton("保存事项")
        self.delete_button = QPushButton("删除所选")
        self.import_button = QPushButton("导入 JSON 并替换")
        self.export_button = QPushButton("导出 JSON")
        self.new_button.clicked.connect(self.new_entry)
        self.save_button.clicked.connect(self.save_entry)
        self.delete_button.clicked.connect(self.delete_entry)
        self.import_button.clicked.connect(self.import_file)
        self.export_button.clicked.connect(self.export_file)
        layout = QVBoxLayout(self)
        layout.addWidget(self.date_status)
        layout.addWidget(self.storage_status)
        layout.addWidget(self.table, 1)
        date_row = QHBoxLayout()
        self.date_steppers: list[DateStepper] = []
        for control, text in [(self.year, "年"), (self.month, "月"), (self.day, "日")]:
            stepper = DateStepper(control, text)
            self.date_steppers.append(stepper)
            date_row.addWidget(stepper)
            date_row.addWidget(QLabel(text))
        date_row.addStretch()
        form = QFormLayout()
        form.addRow("事项日期", date_row)
        form.addRow("注意事项", self.note)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        for button in [self.new_button, self.save_button, self.delete_button, self.import_button, self.export_button]:
            buttons.addWidget(button)
        layout.addLayout(buttons)
        layout.addWidget(QLabel("提醒范围：事项日期前后三个月（含两端）；导入将替换整份时间表，并备份原文件。"))
        self._refresh()

    def _constrain_day(self) -> None:
        self.day.setMaximum(MONTH_DAYS[self.month.value() - 1])
        if hasattr(self, "date_steppers") and len(self.date_steppers) == 3:
            self.date_steppers[2].update_buttons()

    def _selected_index(self) -> int | None:
        item = self.table.item(self.table.currentRow(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _selection_changed(self, *_args) -> None:
        index = self._selected_index()
        if self._draft_row is not None and self.table.currentRow() == self._draft_row and self._draft is not None:
            date, note = self._draft
            self._populate(date, note)
            self.save_button.setText("保存新事项")
            self.storage_status.setText("正在新增（尚未保存）：填写注意事项后点击“保存新事项”。")
            return
        if index is None:
            return
        entry = self.store.entries[index]
        self._populate(entry.date, entry.note)
        self.save_button.setText("保存修改")

    def _populate(self, date: GameDate, note: str) -> None:
        blockers = [QSignalBlocker(control) for control in [self.year, self.month, self.day, self.note]]
        self.year.setValue(date.year)
        self.month.setValue(date.month)
        self._constrain_day()
        self.day.setValue(date.day)
        self.note.setPlainText(note)
        del blockers
        for stepper in self.date_steppers:
            stepper.update_buttons()

    def _sync_draft(self) -> None:
        if self._draft_row is None or self.table.currentRow() != self._draft_row:
            return
        date = GameDate(self.year.value(), self.month.value(), self.day.value())
        note = self.note.toPlainText()
        self._draft = date, note
        self.table.item(self._draft_row, 0).setText(str(date))
        self.table.item(self._draft_row, 1).setText("[未保存] " + (" ".join(note.splitlines()).strip() or "请在下方填写注意事项"))

    def _append_draft(self, date: GameDate, note: str) -> None:
        self._draft = date, note
        self._draft_row = self.table.rowCount()
        self.table.insertRow(self._draft_row)
        self.table.setItem(self._draft_row, 0, QTableWidgetItem(str(date)))
        self.table.setItem(self._draft_row, 1, QTableWidgetItem("[未保存] " + (" ".join(note.splitlines()).strip() or "请在下方填写注意事项")))

    def _refresh(self) -> None:
        self._draft = None
        self._draft_row = None
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.store.entries))
        for row, (index, entry) in enumerate(sorted(enumerate(self.store.entries), key=lambda pair: pair[1].date)):
            date = QTableWidgetItem(str(entry.date))
            date.setData(Qt.ItemDataRole.UserRole, index)
            note = QTableWidgetItem(" ".join(entry.note.splitlines()).strip())
            note.setToolTip(entry.note)
            self.table.setItem(row, 0, date)
            self.table.setItem(row, 1, note)
        self.table.setCurrentCell(-1, -1)
        self.table.blockSignals(False)
        self.note.clear()
        self.save_button.setText("保存事项")
        error = self.store.load_error
        self.storage_status.setText(
            f"时间表读取失败：{error}\n原文件已保留。请修复文件后重启，或导入有效 JSON 恢复。"
            if error else f"已保存 {len(self.store.entries)} 条事项"
        )
        for button in [self.new_button, self.save_button, self.delete_button, self.export_button]:
            button.setEnabled(error is None)

    def new_entry(self) -> None:
        if self.store.load_error:
            return
        if self._draft is None:
            self._append_draft(
                GameDate(self.year.value(), self.month.value(), self.day.value()),
                self.note.toPlainText(),
            )
        self.table.setCurrentCell(self._draft_row, 0)
        self._selection_changed()
        self.table.scrollToItem(self.table.item(self._draft_row, 0))
        self.note.setFocus(Qt.FocusReason.OtherFocusReason)

    def _error(self, error: Exception) -> None:
        QMessageBox.warning(self, "时间表操作失败", str(error))

    def save_entry(self) -> None:
        try:
            entry = TimetableEntry(GameDate(self.year.value(), self.month.value(), self.day.value()), self.note.toPlainText().strip())
            entries = list(self.store.entries)
            index = self._selected_index()
            pending = self._draft if index is not None else None
            if index is None:
                entries.append(entry)
            else:
                entries[index] = entry
            self.store.save(entries)
        except (OSError, ValueError) as exc:
            self._error(exc)
            return
        self._refresh()
        if pending is not None:
            self._append_draft(*pending)
        self.changed.emit()

    def delete_entry(self) -> None:
        if self._draft_row is not None and self.table.currentRow() == self._draft_row:
            self.table.removeRow(self._draft_row)
            self._draft = None
            self._draft_row = None
            self.table.setCurrentCell(-1, -1)
            self.note.clear()
            self.save_button.setText("保存事项")
            self.storage_status.setText(f"已取消未保存事项；已保存 {len(self.store.entries)} 条事项")
            return
        index = self._selected_index()
        if index is None:
            return
        entries = list(self.store.entries)
        del entries[index]
        try:
            self.store.save(entries)
        except (OSError, ValueError) as exc:
            self._error(exc)
            return
        pending = self._draft
        self._refresh()
        if pending is not None:
            self._append_draft(*pending)
        self.changed.emit()

    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入时间表（替换全部事项）", "", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            entries = read_timetable(Path(path))
            answer = QMessageBox.question(
                self, "替换时间表",
                f"将用文件中的 {len(entries)} 条事项替换当前全部 {len(self.store.entries)} 条事项。\n原文件会先自动备份。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            backup = self.store.replace(entries)
        except (OSError, ValueError) as exc:
            self._error(exc)
            return
        self._refresh()
        if backup:
            self.storage_status.setText(f"已导入 {len(entries)} 条事项；原文件备份：{backup}")
        self.changed.emit()

    def export_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出时间表", "timetable.json", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            write_timetable(Path(path), self.store.entries)
        except (OSError, ValueError) as exc:
            self._error(exc)
            return
        self.storage_status.setText(f"已导出 {len(self.store.entries)} 条事项：{path}")
