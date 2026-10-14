"""Native holographic graphics, measured audio displays and shared design tokens."""

from __future__ import annotations

import math
import time
from collections import deque

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

TOKENS = {
    "background": "#030c14",
    "surface": "#071724",
    "raised": "#0c2132",
    "border": "#173b51",
    "text": "#dceaf6",
    "muted": "#8296ae",
    "accent": "#20c9ff",
    "blue": "#468dff",
    "warning": "#efb864",
    "error": "#ed737e",
    "spacing": (4, 8, 12, 16, 24, 32),
}

STYLE = """
QWidget { background:#030c14; color:#dceaf6; font-family:'Segoe UI'; font-size:13px; }
QMainWindow { background:#030c14; }
QFrame#Sidebar { background:#071522; border:1px solid #183b50; border-radius:16px; }
QFrame#Panel { background:#071724; border:1px solid #173b51; border-radius:12px; }
QLabel { background:transparent; }
QWidget#PresenceDetail { background:transparent; }
QLabel#Brand { color:#bddfff; font-size:25px; font-weight:400; letter-spacing:5px; }
QLabel#Title { font-size:23px; font-weight:500; }
QLabel#Muted { color:#8296ae; }
QLabel#Status { color:#8de4ff; padding:10px; background:#082333; border-radius:8px; }
QPushButton { background:#0c2132; border:1px solid #24485c; padding:8px 12px;
 border-radius:8px; font-weight:600; min-height:17px; }
QPushButton:hover { background:#12344b; border-color:#20c9ff; }
QPushButton:focus { border:2px solid #8fe2ff; }
QPushButton:pressed { background:#1a4a65; }
QPushButton:disabled { color:#64788d; border-color:#162b3b; background:#081724; }
QPushButton#Primary { color:#022034; background:#20c9ff; border-color:#4ed8ff; }
QPushButton#Danger { color:#ffb7bc; border-color:#75434c; background:#28121d; }
QPushButton#Nav { text-align:left; padding:10px 12px; background:transparent; border:0; }
QPushButton#Nav:checked { color:#d7f3ff; background:qlineargradient(x1:0,y1:0,x2:1,y2:1,
 stop:0 #124966,stop:1 #182c4a); border:1px solid #3084ba; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
 background:#05131e; border:1px solid #234456; border-radius:7px; padding:7px;
 selection-background-color:#235575; }
QLineEdit:focus, QPlainTextEdit:focus { border-color:#20c9ff; }
QTextEdit#Conversation { background:#030c14; border:0; padding:8px; }
QTableWidget, QListWidget { background:#071724; border:1px solid #173b51;
 border-radius:8px; gridline-color:#173b51; alternate-background-color:#0a1d2c; }
QHeaderView::section { background:#0c2436; border:0; padding:9px; color:#b8cadb; }
QTableWidget::item:selected, QListWidget::item:selected { background:#16415c; }
QCheckBox { spacing:7px; }
QCheckBox::indicator { width:16px; height:16px; }
QScrollArea { border:0; }
QScrollBar:vertical { background:#06131e; width:8px; }
QScrollBar::handle:vertical { background:#284a61; min-height:30px; border-radius:4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QMenu { background:#0b2131; border:1px solid #31566e; }
QMenu::item { padding:8px 18px; }
QMenu::item:selected { background:#16415c; }
QProgressBar { background:#09202d; border:0; border-radius:3px; color:#93cde7; }
QProgressBar::chunk { background:#24bff5; border-radius:3px; }
QToolTip { color:#e6f5ff; background:#0c2639; border:1px solid #29729b; padding:5px; }
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
        self._orb_cache = None
        self._orb_cache_key = None
        self._observed_window = None
        self.setMinimumSize(100, 100)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAccessibleName("JARVIS assistant state")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self._refresh_timer()

    def sizeHint(self):
        return QSize(350, 350)

    def set_state(self, state):
        if state not in STATE_LABELS:
            raise ValueError("Unknown presence state")
        if self.state == state:
            return
        self.state = state
        self._started_at = time.monotonic()
        self.setAccessibleDescription(self.caption)
        self._refresh_timer()
        self.update()

    def set_level(self, level):
        value = float(level)
        self.level = min(max(value, 0.0), 1.0) if math.isfinite(value) else None
        self.setAccessibleDescription(self.caption)
        self.update()

    @property
    def caption(self):
        detail = (
            f"Measured mic RMS {self.level:.3f}"
            if self.level is not None and self.state in {"wake", "listening"}
            else f"Measured playback peak {self.level:.3f}"
            if self.level is not None and self.state == "speaking"
            else "Playback state · no PCM level"
            if self.state == "speaking"
            else "State from JARVIS"
        )
        return STATE_LABELS[self.state] + " · " + detail

    def clear_level(self):
        if self.level is not None:
            self.level = None
            self.setAccessibleDescription(self.caption)
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
            else 60
        )
        self.timer.setInterval(round(1000 / fps))
        if (
            self.isVisible()
            and not self.window().isMinimized()
            and not self.reduce_motion
            and self.state not in {"muted", "error", "approval"}
        ):
            self.timer.start()
        else:
            self.timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        window = self.window()
        if self._observed_window is not window:
            if self._observed_window is not None:
                self._observed_window.removeEventFilter(self)
            self._observed_window = window
            window.installEventFilter(self)
        self._refresh_timer()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        if watched is self._observed_window and event.type() in {
            QEvent.Type.WindowStateChange,
            QEvent.Type.Show,
            QEvent.Type.Hide,
        }:
            self._refresh_timer()
        return super().eventFilter(watched, event)

    def _color(self):
        return QColor(
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

    @staticmethod
    def _tint(color, alpha):
        tinted = QColor(color)
        tinted.setAlpha(alpha)
        return tinted

    @classmethod
    def _halo(cls, painter, x, y, radius, color, alpha):
        gradient = QRadialGradient(x, y, radius)
        gradient.setColorAt(0, cls._tint(color, alpha))
        gradient.setColorAt(0.35, cls._tint(color, alpha // 3))
        gradient.setColorAt(1, cls._tint(color, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(QRectF(x - radius, y - radius, radius * 2, radius * 2))

    def _paint_shell(self, painter, color):
        """Draw original layered vector art once per geometry/palette/DPI change."""
        tint = self._tint
        self._halo(painter, 0, 0, 117, color, 28)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for radius, alpha, stroke in (
            (109, 32, 0.5),
            (103, 80, 0.7),
            (98, 120, 1.1),
            (94, 65, 0.6),
            (90, 140, 1.2),
        ):
            painter.setPen(QPen(tint(color, alpha), stroke))
            painter.drawEllipse(QRectF(-radius, -radius, radius * 2, radius * 2))
        # Broken double arcs create depth rather than a uniform circular outline.
        for radius, offset in ((105, 8), (100.5, 29), (95.5, -18), (87.5, 12)):
            rect = QRectF(-radius, -radius, radius * 2, radius * 2)
            for start, length in (
                (offset, 51),
                (91 + offset, 30),
                (174 + offset, 62),
                (273 + offset, 43),
            ):
                painter.setPen(QPen(tint(color, 20), 5.2))
                painter.drawArc(rect, start * 16, length * 16)
                painter.setPen(QPen(tint(color, 160), 1.25))
                painter.drawArc(rect, start * 16, length * 16)
                painter.setPen(QPen(QColor(110, 211, 255, 170), 0.5))
                painter.drawArc(
                    rect.adjusted(1.2, 1.2, -1.2, -1.2), (start + 4) * 16, max(4, length - 13) * 16
                )
        # Fine radial circuits and fixed particles are decorative geometry, not audio.
        for index in range(96):
            angle = math.tau * index / 96
            start, end = (91, 100) if index % 8 == 0 else (96.5, 98.2)
            painter.setPen(QPen(tint(color, 125 if index % 8 == 0 else 50), 0.6))
            painter.drawLine(
                QPointF(math.cos(angle) * start, math.sin(angle) * start),
                QPointF(math.cos(angle) * end, math.sin(angle) * end),
            )
            if index % 12 == 0:
                painter.setBrush(tint(color, 165))
                painter.drawEllipse(
                    QPointF(math.cos(angle) * 108, math.sin(angle) * 108), 0.75, 0.75
                )
        # The glass globe has an offset highlight and a shaded lower hemisphere.
        globe = QRadialGradient(-27, -53, 141)
        globe.setColorAt(0, QColor("#69d5ff") if self.state != "muted" else QColor("#567080"))
        globe.setColorAt(0.17, QColor("#1b68a2"))
        globe.setColorAt(0.40, QColor("#092f53"))
        globe.setColorAt(0.70, QColor("#04192b"))
        globe.setColorAt(1, QColor("#010912"))
        painter.setPen(QPen(tint(color, 200), 1.4))
        painter.setBrush(globe)
        painter.drawEllipse(QRectF(-84, -84, 168, 168))

        # Project a deterministic triangular mesh onto a spherical front surface.
        def point(row, column):
            latitude = -math.pi / 2 + row * math.pi / 16
            longitude = -math.pi / 2 + column * math.pi / 24
            return QPointF(83 * math.cos(latitude) * math.sin(longitude), 83 * math.sin(latitude))

        for row in range(16):
            for column in range(24):
                points = (
                    point(row, column),
                    point(row, column + 1),
                    point(row + 1, column),
                    point(row + 1, column + 1),
                )
                for triangle in (
                    (points[0], points[1], points[2]),
                    (points[1], points[3], points[2]),
                ):
                    wave = math.sin(row * 7.2 + column * 4.7)
                    alpha = 7 + int((wave + 1) * 13)
                    if row < 6 and wave > 0.1:
                        facet = QColor(75, 163, 225, 25 + int(wave * 28))
                    elif wave < -0.3:
                        facet = QColor(0, 7, 19, 44)
                    else:
                        facet = tint(color, alpha)
                    painter.setBrush(facet)
                    painter.setPen(QPen(QColor(100, 196, 245, 24), 0.35))
                    painter.drawPolygon(QPolygonF(triangle))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Distinct light crescents and a dark lower edge make the shell spherical.
        shell_rect = QRectF(-82, -82, 164, 164)
        for stroke, alpha in ((7.5, 22), (3.5, 65), (1.6, 190)):
            painter.setPen(QPen(QColor(157, 216, 255, alpha), stroke))
            painter.drawArc(shell_rect, 29 * 16, 122 * 16)
        painter.setPen(QPen(QColor(0, 3, 9, 180), 2.5))
        painter.drawArc(QRectF(-77, -77, 154, 154), 206 * 16, 127 * 16)
        for radius in (82, 79, 76):
            painter.setPen(QPen(tint(color, 90), 0.7))
            painter.drawEllipse(QRectF(-radius, -radius, radius * 2, radius * 2))
        for angle in (-22, 25, 74):
            painter.save()
            painter.rotate(angle)
            painter.setPen(QPen(QColor(118, 206, 255, 65), 0.7))
            painter.drawEllipse(QRectF(-83, -27, 166, 54))
            painter.restore()
        for angle, width, height in ((-13, 166, 72), (34, 163, 38), (-68, 162, 46)):
            painter.save()
            painter.rotate(angle)
            ellipse = QRectF(-width / 2, -height / 2, width, height)
            for stroke, alpha in ((4.4, 18), (1.1, 150), (0.45, 225)):
                painter.setPen(QPen(tint(color, alpha), stroke))
                painter.drawArc(ellipse, 17 * 16, 130 * 16)
                painter.drawArc(ellipse, 205 * 16, 122 * 16)
            painter.restore()
        # Fixed small circuit nodes add surface detail without animated particles.
        for index in range(47):
            angle = index * 2.39996
            radius = 59 + (index * 7 % 23)
            x, y = math.cos(angle) * radius, math.sin(angle) * radius
            painter.setPen(QPen(tint(color, 115), 0.5))
            painter.setBrush(tint(color, 140))
            painter.drawEllipse(QPointF(x, y), 0.6, 0.6)
            if index % 4 == 0:
                painter.drawLine(QPointF(x, y), QPointF(x + 4, y - 3))
        # Dark inner chamber keeps the identity readable over the detailed globe.
        chamber = QRadialGradient(-9, -16, 76)
        chamber.setColorAt(0, QColor("#071d2d"))
        chamber.setColorAt(0.65, QColor("#020c15"))
        chamber.setColorAt(1, QColor("#0b3553"))
        painter.setBrush(chamber)
        painter.setPen(QPen(tint(color, 140), 0.8))
        painter.drawEllipse(QRectF(-47, -47, 94, 94))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for radius, alpha in ((53, 160), (49, 60), (43, 95), (40, 45)):
            painter.setPen(QPen(tint(color, alpha), 0.65))
            painter.drawEllipse(QRectF(-radius, -radius, radius * 2, radius * 2))
        painter.setPen(QPen(QColor(146, 222, 255, 150), 1.2))
        painter.drawArc(QRectF(-55, -55, 110, 110), 45 * 16, 55 * 16)
        painter.drawArc(QRectF(-55, -55, 110, 110), 223 * 16, 52 * 16)
        for index in range(24):
            angle = math.tau * index / 24
            painter.setPen(QPen(tint(color, 90), 0.7))
            painter.drawLine(
                QPointF(math.cos(angle) * 50, math.sin(angle) * 50),
                QPointF(math.cos(angle) * 54, math.sin(angle) * 54),
            )
        # Four bright energy caustics match the reference's luminous cardinal axes.
        flare_factor = 0.3 if self.state == "muted" else 1.0
        for rotation in (0, 90, 180, 270):
            painter.save()
            painter.rotate(rotation)
            self._halo(painter, 0, -86, 30, color, round(205 * flare_factor))
            beam = QLinearGradient(0, -110, 0, -69)
            beam.setColorAt(0, tint(color, 0))
            beam.setColorAt(0.47, tint(color, round(130 * flare_factor)))
            beam.setColorAt(0.65, QColor(156, 234, 255, round(190 * flare_factor)))
            beam.setColorAt(1, tint(color, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(beam)
            painter.drawPolygon(
                QPolygonF((QPointF(0, -108), QPointF(11, -84), QPointF(0, -69), QPointF(-11, -84)))
            )
            self._halo(painter, 0, -88, 11, QColor("#72e4ff"), round(240 * flare_factor))
            painter.setBrush(QColor(160, 242, 255, round(225 * flare_factor)))
            painter.drawEllipse(QRectF(-0.8, -96, 1.6, 16))
            painter.setPen(QPen(QColor(181, 240, 255, round(190 * flare_factor)), 0.6))
            painter.drawLine(QPointF(-22, -84), QPointF(22, -84))
            painter.drawLine(QPointF(0, -107), QPointF(0, -72))
            painter.restore()
        self._halo(painter, 0, -10, 20, color, 110)
        mark = QPolygonF((QPointF(-8.5, -15), QPointF(8.5, -15), QPointF(0, 1)))
        painter.setBrush(QColor(10, 120, 194, 100))
        for stroke, alpha in ((5.0, 30), (2.8, 70), (1.3, 250)):
            painter.setPen(QPen(tint(color, alpha), stroke))
            painter.drawPolygon(mark)
        painter.setPen(QPen(QColor("#b9f5ff"), 0.8))
        painter.drawLine(QPointF(0, -13), QPointF(0, -3))
        font = QFont("Segoe UI")
        font.setPixelSize(11)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        painter.setFont(font)
        painter.setPen(QColor("#c1e2f5"))
        painter.drawText(QRectF(-42, 7, 87, 24), Qt.AlignmentFlag.AlignCenter, "JARVIS")

    def paintEvent(self, event):
        side = max(1, min(self.width(), self.height()))
        ratio = self.devicePixelRatioF()
        color = self._color()
        key = (side, ratio, color.rgba(), self.state == "muted")
        if self._orb_cache_key != key:
            cache = QPixmap(round(side * ratio), round(side * ratio))
            cache.setDevicePixelRatio(ratio)
            cache.fill(Qt.GlobalColor.transparent)
            layer = QPainter(cache)
            layer.setRenderHint(QPainter.RenderHint.Antialiasing)
            layer.translate(side / 2, side / 2)
            layer.scale(side / 240, side / 240)
            self._paint_shell(layer, color)
            layer.end()
            self._orb_cache, self._orb_cache_key = cache, key
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(
            QPointF((self.width() - side) / 2, (self.height() - side) / 2), self._orb_cache
        )
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(side / 240, side / 240)
        elapsed = 0 if self.reduce_motion else time.monotonic() - self._started_at
        activity = (
            min((self.level or 0) * 5, 1) if self.state in {"wake", "listening", "speaking"} else 0
        )
        if self.state not in {"muted", "error"}:
            speed = 19 if self.state in {"thinking", "tool"} else 4
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for index, radius in enumerate((102, 92, 72)):
                angle = elapsed * speed * (-1 if index == 1 else 1) + index * 116
                rect = QRectF(-radius, -radius, radius * 2, radius * 2)
                for stroke, alpha in ((4, 22), (1.6, 190)):
                    painter.setPen(QPen(self._tint(color, alpha), stroke))
                    painter.drawArc(rect, round(angle * 16), (37 + index * 9) * 16)
                    painter.drawArc(rect, round((angle + 180) * 16), 20 * 16)
            if activity:
                self._halo(painter, 0, 0, 65, color, round(activity * 58))
            elif self.state in {"idle", "wake", "activated"}:
                # State breathing is ornamental and does not manufacture audio samples.
                breath = 10 if self.reduce_motion else 10 + round(math.sin(elapsed * 1.4) * 6)
                self._halo(painter, 0, -78, 24, color, breath)
        painter.end()


class WaveformWidget(QWidget):
    """Measured microphone RMS or own-process playback peaks, never generated audio."""

    def __init__(self, parent=None, *, sample_count=64):
        super().__init__(parent)
        self.state = "idle"
        self.level = None
        self.reduce_motion = False
        self.samples = deque(maxlen=max(8, min(int(sample_count), 128)))
        self.setMinimumSize(45, 18)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAccessibleName("Measured voice waveform")
        self._describe()

    def sizeHint(self):
        return QSize(160, 30)

    @property
    def caption(self):
        if self.level is not None:
            kind = "playback peak" if self.state == "speaking" else "mic RMS"
            return f"Measured {kind} {self.level:.3f}"
        if self.state == "speaking":
            return "Playback peak unavailable · no own-process meter or PCM samples"
        return "No measured audio samples"

    def _describe(self):
        self.setAccessibleDescription(self.caption)
        self.setToolTip(self.caption)

    def set_state(self, state):
        if state not in STATE_LABELS:
            raise ValueError("Unknown presence state")
        if self.state != state:
            self.state = state
            self.clear_level()
        self._describe()
        self.update()

    def set_level(self, level):
        value = float(level)
        if not math.isfinite(value):
            self.clear_level()
            return
        self.level = min(max(value, 0.0), 1.0)
        self.samples.append(self.level)
        self._describe()
        self.update()

    def clear_level(self):
        self.level = None
        self.samples.clear()
        self._describe()
        self.update()

    def set_reduce_motion(self, reduced):
        self.reduce_motion = bool(reduced)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(TOKENS["muted"] if self.state == "muted" else TOKENS["accent"])
        center = self.height() / 2
        painter.setPen(QPen(CoreWidget._tint(color, 45), 0.8))
        painter.drawLine(QPointF(2, center), QPointF(self.width() - 2, center))
        samples = list(self.samples)
        if samples:
            count = self.samples.maxlen
            spacing = (self.width() - 8) / count
            start = count - len(samples)
            for index, sample in enumerate(samples):
                amplitude = min(sample * 8, 1) * (self.height() - 5) / 2
                x = 4 + (start + index + 0.5) * spacing
                painter.setPen(QPen(CoreWidget._tint(color, 35), max(2, spacing)))
                painter.drawLine(QPointF(x, center - amplitude), QPointF(x, center + amplitude))
                painter.setPen(QPen(color, max(0.8, min(2.2, spacing * 0.46))))
                painter.drawLine(QPointF(x, center - amplitude), QPointF(x, center + amplitude))
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
