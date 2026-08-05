import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import yaml

SCRIPT_PATH = Path(__file__).parents[1] / "tools" / "test-inference.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("test_inference_tool", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_config_uses_annotation_directory_and_preserves_device(tmp_path):
    script = _load_script()

    source_root = tmp_path / "dataset" / "test"
    source_root.mkdir(parents=True)
    test_set = source_root / "annotations.json"
    test_set.write_text('{"data": []}', encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "DATA": {
                    "data_dir": "/home/publisher/dataset",
                    "test": {
                        "path": "/home/publisher/test.json",
                        "video_path": "/home/publisher/test",
                        "dataloader": {"num_workers": 8, "pin_memory": True},
                    },
                    "common": {
                        "splits": {
                            "test": {
                                "annotation_path": "/old/annotations.json",
                                "source_path": "/old/data",
                                "dataloader": {"num_workers": 4},
                            }
                        }
                    },
                },
                "SYSTEM": {
                    "log_dir": "/home/publisher/logs",
                    "save_dir": "/home/publisher/checkpoints",
                    "device": "auto",
                    "GPU": 4,
                    "gpu_id": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    runtime_path = tmp_path / "runtime" / "runtime.yaml"
    runtime_path.parent.mkdir()
    script._write_runtime_config(
        config_path,
        runtime_path,
        test_set=str(test_set),
    )

    runtime = yaml.safe_load(runtime_path.read_text(encoding="utf-8"))
    assert runtime["DATA"]["data_dir"] == str(source_root)
    assert runtime["DATA"]["test"]["path"] == str(test_set)
    assert runtime["DATA"]["test"]["video_path"] == str(source_root)
    assert runtime["DATA"]["test"]["dataloader"] == {
        "num_workers": 0,
        "pin_memory": False,
        "shuffle": False,
    }
    canonical_test = runtime["DATA"]["common"]["splits"]["test"]
    assert canonical_test["annotation_path"] == str(test_set)
    assert canonical_test["source_path"] == str(source_root)
    assert canonical_test["dataloader"] == {
        "num_workers": 0,
        "pin_memory": False,
        "shuffle": False,
    }
    assert runtime["SYSTEM"]["device"] == "auto"
    assert runtime["SYSTEM"]["GPU"] == 4
    assert runtime["SYSTEM"]["gpu_id"] == 0
    assert runtime["SYSTEM"]["save_dir"].startswith(str(runtime_path.parent))


def test_hugging_face_weight_identifier_is_not_treated_as_a_file():
    script = _load_script()
    assert script._resolve_weights_path("OpenSportsLab/model-name") == "OpenSportsLab/model-name"


def test_parser_exposes_only_minimal_inference_controls():
    script = _load_script()
    help_text = script._build_parser().format_help()

    for removed_option in (
        "--data-root",
        "--num-workers",
        "--use-wandb",
        "--use-ddp",
        "--video-path",
    ):
        assert removed_option not in help_text
    assert "--question" in help_text


def test_classification_inference_disables_wandb_and_omits_ddp(
    monkeypatch, tmp_path
):
    script = _load_script()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({"DATA": {}, "MODEL": {}, "SYSTEM": {}}),
        encoding="utf-8",
    )
    test_set = tmp_path / "annotations.json"
    test_set.write_text('{"data": []}', encoding="utf-8")
    output_path = tmp_path / "predictions.json"
    calls = {}

    class FakeModel:
        def infer(self, **kwargs):
            calls["infer"] = kwargs
            return {"data": []}

        def save_predictions(self, **kwargs):
            calls["save"] = kwargs
            return kwargs["output_path"]

    monkeypatch.setattr(script, "_build_model", lambda *_args: FakeModel())
    monkeypatch.setattr(
        script.sys,
        "argv",
        [
            "test-inference.py",
            "--task",
            "classification",
            "--config",
            str(config_path),
            "--test-set",
            str(test_set),
            "--output",
            str(output_path),
        ],
    )

    script.main()

    assert calls["infer"] == {
        "test_set": str(test_set),
        "weights": None,
        "use_wandb": False,
    }
    assert calls["save"]["output_path"] == str(output_path)


def test_vqa_asks_question_for_every_json_sample_with_one_model_load(
    monkeypatch, tmp_path
):
    script = _load_script()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({"TASK": "VQA", "DATA": {}, "MODEL": {}, "SYSTEM": {}}),
        encoding="utf-8",
    )
    for name in ("clip_0.mp4", "clip_1.mp4"):
        (tmp_path / name).write_bytes(b"video")
    test_set = tmp_path / "annotations.json"
    test_set.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "id": "sample_0",
                        "inputs": [{"type": "video", "path": "clip_0.mp4"}],
                        "answers": [{"question": "Old?", "answers": ["Old"]}],
                    },
                    {
                        "id": "sample_1",
                        "inputs": [{"type": "video", "path": "clip_1.mp4"}],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "vqa_predictions.json"
    calls = {"build_count": 0, "infer_count": 0}

    class FakeModel:
        def infer(self, **kwargs):
            calls["infer_count"] += 1
            calls["infer"] = kwargs
            with open(kwargs["test_set"], encoding="utf-8") as handle:
                calls["dataset"] = yaml.safe_load(handle)
            return {"data": []}

        def save_predictions(self, **kwargs):
            return kwargs["output_path"]

    def fake_build(*_args):
        calls["build_count"] += 1
        return FakeModel()

    monkeypatch.setattr(script, "_build_model", fake_build)
    monkeypatch.setattr(
        script.sys,
        "argv",
        [
            "test-inference.py",
            "--task",
            "vqa",
            "--config",
            str(config_path),
            "--test-set",
            str(test_set),
            "--question",
            "Was this a foul?",
            "--output",
            str(output_path),
        ],
    )

    script.main()

    assert calls["build_count"] == 1
    assert calls["infer_count"] == 1
    assert calls["infer"]["use_wandb"] is False
    assert calls["infer"]["weights"] is None
    assert [sample["answers"] for sample in calls["dataset"]["data"]] == [
        [{"question": "Was this a foul?", "answers": []}],
        [{"question": "Was this a foul?", "answers": []}],
    ]


def test_hf_model_download_resolves_config_and_weights(monkeypatch, tmp_path):
    script = _load_script()
    config_path = tmp_path / "config.yaml"
    weights_path = tmp_path / "model.pth.tar"
    calls = []

    def fake_download(repo_id, revision, token, force_download):
        calls.append((repo_id, revision, token, force_download))
        return {
            "task": "classification",
            "config_path": str(config_path),
            "weights": str(weights_path),
        }

    monkeypatch.setattr(script, "_download_hf_artifacts", fake_download)
    args = SimpleNamespace(
        task="classification",
        config=None,
        weights=None,
        hf_model="OpenSportsLab/classifier",
        hf_revision="v2",
        hf_token="hf_private",
        force_download=True,
    )

    assert script._resolve_model_artifacts(args) == (
        str(config_path),
        str(weights_path),
    )
    assert calls == [
        ("OpenSportsLab/classifier", "v2", "hf_private", True)
    ]


def test_hf_model_rejects_conflicting_paths_and_task_mismatch(monkeypatch):
    script = _load_script()
    args = SimpleNamespace(
        task="classification",
        config="local.yaml",
        weights=None,
        hf_model="owner/model",
        hf_revision="main",
        hf_token=None,
        force_download=False,
    )

    try:
        script._resolve_model_artifacts(args)
    except ValueError as exc:
        assert "cannot be combined" in str(exc)
    else:
        raise AssertionError("Expected conflicting model sources to fail")

    args.config = None
    monkeypatch.setattr(
        script,
        "_download_hf_artifacts",
        lambda *_args: {
            "task": "localization",
            "config_path": "/config.yaml",
            "weights": "/model.pt",
        },
    )
    try:
        script._resolve_model_artifacts(args)
    except ValueError as exc:
        assert "model task is 'localization'" in str(exc)
    else:
        raise AssertionError("Expected a model task mismatch to fail")


def test_hf_only_options_require_hf_model():
    script = _load_script()
    args = SimpleNamespace(
        task="classification",
        config=None,
        weights=None,
        hf_model=None,
        hf_revision="main",
        hf_token=None,
        force_download=True,
    )

    try:
        script._resolve_model_artifacts(args)
    except ValueError as exc:
        assert "require --hf-model" in str(exc)
    else:
        raise AssertionError("Expected Hugging Face-only options to fail")
