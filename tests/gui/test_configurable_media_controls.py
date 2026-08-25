import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence

from media_control_settings import PLAYBACK_FACTORS_KEY, SEEK_INTERVALS_KEY
from explorer_settings import EXPLORER_PAGE_SIZE_KEY
from shortcut_settings import (
    DEFAULT_LOCALIZATION_ACCEPT_SHORTCUT,
    DEFAULT_LOCALIZATION_REJECT_SHORTCUT,
    LOCALIZATION_ACCEPT_SHORTCUT_KEY,
    LOCALIZATION_REJECT_SHORTCUT_KEY,
)
from ui.dialogs import ApplicationSettingsDialog
from ui.media_player import MediaCenterPanel


@pytest.mark.gui
@pytest.mark.parametrize(
    ("rates", "expected_labels"),
    [
        ((0.5, 1.0, 2.0), ["0.5x", "1x", "2x"]),
        ((0.25, 0.5, 1.0, 2.0, 4.0), ["0.25x", "0.5x", "1x", "2x", "4x"]),
        (
            (0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0),
            ["0.125x", "0.25x", "0.5x", "1x", "2x", "4x", "8x"],
        ),
    ],
)
def test_media_panel_builds_ordered_speed_buttons(qtbot, rates, expected_labels):
    panel = MediaCenterPanel()
    qtbot.addWidget(panel)
    panel.configure_playback_controls(rates, (1.0, 5.0))

    assert [panel.playbackRowTwoLayout.itemAt(i).widget().text() for i in range(len(rates))] == expected_labels
    emitted = []
    panel.playbackRateRequested.connect(emitted.append)
    qtbot.mouseClick(panel.speed_buttons[rates[-1]], Qt.MouseButton.LeftButton)
    assert emitted == [rates[-1]]


@pytest.mark.gui
def test_media_panel_builds_symmetric_seek_buttons_in_one_row(qtbot):
    panel = MediaCenterPanel()
    qtbot.addWidget(panel)
    intervals = (1.0, 5.0, 10.0, 30.0, 60.0)
    panel.configure_playback_controls((1.0,), intervals)

    labels = [
        panel.playbackRowOneLayout.itemAt(index).widget().text()
        for index in range(panel.playbackRowOneLayout.count())
    ]
    assert labels == [
        "<< 60s", "<< 30s", "<< 10s", "<< 5s", "<< 1s",
        "Play/Pause",
        "1s >>", "5s >>", "10s >>", "30s >>", "60s >>",
    ]

    emitted = []
    panel.seekRelativeRequested.connect(emitted.append)
    qtbot.mouseClick(panel.seek_buttons[-30.0], Qt.MouseButton.LeftButton)
    qtbot.mouseClick(panel.seek_buttons[60.0], Qt.MouseButton.LeftButton)
    assert emitted == [-30000, 60000]


@pytest.mark.gui
def test_settings_dialog_validates_applies_normalizes_and_restores_defaults(qtbot):
    dialog = ApplicationSettingsDialog("2,4", "1,5", 750)
    qtbot.addWidget(dialog)
    applied = []
    page_sizes = []
    dialog.mediaControlsApplyRequested.connect(lambda *values: applied.append(values))
    dialog.explorerPageSizeApplyRequested.connect(page_sizes.append)

    dialog.playback_factors_edit.setText("2,")
    qtbot.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    assert applied == []
    assert dialog.validation_label.text()

    dialog.playback_factors_edit.setText(" 8, 2, 4 ")
    dialog.seek_intervals_edit.setText(" 5, 1, 10 ")
    dialog.explorer_page_size_spin.setValue(900)
    qtbot.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    assert applied[-1][:2] == ("2,4,8", "1,5,10")
    assert page_sizes == [900]
    assert dialog.result() == 0

    qtbot.mouseClick(dialog.restore_defaults_button, Qt.MouseButton.LeftButton)
    assert dialog.playback_factors_edit.text() == "2,4"
    assert dialog.seek_intervals_edit.text() == "1,5"
    assert dialog.explorer_page_size_spin.value() == 500
    assert len(applied) == 1


@pytest.mark.gui
def test_settings_dialog_validates_and_applies_localization_shortcuts(qtbot):
    dialog = ApplicationSettingsDialog("2,4", "1,5")
    qtbot.addWidget(dialog)
    applied = []
    dialog.shortcutSettingsApplyRequested.connect(
        lambda accept, reject: applied.append((accept, reject))
    )

    assert dialog.localization_accept_shortcut_edit.keySequence().toString() == (
        DEFAULT_LOCALIZATION_ACCEPT_SHORTCUT
    )
    assert dialog.localization_reject_shortcut_edit.keySequence().toString() == (
        DEFAULT_LOCALIZATION_REJECT_SHORTCUT
    )

    dialog.localization_accept_shortcut_edit.clear()
    qtbot.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    assert applied == []
    assert "are required" in dialog.shortcut_validation_label.text()

    dialog.localization_accept_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Enter"))
    dialog.localization_reject_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Enter"))
    qtbot.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    assert applied == []
    assert "must be different" in dialog.shortcut_validation_label.text()

    dialog.localization_reject_shortcut_edit.setKeySequence(QKeySequence("Ctrl+S"))
    qtbot.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    assert applied == []
    assert "built-in shortcut" in dialog.shortcut_validation_label.text()

    dialog.localization_reject_shortcut_edit.setKeySequence(
        QKeySequence("Ctrl+S, Ctrl+R")
    )
    qtbot.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    assert applied == []
    assert "built-in shortcut" in dialog.shortcut_validation_label.text()

    dialog.localization_accept_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Return"))
    dialog.localization_reject_shortcut_edit.setKeySequence(QKeySequence("Alt+Backspace"))
    qtbot.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    assert applied == [("Ctrl+Return", "Alt+Backspace")]

    qtbot.mouseClick(dialog.restore_defaults_button, Qt.MouseButton.LeftButton)
    assert dialog.localization_accept_shortcut_edit.keySequence().toString() == (
        DEFAULT_LOCALIZATION_ACCEPT_SHORTCUT
    )
    assert dialog.localization_reject_shortcut_edit.keySequence().toString() == (
        DEFAULT_LOCALIZATION_REJECT_SHORTCUT
    )


