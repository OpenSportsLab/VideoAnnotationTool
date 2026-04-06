"""
Shared pytest fixtures for GUI smoke tests.

Key responsibilities:
- Force headless Qt (`QT_QPA_PLATFORM=offscreen`) for local/CI runs.
- Ensure app imports work from repo root by injecting `annotation_tool/` into `sys.path`.
- Stub `opensportslib` so lifecycle tests do not depend on ML runtime packages.
- Isolate `QSettings` storage to a per-test temp directory.
- Provide:
  - `window`: a ready `VideoAnnotationWindow` attached to `qtbot`
  - `synthetic_project_json`: tiny valid JSON payloads for each app mode
"""

import json
import os
import sys
import types
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "annotation_tool"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def _install_opensportslib_stub() -> None:
    """
    Provide a tiny opensportslib shim so main_window imports do not fail in tests.
    """
    if "opensportslib" in sys.modules:
        return

    class _DummyModelRunner:
        def infer(self, *args, **kwargs):
            return {}

        def train(self, *args, **kwargs):
            return {}

    def _factory(*args, **kwargs):
        return _DummyModelRunner()

    stub_module = types.ModuleType("opensportslib")
    stub_module.model = types.SimpleNamespace(
        classification=_factory,
        localization=_factory,
    )
    sys.modules["opensportslib"] = stub_module


_install_opensportslib_stub()



@pytest.fixture
def window(qtbot, monkeypatch):
    """
    Create and show the main window for GUI tests.

    Notes:
    - Media playback startup is patched out to avoid backend-specific hangs
      in headless environments.
    - Teardown clears dirty/loaded flags to avoid close confirmation dialogs.
    """
    # Avoid real media backend side effects in lifecycle smoke tests.
    monkeypatch.setattr(
        "controllers.media_controller.MediaController.load_and_play",
        lambda self, file_path, auto_play=True: None,
    )

    from main_window import VideoAnnotationWindow

    main_window = VideoAnnotationWindow()
    qtbot.addWidget(main_window)
    main_window.show()
    qtbot.wait(50)

    # Use a test-specific QSettings to isolate from real user data and ensure a clean slate.
    main_window.router.settings = QSettings(
        "OpenSportsLab_test",
        "VideoAnnotationTool_test",
    )

    yield main_window

    # Prevent close confirmation dialogs during teardown.
    main_window.model.is_data_dirty = False
    main_window.model.json_loaded = False
    main_window.close()


@pytest.fixture
def synthetic_project_json(tmp_path):
    """
    Factory fixture that writes a tiny valid JSON project for a given mode.

    Returns:
      Callable[[str], Path]
      Supported modes: classification, localization, description, dense_description.

    Design goals:
    - Keep schema minimal but valid for each mode validator.
    - Use a real test video path relative to the generated JSON file so
      path-resolution logic is exercised.
    """
    def _write(mode: str) -> Path:
        source_video_path = REPO_ROOT / "tests" / "data" / "test_video_1.mp4"
        if not source_video_path.exists():
            raise FileNotFoundError(f"Missing test asset: {source_video_path}")

        # Keep a relative path in JSON so loader path-resolution behavior is tested.
        rel_clip_path = os.path.relpath(source_video_path, start=tmp_path).replace("\\", "/")

        payload_by_mode = {
            "classification": {
                "version": "2.0",
                "date": "2026-04-06",
                "task": "action_classification",
                "description": "Synthetic classification fixture",
                "modalities": ["video"],
                "labels": {
                    "action": {
                        "type": "single_label",
                        "labels": ["pass", "shot"],
                    }
                },
                "data": [
                    {
                        "id": "clip_1",
                        "inputs": [
                            {
                                "path": rel_clip_path,
                                "type": "video",
                            }
                        ],
                        "labels": {},
                    }
                ],
            },
            "localization": {
                "version": "2.0",
                "date": "2026-04-06",
                "task": "action_spotting",
                "dataset_name": "synthetic_localization",
                "modalities": ["video"],
                "labels": {
                    "ball_action": {
                        "type": "single_label",
                        "labels": ["pass", "shot"],
                    }
                },
                "data": [
                    {
                        "id": "clip_1",
                        "inputs": [
                            {
                                "path": rel_clip_path,
                                "type": "video",
                                "fps": 25.0,
                            }
                        ],
                        "events": [
                            {
                                "head": "ball_action",
                                "label": "pass",
                                "position_ms": 1000,
                            }
                        ],
                    }
                ],
            },
            "description": {
                "version": "1.0",
                "date": "2026-04-06",
                "task": "video_captioning",
                "dataset_name": "synthetic_description",
                "metadata": {
                    "source": "pytest-qt",
                },
                "data": [
                    {
                        "id": "clip_1",
                        "inputs": [
                            {
                                "path": rel_clip_path,
                                "type": "video",
                                "fps": 25.0,
                            }
                        ],
                        "captions": [
                            {
                                "lang": "en",
                                "text": "A short test caption.",
                            }
                        ],
                        "metadata": {
                            "path": rel_clip_path,
                        },
                    }
                ],
            },
            "dense_description": {
                "version": "1.0",
                "date": "2026-04-06",
                "task": "dense_video_captioning",
                "dataset_name": "synthetic_dense",
                "metadata": {
                    "source": "pytest-qt",
                },
                "data": [
                    {
                        "id": "clip_1",
                        "inputs": [
                            {
                                "path": rel_clip_path,
                                "type": "video",
                                "fps": 25.0,
                            }
                        ],
                        "dense_captions": [
                            {
                                "position_ms": 1000,
                                "lang": "en",
                                "text": "A dense caption event.",
                            }
                        ],
                    }
                ],
            },
        }

        if mode not in payload_by_mode:
            raise ValueError(f"Unsupported mode: {mode}")

        project_path = tmp_path / f"{mode}_project.json"
        project_path.write_text(json.dumps(payload_by_mode[mode], indent=2), encoding="utf-8")
        return project_path

    return _write
