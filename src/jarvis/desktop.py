"""Responsive, local-first Qt desktop for JARVIS.

Blocking provider, database, tool and transcription calls use tracked runnables.
Qt speech and widgets stay on the application thread. Nothing records or contacts
a provider merely because the window opens.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import Settings, save_settings
from .secrets import SecretStore

STYLE = """
QWidget { background: #0c111b; color: #dde8f5; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow { background: #0c111b; }
QFrame#Sidebar { background: #101824; border-right: 1px solid #223145; }
QFrame#Panel { background: #121c2a; border: 1px solid #26364b; border-radius: 12px; }
QLabel#Brand { color: #78ecf8; font-size: 24px; font-weight: 700; letter-spacing: 4px; }
QLabel#Title { font-size: 25px; font-weight: 600; }
QLabel#Muted { color: #93a6bc; }
QLabel#Status { color: #72d9e6; padding: 8px; background: #101824; border-radius: 7px; }
QPushButton { background: #19283a; border: 1px solid #31465e; padding: 9px 15px;
 border-radius: 7px; font-weight: 600; }
QPushButton:hover { background: #243b50; border-color: #54d4e4; }
QPushButton:pressed { background: #304b63; }
QPushButton:disabled { color: #66778a; border-color: #243348; background: #121b28; }
QPushButton#Primary { color: #08131c; background: #66deeb; border-color: #66deeb; }
QPushButton#Danger { color: #ffa6ab; border-color: #85424b; background: #301e2a; }
QPushButton#Nav { text-align: left; padding: 12px 14px; border: 0; background: transparent; }
QPushButton#Nav:checked { color: #79eaf6; background: #1a3244; border-left: 3px solid #68deeb; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
 background: #0e1724; border: 1px solid #2a3b52; border-radius: 6px; padding: 7px;
 selection-background-color: #28596e; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: #60d8e7; }
QTextEdit#Conversation { border: none; background: #0c111b; padding: 12px; }
QTableWidget, QListWidget { background: #101925; border: 1px solid #26364b;
 border-radius: 7px; gridline-color: #26364b; alternate-background-color: #152132; }
QHeaderView::section { background: #1b2a3d; border: 0; padding: 9px; color: #aebfd3; }
QTableWidget::item:selected, QListWidget::item:selected { background: #23485c; }
QCheckBox { spacing: 8px; }
QScrollArea { border: 0; }
QScrollBar:vertical { background: #101824; width: 10px; }
QScrollBar::handle:vertical { background: #354a63; min-height: 30px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QMenu { background: #152132; border: 1px solid #354a63; }
QMenu::item { padding: 8px 22px; }
QMenu::item:selected { background: #23485c; }
"""


class _JobSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()


class _Job(QRunnable):
    def __init__(self, action: Callable[[], Any], owner: QObject | None = None):
        super().__init__()
        self.action = action
        # The pool destroys its runnable on a worker. Keep the GUI-affine
        # signal object owned by the window until deferred GUI-thread cleanup.
        self.signals = _JobSignals(owner)
        self.cancel = threading.Event()

    def run(self) -> None:
        try:
            result = self.action()
        except Exception as exc:
            # Backend and voice errors provide safe user-facing summaries.
            self.signals.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.signals.succeeded.emit(result)
        finally:
            self.signals.finished.emit()


class _Composer(QPlainTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event: Any) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)


def _button(text: str, callback: Callable[..., Any], *, kind: str = "") -> QPushButton:
    button = QPushButton(text)
    if kind:
        button.setObjectName(kind)
    button.clicked.connect(callback)
    return button


def _label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.verticalHeader().hide()
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#101c2b"))
    painter.setPen(QColor("#66deeb"))
    painter.drawEllipse(4, 4, 56, 56)
    painter.setBrush(QColor("#66deeb"))
    painter.drawEllipse(24, 24, 16, 16)
    painter.end()
    return QIcon(pixmap)


def _ensure_desktop_font() -> None:
    """Give Qt's offscreen Windows platform the same real font as the desktop.

    The offscreen plugin can have an empty system font database on Windows.
    Registering installed font files fixes rendering without substituting text.
    """
    app = QApplication.instance()
    if app is None or app.property("jarvisFontsReady"):
        return
    if sys.platform == "win32" and "Segoe UI" not in QFontDatabase.families():
        for filename in ("segoeui.ttf", "segoeuib.ttf", "segoeuil.ttf", "seguisb.ttf"):
            path = Path("C:/Windows/Fonts") / filename
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Segoe UI", 10))
    app.setProperty("jarvisFontsReady", True)


class MainWindow(QMainWindow):
    """Desktop controller. Service/engine/store must implement CONTRACTS.md."""

    def __init__(self, service: Any, settings: Settings, store: Any, engine: Any):
        super().__init__()
        _ensure_desktop_font()
        self.service, self.settings, self.store, self.engine = service, settings, store, engine
        self.session_id: str | None = None
        self._pool = QThreadPool.globalInstance()
        self._jobs: dict[str, _Job] = {}
        self._closing = False
        self._close_deadline = 0.0
        self._compact = False
        self._normal_geometry = None
        self._voice: Any = None
        self._speech: Any = None
        self._record_release = threading.Event()
        self._record_cancel = threading.Event()
        self._record_stage = "idle"
        self._shown_record_stage = "idle"
        self._chat_cancel: threading.Event | None = None
        self._memories: list[dict[str, Any]] = []
        self._tasks: list[dict[str, Any]] = []
        self._live_task_results: dict[str, dict[str, Any]] = {}
        self._last_task_id: str | None = None
        self._selected_memory: Any = None
        self._stopped = False
        self._routines = []
        self._workflow_runs = []
        self._projects = []
        self._routine_steps = []
        self._routine_dirty = False
        self._editing_routine_id = None
        self._last_reply = {}
        self._last_latency = None
        self._awareness_data = {}
        self._context_snapshot = {}
        self._applications: list[dict[str, Any]] = []
        self._selected_application_id: str | None = None
        self._pending_application_id: str | None = None
        self._action_runs: list[dict[str, Any]] = []
        self._action_health: dict[str, Any] = {}
        from .awareness import DesktopContextProvider, SystemMetricsProvider
        from .workflows import WorkflowEngine

        self.workflows = getattr(service, "workflows", None) or WorkflowEngine(
            store, engine, settings
        )
        self._metrics_provider = SystemMetricsProvider()
        self._context_provider = DesktopContextProvider()
        from .health import build_identity

        self.build_info = build_identity()
        self.health_result = {"backend": "Health check pending", "speech_model": "Not checked"}
        self.setWindowTitle("JARVIS · Command Center")
        self.setWindowIcon(_icon())
        self.resize(1180, 800)
        self.setMinimumSize(760, 560)
        from .ui_components import STYLE as PHASE3_STYLE

        self.setStyleSheet(PHASE3_STYLE)
        self._build()
        self._build_tray()
        self._build_overlay()
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setInterval(100)
        self._shutdown_timer.timeout.connect(self._poll_shutdown)
        self._audio_status_timer = QTimer(self)
        self._audio_status_timer.setInterval(100)
        self._audio_status_timer.timeout.connect(self._update_audio_status)
        self._append_message(
            "JARVIS",
            "Your workspace is ready. Choose a provider in Settings, then type a message. "
            "Desktop actions appear in Mission Control with their actual results. "
            "Enable hands-free listening in Settings, or hold the microphone button to talk.",
        )
        from .voice_controller import VoiceController

        self.voice_controller = VoiceController(self)
        self._presence_timer = QTimer(self)
        self._presence_timer.setInterval(160)
        self._presence_timer.timeout.connect(self._update_presence)
        self._presence_timer.start()
        self._system_timer = QTimer(self)
        self._system_timer.setInterval(5000)
        self._system_timer.timeout.connect(self.refresh_system)
        self._system_timer.start()
        self._action_activity_timer = QTimer(self)
        self._action_activity_timer.setInterval(1000)
        self._action_activity_timer.timeout.connect(self._refresh_active_actions)
        self._action_activity_timer.start()
        shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        shortcut.activated.connect(self.command_palette)
        self._palette_shortcut = shortcut
        self._update_build_health()
        # Reads are asynchronous; initial paint does not wait for the database.
        QTimer.singleShot(0, self.refresh)

    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(190)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(16, 24, 16, 18)
        side.addWidget(_label("JARVIS", "Brand"))
        side.addWidget(_label("AMBIENT INTELLIGENCE", "Muted"))
        side.addSpacing(27)
        self.nav: list[QPushButton] = []
        self.page_titles = (
            "Assistant",
            "Mission Control",
            "Memory Explorer",
            "Timeline",
            "Settings",
            "Workflows",
            "System",
            "Diagnostics",
            "Business",
            "Application Library",
        )
        for index, title in enumerate(self.page_titles):
            button = QPushButton(title)
            button.setObjectName("Nav")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self._navigate(i))
            self.nav.append(button)
            side.addWidget(button)
        side.addStretch()
        self.privacy_label = _label("", "Muted", True)
        side.addWidget(self.privacy_label)
        side.addSpacing(12)
        side.addWidget(_button("Commands · Ctrl K", self.command_palette))
        side.addWidget(_button("Compact assistant", self.toggle_compact))
        side.addWidget(_button("Emergency stop", self.emergency_stop, kind="Danger"))
        self.sidebar_scroll = QScrollArea()
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setFixedWidth(205)
        self.sidebar_scroll.setWidget(self.sidebar)
        outer.addWidget(self.sidebar_scroll)
        main = QVBoxLayout()
        self._main_layout = main
        main.setContentsMargins(28, 24, 28, 18)
        main.setSpacing(16)
        self.title_label = _label("Assistant", "Title")
        self.status_label = _label("Ready · microphone off", "Status", True)
        header = QHBoxLayout()
        header.addWidget(self.title_label)
        header.addStretch()
        self.expand_button = _button("Expand", self.toggle_compact)
        self.expand_button.hide()
        header.addWidget(self.expand_button)
        main.addLayout(header)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._assistant_page())
        self.pages.addWidget(self._activity_page())
        self.pages.addWidget(self._memory_page())
        self.pages.addWidget(self._audit_page())
        self.pages.addWidget(self._settings_page())
        self.pages.addWidget(self._workflows_page())
        self.pages.addWidget(self._system_page())
        self.pages.addWidget(self._diagnostics_page())
        self.pages.addWidget(self._business_page())
        self.pages.addWidget(self._applications_page())
        main.addWidget(self.pages, 1)
        main.addWidget(self.status_label)
        outer.addLayout(main, 1)
        self._navigate(0)
        self._update_privacy_label()

    def _assistant_page(self) -> QWidget:
        from .ui_components import CoreWidget

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        self.assistant_heading = _label("YOUR COMMAND SPACE", "Muted")
        tools.addWidget(self.assistant_heading)
        tools.addStretch()
        self.new_conversation_button = _button("New conversation", self.new_conversation)
        tools.addWidget(self.new_conversation_button)
        layout.addLayout(tools)
        self.presence_panel = QFrame()
        self.presence_panel.setObjectName("Panel")
        presence = QHBoxLayout(self.presence_panel)
        self.core = CoreWidget()
        self.core.set_reduce_motion(self.settings.reduce_motion)
        presence.addWidget(self.core)
        self.presence_details = QWidget()
        self.presence_details.setObjectName("PresenceDetail")
        detail = QVBoxLayout(self.presence_details)
        detail.addWidget(_label("Intelligence, under your control", "Title", True))
        self.presence_caption = _label("Ready for a request · microphone off", "Muted", True)
        detail.addWidget(self.presence_caption)
        self.context_ribbon = _label("CONTEXT · No project selected", "Status", True)
        detail.addWidget(self.context_ribbon)
        self.provider_ribbon = _label("", "Muted", True)
        detail.addWidget(self.provider_ribbon)
        quick = QHBoxLayout()
        quick.addWidget(_button("Choose project", lambda: self._navigate(5)))
        quick.addWidget(_button("Review approvals", lambda: self._navigate(1)))
        detail.addLayout(quick)
        presence.addWidget(self.presence_details, 1)
        layout.addWidget(self.presence_panel)
        self.conversation = QTextEdit()
        self.conversation.setObjectName("Conversation")
        self.conversation.setReadOnly(True)
        self.conversation.setAcceptRichText(False)
        layout.addWidget(self.conversation, 1)
        self.compact_response = _label("Ready for your request", "Muted", True)
        self.compact_response.hide()
        layout.addWidget(self.compact_response, 1)
        panel = QFrame()
        panel.setObjectName("Panel")
        composer_layout = QVBoxLayout(panel)
        self.composer = _Composer()
        self.composer.setObjectName("MessageInput")
        self.composer.setPlaceholderText("Ask JARVIS…  Enter to send · Shift+Enter for a new line")
        self.composer.setFixedHeight(96)
        self.composer.submitted.connect(self.send_message)
        composer_layout.addWidget(self.composer)
        buttons = QHBoxLayout()
        self.mic_button = QPushButton("Hold to talk")
        self.mic_button.setObjectName("Microphone")
        self.mic_button.pressed.connect(self.start_recording)
        self.mic_button.released.connect(self.stop_recording)
        buttons.addWidget(self.mic_button)
        self.speak_check = QCheckBox("Speak replies")
        self.speak_check.setChecked(bool(self.settings.speech_enabled))
        self.speak_check.toggled.connect(self._speech_toggled)
        buttons.addWidget(self.speak_check)
        self.listen_button = _button("Resume listening", lambda: self.voice_controller.toggle())
        buttons.addWidget(self.listen_button)
        buttons.addWidget(_button("Mute", lambda: self.voice_controller.mute()))
        buttons.addStretch()
        composer_layout.addLayout(buttons)
        response_controls = QHBoxLayout()
        self.voice_status = _label("Voice: Idle · microphone off", "Muted", True)
        response_controls.addWidget(self.voice_status, 1)
        self.interrupt_button = _button("Interrupt", self.interrupt)
        self.interrupt_button.setObjectName("Interrupt")
        response_controls.addWidget(self.interrupt_button)
        self.send_button = _button("Send", self.send_message, kind="Primary")
        self.send_button.setObjectName("Primary")
        response_controls.addWidget(self.send_button)
        composer_layout.addLayout(response_controls)
        layout.addWidget(panel)
        return page

    def _activity_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(
            _label(
                "Review exact arguments before approval. Tool output is the execution record.",
                "Muted",
                True,
            )
        )
        form = QFrame()
        form.setObjectName("Panel")
        action_layout = QVBoxLayout(form)
        action_row = QHBoxLayout()
        self.tool_choice = QComboBox()
        self.tool_choice.addItem("List a folder", "list_directory")
        self.tool_choice.addItem("Read a text file", "read_file")
        self.tool_choice.addItem("Open a folder", "open_folder")
        self.tool_choice.addItem("Open an application", "open_app")
        self.tool_choice.addItem("Create a folder", "create_directory")
        self.tool_choice.addItem("Focus an application", "focus_app")
        self.tool_choice.addItem("Open a website", "open_website")
        self.tool_choice.addItem("Search the web", "search_web")
        self.tool_choice.addItem("List installed applications", "list_applications")
        self.tool_choice.addItem("Measure system status", "get_system_status")
        self.tool_choice.currentIndexChanged.connect(self._tool_changed)
        action_row.addWidget(self.tool_choice)
        self.tool_path = QLineEdit()
        self.tool_path.setPlaceholderText("Full path inside a permitted folder")
        action_row.addWidget(self.tool_path, 1)
        self.tool_app = QComboBox()
        self.tool_app.setEditable(True)
        self.tool_app.addItems(["notepad", "calculator", "vscode", "chrome", "edge", "firefox"])
        self.tool_app.hide()
        action_row.addWidget(self.tool_app, 1)
        self.action_button = _button("Submit action", self.submit_action, kind="Primary")
        action_row.addWidget(self.action_button)
        action_layout.addLayout(action_row)
        action_layout.addWidget(
            _label(
                "File output stays local. Allowed folders and approval mode are set in Settings.",
                "Muted",
                True,
            )
        )
        layout.addWidget(form)
        self.mission_summary = _label("No active local operation", "Status", True)
        layout.addWidget(self.mission_summary)
        self.task_table = _table(["Task", "Action", "State"])
        self.task_table.itemSelectionChanged.connect(self._select_task)
        self.task_table.setColumnWidth(0, 140)
        self.task_table.setColumnWidth(1, 180)
        self.task_detail = QPlainTextEdit()
        self.task_detail.setReadOnly(True)
        self.task_detail.setPlaceholderText("Select a task to inspect its arguments and result.")
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.task_table)
        split.addWidget(self.task_detail)
        tabs = QTabWidget()
        tabs.addTab(split, "Tasks & approvals")
        receipts = QWidget()
        receipt_layout = QVBoxLayout(receipts)
        receipt_layout.addWidget(
            _label(
                "Action plans show exact targets and Windows receipts. Browser content is not inspected.",
                "Muted",
                True,
            )
        )
        self.action_run_table = _table(["Request", "State", "Progress"])
        self.action_run_table.itemSelectionChanged.connect(self._select_action_run)
        self.action_run_detail = QPlainTextEdit()
        self.action_run_detail.setReadOnly(True)
        receipt_split = QSplitter(Qt.Orientation.Vertical)
        receipt_split.addWidget(self.action_run_table)
        receipt_split.addWidget(self.action_run_detail)
        receipt_layout.addWidget(receipt_split, 1)
        self.cancel_action_run_button = _button(
            "Cancel selected plan", self.cancel_action_run, kind="Danger"
        )
        self.cancel_action_run_button.setEnabled(False)
        receipt_layout.addWidget(self.cancel_action_run_button)
        tabs.addTab(receipts, "Action plan receipts")
        layout.addWidget(tabs, 1)
        row = QHBoxLayout()
        self.approve_button = _button(
            "Approve selected", lambda: self.task_operation("approve"), kind="Primary"
        )
        self.reject_button = _button("Reject", lambda: self.task_operation("reject"))
        self.cancel_task_button = _button("Cancel task", lambda: self.task_operation("cancel"))
        self.resume_button = _button("Resume after stop", self.resume)
        for button in (self.approve_button, self.reject_button, self.cancel_task_button):
            button.setEnabled(False)
            row.addWidget(button)
        row.addStretch()
        row.addWidget(self.resume_button)
        row.addWidget(_button("Refresh", self.refresh))
        layout.addLayout(row)
        return page

    def _memory_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(
            _label("Save only what you want JARVIS to remember across restarts.", "Muted", True)
        )
        search = QHBoxLayout()
        self.memory_search = QLineEdit()
        self.memory_search.setPlaceholderText("Search saved memory")
        self.memory_search.returnPressed.connect(self.refresh)
        search.addWidget(self.memory_search, 1)
        search.addWidget(_button("Search", self.refresh))
        search.addWidget(_button("Export data", self.export_data))
        layout.addLayout(search)
        self.memory_table = _table(["Category", "Key", "Source"])
        self.memory_table.itemSelectionChanged.connect(self._select_memory)
        self.memory_table.setColumnWidth(0, 160)
        self.memory_table.setColumnWidth(1, 300)
        layout.addWidget(self.memory_table, 1)
        form = QFormLayout()
        self.memory_category = QComboBox()
        self.memory_category.setEditable(True)
        self.memory_category.addItems(["preferences", "project", "business", "task", "knowledge"])
        self.memory_category.addItems(["summary", "application", "routine", "instructions"])
        self.memory_key = QLineEdit()
        self.memory_content = QPlainTextEdit()
        self.memory_content.setMaximumHeight(130)
        form.addRow("Category", self.memory_category)
        form.addRow("Key", self.memory_key)
        form.addRow("Content", self.memory_content)
        layout.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(_button("New memory", self.new_memory))
        row.addStretch()
        self.delete_memory_button = _button("Delete selected", self.delete_memory, kind="Danger")
        self.delete_memory_button.setEnabled(False)
        row.addWidget(self.delete_memory_button)
        row.addWidget(_button("Save memory", self.save_memory, kind="Primary"))
        layout.addLayout(row)
        retention = QHBoxLayout()
        self.memory_retention = QSpinBox()
        self.memory_retention.setRange(1, 3650)
        self.memory_retention.setValue(365)
        self.memory_retention.setSuffix(" days")
        retention.addWidget(_label("Delete older saved memories", "Muted"))
        retention.addWidget(self.memory_retention)
        retention.addWidget(_button("Review deletion", self.prune_saved_memories))
        layout.addLayout(retention)
        return page

    def prune_saved_memories(self):
        days = self.memory_retention.value()
        answer = QMessageBox.question(
            self,
            "Delete old saved memories",
            f"Delete all explicit saved memories last updated more than {days} days ago? This cannot be undone. Export your data first if needed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:

            def deleted(count):
                self._status(f"Deleted {count} old saved memories")
                self.refresh()

            self._run("memory-write", lambda: self.store.prune_memories(days), deleted)

    def _audit_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(_label("Local record of requests, permissions and execution", "Muted"))
        row.addStretch()
        row.addWidget(_button("Refresh", self.refresh))
        layout.addLayout(row)
        self.audit_view = QPlainTextEdit()
        self.audit_view.setReadOnly(True)
        layout.addWidget(self.audit_view, 1)
        row = QHBoxLayout()
        row.addWidget(_label("Saved conversations", "Muted"))
        row.addStretch()
        self.delete_session_button = _button(
            "Delete selected conversation", self.delete_session, kind="Danger"
        )
        row.addWidget(self.delete_session_button)
        layout.addLayout(row)
        self.session_list = QListWidget()
        self.session_list.setMaximumHeight(145)
        self.session_list.itemDoubleClicked.connect(self.load_session)
        layout.addWidget(self.session_list)
        layout.addWidget(
            _label("Double-click a saved conversation to view it. Saving is opt-in.", "Muted")
        )
        return page

    def _settings_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 15, 0)
        layout.addWidget(
            _label("Local first, with explicit choices for privacy and permissions.", "Muted", True)
        )
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.provider_choice = QComboBox()
        self.provider_choice.addItems(["ollama", "openai", "gemini"])
        self.provider_choice.setCurrentText(self.settings.provider)
        self.model_edit = QLineEdit(self.settings.model)
        self.ollama_url_edit = QLineEdit(self.settings.ollama_url)
        self.openai_key_edit = QLineEdit()
        self.gemini_key_edit = QLineEdit()
        self.clear_openai_key = QCheckBox("Remove stored OpenAI key")
        self.clear_gemini_key = QCheckBox("Remove stored Gemini key")
        for field in (self.openai_key_edit, self.gemini_key_edit):
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setPlaceholderText("Leave blank to keep the stored key")
        self.cloud_check = QCheckBox("Allow chat messages to the selected cloud provider")
        self.cloud_check.setChecked(self.settings.cloud_allowed)
        self.history_check = QCheckBox("Save conversations locally")
        self.history_check.setChecked(self.settings.save_history)
        self.mode_choice = QComboBox()
        self.mode_choice.addItems(["manual", "balanced", "advanced"])
        self.mode_choice.setCurrentText(self.settings.mode)
        self.roots_edit = QPlainTextEdit(
            "\n".join(str(path) for path in self.settings.allowed_roots)
        )
        self.roots_edit.setPlaceholderText("One full folder path per line")
        self.roots_edit.setMaximumHeight(90)
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(1, 180)
        self.timeout_spin.setSuffix(" seconds")
        self.timeout_spin.setValue(self.settings.request_timeout)
        self.tokens_spin = QSpinBox()
        self.tokens_spin.setRange(16, 8192)
        self.tokens_spin.setValue(self.settings.max_output_tokens)
        self.requests_spin = QSpinBox()
        self.requests_spin.setRange(1, 1000)
        self.requests_spin.setValue(self.settings.max_requests_per_session)
        self.microphone_choice = QComboBox()
        self.microphone_choice.addItem("System default", None)
        if self.settings.microphone_device is not None:
            self.microphone_choice.addItem(
                f"Device {self.settings.microphone_device}", self.settings.microphone_device
            )
            self.microphone_choice.setCurrentIndex(1)
        self.voice_choice = QComboBox()
        self.voice_choice.addItem("System default")
        if self.settings.speech_voice:
            self.voice_choice.addItem(self.settings.speech_voice)
            self.voice_choice.setCurrentIndex(1)
        self.speaker_choice = QComboBox()
        self.speaker_choice.addItem("Windows default output", None)
        if self.settings.speaker_device:
            self.speaker_choice.addItem(
                "Saved output device (refresh to inspect)", self.settings.speaker_device
            )
            self.speaker_choice.setCurrentIndex(1)
        self.speech_model_edit = QLineEdit(self.settings.speech_model)
        self.speech_device_choice = QComboBox()
        self.speech_device_choice.addItems(["cpu", "cuda"])
        self.speech_device_choice.setCurrentText(self.settings.speech_device)
        self.compute_choice = QComboBox()
        self.compute_choice.addItems(["int8", "float16", "float32", "int8_float16"])
        self.compute_choice.setCurrentText(self.settings.speech_compute_type)
        self.wake_check = QCheckBox("Allow hands-free microphone listening on this PC")
        self.wake_check.setChecked(self.settings.wake_enabled)
        self.wake_phrase_edit = QLineEdit(self.settings.wake_phrase)
        self.sensitivity_spin = QDoubleSpinBox()
        self.sensitivity_spin.setDecimals(3)
        self.sensitivity_spin.setRange(0.001, 0.2)
        self.sensitivity_spin.setSingleStep(0.005)
        self.sensitivity_spin.setValue(self.settings.input_sensitivity)
        self.vad_spin = QSpinBox()
        self.vad_spin.setRange(0, 3)
        self.vad_spin.setValue(self.settings.vad_aggressiveness)
        self.endpoint_spin = QDoubleSpinBox()
        self.endpoint_spin.setRange(0.3, 3)
        self.endpoint_spin.setValue(self.settings.speech_end_silence)
        self.followup_spin = QDoubleSpinBox()
        self.followup_spin.setRange(5, 120)
        self.followup_spin.setValue(self.settings.conversation_timeout)
        self.activation_spin = QDoubleSpinBox()
        self.activation_spin.setRange(2, 60)
        self.activation_spin.setValue(self.settings.speech_start_timeout)
        self.utterance_spin = QDoubleSpinBox()
        self.utterance_spin.setRange(3, 30)
        self.utterance_spin.setValue(self.settings.maximum_utterance_seconds)
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(-1, 1)
        self.rate_spin.setSingleStep(0.1)
        self.rate_spin.setValue(self.settings.speech_rate)
        self.greeting_choice = QComboBox()
        self.greeting_choice.addItems(["brief", "friendly", "professional", "silent"])
        self.greeting_choice.setCurrentText(self.settings.greeting_style)
        self.timezone_edit = QLineEdit(self.settings.timezone)
        self.pronunciation_edit = QPlainTextEdit(
            json.dumps(self.settings.pronunciation_replacements, ensure_ascii=False)
        )
        self.pronunciation_edit.setMaximumHeight(70)
        self.interruption_check = QCheckBox(
            "Headset only: recognize stop commands during speech (experimental)"
        )
        self.interruption_check.setChecked(self.settings.voice_interruption)
        self.proactive_check = QCheckBox("Speak about completed/failed local tasks")
        self.proactive_check.setChecked(self.settings.proactive_enabled)
        self.quiet_start_spin = QSpinBox()
        self.quiet_start_spin.setRange(0, 23)
        self.quiet_start_spin.setValue(self.settings.quiet_start)
        self.quiet_end_spin = QSpinBox()
        self.quiet_end_spin.setRange(0, 23)
        self.quiet_end_spin.setValue(self.settings.quiet_end)
        self.proactive_interval_spin = QDoubleSpinBox()
        self.proactive_interval_spin.setRange(30, 86400)
        self.proactive_interval_spin.setValue(self.settings.proactive_interval_seconds)
        self.startup_check = QCheckBox("Start after my Windows login")
        self.startup_check.setChecked(self.settings.start_with_windows)
        self.tray_check = QCheckBox("Open minimized to the system tray")
        self.tray_check.setChecked(self.settings.minimize_to_tray)
        self.reduce_motion_check = QCheckBox("Reduce animations")
        self.reduce_motion_check.setChecked(self.settings.reduce_motion)
        self.on_top_check = QCheckBox("Keep compact assistant above other windows")
        self.on_top_check.setChecked(self.settings.compact_always_on_top)
        self.desktop_context_check = QCheckBox(
            "Read foreground app and window title locally · no screenshots or uploads"
        )
        self.desktop_context_check.setChecked(self.settings.desktop_context_enabled)
        self.speaking_style_choice = QComboBox()
        self.speaking_style_choice.addItems(
            ["concise", "professional", "conversational", "technical"]
        )
        self.speaking_style_choice.setCurrentText(self.settings.speaking_style)
        self.desktop_actions_check = QCheckBox("Allow explicit application and window actions")
        self.desktop_actions_check.setChecked(
            getattr(self.settings, "desktop_actions_enabled", True)
        )
        self.browser_actions_check = QCheckBox(
            "Allow explicitly requested website and search launches"
        )
        self.browser_actions_check.setChecked(getattr(self.settings, "browser_enabled", True))
        self.browser_choice = QComboBox()
        self.browser_choice.addItems(["default", "chrome", "edge", "firefox"])
        self.browser_choice.setCurrentText(getattr(self.settings, "default_browser", "default"))
        self.search_engine_choice = QComboBox()
        self.search_engine_choice.addItems(["google", "bing", "duckduckgo", "youtube"])
        self.search_engine_choice.setCurrentText(
            getattr(self.settings, "default_search_engine", "google")
        )
        self.browser_window_check = QCheckBox("Request a new window for named browsers")
        self.browser_window_check.setChecked(getattr(self.settings, "browser_new_window", False))
        self.model_actions_check = QCheckBox(
            "Allow the selected AI to propose scoped actions · always review before execution"
        )
        self.model_actions_check.setChecked(getattr(self.settings, "model_action_planning", False))
        self.website_aliases_edit = QPlainTextEdit(
            json.dumps(getattr(self.settings, "preferred_websites", {}), ensure_ascii=False)
        )
        self.website_aliases_edit.setMaximumHeight(85)
        fields = [
            ("AI provider", self.provider_choice),
            ("Model", self.model_edit),
            ("Ollama address", self.ollama_url_edit),
            ("OpenAI key", self.openai_key_edit),
            ("", self.clear_openai_key),
            ("Gemini key", self.gemini_key_edit),
            ("", self.clear_gemini_key),
            ("Cloud permission", self.cloud_check),
            ("Conversation privacy", self.history_check),
            ("Action mode", self.mode_choice),
            ("Permitted folders", self.roots_edit),
            ("Request timeout", self.timeout_spin),
            ("Maximum output tokens", self.tokens_spin),
            ("Requests per session", self.requests_spin),
            ("Microphone", self.microphone_choice),
            ("Speaking voice", self.voice_choice),
            ("Speaker", self.speaker_choice),
            ("Local speech model", self.speech_model_edit),
            ("Speech processing", self.speech_device_choice),
            ("Speech precision", self.compute_choice),
            ("Hands-free permission", self.wake_check),
            ("Wake phrase", self.wake_phrase_edit),
            ("Minimum input level (RMS)", self.sensitivity_spin),
            ("Noise rejection (0–3)", self.vad_spin),
            ("Speech ending pause (seconds)", self.endpoint_spin),
            ("Follow-up window (seconds)", self.followup_spin),
            ("Activation wait (seconds)", self.activation_spin),
            ("Maximum utterance (seconds)", self.utterance_spin),
            ("Speaking speed (−1 to 1)", self.rate_spin),
            ("Greeting style", self.greeting_choice),
            ("Timezone", self.timezone_edit),
            ("Pronunciations (JSON dictionary)", self.pronunciation_edit),
            ("Voice interruption", self.interruption_check),
            ("Proactive speech", self.proactive_check),
            ("Quiet hours start (0–23)", self.quiet_start_spin),
            ("Quiet hours end (0–23)", self.quiet_end_spin),
            ("Notification interval (seconds)", self.proactive_interval_spin),
            ("Windows startup", self.startup_check),
            ("Background display", self.tray_check),
            ("Motion", self.reduce_motion_check),
            ("Compact window", self.on_top_check),
            ("Desktop context permission", self.desktop_context_check),
            ("Response style", self.speaking_style_choice),
            ("Desktop action permission", self.desktop_actions_check),
            ("Browser action permission", self.browser_actions_check),
            ("Preferred browser", self.browser_choice),
            ("Search engine", self.search_engine_choice),
            ("Browser window", self.browser_window_check),
            ("AI action proposals", self.model_actions_check),
            ("Website aliases (JSON dictionary)", self.website_aliases_edit),
        ]
        for title, field in fields:
            form.addRow(title, field)
        layout.addLayout(form)
        layout.addWidget(
            _label(
                "Manual asks before state changes. Balanced permits predefined app/folder launches. "
                "Advanced currently uses the same conservative policy. Folder creation always asks. "
                "Speech models must be installed using the explicit setup command; the microphone button "
                "never downloads one. CUDA requires compatible speech libraries.",
                "Muted",
                True,
            )
        )
        layout.addWidget(
            _label(
                "Hands-free checks speech locally using offline Whisper; speech segments are discarded after recognition. "
                "Saving this permission enables listening now and after restart. Pause or Mute closes the microphone. "
                "During replies the microphone is gated to avoid speaker echo. Interrupt always stops playback. "
                "Voice stop commands during playback require a headset and explicit opt-in; no acoustic echo canceller is installed.",
                "Muted",
                True,
            )
        )
        row = QHBoxLayout()
        self.audio_refresh_button = _button("Refresh audio devices", self.refresh_audio_devices)
        row.addWidget(self.audio_refresh_button)
        row.addStretch()
        self.save_settings_button = _button(
            "Save settings", self.save_configuration, kind="Primary"
        )
        row.addWidget(self.save_settings_button)
        layout.addLayout(row)
        output_row = QHBoxLayout()
        output_row.addWidget(_label("Speech uses the Windows default output device", "Muted"))
        output_row.addStretch()
        output_row.addWidget(_button("Windows sound settings", self.open_sound_settings))
        layout.addLayout(output_row)
        layout.addWidget(_label(f"Local data: {self.settings.data_dir}", "Muted", True))
        self.build_health_label = _label("", "Muted", True)
        self.build_health_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.build_health_label)
        layout.addWidget(_button("Run startup health check", self.run_health_check))
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def _navigate(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.title_label.setText(self.page_titles[index])
        for i, button in enumerate(self.nav):
            button.setChecked(i == index)
        if index == 6:
            self.refresh_system()
        elif index == 9:
            self.refresh_applications()
        elif index == 7:
            self.refresh_action_health()

    def _workflows_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_label("FOCUS & ROUTINES", "Muted"))
        layout.addWidget(
            _label(
                "Inspect every step. Enable a routine, then run it explicitly. Each step keeps its normal permissions.",
                "Muted",
                True,
            )
        )
        row = QHBoxLayout()
        self.project_choice = QComboBox()
        self.project_choice.addItem("Select a project", None)
        row.addWidget(self.project_choice, 1)
        row.addWidget(_button("Use context", self.select_project_context))
        row.addWidget(_button("Development routine", self.create_development_routine))
        layout.addLayout(row)
        project = QHBoxLayout()
        self.project_name = QLineEdit()
        self.project_name.setPlaceholderText("Project name")
        self.project_path = QLineEdit()
        self.project_path.setPlaceholderText("Full folder path inside your permitted roots")
        project.addWidget(self.project_name)
        project.addWidget(self.project_path, 2)
        project.addWidget(_button("Register", self.register_project))
        project.addWidget(_button("Remove", self.delete_project))
        layout.addLayout(project)
        self.routine_choice = QComboBox()
        self.routine_choice.addItem("New routine", None)
        self.routine_choice.currentIndexChanged.connect(self._select_routine)
        layout.addWidget(self.routine_choice)
        row = QHBoxLayout()
        self.routine_name = QLineEdit()
        self.routine_name.setPlaceholderText("Routine name")
        self.routine_name.textEdited.connect(self._mark_routine_dirty)
        row.addWidget(self.routine_name, 1)
        self.routine_enabled = QCheckBox("Enabled")
        self.routine_enabled.clicked.connect(self.enable_routine)
        row.addWidget(self.routine_enabled)
        layout.addLayout(row)
        step = QHBoxLayout()
        self.routine_tool = QComboBox()
        for title, name in (
            ("Open application", "open_app"),
            ("Open folder", "open_folder"),
            ("List folder", "list_directory"),
            ("Read text file", "read_file"),
            ("Create folder · approval", "create_directory"),
        ):
            self.routine_tool.addItem(title, name)
        self.routine_argument = QLineEdit()
        self.routine_argument.setPlaceholderText(
            "chrome / vscode / notepad / calculator, or full permitted path"
        )
        step.addWidget(self.routine_tool)
        step.addWidget(self.routine_argument, 1)
        step.addWidget(_button("Add step", self.add_routine_step))
        layout.addLayout(step)
        self.routine_preview = QListWidget()
        self.routine_preview.setMinimumHeight(100)
        self.routine_preview.setMaximumHeight(160)
        layout.addWidget(self.routine_preview)
        row = QHBoxLayout()
        row.addWidget(_button("Remove step", self.remove_routine_step))
        row.addWidget(_button("Save routine", self.save_routine))
        row.addWidget(_button("Delete routine", self.delete_routine))
        row.addStretch()
        self.run_routine_button = _button("Run selected", self.run_routine, kind="Primary")
        row.addWidget(self.run_routine_button)
        layout.addLayout(row)
        layout.addWidget(_label("WORKFLOW REPLAY · actual step evidence", "Muted"))
        self.workflow_table = _table(["Routine", "State", "Steps"])
        self.workflow_table.itemSelectionChanged.connect(self._select_workflow_run)
        self.workflow_table.setMinimumHeight(130)
        self.workflow_detail = QPlainTextEdit()
        self.workflow_detail.setReadOnly(True)
        self.workflow_detail.setMinimumHeight(130)
        layout.addWidget(self.workflow_table)
        layout.addWidget(self.workflow_detail)
        row = QHBoxLayout()
        row.addWidget(_button("Continue after approval", self.resume_workflow))
        row.addWidget(_button("Cancel selected run", self.cancel_workflow))
        row.addStretch()
        row.addWidget(_button("Review pending approval", lambda: self._navigate(1)))
        layout.addLayout(row)
        scroll.setWidget(page)
        return scroll

    def _system_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_label("MEASURED AWARENESS", "Muted"))
        layout.addWidget(
            _label(
                "Resource samples run off the interface thread. Desktop titles are read only with the separate permission in Settings.",
                "Muted",
                True,
            )
        )
        self.system_summary = _label(
            "Open this page to sample CPU, RAM and available GPU information.", "Status", True
        )
        layout.addWidget(self.system_summary)
        self.system_details = QPlainTextEdit()
        self.system_details.setReadOnly(True)
        layout.addWidget(self.system_details, 1)
        row = QHBoxLayout()
        row.addWidget(_button("Refresh measurements", lambda: self.refresh_system(force=True)))
        row.addWidget(_button("Check AI connection", self.run_health_check))
        layout.addLayout(row)
        return page

    def _diagnostics_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_label("BUILD & STARTUP HEALTH", "Muted"))
        layout.addWidget(self.build_health_label)
        layout.addWidget(_button("Run startup health check", self.run_health_check))
        self.ai_diagnostics = _label("No provider request measured in this window.", "Status", True)
        layout.addWidget(self.ai_diagnostics)
        self.action_diagnostics = QPlainTextEdit()
        self.action_diagnostics.setReadOnly(True)
        self.action_diagnostics.setPlaceholderText(
            "Open Diagnostics or run the startup health check to inspect Windows, application and browser status."
        )
        layout.addWidget(self.action_diagnostics, 1)
        layout.addWidget(
            _label(
                "Voice playback animation reflects the Windows speech engine state. This engine does not expose synthesized PCM amplitude; the display does not claim an audio waveform.",
                "Muted",
                True,
            )
        )
        layout.addStretch()
        return page

    def _applications_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_label("LOCAL APPLICATION LIBRARY", "Muted"))
        layout.addWidget(
            _label(
                "Discovery reads installed application metadata locally. New arbitrary applications stay disabled until you review their exact target. Aliases and favorites never authorize execution.",
                "Muted",
                True,
            )
        )
        row = QHBoxLayout()
        self.application_search = QLineEdit()
        self.application_search.setPlaceholderText("Search names and aliases")
        self.application_search.returnPressed.connect(self.refresh_applications)
        row.addWidget(self.application_search, 1)
        row.addWidget(_button("Search", self.refresh_applications))
        self.application_refresh_button = _button(
            "Refresh installed apps", lambda: self.refresh_applications(rescan=True)
        )
        row.addWidget(self.application_refresh_button)
        layout.addLayout(row)
        self.application_notice = _label("Application catalog has not been read.", "Status", True)
        layout.addWidget(self.application_notice)
        self.application_table = _table(["Application", "Permission", "Favorite", "Source"])
        self.application_table.setMinimumHeight(160)
        self.application_table.itemSelectionChanged.connect(self._select_application)
        layout.addWidget(self.application_table)
        self.application_detail = QPlainTextEdit()
        self.application_detail.setReadOnly(True)
        self.application_detail.setMaximumHeight(170)
        self.application_detail.setPlaceholderText(
            "Select an application to inspect its executable or packaged identity."
        )
        layout.addWidget(self.application_detail)
        controls = QHBoxLayout()
        self.application_enable_button = _button(
            "Review & enable", self.toggle_application_permission
        )
        self.application_favorite_button = _button("Favorite", self.toggle_application_favorite)
        self.application_launch_button = _button(
            "Request launch", self.launch_library_application, kind="Primary"
        )
        for button in (
            self.application_enable_button,
            self.application_favorite_button,
            self.application_launch_button,
        ):
            button.setEnabled(False)
            controls.addWidget(button)
        layout.addLayout(controls)
        alias = QHBoxLayout()
        self.application_alias = QLineEdit()
        self.application_alias.setPlaceholderText("Exact spoken alias, for example editor")
        alias.addWidget(self.application_alias, 1)
        self.application_alias_add_button = _button(
            "Add alias", lambda: self.application_alias_operation(False)
        )
        self.application_alias_remove_button = _button(
            "Remove alias", lambda: self.application_alias_operation(True)
        )
        alias.addWidget(self.application_alias_add_button)
        alias.addWidget(self.application_alias_remove_button)
        layout.addLayout(alias)
        form = QFormLayout()
        self.custom_application_name = QLineEdit()
        self.custom_application_path = QLineEdit()
        self.custom_application_path.setPlaceholderText("Absolute path to a local .exe")
        form.addRow("Custom application name", self.custom_application_name)
        form.addRow("Executable", self.custom_application_path)
        layout.addLayout(form)
        self.application_register_button = _button(
            "Register disabled application", self.register_application
        )
        layout.addWidget(self.application_register_button)
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def _application_registry(self):
        return getattr(getattr(self.engine, "registry", None), "applications", None)

    def _selected_application(self):
        row = self.application_table.currentRow()
        return (
            self._applications[row]
            if self.application_table.selectionModel().hasSelection()
            and 0 <= row < len(self._applications)
            else None
        )

    def _application_mutation_allowed(self):
        if self._transition_busy():
            return False
        if self._stopped or "emergency-stop" in self._jobs:
            self._status(
                "Emergency stop is active. Resume before changing application permissions."
            )
            return False
        if self._application_registry() is None:
            self._status("Application discovery is unavailable in this service.")
            return False
        return True

    def refresh_applications(self, *, rescan=False):
        registry = self._application_registry()
        if registry is None:
            self.application_notice.setText("Application discovery is unavailable in this service.")
            self._select_application()
            return
        if rescan and not self._application_mutation_allowed():
            return
        query = self.application_search.text().strip()

        def fetch():
            if rescan:
                registry.refresh()
            return {"applications": registry.list_apps(query), "health": registry.health()}

        self._run("application-read", fetch, self._show_applications)

    def _show_applications(self, data):
        selected = self._pending_application_id or self._selected_application_id
        self._pending_application_id = None
        previous = self._selected_application()
        if selected is None and previous:
            selected = previous["id"]
        self._applications = data.get("applications", [])
        self.application_table.blockSignals(True)
        self.application_table.clearSelection()
        self.application_table.setRowCount(len(self._applications))
        selected_row = -1
        for row, record in enumerate(self._applications):
            for column, value in enumerate(
                (
                    record["name"],
                    "Enabled" if record.get("enabled") else "Disabled",
                    "Yes" if record.get("favorite") else "",
                    record.get("source", ""),
                )
            ):
                self.application_table.setItem(row, column, QTableWidgetItem(str(value)))
            if record["id"] == selected:
                selected_row = row
        if selected_row >= 0:
            self.application_table.selectRow(selected_row)
        self.application_table.blockSignals(False)
        health = data.get("health", {})
        self.application_notice.setText(
            f"{len(self._applications)} matching local applications · {health.get('enabled', 0)} enabled in catalog. Discovery does not prove an app is currently running."
        )
        self._selected_application_id = selected if selected_row >= 0 else None
        self._select_application()

    def _select_application(self):
        record = self._selected_application()
        self._selected_application_id = record.get("id") if record else None
        self.application_detail.setPlainText(
            json.dumps(record, indent=2, ensure_ascii=False, default=str) if record else ""
        )
        busy = (
            self._closing
            or self._stopped
            or any(
                name in self._jobs for name in ("settings", "application-write", "emergency-stop")
            )
        )
        selected = bool(record) and not busy
        self.application_enable_button.setText(
            "Disable" if record and record.get("enabled") else "Review & enable"
        )
        self.application_favorite_button.setText(
            "Remove favorite" if record and record.get("favorite") else "Favorite"
        )
        for button in (
            self.application_enable_button,
            self.application_favorite_button,
            self.application_alias_add_button,
            self.application_alias_remove_button,
        ):
            button.setEnabled(selected)
        self.application_launch_button.setEnabled(selected and bool(record.get("enabled")))
        self.application_register_button.setEnabled(
            not busy and self._application_registry() is not None
        )
        self.application_refresh_button.setEnabled(
            not busy and self._application_registry() is not None
        )

    def _application_changed(self, record):
        self._pending_application_id = (
            record.get("id") if isinstance(record, dict) else self._selected_application_id
        )
        self._status("Application library updated locally · launch permissions still apply")
        self.refresh_applications()

    def register_application(self):
        if not self._application_mutation_allowed():
            return
        name, path = (
            self.custom_application_name.text().strip(),
            self.custom_application_path.text().strip(),
        )
        registry = self._application_registry()
        self._run(
            "application-write",
            lambda: registry.register_custom(name, path),
            self._application_changed,
        )

    def toggle_application_permission(self):
        if not self._application_mutation_allowed():
            return
        record = self._selected_application()
        if not record:
            return
        enabled = not record.get("enabled", False)
        reviewed_target = (record.get("kind"), record.get("target"))
        if enabled:
            answer = QMessageBox.question(
                self,
                "Enable application launch",
                f"Allow explicitly requested launches of {record['name']}?\n\nExact {record.get('kind', 'application')} target:\n{record.get('target', '')}\n\nAn executable runs with your Windows account permissions. Review this target before enabling it.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            if not self._application_mutation_allowed():
                return
        registry, identity = self._application_registry(), record["id"]

        def change_permission():
            if enabled:
                current = next(
                    (item for item in registry.list_apps() if item["id"] == identity), None
                )
                if (
                    current is None
                    or (current.get("kind"), current.get("target")) != reviewed_target
                ):
                    raise PermissionError(
                        "The application target changed after review. Refresh and inspect it again."
                    )
            return registry.set_enabled(
                identity,
                enabled,
                expected_kind=reviewed_target[0] if enabled else None,
                expected_target=reviewed_target[1] if enabled else None,
            )

        self._run(
            "application-write",
            change_permission,
            self._application_changed,
        )

    def toggle_application_favorite(self):
        if not self._application_mutation_allowed():
            return
        record = self._selected_application()
        if record:
            registry, identity, favorite = (
                self._application_registry(),
                record["id"],
                not record.get("favorite", False),
            )
            self._run(
                "application-write",
                lambda: registry.set_favorite(identity, favorite),
                self._application_changed,
            )

    def application_alias_operation(self, remove=False):
        if not self._application_mutation_allowed():
            return
        record, alias = self._selected_application(), self.application_alias.text().strip()
        if record:
            registry, identity = self._application_registry(), record["id"]
            operation = registry.remove_alias if remove else registry.set_alias
            self._run(
                "application-write", lambda: operation(identity, alias), self._application_changed
            )

    def launch_library_application(self):
        if not self._application_mutation_allowed():
            return
        record = self._selected_application()
        if record and record.get("enabled"):
            identity = record["id"]
            self._run(
                "action",
                lambda: self.engine.submit("open_app", {"app": identity}),
                self._task_result,
            )

    def _selected_action_run(self):
        row = self.action_run_table.currentRow()
        return (
            self._action_runs[row]
            if self.action_run_table.selectionModel().hasSelection()
            and 0 <= row < len(self._action_runs)
            else None
        )

    def _select_action_run(self):
        run = self._selected_action_run()
        self.action_run_detail.setPlainText(
            json.dumps(run, indent=2, ensure_ascii=False, default=str) if run else ""
        )
        self.cancel_action_run_button.setEnabled(
            bool(run and run.get("state") in {"running", "awaiting_approval"}) and not self._closing
        )

    def cancel_action_run(self):
        run, actions = self._selected_action_run(), getattr(self.service, "actions", None)
        if run and actions:
            identity = run["id"]
            self._run("action-cancel", lambda: actions.cancel(identity), lambda _: self.refresh())

    def _show_action_runs(self, runs):
        previous = self._selected_action_run()
        identity = previous.get("id") if previous else None
        self._action_runs = runs
        self.action_run_table.blockSignals(True)
        self.action_run_table.clearSelection()
        self.action_run_table.setRowCount(len(runs))
        for row, run in enumerate(runs):
            for column, value in enumerate(
                (
                    run.get("name", "Requested actions"),
                    run.get("state", "unknown"),
                    f"{run.get('step_index', 0)} / {len(run.get('steps', []))}",
                )
            ):
                self.action_run_table.setItem(row, column, QTableWidgetItem(str(value)))
            if run["id"] == identity:
                self.action_run_table.selectRow(row)
        self.action_run_table.blockSignals(False)
        self._select_action_run()

    def _refresh_active_actions(self):
        if self._closing or not any(
            name in self._jobs for name in ("chat", "action", "task-operation", "action-cancel")
        ):
            return
        actions = getattr(self.service, "actions", None)

        def fetched(data):
            self._show_task_records(data["tasks"])
            self._show_action_runs(data["action_runs"])

        self._run(
            "action-progress",
            lambda: {
                "tasks": self.store.tasks(),
                "action_runs": actions.history() if actions else [],
            },
            fetched,
        )

    def _read_action_health(self):
        registry = getattr(self.engine, "registry", None)
        health = {}
        for name in ("windows", "applications", "browser"):
            component = getattr(registry, name, None)
            health[name] = (
                component.health()
                if component and hasattr(component, "health")
                else {"status": "unavailable"}
            )
        health["model_action_planning"] = getattr(self.settings, "model_action_planning", False)
        health["desktop_actions_enabled"] = getattr(self.settings, "desktop_actions_enabled", True)
        return health

    def refresh_action_health(self):
        self._run("action-health", self._read_action_health, self._show_action_health)

    def _show_action_health(self, health):
        self._action_health = health
        self.action_diagnostics.setPlainText(
            json.dumps(health, indent=2, ensure_ascii=False, default=str)
        )

    def _business_page(self) -> QWidget:
        from .business import sample_summary

        self._business = None
        self._business_products = []
        self._business_orders = []
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_label("BUSINESS · LOCAL BOOKKEEPING", "Muted"))
        self.business_notice = _label(
            "SAMPLE DATA · no private financial records loaded. Payments and fulfillment below are manual records, not external verification or delivery.",
            "Status",
            True,
        )
        layout.addWidget(self.business_notice)
        self.business_summary = QPlainTextEdit()
        self.business_summary.setReadOnly(True)
        self.business_summary.setMaximumHeight(180)
        self.business_summary.setPlainText(json.dumps(sample_summary(), indent=2))
        layout.addWidget(self.business_summary)
        layout.addWidget(_button("Use my local ledger", self.open_business_ledger))
        self.business_editor = QWidget()
        edit = QVBoxLayout(self.business_editor)
        row = QHBoxLayout()
        self.inventory_name = QLineEdit()
        self.inventory_name.setPlaceholderText("Product name")
        self.inventory_sku = QLineEdit()
        self.inventory_sku.setPlaceholderText("SKU")
        self.inventory_quantity = QSpinBox()
        self.inventory_quantity.setRange(1, 100000)
        self.inventory_cost = QLineEdit("0.00")
        self.inventory_cost.setPlaceholderText("Purchase price per unit")
        self.inventory_currency = QComboBox()
        self.inventory_currency.addItems(["INR", "USD", "EUR", "GBP"])
        for widget in (
            self.inventory_name,
            self.inventory_sku,
            self.inventory_quantity,
            self.inventory_cost,
            self.inventory_currency,
        ):
            row.addWidget(widget)
        edit.addWidget(
            _label("Inventory · name, SKU, quantity, unit purchase price, currency", "Muted", True)
        )
        edit.addLayout(row)
        edit.addWidget(_button("Add inventory record", self.add_business_inventory))
        row = QHBoxLayout()
        self.order_product = QComboBox()
        self.order_quantity = QSpinBox()
        self.order_quantity.setRange(1, 100000)
        self.order_sale = QLineEdit("0.00")
        self.order_cost = QLineEdit("0.00")
        for widget in (self.order_product, self.order_quantity, self.order_sale, self.order_cost):
            row.addWidget(widget)
        edit.addWidget(
            _label(
                "Order · product, quantity, unit sale price, total transaction cost", "Muted", True
            )
        )
        edit.addLayout(row)
        edit.addWidget(_button("Record order", self.add_business_order))
        self.business_table = _table(["Product", "Quantity", "State", "Payment provenance"])
        self.business_table.setMinimumHeight(150)
        edit.addWidget(self.business_table)
        self.business_order_detail = QPlainTextEdit()
        self.business_order_detail.setReadOnly(True)
        self.business_order_detail.setMaximumHeight(140)
        self.business_table.itemSelectionChanged.connect(self._select_business_order)
        edit.addWidget(self.business_order_detail)
        row = QHBoxLayout()
        row.addWidget(
            _button("Record payment received", lambda: self.business_operation("confirm_payment"))
        )
        row.addWidget(_button("Record fulfilled", lambda: self.business_operation("fulfill_order")))
        row.addWidget(
            _button("Cancel order record", lambda: self.business_operation("cancel_order"))
        )
        edit.addLayout(row)
        self.business_editor.hide()
        layout.addWidget(self.business_editor)
        layout.addWidget(
            _label(
                "No messaging, purchases, transfers or item delivery. WhatsApp/LINE adapters only describe future official connections; no account is connected.",
                "Muted",
                True,
            )
        )
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def open_business_ledger(self):
        from .business import BusinessLedger

        def opened(ledger):
            self._business = ledger
            self.business_notice.setText(
                "LOCAL RECORDS · manually entered. No payment provider verification, messages, money transfers or inventory delivery."
            )
            self.business_editor.show()
            self.refresh_business()

        self._run("business", lambda: BusinessLedger(self.settings.data_dir), opened)

    def refresh_business(self):
        if not self._business:
            return

        def fetched(data):
            row = self.business_table.currentRow()
            selected = (
                self._business_orders[row]["id"] if 0 <= row < len(self._business_orders) else None
            )
            selected_product = self.order_product.currentData()
            self._business_products, self._business_orders = data["products"], data["orders"]
            self.business_summary.setPlainText(
                json.dumps(data["summary"], indent=2, ensure_ascii=False)
            )
            self.order_product.clear()
            for product in self._business_products:
                self.order_product.addItem(product["name"], product["id"])
            selected_index = self.order_product.findData(selected_product)
            if selected_index >= 0:
                self.order_product.setCurrentIndex(selected_index)
            self.business_table.blockSignals(True)
            self.business_table.setRowCount(len(self._business_orders))
            for row, order in enumerate(self._business_orders):
                for col, value in enumerate(
                    (
                        order.get("product_name", order.get("product_id")),
                        order["quantity"],
                        order["status"],
                        "Manual confirmation"
                        if order.get("payment_confirmed_manually")
                        else "Unconfirmed",
                    )
                ):
                    self.business_table.setItem(row, col, QTableWidgetItem(str(value)))
                if order["id"] == selected:
                    self.business_table.selectRow(row)
            self.business_table.blockSignals(False)
            self._select_business_order()

        self._run(
            "business-refresh",
            lambda: {
                "products": self._business.inventory(),
                "orders": self._business.orders(),
                "summary": self._business.summary(),
            },
            fetched,
        )

    def add_business_inventory(self):
        if self._business:
            values = (
                self.inventory_name.text(),
                self.inventory_sku.text(),
                self.inventory_quantity.value(),
                self.inventory_cost.text(),
                self.inventory_currency.currentText(),
            )
            self._run(
                "business",
                lambda: self._business.add_inventory(*values),
                lambda _: self.refresh_business(),
            )

    def add_business_order(self):
        if self._business and self.order_product.currentData():
            values = (
                self.order_product.currentData(),
                self.order_quantity.value(),
                self.order_sale.text(),
                self.order_cost.text(),
            )
            self._run(
                "business",
                lambda: self._business.create_order(*values),
                lambda _: self.refresh_business(),
            )

    def _select_business_order(self):
        row = self.business_table.currentRow()
        self.business_order_detail.setPlainText(
            json.dumps(self._business_orders[row], indent=2, ensure_ascii=False)
            if 0 <= row < len(self._business_orders)
            else ""
        )

    def business_operation(self, operation):
        row = self.business_table.currentRow()
        if self._business and 0 <= row < len(self._business_orders):
            identity = self._business_orders[row]["id"]
            self._run(
                "business",
                lambda: getattr(self._business, operation)(identity),
                lambda _: self.refresh_business(),
            )

    def command_palette(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("JARVIS commands")
        dialog.resize(450, 420)
        layout = QVBoxLayout(dialog)
        query = QLineEdit()
        query.setPlaceholderText("Find a command…")
        layout.addWidget(query)
        commands = QListWidget()
        actions = [
            (title, lambda i=i: self._navigate(i)) for i, title in enumerate(self.page_titles)
        ]
        actions += [
            ("Compact assistant", self.toggle_compact),
            ("New conversation", self.new_conversation),
            ("Pause microphone", lambda: self.voice_controller.stop()),
            ("Mute", lambda: self.voice_controller.mute()),
            ("Emergency stop", self.emergency_stop),
        ]
        for title, _ in actions:
            commands.addItem(title)
        layout.addWidget(commands)

        def filter_items(text):
            for i in range(commands.count()):
                commands.item(i).setHidden(text.lower() not in commands.item(i).text().lower())

        def execute(item):
            row = commands.row(item)
            dialog.accept()
            actions[row][1]()

        query.textChanged.connect(filter_items)
        commands.itemActivated.connect(execute)
        query.returnPressed.connect(
            lambda: execute(
                next(
                    (
                        commands.item(i)
                        for i in range(commands.count())
                        if not commands.item(i).isHidden()
                    ),
                    commands.item(0),
                )
            )
        )
        query.setFocus()
        dialog.exec()

    def _update_presence(self) -> None:
        if self._closing:
            return
        controller = self.voice_controller
        active_jobs = [
            name
            for name in self._jobs
            if name not in {"refresh", "health", "awareness", "audio-devices"}
        ]
        pending = sum(task.get("state") == "awaiting_approval" for task in self._tasks)
        self.mission_summary.setText(
            f"Active · {', '.join(active_jobs) if active_jobs else 'none'}    Approvals · {pending}    Recorded tasks · {len(self._tasks)}"
        )
        value = controller.session.state.value
        capture = bool(
            controller.input and controller.input.running and controller.input.mode != "gated"
        )
        mapping = {
            "WAKE_WORD_LISTENING": "wake",
            "ACTIVATED": "activated",
            "USER_SPEAKING": "listening",
            "PROCESSING": "thinking",
            "ASSISTANT_SPEAKING": "speaking",
            "FOLLOW_UP_LISTENING": "listening",
            "MUTED": "muted",
            "ERROR": "error",
        }
        state = mapping.get(value, "idle")
        if state in {"wake", "listening", "activated"} and not capture:
            state = "idle"
        if self._stopped:
            state = "muted"
        elif self._speech and self._speech.speaking:
            state = "speaking"
        elif any(key in self._jobs for key in ("action", "task-operation", "workflow-run")):
            state = "tool"
        elif (
            "chat" in self._jobs or "record" in self._jobs and self._record_stage == "transcribing"
        ):
            state = "thinking"
        elif self._record_stage == "recording":
            state = "listening"
        elif any(task.get("state") == "awaiting_approval" for task in self._tasks):
            state = "approval"
        self.core.set_state(state)
        level = getattr(controller.input, "level", None) if capture else None
        if level is None:
            self.core.clear_level()
        else:
            self.core.set_level(level)
        self.presence_caption.setText(self.voice_status.text())
        self._update_overlay(state)
        self.provider_ribbon.setText(
            f"{self.settings.provider.upper()} · {self.settings.model or 'Choose a model'} · {'Cloud consent on' if self.settings.cloud_allowed else 'Local first'}"
        )
        context = self._context_snapshot
        project = context.get("project")
        self.context_ribbon.setText(
            "CONTEXT · "
            + (project.get("name", "Selected project") if project else "No project selected")
        )

    def refresh_system(self, force=False) -> None:
        if self._closing or not force and self.pages.currentIndex() != 6:
            return
        from .awareness import collect_awareness

        consent = self.settings.desktop_context_enabled

        def measured(result):
            self._awareness_data = result.as_dict()
            # A revoked permission discards any in-flight foreground sample.
            if consent and not self.settings.desktop_context_enabled:
                self._awareness_data.pop("desktop", None)
                self._awareness_data.pop("context", None)
            system = self._awareness_data.get("system", {})
            cpu = system.get("cpu_percent")
            ram = system.get("memory_percent")
            self.system_summary.setText(
                f"CPU · {f'{cpu:.1f}%' if cpu is not None else 'Waiting for second sample'}    RAM · {f'{ram:.1f}%' if ram is not None else 'Unavailable'}\nMeasured: {system.get('sampled_at', 'Unavailable')}"
            )
            self.system_details.setPlainText(
                json.dumps(self._awareness_data, indent=2, ensure_ascii=False)
            )

        self._run(
            "awareness",
            lambda: collect_awareness(
                self._metrics_provider, self._context_provider, consent=consent
            ),
            measured,
        )

    def _routine_done(self, result=None):
        if isinstance(result, dict) and "steps" in result and "state" in result:
            self._status(
                "Workflow "
                + str(result["state"]).replace("_", " ")
                + " · review steps and evidence"
            )
        self.refresh()

    def _build_overlay(self):
        from .ui_components import CoreWidget

        self._overlay_dismissed = False
        self.ambient_overlay = QFrame(
            self,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.ambient_overlay.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.ambient_overlay.setObjectName("Panel")
        self.ambient_overlay.setStyleSheet(self.styleSheet())
        layout = QVBoxLayout(self.ambient_overlay)
        self.overlay_core = CoreWidget()
        self.overlay_core.set_reduce_motion(self.settings.reduce_motion)
        self.overlay_core.setMaximumHeight(110)
        layout.addWidget(self.overlay_core)
        self.overlay_label = _label("", "Muted", True)
        layout.addWidget(self.overlay_label)
        row = QHBoxLayout()
        row.addWidget(_button("Open JARVIS", self.show_from_tray))
        row.addWidget(_button("Dismiss", self.dismiss_overlay))
        layout.addLayout(row)
        self.ambient_overlay.resize(320, 210)

    def dismiss_overlay(self):
        self._overlay_dismissed = True
        self.ambient_overlay.hide()

    def _update_overlay(self, state):
        if state in {"idle", "wake", "muted", "error"}:
            self._overlay_dismissed = False
        active = state in {"activated", "listening", "thinking", "tool", "speaking", "approval"}
        if self.isVisible() or not active or self._overlay_dismissed or self._closing:
            self.ambient_overlay.hide()
            return
        self.overlay_core.set_state(state)
        self.overlay_label.setText(self.voice_status.text())
        screen = QApplication.primaryScreen()
        if screen:
            rect = screen.availableGeometry()
            self.ambient_overlay.move(
                rect.right() - self.ambient_overlay.width() - 24,
                rect.bottom() - self.ambient_overlay.height() - 24,
            )
        self.ambient_overlay.show()

    def register_project(self):
        if self._transition_busy():
            return
        name, path = self.project_name.text().strip(), self.project_path.text().strip()
        self._run(
            "workflow-write",
            lambda: self.workflows.register_project(name, path),
            self._routine_done,
        )

    def delete_project(self):
        if self._transition_busy():
            return
        identity = self.project_choice.currentData()
        if identity:
            self._run(
                "workflow-write",
                lambda: self.workflows.delete_project(identity),
                self._routine_done,
            )

    def select_project_context(self):
        if self._transition_busy():
            return
        identity = self.project_choice.currentData()
        if identity:
            if self.session_id is None:
                import uuid

                self.session_id = str(uuid.uuid4())

            def selected(context):
                self._context_snapshot = context
                self._update_presence()
                self._status("Project context selected · actions still require explicit requests")

            self._run(
                "context",
                lambda: self.workflows.select_project(identity, self.session_id),
                selected,
            )

    def create_development_routine(self):
        if self._transition_busy():
            return
        identity = self.project_choice.currentData()
        if identity:
            project = next(item for item in self._projects if item["id"] == identity)
            self._run(
                "workflow-write",
                lambda: self.workflows.create_development_routine(
                    identity, "Development · " + project["name"]
                ),
                self._routine_done,
            )
        else:
            self._status("Register or select a project first")

    def _select_routine(self):
        identity = self.routine_choice.currentData()
        self._editing_routine_id = identity
        self._routine_dirty = False
        self.routine_enabled.setEnabled(bool(identity))
        routine = next((item for item in self._routines if item["id"] == identity), None)
        self._routine_steps = list(routine["steps"]) if routine else []
        self.routine_name.setText(routine["name"] if routine else "")
        self.routine_enabled.setChecked(bool(routine and routine["enabled"]))
        self.run_routine_button.setEnabled(bool(routine and routine["enabled"]))
        self._show_routine_steps()

    def _show_routine_steps(self):
        self.routine_preview.clear()
        for i, step in enumerate(self._routine_steps, 1):
            self.routine_preview.addItem(
                f"{i}. {step['tool'].replace('_', ' ')} · {json.dumps(step['arguments'], ensure_ascii=False)}"
            )

    def _mark_routine_dirty(self):
        self._routine_dirty = True
        self.run_routine_button.setEnabled(False)
        self.routine_enabled.setEnabled(False)
        self._status("Unsaved routine changes · save, inspect and enable before running")

    def add_routine_step(self):
        tool = self.routine_tool.currentData()
        argument = self.routine_argument.text().strip()
        if argument:
            self._routine_steps.append(
                {"tool": tool, "arguments": {"app" if tool == "open_app" else "path": argument}}
            )
            self._show_routine_steps()
            self._mark_routine_dirty()
            self._status("Unsaved changes · save, inspect and enable before running")

    def remove_routine_step(self):
        index = self.routine_preview.currentRow()
        if 0 <= index < len(self._routine_steps):
            self._routine_steps.pop(index)
            self._show_routine_steps()
            self._mark_routine_dirty()

    def save_routine(self):
        if self._transition_busy():
            return
        identity, name, steps = (
            self.routine_choice.currentData(),
            self.routine_name.text().strip(),
            list(self._routine_steps),
        )

        def action():
            return (
                self.workflows.update_routine(identity, name=name, steps=steps)
                if identity
                else self.workflows.create_routine(name, steps)
            )

        def saved(result):
            self._routine_dirty = False
            self._routine_done(result)

        self._run("workflow-write", action, saved)

    def enable_routine(self):
        if self._transition_busy():
            return
        identity, enabled = self.routine_choice.currentData(), self.routine_enabled.isChecked()
        if identity and not self._routine_dirty:
            self._run(
                "workflow-write",
                lambda: self.workflows.set_enabled(identity, enabled),
                self._routine_done,
            )
        else:
            self.routine_enabled.setChecked(False)

    def delete_routine(self):
        if self._transition_busy():
            return
        identity = self.routine_choice.currentData()
        if identity:
            self._run(
                "workflow-write",
                lambda: self.workflows.delete_routine(identity),
                self._routine_done,
            )

    def run_routine(self):
        identity = self.routine_choice.currentData()
        if (
            identity
            and not self._routine_dirty
            and not self._stopped
            and not self._transition_busy()
        ):
            self._run(
                "workflow-run",
                lambda: self.workflows.start(identity, session_id=self.session_id or "default"),
                self._routine_done,
            )

    def _selected_workflow(self):
        row = self.workflow_table.currentRow()
        return self._workflow_runs[row] if 0 <= row < len(self._workflow_runs) else None

    def _select_workflow_run(self):
        run = self._selected_workflow()
        self.workflow_detail.setPlainText(
            json.dumps(run, indent=2, ensure_ascii=False)
            if run
            else "Select a run to inspect its actual steps and results."
        )

    def resume_workflow(self):
        if self._transition_busy():
            return
        run = self._selected_workflow()
        if run and not self._stopped:
            self._run("workflow-run", lambda: self.workflows.resume(run["id"]), self._routine_done)

    def cancel_workflow(self):
        run = self._selected_workflow()
        if run:
            self._run(
                "workflow-cancel", lambda: self.workflows.cancel(run["id"]), self._routine_done
            )

    def _status(self, text: str) -> None:
        self.status_label.setText(text)

    def _update_build_health(self) -> None:
        controller = getattr(self, "voice_controller", None)
        voice = controller.session.state.value if controller else "IDLE"
        error = controller.session.error if controller else None
        startup_error = self.settings.data_dir / "startup-error.json"
        if not error and startup_error.is_file():
            try:
                historical = json.loads(startup_error.read_text(encoding="utf-8"))
                error = f"{historical.get('error', 'Unknown')} ({historical.get('time_utc', 'historical')})"
            except (ValueError, OSError):
                error = "Startup error record could not be read"
        identity = self.build_info
        speech = self._speech
        engine = (
            (speech.engine or speech.error)
            if speech and hasattr(speech, "engine")
            else "Not initialized; enable Speak replies or refresh devices"
        )
        self.build_health_label.setText(
            f"Application {identity['version']} · Git {identity['git_commit'][:12]} · dirty={identity.get('dirty')}\n"
            f"Built: {identity['build_date_utc']}\nExecutable: {identity['executable']}\n"
            f"Voice engine: {engine}\nWake: {voice} · phrase: {self.settings.wake_phrase}\n"
            f"Microphone: {self.voice_status.text()}\nBackend: {self.health_result['backend']}\n"
            f"Speech model: {self.health_result['speech_model']}\nLast startup/voice error: {error or 'None reported'}"
        )

    def run_health_check(self) -> None:
        from .health import startup_health

        def checked(result):
            self.health_result = result
            self._update_build_health()
            self._status("Startup health checked · see build and voice details in Settings")

        self._run("health", lambda: startup_health(self.settings.model_copy(deep=True)), checked)
        self.refresh_action_health()

    def _transition_busy(self) -> bool:
        if any(name in self._jobs for name in ("settings", "history", "history-delete")):
            self._status("Please wait while settings or the saved conversation are updated.")
            return True
        return False

    def _update_privacy_label(self) -> None:
        location = "Cloud enabled" if self.settings.cloud_allowed else "Local only"
        history = "History saved" if self.settings.save_history else "History in memory"
        self.privacy_label.setText(f"{location}\n{history}\n{self.settings.mode.title()} actions")

    def _append_message(self, role: str, content: str) -> None:
        cursor = self.conversation.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        title = QTextCharFormat()
        title.setForeground(QColor("#70e0ed" if role == "JARVIS" else "#b8c8dc"))
        title.setFontWeight(700)
        cursor.insertText(f"{role}\n", title)
        body = QTextCharFormat()
        body.setForeground(QColor("#dde8f5"))
        cursor.insertText(str(content) + "\n\n", body)
        self.conversation.setTextCursor(cursor)
        self.conversation.ensureCursorVisible()
        if role == "JARVIS" and hasattr(self, "compact_response"):
            self.compact_response.setText(
                str(content)[:160] + ("…" if len(str(content)) > 160 else "")
            )

    def _run(
        self,
        name: str,
        action: Callable[[], Any],
        success: Callable[[Any], None] | None = None,
        failure: Callable[[str], None] | None = None,
    ) -> _Job | None:
        if name in self._jobs or self._closing:
            return None
        job = _Job(action, self)
        self._jobs[name] = job

        def done(result: Any) -> None:
            if not self._closing and success:
                success(result)

        def failed(error: str) -> None:
            if not self._closing:
                (failure or self._status)(error)

        job.signals.succeeded.connect(done)
        job.signals.failed.connect(failed)
        job.signals.finished.connect(lambda: self._finish_job(name))
        self._pool.start(job)
        if name in {"application-write", "settings", "emergency-stop"} and hasattr(
            self, "application_table"
        ):
            self._select_application()
        return job

    def _finish_job(self, name: str) -> None:
        job = self._jobs.pop(name, None)
        if job is not None:
            job.signals.deleteLater()
        if name == "chat":
            self._chat_cancel = None
            self.send_button.setEnabled(not self._closing)
        if name == "record":
            self._audio_status_timer.stop()
            self._record_stage = "idle"
            self.mic_button.setText("Hold to talk")
            self.mic_button.setEnabled(not self._closing)
        if name == "settings":
            self.save_settings_button.setEnabled(not self._closing)
        if name in {"application-write", "settings", "emergency-stop", "resume"}:
            self._select_application()
        if self._closing:
            self._poll_shutdown()
        elif hasattr(self, "voice_controller"):
            self._update_presence()

    def send_message(self) -> bool:
        text = self.composer.toPlainText().strip()
        if not text or "chat" in self._jobs or self._closing:
            return False
        if self._transition_busy():
            return False
        if self._stopped:
            self._status("Emergency stop is active. Resume in Mission Control before sending.")
            return False
        self.composer.clear()
        controller = self.voice_controller
        if controller.active:
            from .conversation import VoiceState

            if controller.session.state == VoiceState.ASSISTANT_SPEAKING:
                if self._speech:
                    self._speech.stop()
                controller.session.response_finished()
            if controller.session.state == VoiceState.WAKE_WORD_LISTENING:
                controller.session.wake(text)
            if controller.session.state != VoiceState.PROCESSING:
                controller.gate()
                controller.session.processing()
        self._append_message("YOU", text)
        self.send_button.setEnabled(False)
        self._status("Processing your request · Interrupt cancels at the next safe boundary")
        cancel = threading.Event()
        self._chat_cancel = cancel
        session = self.session_id
        requested_at = time.monotonic()

        def succeeded(result: dict[str, Any]) -> None:
            self.session_id = result.get("session_id", self.session_id)
            if cancel.is_set():
                self._status("Request interrupted. A provider may finish its in-flight request.")
                return
            answer = str(result.get("text", ""))
            self._last_reply = result
            self._last_latency = time.monotonic() - requested_at
            self.ai_diagnostics.setText(
                f"Last reply · {result.get('provider', 'unknown')} / {result.get('model', '')}\n"
                f"Elapsed: {self._last_latency:.2f} seconds\nReported token usage: {json.dumps(result.get('usage', {}))}\n"
                "API cost: unavailable (no pricing estimate configured)"
            )
            self._append_message("JARVIS", answer)
            self._status(
                f"Reply from {result.get('provider', self.settings.provider)} · {result.get('model', self.settings.model)}"
            )
            self.voice_controller.reply(answer)
            self.refresh()

        def failed(error: str) -> None:
            self._append_message("SYSTEM", error)
            self._status("Request failed · review the message above")
            self.voice_controller.interrupted()

        self._run(
            "chat",
            lambda: self.service.chat(text, session_id=session, cancel=cancel),
            succeeded,
            failed,
        )
        return True

    def new_conversation(self) -> None:
        if self._transition_busy():
            return
        if "chat" in self._jobs:
            self._status("Interrupt or wait for the current reply before starting a conversation.")
            return
        self._reset_conversation()

    def _reset_conversation(self) -> None:
        self.session_id = None
        self._context_snapshot = {}
        self.conversation.clear()
        self._status("New conversation · microphone off")

    def interrupt(self) -> None:
        if self._chat_cancel:
            self._chat_cancel.set()
        self._record_cancel.set()
        self._record_release.set()
        if self._speech:
            self._speech.stop()
        if hasattr(self, "voice_controller"):
            self.voice_controller.interrupted()
        if not self._closing:
            self._run("workflow-interrupt", self.workflows.emergency_stop)
            actions = getattr(self.service, "actions", None)
            if actions:
                self._run("action-interrupt", actions.emergency_stop)
        self._status("Interrupted · active requests stop at the next safe boundary")

    def _tool_changed(self) -> None:
        tool = self.tool_choice.currentData()
        app = tool in {"open_app", "focus_app"}
        self.tool_app.setVisible(app)
        self.tool_path.setVisible(
            not app and tool not in {"list_applications", "get_system_status"}
        )
        self.tool_path.setPlaceholderText(
            "Public HTTPS URL or approved website alias"
            if tool == "open_website"
            else "Search words (opened in your preferred browser)"
            if tool == "search_web"
            else "Full path inside a permitted folder"
        )

    def submit_action(self) -> None:
        if self._transition_busy():
            return
        tool = self.tool_choice.currentData()
        if tool in {"open_app", "focus_app"}:
            args = {"app": self.tool_app.currentText().strip()}
        elif tool in {"list_applications", "get_system_status"}:
            args = {}
        else:
            key = (
                "target" if tool == "open_website" else "query" if tool == "search_web" else "path"
            )
            args = {key: self.tool_path.text().strip()}
        if args and not next(iter(args.values())):
            self._status("Enter a target for this action.")
            return
        if self._stopped:
            self._status("Emergency stop is active. Resume before submitting actions.")
            return
        self._status("Submitting the scoped action…")
        self._run("action", lambda: self.engine.submit(tool, args), self._task_result)

    def _task_result(self, result: dict[str, Any]) -> None:
        if result.get("id"):
            self._last_task_id = result["id"]
            self._live_task_results[result["id"]] = result
        self.task_detail.setPlainText(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        self._status(
            f"Action {result.get('state', 'updated')} · review Mission Control for evidence"
        )
        self.refresh()
        self.voice_controller.task_event(result)

    def _selected_task(self) -> dict[str, Any] | None:
        row = self.task_table.currentRow()
        return (
            self._tasks[row]
            if self.task_table.selectionModel().hasSelection() and 0 <= row < len(self._tasks)
            else None
        )

    def _select_task(self) -> None:
        task = self._selected_task()
        self.task_detail.setPlainText(
            json.dumps(task, indent=2, ensure_ascii=False, default=str) if task else ""
        )
        pending = bool(task and task.get("state") == "awaiting_approval")
        self.approve_button.setEnabled(pending and not self._stopped)
        self.reject_button.setEnabled(pending)
        self.cancel_task_button.setEnabled(
            bool(
                task
                and task.get("state")
                in (
                    "queued",
                    "awaiting_approval",
                    "running",
                    "verifying",
                )
            )
        )

    def task_operation(self, operation: str) -> None:
        if self._transition_busy():
            return
        task = self._selected_task()
        if not task:
            return
        task_id = task["id"]

        def operate():
            result = getattr(self.engine, operation)(task_id)
            self.workflows.resume_for_task(task_id)
            actions = getattr(self.service, "actions", None)
            if actions:
                actions.resume_for_task(task_id)
            return result

        self._run("task-operation", operate, self._task_result)

    def emergency_stop(self) -> None:
        self._stopped = True
        self.interrupt()
        self.voice_controller.stop("mute")
        self._select_task()
        self._status("EMERGENCY STOP · cancelling pending actions and voice")
        stop = getattr(self.service, "emergency_stop", self.engine.emergency_stop)

        def halt():
            stop()
            self.workflows.emergency_stop()

        self._run("emergency-stop", halt, lambda _: self.refresh())

    def resume(self) -> None:
        if "emergency-stop" in self._jobs:
            self._status("Wait for the emergency stop to finish before resuming.")
            return

        def resumed(_: Any) -> None:
            self._stopped = False
            self._status("Ready · pending actions still require their approvals")
            self._select_task()
            self.refresh()

        reset = getattr(self.service, "reset_stop", self.engine.reset_stop)
        self._run("resume", reset, resumed)

    def refresh(self) -> None:
        query = self.memory_search.text().strip()
        session = self.session_id or "default"

        def fetch() -> dict[str, Any]:
            actions = getattr(self.service, "actions", None)
            return {
                "tasks": self.store.tasks(),
                "memories": self.store.memories(query),
                "audits": self.store.audits(limit=100),
                "sessions": self.store.sessions(),
                "routines": self.workflows.routines(),
                "workflow_runs": self.workflows.runs(),
                "projects": self.workflows.projects(),
                "context": self.workflows.session_context(session),
                "action_runs": actions.history() if actions else [],
            }

        self._run("refresh", fetch, self._show_data)

    def _show_task_records(self, tasks):
        selected_task = self._selected_task()
        task_id = self._last_task_id or (selected_task.get("id") if selected_task else None)
        self._last_task_id = None
        self._tasks = [
            self._live_task_results.get(task["id"], task)
            if self._live_task_results.get(task["id"], {}).get("state") == task["state"]
            else task
            for task in tasks
        ]
        self.task_table.blockSignals(True)
        self.task_table.clearSelection()
        self.task_table.setRowCount(len(self._tasks))
        task_row = -1
        for row, task in enumerate(self._tasks):
            for column, value in enumerate((task["id"], task["tool"], task["state"])):
                self.task_table.setItem(row, column, QTableWidgetItem(str(value)))
            if task["id"] == task_id:
                task_row = row
        if task_row >= 0:
            self.task_table.selectRow(task_row)
        self.task_table.blockSignals(False)
        self._select_task()

    def _show_data(self, data: dict[str, Any]) -> None:
        self._show_task_records(data["tasks"])
        selected_memory_id = self._selected_memory
        self._memories = data["memories"]
        self.memory_table.blockSignals(True)
        self.memory_table.setRowCount(len(self._memories))
        self.memory_table.clearSelection()
        memory_row = -1
        for row, memory in enumerate(self._memories):
            for column, key in enumerate(("category", "key", "source")):
                self.memory_table.setItem(row, column, QTableWidgetItem(str(memory.get(key, ""))))
            if memory["id"] == selected_memory_id:
                memory_row = row
        if memory_row >= 0:
            self.memory_table.selectRow(memory_row)
        self.memory_table.blockSignals(False)
        self.audit_view.setPlainText(
            json.dumps(data["audits"], indent=2, ensure_ascii=False, default=str)
        )
        self.session_list.clear()
        for session in data["sessions"]:
            session_id = str(session.get("session_id", session.get("id", "")))
            self.session_list.addItem(session_id)
            item = self.session_list.item(self.session_list.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, session_id)
        self._select_task()
        self._show_workflow_data(data)
        self._show_action_runs(data.get("action_runs", []))

    def _show_workflow_data(self, data):
        self._context_snapshot = data.get("context", {})
        selected_project = self.project_choice.currentData()
        selected_routine = self.routine_choice.currentData()
        previous_run = self._selected_workflow()
        selected_id = previous_run.get("id") if previous_run else None
        self._projects, self._routines = data.get("projects", []), data.get("routines", [])
        self._workflow_runs = data.get("workflow_runs", [])
        for choice, title, records, selected in (
            (self.project_choice, "Select a project", self._projects, selected_project),
            (self.routine_choice, "New routine", self._routines, selected_routine),
        ):
            choice.blockSignals(True)
            choice.clear()
            choice.addItem(title, None)
            for item in records:
                choice.addItem(item["name"], item["id"])
            index = choice.findData(selected)
            choice.setCurrentIndex(max(index, 0))
            choice.blockSignals(False)
        if not self._routine_dirty or self._editing_routine_id != self.routine_choice.currentData():
            self._select_routine()
        self.workflow_table.setRowCount(len(self._workflow_runs))
        for row, run in enumerate(self._workflow_runs):
            for column, value in enumerate(
                (run["name"], run["state"], f"{run.get('step_index', 0)} / {len(run['steps'])}")
            ):
                self.workflow_table.setItem(row, column, QTableWidgetItem(str(value)))
            if run["id"] == selected_id:
                self.workflow_table.selectRow(row)
        self._select_workflow_run()

    def _select_memory(self) -> None:
        row = self.memory_table.currentRow()
        if not 0 <= row < len(self._memories):
            self.delete_memory_button.setEnabled(False)
            return
        memory = self._memories[row]
        self._selected_memory = memory["id"]
        self.memory_category.setCurrentText(str(memory["category"]))
        self.memory_key.setText(str(memory["key"]))
        self.memory_content.setPlainText(str(memory["content"]))
        self.delete_memory_button.setEnabled(True)

    def new_memory(self) -> None:
        self._selected_memory = None
        self.memory_table.clearSelection()
        self.memory_key.clear()
        self.memory_content.clear()
        self.delete_memory_button.setEnabled(False)

    def save_memory(self) -> None:
        category = self.memory_category.currentText().strip()
        key = self.memory_key.text().strip()
        content = self.memory_content.toPlainText().strip()
        if not all((category, key, content)):
            self._status("Memory needs a category, key and content.")
            return
        old_id = self._selected_memory
        old = next((item for item in self._memories if item["id"] == old_id), None)

        def save() -> Any:
            result = self.store.save_memory(category, key, content, source="user")
            # The store upserts category/key; renaming a selected item removes its old identity.
            if old and (old["category"], old["key"]) != (category, key):
                self.store.delete_memory(old_id)
            return result

        def saved(result: dict[str, Any]) -> None:
            self._selected_memory = result["id"]
            self._status("Memory saved locally")
            self.refresh()

        self._run("memory-write", save, saved)

    def delete_memory(self) -> None:
        memory_id = self._selected_memory
        if memory_id is None:
            return

        def deleted(_: Any) -> None:
            self.new_memory()
            self._status("Selected memory deleted")
            self.refresh()

        self._run("memory-write", lambda: self.store.delete_memory(memory_id), deleted)

    def export_data(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export local JARVIS data", "jarvis-export.json", "JSON (*.json)"
        )
        if not filename:
            return

        def export() -> None:
            snapshot = self.store.export()
            snapshot["workflows"] = self.workflows.export()
            if self._business:
                snapshot["business"] = self._business.export()
            Path(filename).write_text(
                json.dumps(snapshot, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )

        self._run("export", export, lambda _: self._status(f"Export saved to {filename}"))

    def load_session(self, item: Any) -> None:
        if self._transition_busy():
            return
        if "chat" in self._jobs:
            self._status("Wait for the current request before switching conversations.")
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)

        def loaded(messages: list[dict[str, Any]]) -> None:
            self.session_id = session_id
            self.conversation.clear()
            for message in messages:
                self._append_message(
                    "YOU" if message["role"] == "user" else "JARVIS", message["content"]
                )
            self._navigate(0)
            self._status("Saved conversation loaded")

        self._run("history", lambda: self.store.history(session_id, limit=200), loaded)

    def delete_session(self) -> None:
        if self._transition_busy() or "chat" in self._jobs:
            self._status(
                "Wait for the current request or conversation update before deleting saved history."
            )
            return
        item = self.session_list.currentItem()
        if not item:
            self._status("Select a saved conversation first.")
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if session_id == self.session_id and "chat" in self._jobs:
            self._status("Wait for the current request before deleting its conversation.")
            return

        def deleted(_: Any) -> None:
            if self.session_id == session_id:
                self._reset_conversation()
            self._status("Saved conversation deleted from local storage")
            self.refresh()

        delete = getattr(self.service, "delete_session", self.store.delete_session)
        self._run("history-delete", lambda: delete(session_id), deleted)

    def save_configuration(self) -> None:
        if any(name not in ("refresh", "audio-devices") for name in self._jobs):
            self._status("Finish or interrupt active work before saving settings.")
            return
        values = self.settings.model_dump()
        try:
            pronunciations = json.loads(self.pronunciation_edit.toPlainText())
            websites = json.loads(self.website_aliases_edit.toPlainText())
        except ValueError:
            self._status("Pronunciations and website aliases must be valid JSON dictionaries.")
            return
        values.update(
            provider=self.provider_choice.currentText(),
            model=self.model_edit.text().strip(),
            ollama_url=self.ollama_url_edit.text().strip(),
            cloud_allowed=self.cloud_check.isChecked(),
            save_history=self.history_check.isChecked(),
            mode=self.mode_choice.currentText(),
            allowed_roots=[
                Path(line.strip())
                for line in self.roots_edit.toPlainText().splitlines()
                if line.strip()
            ],
            request_timeout=self.timeout_spin.value(),
            max_output_tokens=self.tokens_spin.value(),
            max_requests_per_session=self.requests_spin.value(),
            speech_enabled=self.speak_check.isChecked(),
            microphone_device=self.microphone_choice.currentData(),
            speech_model=self.speech_model_edit.text().strip(),
            speech_device=self.speech_device_choice.currentText(),
            speech_compute_type=self.compute_choice.currentText(),
            speech_voice=self.voice_choice.currentText()
            if self.voice_choice.currentIndex() > 0
            else None,
            speaker_device=self.speaker_choice.currentData(),
            wake_enabled=self.wake_check.isChecked(),
            wake_phrase=self.wake_phrase_edit.text().strip(),
            input_sensitivity=self.sensitivity_spin.value(),
            vad_aggressiveness=self.vad_spin.value(),
            speech_end_silence=self.endpoint_spin.value(),
            conversation_timeout=self.followup_spin.value(),
            speech_start_timeout=self.activation_spin.value(),
            maximum_utterance_seconds=self.utterance_spin.value(),
            speech_rate=self.rate_spin.value(),
            greeting_style=self.greeting_choice.currentText(),
            timezone=self.timezone_edit.text().strip(),
            pronunciation_replacements=pronunciations,
            voice_interruption=self.interruption_check.isChecked(),
            proactive_enabled=self.proactive_check.isChecked(),
            quiet_start=self.quiet_start_spin.value(),
            quiet_end=self.quiet_end_spin.value(),
            proactive_interval_seconds=self.proactive_interval_spin.value(),
            start_with_windows=self.startup_check.isChecked(),
            minimize_to_tray=self.tray_check.isChecked(),
            reduce_motion=self.reduce_motion_check.isChecked(),
            compact_always_on_top=self.on_top_check.isChecked(),
            desktop_context_enabled=self.desktop_context_check.isChecked(),
            speaking_style=self.speaking_style_choice.currentText(),
            desktop_actions_enabled=self.desktop_actions_check.isChecked(),
            browser_enabled=self.browser_actions_check.isChecked(),
            default_browser=self.browser_choice.currentText(),
            default_search_engine=self.search_engine_choice.currentText(),
            browser_new_window=self.browser_window_check.isChecked(),
            model_action_planning=self.model_actions_check.isChecked(),
            preferred_websites=websites,
        )
        try:
            candidate = Settings.model_validate(values)
        except Exception as exc:
            self._status(f"Settings could not be saved: {exc}")
            return
        keys = {
            "OPENAI_API_KEY": self.openai_key_edit.text().strip(),
            "GEMINI_API_KEY": self.gemini_key_edit.text().strip(),
        }
        remove = {
            "OPENAI_API_KEY": self.clear_openai_key.isChecked(),
            "GEMINI_API_KEY": self.clear_gemini_key.isChecked(),
        }
        self.save_settings_button.setEnabled(False)
        from .conversation import VoiceState

        previous_voice_state = self.voice_controller.session.state
        previous_wake = self.settings.wake_enabled
        self.voice_controller.stop("disable")
        save_voice_epoch = self.voice_controller.epoch
        previous_startup = self.settings.start_with_windows

        def save() -> Settings:
            if candidate.start_with_windows != previous_startup:
                from .startup import set_start_with_windows

                set_start_with_windows(candidate.start_with_windows, candidate.data_dir)
            secrets = getattr(self.service, "secret_store", None) or SecretStore(candidate.data_dir)
            for name, value in keys.items():
                if remove[name]:
                    secrets.delete(name)
                elif value:
                    secrets.set(name, value)
            save_settings(candidate)
            for field in type(candidate).model_fields:
                setattr(self.settings, field, getattr(candidate, field))
            reconfigure = getattr(self.service, "reconfigure", None)
            if reconfigure:
                reconfigure(self.settings)
            return candidate

        def saved(_: Settings) -> None:
            self.openai_key_edit.clear()
            self.gemini_key_edit.clear()
            self.clear_openai_key.setChecked(False)
            self.clear_gemini_key.setChecked(False)
            self._voice = None
            if self._speech:
                self._speech.stop()
                if getattr(self._speech, "_tts", None):
                    self._speech._tts.deleteLater()
                self._speech = None
            self._update_privacy_label()
            self.core.set_reduce_motion(self.settings.reduce_motion)
            self.overlay_core.set_reduce_motion(self.settings.reduce_motion)
            if not self.settings.desktop_context_enabled:
                self._awareness_data = {}
                self.system_details.clear()
            self._status("Settings saved · privacy and permission folders updated")
            from .conversation import ProactivePolicy, VoiceSession

            self.voice_controller.proactive = ProactivePolicy(self.settings)
            if self.voice_controller.epoch == save_voice_epoch:
                self.voice_controller.session = VoiceSession(self.settings)
                if previous_wake == self.settings.wake_enabled and previous_voice_state in {
                    VoiceState.MUTED,
                    VoiceState.SLEEPING,
                }:
                    if previous_voice_state == VoiceState.MUTED:
                        self.voice_controller.session.mute()
                    else:
                        self.voice_controller.session.enable()
                        self.voice_controller.session.pause()
                    self.voice_controller._display()
                elif self.settings.wake_enabled:
                    self.voice_controller.schedule_restart()

        def failed(error: str) -> None:
            # Do not retain pasted credentials in a disabled form after errors.
            self.openai_key_edit.clear()
            self.gemini_key_edit.clear()
            self._status(f"Settings could not be saved: {error}")

        self._run("settings", save, saved, failed)

    def _ensure_speech(self) -> Any:
        if self._speech is None:
            from .voice import SpeechOutput

            self._speech = (
                SpeechOutput(self, output_device=self.settings.speaker_device)
                if self.settings.speaker_device
                else SpeechOutput(self)
            )
            if hasattr(self._speech, "on_finished"):
                self._speech.on_finished(self.voice_controller.speech_finished)
            engine = getattr(self._speech, "_tts", None)
            if engine is not None:
                engine.stateChanged.connect(
                    lambda state: (
                        self.voice_controller.playback_started()
                        if getattr(state, "name", "") == "Speaking"
                        else None
                    )
                )
        if not getattr(self._speech, "available", True):
            raise RuntimeError(
                getattr(self._speech, "error", None) or "Speech output is unavailable."
            )
        return self._speech

    def open_sound_settings(self) -> None:
        if sys.platform != "win32":
            self._status("Choose your output device in your operating system's sound settings.")
        elif not QDesktopServices.openUrl(QUrl("ms-settings:sound")):
            self._status("Windows sound settings could not be opened.")

    def _speech_toggled(self, enabled: bool) -> None:
        if enabled:
            try:
                self._ensure_speech()
            except Exception as exc:
                self._status(str(exc))
                self.speak_check.blockSignals(True)
                self.speak_check.setChecked(False)
                self.speak_check.blockSignals(False)
        elif self._speech:
            self._speech.stop()

    def _speak(self, text: str) -> None:
        self.voice_controller._speech_requested_at = time.monotonic()
        try:
            speech = self._ensure_speech()
            if self.voice_choice.currentIndex() > 0:
                speech.set_voice(self.voice_choice.currentText())
            if hasattr(speech, "set_rate"):
                speech.set_rate(self.settings.speech_rate)
                speech.speak(text, replacements=self.settings.pronunciation_replacements)
            else:
                speech.speak(text)
            if not getattr(speech, "speaking", True):
                self.voice_controller.speech_finished()
        except Exception as exc:
            self._status(f"Reply received. Speech unavailable: {exc}")
            self.voice_controller.speech_finished()

    def refresh_audio_devices(self) -> None:
        if self._transition_busy():
            return
        if "record" in self._jobs:
            self._status("Finish recording and transcription before refreshing devices.")
            return
        if self.voice_controller.active:
            self._status("Pause hands-free listening before refreshing audio devices.")
            return
        try:
            from .voice import SpeechOutput

            if hasattr(SpeechOutput, "output_devices"):
                outputs = SpeechOutput.output_devices()
                current_output = self.speaker_choice.currentData()
                self.speaker_choice.clear()
                self.speaker_choice.addItem("Windows default output", None)
                for output in outputs:
                    self.speaker_choice.addItem(output["name"], output["id"])
                index = self.speaker_choice.findData(current_output)
                if current_output and index < 0:
                    self.speaker_choice.addItem("Saved output device disconnected", current_output)
                    index = self.speaker_choice.count() - 1
                self.speaker_choice.setCurrentIndex(max(0, index))
            voices = self._ensure_speech().voices()
            current_voice = self.voice_choice.currentText()
            self.voice_choice.clear()
            self.voice_choice.addItem("System default")
            self.voice_choice.addItems(voices)
            if current_voice in voices:
                self.voice_choice.setCurrentText(current_voice)
        except Exception as exc:
            self._status(f"Speech output: {exc}")

        def devices() -> list[dict[str, Any]]:
            from .voice import VoiceInput

            if self._voice is None:
                self._voice = VoiceInput(self.settings)
            return self._voice.devices()

        def loaded(items: list[dict[str, Any]]) -> None:
            current = self.microphone_choice.currentData()
            self.microphone_choice.clear()
            self.microphone_choice.addItem("System default", None)
            for device in items:
                self.microphone_choice.addItem(str(device["name"]), device["id"])
            index = self.microphone_choice.findData(current)
            self.microphone_choice.setCurrentIndex(max(index, 0))
            self._status(f"Found {len(items)} microphone device(s) · microphone remains off")

        self._run("audio-devices", devices, loaded)

    def start_recording(self) -> None:
        if self._transition_busy():
            return
        if self.voice_controller.active:
            self.voice_controller.stop()
            self._status("Hands-free paused. Hold to talk once its microphone closes.")
            return
        if (
            any(name in self._jobs for name in ("record", "chat", "audio-devices"))
            or self._closing
            or self._stopped
        ):
            self._status("Finish the active request before recording.")
            return
        self._record_release = threading.Event()
        self._record_cancel = threading.Event()
        release, cancel = self._record_release, self._record_cancel
        self._record_stage = "starting"
        self._shown_record_stage = "idle"
        self.mic_button.setText("Starting microphone…")
        self._audio_status_timer.start()
        self._status("Microphone requested · hold to record (maximum 30 seconds)")
        device = self.microphone_choice.currentData()

        def record() -> str | None:
            from .voice import VoiceInput

            if self._voice is None:
                self._voice = VoiceInput(self.settings)
            voice = self._voice
            try:
                if cancel.is_set():
                    return None
                voice.start(device=device)
                self._record_stage = "recording"
                deadline = time.monotonic() + 30
                while not release.wait(0.05):
                    if (
                        cancel.is_set()
                        or time.monotonic() >= deadline
                        or not getattr(voice, "recording", True)
                    ):
                        break
                if cancel.is_set():
                    self._record_stage = "stopping"
                    voice.cancel()
                    return None
                self._record_stage = "stopping"
                audio = voice.stop()
                self._record_stage = "transcribing"
                if cancel.is_set():
                    return None
                text = voice.transcribe(audio)
                return None if cancel.is_set() else text
            except Exception:
                voice.cancel()
                raise

        def transcribed(text: str | None) -> None:
            if text:
                self.composer.setPlainText(text)
                self.composer.setFocus()
                self._status("Transcription ready · review and send when you choose")
            else:
                self._status("Recording finished · no transcription or capture cancelled")

        self._run(
            "record",
            record,
            transcribed,
            lambda error: self._status(f"Microphone / transcription: {error}"),
        )

    def stop_recording(self) -> None:
        if "record" in self._jobs:
            self._record_release.set()
            self.mic_button.setEnabled(False)
            self._status("Microphone stopping · local transcription follows")

    def _update_audio_status(self) -> None:
        stage = self._record_stage
        if stage == self._shown_record_stage or self._closing or self._record_cancel.is_set():
            return
        self._shown_record_stage = stage
        labels = {
            "starting": ("Starting microphone…", "Microphone requested · hold to record"),
            "recording": (
                "Recording · release to transcribe",
                "RECORDING · release to stop (maximum 30 seconds)",
            ),
            "stopping": ("Stopping microphone…", "Stopping microphone · your audio stays local"),
            "transcribing": ("Transcribing · mic off", "Microphone off · transcribing locally…"),
        }
        if stage in labels:
            button_text, status_text = labels[stage]
            self.mic_button.setText(button_text)
            self._status(status_text)

    def toggle_compact(self) -> None:
        self._compact = not self._compact
        if self._compact:
            self._normal_geometry = self.saveGeometry()
            self.sidebar.hide()
            self.sidebar_scroll.hide()
            self.assistant_heading.hide()
            self.new_conversation_button.hide()
            self._main_layout.setContentsMargins(16, 12, 16, 10)
            self._main_layout.setSpacing(8)
            self.expand_button.show()
            self._navigate(0)
            self.setMinimumSize(430, 530)
            self.setWindowFlag(
                Qt.WindowType.WindowStaysOnTopHint, self.settings.compact_always_on_top
            )
            self.presence_details.hide()
            self.conversation.hide()
            self.compact_response.show()
            self.composer.setFixedHeight(56)
            self.core.setMaximumHeight(110)
            self.speak_check.hide()
            self.listen_button.hide()
            self.resize(460, 550)
        else:
            self.sidebar.show()
            self.sidebar_scroll.show()
            self.assistant_heading.show()
            self.new_conversation_button.show()
            self._main_layout.setContentsMargins(28, 24, 28, 18)
            self._main_layout.setSpacing(16)
            self.expand_button.hide()
            self.setMinimumSize(760, 560)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
            self.presence_details.show()
            self.conversation.show()
            self.compact_response.hide()
            self.composer.setFixedHeight(96)
            self.core.setMaximumHeight(220)
            self.speak_check.show()
            self.listen_button.show()
            if self._normal_geometry:
                self.restoreGeometry(self._normal_geometry)
        self.show()

    def _build_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("JARVIS · microphone off until you hold to talk")
        menu = QMenu(self)
        for title, callback in (
            ("Show JARVIS", self.show_from_tray),
            ("Compact assistant", self.toggle_compact),
            ("Pause listening", lambda: self.voice_controller.stop()),
            ("Resume listening", lambda: self.voice_controller.start()),
            ("Mute voice and microphone", lambda: self.voice_controller.mute()),
            (
                "View voice status",
                lambda: (self.show_from_tray(), self._status(self.voice_status.text())),
            ),
            ("Emergency stop", self.emergency_stop),
            ("Quit", self.close),
        ):
            action = QAction(title, menu)
            action.triggered.connect(callback)
            menu.addAction(action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: (
                self.show_from_tray()
                if reason == QSystemTrayIcon.ActivationReason.Trigger
                else None
            )
        )
        self.tray.show()
        hide_action = QAction("Hide to tray", self)
        hide_action.triggered.connect(self.hide)
        self.menuBar().addAction(hide_action)

    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._closing and not self._jobs:
            self.interrupt()
            if self.tray:
                self.tray.hide()
            event.accept()
            return
        event.ignore()
        if self._closing:
            return
        self.interrupt()
        self.voice_controller.stop("disable")
        self._stopped = True
        stop = getattr(self.service, "emergency_stop", self.engine.emergency_stop)
        self._run("shutdown-stop", stop)
        self._closing = True
        self.ambient_overlay.hide()
        self._presence_timer.stop()
        self._system_timer.stop()
        self._action_activity_timer.stop()
        # The pooled runnables retain their own signals and never destroy a live QThread.
        self.centralWidget().setEnabled(False)
        self._close_deadline = time.monotonic() + max(5.0, self.settings.request_timeout + 5)
        self._status("Closing safely · waiting for active work to stop")
        self._shutdown_timer.start()

    def _poll_shutdown(self) -> None:
        if not self._closing:
            return
        if not self._jobs:
            self._shutdown_timer.stop()
            self.close()
        elif time.monotonic() >= self._close_deadline:
            # Native speech inference cannot safely be force-killed. Return control
            # instead of hanging close or tearing down objects used by a worker.
            self._shutdown_timer.stop()
            self._closing = False
            self._presence_timer.start()
            self._system_timer.start()
            self._action_activity_timer.start()
            self.centralWidget().setEnabled(True)
            self.send_button.setEnabled("chat" not in self._jobs)
            self.mic_button.setEnabled("record" not in self._jobs)
            self._status(
                "Background work is still stopping. The window remains open safely; retry Quit when it finishes."
            )


def run_desktop(service: Any, settings: Settings, store: Any, engine: Any) -> int:
    """Run one desktop application; storage lifecycle belongs to the caller."""
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("JARVIS")
    app.setOrganizationName("Project JARVIS")
    window = MainWindow(service, settings, store, engine)
    window.show()
    QTimer.singleShot(0, window.run_health_check)
    if settings.minimize_to_tray and window.tray:
        QTimer.singleShot(0, window.hide)
    return app.exec()