@pytest.mark.gui
def test_window_persists_and_restores_media_controls(window):
    window._save_and_apply_media_controls(
        "2,4,8",
        "1,5,10",
        (0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0),
        (1.0, 5.0, 10.0),
    )
    settings = window.dataset_explorer_controller.settings
    assert settings.value(PLAYBACK_FACTORS_KEY) == "2,4,8"
    assert settings.value(SEEK_INTERVALS_KEY) == "1,5,10"

    window.center_panel.configure_playback_controls((1.0,), (2.0,))
    window._restore_media_controls_from_settings()
    assert tuple(window.center_panel.speed_buttons) == (
        0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0
    )
    assert window._seek_intervals_seconds == (1.0, 5.0, 10.0)


@pytest.mark.gui
def test_window_persists_and_restores_explorer_page_size(window):
    window._save_and_apply_explorer_page_size(750)
    settings = window.dataset_explorer_controller.settings
    assert settings.value(EXPLORER_PAGE_SIZE_KEY) in (750, "750")
    assert window.tree_model.page_size() == 750

    settings.setValue(EXPLORER_PAGE_SIZE_KEY, 300)
    settings.sync()
    window._restore_explorer_settings_from_settings()
    assert window.tree_model.page_size() == 300


@pytest.mark.gui
def test_window_persists_restores_and_remaps_localization_shortcuts(window):
    window._save_and_apply_localization_review_shortcuts(
        "Alt+Enter", "Alt+Backspace"
    )
    settings = window.dataset_explorer_controller.settings
    assert settings.value(LOCALIZATION_ACCEPT_SHORTCUT_KEY) == "Alt+Enter"
    assert settings.value(LOCALIZATION_REJECT_SHORTCUT_KEY) == "Alt+Backspace"
    assert window.shortcut_localization_accept.key().toString() == "Alt+Enter"
    assert window.shortcut_localization_reject.key().toString() == "Alt+Backspace"

    settings.setValue(LOCALIZATION_ACCEPT_SHORTCUT_KEY, "Ctrl+Return")
    settings.setValue(LOCALIZATION_REJECT_SHORTCUT_KEY, "Ctrl+Delete")
    window._restore_shortcut_settings_from_settings()
    assert window.shortcut_localization_accept.key().toString() == "Ctrl+Return"
    assert window.shortcut_localization_reject.key().toString() == "Ctrl+Del"


@pytest.mark.gui
def test_apply_resets_only_a_removed_active_rate_and_remaps_shortcuts(window, monkeypatch):
    window.media_controller.set_playback_rate(4.0)
    window._apply_media_controls("2,4", "2,10", (0.25, 0.5, 1.0, 2.0, 4.0), (2.0, 10.0))
    assert window.media_controller.playback_rate() == 4.0

    deltas = []
    monkeypatch.setattr(window.media_controller, "seek_relative", deltas.append)
    window.shortcut_seek_back_primary.activated.emit()
    window.shortcut_seek_fwd_secondary.activated.emit()
    assert deltas == [-2000, 10000]

    window._apply_media_controls("2", "2", (0.5, 1.0, 2.0), (2.0,))
    assert window.media_controller.playback_rate() == 1.0
    assert window.shortcut_seek_back_secondary.isEnabled() is False
    assert window.shortcut_seek_fwd_secondary.isEnabled() is False

    window.shortcut_seek_back_primary.activated.emit()
    window.shortcut_seek_fwd_primary.activated.emit()
    assert deltas == [-2000, 10000, -2000, 2000]


@pytest.mark.gui
def test_shortcuts_help_uses_configured_intervals(window, monkeypatch):
    window._apply_media_controls("2", "2,10", (0.5, 1.0, 2.0), (2.0, 10.0))
    shown = []
    monkeypatch.setattr(
        "main_window.QMessageBox.information",
        lambda _parent, _title, text: shown.append(text),
    )
    window._show_shortcuts_popup()
    assert "Ctrl+Left: Seek backward 2 seconds" in shown[0]
    assert "Ctrl+Shift+Right: Seek forward 10 seconds" in shown[0]
    assert "Ctrl+Enter: Accept selected inferred annotation" in shown[0]
    assert "Ctrl+Backspace: Reject selected inferred annotation" in shown[0]
