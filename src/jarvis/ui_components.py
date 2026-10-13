"""Original native vector presence and reusable ambient intelligence design tokens."""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

TOKENS = {
    "background": "#0b1018",
    "surface": "#111b29",
    "raised": "#172436",
    "border": "#293b50",
    "text": "#e2edf7",
    "muted": "#a2b3c7",
    "accent": "#78dce7",
    "blue": "#95b9f7",
    "warning": "#efbf79",
    "error": "#f19a9e",
    "spacing": (4, 8, 12, 16, 24, 32),
}

STYLE = """
QWidget { background:#0b1018; color:#e2edf7; font-family:'Segoe UI'; font-size:13px; }
QMainWindow { background:#0b1018; }
QFrame#Sidebar { background:#101927; border-right:1px solid #26384c; }
QFrame#Panel { background:#111b29; border:1px solid #293b50; border-radius:14px; }
QLabel { background:transparent; }
QWidget#PresenceDetail { background:transparent; }
QLabel#Brand { color:#78dce7; font-size:25px; font-weight:700; letter-spacing:4px; }
QLabel#Title { font-size:23px; font-weight:600; }
QLabel#Muted { color:#a2b3c7; }
QLabel#Status { color:#b2e8ed; padding:10px; background:#132333; border-radius:8px; }
QPushButton { background:#19283b; border:1px solid #31485e; padding:8px 12px;
 border-radius:8px; font-weight:600; min-height:17px; }
QPushButton:hover { background:#263b50; border-color:#78dce7; }
QPushButton:focus { border:2px solid #9aebf2; }
QPushButton:pressed { background:#30495e; }
QPushButton:disabled { color:#8292a6; border-color:#273547; background:#121c29; }
QPushButton#Primary { color:#0b1821; background:#78dce7; border-color:#78dce7; }
QPushButton#Danger { color:#ffb7bc; border-color:#87515a; background:#32212b; }
QPushButton#Nav { text-align:left; padding:10px 12px; background:transparent; border:0; }
QPushButton#Nav:checked { color:#95ecf2; background:#1b3345; border-left:3px solid #78dce7; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
 background:#0f1927; border:1px solid #304459; border-radius:7px; padding:7px;
 selection-background-color:#326176; }
QLineEdit:focus, QPlainTextEdit:focus { border-color:#86e2eb; }
QTextEdit#Conversation { background:#0b1018; border:0; padding:8px; }
QTableWidget, QListWidget { background:#101b28; border:1px solid #2b3d52;
 border-radius:8px; gridline-color:#293b50; alternate-background-color:#152334; }
QHeaderView::section { background:#1b2d40; border:0; padding:9px; color:#b8cadb; }
QTableWidget::item:selected, QListWidget::item:selected { background:#2b5268; }
QCheckBox { spacing:7px; }
QCheckBox::indicator { width:16px; height:16px; }
QScrollArea { border:0; }
QScrollBar:vertical { background:#101b28; width:10px; }
QScrollBar::handle:vertical { background:#42586e; min-height:30px; border-radius:4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QMenu { background:#172638; border:1px solid #385269; }
QMenu::item { padding:8px 18px; }
QMenu::item:selected { background:#2b5268; }
"""

STATE_LABELS = {
    "idle": "READY",
    "wake": "WAKE LISTENING",
    "activated": "ACTIVATED",
    "listening": "LISTENING",
    "thinking": "PROCESSING",
    "tool": "EXECUTING TOOL",
    "speaking": "SPEAKING",
    "approval": "APPROVAL REQUIRED",
    "error": "VOICE ERROR",
    "muted": "MICROPHONE OFF",
}


