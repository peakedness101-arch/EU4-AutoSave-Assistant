from __future__ import annotations

import logging
import math
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QLineSeries,
    QPieSeries,
    QValueAxis,
)
from PySide6.QtCore import (
    QFileSystemWatcher,
    QPoint,
    QPointF,
    QUrl,
    Signal,
    Qt,
    QThreadPool,
    QTimer,
)
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QDialog,
    QFileDialog,
    QFrame,
    QFormLayout,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..alerts import economic_alerts
from ..archive import archive_many, archive_save, preview_archive_path, undo_last_archive
from ..bridge import BridgeClient
from ..calculator import (
    LoanCalculationError,
    calculate_loan_capacity,
    select_standard_loan_principal,
)
from ..compare import (
    comparison_metric_value,
    comparison_series,
    consecutive_date_gaps,
    forensic_differences,
    validate_same_game_version,
)
from ..config import AppConfig, PROJECT_ROOT, load_config, save_config
from ..country_names import country_label, country_name
from ..mapdata import (
    ProvinceInfo,
    build_political_map,
    load_or_build_province_index,
    province_id_at,
)
from ..models import CountrySnapshot, SaveRecord
from ..parser import parse_save
from ..scheduling import AutosaveScheduler, ScheduledSaveRequest
from ..savefiles import latest_save, managed_autosaves
from ..storage import SaveDatabase
from ..versioning import detect_game_version
from ..workers import FunctionWorker
from .assets import (
    country_flag_pixmap,
    game_interface_pixmap,
    game_logo_pixmap,
    pil_to_qimage,
)


LOGGER = logging.getLogger("eu4_assistant.ui")


class SortableTableWidgetItem(QTableWidgetItem):
    """Table item that keeps formatted text while sorting by its raw number."""

    def __init__(self, text: str, sort_value: float | int | None = None) -> None:
        super().__init__(text)
        if sort_value is not None:
            self.setData(Qt.ItemDataRole.UserRole, sort_value)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(Qt.ItemDataRole.UserRole)
        right = other.data(Qt.ItemDataRole.UserRole)
        if left is not None and right is not None:
            return float(left) < float(right)
        return self.text().casefold() < other.text().casefold()


