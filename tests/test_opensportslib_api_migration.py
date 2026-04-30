import types
import subprocess

import yaml

from controllers.classification import inference_manager as classification_inference_module
from controllers.classification import train_manager as classification_train_module
from controllers.localization import loc_inference as localization_inference_module


def test_classification_inference_helper_uses_class_model_and_weights(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    calls = {}

    class _FakeClassificationModel:
        def __init__(self, config):
            calls["config"] = config

        def infer(self, **kwargs):
            calls["infer_kwargs"] = kwargs
            return {
                "data": [
                    {
                        "id": "sample_1",
                        "labels": {"action": {"label": "Dive", "confidence": 0.88}},
                    }
                ]
            }

    monkeypatch.setattr(
        classification_inference_module,
        "model",
        types.SimpleNamespace(ClassificationModel=_FakeClassificationModel),
    )

    base_config_path = tmp_path / "base_config.yaml"
    base_config_path.write_text(
        "SYSTEM:\n  log_dir: ./logs\n  save_dir: ./temp_workspace/checkpoints\n",
        encoding="utf-8",
    )
    temp_data = {"data": [{"id": "sample_1"}]}

    metrics, pred_data = classification_inference_module._run_opensportslib_inference(
        str(base_config_path),
        temp_data,
        "infer",
        "OpenSportsLab/some-classifier",
    )

    assert calls["config"].endswith(".yaml")
    assert calls["infer_kwargs"]["weights"] == "OpenSportsLab/some-classifier"
    assert calls["infer_kwargs"]["use_wandb"] is False
    assert calls["infer_kwargs"]["test_set"].endswith(".json")
    assert "pretrained" not in calls["infer_kwargs"]
    assert metrics == {}
    assert pred_data["data"][0]["id"] == "sample_1"


def test_train_worker_uses_class_model_and_explicit_split_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    calls = {}

    class _FakeClassificationModel:
        def __init__(self, config):
            calls["config_path"] = config
            with open(config, "r", encoding="utf-8") as handle:
                calls["runtime_config"] = yaml.safe_load(handle) or {}

        def train(self, **kwargs):
            calls["train_kwargs"] = kwargs
            print("Epoch 1/1")
            print("1/1 [")
            return {}

    monkeypatch.setattr(
        classification_train_module,
        "model",
        types.SimpleNamespace(ClassificationModel=_FakeClassificationModel),
    )

    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    train_json = dataset_dir / "annotations_train.json"
    valid_json = dataset_dir / "annotations_valid.json"
    train_json.write_text('{"data": []}', encoding="utf-8")
    valid_json.write_text('{"data": []}', encoding="utf-8")

    base_config_path = tmp_path / "config.yaml"
    base_config_path.write_text(
        yaml.safe_dump(
            {
                "DATA": {
                    "data_dir": "",
                    "train": {"dataloader": {"batch_size": 1, "num_workers": 0}},
                    "annotations": {},
                },
                "TRAIN": {
                    "save_dir": "",
                    "epochs": 1,
                    "optimizer": {"lr": 0.0001},
                },
                "SYSTEM": {"log_dir": "", "save_dir": "", "device": "cpu"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    worker = classification_train_module.TrainWorker(
        str(base_config_path),
        {
            "epochs": "2",
            "lr": "0.001",
            "batch": "4",
            "device": "cpu",
            "workers": "0",
            "train_json": str(train_json),
            "valid_json": str(valid_json),
        },
    )
    worker.run()

    runtime_config = calls["runtime_config"]
    expected_checkpoint_dir = str((dataset_dir / "checkpoints").as_posix())
    expected_log_dir = str((dataset_dir / "logs").as_posix())
    assert runtime_config["SYSTEM"]["save_dir"] == expected_checkpoint_dir
    assert runtime_config["SYSTEM"]["log_dir"] == expected_log_dir

    assert calls["train_kwargs"] == {
        "train_set": str(train_json),
        "valid_set": str(valid_json),
        "use_wandb": False,
    }


def test_localization_worker_uses_class_model_weights_and_position_fallback(monkeypatch, tmp_path):
    import opensportslib

    calls = {}

    class _FakeLocalizationModel:
        def __init__(self, config):
            calls["config"] = config

        def infer(self, **kwargs):
            calls["infer_kwargs"] = kwargs
            return {
                "data": [
                    {
                        "events": [
                            {"label": "pass", "position": 1200, "confidence": 0.75},
                            {"label": "pass", "position_ms": 0, "confidence": 0.99},
                        ]
                    }
                ]
            }

    monkeypatch.setattr(
        opensportslib,
        "model",
        types.SimpleNamespace(LocalizationModel=_FakeLocalizationModel),
        raising=False,
    )

    config_path = tmp_path / "loc_config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "dali": False,
                "DATA": {
                    "classes": ["pass", "shot"],
                    "test": {"dataloader": {"batch_size": 1, "num_workers": 0}},
                },
                "MODEL": {},
                "SYSTEM": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"")

    worker = localization_inference_module.LocInferenceWorker(
        video_path=str(video_path),
        start_ms=0,
        end_ms=0,
        config_path=str(config_path),
        model_id="OpenSportsLab/some-localizer",
        head_name="ball_action",
        labels=["pass", "shot"],
        input_fps=25.0,
    )

    finished_payloads = []
    worker.finished_signal.connect(lambda payload: finished_payloads.append(payload))
    worker.run()

    assert calls["infer_kwargs"]["weights"] == "OpenSportsLab/some-localizer"
    assert calls["infer_kwargs"]["use_wandb"] is False
    assert calls["infer_kwargs"]["test_set"].endswith("temp_test.json")
    assert len(finished_payloads) == 1
    assert finished_payloads[0] == [
        {
            "head": "ball_action",
            "label": "pass",
            "position_ms": 1200,
            "confidence_score": 0.75,
        }
    ]


def test_localization_worker_clip_falls_back_to_reencode(monkeypatch, tmp_path):
    import opensportslib

    calls = {"commands": []}

    class _FakeLocalizationModel:
        def __init__(self, config):
            calls["config"] = config

        def infer(self, **kwargs):
            calls["infer_kwargs"] = kwargs
            return {"data": [{"events": [{"label": "pass", "position_ms": 250}]}]}

    def _fake_run(command, capture_output=False, text=False, check=False, **_kwargs):
        calls["commands"].append(command)
        if command[-3:-1] == ["-c", "copy"]:
            raise subprocess.CalledProcessError(254, command, stderr="copy failed")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        opensportslib,
        "model",
        types.SimpleNamespace(LocalizationModel=_FakeLocalizationModel),
        raising=False,
    )
    monkeypatch.setattr(localization_inference_module, "_resolve_ffmpeg_executable", lambda: "ffmpeg")
    monkeypatch.setattr(localization_inference_module.subprocess, "run", _fake_run)

    config_path = tmp_path / "loc_config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "dali": False,
                "DATA": {
                    "classes": ["pass", "shot"],
                    "test": {"dataloader": {"batch_size": 1, "num_workers": 0}},
                },
                "MODEL": {},
                "SYSTEM": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video")

    worker = localization_inference_module.LocInferenceWorker(
        video_path=str(video_path),
        start_ms=1000,
        end_ms=4000,
        config_path=str(config_path),
        model_id="OpenSportsLab/some-localizer",
        head_name="ball_action",
        labels=["pass", "shot"],
        input_fps=25.0,
    )

    finished_payloads = []
    worker.finished_signal.connect(lambda payload: finished_payloads.append(payload))
    worker.run()

    assert len(calls["commands"]) == 2
    assert calls["commands"][0][-3:-1] == ["-c", "copy"]
    fallback_command = calls["commands"][1]
    assert fallback_command[fallback_command.index("-c:v") : fallback_command.index("-c:v") + 2] == [
        "-c:v",
        "libx264",
    ]
    assert fallback_command[fallback_command.index("-preset") : fallback_command.index("-preset") + 4] == [
        "-preset",
        "veryfast",
        "-crf",
        "23",
    ]
    assert fallback_command[fallback_command.index("-c:a") : fallback_command.index("-c:a") + 2] == [
        "-c:a",
        "aac",
    ]
    assert calls["infer_kwargs"]["weights"] == "OpenSportsLab/some-localizer"
    assert finished_payloads == [
        [
            {
                "head": "ball_action",
                "label": "pass",
                "position_ms": 1250,
                "confidence_score": 1.0,
            }
        ]
    ]
