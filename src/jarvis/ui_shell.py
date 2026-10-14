"""Original, native Qt shell components for the reference command center.

The artwork is decorative. Listening, model and resource labels receive real
state from the controller; this module neither opens a microphone nor reads a
provider. Buttons retain native keyboard, focus and accessibility behavior.
"""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def _font(size: int, *, bold: bool = False) -> QFont:
    font = QFont("Segoe UI")
    font.setPixelSize(size)
    font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return font


def _pen(color: QColor | str, width: float = 1.6) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _draw_symbol(painter: QPainter, name: str, color: QColor | str) -> None:
    """Paint original line geometry in a 24×24 logical coordinate system."""
    painter.setPen(_pen(color))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    if name in {"assistant", "logo", "jarvis"}:
        path.moveTo(4, 5)
        path.lineTo(20, 5)
        path.lineTo(12, 19)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(8, 8), QPointF(12, 14))
        painter.drawLine(QPointF(12, 14), QPointF(16, 8))
        painter.drawLine(QPointF(9, 22), QPointF(15, 22))
    elif name in {"home", "assistant-home"}:
        path.moveTo(3, 11)
        path.lineTo(12, 3)
        path.lineTo(21, 11)
        path.moveTo(6, 10)
        path.lineTo(6, 21)
        path.lineTo(10, 21)
        path.lineTo(10, 15)
        path.lineTo(14, 15)
        path.lineTo(14, 21)
        path.lineTo(18, 21)
        path.lineTo(18, 10)
        painter.drawPath(path)
    elif name in {"mission", "monitor", "system"}:
        painter.drawRoundedRect(QRectF(3, 4, 18, 15), 1.5, 1.5)
        painter.drawLine(QPointF(8, 22), QPointF(16, 22))
        painter.drawLine(QPointF(12, 19), QPointF(12, 22))
        painter.drawLine(QPointF(7, 11), QPointF(10, 11))
        painter.drawLine(QPointF(10, 8), QPointF(10, 14))
        painter.drawLine(QPointF(14, 9), QPointF(17, 9))
        painter.drawLine(QPointF(14, 13), QPointF(17, 13))
    elif name in {"memory", "file"}:
        painter.drawRoundedRect(QRectF(5, 6, 14, 16), 2, 2)
        painter.drawRoundedRect(QRectF(8, 2, 8, 4), 1, 1)
        painter.drawRoundedRect(QRectF(9, 11, 6, 6), 1, 1)
    elif name in {"automation", "automations", "spark"}:
        path.moveTo(12, 2)
        path.lineTo(14, 9)
        path.lineTo(21, 12)
        path.lineTo(14, 15)
        path.lineTo(12, 22)
        path.lineTo(10, 15)
        path.lineTo(3, 12)
        path.lineTo(10, 9)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawEllipse(QRectF(10.5, 10.5, 3, 3))
    elif name in {"workspaces", "grid", "apps"}:
        for x, y in ((3, 3), (13, 3), (3, 13), (13, 13)):
            painter.drawRoundedRect(QRectF(x, y, 7, 7), 1.3, 1.3)
    elif name in {"browser", "web", "globe"}:
        painter.drawEllipse(QRectF(2.5, 2.5, 19, 19))
        painter.drawEllipse(QRectF(7.5, 2.5, 9, 19))
        painter.drawLine(QPointF(3.5, 8), QPointF(20.5, 8))
        painter.drawLine(QPointF(3.5, 16), QPointF(20.5, 16))
    elif name in {"settings", "gear"}:
        for index in range(8):
            angle = index * math.pi / 4
            painter.drawLine(
                QPointF(12 + math.cos(angle) * 8, 12 + math.sin(angle) * 8),
                QPointF(12 + math.cos(angle) * 11, 12 + math.sin(angle) * 11),
            )
        painter.drawEllipse(QRectF(4.5, 4.5, 15, 15))
        painter.drawEllipse(QRectF(9, 9, 6, 6))
    elif name in {"microphone", "mic", "mic-off", "mute"}:
        painter.drawRoundedRect(QRectF(9, 2, 6, 12), 3, 3)
        painter.drawArc(QRectF(6, 7, 12, 11), 180 * 16, 180 * 16)
        painter.drawLine(QPointF(12, 18), QPointF(12, 22))
        painter.drawLine(QPointF(8, 22), QPointF(16, 22))
        if name in {"mic-off", "mute"}:
            painter.drawLine(QPointF(3, 3), QPointF(21, 21))
    elif name in {"code", "coding"}:
        path.moveTo(7, 6)
        path.lineTo(2, 12)
        path.lineTo(7, 18)
        path.moveTo(17, 6)
        path.lineTo(22, 12)
        path.lineTo(17, 18)
        path.moveTo(14, 3)
        path.lineTo(10, 21)
        painter.drawPath(path)
    elif name in {"book", "study"}:
        path.moveTo(12, 6)
        path.cubicTo(8, 3, 5, 3, 2, 4)
        path.lineTo(2, 19)
        path.cubicTo(5, 18, 8, 18, 12, 21)
        path.cubicTo(16, 18, 19, 18, 22, 19)
        path.lineTo(22, 4)
        path.cubicTo(19, 3, 16, 3, 12, 6)
        path.lineTo(12, 21)
        painter.drawPath(path)
    elif name in {"search", "search-web"}:
        painter.drawEllipse(QRectF(3, 2, 14, 14))
        painter.drawLine(QPointF(15, 14), QPointF(22, 21))
    elif name in {"play", "routine", "send"}:
        path.moveTo(4, 3)
        path.lineTo(22, 12)
        path.lineTo(4, 21)
        path.closeSubpath()
        painter.drawPath(path)
        if name == "send":
            painter.drawLine(QPointF(4, 12), QPointF(17, 12))
    elif name in {"attachment", "attach"}:
        path.moveTo(9, 17)
        path.lineTo(15, 7)
        path.cubicTo(17, 3, 22, 6, 20, 10)
        path.lineTo(13, 21)
        path.cubicTo(10, 25, 3, 20, 6, 15)
        path.lineTo(13, 4)
        path.cubicTo(16, 0, 22, 4, 19, 9)
        painter.drawPath(path)
    elif name in {"shield", "approval"}:
        path.moveTo(12, 2)
        path.lineTo(21, 6)
        path.lineTo(20, 15)
        path.cubicTo(19, 18, 15, 21, 12, 23)
        path.cubicTo(9, 21, 5, 18, 4, 15)
        path.lineTo(3, 6)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(12, 8), QPointF(12, 14))
        painter.drawPoint(QPointF(12, 17))
    elif name == "check":
        painter.drawLine(QPointF(4, 12), QPointF(10, 18))
        painter.drawLine(QPointF(10, 18), QPointF(21, 5))
    elif name == "close":
        painter.drawLine(QPointF(6, 6), QPointF(18, 18))
        painter.drawLine(QPointF(18, 6), QPointF(6, 18))
    elif name in {"maximize", "expand"}:
        painter.drawRoundedRect(QRectF(5, 5, 14, 14), 1, 1)
    elif name == "restore":
        painter.drawRect(QRectF(8, 4, 12, 12))
        painter.drawRect(QRectF(4, 8, 12, 12))
    elif name == "minimize":
        painter.drawLine(QPointF(5, 12), QPointF(19, 12))
    else:
        painter.drawEllipse(QRectF(3, 3, 18, 18))
        painter.drawEllipse(QRectF(9, 9, 6, 6))


