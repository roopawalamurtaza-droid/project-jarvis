"""Native message cards; Markdown never loads remote or local embedded media."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .ui_shell import make_icon


class SafeMarkdown(QTextBrowser):
    def __init__(self, content: str, parent=None):
        super().__init__(parent)
        self.setObjectName("MessageBody")
        self.setReadOnly(True)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
        self.document().setDefaultStyleSheet(
            "body{color:#dceaf6;} pre{background:#0c2335;color:#b9e9ff;} "
            "code{font-family:Consolas;} a{color:#38c8f3;}"
        )
        self.document().setMarkdown(content, QTextDocument.MarkdownFeature.MarkdownNoHTML)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.document().documentLayout().documentSizeChanged.connect(self._fit)
        self._fit()

    def loadResource(self, resource_type, name):
        # Untrusted model Markdown must not cause network requests or local reads.
        return None

    def _fit(self, *_):
        self.setFixedHeight(min(420, max(34, int(self.document().size().height()) + 12)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.document().setTextWidth(max(40, self.viewport().width() - 8))
        self._fit()


class ChatTranscript(QScrollArea):
    replay_requested = Signal(str)
    link_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Conversation")
        self.setWidgetResizable(True)
        self.setAccessibleName("Conversation history")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._surface = QWidget()
        self._surface.setObjectName("TranscriptSurface")
        self._layout = QVBoxLayout(self._surface)
        self._layout.setContentsMargins(4, 4, 8, 4)
        self._layout.setSpacing(10)
        self._layout.addStretch()
        self.setWidget(self._surface)
        self._messages: list[tuple[str, str, QWidget]] = []
        self._stream_row = None
        self._stream_text = ""
        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(60)
        self._stream_timer.timeout.connect(self._flush_stream)

    def append_message(self, role: str, content: str, timestamp: str | None = None):
        content = str(content)[:100000]
        row = QWidget()
        row.setObjectName("MessageRow")
        row._content = content
        horizontal = QHBoxLayout(row)
        horizontal.setContentsMargins(0, 0, 0, 0)
        horizontal.setSpacing(10)
        avatar = QLabel("▽" if role == "JARVIS" else "A" if role == "YOU" else "!")
        avatar.setObjectName("AssistantAvatar" if role == "JARVIS" else "UserAvatar")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFixedSize(40, 40)
        if role == "JARVIS":
            avatar.setPixmap(make_icon("assistant", "#43d2ff", 26).pixmap(26, 26))
        horizontal.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
        card = QFrame()
        card.setObjectName("AssistantMessage" if role == "JARVIS" else "UserMessage")
        body = QVBoxLayout(card)
        body.setContentsMargins(12, 8, 12, 6)
        body.setSpacing(2)
        header = QHBoxLayout()
        name = QLabel(role)
        name.setTextFormat(Qt.TextFormat.PlainText)
        name.setObjectName("MessageAuthor")
        header.addWidget(name)
        header.addStretch()
        date = QLabel(timestamp or datetime.now().strftime("%I:%M %p").lstrip("0"))
        date.setObjectName("Muted")
        date.setTextFormat(Qt.TextFormat.PlainText)
        header.addWidget(date)
        body.addLayout(header)
        text = SafeMarkdown(content)
        row._body = text
        row._actions = []
        text.anchorClicked.connect(lambda url: self.link_requested.emit(url.toString()))
        body.addWidget(text)
        if role == "JARVIS":
            controls = QHBoxLayout()
            controls.addStretch()
            copy = QPushButton("Copy")
            copy.setObjectName("MessageAction")
            copy.setAccessibleName("Copy assistant message")
            copy.clicked.connect(lambda: QApplication.clipboard().setText(row._content))
            replay = QPushButton("Speak")
            replay.setObjectName("MessageAction")
            replay.setAccessibleName("Replay assistant speech")
            replay.clicked.connect(lambda: self.replay_requested.emit(row._content))
            controls.addWidget(copy)
            controls.addWidget(replay)
            body.addLayout(controls)
            row._actions = [copy, replay]
        horizontal.addWidget(card, 1)
        self._layout.insertWidget(self._layout.count() - 1, row)
        self._messages.append((role, content, row))
        while len(self._messages) > 200:
            _, _, old = self._messages.pop(0)
            self._layout.removeWidget(old)
            old.deleteLater()
        QTimer.singleShot(0, self.ensureCursorVisible)
        return row

    def append_stream_delta(self, delta: str):
        if not self._stream_row:
            self._stream_row = self.append_message("JARVIS", "")
            for action in self._stream_row._actions:
                action.setEnabled(False)
        self._stream_text = (self._stream_text + delta)[:100000]
        if not self._stream_timer.isActive():
            self._stream_timer.start()

    def _flush_stream(self):
        row = self._stream_row
        if row is None or row._content == self._stream_text:
            return
        row._content = self._stream_text
        row._body.document().setMarkdown(
            self._stream_text, QTextDocument.MarkdownFeature.MarkdownNoHTML
        )
        for index, (role, _, item) in enumerate(self._messages):
            if item is row:
                self._messages[index] = (role, self._stream_text, row)
                break
        self.ensureCursorVisible()

    def finish_stream(self, content):
        if self._stream_row is None:
            return False
        self._stream_text = str(content)[:100000]
        self._flush_stream()
        for action in self._stream_row._actions:
            action.setEnabled(True)
        self._stream_timer.stop()
        self._stream_row = None
        self._stream_text = ""
        return True

    def cancel_stream(self):
        self._stream_timer.stop()
        row = self._stream_row
        if row is not None:
            self._messages = [
                (role, text, item) for role, text, item in self._messages if item is not row
            ]
            self._layout.removeWidget(row)
            row.deleteLater()
        self._stream_row = None
        self._stream_text = ""

    def toPlainText(self):
        return "\n\n".join(role + "\n" + content for role, content, _ in self._messages)

    def clear(self):
        self.cancel_stream()
        for _, _, row in self._messages:
            self._layout.removeWidget(row)
            row.deleteLater()
        self._messages.clear()

    def ensureCursorVisible(self):
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
