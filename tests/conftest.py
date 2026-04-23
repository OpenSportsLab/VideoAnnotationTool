"""
Shared pytest fixtures for GUI smoke tests.

Key responsibilities:
- Force headless Qt (`QT_QPA_PLATFORM=offscreen`) for local/CI runs.
- Ensure app imports work from repo root by injecting `annotation_tool/` into `sys.path`.
- Stub only `opensportslib.model` so lifecycle tests do not depend on ML runtime packages.
- Isolate `QSettings` storage to a per-test temp directory.
- Provide:
  - `window`: a ready `VideoAnnotationWindow` attached to `qtbot`
  - `synthetic_project_json`: tiny valid JSON payloads for each app mode
"""

import json
import os
import sys
import types
from itertools import cycle, islice
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
    Replace only ``opensportslib.model`` with a tiny shim for GUI tests.

    This keeps the real ``opensportslib`` package available so non-GUI tests can
    still import ``opensportslib.tools`` and other submodules.
    """
    try:
        import opensportslib
    except Exception:
        return

    class _DummyModelRunner:
        def infer(self, *args, **kwargs):
            return {}

        def train(self, *args, **kwargs):
            return {}

    def _factory(*args, **kwargs):
        return _DummyModelRunner()

    opensportslib.model = types.SimpleNamespace(
        classification=_factory,
        localization=_factory,
    )


_install_opensportslib_stub()



@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
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

    # Use a test-specific QSettings file to isolate from real user data and ensure a clean slate.
    settings_file = tmp_path / "app_settings.ini"
    main_window.dataset_explorer_controller.settings = QSettings(
        str(settings_file),
        QSettings.Format.IniFormat,
    )
    main_window._test_settings_file = str(settings_file)

    yield main_window

    # Prevent close confirmation dialogs during teardown.
    main_window.dataset_explorer_controller.is_data_dirty = False
    main_window.dataset_explorer_controller.json_loaded = False
    main_window.close()


@pytest.fixture
def synthetic_project_json(tmp_path):
    """
    Factory fixture that writes a tiny valid JSON project for a given mode.

    Returns:
      Callable[[str], Path]
      Supported modes: classification, localization, description, dense_description, question_answer.

    Design goals:
    - Keep schema minimal but valid for each mode validator.
    - Use a real test video path relative to the generated JSON file so
      path-resolution logic is exercised.
    """
    def _write(mode: str, item_count: int = 1) -> Path:
        if item_count < 1:
            raise ValueError("item_count must be >= 1")

        source_video_paths = [
            REPO_ROOT / "tests" / "data" / "test_video_1.mp4",
            REPO_ROOT / "tests" / "data" / "test_video_2.mp4",
            REPO_ROOT / "tests" / "data" / "test_video_3.mp4",
        ]
        for source_video_path in source_video_paths:
            if not source_video_path.exists():
                raise FileNotFoundError(f"Missing test asset: {source_video_path}")

        selected_sources = list(islice(cycle(source_video_paths), item_count))
        rel_clip_paths = [
            os.path.relpath(source_video_path, start=tmp_path).replace("\\", "/")
            for source_video_path in selected_sources
        ]
        extra_rel_clip_paths = [
            os.path.relpath(source_video_path, start=tmp_path).replace("\\", "/")
            for source_video_path in source_video_paths[:2]
        ]

        classification_data = []
        localization_data = []
        description_data = []
        dense_data = []
        qa_data = []
        for idx, rel_clip_path in enumerate(rel_clip_paths, start=1):
            clip_id = f"clip_{idx}"
            classification_data.append(
                {
                    "id": clip_id,
                    "inputs": [{"path": rel_clip_path, "type": "video"}],
                    "labels": {},
                }
            )
            localization_data.append(
                {
                    "id": clip_id,
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
            )
            description_data.append(
                {
                    "id": clip_id,
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
                            "text": "A short test caption." if idx == 1 else f"A short test caption {idx}.",
                        }
                    ],
                    "metadata": {
                        "path": rel_clip_path,
                    },
                }
            )
            dense_data.append(
                {
                    "id": clip_id,
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
                            "text": "A dense caption event." if idx == 1 else f"A dense caption event {idx}.",
                        }
                    ],
                }
            )
            qa_data.append(
                {
                    "id": clip_id,
                    "inputs": [
                        {
                            "path": rel_clip_path,
                            "type": "video",
                            "fps": 25.0,
                        }
                    ],
                    "answers": [
                        {
                            "question_id": "q1",
                            "answer": "I am fine." if idx == 1 else f"Answer {idx}",
                        }
                    ],
                }
            )

        mixed_data = []
        for idx, rel_clip_path in enumerate(rel_clip_paths, start=1):
            sample = {
                "id": f"clip_{idx}",
                "inputs": [
                    {
                        "path": rel_clip_path,
                        "type": "video",
                        "fps": 25.0,
                    }
                ],
                "metadata": {
                    "note": f"keep-sample-{idx}",
                },
                "custom_sample": {"keep": True, "index": idx},
            }
            if idx == 1:
                sample.update(
                    {
                        "labels": {
                            "action": {"label": "shot", "confidence_score": 0.8},
                        },
                        "events": [
                            {"head": "ball_action", "label": "pass", "position_ms": 1000},
                            {"head": "ball_action", "label": "shot", "position_ms": 2000, "confidence_score": 0.7},
                        ],
                        "captions": [
                            {"lang": "en", "text": "Mixed caption"},
                        ],
                        "dense_captions": [
                            {"position_ms": 1500, "lang": "en", "text": "Mixed dense caption"},
                        ],
                        "answers": [
                            {"question_id": "q1", "answer": "Mixed answer"},
                        ],
                    }
                )
            mixed_data.append(sample)

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
                "data": classification_data,
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
                "data": localization_data,
            },
            "description": {
                "version": "1.0",
                "date": "2026-04-06",
                "task": "video_captioning",
                "dataset_name": "synthetic_description",
                "metadata": {
                    "source": "pytest-qt",
                },
                "data": description_data,
            },
            "dense_description": {
                "version": "1.0",
                "date": "2026-04-06",
                "task": "dense_video_captioning",
                "dataset_name": "synthetic_dense",
                "metadata": {
                    "source": "pytest-qt",
                },
                "data": dense_data,
            },
            "question_answer": {
                "version": "2.0",
                "date": "2026-04-06",
                "task": "video_question_answering",
                "dataset_name": "synthetic_question_answer",
                "modalities": ["video"],
                "metadata": {
                    "source": "pytest-qt",
                },
                "questions": [
                    {"id": "q1", "question": "How are you?"},
                    {"id": "q2", "question": "What happened?"},
                ],
                "data": qa_data,
            },
            "mixed": {
                "version": "2.0",
                "date": "2026-04-06",
                "task": "video_captioning",
                "dataset_name": "synthetic_mixed",
                "description": "Synthetic mixed annotation fixture",
                "modalities": ["video"],
                "metadata": {
                    "source": "pytest-qt",
                    "owner": "qa",
                },
                "custom_root": {"keep": True},
                "labels": {
                    "action": {
                        "type": "single_label",
                        "labels": ["pass", "shot"],
                    },
                    "ball_action": {
                        "type": "single_label",
                        "labels": ["pass", "shot"],
                    },
                },
                "questions": [
                    {"id": "q1", "question": "How are you?"},
                    {"id": "q2", "question": "What happened?"},
                ],
                "data": mixed_data,
            },
            "multiview": {
                "version": "2.0",
                "date": "2026-04-06",
                "task": "action_classification",
                "dataset_name": "synthetic_multiview",
                "modalities": ["video"],
                "labels": {
                    "action": {
                        "type": "single_label",
                        "labels": ["pass", "shot"],
                    }
                },
                "data": [
                    {
                        "id": "mv_clip",
                        "inputs": [
                            {"path": extra_rel_clip_paths[0], "type": "video"},
                            {"path": extra_rel_clip_paths[1], "type": "video"},
                        ],
                        "labels": {},
                    }
                ],
            },
            "duplicate_id": {
                "version": "2.0",
                "date": "2026-04-06",
                "task": "action_classification",
                "dataset_name": "synthetic_duplicate_id",
                "modalities": ["video"],
                "labels": {
                    "action": {
                        "type": "single_label",
                        "labels": ["pass", "shot"],
                    }
                },
                "data": [
                    {
                        "id": "clip_dup",
                        "inputs": [{"path": extra_rel_clip_paths[0], "type": "video"}],
                    },
                    {
                        "id": "clip_dup",
                        "inputs": [{"path": extra_rel_clip_paths[1], "type": "video"}],
                    },
                ],
            },
            "missing_id": {
                "version": "2.0",
                "date": "2026-04-06",
                "task": "action_classification",
                "dataset_name": "synthetic_missing_id",
                "modalities": ["video"],
                "labels": {
                    "action": {
                        "type": "single_label",
                        "labels": ["pass", "shot"],
                    }
                },
                "data": [
                    {
                        "inputs": [{"path": extra_rel_clip_paths[0], "type": "video"}],
                    },
                    {
                        "inputs": [{"path": extra_rel_clip_paths[1], "type": "video"}],
                    },
                ],
            },
        }

        if mode not in payload_by_mode:
            raise ValueError(f"Unsupported mode: {mode}")

        project_path = tmp_path / f"{mode}_project.json"
        project_path.write_text(json.dumps(payload_by_mode[mode], indent=2), encoding="utf-8")
        return project_path

    return _write