def make_icon(name: str, color: str = "#38c8f3", size: int = 24) -> QIcon:
    """Return a high-DPI icon painted from original vector geometry.

    Call on Qt's GUI thread after QApplication exists. No commercial application
    logo or downloaded icon pack is used. Multiple DPR variants prevent blur at
    ordinary Windows display scales.
    """
    logical = max(8, min(int(size), 512))
    icon = QIcon()
    for ratio in (1, 2, 3):
        pixmap = QPixmap(logical * ratio, logical * ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(ratio)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(logical / 24, logical / 24)
        _draw_symbol(painter, name, color)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class _PaintedButton(QPushButton):
    def __init__(self, title: str, subtitle: str, iconname: str, parent=None):
        super().__init__(title, parent)
        self.title = title
        self.subtitle = subtitle
        self.iconname = iconname
        self._hover = 0.0
        self._reduced_motion = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(title)
        self.setAccessibleDescription(subtitle)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(140)
        self._animation.valueChanged.connect(self._hover_changed)
        self.toggled.connect(self.update)

    def _hover_changed(self, value):
        self._hover = float(value)
        self.update()

    def _animate_hover(self, target):
        self._animation.stop()
        if self._reduced_motion:
            self._hover_changed(target)
        else:
            self._animation.setStartValue(self._hover)
            self._animation.setEndValue(float(target))
            self._animation.start()

    def set_reduce_motion(self, reduced: bool):
        self._reduced_motion = bool(reduced)
        if self._reduced_motion:
            self._animation.stop()

    def enterEvent(self, event):
        self._animate_hover(1)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0)
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._animation.stop()
        self._hover = 0
        super().hideEvent(event)

    def _painter(self):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isDown():
            painter.translate(0, 1)
        return painter

    def _text(self, painter, text, rect, *, size, color, bold=False):
        painter.setFont(_font(size, bold=bold))
        painter.setPen(QColor(color if self.isEnabled() else "#63748a"))
        text = painter.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideRight, int(rect.width())
        )
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)


