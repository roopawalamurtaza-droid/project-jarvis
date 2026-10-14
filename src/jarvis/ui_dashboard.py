"""Reference-composed intelligence cards backed only by measured application data.

The widget performs no I/O or actions. Its owner supplies worker snapshots and
handles the exact task-ID signals through the existing authorization engine.
"""

from __future__ import annotations

import math
from collections import deque

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .ui_shell import make_icon

ACTIVE_STATES = frozenset({"queued", "planning", "running", "verifying", "awaiting_approval"})
MAX_RECORDS = 256
MAX_VISIBLE = 4
MAX_HISTORY = 60

TOOL_LABELS = {
    "open_app": "Open application",
    "focus_app": "Focus application",
    "open_folder": "Open folder",
    "open_website": "Open website",
    "search_web": "Web search",
    "list_files": "List files",
    "list_directory": "List files",
    "read_file": "Read file",
    "write_file": "Write file",
    "create_directory": "Create folder",
    "list_applications": "Application library",
    "get_system_status": "System measurements",
}

_STYLE = """
QScrollArea#IntelligenceDashboard, QWidget#DashboardContents {
 background:transparent; border:0; }
QFrame#DashboardCard {
 background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #081826,stop:1 #04111b);
 border:1px solid #213c4f; border-radius:11px; }
QFrame#DashboardApprovalCard {
 background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #1a1421,stop:1 #0a121b);
 border:1px solid #663047; border-radius:11px; }
QFrame#DashboardCard QWidget, QFrame#DashboardApprovalCard QWidget {
 background:transparent; }
QLabel { color:#c7dce9; background:transparent; border:0; font-size:11px; }
QLabel#DashboardTitle { color:#d9eaf4; font-size:13px; font-weight:600; }
QLabel#DashboardGlyph { color:#79d2f5; font-size:17px; }
QLabel#DashboardMuted { color:#7690a5; font-size:10px; }
QLabel#DashboardBadge { color:#61c6ed; background:#092a3d; border-radius:7px;
 padding:2px 8px; font-size:10px; }
QPushButton#DashboardDetails { color:#7b9bb0; border:0; background:transparent;
 padding:0; min-height:14px; min-width:13px; font-size:17px; }
QPushButton#DashboardDetails:hover { color:#52d7ff; }
QFrame#DashboardRow { border:0; background:transparent; border-radius:5px; }
QFrame#DashboardRow:hover { background:#0b2434; }
QProgressBar { background:#173043; border:0; border-radius:2px; min-height:3px;
 max-height:3px; color:transparent; }
QProgressBar::chunk { background:#36bdf0; border-radius:2px; }
QFrame#DashboardApproval { border:1px solid #70394a; border-radius:7px;
 background:#1d1420; }
QPushButton#DashboardApprove { color:#062238; background:#26bcf2; border:1px solid #58d5ff;
 padding:3px 11px; border-radius:5px; font-size:10px; min-height:15px; }
QPushButton#DashboardDeny { color:#c7b4ca; background:#281d2d; border:1px solid #59445d;
 padding:3px 11px; border-radius:5px; font-size:10px; min-height:15px; }
QPushButton#DashboardApprove:disabled, QPushButton#DashboardDeny:disabled {
 color:#76808c; background:#18202a; border-color:#293646; }
"""


def _text(value, limit=160) -> str:
    """Bound untrusted display strings, preserve text literally, remove line breaks."""
    if not isinstance(value, (str, int, float)) or type(value) is bool:
        return ""
    return str(value).replace("\x00", "").replace("\r", " ").replace("\n", " ")[:limit]


def _identity(value):
    # Never truncate an authorization ID into a different requested task.
    return (
        value
        if isinstance(value, str)
        and 0 < len(value) <= 128
        and not any(ord(character) < 32 for character in value)
        else ""
    )


def _number(value, *, maximum=None):
    if type(value) not in {int, float} or value < 0 or value > 2**53:
        return None
    if not math.isfinite(value):
        return None
    if maximum is not None and value > maximum:
        return None
    return value