class CoreWidget(QWidget):
    """Render real state and optional measured microphone RMS, never simulated audio."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "idle"
        self.level = None
        self.reduce_motion = False
        self._started_at = time.monotonic()
        self.setMinimumSize(120, 110)
        self.setMaximumSize(210, 220)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setAccessibleName("JARVIS assistant state")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self._refresh_timer()

    def sizeHint(self):
        return QSize(190, 200)

    def set_state(self, state):
        if state not in STATE_LABELS:
            raise ValueError("Unknown presence state")
        if self.state == state:
            return
        self.state = state
        self._started_at = time.monotonic()
        self.setAccessibleDescription(STATE_LABELS[state])
        self._refresh_timer()
        self.update()

    def set_level(self, level):
        value = float(level)
        self.level = min(max(value, 0.0), 1.0) if math.isfinite(value) else None
        self.update()

    @property
    def caption(self):
        detail = (
            f"Measured mic RMS {self.level:.3f}"
            if self.level is not None and self.state in {"wake", "listening"}
            else "Playback state · no PCM level"
            if self.state == "speaking"
            else "State from JARVIS"
        )
        return STATE_LABELS[self.state] + " · " + detail

    def clear_level(self):
        if self.level is not None:
            self.level = None
            self.update()

    def set_reduce_motion(self, reduced):
        self.reduce_motion = bool(reduced)
        self._refresh_timer()
        self.update()

    def _refresh_timer(self):
        fps = (
            8
            if self.state in {"idle", "muted", "error", "approval"}
            else 12
            if self.state == "wake"
            else 20
        )
        self.timer.setInterval(round(1000 / fps))
        if (
            self.isVisible()
            and not self.reduce_motion
            and self.state not in {"muted", "error", "approval"}
        ):
            self.timer.start()
        else:
            self.timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_timer()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        cx, cy = width / 2, (height - 38) / 2
        radius = max(10, min(width - 28, height - 48) / 2)
        elapsed = 0.0 if self.reduce_motion else time.monotonic() - self._started_at
        color = QColor(
            TOKENS["warning"]
            if self.state == "approval"
            else TOKENS["error"]
            if self.state == "error"
            else TOKENS["muted"]
            if self.state == "muted"
            else TOKENS["blue"]
            if self.state in {"thinking", "tool"}
            else TOKENS["accent"]
        )
        activity = min((self.level or 0) * 5, 1) if self.state == "listening" else 0
        breath = 0.0 if self.reduce_motion else math.sin(elapsed * 1.3) * 0.025
        glow = QRadialGradient(cx, cy, radius)
        transparent = QColor(color)
        transparent.setAlpha(0)
        middle = QColor(color)
        middle.setAlpha(25 + int(activity * 35))
        glow.setColorAt(0, middle)
        glow.setColorAt(1, transparent)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index, scale in enumerate((1.0, 0.83, 0.64)):
            r = radius * (scale + breath + activity * 0.045)
            ring = QColor(color)
            ring.setAlpha(55 + index * 40)
            pen = QPen(ring, 1.0 if index == 0 else 1.5)
            painter.setPen(pen)
            rect = QRectF(cx - r, cy - r, r * 2, r * 2)
            painter.drawEllipse(rect)
            angle = (
                elapsed
                * (24 if self.state in {"thinking", "tool", "speaking"} else 7)
                * (-1 if index == 1 else 1)
            )
            painter.setPen(QPen(color, 2.5))
            painter.drawArc(
                rect, int((angle + index * 95) * 16), (48 if self.state == "wake" else 76) * 16
            )
        core_r = radius * (0.24 + activity * 0.09 + breath)
        painter.setPen(QPen(color, 1.5))
        core_color = QColor(color)
        core_color.setAlpha(25)
        painter.setBrush(core_color)
        painter.drawEllipse(QRectF(cx - core_r, cy - core_r, core_r * 2, core_r * 2))
        painter.setBrush(color)
        painter.drawEllipse(QRectF(cx - 3, cy - 3, 6, 6))
        painter.setPen(color)
        font = QFont("Segoe UI", 8)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(
            QRectF(0, height - 35, width, 17),
            Qt.AlignmentFlag.AlignCenter,
            STATE_LABELS[self.state],
        )
        painter.setPen(QColor(TOKENS["muted"]))
        font.setPointSize(7)
        painter.setFont(font)
        detail = (
            f"Measured mic RMS {self.level:.3f}"
            if self.level is not None and self.state in {"wake", "listening"}
            else "Playback state · no PCM level"
            if self.state == "speaking"
            else "State from JARVIS"
        )
        painter.drawText(QRectF(0, height - 18, width, 16), Qt.AlignmentFlag.AlignCenter, detail)
        painter.end()


def metric_card(title, value, detail=""):
    card = QFrame()
    card.setObjectName("Panel")
    layout = QVBoxLayout(card)
    for text, name in ((title, "Muted"), (value, "Title"), (detail, "Muted")):
        label = QLabel(str(text))
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setObjectName(name)
        layout.addWidget(label)
    return card