class NavButton(_PaintedButton):
    """Two-line sidebar item with native selection, click and keyboard behavior."""

    def __init__(self, title: str, subtitle: str, iconname: str, parent=None):
        super().__init__(title, subtitle, iconname, parent)
        self.setObjectName("Nav")
        self.setCheckable(True)
        self.setMinimumHeight(58)
        self.setIcon(make_icon(iconname, "#acbde0", 25))
        self._active_icon = make_icon(iconname, "#50d5ff", 25)

    def sizeHint(self):
        return QSize(224, 62)

    def minimumSizeHint(self):
        return QSize(155, 58)

    def paintEvent(self, event):
        painter = self._painter()
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        active = self.isChecked()
        if active or self._hover > 0.01:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0, QColor("#143753" if active else "#0c2235"))
            gradient.setColorAt(1, QColor("#20588a" if active else "#122d43"))
            painter.setBrush(gradient)
            painter.setPen(_pen("#4398ca" if active else "#1f465f", 1))
            painter.drawRoundedRect(rect, 11, 11)
            if active:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(_pen(QColor(50, 190, 245, 38), 5))
                painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 9, 9)
        icon = self._active_icon if active else self.icon()
        icon.paint(painter, 16, (self.height() - 25) // 2, 25, 25)
        self._text(
            painter,
            self.title,
            QRectF(59, 9, self.width() - 66, 25),
            size=14,
            color="#edf4fb",
            bold=True,
        )
        self._text(
            painter,
            self.subtitle,
            QRectF(59, 32, self.width() - 66, 19),
            size=11,
            color="#97bad6" if active else "#8094b1",
        )
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(_pen("#91e9ff", 1.5))
            painter.drawRoundedRect(rect, 11, 11)
        painter.end()


class QuickActionCard(_PaintedButton):
    """Responsive, two-line action card; its clicked signal invokes the controller."""

    def __init__(self, title: str, subtitle: str, iconname: str, parent=None):
        super().__init__(title, subtitle, iconname, parent)
        self.setObjectName("QuickAction")
        self.setMinimumHeight(78)
        color = {
            "browser": "#56ceff",
            "code": "#9b9cf4",
            "book": "#a696ff",
            "search": "#b9cced",
            "play": "#20d8b2",
            "routine": "#20d8b2",
        }.get(iconname, "#42ccf0")
        self.setIcon(make_icon(iconname, color, 23))

    def sizeHint(self):
        return QSize(130, 84)

    def minimumSizeHint(self):
        return QSize(96, 78)

    def paintEvent(self, event):
        painter = self._painter()
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, QColor("#102b3e" if self._hover > 0.1 else "#081923"))
        gradient.setColorAt(1, QColor("#06121c"))
        painter.setBrush(gradient)
        painter.setPen(_pen("#3794bd" if self._hover > 0.1 else "#1b384a", 1))
        painter.drawRoundedRect(rect, 8, 8)
        self.icon().paint(painter, 15, 11, 23, 23)
        self._text(
            painter,
            self.title,
            QRectF(13, 41, self.width() - 22, 18),
            size=11,
            color="#dbeaf5",
            bold=True,
        )
        self._text(
            painter,
            self.subtitle,
            QRectF(13, 59, self.width() - 22, 17),
            size=10,
            color="#7891ab",
        )
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(_pen("#91e9ff", 1.5))
            painter.drawRoundedRect(rect, 8, 8)
        painter.end()