def _bytes(value) -> str:
    value = _number(value)
    if value is None:
        return "—"
    for suffix, scale in (("TB", 1024**4), ("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if value >= scale:
            return f"{value / scale:.1f} {suffix}"
    return f"{value:.0f} B"


def _duration(value) -> str:
    value = _number(value)
    if value is None:
        return "—"
    if value >= 60:
        return f"{value / 60:.1f}m"
    return f"{value:.1f}s"


def _label(value="", *, muted=False, parent=None):
    label = QLabel(_text(value), parent)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setObjectName("DashboardMuted" if muted else "DashboardText")
    label.setMinimumWidth(0)
    return label


def _icon_label(name, *, size=18, color="#79d2f5", parent=None):
    label = _label(parent=parent)
    label.setPixmap(make_icon(name, color, size).pixmap(QSize(size, size)))
    label.setFixedSize(size, size)
    return label


class _ElidedLabel(QLabel):
    """Keep long external labels inside the fixed reference column."""

    def __init__(self, value="", parent=None):
        super().__init__(parent)
        self._source = ""
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(value)

    def setText(self, value):
        self._source = _text(value, 500)
        self.setToolTip(self._source)
        self._elide()

    def _elide(self):
        super().setText(
            self.fontMetrics().elidedText(self._source, Qt.TextElideMode.ElideRight, self.width())
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()


class SparklineMetric(QFrame):
    """A bounded real measurement history; unavailable samples are visible gaps."""

    def __init__(self, title, color, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.history: deque[float | None] = deque(maxlen=MAX_HISTORY)
        self.setMinimumSize(72, 58)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 19)
        layout.setSpacing(0)
        self.title_label = _label(title, muted=True, parent=self)
        self.value_label = _label("—", parent=self)
        self.value_label.setStyleSheet("font-size:17px; color:#d4e9f6;")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        self.setAccessibleName(f"Measured {title}")

    def set_value(self, value, *, append=True, reason=None):
        value = _number(value, maximum=100)
        if append:
            self.history.append(float(value) if value is not None else None)
        self.value_label.setText(f"{value:.0f}%" if value is not None else "—")
        self.setToolTip(_text(reason, 300) if value is None else "Measured percentage")
        self.setAccessibleDescription(
            f"{value:.1f} percent" if value is not None else "Measurement unavailable"
        )
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        background = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
        background.setColorAt(0, QColor("#071923"))
        background.setColorAt(1, QColor("#041019"))
        painter.setBrush(background)
        painter.setPen(QPen(QColor("#183b4c"), 1))
        painter.drawRoundedRect(bounds, 5, 5)
        graph = QRectF(7, self.height() - 22, max(1, self.width() - 14), 17)
        samples = list(self.history)
        if samples:
            path = QPainterPath()
            started = False
            for index, value in enumerate(samples):
                if value is None:
                    started = False
                    continue
                x = graph.left() + graph.width() * index / max(1, len(samples) - 1)
                y = graph.bottom() - graph.height() * value / 100
                if started:
                    path.lineTo(x, y)
                else:
                    path.moveTo(x, y)
                    painter.setPen(QPen(self.color, 2))
                    painter.drawPoint(QPointF(x, y))
                    started = True
            glow = QColor(self.color)
            glow.setAlpha(34)
            painter.setPen(QPen(glow, 5))
            painter.drawPath(path)
            painter.setPen(QPen(self.color, 1.5))
            painter.drawPath(path)
        painter.end()


class _DashboardCard(QFrame):
    def __init__(self, title, icon_name, *, approval=False, parent=None):
        super().__init__(parent)
        self.setObjectName("DashboardApprovalCard" if approval else "DashboardCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(9, 7, 9, 8)
        self.layout.setSpacing(5)
        header = QHBoxLayout()
        header.setSpacing(7)
        icon = _icon_label(icon_name, color="#de8798" if approval else "#79d2f5", parent=self)
        icon.setObjectName("DashboardGlyph")
        title_label = _ElidedLabel(title, self)
        title_label.setObjectName("DashboardTitle")
        self.badge = _label(parent=self)
        self.badge.setObjectName("DashboardBadge")
        self.badge.setMaximumWidth(104)
        self.details = QPushButton(self)
        self.details.setIcon(make_icon("expand", "#7b9bb0", 12))
        self.details.setIconSize(QSize(12, 12))
        self.details.setObjectName("DashboardDetails")
        self.details.setAccessibleName(f"Open {title.lower()} details")
        self.details.setFixedWidth(16)
        header.addWidget(icon)
        header.addWidget(title_label, 1)
        header.addWidget(self.badge)
        header.addWidget(self.details)
        self.layout.addLayout(header)
        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(5)
        self.layout.addWidget(self.body)


class _ActivityRow(QFrame):
    selected = Signal(str)

    def __init__(self, title, detail, identity="", *, progress=None, state="running", parent=None):
        super().__init__(parent)
        self.identity = identity
        self.setObjectName("DashboardRow")
        self.setMinimumHeight(36)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(7)
        symbol = "check" if state == "completed" else "close" if state == "failed" else "spark"
        color = "#30cda6" if state == "completed" else "#ed8c9a" if state == "failed" else "#3ab9e9"
        icon = _icon_label(symbol, size=19, color=color, parent=self)
        layout.addWidget(icon)
        text = QVBoxLayout()
        text.setSpacing(1)
        self.title_label = _ElidedLabel(title, self)
        self.detail_label = _ElidedLabel(detail, self)
        self.detail_label.setObjectName("DashboardMuted")
        text.addWidget(self.title_label)
        text.addWidget(self.detail_label)
        layout.addLayout(text, 1)
        self.progress_bar = None
        self._indeterminate = False
        if progress is not False:
            right = QVBoxLayout()
            right.setContentsMargins(0, 0, 0, 0)
            self.progress_bar = QProgressBar(self)
            self.progress_bar.setTextVisible(False)
            self.progress_bar.setFixedWidth(88)
            progress = _number(progress, maximum=100)
            if progress is None:
                self._indeterminate = True
                self.progress_bar.setRange(0, 0)
                caption = _label("—", muted=True, parent=self)
            else:
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(round(progress))
                caption = _label(f"{progress:.0f}%", muted=True, parent=self)
            caption.setAlignment(Qt.AlignmentFlag.AlignRight)
            right.addWidget(caption)
            right.addWidget(self.progress_bar)
            layout.addLayout(right)
        if identity:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_text(detail, 300))

    def set_reduce_motion(self, reduced):
        if self.progress_bar is not None and self._indeterminate:
            # A static empty rail with the unchanged unknown caption replaces
            # Qt's busy animation. It does not report a zero-percent estimate.
            self.progress_bar.setRange(0, 1 if reduced else 0)
            if reduced:
                self.progress_bar.setValue(0)
            self.progress_bar.setAccessibleDescription("Progress is unavailable")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.identity:
            self.selected.emit(self.identity)
        super().mouseReleaseEvent(event)


class _ExecutionRow(QFrame):
    selected = Signal(str)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.identity = _identity(task.get("id"))
        self.setObjectName("DashboardRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)
        state = _text(task.get("state"), 30)
        symbol = "check" if state == "completed" else "close" if state == "failed" else "spark"
        color = "#34c9a8" if state == "completed" else "#ed8c9a" if state == "failed" else "#50bcef"
        icon = _icon_label(symbol, size=17, color=color, parent=self)
        self.title_label = _ElidedLabel(_tool_title(task), self)
        self.state_label = _label(_state_label(state), muted=True, parent=self)
        if state == "completed":
            self.state_label.setStyleSheet("color:#30bd9a; font-size:10px;")
        elif state == "failed":
            self.state_label.setStyleSheet("color:#f19ba5; font-size:10px;")
        self.duration_label = _label(
            _duration(task.get("duration_seconds")), muted=True, parent=self
        )
        self.duration_label.setMinimumWidth(31)
        layout.addWidget(icon)
        layout.addWidget(self.title_label, 1)
        layout.addWidget(self.state_label)
        layout.addWidget(self.duration_label)
        layout.addWidget(_icon_label("expand", size=11, color="#7893a8", parent=self))
        self.setMinimumHeight(22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        evidence = task.get("error")
        result = task.get("result")
        if not evidence and isinstance(result, dict):
            evidence = result.get("detail")
        self.setToolTip(_text(evidence or _state_label(state), 300))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.identity:
            self.selected.emit(self.identity)
        super().mouseReleaseEvent(event)


def _state_label(state):
    return {"awaiting_approval": "Approval", "verifying": "Verifying", "queued": "Queued"}.get(
        state, _text(state, 30).replace("_", " ").capitalize() or "Unknown"
    )


def _tool_title(task):
    tool = _text(task.get("tool"), 100)
    return TOOL_LABELS.get(tool, tool.replace("_", " ").capitalize() or "Requested task")


def _task_detail(task):
    args = task.get("arguments")
    args = args if isinstance(args, dict) else {}
    target = next(
        (args[key] for key in ("app", "query", "target", "url", "path") if args.get(key)), None
    )
    return _text(target or task.get("error") or _state_label(task.get("state", "")), 160)


def _steps(run):
    steps = run.get("steps")
    return steps[:64] if isinstance(steps, list) else []


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.deleteLater()


class IntelligenceDashboard(QScrollArea):
    """Five reference-shaped cards, updated from already-authorized local data."""

    task_selected = Signal(str)
    approve_requested = Signal(str)
    deny_requested = Signal(str)
    details_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("IntelligenceDashboard")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumWidth(280)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(_STYLE)
        self.contents = QWidget(self)
        self.contents.setObjectName("DashboardContents")
        self.stack = QVBoxLayout(self.contents)
        self.stack.setContentsMargins(0, 0, 1, 0)
        self.stack.setSpacing(9)
        self.setWidget(self.contents)
        self.active_card = self._card("Active Tasks", "mission", "tasks")
        self.active_card.setMinimumHeight(167)
        self.system_card = self._card("System Status", "system", "system")
        self.ai_card = self._card("AI Status", "assistant", "ai")
        self.tools_card = self._card("Tool Execution", "settings", "tools")
        self.tools_card.setMinimumHeight(110)
        self.approvals_card = self._card(
            "Approval Requests", "approval", "approvals", approval=True
        )
        self.approvals_card.setMinimumHeight(105)
        self.stack.addStretch(1)
        self.active_badge = self.active_card.badge
        self.system_badge = self.system_card.badge
        self.ai_badge = self.ai_card.badge
        self.approval_badge = self.approvals_card.badge
        self.metrics = {}
        metric_row = QHBoxLayout()
        metric_row.setSpacing(6)
        for key, title, color in (
            ("cpu", "CPU", "#18c7b2"),
            ("ram", "RAM", "#1ba8ef"),
            ("disk", "Disk", "#9166e9"),
        ):
            tile = SparklineMetric(title, color, self.system_card.body)
            self.metrics[key] = tile
            metric_row.addWidget(tile)
        self.system_card.body_layout.addLayout(metric_row)
        resources = QHBoxLayout()
        resources.setSpacing(4)
        self.temperature_label = _label("—", parent=self.system_card.body)
        self.disk_label = _label("—", parent=self.system_card.body)
        self.network_label = _label("—", parent=self.system_card.body)
        for value, title in (
            (self.temperature_label, "CPU Temp"),
            (self.disk_label, "System volume"),
            (self.network_label, "Network RX + TX"),
        ):
            column = QVBoxLayout()
            column.setSpacing(1)
            column.addWidget(value)
            caption = _ElidedLabel(title, self.system_card.body)
            caption.setObjectName("DashboardMuted")
            column.addWidget(caption)
            resources.addLayout(column, 1)
        self.system_card.body_layout.addLayout(resources)
        ai_body = QHBoxLayout()
        ai_body.setSpacing(10)
        self.ai_icon = _icon_label("assistant", size=35, color="#91cbea", parent=self.ai_card.body)
        ai_body.addWidget(self.ai_icon)
        model_box = QVBoxLayout()
        model_box.setSpacing(1)
        model_box.addWidget(_label("Model", muted=True, parent=self.ai_card.body))
        self.model_label = _ElidedLabel("—", self.ai_card.body)
        self.model_label.setStyleSheet("font-size:13px; color:#e1edf7;")
        self.provider_label = _ElidedLabel("—", self.ai_card.body)
        self.provider_label.setObjectName("DashboardMuted")
        model_box.addWidget(self.model_label)
        model_box.addWidget(self.provider_label)
        ai_body.addLayout(model_box, 1)
        response_box = QVBoxLayout()
        response_box.setSpacing(6)
        self.latency_label = _ElidedLabel("Response   —", self.ai_card.body)
        self.usage_label = _ElidedLabel("Tokens      —", self.ai_card.body)
        self.latency_label.setMinimumWidth(112)
        self.usage_label.setMinimumWidth(112)
        response_box.addWidget(self.latency_label)
        response_box.addWidget(self.usage_label)
        ai_body.addLayout(response_box)
        self.ai_card.body_layout.addLayout(ai_body)
        self.task_rows: list[_ActivityRow] = []
        self.execution_rows: list[_ExecutionRow] = []
        self.approval_rows: list[QFrame] = []
        self._activity_signature = None
        self._reduce_motion = False
        self._last_sampled_at = None
        self.update_activity([], [], [], [])
        self.update_system({})
        self.update_ai("—", "—", "Not checked", None, {})

    def sizeHint(self):
        return QSize(372, 690)

    def _card(self, title, icon_name, section, *, approval=False):
        card = _DashboardCard(title, icon_name, approval=approval, parent=self.contents)
        card.details.clicked.connect(
            lambda _checked=False, key=section: self.details_requested.emit(key)
        )
        self.stack.addWidget(card)
        return card

    def update_activity(self, jobs, tasks, action_runs, workflow_runs, stopped=False):
        tasks = [task for task in list(tasks)[:MAX_RECORDS] if isinstance(task, dict)]
        actions = [run for run in list(action_runs)[:MAX_RECORDS] if isinstance(run, dict)]
        workflows = [run for run in list(workflow_runs)[:MAX_RECORDS] if isinstance(run, dict)]
        jobs = [_text(job, 80) for job in list(jobs)[:32]]
        # Compare only bounded displayed fields. Tool result bodies can include
        # long file content and must never be copied into this UI signature.
        signature = (
            tuple(jobs),
            tuple(
                (
                    _identity(task.get("id")),
                    _tool_title(task),
                    _task_detail(task),
                    _text(task.get("state"), 30),
                    _duration(task.get("duration_seconds")),
                    _text(task.get("error"), 300),
                )
                for task in tasks
            ),
            tuple(
                (
                    _identity(run.get("id")),
                    _text(run.get("name"), 120),
                    _text(run.get("state"), 30),
                    _text(run.get("step_index"), 8),
                    tuple(
                        (_text(step.get("state"), 30), _identity(step.get("task_id")))
                        for step in _steps(run)
                        if isinstance(step, dict)
                    ),
                )
                for run in actions + workflows
            ),
            bool(stopped),
        )
        if signature == self._activity_signature:
            return
        self._activity_signature = signature
        active_tasks = [task for task in tasks if task.get("state") in ACTIVE_STATES]
        active_actions = [run for run in actions if run.get("state") in ACTIVE_STATES]
        active_workflows = [run for run in workflows if run.get("state") in ACTIVE_STATES]
        referenced = {
            step.get("task_id")
            for run in active_actions
            for step in _steps(run)[:6]
            if isinstance(step, dict)
        }
        referenced.update(run.get("task_id") for run in active_workflows)
        ungrouped = [task for task in active_tasks if task.get("id") not in referenced]
        records = []
        for run, is_action in [(run, True) for run in active_actions] + [
            (run, False) for run in active_workflows
        ]:
            steps = _steps(run)
            if is_action:
                finished = sum(
                    isinstance(step, dict) and step.get("state") == "completed"
                    for step in steps[:64]
                )
            else:
                index = run.get("step_index", 0)
                finished = min(max(index, 0), len(steps)) if type(index) is int else 0
            progress = 100 * finished / len(steps) if steps else None
            identity = _identity(run.get("id"))
            records.append(
                (
                    _text(run.get("name") or "Requested actions"),
                    _state_label(run.get("state")),
                    identity,
                    progress,
                    "run",
                )
            )
        for task in ungrouped:
            records.append(
                (_tool_title(task), _task_detail(task), _identity(task.get("id")), None, "task")
            )
        # UI data refresh and measurement jobs are not user tasks. Only active
        # conversation/audio requests get a visible indeterminate activity row.
        user_jobs = [
            job
            for job in jobs
            if job
            in {
                "chat",
                "voice-chat",
                "voice",
                "transcribe",
                "speak",
                "record",
                "speech",
                "action",
                "tool-submit",
                "workflow-run",
                "task-operation",
            }
        ]
        if not records:
            records.extend(
                (job.replace("-", " ").capitalize(), "Working…", "", None, "job")
                for job in user_jobs
            )
        count = len(records)
        self.active_badge.setText(
            "Stopped" if stopped else f"{count} active" if count else "Standby"
        )
        _clear(self.active_card.body_layout)
        self.task_rows = []
        self.active_empty = None
        if not records:
            self.active_empty = _label(
                "No active tasks\nReady when you are.", muted=True, parent=self.active_card.body
            )
            self.active_empty.setText("No active tasks\nReady when you are.")
            self.active_empty.setWordWrap(True)
            self.active_card.body_layout.addWidget(self.active_empty)
            self.active_card.body_layout.addStretch()
        else:
            for title, detail, identity, progress, kind in records[:MAX_VISIBLE]:
                row = _ActivityRow(
                    title, detail, identity, progress=progress, parent=self.active_card.body
                )
                row.selected.connect(
                    self.task_selected.emit if kind == "task" else self.details_requested.emit
                )
                row.set_reduce_motion(self._reduce_motion)
                self.task_rows.append(row)
                self.active_card.body_layout.addWidget(row)
            if count > MAX_VISIBLE:
                self.active_card.body_layout.addWidget(
                    _label(
                        f"+{count - MAX_VISIBLE} more in Mission Control",
                        muted=True,
                        parent=self.active_card.body,
                    )
                )
        _clear(self.tools_card.body_layout)
        self.execution_rows = []
        tool_running = sum(task.get("state") in {"running", "verifying"} for task in tasks)
        self.tools_card.badge.setText(f"{tool_running} running" if tool_running else "Recent")
        for task in tasks[:MAX_VISIBLE]:
            row = _ExecutionRow(task, self.tools_card.body)
            row.selected.connect(self.task_selected.emit)
            self.execution_rows.append(row)
            self.tools_card.body_layout.addWidget(row)
        if not tasks:
            self.tools_card.body_layout.addWidget(
                _label("No tool executions yet", muted=True, parent=self.tools_card.body)
            )
            self.tools_card.body_layout.addStretch()
        pending = [
            task
            for task in tasks
            if task.get("state") == "awaiting_approval" and _identity(task.get("id"))
        ]
        self.approval_badge.setText(str(len(pending)) if pending else "None")
        _clear(self.approvals_card.body_layout)
        self.approval_rows = []
        if not pending:
            message = (
                "Actions are stopped. Resume in Mission Control."
                if stopped
                else "No approvals waiting\nYou remain in control."
            )
            label = _label(parent=self.approvals_card.body)
            label.setText(message)
            label.setWordWrap(True)
            label.setObjectName("DashboardMuted")
            self.approvals_card.body_layout.addWidget(label)
            self.approvals_card.body_layout.addStretch()
        for task in pending[:2]:
            self.approval_rows.append(self._approval(task, stopped))
        if len(pending) > 2:
            self.approvals_card.body_layout.addWidget(
                _label(
                    f"+{len(pending) - 2} more in Mission Control",
                    muted=True,
                    parent=self.approvals_card.body,
                )
            )

    def _approval(self, task, stopped):
        identity = _identity(task["id"])
        frame = QFrame(self.approvals_card.body)
        frame.setObjectName("DashboardApproval")
        frame.setProperty("taskId", identity)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(7, 5, 7, 5)
        layout.setSpacing(3)
        title = _ElidedLabel(_tool_title(task) + "?", frame)
        title.setStyleSheet("color:#f2b5b7; font-size:11px;")
        detail = _ElidedLabel(_task_detail(task), frame)
        detail.setObjectName("DashboardMuted")
        layout.addWidget(title)
        layout.addWidget(detail)
        effects = {
            "create_directory": "Approve once · Creates a folder on this PC.",
            "open_website": "Approve once · Opens an external website.",
            "search_web": "Approve once · Sends search words to your browser.",
            "open_app": "Approve once · Launches or focuses this app.",
            "focus_app": "Approve once · Changes the foreground app.",
            "open_folder": "Approve once · Opens the selected folder.",
            "read_file": "Approve once · Reads this permitted local file.",
        }
        permission = _ElidedLabel(
            effects.get(task.get("tool"), "Approve once · Authorizes this exact action."), frame
        )
        permission.setObjectName("DashboardMuted")
        layout.addWidget(permission)
        actions = QHBoxLayout()
        review = QPushButton("Details", frame)
        review.setObjectName("DashboardDetails")
        review.setStyleSheet("font-size:10px;")
        review.setAccessibleName("Review exact pending action")
        review.clicked.connect(lambda _checked=False, key=identity: self.task_selected.emit(key))
        deny = QPushButton("Deny", frame)
        deny.setObjectName("DashboardDeny")
        approve = QPushButton("Approve", frame)
        approve.setObjectName("DashboardApprove")
        for button in (approve, deny):
            button.setEnabled(not stopped)
        approve.clicked.connect(
            lambda _checked=False, key=identity: self.approve_requested.emit(key)
        )
        deny.clicked.connect(lambda _checked=False, key=identity: self.deny_requested.emit(key))
        actions.addWidget(review)
        actions.addStretch()
        actions.addWidget(deny)
        actions.addWidget(approve)
        layout.addLayout(actions)
        self.approvals_card.body_layout.addWidget(frame)
        return frame

    def update_system(self, system):
        system = system if isinstance(system, dict) else {}
        stamp = (
            _text(system.get("sampled_at"), 80),
            *(
                _number(system.get(key), maximum=100)
                for key in ("cpu_percent", "memory_percent", "disk_percent")
            ),
        )
        append = not system.get("sampled_at") or stamp != self._last_sampled_at
        self._last_sampled_at = stamp
        for key, field, reason in (
            ("cpu", "cpu_percent", "cpu_unavailable_reason"),
            ("ram", "memory_percent", "memory_unavailable_reason"),
            ("disk", "disk_percent", "disk_unavailable_reason"),
        ):
            self.metrics[key].set_value(
                system.get(field),
                append=append,
                reason=system.get(reason) or system.get("unavailable_reason"),
            )
        present = sum(
            _number(system.get(key), maximum=100) is not None
            for key in ("cpu_percent", "memory_percent", "disk_percent")
        )
        self.system_badge.setText(
            "Measured" if present == 3 else "Partial" if present else "Not sampled"
        )
        temperature = _number(system.get("cpu_temperature_celsius"), maximum=150)
        self.temperature_label.setText(f"{temperature:.0f}°C" if temperature is not None else "—")
        self.temperature_label.setToolTip(
            _text(system.get("temperature_unavailable_reason") or "Measured CPU temperature", 300)
        )
        total = system.get("disk_total_bytes")
        used = system.get("disk_used_bytes")
        self.disk_label.setText(_bytes(total))
        self.disk_label.setToolTip(
            f"System volume: {_bytes(used)} used / {_bytes(total)} total (caller quota)"
        )
        network = _number(system.get("network_bytes_per_second"))
        self.network_label.setText(f"{_bytes(network)}/s" if network is not None else "—")
        self.network_label.setToolTip(
            _text(
                system.get("network_unavailable_reason")
                or "Measured physical-interface receive + transmit bytes per second",
                300,
            )
        )

    def set_reduce_motion(self, reduced):
        self._reduce_motion = bool(reduced)
        for row in self.task_rows:
            row.set_reduce_motion(self._reduce_motion)

    def update_ai(self, provider, model, health, latency=None, usage=None):
        self.provider_label.setText(_text(provider, 80))
        self.model_label.setText(_text(model, 100))
        full_health = _text(health or "Not checked", 300)
        compact_health = {
            "In-process service ready": "Local ready",
            "Local Ollama connected; selected model installed": "Connected",
            "Ollama connected; selected model not installed": "Model missing",
            "Ollama unavailable; start Ollama and rerun health check": "Offline",
            "Cloud adapter configured; live credentials not tested": "Unverified",
            "Cloud permission disabled": "Permission off",
            "Select a local AI model in Settings": "Choose model",
            "Health check pending": "Not checked",
        }.get(full_health, full_health[:28])
        self.ai_badge.setText(compact_health)
        self.ai_badge.setToolTip(full_health)
        self.latency_label.setText(f"Response   {_duration(latency)}")
        usage = usage if isinstance(usage, dict) else {}
        total = _number(usage.get("total_tokens"))
        input_tokens = _number(usage.get("input_tokens"))
        output_tokens = _number(usage.get("output_tokens"))
        if total is None and input_tokens is not None and output_tokens is not None:
            total = input_tokens + output_tokens
        self.usage_label.setText(
            f"Tokens      {total:,.0f}" if total is not None else "Tokens      —"
        )
        self.usage_label.setToolTip(
            f"Provider reported input: {input_tokens if input_tokens is not None else 'unavailable'}; output: {output_tokens if output_tokens is not None else 'unavailable'}"
        )
