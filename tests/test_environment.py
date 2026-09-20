"""OpenSportsLib environment inspection must remain read-only."""

import sys
from types import SimpleNamespace

import environment


def test_setup_opensportslib_runs_only_the_explicit_cli_command(monkeypatch):
    commands = []
    monkeypatch.setattr(
        environment.subprocess, "check_call", lambda command: commands.append(command)
    )
    environment.setup_opensportslib()
    assert commands == [["opensportslib", "setup"]]


def test_opensportslib_environment_status_reports_cuda_build(monkeypatch):
    versions = {
        "opensportslib": "0.3.1.dev12",
        "torch": "2.10.0+cu128",
    }
    monkeypatch.setattr(
        environment.importlib.metadata,
        "version",
        lambda name: versions[name],
    )
    fake_torch = SimpleNamespace(
        version=SimpleNamespace(cuda="12.8"),
        cuda=SimpleNamespace(
            is_available=lambda: True,
            get_device_name=lambda _index: "Test GPU",
        ),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    assert environment.opensportslib_environment_status() == {
        "opensportslib_version": "0.3.1.dev12",
        "torch_version": "2.10.0+cu128",
        "gpu_support_installed": True,
        "cuda_version": "12.8",
        "cuda_available": True,
        "gpu_name": "Test GPU",
    }


def test_opensportslib_environment_status_reports_cpu_build(monkeypatch):
    versions = {"opensportslib": "0.3.1.dev12", "torch": "2.10.0+cpu"}
    monkeypatch.setattr(
        environment.importlib.metadata,
        "version",
        lambda name: versions[name],
    )
    fake_torch = SimpleNamespace(
        version=SimpleNamespace(cuda=None),
        cuda=SimpleNamespace(is_available=lambda: False),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    status = environment.opensportslib_environment_status()
    assert status["gpu_support_installed"] is False
    assert status["cuda_available"] is False
    assert status["cuda_version"] == ""
