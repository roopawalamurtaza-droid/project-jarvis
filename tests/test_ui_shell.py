"""Native reference-shell behavior with no microphone or provider activity."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QLabel
from test_desktop import app as desktop_app

from jarvis.ui_shell import HeaderBar, NavButton, QuickActionCard, SidebarAtmosphere, make_icon

app = desktop_app


@pytest.fixture
def widgets(app):
    created = []
    yield created
    for widget in created:
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_navigation_remains_native_and_keyboard_accessible(app, widgets):
    button = NavButton("Assistant", "Chat · Voice · Vision", "home")
    widgets.append(button)
    button.resize(224, 62)
    button.show()
    button.setFocus()
    clicked = QSignalSpy(button.clicked)
    QTest.keyClick(button, Qt.Key.Key_Space)
    assert clicked.count() == 1
    assert button.isChecked()
    assert button.accessibleName() == "Assistant"
    assert button.accessibleDescription() == "Chat · Voice · Vision"
    button.setEnabled(False)
    QTest.keyClick(button, Qt.Key.Key_Space)
    assert clicked.count() == 1
    assert not button.grab().isNull()


def test_quick_action_dispatches_without_an_animation_delay(app, widgets):
    button = QuickActionCard("Open browser", "Configured browser", "browser")
    widgets.append(button)
    button.show()
    clicked = QSignalSpy(button.clicked)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert clicked.count() == 1
    assert button.sizeHint().height() == 84
    assert not button.isCheckable()
    button.set_reduce_motion(True)
    button._animate_hover(1)
    assert not button._animation.state() == button._animation.State.Running
    assert button._hover == 1


def test_hidden_button_stops_hover_animation(app, widgets):
    button = NavButton("Settings", "Personalize · Models · Tools", "settings")
    widgets.append(button)
    button.show()
    button._animate_hover(1)
    button.hide()
    assert not button._animation.state() == button._animation.State.Running
    assert button._hover == 0


@pytest.mark.parametrize("size", [16, 24, 48])
@pytest.mark.parametrize("name", ["assistant", "home", "browser", "settings", "mic-off", "book"])
def test_original_icon_has_renderable_dpi_variants(app, name, size):
    icon = make_icon(name, "#45c7ee", size)
    assert not icon.isNull()
    assert not icon.pixmap(QSize(size, size)).isNull()
    assert not icon.pixmap(QSize(size * 2, size * 2)).isNull()


def test_header_has_no_fabricated_measurements_or_duplicate_native_controls(app, widgets):
    header = HeaderBar("0.4.5")
    widgets.append(header)
    header.resize(1440, 56)
    header.show()
    app.processEvents()
    assert header.version_label.text() == "v0.4.5"
    assert header.state_label.text() == "Standby"
    assert header.model_label.text() == "Not checked"
    assert header.cpu_label.text() == "CPU —"
    assert header.network_label.text() == "NET —"
    assert header.window_buttons == {}
    assert all(
        label.textFormat() == Qt.TextFormat.PlainText for label in header.findChildren(QLabel)
    )
    header.model_label.setText("<img src='https://example.invalid/tracker'>")
    assert header.model_label.textFormat() == Qt.TextFormat.PlainText
    header.set_voice_state("Microphone muted", muted=True)
    assert header.state_label.text() == "Microphone muted"


def test_optional_header_control_signals_are_native_clicks(app, widgets):
    header = HeaderBar("0.4.5", window_controls=True)
    widgets.append(header)
    header.resize(1440, 56)
    header.show()
    for name, signal in (
        ("minimize", header.minimize_requested),
        ("maximize", header.maximize_requested),
        ("close", header.close_requested),
    ):
        spy = QSignalSpy(signal)
        QTest.mouseClick(header.window_buttons[name], Qt.MouseButton.LeftButton)
        assert spy.count() == 1
    header.set_maximized(True)
    assert not header.window_buttons["maximize"].icon().isNull()


def test_header_condenses_optional_information_before_overlapping(app, widgets):
    header = HeaderBar("0.4.5")
    widgets.append(header)
    header.resize(1440, 56)
    header.show()
    app.processEvents()
    assert header.metrics_box.isVisible()
    header.resize(760, 56)
    app.processEvents()
    assert header.metrics_box.isHidden()
    assert header.provider_box.isHidden()
    assert header.state_label.isVisible()
    assert header.brand_label.isVisible()


def test_atmosphere_fallback_paints_without_a_remote_asset(app, widgets, tmp_path):
    illustration = SidebarAtmosphere(art_path=tmp_path / "missing.jpg")
    widgets.append(illustration)
    illustration.resize(224, 248)
    illustration.show()
    app.processEvents()
    assert illustration._art.isNull()
    assert not illustration.grab().isNull()
    assert illustration.accessibleName() == "JARVIS atmospheric identity illustration"
    illustration.resize(180, 150)
    assert not illustration.grab().isNull()
