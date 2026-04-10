import pytest
from PyQt6.QtCore import Qt


@pytest.mark.gui
def test_mute_button_toggles_media_controller_and_updates_label(window, qtbot):
    assert window.center_panel.btn_mute.text() == ""
    assert window.center_panel.btn_mute.toolTip() == "Mute"
    assert window.center_panel.btn_mute.accessibleName() == "Mute"
    assert window.media_controller.is_muted() is False

    mute_states = []
    window.media_controller.muteStateChanged.connect(mute_states.append)

    qtbot.mouseClick(window.center_panel.btn_mute, Qt.MouseButton.LeftButton)
    qtbot.wait(20)
    assert window.media_controller.is_muted() is True
    assert window.center_panel.btn_mute.text() == ""
    assert window.center_panel.btn_mute.toolTip() == "Unmute"
    assert window.center_panel.btn_mute.accessibleName() == "Unmute"
    assert mute_states == [True]

    qtbot.mouseClick(window.center_panel.btn_mute, Qt.MouseButton.LeftButton)
    qtbot.wait(20)
    assert window.media_controller.is_muted() is False
    assert window.center_panel.btn_mute.text() == ""
    assert window.center_panel.btn_mute.toolTip() == "Mute"
    assert window.center_panel.btn_mute.accessibleName() == "Mute"
    assert mute_states == [True, False]


@pytest.mark.gui
def test_media_controller_set_muted_is_idempotent(window, qtbot):
    window.media_controller.set_muted(False)
    qtbot.wait(10)

    mute_states = []
    window.media_controller.muteStateChanged.connect(mute_states.append)

    window.media_controller.set_muted(False)
    qtbot.wait(10)
    assert mute_states == []

    window.media_controller.set_muted(True)
    qtbot.wait(10)
    assert mute_states == [True]

    window.media_controller.set_muted(True)
    qtbot.wait(10)
    assert mute_states == [True]

    window.media_controller.set_muted(False)
    qtbot.wait(10)
    assert mute_states == [True, False]


@pytest.mark.gui
def test_media_controller_mute_signal_updates_button_text(window, qtbot):
    window.media_controller.muteStateChanged.emit(True)
    qtbot.wait(10)
    assert window.center_panel.btn_mute.text() == ""
    assert window.center_panel.btn_mute.toolTip() == "Unmute"
    assert window.center_panel.btn_mute.accessibleName() == "Unmute"

    window.media_controller.muteStateChanged.emit(False)
    qtbot.wait(10)
    assert window.center_panel.btn_mute.text() == ""
    assert window.center_panel.btn_mute.toolTip() == "Mute"
    assert window.center_panel.btn_mute.accessibleName() == "Mute"