class MapView(QGraphicsView):
    mapClicked = Signal(QPointF)

    def __init__(self, scene: QGraphicsScene):
        super().__init__(scene)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QColor("#1f3441"))
        self._press_position: QPoint | None = None

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming convention
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt naming convention
        press_position = self._press_position
        super().mouseReleaseEvent(event)
        if (
            event.button() == Qt.MouseButton.LeftButton
            and press_position is not None
            and (event.position().toPoint() - press_position).manhattanLength() <= 5
        ):
            scene_position = self.mapToScene(event.position().toPoint())
            QTimer.singleShot(0, lambda position=scene_position: self.mapClicked.emit(position))
        self._press_position = None

    def wheelEvent(self, event):  # noqa: N802 - Qt naming convention
        current = self.transform().m11()
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        target = current * factor
        if 0.05 <= target <= 24.0:
            self.scale(factor, factor)
        event.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EU4 联机自动存档与分析助手")
        self.resize(1500, 920)
        self.config = load_config()
        self.database = SaveDatabase(self.config.database_path)
        self.thread_pool = QThreadPool.globalInstance()
        self._active_workers: set[FunctionWorker] = set()
        self.records: dict[str, SaveRecord] = {}
        self.current_record: SaveRecord | None = None
        self.provinces: dict[int, ProvinceInfo] = {}
        self.map_cache_dir = PROJECT_ROOT / "data" / "map_cache"
        self.bridge = BridgeClient(
            self.config.game_dir,
            allow_unsupported_version=self.config.allow_unsupported_version,
        )
        self.scheduler = AutosaveScheduler(self.config.autosave_mode, now=time.monotonic())
        self.save_request_busy = False
        self.last_bridge_game_date: str | None = None
        self.bridge_poll_busy = False
        self.compare_records: list[SaveRecord] = []
        self.auto_archive_busy = False
        self.auto_archive_seen: dict[str, int] = {}
        self.filling_calculator = False
        self.map_index_busy = False
        self.map_render_generation = 0
        self.sidebar_collapsed = False
        self.selected_country_tag: str | None = None
        self.army_popup_widget: QFrame | None = None
        self.tool_dialogs: dict[str, QDialog] = {}
        self.analysis_dialogs: list[QDialog] = []

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self._build_control_dialog()
        self._build_map_tab()
        central_layout.addWidget(self.map_page, 1)
        self._build_dashboard_tab()
        self._build_country_details_dialog()
        self._build_army_dialog()
        self._build_alerts_dialog()
        self._build_archive_tab()
        self._build_compare_tab()
        self._build_calculator_tab()
        self._build_settings_tab()
        self._apply_theme()
        self._refresh_game_art()
        self._refresh_version_status()
        self._load_database_index()
        self._install_save_watcher()

        self.bridge_timer = QTimer(self)
        self.bridge_timer.timeout.connect(self._poll_bridge)
        self.bridge_timer.start(5000)

    def _build_control_dialog(self) -> None:
        self.left_rail = QFrame()
        self.left_rail.setObjectName("controlPanel")
        self.left_rail.setMinimumWidth(238)
        self.left_rail.setMaximumWidth(270)
        layout = QVBoxLayout(self.left_rail)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(7)

        self.logo_label = QLabel("EU4 战局助手")
        self.logo_label.setObjectName("gameLogo")
        self.logo_label.setFixedHeight(54)
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.logo_label)
        title = QLabel("联机存档与战局分析")
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.import_status = QLabel("选择存档后可查看政治地图、告警和国家数据")
        self.import_status.setObjectName("subtleText")
        self.import_status.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(self.import_status)
        self.version_label = QLabel()
        self.version_label.setObjectName("versionChip")
        self.version_label.setWordWrap(True)
        self.bridge_label = QLabel("原生桥：未连接")
        self.bridge_label.setObjectName("bridgeChip")
        self.bridge_label.setWordWrap(True)
        layout.addWidget(self.version_label)
        layout.addWidget(self.bridge_label)
        self.compatibility_risk_banner = QLabel(
            "⚠ 非 491d 风险模式：将尝试自动存档与解析；可能导致游戏崩溃、掉线或存档不可用。"
        )
        self.compatibility_risk_banner.setObjectName("compatibilityRiskBanner")
        self.compatibility_risk_banner.setWordWrap(True)
        self.compatibility_risk_banner.hide()
        layout.addWidget(self.compatibility_risk_banner)
        layout.addWidget(QLabel("自动存档周期"))
        self.schedule_combo = QComboBox()
        self.schedule_combo.addItem("仅手动", "manual")
        self.schedule_combo.addItem("每 3 个游戏月", "quarterly")
        self.schedule_combo.addItem("每个游戏年", "yearly")
        self.schedule_combo.addItem("每 10 个现实分钟", "ten_minutes")
        selected = self.schedule_combo.findData(self.config.autosave_mode)
        self.schedule_combo.setCurrentIndex(max(selected, 0))
        self.reconnect_button = QPushButton("连接原生桥")
        self.reconnect_button.clicked.connect(self._connect_bridge)
        self.save_now_button = QPushButton("立即存档")
        self.save_now_button.setObjectName("primaryButton")
        self.save_now_button.clicked.connect(lambda: self._request_native_save())
        self.import_button = QPushButton("导入存档")
        self.import_button.clicked.connect(self._choose_saves)
        self.quick_read_button = QPushButton("⚡ 快速读取最新存档")
        self.quick_read_button.setObjectName("primaryButton")
        self.quick_read_button.clicked.connect(self._quick_read_latest_save)
        self.save_combo = QComboBox()
        self.save_combo.currentIndexChanged.connect(self._select_save)
        layout.addWidget(self.schedule_combo)
        layout.addWidget(self.reconnect_button)
        layout.addWidget(self.save_now_button)
        layout.addWidget(self.quick_read_button)
        layout.addWidget(self.import_button)
        layout.addWidget(QLabel("当前存档"))
        layout.addWidget(self.save_combo)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)
        self.left_tool_buttons: dict[str, QPushButton] = {}
        for key, label in [
            ("countries", "国家列表"),
            ("country_details", "国家详细分析"),
            ("armies", "军队总览"),
            ("alerts", "玩家警告总览"),
            ("archive", "归档与改名"),
            ("compare", "多存档对比"),
            ("calculator", "贷款计算器"),
            ("settings", "设置与诊断"),
        ]:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, name=key: self._show_tool_dialog(name))
            layout.addWidget(button)
            self.left_tool_buttons[key] = button
        refresh_map = QPushButton("刷新政治地图")
        refresh_map.clicked.connect(self._ensure_map_index)
        fit_map = QPushButton("显示完整世界")
        fit_map.clicked.connect(self._fit_world_map)
        layout.addWidget(refresh_map)
        layout.addWidget(fit_map)
        layout.addStretch(1)

    def _register_tool_dialog(
        self, key: str, title: str, content: QWidget, size: tuple[int, int]
    ) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setModal(False)
        dialog.resize(*size)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(content)
        self.tool_dialogs[key] = dialog
        if key != "settings":
            self.analysis_dialogs.append(dialog)

    def _show_tool_dialog(self, key: str) -> None:
        dialog = self.tool_dialogs.get(key)
        if dialog is None:
            return
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def closeEvent(self, event):  # noqa: N802
        LOGGER.info("主窗口正在关闭")
        if hasattr(self, "bridge_timer"):
            self.bridge_timer.stop()
        if hasattr(self, "save_watcher"):
            self.save_watcher.blockSignals(True)
        self.thread_pool.waitForDone(10000)
        self.bridge.close()
        self.database.close()
        super().closeEvent(event)

    def _build_dashboard_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        heading = QLabel("玩家国家数据")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        self.country_table = QTableWidget(0, 13)
        self.country_table.setHorizontalHeaderLabels(
            [
                "TAG",
                "国家",
                "玩家",
                "ADM/DIP/MIL",
                "科技",
                "月收入",
                "月支出",
                "月利息",
                "国库",
                "贷款",
                "债务",
                "陆军兵力",
                "告警",
            ]
        )
        self.country_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.country_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.country_table.setSortingEnabled(True)
        self.country_table.horizontalHeader().setSortIndicatorShown(True)
        self.country_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.country_table.horizontalHeader().setStretchLastSection(True)
        self.country_table.itemSelectionChanged.connect(self._country_selection_changed)
        layout.addWidget(self.country_table)
        self._register_tool_dialog("countries", "国家列表", tab, (1050, 620))

    def _build_country_details_dialog(self) -> None:
        page = QWidget()
        outer = QVBoxLayout(page)
        self.detail_country_title = QLabel("尚未选择国家")
        self.detail_country_title.setObjectName("countryTitle")
        self.detail_country_summary = QLabel("导入存档后显示详细经济与点数数据")
        self.detail_country_summary.setWordWrap(True)
        outer.addWidget(self.detail_country_title)
        outer.addWidget(self.detail_country_summary)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        idea_group = QGroupBox("理念情况")
        idea_layout = QVBoxLayout(idea_group)
        self.detail_ideas = QLabel("—")
        self.detail_ideas.setWordWrap(True)
        idea_layout.addWidget(self.detail_ideas)
        content_layout.addWidget(idea_group)

        economy_row = QHBoxLayout()
        self.detail_income_chart = QChart()
        self.detail_expense_chart = QChart()
        for chart, title in (
            (self.detail_income_chart, "上月收入分布"),
            (self.detail_expense_chart, "上月支出分布"),
        ):
            chart.setTitle(title)
            view = QChartView(chart)
            view.setRenderHint(QPainter.RenderHint.Antialiasing)
            view.setMinimumHeight(380)
            economy_row.addWidget(view, 1)
        content_layout.addLayout(economy_row)

        self.detail_mana_chart = QChart()
        mana_view = QChartView(self.detail_mana_chart)
        mana_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        mana_view.setMinimumHeight(390)
        content_layout.addWidget(mana_view)

        self.detail_mana_tables: dict[str, QTableWidget] = {}
        self.detail_mana_pies: dict[str, QChart] = {}
        for power in ("adm", "dip", "mil"):
            group = QGroupBox(f"{power.upper()} 点数用途明细")
            row = QHBoxLayout(group)
            table = QTableWidget(0, 3)
            table.setHorizontalHeaderLabels(["用途", "数值", "占比"])
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            chart = QChart()
            view = QChartView(chart)
            view.setRenderHint(QPainter.RenderHint.Antialiasing)
            view.setMinimumSize(500, 360)
            row.addWidget(table, 1)
            row.addWidget(view, 1)
            content_layout.addWidget(group)
            self.detail_mana_tables[power] = table
            self.detail_mana_pies[power] = chart
        content_layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self._register_tool_dialog("country_details", "国家详细分析", page, (1320, 860))

    def _build_army_dialog(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.army_dialog_title = QLabel("当前国家军队")
        self.army_dialog_title.setObjectName("sectionTitle")
        layout.addWidget(self.army_dialog_title)
        self.army_overview_table = QTableWidget(0, 6)
        self.army_overview_table.setHorizontalHeaderLabels(
            ["国家", "军队", "省份 ID", "团数", "实际兵力", "兵种"]
        )
        self.army_overview_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.army_overview_table.horizontalHeader().setStretchLastSection(True)
        self.army_overview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.army_overview_table)
        self._register_tool_dialog("armies", "军队总览", page, (1080, 680))

    def _build_alerts_dialog(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        header = QHBoxLayout()
        self.alert_overview_summary = QLabel("导入存档后显示玩家国家警告")
        self.alert_overview_summary.setObjectName("sectionTitle")
        refresh = QPushButton("刷新警告")
        refresh.clicked.connect(self._refresh_player_alert_overview)
        header.addWidget(self.alert_overview_summary, 1)
        header.addWidget(refresh)
        layout.addLayout(header)
        self.alert_overview_table = QTableWidget(0, 6)
        self.alert_overview_table.setHorizontalHeaderLabels(
            ["级别", "TAG", "玩家", "警告数", "警告类型", "具体信息"]
        )
        self.alert_overview_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.alert_overview_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.alert_overview_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.alert_overview_table.horizontalHeader().setStretchLastSection(True)
        self.alert_overview_table.cellDoubleClicked.connect(
            self._alert_overview_activated
        )
        layout.addWidget(self.alert_overview_table)
        hint = QLabel("双击任意一行，可在右侧栏切换到该玩家国家并查看完整警告。")
        hint.setObjectName("subtleText")
        layout.addWidget(hint)
        self._register_tool_dialog("alerts", "玩家国家警告总览", page, (1120, 680))

    def _build_map_tab(self) -> None:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.map_status = QLabel("导入存档后显示国家着色政治地图；左键拖动，滚轮缩放")
        self.map_status.hide()
        map_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.map_scene = QGraphicsScene()
        self.map_view = MapView(self.map_scene)
        self.map_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.map_view.mapClicked.connect(self._map_clicked)
        map_container = QWidget()
        map_overlay = QGridLayout(map_container)
        map_overlay.setContentsMargins(0, 0, 0, 0)
        map_overlay.addWidget(self.map_view, 0, 0)
        self.left_rail_toggle = QToolButton(map_container)
        self.left_rail_toggle.setObjectName("floatingFunctionButton")
        self.left_rail_toggle.setText("隐藏功能栏 ◀")
        self.left_rail_toggle.setFixedHeight(38)
        self.left_rail_toggle.clicked.connect(self._toggle_left_rail)
        map_overlay.addWidget(
            self.left_rail_toggle,
            0,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        self.map_year_badge = QLabel("当前年份：—", map_container)
        self.map_year_badge.setObjectName("mapYearBadge")
        self.map_year_badge.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.map_year_badge.setStyleSheet(
            "QLabel#mapYearBadge{background:rgba(13,27,42,205);color:#ffffff;"
            "border:1px solid rgba(255,255,255,120);border-radius:6px;"
            "font-size:16px;font-weight:700;padding:7px 11px;}"
        )
        map_overlay.addWidget(
            self.map_year_badge,
            0,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
        )
        map_overlay.setContentsMargins(10, 10, 0, 0)
        map_splitter.addWidget(map_container)

        self.warning_panel = QFrame()
        self.warning_panel.setObjectName("warningPanel")
        self.warning_panel.setMinimumWidth(390)
        self.warning_panel.setMaximumWidth(560)
        panel_layout = QVBoxLayout(self.warning_panel)
        panel_layout.setContentsMargins(10, 10, 10, 10)
        panel_header = QHBoxLayout()
        panel_title = QLabel("国家详情与战局警告")
        panel_title.setObjectName("sectionTitle")
        self.sidebar_toggle = QToolButton()
        self.sidebar_toggle.setText("收起 ◀")
        self.sidebar_toggle.clicked.connect(self._toggle_warning_sidebar)
        panel_header.addWidget(panel_title, 1)
        panel_header.addWidget(self.sidebar_toggle)
        panel_layout.addLayout(panel_header)
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.warning_content = QWidget()
        warning_layout = QVBoxLayout(self.warning_content)
        warning_layout.setContentsMargins(0, 0, 0, 0)
        country_header = QHBoxLayout()
        self.sidebar_flag = QLabel("旗帜")
        self.sidebar_flag.setObjectName("flagFrame")
        self.sidebar_flag.setFixedSize(76, 76)
        self.sidebar_flag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        country_text = QVBoxLayout()
        self.sidebar_country = QLabel("尚未选择国家")
        self.sidebar_country.setObjectName("countryTitle")
        self.sidebar_alert_badge = QLabel("导入存档后显示警告")
        self.sidebar_alert_badge.setObjectName("alertBadge")
        country_text.addWidget(self.sidebar_country)
        country_text.addWidget(self.sidebar_alert_badge)
        country_header.addWidget(self.sidebar_flag)
        country_header.addLayout(country_text, 1)
        warning_layout.addLayout(country_header)
        self.map_country_combo = QComboBox()
        self.map_country_combo.currentIndexChanged.connect(self._map_country_changed)
        warning_layout.addWidget(self.map_country_combo)

        self.country_overview = QGroupBox("国家概况")
        overview_grid = QGridLayout(self.country_overview)
        self.stat_labels: dict[str, QLabel] = {}
        self.stat_positions: dict[str, tuple[int, int, int]] = {}
        overview_specs = [
            ("treasury", "国库", ["icon_gold.dds"], 0, 0, 1),
            ("expense", "支出", ["root_out_corruption.dds", "icon_gold.dds"], 0, 1, 1),
            ("income", "收入", ["icon_diplomacy_economy.dds", "vassal_income.dds"], 1, 0, 1),
            ("interest", "利息支出", ["icon_gold.dds"], 1, 1, 1),
            ("technology", "科技", ["tab_domestic_technology.dds"], 2, 0, 1),
            ("ideas", "理念", ["ideas_icon.dds", "idea_groups.dds"], 2, 1, 1),
            ("powers", "点数", ["country_technology_researchbutton.dds"], 3, 0, 2),
            ("development", "发展度", ["development_icon.dds"], 4, 0, 1),
            ("stability", "稳定度", ["icon_stability.dds", "fervor_stability.dds"], 4, 1, 1),
            ("army", "陆军数量", ["icon_army.dds", "icon_manpower.dds"], 5, 0, 1),
            ("manpower", "陆军人力", ["icon_manpower.dds", "development_button_manpower.dds"], 5, 1, 1),
            ("navy", "海军数量", ["button_navy.dds", "big_ship_icon_small.dds"], 6, 0, 1),
            ("sailors", "水手数量", ["icon_sailors.dds", "icon_sailors2.dds"], 6, 1, 1),
        ]
        for key, title, icons, row, column, span in overview_specs:
            icon = QLabel()
            icon.setFixedSize(28, 28)
            pixmap = game_interface_pixmap(self.config.game_dir, icons, (26, 26))
            if not pixmap.isNull():
                icon.setPixmap(pixmap)
            value = QLabel(f"{title}\n—")
            value.setObjectName("statValue")
            cell = QHBoxLayout()
            cell.addWidget(icon)
            cell.addWidget(value, 1)
            overview_grid.addLayout(cell, row, column, 1, span)
            self.stat_labels[key] = value
            self.stat_positions[key] = (row, column, span)
        warning_layout.addWidget(self.country_overview)

        self.identity_label = QLabel("宗教：—\n主流文化：—")
        self.identity_label.setWordWrap(True)
        self.identity_label.setObjectName("identityCard")
        warning_layout.addWidget(self.identity_label)

        detail_button = QPushButton("打开国家详细分析大窗口")
        detail_button.setObjectName("primaryButton")
        detail_button.clicked.connect(lambda: self._show_tool_dialog("country_details"))
        warning_layout.addWidget(detail_button)

        warning_title = QLabel("警告具体信息")
        warning_title.setObjectName("subsectionTitle")
        warning_layout.addWidget(warning_title)
        self.alert_text = QTextEdit()
        self.alert_text.setReadOnly(True)
        self.alert_text.setPlaceholderText("收入、支出、利息、贷款和警告详情将在此显示。")
        self.alert_text.setMinimumHeight(150)
        warning_layout.addWidget(self.alert_text)

        warning_layout.addStretch(1)

        sidebar_scroll.setWidget(self.warning_content)
        panel_layout.addWidget(sidebar_scroll, 1)
        map_splitter.addWidget(self.warning_panel)
        map_splitter.setSizes([1180, 430])
        layout.addWidget(self.left_rail)
        layout.addWidget(map_splitter, 1)
        self.map_page = tab

    def _build_archive_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.archive_sources = QListWidget()
        layout.addWidget(self.archive_sources)
        controls = QGridLayout()
        choose = QPushButton("选择待归档存档")
        choose.clicked.connect(self._choose_archive_sources)
        destination_button = QPushButton("选择归档目录")
        destination_button.clicked.connect(self._choose_archive_destination)
        self.archive_destination = QLineEdit(self.config.archive_dir)
        self.campaign_edit = QLineEdit(self.config.campaign_name)
        self.remove_source = QCheckBox("验证成功后删除源文件（移动）")
        self.remove_source.setChecked(True)
        self.auto_archive_checkbox = QCheckBox("自动归档并解析桥接生成的存档")
        self.auto_archive_checkbox.setChecked(True)
        preview = QPushButton("预览命名")
        preview.clicked.connect(self._preview_archive)
        execute = QPushButton("执行安全归档")
        execute.clicked.connect(self._execute_archive)
        undo = QPushButton("撤销最后一次归档")
        undo.clicked.connect(self._undo_archive)
        controls.addWidget(choose, 0, 0)
        controls.addWidget(QLabel("战役名"), 0, 1)
        controls.addWidget(self.campaign_edit, 0, 2)
        controls.addWidget(destination_button, 1, 0)
        controls.addWidget(self.archive_destination, 1, 1, 1, 2)
        controls.addWidget(self.remove_source, 2, 0, 1, 2)
        controls.addWidget(self.auto_archive_checkbox, 2, 2)
        controls.addWidget(preview, 3, 0)
        controls.addWidget(undo, 3, 1)
        controls.addWidget(execute, 3, 2)
        layout.addLayout(controls)
        self.archive_log = QTextEdit()
        self.archive_log.setReadOnly(True)
        layout.addWidget(self.archive_log)
        self._register_tool_dialog("archive", "归档与改名", tab, (880, 620))

    def _build_compare_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        controls = QHBoxLayout()
        choose = QPushButton("选择多个存档")
        choose.clicked.connect(self._choose_compare_saves)
        self.compare_tag = QComboBox()
        self.compare_tag.setEditable(True)
        self.compare_tag.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.compare_tag.setPlaceholderText("输入或选择国家 TAG")
        self.compare_tag.currentTextChanged.connect(self._render_comparison)
        self.compare_metric = QComboBox()
        for label, key in [
            ("国库", "treasury"),
            ("月收入", "monthly_income"),
            ("月支出", "monthly_expense"),
            ("月利息", "monthly_interest"),
            ("总债务", "debt"),
            ("ADM", "adm"),
            ("DIP", "dip"),
            ("MIL", "mil"),
            ("人力", "manpower"),
            ("陆军实际兵力", "army_strength"),
            ("累计 ADM 支出", "mana_total:adm"),
            ("累计 DIP 支出", "mana_total:dip"),
            ("累计 MIL 支出", "mana_total:mil"),
            ("ADM 理念支出", "mana:adm:buy_idea"),
            ("DIP 理念支出", "mana:dip:buy_idea"),
            ("MIL 理念支出", "mana:mil:buy_idea"),
            ("ADM 科技支出", "mana:adm:advance_tech"),
            ("DIP 科技支出", "mana:dip:advance_tech"),
            ("MIL 科技支出", "mana:mil:advance_tech"),
            ("ADM 发展支出", "mana:adm:develop_prov"),
            ("DIP 发展支出", "mana:dip:develop_prov"),
            ("MIL 发展支出", "mana:mil:develop_prov"),
            ("ADM 核心支出", "mana:adm:make_province_core"),
            ("ADM 稳定支出", "mana:adm:boost_stab"),
            ("ADM 降通胀支出", "mana:adm:reduce_inflation"),
            ("DIP 非战争目标割地支出", "mana:dip:demand_non_wargoal_prov"),
            ("DIP 转换主流文化支出", "mana:dip:set_primary_culture"),
            ("DIP 接纳文化支出", "mana:dip:add_accepted_culture"),
            ("MIL 残酷镇压支出", "mana:mil:harsh_treatment"),
            ("MIL 炮兵轰击支出", "mana:mil:artillery_barrage"),
            ("MIL 强行军支出", "mana:mil:force_march"),
            ("MIL 将领支出", "mana:mil:create_leader"),
            ("税收收入", "income:taxation"),
            ("生产收入", "income:production"),
            ("贸易收入", "income:trade"),
            ("金矿收入", "income:gold"),
            ("附庸收入", "income:vassals"),
            ("关税收入", "income:tariffs"),
            ("补贴收入", "income:subsidies"),
            ("战争赔款收入", "income:war_reparations"),
            ("陆军维护费", "expense:army_maintenance"),
            ("海军维护费", "expense:fleet_maintenance"),
            ("顾问维护费", "expense:advisor_maintenance"),
            ("要塞维护费", "expense:fort_maintenance"),
            ("利息支出分项", "expense:interest"),
            ("直属州维护费", "expense:state_maintenance"),
            ("补贴支出", "expense:subsidies"),
            ("殖民支出", "expense:colonists"),
            ("传教支出", "expense:missionaries"),
            ("肃清腐败支出", "expense:root_out_corruption"),
        ]:
            self.compare_metric.addItem(label, key)
        self.compare_metric.currentIndexChanged.connect(self._render_comparison)
        self.compare_status = QLabel("至少选择两个存档")
        controls.addWidget(choose)
        controls.addWidget(QLabel("国家"))
        controls.addWidget(self.compare_tag)
        controls.addWidget(QLabel("指标"))
        controls.addWidget(self.compare_metric)
        controls.addWidget(self.compare_status, 1)
        layout.addLayout(controls)
        self.chart = QChart()
        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        layout.addWidget(self.chart_view, 2)
        self.compare_table = QTableWidget(0, 8)
        self.compare_table.setHorizontalHeaderLabels(
            ["日期", "国库", "收入", "支出", "利息", "债务", "点数", "科技"]
        )
        self.compare_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.compare_table, 1)
        self.compare_breakdown_table = QTableWidget(0, 12)
        self.compare_breakdown_table.setHorizontalHeaderLabels(
            [
                "日期", "ADM支出", "DIP支出", "MIL支出", "税收", "生产", "贸易",
                "陆军维护", "海军维护", "顾问", "要塞", "利息",
            ]
        )
        self.compare_breakdown_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.compare_breakdown_table.horizontalHeader().setStretchLastSection(True)
        self.compare_breakdown_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.compare_breakdown_table, 1)
        self.forensic_text = QTextEdit()
        self.forensic_text.setReadOnly(True)
        self.forensic_text.setPlaceholderText("连续存档中的事件、旗标和变量变化将在此显示。")
        layout.addWidget(self.forensic_text, 1)
        self._register_tool_dialog("compare", "多存档对比", tab, (1050, 720))

    def _build_calculator_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        group = QGroupBox("3% 贷款容量估算")
        form = QFormLayout(group)
        self.calc_income = QDoubleSpinBox()
        self.calc_income.setRange(0, 100000000)
        self.calc_income.setDecimals(3)
        self.calc_principal = QDoubleSpinBox()
        self.calc_principal.setRange(0, 100000000)
        self.calc_principal.setDecimals(3)
        self.calc_principal.valueChanged.connect(self._calculator_principal_changed)
        self.calc_interest = QDoubleSpinBox()
        self.calc_interest.setRange(0.001, 100)
        self.calc_interest.setValue(3.0)
        self.calc_interest.setSuffix(" %")
        self.calc_count = QSpinBox()
        self.calc_count.setRange(0, 1000000)
        self.calc_source = QLabel("手动")
        form.addRow("预估月收入", self.calc_income)
        form.addRow("标准普通贷款本金", self.calc_principal)
        form.addRow("本金来源", self.calc_source)
        form.addRow("预估年利率", self.calc_interest)
        form.addRow("当前普通贷款数", self.calc_count)
        buttons = QHBoxLayout()
        fill = QPushButton("从当前选中国家带入")
        fill.clicked.connect(self._fill_calculator)
        calculate = QPushButton("计算")
        calculate.clicked.connect(self._calculate_loans)
        buttons.addWidget(fill)
        buttons.addWidget(calculate)
        form.addRow(buttons)
        layout.addWidget(group)
        self.calc_output = QTextEdit()
        self.calc_output.setReadOnly(True)
        layout.addWidget(self.calc_output)
        self._register_tool_dialog("calculator", "贷款计算器", tab, (640, 520))

    def _build_settings_tab(self) -> None:
        tab = QWidget()
        form = QFormLayout(tab)
        self.game_dir_edit = QLineEdit(self.config.game_dir)
        self.save_dir_edit = QLineEdit(self.config.save_dir)
        self.settings_archive_edit = QLineEdit(self.config.archive_dir)
        game_button = QPushButton("选择 EU4 安装目录")
        game_button.clicked.connect(lambda: self._choose_directory(self.game_dir_edit))
        save_button = QPushButton("选择存档目录")
        save_button.clicked.connect(lambda: self._choose_directory(self.save_dir_edit))
        archive_button = QPushButton("选择默认归档目录")
        archive_button.clicked.connect(lambda: self._choose_directory(self.settings_archive_edit))
        self.allow_unsupported_checkbox = QCheckBox(
            "允许非 491d 风险模式（尝试自动存档、归档与解析）"
        )
        self.allow_unsupported_checkbox.setChecked(
            self.config.allow_unsupported_version
        )
        self.allow_unsupported_checkbox.toggled.connect(
            self._unsupported_option_toggled
        )
        compatibility_risk = QLabel(
            "高风险：原生桥只在 491d 上完成过动态验证。其它版本启用后会尝试注入并调用"
            "原生存档路径，可能导致游戏崩溃、联机掉线、存档失败或存档损坏；新版存档结构"
            "变化也可能造成解析缺失或误判。请保留原件，并先关闭“删除源文件”。"
        )
        compatibility_risk.setWordWrap(True)
        compatibility_risk.setObjectName("riskNotice")
        save_settings = QPushButton("保存设置并重新检测版本")
        save_settings.clicked.connect(self._save_settings)
        self.log_directory = QLineEdit(str(PROJECT_ROOT / "logs"))
        self.log_directory.setReadOnly(True)
        open_logs = QPushButton("打开报错日志目录")
        open_logs.clicked.connect(self._open_log_directory)
        form.addRow("EU4 安装目录", self.game_dir_edit)
        form.addRow("", game_button)
        form.addRow("EU4 存档目录", self.save_dir_edit)
        form.addRow("", save_button)
        form.addRow("默认归档目录", self.settings_archive_edit)
        form.addRow("", archive_button)
        form.addRow("非 491d 使用", self.allow_unsupported_checkbox)
        form.addRow("", compatibility_risk)
        form.addRow("运行与崩溃日志", self.log_directory)
        form.addRow("", open_logs)
        form.addRow("", save_settings)
        self._register_tool_dialog("settings", "设置与诊断", tab, (820, 580))

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #eef2f5; color: #16232d; }
            QFrame#controlPanel { background: #0f172a; border: 0; border-radius: 7px; }
            QFrame#controlPanel QLabel { background: transparent; color: #e5eef5; }
            QLabel#appTitle { font-size: 20px; font-weight: 700; color: white; }
            QLabel#subtleText { color: #9fb3c8; }
            QLabel#gameLogo { color: white; font-size: 22px; font-weight: 700; }
            QLabel#versionChip, QLabel#bridgeChip {
                background: #172a3f; border: 1px solid #2b4a63; border-radius: 5px;
                padding: 4px 8px; color: #d9edf5;
            }
            QTabWidget::pane { border: 0; background: #eef2f5; }
            QTabBar::tab {
                background: #dce5eb; padding: 10px 20px; margin-right: 1px;
                color: #33485a; font-weight: 600;
            }
            QTabBar::tab:selected { background: #0f766e; color: white; }
            QTabBar::tab:disabled { color: #98a5ad; background: #e7ecef; }
            QPushButton, QToolButton {
                background: white; border: 1px solid #b8c6cf; border-radius: 5px;
                padding: 6px 10px; color: #213541;
            }
            QPushButton:hover, QToolButton:hover { border-color: #0f766e; color: #0f766e; }
            QPushButton#primaryButton { background: #0284c7; border-color: #0284c7; color: white; }
            QToolButton#floatingFunctionButton {
                background: rgba(15, 23, 42, 225); color: white; border: 1px solid #65a9c7;
                border-radius: 7px; font-weight: 700; padding: 6px 10px;
            }
            QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QListWidget, QTableWidget {
                background: white; border: 1px solid #c5d0d7; border-radius: 4px;
                selection-background-color: #0f766e; selection-color: white;
            }
            QHeaderView::section {
                background: #dce7ec; color: #274152; border: 0; border-right: 1px solid #c3d0d8;
                padding: 6px; font-weight: 600;
            }
            QLabel#sectionTitle { font-size: 16px; font-weight: 700; color: #183447; }
            QFrame#warningPanel { background: white; border: 1px solid #bdcbd3; border-radius: 7px; }
            QLabel#flagFrame { background: #e4ebef; border: 1px solid #b9c7cf; border-radius: 5px; }
            QLabel#countryTitle { font-size: 18px; font-weight: 700; color: #152d3b; }
            QLabel#alertBadge { background: #e8eef1; color: #405667; border-radius: 4px; padding: 4px; }
            QLabel#subsectionTitle { font-size: 14px; font-weight: 700; color: #183447; margin-top: 5px; }
            QLabel#statValue { background: white; color: #233947; padding: 3px; }
            QLabel#identityCard { background: #e8f0f4; border-radius: 5px; padding: 8px; }
            QLabel#riskNotice {
                background: #fff4d6; color: #7a4b00; border: 1px solid #e8c46b;
                border-radius: 5px; padding: 9px;
            }
            QLabel#compatibilityRiskBanner {
                background: #7f1d1d; color: #fff7ed; border: 1px solid #f59e0b;
                border-radius: 5px; padding: 7px; font-weight: 700;
            }
            QStatusBar { background: #0f172a; color: #dce9ef; }
            """
        )

    def _refresh_game_art(self) -> None:
        logo = game_logo_pixmap(self.config.game_dir, (184, 52))
        if not logo.isNull():
            self.logo_label.setPixmap(logo)
            self.logo_label.setText("")
        else:
            self.logo_label.setPixmap(QPixmap())
            self.logo_label.setText("EU4 战局助手")

    def _show_control_dialog(self) -> None:
        self.left_rail.show()
        self.left_rail_toggle.setText("隐藏功能栏 ◀")

    def _toggle_left_rail(self) -> None:
        visible = not self.left_rail.isHidden()
        self.left_rail.setVisible(not visible)
        self.left_rail_toggle.setText("☰ 功能栏" if visible else "隐藏功能栏 ◀")

    def _toggle_warning_sidebar(self) -> None:
        self.sidebar_collapsed = not self.sidebar_collapsed
        self.warning_content.setVisible(not self.sidebar_collapsed)
        if self.sidebar_collapsed:
            self.sidebar_toggle.setText("▶")
            self.warning_panel.setMinimumWidth(44)
            self.warning_panel.setMaximumWidth(44)
        else:
            self.sidebar_toggle.setText("收起 ◀")
            self.warning_panel.setMinimumWidth(390)
            self.warning_panel.setMaximumWidth(560)

    def _fit_world_map(self) -> None:
        bounds = self.map_scene.itemsBoundingRect()
        if not bounds.isEmpty():
            self.map_view.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def _fill_map_view(self) -> None:
        """Fill the map viewport initially; users can still request the full world."""
        bounds = self.map_scene.itemsBoundingRect()
        viewport = self.map_view.viewport().size()
        if bounds.isEmpty() or viewport.width() <= 0 or viewport.height() <= 0:
            return
        scale = max(viewport.width() / bounds.width(), viewport.height() / bounds.height())
        self.map_view.resetTransform()
        self.map_view.scale(scale, scale)
        self.map_view.centerOn(bounds.center())

    def _map_country_changed(self, _index: int) -> None:
        tag = self.map_country_combo.currentData()
        if not tag:
            return
        self.selected_country_tag = str(tag)
        for row in range(self.country_table.rowCount()):
            item = self.country_table.item(row, 0)
            if item is not None and item.text() == tag:
                self.country_table.blockSignals(True)
                self.country_table.selectRow(row)
                self.country_table.blockSignals(False)
                break
        self._country_selection_changed()

    def _unsupported_option_toggled(self, checked: bool) -> None:
        if checked:
            answer = QMessageBox.warning(
                self,
                "启用非 491d 高风险模式",
                "原生桥只在 491d 上完成过动态验证。启用后，程序将允许向其它版本的 "
                "eu4.exe 注入原生桥并尝试自动存档。\n\n"
                "风险包括：游戏崩溃、联机掉线、存档失败或损坏，以及新版字段变化造成的"
                "解析缺失或误判。成功与否取决于该版本的内部结构，不能保证兼容。\n\n"
                "请先备份存档并关闭“删除源文件”。确认承担风险并启用吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.allow_unsupported_checkbox.blockSignals(True)
                self.allow_unsupported_checkbox.setChecked(False)
                self.allow_unsupported_checkbox.blockSignals(False)
                checked = False
        self.config.allow_unsupported_version = checked
        self.bridge.allow_unsupported_version = checked
        self._refresh_version_status()

    def _run_worker(
        self,
        function,
        on_result,
        *args,
        on_error=None,
        on_finished=None,
        **kwargs,
    ) -> None:
        worker = FunctionWorker(function, *args, **kwargs)
        self._active_workers.add(worker)
        worker.signals.result.connect(on_result)

        def handle_error(trace: str) -> None:
            self._show_worker_error(trace)
            if on_error is not None:
                on_error(trace)

        worker.signals.error.connect(handle_error)
        def handle_finished() -> None:
            self._active_workers.discard(worker)
            if on_finished is not None:
                on_finished()

        worker.signals.finished.connect(handle_finished)
        self.thread_pool.start(worker)

    def _show_worker_error(self, trace: str) -> None:
        LOGGER.error("界面收到后台任务异常\n%s", trace)
        self.statusBar().showMessage("操作失败", 5000)
        QMessageBox.critical(self, "操作失败", trace)

    def _open_log_directory(self) -> None:
        directory = PROJECT_ROOT / "logs"
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            LOGGER.exception("无法创建日志目录 %s", directory)
            QMessageBox.critical(self, "日志目录不可用", str(exc))
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory.resolve()))):
            LOGGER.error("系统拒绝打开日志目录 %s", directory)
            QMessageBox.warning(self, "无法打开", f"请手工打开：\n{directory}")

    def _refresh_version_status(self) -> None:
        status = detect_game_version(self.config.game_dir)
        if status.supported:
            self.version_label.setText(
                f"<b style='color:#6ee7b7'>491d 已验证</b> · {status.display_version or ''}"
            )
        elif self.config.allow_unsupported_version:
            self.version_label.setText(
                f"<b style='color:#fbbf24'>非 491d 高风险模式</b> · "
                f"{status.detected_build_id or '版本未知'} · 允许尝试自动存档与解析"
            )
        else:
            self.version_label.setText(
                f"<b style='color:#f87171'>版本未支持</b> · "
                f"{status.detected_build_id or '未知'} · 请在设置中确认风险"
            )
        analysis_allowed = status.supported or self.config.allow_unsupported_version
        native_allowed = status.supported or self.config.allow_unsupported_version
        for dialog in self.analysis_dialogs:
            dialog.setEnabled(analysis_allowed)
        self.reconnect_button.setEnabled(native_allowed)
        self.schedule_combo.setEnabled(native_allowed)
        self.save_now_button.setEnabled(native_allowed and not self.save_request_busy)
        self.compatibility_risk_banner.setVisible(
            self.config.allow_unsupported_version and not status.supported
        )
        if status.supported:
            self.bridge_label.setText("原生桥：未连接")
        elif self.config.allow_unsupported_version:
            self.bridge_label.setText("原生桥：高风险强制模式，尚未连接")
        else:
            self.bridge_label.setText("原生桥：因版本不匹配已禁用")
        if not status.supported:
            if not self.config.allow_unsupported_version:
                self.auto_archive_checkbox.setChecked(False)
            self.remove_source.setChecked(False)
            if not analysis_allowed:
                self._show_tool_dialog("settings")

    def _load_database_index(self) -> None:
        rows = self.database.list_saves()
        self.save_combo.blockSignals(True)
        for row in rows:
            self.save_combo.addItem(f"{row['game_date']} — {Path(row['path']).name}", row["fingerprint"])
        self.save_combo.blockSignals(False)
        if rows:
            self.save_combo.setCurrentIndex(self.save_combo.count() - 1)
            QTimer.singleShot(0, self._select_save)

    def _install_save_watcher(self) -> None:
        self.save_watcher = QFileSystemWatcher(self)
        if Path(self.config.save_dir).is_dir():
            self.save_watcher.addPath(self.config.save_dir)
        self.save_watcher.directoryChanged.connect(self._save_directory_changed)
        QTimer.singleShot(1000, self._scan_auto_archive)

    def _save_directory_changed(self, _path: str) -> None:
        QTimer.singleShot(1000, self._scan_auto_archive)

    def _scan_auto_archive(self) -> None:
        if (
            self.save_request_busy
            or self.auto_archive_busy
            or not self.auto_archive_checkbox.isChecked()
        ):
            return
        save_dir = Path(self.config.save_dir)
        pending: list[tuple[int, Path, str]] = []
        for candidate in managed_autosaves(save_dir):
            if not candidate.is_file():
                continue
            try:
                mtime = candidate.stat().st_mtime_ns
                key = str(candidate.resolve())
            except OSError:
                continue
            if self.auto_archive_seen.get(key) != mtime:
                pending.append((mtime, candidate, key))
        if not pending:
            return
        mtime, candidate, key = min(pending, key=lambda item: item[0])
        self.auto_archive_seen[key] = mtime
        self.auto_archive_busy = True
        archive_root = self.archive_destination.text()
        campaign_name = self.campaign_edit.text()

        def run_auto_archive():
            try:
                return archive_save(
                    candidate,
                    archive_root,
                    campaign_name,
                    remove_source=True,
                ), None
            except Exception as exc:  # returned to UI for retry-safe state handling
                return None, str(exc)

        def done(payload):
            result, error = payload
            self.auto_archive_busy = False
            if error:
                self.auto_archive_seen.pop(key, None)
                self.archive_log.append(f"自动归档失败：{error}")
                QTimer.singleShot(5000, self._scan_auto_archive)
                return
            self.archive_log.append(f"自动归档完成：{result.destination}")
            self._import_verified_save(result.destination)
            QTimer.singleShot(0, self._scan_auto_archive)

        self._run_worker(run_auto_archive, done)

    def _auto_archive_imported(self, record: SaveRecord) -> None:
        self.database.import_record(record)
        self.records[record.fingerprint] = record
        if self.save_combo.findData(record.fingerprint) < 0:
            self.save_combo.addItem(f"{record.game_date} — {record.path.name}", record.fingerprint)
        self.save_combo.setCurrentIndex(self.save_combo.findData(record.fingerprint))
        self._show_record(record)

    def _import_verified_save(self, path: str | Path) -> None:
        self.import_status.setText(f"正在解析已验证存档：{Path(path).name}")
        self._run_worker(
            parse_save,
            self._auto_archive_imported,
            path,
            include_all_countries=True,
        )

    def _choose_saves(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择 EU4 存档", self.config.save_dir, "EU4 saves (*.eu4)"
        )
        if not paths:
            return
        self.import_status.setText("正在解析…")
        self._run_worker(
            lambda: [parse_save(path, include_all_countries=True) for path in paths],
            self._imports_ready,
        )

    def _quick_read_latest_save(self) -> None:
        candidates = [
            latest_save(self.archive_destination.text(), recursive=True),
            latest_save(self.config.save_dir),
        ]
        available = [path for path in candidates if path is not None]
        path = max(available, key=lambda item: item.stat().st_mtime_ns) if available else None
        if path is None:
            self.import_status.setText("存档目录和归档目标内都没有 .eu4 文件")
            self.statusBar().showMessage(self.import_status.text(), 5000)
            return
        self.import_status.setText(f"正在快速读取最新存档：{path.name}")
        self.quick_read_button.setEnabled(False)
        self._run_worker(
            lambda: [parse_save(path, include_all_countries=True)],
            self._imports_ready,
            on_finished=lambda: self.quick_read_button.setEnabled(True),
        )

    def _imports_ready(self, records: list[SaveRecord]) -> None:
        for record in records:
            self.database.import_record(record)
            self.records[record.fingerprint] = record
            index = self.save_combo.findData(record.fingerprint)
            label = f"{record.game_date} — {record.path.name}"
            if index < 0:
                self.save_combo.addItem(label, record.fingerprint)
            else:
                self.save_combo.setItemText(index, label)
        if records:
            self.save_combo.setCurrentIndex(self.save_combo.findData(records[-1].fingerprint))
            self._show_record(records[-1])
        self.import_status.setText(f"已导入 {len(records)} 份存档")

    def _select_save(self) -> None:
        fingerprint = self.save_combo.currentData()
        if not fingerprint:
            return
        if fingerprint in self.records:
            self._show_record(self.records[fingerprint])
            return
        rows = [row for row in self.database.list_saves() if row["fingerprint"] == fingerprint]
        if rows and Path(rows[0]["path"]).is_file():
            self._run_worker(
                parse_save,
                self._show_record,
                rows[0]["path"],
                include_all_countries=True,
            )

    def _show_record(self, record: SaveRecord) -> None:
        self.records[record.fingerprint] = record
        self.current_record = record
        year = record.game_date.split(".", 1)[0].strip() or "—"
        self.map_year_badge.setText(f"当前年份：{year}年")
        countries = sorted(record.countries.values(), key=lambda item: item.tag)
        self.map_country_combo.blockSignals(True)
        self.map_country_combo.clear()
        for country in countries:
            localized = country_label(country.tag)
            label = (
                f"{localized} — {country.player_name}"
                if country.player_name
                else localized
            )
            self.map_country_combo.addItem(label, country.tag)
        self.map_country_combo.blockSignals(False)
        listed_countries = [country for country in countries if country.player_name]
        sorting_enabled = self.country_table.isSortingEnabled()
        self.country_table.setSortingEnabled(False)
        self.country_table.setRowCount(len(listed_countries))
        for row, country in enumerate(listed_countries):
            alerts = economic_alerts(country)
            values = [
                (country.tag, None),
                (country_name(country.tag), None),
                (country.player_name or "", None),
                (
                    "/".join(str(value) for value in country.powers),
                    sum(country.powers),
                ),
                (
                    "/".join(str(value) for value in country.technology),
                    sum(country.technology),
                ),
                (f"{country.monthly_income:.2f}", country.monthly_income),
                (f"{country.monthly_expense:.2f}", country.monthly_expense),
                (f"{country.monthly_interest:.2f}", country.monthly_interest),
                (f"{country.treasury:.2f}", country.treasury),
                (str(len(country.loans)), len(country.loans)),
                (f"{country.total_debt:.2f}", country.total_debt),
                (f"{country.army_strength:.0f}", country.army_strength),
                ("；".join(alert.title for alert in alerts), len(alerts)),
            ]
            for column, (value, sort_value) in enumerate(values):
                item = SortableTableWidgetItem(value, sort_value)
                if alerts:
                    item.setBackground(QColor("#ffcccc"))
                self.country_table.setItem(row, column, item)
        self.country_table.setSortingEnabled(sorting_enabled)
        self.import_status.setText(
            f"{record.game_date}，版本 {record.game_version or '未知'}，"
            f"{'联机' if record.multiplayer else '单机/未知'}，玩家映射 {len(record.players)}，"
            f"现存国家 {len(countries)}"
        )
        if countries:
            preferred_tag = record.local_player_tag or countries[0].tag
            self.selected_country_tag = preferred_tag
            self._country_selection_changed()
        else:
            self.alert_text.clear()
        self._refresh_player_alert_overview()
        if self.provinces:
            self._render_map()
        else:
            self._ensure_map_index()

    def _selected_country(self) -> CountrySnapshot | None:
        if self.current_record is None:
            return None
        if self.selected_country_tag:
            selected = self.current_record.countries.get(self.selected_country_tag)
            if selected is not None:
                return selected
        return next(iter(self.current_record.countries.values()), None)

    def _country_selection_changed(self) -> None:
        if self.sender() is self.country_table:
            row = self.country_table.currentRow()
            if row >= 0 and self.country_table.item(row, 0) is not None:
                self.selected_country_tag = self.country_table.item(row, 0).text()
        country = self._selected_country()
        if country is None:
            self.alert_text.clear()
            self.sidebar_country.setText("尚未选择国家")
            self.sidebar_flag.clear()
            return
        alerts = economic_alerts(country)
        self.map_country_combo.blockSignals(True)
        combo_index = self.map_country_combo.findData(country.tag)
        if combo_index >= 0:
            self.map_country_combo.setCurrentIndex(combo_index)
        self.map_country_combo.blockSignals(False)
        self.sidebar_country.setText(
            f"{country_label(country.tag)} · {country.player_name or '非玩家国家'}"
        )
        flag = country_flag_pixmap(self.config.game_dir, country.tag)
        if flag.isNull():
            self.sidebar_flag.setPixmap(QPixmap())
            self.sidebar_flag.setText(country.tag)
        else:
            self.sidebar_flag.setText("")
            self.sidebar_flag.setPixmap(flag)
        if alerts:
            critical = sum(alert.severity == "critical" for alert in alerts)
            self.sidebar_alert_badge.setText(
                f"{len(alerts)} 条警告" + (f" · {critical} 条严重" if critical else "")
            )
            color = "#991b1b" if critical else "#9a5800"
            background = "#fee2e2" if critical else "#fff3cd"
        else:
            self.sidebar_alert_badge.setText("当前没有经济警告")
            color, background = "#166534", "#dcfce7"
        self.sidebar_alert_badge.setStyleSheet(
            f"background:{background}; color:{color}; border-radius:4px; padding:5px;"
        )
        self.stat_labels["treasury"].setText(f"国库\n{country.treasury:,.2f}")
        self.stat_labels["income"].setText(f"上月收入\n{country.monthly_income:,.2f}")
        self.stat_labels["expense"].setText(f"上月支出\n{country.monthly_expense:,.2f}")
        self.stat_labels["manpower"].setText(
            f"陆军人力\n{country.manpower_people:,.0f}/{country.max_manpower_people:,.0f} 人"
        )
        self.stat_labels["development"].setText(f"发展度\n{country.development:,.1f}")
        self.stat_labels["stability"].setText(
            f"稳定/通胀\n{country.stability:.0f} / {country.inflation:.2f}%"
        )
        self.stat_labels["technology"].setText(
            "科技\n" + "/".join(str(value) for value in country.technology)
        )
        self.stat_labels["powers"].setText(
            "ADM/DIP/MIL\n" + "/".join(str(value) for value in country.powers)
        )
        completed_ideas = sum(max(0, value) for value in country.ideas.values())
        self.stat_labels["ideas"].setText(
            f"理念\n{completed_ideas} 项 / {len(country.ideas)} 组"
        )
        self.stat_labels["interest"].setText(
            f"上月利息\n{country.monthly_interest:,.2f}"
        )
        self.stat_labels["army"].setText(
            f"陆军数量\n{country.army_strength:,.0f} 人（{len(country.armies)} 支军队）"
        )
        self.stat_labels["navy"].setText(f"海军数量\n{country.ship_count:,} 艘")
        self.stat_labels["sailors"].setText(
            f"水手数量\n{country.sailors:,.0f}/{country.max_sailors:,.0f} 人"
        )
        self.identity_label.setText(
            f"宗教：{country.religion or '存档未记录'}\n"
            f"主流文化：{country.primary_culture or '存档未记录'}\n"
            f"普通贷款：{len(country.ordinary_loans)} 笔　总债务：{country.total_debt:,.2f}　"
            f"陆军：{country.army_strength:,.0f} 人　海军：{country.ship_count:,} 艘　"
            f"水手：{country.sailors:,.0f}/{country.max_sailors:,.0f} 人"
        )

        lines: list[str] = []
        for alert in alerts:
            severity = "严重" if alert.severity == "critical" else "警告"
            lines.append(f"【{severity} · {alert.title}】\n{alert.message}")
        if not alerts:
            lines.append("当前未触发经济警告。")
        lines.append(
            f"\n监测值：实际利息 {country.monthly_interest:.2f} / 上月收入 "
            f"{country.monthly_income:.2f}；国库 {country.treasury:.2f}。"
        )
        if country.loans:
            lines.append(
                "\n贷款明细："
                + "；".join(
                    f"{loan.amount:.2f}@{loan.annual_interest:.2f}%"
                    f"（{'阶层' if loan.estate_loan else '普通'}）"
                    for loan in country.loans
                )
            )
        self.alert_text.setPlainText("\n".join(lines))
        self._render_country_charts(country)
        self._render_army_overview(country)

    def _render_country_charts(self, country: CountrySnapshot) -> None:
        income_names = {
            "taxation": "税收", "production": "生产", "trade": "贸易", "gold": "金矿",
            "tariffs": "关税", "vassals": "附庸", "harbor_fees": "港口费",
            "subsidies": "补贴", "war_reparations": "战争赔款", "interest": "利息",
            "gifts": "礼物", "events": "事件", "spoils_of_war": "战利品",
            "treasure_fleet": "宝船", "siphoning_income": "攫取收入",
            "condottieri": "雇佣军出租", "knowledge_sharing": "知识共享",
            "blockading_foreign_ports": "封锁港口", "looting_foreign_cities": "劫掠",
            "other": "其它",
        }
        expense_names = {
            "advisor_maintenance": "顾问维护", "interest": "利息",
            "state_maintenance": "直属州维护", "army_maintenance": "陆军维护",
            "fleet_maintenance": "海军维护", "fort_maintenance": "要塞维护",
            "subsidies": "补贴", "war_reparations": "战争赔款",
            "colonists": "殖民者", "missionaries": "传教士",
            "root_out_corruption": "肃清腐败", "repaid_loans": "偿还贷款",
            "events": "事件", "buildings": "建筑", "other": "其它",
        }
        mana_names = {
            "buy_idea": "理念", "advance_tech": "科技", "boost_stab": "提升稳定度",
            "buy_general": "招募陆军将领", "buy_admiral": "招募海军将领",
            "buy_conq": "招募征服者", "buy_explorer": "招募探险家",
            "develop_prov": "发展省份", "force_march": "强行军", "assault": "强攻",
            "seize_colony": "夺取殖民地", "burn_colony": "焚毁殖民地",
            "attack_natives": "攻击原住民", "scorch_earth": "焦土",
            "demand_non_wargoal_prov": "非战争目标割地", "reduce_inflation": "降低通胀",
            "move_capital": "迁都", "make_province_core": "制造核心",
            "replace_rival": "更换宿敌", "change_gov": "更换政体",
            "change_culture": "转变省份文化", "harsh_treatment": "残酷镇压",
            "reduce_we": "降低厌战", "boost_faction": "扶持派系",
            "raise_war_taxes": "征收战争税", "buy_native_advancement": "原住民改革",
            "increse_tariffs": "提高关税", "promote_merc": "提高重商主义",
            "decrease_tariffs": "降低关税", "move_trade_port": "迁移贸易本埠",
            "create_trade_post": "建立贸易站", "siege_sorties": "守军突击",
            "buy_religious_reform": "宗教改革", "set_primary_culture": "转换主流文化",
            "add_accepted_culture": "接纳文化", "remove_accepted_culture": "移除接纳文化",
            "strengthen_government": "加强政府", "boost_militarization": "提高军事化",
            "artillery_barrage": "炮兵轰击", "establish_siberian_frontier": "西伯利亚拓荒",
            "government_interaction": "政府互动", "naval_barrage": "海军轰击",
            "add_tribal_land": "添加部落领地", "create_leader": "招募将领",
            "enforce_culture": "强制文化", "effect": "事件或脚本效果",
            "minority_expulsion": "驱逐少数族群", "other": "其它",
        }
        self.detail_country_title.setText(
            f"{country_label(country.tag)} · "
            f"{country.player_name or '非玩家国家'} — 国家详细分析"
        )
        self.detail_country_summary.setText(
            f"国库 {country.treasury:,.2f}　上月收入 {country.monthly_income:,.2f}　"
            f"上月支出 {country.monthly_expense:,.2f}　利息 {country.monthly_interest:,.2f}　"
            f"陆军 {country.army_strength:,.0f} 人（{len(country.armies)} 支）　"
            f"人力 {country.manpower_people:,.0f}/{country.max_manpower_people:,.0f} 人　"
            f"海军 {country.ship_count:,} 艘　水手 {country.sailors:,.0f}/{country.max_sailors:,.0f} 人　"
            f"宗教 {country.religion or '—'}　文化 {country.primary_culture or '—'}"
        )
        if country.ideas:
            self.detail_ideas.setText(
                "　".join(
                    f"{name}：{value}/7"
                    for name, value in sorted(country.ideas.items())
                )
            )
        else:
            self.detail_ideas.setText("存档未记录已启用理念组。")

        self._render_breakdown_pie(
            self.detail_income_chart,
            country.income_breakdown,
            income_names,
            f"上月收入分布 · 合计 {country.monthly_income:,.2f}",
        )
        self._render_breakdown_pie(
            self.detail_expense_chart,
            country.expense_breakdown,
            expense_names,
            f"上月支出分布 · 合计 {country.monthly_expense:,.2f}",
        )

        self.detail_mana_chart.removeAllSeries()
        for axis in list(self.detail_mana_chart.axes()):
            self.detail_mana_chart.removeAxis(axis)
        categories = ["理念", "科技", "发展", "其它"]
        series = QBarSeries()
        colors = {"adm": QColor("#52c99a"), "dip": QColor("#5c8ff1"), "mil": QColor("#6f819f")}
        for power in ("adm", "dip", "mil"):
            values = country.mana_spending.get(power, {})
            bar = QBarSet(power.upper())
            bar.setColor(colors[power])
            grouped = [
                values.get("buy_idea", 0),
                values.get("advance_tech", 0),
                values.get("develop_prov", 0),
                sum(
                    value
                    for key, value in values.items()
                    if key not in {"buy_idea", "advance_tech", "develop_prov"}
                ),
            ]
            bar.append([float(value) for value in grouped])
            series.append(bar)
            table = self.detail_mana_tables[power]
            ordered = [item for item in sorted(values.items(), key=lambda item: item[1], reverse=True) if item[1] > 0]
            for key, _value in ordered:
                if key.startswith("unknown_"):
                    mana_names[key] = f"未知用途（存档索引 {key.removeprefix('unknown_')}）"
            total = sum(value for _key, value in ordered)
            table.setRowCount(len(ordered) + 1)
            for row, (key, value) in enumerate(ordered):
                table.setItem(row, 0, QTableWidgetItem(mana_names.get(key, key)))
                table.setItem(row, 1, QTableWidgetItem(f"{value:,}"))
                table.setItem(row, 2, QTableWidgetItem(f"{value / total * 100:.2f}%" if total else "0%"))
            table.setItem(len(ordered), 0, QTableWidgetItem("合计"))
            table.setItem(len(ordered), 1, QTableWidgetItem(f"{total:,}"))
            table.setItem(len(ordered), 2, QTableWidgetItem("100%" if total else "0%"))
            self._render_breakdown_pie(
                self.detail_mana_pies[power],
                {key: float(value) for key, value in ordered},
                mana_names,
                f"{power.upper()} 累计用途 · {total:,}",
            )
        self.detail_mana_chart.addSeries(series)
        category_axis = QBarCategoryAxis()
        category_axis.append(categories)
        self.detail_mana_chart.addAxis(category_axis, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(category_axis)
        value_axis = QValueAxis()
        value_axis.setLabelFormat("%.0f")
        self.detail_mana_chart.addAxis(value_axis, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(value_axis)
        self.detail_mana_chart.setTitle("ADM / DIP / MIL 累计点数用途（存档可验证部分）")
        self.detail_mana_chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)

    @staticmethod
    def _render_breakdown_pie(
        chart: QChart,
        values: dict[str, float],
        names: dict[str, str],
        title: str,
    ) -> None:
        chart.removeAllSeries()
        for axis in list(chart.axes()):
            chart.removeAxis(axis)
        series = QPieSeries()
        positive = [(key, value) for key, value in values.items() if value > 0]
        total = sum(value for _key, value in positive)
        for key, value in sorted(positive, key=lambda item: item[1], reverse=True):
            label = names.get(key, key)
            piece = series.append(label, value)
            piece.setLabel(f"{label} {value:,.1f}")
            piece.setLabelVisible(value >= max(total * 0.035, 0.01))
        if not positive:
            series.append("无可用分项", 1)
        chart.addSeries(series)
        chart.setTitle(title)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)

    def _render_army_overview(self, country: CountrySnapshot) -> None:
        self.army_dialog_title.setText(
            f"{country_label(country.tag)} 军队 · {len(country.armies)} 支 · "
            f"实际兵力 {country.army_strength:,.0f}"
        )
        self.army_overview_table.setRowCount(len(country.armies))
        for row, army in enumerate(country.armies):
            unit_types = "，".join(f"{name}:{count}" for name, count in army.unit_types.items())
            values = [
                country_label(country.tag),
                army.name,
                str(army.location or "—"),
                str(army.regiment_count),
                f"{army.strength:,.0f}",
                unit_types or "—",
            ]
            for column, value in enumerate(values):
                self.army_overview_table.setItem(row, column, QTableWidgetItem(value))

    def _refresh_player_alert_overview(self) -> None:
        players = [] if self.current_record is None else [
            country
            for country in self.current_record.countries.values()
            if country.player_name
        ]
        warned = []
        for country in players:
            alerts = economic_alerts(country)
            if alerts:
                warned.append((country, alerts))
        warned.sort(
            key=lambda item: (
                not any(alert.severity == "critical" for alert in item[1]),
                -len(item[1]),
                item[0].tag,
            )
        )
        self.alert_overview_summary.setText(
            f"玩家国家警告：{len(warned)} / {len(players)} 个玩家国家触发告警"
        )
        if "alerts" in self.left_tool_buttons:
            self.left_tool_buttons["alerts"].setText(
                f"玩家警告总览（{len(warned)}）"
            )
        self.alert_overview_table.setRowCount(len(warned))
        for row, (country, alerts) in enumerate(warned):
            critical = any(alert.severity == "critical" for alert in alerts)
            severity = "严重" if critical else "警告"
            values = [
                severity,
                country.tag,
                country.player_name or "—",
                str(len(alerts)),
                "；".join(alert.title for alert in alerts),
                "\n".join(alert.message for alert in alerts),
            ]
            color = QColor("#fecaca" if critical else "#fef3c7")
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setBackground(color)
                self.alert_overview_table.setItem(row, column, item)
        self.alert_overview_table.resizeRowsToContents()

    def _alert_overview_activated(self, row: int, _column: int) -> None:
        tag_item = self.alert_overview_table.item(row, 1)
        if tag_item is None:
            return
        tag = tag_item.text()
        self.selected_country_tag = tag
        combo_index = self.map_country_combo.findData(tag)
        if combo_index >= 0:
            self.map_country_combo.setCurrentIndex(combo_index)
        else:
            self._country_selection_changed()
        if self.sidebar_collapsed:
            self._toggle_warning_sidebar()

    def _ensure_map_index(self) -> None:
        if self.map_index_busy:
            return
        self.map_index_busy = True
        self.map_status.setText("正在生成省份中心索引，首次运行可能需要数十秒…")
        cache = PROJECT_ROOT / "data" / "province_index.json"
        self._run_worker(
            load_or_build_province_index,
            self._map_index_ready,
            self.config.game_dir,
            cache,
            on_finished=lambda: setattr(self, "map_index_busy", False),
        )

    def _map_index_ready(self, provinces: dict[int, ProvinceInfo]) -> None:
        self.provinces = provinces
        self.map_status.setText(f"已加载 {len(provinces)} 个省份")
        self._render_map()

    def _map_clicked(self, scene_position: QPointF) -> None:
        if self.current_record is None:
            return
        province_id = province_id_at(
            self.config.game_dir,
            scene_position.x(),
            scene_position.y(),
            self.map_cache_dir,
        )
        if province_id is None:
            self._remove_army_popup()
            return
        owner = self.current_record.province_owners.get(province_id)
        controller = self.current_record.province_controllers.get(province_id)
        if owner and owner in self.current_record.countries:
            combo_index = self.map_country_combo.findData(owner)
            if combo_index >= 0:
                self.map_country_combo.setCurrentIndex(combo_index)
            else:
                self.selected_country_tag = owner
                self._country_selection_changed()
        self._show_province_armies(province_id, scene_position, owner, controller)

    def _remove_army_popup(self) -> None:
        widget = self.army_popup_widget
        if widget is None:
            return
        self.army_popup_widget = None
        widget.hide()
        widget.deleteLater()

    def _show_province_armies(
        self,
        province_id: int,
        scene_position: QPointF,
        owner: str | None,
        controller: str | None,
    ) -> None:
        self._remove_army_popup()
        if self.current_record is None:
            return
        armies = [
            (country.tag, army)
            for country in self.current_record.countries.values()
            for army in country.armies
            if army.location == province_id
        ]
        if not armies:
            return
        info = self.provinces.get(province_id)
        frame = QFrame(self.map_view.viewport())
        frame.setObjectName("armyPopup")
        frame.setStyleSheet(
            "QFrame#armyPopup{background:#fffdf6;border:2px solid #6c512b;border-radius:7px;}"
            "QLabel{background:transparent;color:#172632;}"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        header = QHBoxLayout()
        title = QLabel(
            f"<b>{info.name if info else '省份'} ({province_id})</b><br>"
            f"原主 {country_label(owner)} · "
            f"控制方 {country_label(controller or owner)}"
        )
        close_button = QToolButton()
        close_button.setText("×")
        close_button.setFixedSize(26, 26)
        header.addWidget(title, 1)
        header.addWidget(close_button)
        layout.addLayout(header)
        total = sum(army.strength for _tag, army in armies)
        layout.addWidget(QLabel(f"当地共 {len(armies)} 支军队 · 实际兵力 {total:,.0f}"))
        for tag, army in armies:
            unit_types = "，".join(
                f"{name}:{count}" for name, count in army.unit_types.items()
            )
            row = QLabel(
                f"<b>{country_label(tag)} · {army.name}</b><br>"
                f"{army.regiment_count} 团 / {army.strength:,.0f} 兵力"
                + (f"<br>{unit_types}" if unit_types else "")
            )
            row.setWordWrap(True)
            layout.addWidget(row)
        frame.setMaximumWidth(360)
        frame.adjustSize()
        viewport_position = self.map_view.mapFromScene(scene_position)
        viewport = self.map_view.viewport().rect()
        x = min(max(viewport_position.x() + 14, 0), max(0, viewport.width() - frame.width()))
        y = min(max(viewport_position.y() + 14, 0), max(0, viewport.height() - frame.height()))
        frame.move(x, y)
        frame.show()
        frame.raise_()
        self.army_popup_widget = frame
        close_button.clicked.connect(self._remove_army_popup)

    def _render_map(self) -> None:
        if self.current_record is None or not self.provinces:
            return
        record = self.current_record
        self.map_render_generation += 1
        generation = self.map_render_generation
        self.map_status.setText(
            f"正在渲染 {record.game_date} 政治地图（{len(record.province_owners)} 个有主省份）…"
        )

        def ready(image) -> None:
            if generation != self.map_render_generation or self.current_record is None:
                return
            if self.current_record.fingerprint != record.fingerprint:
                return
            self._political_map_ready(image)

        self._run_worker(
            build_political_map,
            ready,
            self.config.game_dir,
            dict(record.province_owners),
            dict(record.province_controllers),
            cache_dir=self.map_cache_dir,
            on_error=lambda _trace: self.map_status.setText("政治地图渲染失败"),
        )

    def _political_map_ready(self, image) -> None:
        pixmap = QPixmap.fromImage(pil_to_qimage(image))
        self._remove_army_popup()
        self.map_scene.clear()
        self.map_scene.addPixmap(pixmap)
        colors = [QColor("#ff1744"), QColor("#00e676"), QColor("#2979ff"), QColor("#ffea00")]
        for country_index, country in enumerate(self.current_record.countries.values()):
            color = colors[country_index % len(colors)]
            for army in country.armies:
                info = self.provinces.get(army.location or -1)
                if info is None or info.center_x is None or info.center_y is None:
                    continue
                radius = max(4.0, min(18.0, math.sqrt(max(army.strength, 1)) / 50.0))
                ellipse = self.map_scene.addEllipse(
                    info.center_x - radius,
                    info.center_y - radius,
                    radius * 2,
                    radius * 2,
                    QPen(Qt.GlobalColor.black, 1),
                    color,
                )
                ellipse.setToolTip(
                    f"{country_label(country.tag)} {army.name}\n"
                    f"{info.name} ({info.province_id})\n"
                    f"{army.regiment_count} 团 / {army.strength:.0f} 兵力"
                )
                ellipse.setZValue(10)
        self._fill_map_view()
        QTimer.singleShot(0, self._fill_map_view)
        self.map_status.setText(
            f"政治地图已生成 · {len(self.current_record.province_owners)} 个有主省份 · "
            "单击省份查看国家/驻军，左键拖动，滚轮缩放"
        )
        self.statusBar().showMessage(self.map_status.text(), 7000)

    def _choose_archive_sources(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择待归档存档", self.config.save_dir, "EU4 saves (*.eu4)"
        )
        for path in paths:
            self.archive_sources.addItem(path)

    def _choose_archive_destination(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择归档目录", self.archive_destination.text())
        if path:
            self.archive_destination.setText(path)

    def _preview_archive(self) -> None:
        paths = [self.archive_sources.item(i).text() for i in range(self.archive_sources.count())]
        if not paths:
            return
        def build_preview():
            lines = []
            for path in paths:
                record = parse_save(path)
                destination = preview_archive_path(
                    path,
                    self.archive_destination.text(),
                    self.campaign_edit.text(),
                    record.game_date,
                    record.local_player_tag,
                )
                lines.append(f"{path}\n  → {destination}")
            return "\n".join(lines)
        self._run_worker(build_preview, self.archive_log.setPlainText)

    def _execute_archive(self) -> None:
        paths = [self.archive_sources.item(i).text() for i in range(self.archive_sources.count())]
        if not paths:
            return
        destination = self.archive_destination.text()
        campaign = self.campaign_edit.text()
        remove = self.remove_source.isChecked()

        def done(items):
            lines: list[str] = []
            failed: list[str] = []
            for item in items:
                if item.result is not None:
                    lines.append(f"已归档：{item.result.destination}")
                else:
                    lines.append(f"归档失败：{item.source}\n  {item.error}")
                    failed.append(item.source)
            self.archive_log.setPlainText("\n".join(lines))
            self.archive_sources.clear()
            self.archive_sources.addItems(failed)

        self._run_worker(
            archive_many,
            done,
            paths,
            destination,
            campaign,
            remove_source=remove,
        )

    def _undo_archive(self) -> None:
        root = self.archive_destination.text()

        def done(result):
            self.archive_log.append(
                f"已恢复：{result.restored_source}\n已移除归档：{result.removed_archive}"
            )

        self._run_worker(undo_last_archive, done, root)

    def _choose_compare_saves(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择连续存档", self.config.save_dir, "EU4 saves (*.eu4)"
        )
        if len(paths) < 2:
            return
        self.compare_status.setText("正在解析对比存档…")
        def load_comparison():
            records = [parse_save(path, include_all_countries=True) for path in paths]
            validate_same_game_version(records)
            return records

        self._run_worker(load_comparison, self._comparison_ready)

    def _comparison_ready(self, records: list[SaveRecord]) -> None:
        self.compare_records = records
        tags = sorted({tag for record in records for tag in record.countries})
        self.compare_tag.blockSignals(True)
        self.compare_tag.clear()
        self.compare_tag.addItems(tags)
        if tags:
            self.compare_tag.setCurrentIndex(0)
        self.compare_tag.blockSignals(False)
        self.compare_status.setText(
            f"已载入 {len(records)} 份存档；版本 {validate_same_game_version(records)}"
        )
        self._render_comparison()

    def _render_comparison(self) -> None:
        if not self.compare_records or not self.compare_tag.currentText():
            return
        country_tag = self.compare_tag.currentText().strip().upper()
        points = comparison_series(self.compare_records, country_tag)
        metric = self.compare_metric.currentData() or "treasury"
        self.chart.removeAllSeries()
        for axis in list(self.chart.axes()):
            self.chart.removeAxis(axis)
        series = QLineSeries()
        series.setName(self.compare_metric.currentText())
        for index, point in enumerate(points):
            series.append(QPointF(index, comparison_metric_value(point, metric)))
        self.chart.addSeries(series)
        x_axis = QValueAxis()
        x_axis.setRange(0, max(len(points) - 1, 1))
        x_axis.setLabelFormat("%d")
        y_axis = QValueAxis()
        values = [comparison_metric_value(point, metric) for point in points] or [0.0]
        low, high = min(values), max(values)
        padding = max((high - low) * 0.1, 1.0)
        y_axis.setRange(low - padding, high + padding)
        self.chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)
        self.chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(x_axis)
        series.attachAxis(y_axis)
        self.chart.setTitle(f"{country_tag} — {self.compare_metric.currentText()}")
        self.compare_table.setRowCount(len(points))
        for row, point in enumerate(points):
            values = [
                point.game_date,
                f"{point.treasury:.2f}",
                f"{point.monthly_income:.2f}",
                f"{point.monthly_expense:.2f}",
                f"{point.monthly_interest:.2f}",
                f"{point.debt:.2f}",
                f"{point.adm}/{point.dip}/{point.mil}",
                f"{point.adm_tech}/{point.dip_tech}/{point.mil_tech}",
            ]
            for column, value in enumerate(values):
                self.compare_table.setItem(row, column, QTableWidgetItem(value))
        self.compare_breakdown_table.setRowCount(len(points))
        for row, point in enumerate(points):
            breakdown_values = [
                point.game_date,
                f"{comparison_metric_value(point, 'mana_total:adm'):,.0f}",
                f"{comparison_metric_value(point, 'mana_total:dip'):,.0f}",
                f"{comparison_metric_value(point, 'mana_total:mil'):,.0f}",
                f"{comparison_metric_value(point, 'income:taxation'):,.2f}",
                f"{comparison_metric_value(point, 'income:production'):,.2f}",
                f"{comparison_metric_value(point, 'income:trade'):,.2f}",
                f"{comparison_metric_value(point, 'expense:army_maintenance'):,.2f}",
                f"{comparison_metric_value(point, 'expense:fleet_maintenance'):,.2f}",
                f"{comparison_metric_value(point, 'expense:advisor_maintenance'):,.2f}",
                f"{comparison_metric_value(point, 'expense:fort_maintenance'):,.2f}",
                f"{comparison_metric_value(point, 'expense:interest'):,.2f}",
            ]
            for column, value in enumerate(breakdown_values):
                self.compare_breakdown_table.setItem(row, column, QTableWidgetItem(value))
        gaps = consecutive_date_gaps(points)
        missing = [
            record.path.name
            for record in self.compare_records
            if country_tag not in record.countries
        ]
        notes = list(gaps)
        if missing:
            notes.append(f"{len(missing)} 份存档中不存在 {country_tag}")
        suffix = f"；{'；'.join(notes)}" if notes else ""
        self.compare_status.setText(f"{len(points)} 个数据点{suffix}")
        findings = forensic_differences(self.compare_records, country_tag)
        if findings:
            self.forensic_text.setPlainText(
                "\n".join(
                    f"[{item.classification}] {item.from_date} → {item.to_date} "
                    f"{item.field}: {item.details}"
                    for item in findings
                )
            )
        else:
            self.forensic_text.setPlainText("未发现可持久化的事件、旗标或变量变化；这不等于不存在其它变化。")

    def _fill_calculator(self) -> None:
        country = self._selected_country()
        if country is None:
            QMessageBox.information(self, "贷款计算器", "请先导入并选择国家。")
            return
        self.calc_income.setValue(country.monthly_income)
        self.calc_count.setValue(len(country.ordinary_loans))
        try:
            principal, source = select_standard_loan_principal(country)
        except LoanCalculationError as exc:
            self.filling_calculator = True
            self.calc_principal.setValue(0)
            self.filling_calculator = False
            self.calc_source.setText("manual（请手动输入）")
            self.calc_output.setPlainText(str(exc))
        else:
            self.filling_calculator = True
            self.calc_principal.setValue(principal)
            self.filling_calculator = False
            self.calc_source.setText(source)

    def _calculator_principal_changed(self, _value: float) -> None:
        if not self.filling_calculator:
            self.calc_source.setText("manual")

    def _calculate_loans(self) -> None:
        try:
            result = calculate_loan_capacity(
                self.calc_income.value(),
                self.calc_principal.value(),
                self.calc_interest.value(),
                self.calc_count.value(),
                self.calc_source.text(),
            )
        except LoanCalculationError as exc:
            QMessageBox.warning(self, "无法计算", str(exc))
            return
        self.calc_output.setPlainText(
            "【以下均为估算值】\n"
            f"标准单笔贷款本金：{result.loan_principal:.2f}（{result.principal_source}）\n"
            f"单笔月利息：{result.monthly_interest_per_loan:.3f}\n"
            f"估算最大贷款数：{result.estimated_max_loans}\n"
            f"估算剩余贷款数：{result.estimated_remaining_loans}\n"
            f"估算总贷款额度：{result.estimated_total_capacity:.2f}\n"
            f"当前估算月利息：{result.estimated_current_interest:.2f}\n"
            f"估算容量使用率：{result.capacity_usage:.2%}"
        )

    def _choose_directory(self, target: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择目录", target.text())
        if path:
            target.setText(path)

    def _save_settings(self) -> None:
        self.config.game_dir = self.game_dir_edit.text()
        self.config.save_dir = self.save_dir_edit.text()
        self.config.archive_dir = self.settings_archive_edit.text()
        self.config.autosave_mode = self.schedule_combo.currentData()
        self.config.campaign_name = self.campaign_edit.text()
        self.config.allow_unsupported_version = self.allow_unsupported_checkbox.isChecked()
        save_config(self.config)
        self.archive_destination.setText(self.config.archive_dir)
        self.bridge.close()
        self.bridge = BridgeClient(
            self.config.game_dir,
            allow_unsupported_version=self.config.allow_unsupported_version,
        )
        old_paths = self.save_watcher.directories()
        if old_paths:
            self.save_watcher.removePaths(old_paths)
        if Path(self.config.save_dir).is_dir():
            self.save_watcher.addPath(self.config.save_dir)
        QTimer.singleShot(0, self._scan_auto_archive)
        self._refresh_game_art()
        self._refresh_version_status()
        self.statusBar().showMessage("设置已保存", 3000)

    def _poll_bridge(self) -> None:
        if self.bridge_poll_busy:
            return
        self.bridge_poll_busy = True
        self._run_worker(
            self.bridge.status,
            self._bridge_status_ready,
            on_finished=lambda: setattr(self, "bridge_poll_busy", False),
        )

    def _bridge_status_ready(self, status) -> None:
        if not status.connected:
            self.bridge_label.setText(f"原生桥：不可用 — {status.message}")
            return
        self.last_bridge_game_date = status.game_date
        self.bridge_label.setText(
            f"原生桥：已连接；日期 {status.game_date or '未知'}；"
            f"载入={status.game_loaded} 就绪={status.synchronized} 存档中={status.saving}"
        )
        self._evaluate_schedule(status)

    def _connect_bridge(self) -> None:
        self.bridge_label.setText("原生桥：正在检测并加载…")

        def done(status):
            self.bridge_label.setText(
                "原生桥：已连接" if status.connected else f"原生桥：不可用 — {status.message}"
            )

        self._run_worker(self.bridge.ensure_injected, done)

    def _evaluate_schedule(self, status) -> None:
        if (
            self.save_request_busy
            or not status.game_loaded
            or not status.synchronized
            or status.saving
        ):
            return
        now = time.monotonic()
        self.scheduler.set_mode(self.schedule_combo.currentData(), now=now)
        request = self.scheduler.due(status.game_date, now=now)
        if request is not None:
            self._request_native_save(request)

    def _request_native_save(
        self, schedule_request: ScheduledSaveRequest | None = None
    ) -> None:
        if self.save_request_busy:
            self.statusBar().showMessage("已有存档请求正在验证，请稍候。", 5000)
            return
        self.save_request_busy = True
        self.save_now_button.setEnabled(False)
        self.statusBar().showMessage("正在请求并验证客机存档…")
        request_label = schedule_request.mode if schedule_request is not None else "manual"
        started_at = datetime.now().strftime("%H:%M:%S")
        self.archive_log.append(f"[{started_at}] 开始存档请求：{request_label}")

        def done(response):
            now = time.monotonic()
            success = bool(response.get("ok") and response.get("file_created"))
            if schedule_request is not None:
                self.scheduler.complete(schedule_request, success=success, now=now)
            elif success:
                self.scheduler.note_manual_success(self.last_bridge_game_date, now=now)
            message = str(response.get("message") or "已提交存档请求")
            self.statusBar().showMessage(message, 5000)
            self.archive_log.append(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"存档验证{'成功' if success else '失败'}：{message}"
            )
            if (
                success
                and response.get("save_path")
                and not self.auto_archive_checkbox.isChecked()
            ):
                self._import_verified_save(str(response["save_path"]))

        def failed(trace: str) -> None:
            if schedule_request is not None:
                self.scheduler.complete(
                    schedule_request, success=False, now=time.monotonic()
                )
            summary = trace.strip().splitlines()[-1] if trace.strip() else "未知错误"
            self.archive_log.append(
                f"[{datetime.now().strftime('%H:%M:%S')}] 存档请求异常：{summary}"
            )

        def finished() -> None:
            self.save_request_busy = False
            self.save_now_button.setEnabled(True)
            QTimer.singleShot(0, self._scan_auto_archive)

        self._run_worker(
            lambda: self.bridge.request_save_and_wait(self.config.save_dir),
            done,
            on_error=failed,
            on_finished=finished,
        )
