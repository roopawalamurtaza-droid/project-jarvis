"""Truthful measured graphics and UI-only floating assistant lifecycle checks."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget
from test_desktop import app as desktop_app

from jarvis.ui_components import CoreWidget, WaveformWidget
from jarvis.ui_mini import MiniAssistant

app = desktop_app


def dispose(app, widget):
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_dimensional_core_is_large_by_default_and_renders_compact(app):
    core = CoreWidget()
    try:
        assert core.sizeHint().width() == 350
        assert core.maximumWidth() > 350
        core.set_reduce_motion(True)
        core.resize(350, 350)
        core.show()
        app.processEvents()
        image = core.grab().toImage()
        assert not image.isNull()
        # The layered globe contains distinct shaded regions, not a single fill.
        colors = {
            image.pixelColor(x, y).rgba() for x in range(80, 271, 10) for y in range(80, 271, 10)
        }
        assert len(colors) > 50
        core.setMaximumHeight(110)
        core.resize(150, 110)
        app.processEvents()
        assert core.height() == 110
        assert not core.grab().isNull()
    finally:
        dispose(app, core)


def test_minimized_parent_stops_core_and_restore_resumes(app):
    parent = QWidget()
    layout = QVBoxLayout(parent)
    core = CoreWidget(parent)
    layout.addWidget(core)
    try:
        core.set_state("thinking")
        parent.show()
        app.processEvents()
        assert core.timer.isActive()
        assert core.timer.interval() <= 17
        parent.showMinimized()
        app.processEvents()
        assert not core.timer.isActive()
        parent.showNormal()
        app.processEvents()
        assert core.timer.isActive()
    finally:
        dispose(app, parent)


def test_waveform_changes_only_on_real_sample_calls(app):
    waveform = WaveformWidget()
    try:
        waveform.set_state("listening")
        waveform.set_level(0.021)
        waveform.set_level(0.053)
        waveform.show()
        original = tuple(waveform.samples)
        QTest.qWait(150)
        app.processEvents()
        assert tuple(waveform.samples) == original == (0.021, 0.053)
        assert waveform.level == pytest.approx(0.053)
        assert "Measured" in waveform.caption
        assert not waveform.grab().isNull()
        waveform.set_state("speaking")
        assert not waveform.samples
        assert waveform.level is None
        assert "unavailable" in waveform.caption
        QTest.qWait(50)
        assert not waveform.samples
    finally:
        dispose(app, waveform)


def test_waveform_bounds_and_invalid_samples_clear_history(app):
    waveform = WaveformWidget(sample_count=8)
    try:
        for _ in range(12):
            waveform.set_level(2)
        assert len(waveform.samples) == 8
        assert tuple(waveform.samples) == (1.0,) * 8
        waveform.set_level(-2)
        assert waveform.level == 0
        waveform.set_level(float("nan"))
        assert waveform.level is None
        assert not waveform.samples
        waveform.set_reduce_motion(True)
        waveform.set_level(0.25)
        assert waveform.reduce_motion and waveform.level == 0.25
        with pytest.raises(ValueError):
            waveform.set_state("fabricated_audio")
    finally:
        dispose(app, waveform)


def test_mini_assistant_only_emits_commands_and_displays_shared_state(app):
    parent = QWidget()
    mini = MiniAssistant(parent)
    try:
        assert mini.parent() is parent
        assert mini.windowFlags() & Qt.WindowType.Tool
        assert not hasattr(mini, "voice_runtime")
        expand = QSignalSpy(mini.expand_requested)
        settings = QSignalSpy(mini.settings_requested)
        mute = QSignalSpy(mini.mute_requested)
        dismiss = QSignalSpy(mini.dismiss_requested)
        mini.set_reduce_motion(True)
        mini.set_state("listening", "Listening…")
        mini.set_level(0.18)
        mini.show()
        app.processEvents()
        assert mini.label.text() == "Listening…"
        assert mini.core.level == mini.waveform.level == pytest.approx(0.18)
        assert not mini.core.timer.isActive()
        mini.expand_button.click()
        mini.settings_button.click()
        mini.mute_button.click()
        assert (expand.count(), settings.count(), mute.count()) == (1, 1, 1)
        mini.set_state("speaking")
        mini.clear_level()
        assert mini.waveform.level is None
        assert "no PCM" in mini.core.caption
        mini.set_always_on_top(True)
        assert mini.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert mini.isVisible()
        mini.dismiss_button.click()
        assert dismiss.count() == 1
        assert not mini.isVisible()
        assert not mini.core.timer.isActive()
    finally:
        dispose(app, parent)
