"""Movable miniature view of the main assistant's existing voice state."""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .ui_components import STATE_LABELS, CoreWidget, WaveformWidget


class MiniAssistant(QFrame):
    """A UI-only tool window; it never opens a microphone or starts a backend."""

    expand_requested = Signal()
    settings_requested = Signal()
    mute_requested = Signal()
    dismiss_requested = Signal()

    def __init__(self, parent, *, always_on_top=False):
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self._drag_offset = None
        self.setObjectName("MiniAssistant")
        self.setWindowTitle("JARVIS · Mini Assistant")
        self.setAccessibleName("JARVIS floating voice controls")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet("""
            QFrame#MiniAssistant { background:#051623; border:1px solid #2488b7;
                border-radius:16px; }
            QLabel { color:#aecde2; background:transparent; font:11px 'Segoe UI'; }
            QLabel#MiniIdentity { color:#ccecff; letter-spacing:2px; font-size:11px; }
            QPushButton { background:transparent; border:0; border-radius:8px;
                color:#92c8e5; padding:0; min-height:0; font:15px 'Segoe UI'; }
            QPushButton:hover { color:#d3f8ff; background:#0e354d; }
            QPushButton#MiniMic { border:1px solid #225c79; background:#082839;
                border-radius:14px; font-size:14px; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(2)
        self.header = QFrame()
        self.header.setStyleSheet("background:transparent;border:0;")
        header = QHBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(3)
        self.identity = QLabel("JARVIS")
        self.identity.setObjectName("MiniIdentity")
        header.addWidget(self.identity, 1)
        self.expand_button = self._button("expand", "Open JARVIS command center")
        self.settings_button = self._button("settings", "Open JARVIS settings")
        self.dismiss_button = self._button("close", "Hide mini assistant")
        for button in (self.expand_button, self.settings_button, self.dismiss_button):
            header.addWidget(button)
        self.expand_button.clicked.connect(self.expand_requested.emit)
        self.settings_button.clicked.connect(self.settings_requested.emit)
        self.dismiss_button.clicked.connect(self._dismiss)
        self.header.installEventFilter(self)
        self.identity.installEventFilter(self)
        layout.addWidget(self.header)
        self.core = CoreWidget(self)
        self.core.setMinimumSize(100, 100)
        self.core.setMaximumHeight(114)
        layout.addWidget(self.core, 0, Qt.AlignmentFlag.AlignCenter)
        self.label = QLabel("Standby")
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        audio_row = QHBoxLayout()
        audio_row.setContentsMargins(0, 0, 0, 0)
        audio_row.setSpacing(5)
        self.waveform = WaveformWidget(self, sample_count=32)
        self.waveform.setFixedHeight(26)
        self.mute_button = self._button("microphone", "Mute or unmute the shared microphone")
        self.mute_button.setObjectName("MiniMic")
        self.mute_button.setFixedSize(29, 29)
        self.mute_button.clicked.connect(self.mute_requested.emit)
        audio_row.addWidget(self.waveform, 1)
        audio_row.addWidget(self.mute_button)
        layout.addLayout(audio_row)
        self.setFixedSize(204, 214)

    @staticmethod
    def _icon(kind, muted=False):
        """Original line icons avoid relying on optional Unicode symbol fonts."""
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(32 / 24, 32 / 24)
        painter.setPen(QPen(QColor("#8dd7f5"), 1.3))
        if kind == "close":
            painter.drawLine(7, 7, 17, 17)
            painter.drawLine(7, 17, 17, 7)
        elif kind == "expand":
            painter.drawLine(7, 17, 17, 7)
            painter.drawLine(9, 7, 17, 7)
            painter.drawLine(17, 7, 17, 15)
        elif kind == "settings":
            painter.drawEllipse(8, 8, 8, 8)
            painter.drawEllipse(11, 11, 2, 2)
            for index in range(8):
                angle = index * math.tau / 8
                painter.drawLine(
                    round(12 + math.cos(angle) * 5),
                    round(12 + math.sin(angle) * 5),
                    round(12 + math.cos(angle) * 7),
                    round(12 + math.sin(angle) * 7),
                )
        else:
            painter.drawRoundedRect(9, 4, 6, 11, 3, 3)
            painter.drawArc(6, 8, 12, 11, 180 * 16, 180 * 16)
            painter.drawLine(12, 18, 12, 21)
            painter.drawLine(9, 21, 15, 21)
            if muted:
                painter.setPen(QPen(QColor("#ed737e"), 1.6))
                painter.drawLine(5, 5, 19, 20)
        painter.end()
        return QIcon(pixmap)

    def _button(self, kind, description):
        button = QPushButton(self)
        button.setIcon(self._icon(kind))
        button.setFixedSize(24, 24)
        button.setToolTip(description)
        button.setAccessibleName(description)
        return button

    def _dismiss(self):
        self.hide()
        self.dismiss_requested.emit()

    def set_state(self, state, label=None):
        self.core.set_state(state)
        self.waveform.set_state(state)
        self.label.setText(str(label) if label is not None else STATE_LABELS[state].title())
        self.mute_button.setIcon(self._icon("microphone", state == "muted"))
        self.mute_button.setToolTip(
            "Unmute the shared microphone" if state == "muted" else "Mute the shared microphone"
        )

    def set_level(self, level):
        self.core.set_level(level)
        self.waveform.set_level(level)

    def clear_level(self):
        self.core.clear_level()
        self.waveform.clear_level()

    def set_reduce_motion(self, reduced):
        self.core.set_reduce_motion(reduced)
        self.waveform.set_reduce_motion(reduced)

    def set_always_on_top(self, enabled):
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(enabled))
        if visible:
            self.show()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0, QColor("#082336"))
        gradient.setColorAt(0.3, QColor("#051623"))
        gradient.setColorAt(1, QColor("#030f1b"))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor("#2785ac"), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.7, 0.7, -0.7, -0.7), 15, 15)
        painter.end()

    def eventFilter(self, watched, event):
        if watched in (self.header, self.identity):
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._drag_offset = event.globalPosition().toPoint() - self.pos()
                event.accept()
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag_offset is not None:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                event.accept()
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_offset = None
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            position = event.globalPosition().toPoint() - self._drag_offset
            self.move(QPoint(position))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)