class SidebarAtmosphere(QWidget):
    """Original atmospheric footer with optional small, packaged Canva artwork.

    Terrain, skyline, atmospheric dome and identity are painted independently of
    the reference image. The optional asset adds scenery; no screenshot controls
    are used as wallpaper. There is no background animation or remote loading.
    """

    def __init__(self, parent=None, *, art_path: str | Path | None = None):
        super().__init__(parent)
        self.setObjectName("SidebarAtmosphere")
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setAccessibleName("JARVIS atmospheric identity illustration")
        self.setAccessibleDescription("Decorative mountain landscape and energy dome")
        self._art = QPixmap()
        self._identity_icon = make_icon("assistant", "#53c5eb", 23)
        self.set_artwork(art_path or Path(__file__).parent / "assets" / "sidebar-canva.jpg")

    def sizeHint(self):
        return QSize(224, 248)

    def set_artwork(self, path: str | Path | None) -> bool:
        self._art = QPixmap(str(path)) if path else QPixmap()
        self.update()
        return not self._art.isNull()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        art_height = max(65, height - 98)
        painter.fillRect(self.rect(), QColor("#07111b"))
        painter.save()
        painter.setClipRect(QRectF(0, 0, width, art_height))
        sky = QLinearGradient(0, 0, 0, art_height)
        sky.setColorAt(0, QColor("#09121f"))
        sky.setColorAt(0.6, QColor("#102945"))
        sky.setColorAt(1, QColor("#06101b"))
        painter.fillRect(QRectF(0, 0, width, art_height), sky)
        if not self._art.isNull():
            painter.save()
            painter.setClipRect(QRectF(0, 0, width, art_height))
            scaled = self._art.scaled(
                width,
                int(art_height),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.setOpacity(0.78)
            painter.drawPixmap(int((width - scaled.width()) / 2), 0, scaled)
            painter.restore()
        else:
            for index in range(36):
                x = (index * 67 + 19) % max(width, 1)
                y = (index * 31 + 7) % max(int(art_height * 0.65), 1)
                painter.setPen(_pen(QColor(97, 156, 221, 100 + index % 3 * 35), 1))
                painter.drawPoint(QPointF(x, y))
        dome_y = art_height * 0.72
        glow = QRadialGradient(width * 0.62, dome_y, width * 0.35)
        glow.setColorAt(0, QColor(35, 166, 237, 65 if self._art.isNull() else 15))
        glow.setColorAt(1, QColor(6, 14, 25, 0))
        painter.setBrush(glow)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(width * 0.25, dome_y - width * 0.3, width * 0.75, width * 0.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._art.isNull():
            painter.setPen(_pen(QColor(116, 192, 247, 110), 1))
            painter.drawArc(QRectF(width * 0.38, dome_y - 31, width * 0.56, 64), 0, 180 * 16)
        for index, shade in enumerate(("#142134", "#0c1828", "#050c15")):
            path = QPainterPath(QPointF(0, art_height))
            for point in range(19):
                x = point * width / 18
                peak = ((point * 7 + index * 5) % 11) / 11
                y = art_height * (0.57 + index * 0.13) - peak * (28 - index * 5)
                path.lineTo(x, y)
            path.lineTo(width, art_height)
            path.closeSubpath()
            mountain_color = QColor(shade)
            if not self._art.isNull():
                mountain_color.setAlpha(18)
            painter.setBrush(mountain_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(path)
        for index in range(20):
            x = width * 0.12 + (index * 43 % max(int(width * 0.8), 1))
            y = art_height * 0.88 + (index * 13 % 15)
            painter.fillRect(QRectF(x, y, 2, 1), QColor(203, 175, 117, 160))
        painter.restore()
        fade = QLinearGradient(0, art_height - 30, 0, art_height + 15)
        fade.setColorAt(0, QColor(7, 17, 27, 0))
        fade.setColorAt(1, QColor("#07111b"))
        painter.fillRect(QRectF(0, art_height - 30, width, 45), fade)
        painter.setFont(_font(12))
        painter.setPen(QColor("#b7c9da"))
        painter.drawText(
            QRectF(18, art_height + 7, width - 36, 40),
            Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
            "Ideas. Actions.\nOne assistant.",
        )
        self._identity_icon.paint(painter, 18, height - 36, 23, 23)
        font = _font(11)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        painter.setFont(font)
        painter.setPen(QColor("#91adca"))
        painter.drawText(
            QRectF(55, height - 37, width - 63, 25), Qt.AlignmentFlag.AlignVCenter, "JARVIS"
        )
        painter.end()


def _plain_label(text: str, size: int, color: str, *, bold=False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setFont(_font(size, bold=bold))
    label.setStyleSheet(f"background:transparent; color:{color}; font-size:{size}px;")
    return label


class HeaderBar(QWidget):
    """Compact live-state header, with optional native system window operations.

    Controller connects the three control signals when using a custom frame.
    Dragging requests Windows/Qt's native system move; double-click requests the
    controller's maximize/restore. No invented model or resource value is set.
    """

    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    def __init__(self, version: str, parent=None, *, window_controls: bool = False):
        super().__init__(parent)
        self.setObjectName("HeaderBar")
        self.setFixedHeight(56)
        layout = QHBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setContentsMargins(17, 4, 13, 4)
        layout.setSpacing(14)
        brand = QWidget(self)
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(12)
        mark = QLabel()
        mark.setTextFormat(Qt.TextFormat.PlainText)
        mark.setPixmap(make_icon("assistant", "#39c9f6", 25).pixmap(QSize(25, 25)))
        brand_layout.addWidget(mark)
        self.brand_label = _plain_label("JARVIS", 23, "#c8e1fa")
        wordmark_font = self.brand_label.font()
        wordmark_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        self.brand_label.setFont(wordmark_font)
        brand_layout.addWidget(self.brand_label)
        self.subtitle_label = _plain_label("AI ASSISTANT", 10, "#879eb9")
        brand_layout.addWidget(self.subtitle_label)
        self.version_label = _plain_label(f"v{version}", 10, "#7c92aa")
        brand_layout.addWidget(self.version_label)
        layout.addWidget(brand)
        layout.addStretch(1)
        self.voice_box = QWidget(self)
        voice_layout = QHBoxLayout(self.voice_box)
        voice_layout.setContentsMargins(0, 0, 0, 0)
        voice_layout.setSpacing(7)
        self.waveform_host = QHBoxLayout()
        self.waveform_host.setContentsMargins(0, 0, 0, 0)
        voice_layout.addLayout(self.waveform_host)
        self.microphone_label = QLabel()
        self.microphone_label.setTextFormat(Qt.TextFormat.PlainText)
        self.microphone_label.setPixmap(make_icon("mic", "#50d8ff", 23).pixmap(QSize(23, 23)))
        voice_layout.addWidget(self.microphone_label)
        self.state_label = _plain_label("Standby", 13, "#c8deef")
        self.state_label.setMinimumWidth(92)
        voice_layout.addWidget(self.state_label)
        layout.addWidget(self.voice_box)
        layout.addStretch(1)
        self.provider_box = QWidget(self)
        provider_layout = QHBoxLayout(self.provider_box)
        provider_layout.setContentsMargins(8, 1, 8, 1)
        provider_layout.setSpacing(8)
        provider_icon = QLabel()
        provider_icon.setTextFormat(Qt.TextFormat.PlainText)
        provider_icon.setPixmap(make_icon("spark", "#abc6df", 25).pixmap(QSize(25, 25)))
        provider_layout.addWidget(provider_icon)
        provider_text = QVBoxLayout()
        provider_text.setSpacing(0)
        self.model_label = _plain_label("Not checked", 12, "#dae9f5", bold=True)
        self.provider_label = _plain_label("Provider unavailable", 10, "#8097b0")
        provider_text.addWidget(self.model_label)
        provider_text.addWidget(self.provider_label)
        provider_layout.addLayout(provider_text)
        layout.addWidget(self.provider_box)
        self.metrics_box = QWidget(self)
        metrics_layout = QHBoxLayout(self.metrics_box)
        metrics_layout.setContentsMargins(8, 0, 0, 0)
        metrics_layout.setSpacing(18)
        self.cpu_label = _plain_label("CPU —", 10, "#9db6ce")
        self.ram_label = _plain_label("RAM —", 10, "#9db6ce")
        self.network_label = _plain_label("NET —", 10, "#9db6ce")
        for label in (self.cpu_label, self.ram_label, self.network_label):
            metrics_layout.addWidget(label)
        layout.addWidget(self.metrics_box)
        self.window_buttons: dict[str, QPushButton] = {}
        if window_controls:
            controls = QHBoxLayout()
            controls.setSpacing(1)
            for name, description, signal in (
                ("minimize", "Minimize window", self.minimize_requested),
                ("maximize", "Maximize or restore window", self.maximize_requested),
                ("close", "Close JARVIS", self.close_requested),
            ):
                button = QPushButton()
                button.setObjectName("WindowControl")
                button.setIcon(make_icon(name, "#b1c3d6", 17))
                button.setFixedSize(31, 30)
                button.setToolTip(description)
                button.setAccessibleName(description)
                button.setStyleSheet(
                    "QPushButton {background:transparent;border:0;padding:0;}"
                    "QPushButton:hover {background:#16354b;border-radius:5px;}"
                    "QPushButton:focus {border:1px solid #84d8ef;}"
                )
                button.clicked.connect(signal.emit)
                controls.addWidget(button)
                self.window_buttons[name] = button
            layout.addLayout(controls)

    def set_voice_state(self, text: str, *, muted: bool = False):
        self.state_label.setText(text)
        self.microphone_label.setPixmap(
            make_icon("mic-off" if muted else "mic", "#8396ad" if muted else "#50d8ff", 23).pixmap(
                QSize(23, 23)
            )
        )

    def set_maximized(self, maximized: bool):
        button = self.window_buttons.get("maximize")
        if button:
            button.setIcon(make_icon("restore" if maximized else "maximize", "#b1c3d6", 17))

    def resizeEvent(self, event):
        self.metrics_box.setVisible(self.width() >= 1080)
        self.subtitle_label.setVisible(self.width() >= 900)
        self.provider_box.setVisible(self.width() >= 780)
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, self.width(), 0)
        gradient.setColorAt(0, QColor("#05101a"))
        gradient.setColorAt(0.45, QColor("#071926"))
        gradient.setColorAt(1, QColor("#05101a"))
        painter.fillRect(self.rect(), gradient)
        painter.setPen(_pen("#153449", 1))
        painter.drawLine(
            QPointF(0, self.height() - 0.5), QPointF(self.width(), self.height() - 0.5)
        )
        painter.end()
