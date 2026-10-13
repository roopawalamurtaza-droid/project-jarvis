"""Native presence component tests without microphone or AI provider access."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel
from test_desktop import app as desktop_app

from jarvis.ui_components import CoreWidget, metric_card

app = desktop_app


@pytest.fixture
def core(app):
    widget = CoreWidget()
    widget.resize(260, 190)
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


@pytest.mark.parametrize(
    "state",
    [
        "idle",
        "wake",
        "activated",
        "listening",
        "thinking",
        "tool",
        "speaking",
        "approval",
        "error",
        "muted",
    ],
)
def test_explicit_state_survives_reduced_motion(core, state):
    core.set_reduce_motion(True)
    core.set_state(state)
    core.show()
    assert core.state == state
    assert not core.timer.isActive()


def test_hidden_core_does_not_animate_and_resumes_visible_state(app, core):
    core.set_state("thinking")
    assert not core.timer.isActive()
    core.show()
    app.processEvents()
    assert core.timer.isActive()
    core.hide()
    app.processEvents()
    assert not core.timer.isActive()
    core.show()
    app.processEvents()
    assert core.state == "thinking"
    assert core.timer.isActive()


def test_reduce_motion_stays_disabled_across_hidden_and_state_changes(app, core):
    core.show()
    core.set_state("thinking")
    assert core.timer.isActive()
    core.set_reduce_motion(True)
    assert not core.timer.isActive()
    core.hide()
    core.set_state("speaking")
    core.show()
    app.processEvents()
    assert core.state == "speaking"
    assert not core.timer.isActive()
    core.set_reduce_motion(False)
    assert core.timer.isActive()


def test_idle_redraw_rate_is_bounded(core):
    core.set_state("idle")
    core.show()
    assert core.timer.interval() >= 100


@pytest.mark.parametrize("state", ["muted", "error", "approval"])
def test_important_static_states_do_not_run_an_idle_timer(core, state):
    core.set_state(state)
    core.show()
    assert core.state == state
    assert not core.timer.isActive()


def test_measured_level_does_not_become_a_simulated_waveform(app, core):
    core.set_state("listening")
    core.set_level(0.42)
    core.show()
    QTest.qWait(200)
    app.processEvents()
    assert core.level == pytest.approx(0.42)
    core.clear_level()
    QTest.qWait(100)
    assert core.level is None


def test_core_fits_the_compact_overlay_height(app, core):
    core.setMaximumHeight(110)
    core.resize(240, 110)
    core.set_reduce_motion(True)
    core.show()
    app.processEvents()
    assert core.height() <= 110
    assert core.minimumHeight() <= 110
    # Native paint must work at compact dimensions without needing remote art.
    assert not core.grab().isNull()


def test_metric_card_keeps_external_text_literal(app):
    value = "<img src='https://untrusted.invalid/tracker'>"
    card = metric_card("Measured value", value, "Unavailable until sampled")
    labels = card.findChildren(QLabel)
    assert any(label.text() == value for label in labels)
    assert all(label.textFormat() == Qt.TextFormat.PlainText for label in labels)
    card.deleteLater()
    app.processEvents()
