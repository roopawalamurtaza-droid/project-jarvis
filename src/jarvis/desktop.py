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
    QPainter,
    QPixmap,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
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
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
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
    def __init__(self, action: Callable[[], Any]):
        super().__init__()
        self.action = action
        self.signals = _JobSignals()
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
        from .health import build_identity

        self.build_info = build_identity()
        self.health_result = {"backend": "Health check pending", "speech_model": "Not checked"}
        self.setWindowTitle("JARVIS · Personal workspace")
        self.setWindowIcon(_icon())
        self.resize(1180, 800)
        self.setMinimumSize(760, 560)
        self.setStyleSheet(STYLE)
        self._build()
        self._build_tray()
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setInterval(100)
        self._shutdown_timer.timeout.connect(self._poll_shutdown)
        self._audio_status_timer = QTimer(self)
        self._audio_status_timer.setInterval(100)
        self._audio_status_timer.timeout.connect(self._update_audio_status)
        self._append_message(
            "JARVIS",
            "Your workspace is ready. Choose a provider in Settings, then type a message. "
            "Desktop actions appear in Activity with their actual results. "
            "Enable hands-free listening in Settings, or hold the microphone button to talk.",
        )
        from .voice_controller import VoiceController

        self.voice_controller = VoiceController(self)
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
        self.sidebar.setFixedWidth(205)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(16, 24, 16, 18)
        side.addWidget(_label("JARVIS", "Brand"))
        side.addWidget(_label("PERSONAL WORKSPACE", "Muted"))
        side.addSpacing(27)
        self.nav: list[QPushButton] = []
        for index, title in enumerate(("Assistant", "Activity", "Memory", "Audit", "Settings")):
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
        side.addWidget(_button("Compact assistant", self.toggle_compact))
        side.addWidget(_button("Emergency stop", self.emergency_stop, kind="Danger"))
        outer.addWidget(self.sidebar)
        main = QVBoxLayout()
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
        main.addWidget(self.pages, 1)
        main.addWidget(self.status_label)
        outer.addLayout(main, 1)
        self._navigate(0)
        self._update_privacy_label()

    def _assistant_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        tools.addWidget(_label("A focused space to think and act", "Muted"))
        tools.addStretch()
        tools.addWidget(_button("New conversation", self.new_conversation))
        layout.addLayout(tools)
        self.conversation = QTextEdit()
        self.conversation.setObjectName("Conversation")
        self.conversation.setReadOnly(True)
        self.conversation.setAcceptRichText(False)
        layout.addWidget(self.conversation, 1)
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
        self.interrupt_button = _button("Interrupt", self.interrupt)
        self.interrupt_button.setObjectName("Interrupt")
        buttons.addWidget(self.interrupt_button)
        self.send_button = _button("Send", self.send_message, kind="Primary")
        self.send_button.setObjectName("Primary")
        buttons.addWidget(self.send_button)
        composer_layout.addLayout(buttons)
        self.voice_status = _label("Voice: Idle · microphone off", "Muted", True)
        composer_layout.addWidget(self.voice_status)
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
        self.tool_choice.currentIndexChanged.connect(self._tool_changed)
        action_row.addWidget(self.tool_choice)
        self.tool_path = QLineEdit()
        self.tool_path.setPlaceholderText("Full path inside a permitted folder")
        action_row.addWidget(self.tool_path, 1)
        self.tool_app = QComboBox()
        self.tool_app.addItems(["notepad", "calculator", "vscode", "chrome"])
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
        layout.addWidget(split, 1)
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
        return page

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
        self.title_label.setText(("Assistant", "Activity", "Memory", "Audit", "Settings")[index])
        for i, button in enumerate(self.nav):
            button.setChecked(i == index)

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

    def _run(
        self,
        name: str,
        action: Callable[[], Any],
        success: Callable[[Any], None] | None = None,
        failure: Callable[[str], None] | None = None,
    ) -> _Job | None:
        if name in self._jobs or self._closing:
            return None
        job = _Job(action)
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
        return job

    def _finish_job(self, name: str) -> None:
        self._jobs.pop(name, None)
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
        if self._closing:
            self._poll_shutdown()

    def send_message(self) -> bool:
        text = self.composer.toPlainText().strip()
        if not text or "chat" in self._jobs or self._closing:
            return False
        if self._transition_busy():
            return False
        if self._stopped:
            self._status("Emergency stop is active. Resume in Activity before sending.")
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
        self._status(f"Waiting for {self.settings.provider} · Interrupt cancels this request")
        cancel = threading.Event()
        self._chat_cancel = cancel
        session = self.session_id

        def succeeded(result: dict[str, Any]) -> None:
            self.session_id = result.get("session_id", self.session_id)
            if cancel.is_set():
                self._status("Request interrupted. A provider may finish its in-flight request.")
                return
            answer = str(result.get("text", ""))
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
        self._status("Interrupted · active requests stop at the next safe boundary")

    def _tool_changed(self) -> None:
        app = self.tool_choice.currentData() == "open_app"
        self.tool_app.setVisible(app)
        self.tool_path.setVisible(not app)

    def submit_action(self) -> None:
        if self._transition_busy():
            return
        tool = self.tool_choice.currentData()
        args = (
            {"app": self.tool_app.currentText()}
            if tool == "open_app"
            else {"path": self.tool_path.text().strip()}
        )
        if tool != "open_app" and not args["path"]:
            self._status("Enter a full path for this action.")
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
        self._status(f"Action {result.get('state', 'updated')} · review Activity for evidence")
        self.refresh()
        self.voice_controller.task_event(result)

    def _selected_task(self) -> dict[str, Any] | None:
        row = self.task_table.currentRow()
        return self._tasks[row] if 0 <= row < len(self._tasks) else None

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
        self._run(
            "task-operation", lambda: getattr(self.engine, operation)(task_id), self._task_result
        )

    def emergency_stop(self) -> None:
        self._stopped = True
        self.interrupt()
        self.voice_controller.stop("mute")
        self._select_task()
        self._status("EMERGENCY STOP · cancelling pending actions and voice")
        stop = getattr(self.service, "emergency_stop", self.engine.emergency_stop)
        self._run("emergency-stop", stop, lambda _: self.refresh())

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

        def fetch() -> dict[str, Any]:
            return {
                "tasks": self.store.tasks(),
                "memories": self.store.memories(query),
                "audits": self.store.audits(limit=100),
                "sessions": self.store.sessions(),
            }

        self._run("refresh", fetch, self._show_data)

    def _show_data(self, data: dict[str, Any]) -> None:
        selected_task = self._selected_task()
        task_id = self._last_task_id or (selected_task.get("id") if selected_task else None)
        self._last_task_id = None
        self._tasks = [
            self._live_task_results.get(task["id"], task)
            if self._live_task_results.get(task["id"], {}).get("state") == task["state"]
            else task
            for task in data["tasks"]
        ]
        self.task_table.blockSignals(True)
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
            Path(filename).write_text(
                json.dumps(self.store.export(), indent=2, ensure_ascii=False, default=str),
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
        except ValueError:
            self._status(
                'Pronunciations must be a JSON dictionary, for example {"JARVIS": "Jarvis"}.'
            )
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
            self.expand_button.show()
            self._navigate(0)
            self.setMinimumSize(430, 380)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self.resize(500, 570)
        else:
            self.sidebar.show()
            self.expand_button.hide()
            self.setMinimumSize(760, 560)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
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
