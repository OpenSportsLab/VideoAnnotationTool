"""Application versions and explicit OpenSportsLib setup UI."""

from types import SimpleNamespace

from ui.dialogs import ApplicationInfoDialog
from PyQt6.QtWidgets import QLabel


def _status(**overrides):
    status = {
        "opensportslib_version": "0.3.1.dev12",
        "torch_version": "2.10.0+cu128",
        "gpu_support_installed": True,
        "cuda_version": "12.8",
        "cuda_available": True,
        "gpu_name": "Test GPU",
    }
    status.update(overrides)
    return status


def test_application_info_dialog_reports_gpu_and_requests_setup(qtbot):
    dialog = ApplicationInfoDialog("VAT", "1.2.3", _status())
    qtbot.addWidget(dialog)

    text = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "Installed (CUDA 12.8)" in text
    assert "Available (Test GPU)" in text
    assert dialog.setup_button.text() == "Set Up OpenSportsLib"
    assert dialog.setup_requested is False

    dialog.setup_button.click()
    assert dialog.setup_requested is True


def test_application_info_dialog_disables_setup_while_running(qtbot):
    dialog = ApplicationInfoDialog(
        "VAT", "1.2.3",
        _status(gpu_support_installed=False, cuda_version="", cuda_available=False),
        setup_running=True,
    )
    qtbot.addWidget(dialog)
    assert dialog.setup_button.isEnabled() is False
    assert dialog.setup_button.text() == "Setup in progress…"


def test_main_window_info_dialog_routes_explicit_setup_request(monkeypatch):
    from main_window import VideoAnnotationWindow

    opened = []
    started = []

    class FakeInfoDialog:
        setup_requested = True

        def __init__(self, *args, **kwargs):
            opened.append((args, kwargs))

        def exec(self):
            return 0

    monkeypatch.setattr("main_window.ApplicationInfoDialog", FakeInfoDialog)
    monkeypatch.setattr(
        "main_window.opensportslib_environment_status", lambda: _status()
    )
    owner = SimpleNamespace(
        _opensportslib_setup_worker=None,
        _start_opensportslib_setup=lambda: started.append(True),
    )

    VideoAnnotationWindow._show_info_popup(owner)

    assert len(opened) == 1
    assert opened[0][1]["setup_running"] is False
    assert started == [True]
