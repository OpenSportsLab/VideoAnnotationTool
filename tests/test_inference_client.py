import json
import tempfile
import threading
from pathlib import Path

import httpx
import pytest
import yaml

from inference_providers import (
    LocalInferenceProvider,
    RemoteInferenceProvider,
    RemoteVqaSessionCache,
)
from inference_settings import (
    LOCAL_MODELS_KEY,
    LOCAL_MODELS_SCHEMA_VERSION,
    LOCAL_MODELS_SCHEMA_VERSION_KEY,
    REMOTE_ENABLED_KEY,
    load_last_model_choice,
    load_localization_min_confidence_percent,
    load_local_models,
    save_last_model_choice,
    save_localization_min_confidence_percent,
)
from inference_types import (
    InferenceError,
    InferenceInput,
    InferenceItem,
    InferenceRequest,
    ModelDescriptor,
    validate_result_payload,
)
from controllers.dataset_explorer_controller import DatasetExplorerController
from controllers.inference_controller import InferenceController


class MemorySettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def value(self, key, default=""):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        pass


def _request(task, path, *, model_id="model"):
    return InferenceRequest(
        task=task,
        model_id=model_id,
        backend="remote",
        items=[InferenceItem("sample", [InferenceInput(str(path))], {"id": "sample"})],
    )


@pytest.mark.parametrize(
    ("task", "field", "value"),
    [
        ("classification", "labels", {"action": {"label": "shot"}}),
        ("localization", "events", [{"head": "action", "label": "shot", "position_ms": 1}]),
        ("description", "captions", [{"lang": "en", "text": "A shot."}]),
        ("dense_description", "dense_captions", [{"lang": "en", "text": "A shot.", "position_ms": 1}]),
        ("question_answer", "answer", {"text": "A shot."}),
    ],
)
def test_result_validation_accepts_all_task_native_shapes(tmp_path, task, field, value):
    request = _request(task, tmp_path / "video.mp4")
    result = validate_result_payload(
        request,
        {"items": [{"item_id": request.items[0].item_id, field: value}]},
    )
    assert result.task == task
    assert result.items[0][field] == value
    assert result.items[0]["sample_id"] == "sample"


def test_result_validation_correlates_reordered_items_and_overwrites_server_ids(tmp_path):
    request = InferenceRequest(
        task="description",
        model_id="model",
        backend="remote",
        items=[
            InferenceItem("sample-a", [InferenceInput(str(tmp_path / "a.mp4"))]),
            InferenceItem("sample-b", [InferenceInput(str(tmp_path / "b.mp4"))]),
        ],
    )
    first, second = request.items

    result = validate_result_payload(request, {"items": [
        {
            "item_id": second.item_id,
            "sample_id": "incorrect-server-id",
            "captions": [{"text": "B"}],
        },
        {
            "item_id": first.item_id,
            "sample_id": "also-incorrect",
            "captions": [{"text": "A"}],
        },
    ]})

    assert [item["sample_id"] for item in result.items] == ["sample-b", "sample-a"]
    assert [item["item_id"] for item in result.items] == [second.item_id, first.item_id]


def test_result_validation_supports_unique_sample_id_and_local_positional_fallback(tmp_path):
    remote = _request("description", tmp_path / "remote.mp4")
    by_sample = validate_result_payload(
        remote,
        {"items": [{"sample_id": "sample", "captions": [{"text": "Remote"}]}]},
    )
    assert by_sample.items[0]["item_id"] == remote.items[0].item_id

    local = InferenceRequest(
        task="description",
        model_id="model",
        backend="local",
        items=[InferenceItem("local-sample", [InferenceInput(str(tmp_path / "local.mp4"))])],
    )
    positional = validate_result_payload(
        local,
        {"data": [{"id": "legacy-osl-id", "captions": [{"text": "Local"}]}]},
    )
    assert positional.items[0]["sample_id"] == "local-sample"


@pytest.mark.parametrize("items", [
    [],
    [{"item_id": "unknown", "captions": [{"text": "Unknown"}]}],
])
def test_result_validation_rejects_missing_or_unknown_remote_items(tmp_path, items):
    request = _request("description", tmp_path / "video.mp4")
    with pytest.raises(InferenceError) as error:
        validate_result_payload(request, {"items": items})
    assert getattr(error.value, "code", "") == "invalid_result"


def test_result_validation_rejects_duplicate_request_item(tmp_path):
    request = InferenceRequest(
        task="description",
        model_id="model",
        backend="remote",
        items=[
            InferenceItem("sample-a", [InferenceInput(str(tmp_path / "a.mp4"))]),
            InferenceItem("sample-b", [InferenceInput(str(tmp_path / "b.mp4"))]),
        ],
    )
    duplicate_id = request.items[0].item_id
    with pytest.raises(InferenceError) as error:
        validate_result_payload(request, {"items": [
            {"item_id": duplicate_id, "captions": [{"text": "One"}]},
            {"item_id": duplicate_id, "captions": [{"text": "Duplicate"}]},
        ]})
    assert error.value.code == "invalid_result"


def test_local_provider_reports_missing_native_caption_apis():
    provider = LocalInferenceProvider(MemorySettings(), base_dir=str(Path(__file__).parents[1] / "annotation_tool"))
    description = provider.list_models("description")[0]
    dense = provider.list_models("dense_description")[0]
    assert description.available is False
    assert "DescriptionModel" in description.unavailable_reason
    assert dense.available is False
    assert "DenseDescriptionModel" in dense.unavailable_reason


def test_local_tracking_inference_uses_h5_offset_when_selected_video_is_ignored(
    monkeypatch,
    tmp_path,
):
    from controllers.localization import loc_inference as localization_module

    class FakeSignal:
        def __init__(self):
            self.callback = None

        def connect(self, callback):
            self.callback = callback

    class FakeWorker:
        def __init__(self, *_args, **_kwargs):
            self.finished_signal = FakeSignal()
            self.error_signal = FakeSignal()

        def run(self):
            self.finished_signal.callback(
                [{"label": "header", "position_ms": 1_250}]
            )

    monkeypatch.setattr(localization_module, "LocInferenceWorker", FakeWorker)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("DATA: {}\nMODEL: {}\nSYSTEM: {}\n", encoding="utf-8")
    provider = LocalInferenceProvider(
        MemorySettings(),
        local_models=[
            {
                "task": "localization",
                "id": "header-spotter",
                "display_name": "Header spotter",
                "config_path": str(config_path),
                "checkpoint_free": True,
            }
        ],
    )
    request = InferenceRequest(
        task="localization",
        model_id="header-spotter",
        backend="local",
        parameters={"head": "Actions", "labels": ["header"]},
        items=[
            InferenceItem(
                "sample",
                [
                    InferenceInput(str(tmp_path / "match.mp4"), "video"),
                    InferenceInput(
                        str(tmp_path / "tracking.h5"),
                        "player_joints_h5",
                        {"ball_path": str(tmp_path / "ball.h5")},
                    ),
                ],
                timeline_offset_ms=0,
                input_timeline_offsets_ms=(0, 300_000),
            )
        ],
    )

    result = provider.run(request, lambda *_args: None, threading.Event())

    assert result.items[0]["events"][0]["position_ms"] == 301_250


def test_local_vqa_uses_portable_runtime_config_and_opensportslib_03_answer(
    monkeypatch, tmp_path
):
    import opensportslib

    # This test exercises the "no CUDA" normalization branch of
    # configure_compute_device specifically; without mocking it, the
    # assertion below depends on whether the machine running the suite
    # happens to have a visible CUDA device.
    monkeypatch.setattr("controllers.inference_runtime.cuda_is_available", lambda: False)

    captured = {}

    class FakeVQAModel:
        def __init__(self, config):
            with open(config, encoding="utf-8") as handle:
                captured["config"] = yaml.safe_load(handle)

        def infer(self, **kwargs):
            captured["infer"] = kwargs
            return {"task": "vqa", "data": [{"answer_text": "A late tackle."}]}

    monkeypatch.setattr(
        opensportslib,
        "model",
        type("FakeModelModule", (), {"VQAModel": FakeVQAModel}),
        raising=False,
    )
    config_path = tmp_path / "vqa.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "TASK": "VQA",
                "SYSTEM": {
                    "device": "auto",
                    "paths": {
                        "save_dir": "/home/vorajv/checkpoints",
                        "work_dir": "/home/vorajv/checkpoints",
                    },
                },
                "MODEL": {"runtime": {"device": "auto", "dtype": "fp16"}},
                "TRAIN": {"execution": {"hf": {}}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    provider = LocalInferenceProvider(
        MemorySettings(),
        local_models=[{
            "task": "question_answer",
            "id": "OpenSportsLab/vqa",
            "display_name": "VQA",
            "config_path": str(config_path),
            "weights": str(tmp_path / "adapter.safetensors"),
        }],
    )
    request = InferenceRequest(
        task="question_answer",
        model_id="OpenSportsLab/vqa",
        backend="local",
        parameters={"question": "What happened?"},
        items=[InferenceItem("sample", [InferenceInput(str(video))])],
    )

    result = provider.run(request, lambda *_args: None, threading.Event())

    assert result.items[0]["answer"] == "A late tackle."
    assert captured["config"]["SYSTEM"]["device"] == "cpu"
    assert not captured["config"]["SYSTEM"]["paths"]["save_dir"].startswith(
        "/home/vorajv"
    )
    assert captured["config"]["MODEL"]["runtime"]["dtype"] == "float32"
    assert captured["infer"]["video_path"] == str(video)


def test_local_vqa_reports_missing_xvars_dependencies_before_model_start(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({
            "TASK": "VQA",
            "SYSTEM": {"device": "auto", "paths": {"save_dir": "/home/vorajv/out"}},
            "MODEL": {
                "components": {
                    "video_encoder": {
                        "kind": "encoder",
                        "load": {"weights_path": "/home/vorajv/X-VARS/weights/14_model.pth.tar"},
                    },
                    "llm_decoder": {
                        "kind": "decoder",
                        "params": {"repo_id": "/home/vorajv/X-VARS/weights/base_model_videoChatGPT"},
                    },
                }
            },
            "TRAIN": {
                "execution": {
                    "hf": {"tokenizer_id": "/home/vorajv/X-VARS/weights/base_model_videoChatGPT"}
                }
            },
        }, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(InferenceError) as error, tempfile.TemporaryDirectory() as runtime_dir:
        LocalInferenceProvider._build_vqa_runtime_config(
            str(config_path), runtime_dir
        )

    assert error.value.code == "local_model_dependency_missing"
    assert "publisher's machine" in str(error.value)
    assert len(error.value.details["missing"]) == 3


def test_local_model_registry_is_saved_only_and_filters_retired_entries(tmp_path):
    assert load_local_models(MemorySettings()) == []
    assert load_local_models(MemorySettings({LOCAL_MODELS_KEY: "[]"})) == []
    migrated = load_local_models(MemorySettings({
        LOCAL_MODELS_KEY: json.dumps([
            {
                "task": "classification",
                "id": "jeetv/snpro-classification-mvit",
                "config_path": "/tmp/old-classification.yaml",
            },
            {
                "task": "localization",
                "id": "jeetv/snpro-snbas-2024",
                "config_path": "/tmp/old-localization.yaml",
            },
        ])
    }))
    assert migrated == []

    former_opensportslab_defaults = load_local_models(MemorySettings({
        LOCAL_MODELS_KEY: json.dumps([
            {
                "task": "classification",
                "id": "OpenSportsLab/OSL-cls-action-mvitv2",
                "config_path": "/app/config.yaml",
                "weights": "OpenSportsLab/OSL-cls-action-mvitv2",
                "hf_repo_id": "OpenSportsLab/OSL-cls-action-mvitv2",
            },
            {
                "task": "localization",
                "id": "OpenSportsLab/OSL-loc-snbas-2025-e2e",
                "config_path": "/app/loc_config.yaml",
                "weights": "OpenSportsLab/OSL-loc-snbas-2025-e2e",
                "hf_repo_id": "OpenSportsLab/OSL-loc-snbas-2025-e2e",
            },
        ])
    }))
    assert former_opensportslab_defaults == []

    explicitly_saved_lazy_model = load_local_models(MemorySettings({
        LOCAL_MODELS_SCHEMA_VERSION_KEY: LOCAL_MODELS_SCHEMA_VERSION,
        LOCAL_MODELS_KEY: json.dumps([{
            "task": "classification",
            "id": "OpenSportsLab/OSL-cls-action-mvitv2",
            "config_path": "/custom/config.yaml",
            "weights": "OpenSportsLab/OSL-cls-action-mvitv2",
            "hf_repo_id": "OpenSportsLab/OSL-cls-action-mvitv2",
        }]),
    }))
    assert [model["id"] for model in explicitly_saved_lazy_model] == [
        "OpenSportsLab/OSL-cls-action-mvitv2"
    ]

    configured = load_local_models(MemorySettings({
        LOCAL_MODELS_KEY: json.dumps([{
            "task": "classification",
            "id": "custom/classifier",
            "display_name": "Custom",
            "config_path": str(tmp_path / "custom.yaml"),
        }])
    }))
    assert [model["id"] for model in configured] == [
        "custom/classifier",
    ]

    untrusted_override = load_local_models(MemorySettings({
        LOCAL_MODELS_KEY: json.dumps([{
            "task": "localization",
            "id": "OpenSportsLab/OSL-loc-snbas-2025-e2e",
            "weights": "someone/other-checkpoint",
        }])
    }))
    localization = next(
        model for model in untrusted_override if model["task"] == "localization"
    )
    assert localization["trusted_legacy"] is False

    untrusted_revision = load_local_models(MemorySettings({
        LOCAL_MODELS_KEY: json.dumps([{
            "task": "localization",
            "id": "OpenSportsLab/OSL-loc-snbas-2025-e2e",
            "hf_repo_id": "OpenSportsLab/OSL-loc-snbas-2025-e2e",
            "hf_revision": "experimental",
            "trusted_legacy": True,
        }])
    }))
    localization_2025 = next(
        model
        for model in untrusted_revision
        if model["id"] == "OpenSportsLab/OSL-loc-snbas-2025-e2e"
    )
    assert localization_2025["trusted_legacy"] is False


def test_local_discovery_uses_only_explicit_registry_entries(tmp_path):
    settings = MemorySettings({
        LOCAL_MODELS_KEY: json.dumps([{
            "task": "classification",
            "id": "custom/classifier",
            "display_name": "Custom",
            "config_path": str(tmp_path / "config.yaml"),
        }])
    })
    provider = LocalInferenceProvider(
        settings,
        base_dir=str(Path(__file__).parents[1] / "annotation_tool"),
    )
    classification = provider.list_models("classification")
    localization = provider.list_models("localization")
    assert [model.id for model in classification] == ["custom/classifier"]
    assert localization == []


def test_local_discovery_never_constructs_http_client(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("HTTP used for local inference")))
    controller = InferenceController(settings=MemorySettings(), base_dir=str(Path(__file__).parents[1] / "annotation_tool"))
    models = controller.discover_models("classification", "local", {"local_models": []})
    assert models == []


def test_combined_catalog_does_not_construct_http_client_when_remote_is_disabled(
    monkeypatch,
):
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("HTTP used while remote inference is disabled")
        ),
    )
    controller = InferenceController(
        settings=MemorySettings({
            REMOTE_ENABLED_KEY: False,
            LOCAL_MODELS_KEY: json.dumps([{
                "task": "classification",
                "id": "custom/classifier",
                "display_name": "Custom",
                "config_path": "/tmp/custom.yaml",
            }]),
        }),
        base_dir=str(Path(__file__).parents[1] / "annotation_tool"),
    )

    choices, warning = controller.discover_model_catalog("classification")

    assert choices
    assert {choice.backend for choice in choices} == {"local"}
    assert warning == ""


def test_combined_catalog_keeps_local_models_when_remote_discovery_fails(monkeypatch):
    controller = InferenceController(settings=MemorySettings())

    class Provider:
        def __init__(self, models=None, error=None):
            self.models = list(models or [])
            self.error = error

        def list_models(self, _task):
            if self.error:
                raise self.error
            return self.models

        def close(self):
            pass

    local = Provider([
        ModelDescriptor("same-id", "Local model", "classification"),
        ModelDescriptor(
            "unavailable", "Unavailable", "classification", available=False
        ),
    ])
    remote = Provider(error=RuntimeError("server unavailable"))
    monkeypatch.setattr(
        controller,
        "_provider",
        lambda backend, _config=None: local if backend == "local" else remote,
    )

    choices, warning = controller.discover_model_catalog(
        "classification", {"remote_enabled": True}
    )

    assert [(choice.backend, choice.descriptor.id) for choice in choices] == [
        ("local", "same-id")
    ]
    assert "unavailable Local model" in warning
    assert "server unavailable" in warning


def test_settings_remote_catalog_uses_unsaved_configuration(monkeypatch, tmp_path):
    controller = InferenceController(settings=MemorySettings())
    captured = {}

    class Provider:
        def list_models(self, task):
            return [ModelDescriptor(f"{task}-model", task, task)]

        def close(self):
            pass

    def provider(backend, config=None):
        captured["backend"] = backend
        captured["config"] = dict(config or {})
        return Provider()

    monkeypatch.setattr(controller, "_provider", provider)
    draft = {
        "remote_enabled": True,
        "server_url": "http://draft-server:9000",
        "local_models": [],
    }

    models = controller.discover_remote_catalog(draft)

    assert captured == {"backend": "remote", "config": draft}
    assert {(model.task, model.id) for model in models} == {
        (task, f"{task}-model")
        for task in (
            "classification",
            "localization",
            "description",
            "dense_description",
            "question_answer",
        )
    }


@pytest.mark.parametrize(
    ("action", "payload", "expected_method", "expected_kwargs"),
    [
        (
            "register_huggingface",
            {"task": "question_answer", "repository_id": "org/vqa"},
            "register_model",
            {"task_type": "vqa", "huggingface_model_id": "org/vqa"},
        ),
        (
            "register_local",
            {
                "task": "localization",
                "model_id": "local:model",
                "weights_path": "/srv/models/model.pth",
                "config_path": "/srv/models/config.yaml",
            },
            "register_model",
            {
                "task_type": "localization",
                "model_id": "local:model",
                "weights_path": "/srv/models/model.pth",
                "config_path": "/srv/models/config.yaml",
            },
        ),
        (
            "set_default",
            {"task": "classification", "model_id": "cls"},
            "set_default",
            {"task_type": "classification", "model_id": "cls"},
        ),
        (
            "unregister",
            {"task": "classification", "model_id": "cls"},
            "unregister_model",
            {"model_id": "cls"},
        ),
    ],
)
def test_remote_registry_operations_use_session_credentials_and_official_client(
    qtbot, monkeypatch, action, payload, expected_method, expected_kwargs
):
    calls = []

    class Registry:
        def __init__(self, remote, admin_token):
            calls.append(("init", {"remote": remote, "admin_token": admin_token}))

        def register_model(self, **kwargs):
            calls.append(("register_model", kwargs))
            return {"model_id": kwargs.get("model_id") or "registered"}

        def set_default(self, task_type, model_id):
            calls.append(
                ("set_default", {"task_type": task_type, "model_id": model_id})
            )
            return {"model_id": model_id}

        def unregister_model(self, model_id):
            calls.append(("unregister_model", {"model_id": model_id}))
            return {"model_id": model_id}

    monkeypatch.setattr("opensportslib.RemoteModelRegistry", Registry)
    controller = InferenceController(settings=MemorySettings())
    request = {
        **payload,
        "server_url": "http://server/",
        "admin_token": "session-secret",
    }
    with qtbot.waitSignal(
        controller.remoteModelOperationSucceeded, timeout=1000
    ) as completed:
        assert controller.request_remote_model_operation(action, request)

    assert completed.args[0] == action
    assert calls[0] == (
        "init",
        {"remote": "http://server", "admin_token": "session-secret"},
    )
    assert calls[1] == (expected_method, expected_kwargs)
    qtbot.waitUntil(lambda: controller.remote_registry_worker is None)
    assert controller.shutdown()


@pytest.mark.parametrize("status", [401, 409, 422, 503])
def test_remote_registry_operation_reports_admin_errors(qtbot, monkeypatch, status):
    class Registry:
        def __init__(self, _remote, admin_token):
            assert admin_token == "session-secret"

        def set_default(self, _task, _model_id):
            raise RuntimeError(f"Remote model registry returned HTTP {status}: rejected")

    monkeypatch.setattr("opensportslib.RemoteModelRegistry", Registry)
    controller = InferenceController(settings=MemorySettings())
    with qtbot.waitSignal(
        controller.remoteModelOperationFailed, timeout=1000
    ) as failed:
        assert controller.request_remote_model_operation(
            "set_default",
            {
                "server_url": "http://server",
                "admin_token": "session-secret",
                "task": "classification",
                "model_id": "model",
            },
        )

    assert failed.args[0] == "set_default"
    assert f"HTTP {status}" in failed.args[1]
    assert "session-secret" not in failed.args[1]
    qtbot.waitUntil(lambda: controller.remote_registry_worker is None)
    assert controller.shutdown()


def test_last_successful_model_choice_is_persisted_per_task():
    settings = MemorySettings()

    save_last_model_choice(settings, "classification", "local", "classifier")
    save_last_model_choice(settings, "localization", "remote", "detector")

    assert load_last_model_choice(settings, "classification") == (
        "local",
        "classifier",
    )
    assert load_last_model_choice(settings, "localization") == (
        "remote",
        "detector",
    )
    assert load_last_model_choice(settings, "description") is None


def test_localization_min_confidence_preference_is_bounded_and_persisted():
    settings = MemorySettings()
    assert load_localization_min_confidence_percent(settings) == 0.0

    save_localization_min_confidence_percent(settings, 75.25)
    assert load_localization_min_confidence_percent(settings) == 75.2
    save_localization_min_confidence_percent(settings, 150)
    assert load_localization_min_confidence_percent(settings) == 100.0
    settings.values["inference/localization_min_confidence_percent"] = "nan"
    assert load_localization_min_confidence_percent(settings) == 0.0


def test_inference_controller_owns_and_clears_remote_vqa_sessions():
    controller = InferenceController(settings=MemorySettings())
    provider = controller._provider(
        "remote", {"server_url": "http://127.0.0.1:8000/"}
    )
    key = ("server", "model", "sample", "path", 1, 2)
    provider._vqa_sessions.put(key, "session")

    assert provider.base_url == "http://127.0.0.1:8000"
    assert provider._vqa_sessions is controller._remote_vqa_sessions
    assert controller._remote_vqa_sessions.get(key) == "session"

    controller.clear_remote_sessions()
    assert controller._remote_vqa_sessions.get(key) is None
    provider.close()


def test_smart_qa_answer_normalization_preserves_metadata_and_manual_strings():
    normalized = DatasetExplorerController._normalize_sample_answers_payload([
        {
            "question": "What happened?",
            "answers": [
                "A pass.",
                {"text": "A shot.", "confidence_score": 1.5, "inference_model_id": "vqa"},
            ],
        }
    ])
    assert normalized == [{
        "question": "What happened?",
        "answers": [
            "A pass.",
            {"text": "A shot.", "confidence_score": 1.0, "inference_model_id": "vqa"},
        ],
    }]


def _remote_provider(task, model_id="model", *, sessions=None):
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500))
    )
    provider = RemoteInferenceProvider(
        "http://server", MemorySettings(), client=client, vqa_sessions=sessions
    )
    provider._catalog = [ModelDescriptor(model_id, model_id, task)]
    return provider


def test_official_server_discovery_maps_registry_states_defaults_and_vqa():
    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={
                "status": "ok",
                "redis_reachable": True,
                "worker_alive": True,
                "configured_models": ["cls-model", "vqa-model"],
            })
        if request.url.path == "/models":
            return httpx.Response(200, json={"models": [
                {
                    "model_id": "cls-model",
                    "task_type": "classification",
                    "status": "ready",
                    "generation": 3,
                },
                {
                    "model_id": "loc-model",
                    "task_type": "localization",
                    "status": "registering",
                    "generation": 1,
                },
                {
                    "model_id": "failed-model",
                    "task_type": "localization",
                    "status": "failed",
                    "error": "bad checkpoint",
                },
                {
                    "model_id": "vqa-model",
                    "task_type": "vqa",
                    "status": "ready",
                },
                {
                    "model_id": "retiring-model",
                    "task_type": "classification",
                    "status": "unregistering",
                },
            ]})
        if request.url.path == "/config-capabilities":
            assert "model_id" not in request.url.params
            task = str(request.url.params["task_type"])
            defaults = {"classification": "cls-model", "vqa": "vqa-model"}
            if task in defaults:
                return httpx.Response(
                    200, json={"model_id": defaults[task], "version": 1, "options": {}}
                )
            return httpx.Response(404, json={"detail": "no default"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    provider = RemoteInferenceProvider(
        "http://server",
        MemorySettings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    classification = provider.list_models("classification")
    assert [model.id for model in classification] == [
        "cls-model",
        "retiring-model",
    ]
    assert classification[0].available is True
    assert classification[0].is_default is True
    assert classification[0].version == "generation-3"
    assert classification[1].available is False
    assert classification[1].status == "unregistering"
    localization = provider.list_models("localization")
    assert [model.id for model in localization] == ["loc-model", "failed-model"]
    assert localization[0].supports_time_range is True
    assert localization[0].available is False
    assert "progress" in localization[0].unavailable_reason
    assert localization[1].unavailable_reason == "bad checkpoint"
    assert [model.id for model in provider.list_models("question_answer")] == ["vqa-model"]
    assert provider.list_models("description") == []
    assert provider.list_models("dense_description") == []
    assert localization[0].max_inputs is None
    assert provider.list_models("classification")[0].max_inputs is None
    assert provider.list_models("question_answer")[0].max_inputs == 1

    health = provider.discover_capabilities()
    assert health["redis_reachable"] is True
    assert health["worker_alive"] is True
    assert health["configured_models"] == ["cls-model", "vqa-model"]


@pytest.mark.parametrize("models_payload", [{}, {"models": ["bad"]}])
def test_remote_registry_rejects_malformed_catalog(models_payload):
    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "redis_reachable": True,
                    "worker_alive": True,
                },
            )
        if request.url.path == "/models":
            return httpx.Response(200, json=models_payload)
        if request.url.path == "/config-capabilities":
            return httpx.Response(404, json={"detail": "no default"})
        raise AssertionError(request.url)

    provider = RemoteInferenceProvider(
        "http://server",
        MemorySettings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(InferenceError) as error:
        provider.list_models("classification")
    assert error.value.code == "invalid_response"


def test_remote_registry_ready_model_is_unavailable_when_server_is_degraded():
    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={
                    "status": "degraded",
                    "redis_reachable": True,
                    "worker_alive": False,
                },
            )
        if request.url.path == "/models":
            return httpx.Response(200, json={"models": [{
                "model_id": "model",
                "task_type": "classification",
                "status": "ready",
            }]})
        if request.url.path == "/config-capabilities":
            return httpx.Response(404, json={"detail": "no default"})
        raise AssertionError(request.url)

    provider = RemoteInferenceProvider(
        "http://server",
        MemorySettings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    model = provider.list_models("classification")[0]
    assert model.status == "ready"
    assert model.available is False
    assert "worker or Redis" in model.unavailable_reason


def test_remote_registry_transitional_model_is_not_retryable(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    provider = _remote_provider("classification")
    provider._catalog = [
        ModelDescriptor(
            "model",
            "model",
            "classification",
            available=False,
            unavailable_reason="Model registration is still in progress.",
            status="registering",
        )
    ]

    with pytest.raises(InferenceError) as error:
        provider.run(_request("classification", video), lambda *_args: None)

    assert error.value.code == "model_unavailable"
    assert error.value.retryable is False


def test_remote_classification_uses_official_wrapper_and_normalizes_head(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    request = _request("classification", video, model_id="cls-model")
    request.parameters["head"] = "ball_action"
    request.schema = {
        "ball_action": {"type": "single_label", "labels": ["pass", "shot"]}
    }
    request.items[0].inputs[0].metadata["fps"] = 25
    captured = {}

    class Runner:
        def infer(self, **kwargs):
            captured.update(kwargs)
            return {"data": [{"labels": {"action": {"label": "shot", "confidence_score": 0.9}}}]}

    provider = _remote_provider("classification", "cls-model")
    monkeypatch.setattr(provider, "_build_runner", lambda _request: Runner())
    progress = []
    result = provider.run(request, lambda *args: progress.append(args), threading.Event())

    assert captured["video_path"] == str(video)
    assert captured["use_wandb"] is False
    options = captured["remote_task_options"]
    assert options["label_schema"] == {
        "action": {"type": "single_label", "labels": ["pass", "shot"]}
    }
    assert options["sample_id"] == "sample"
    assert options["fps"] == 25
    assert result.items[0]["sample_id"] == "sample"
    assert result.items[0]["labels"] == {
        "ball_action": {"label": "shot", "confidence_score": 0.9}
    }
    assert progress[-1] == ("Completed remote inference (1/1)", 1, 1)


def test_remote_wrapper_is_constructed_without_local_weights(monkeypatch):
    captured = {}

    class Runner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("opensportslib.apis.ClassificationModel", Runner)
    provider = _remote_provider("classification", "server-local:model")
    request = _request(
        "classification", "/unused.mp4", model_id="server-local:model"
    )

    built = provider._build_runner(request)

    assert isinstance(built, Runner)
    assert captured == {
        "remote": "http://server",
        "remote_model_id": "server-local:model",
    }


def test_remote_localization_clips_and_projects_events(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    clipped = tmp_path / "clip-range.mp4"
    clipped.write_bytes(b"range")
    request = InferenceRequest(
        task="localization",
        model_id="loc-model",
        backend="remote",
        items=[InferenceItem(
            "sample",
            [InferenceInput(str(video))],
            timeline_offset_ms=300_000,
            sample={"metadata": {"match": "final"}},
        )],
        parameters={"start_ms": 1_000, "end_ms": 3_000, "head": "play"},
        schema={"play": {"type": "single_label", "labels": ["header"]}},
    )
    captured = {}

    class ClipWorker:
        def __init__(self, *_args, **_kwargs):
            pass

        def _clip_video_if_needed(self, *_args, **_kwargs):
            return str(clipped), 1_000

    class Runner:
        def infer(self, **kwargs):
            captured.update(kwargs)
            return {"data": [{"events": [{
                "head": "action", "label": "header", "position_ms": 1_250
            }]}]}

    monkeypatch.setattr(
        "controllers.localization.loc_inference.LocInferenceWorker", ClipWorker
    )
    provider = _remote_provider("localization", "loc-model")
    monkeypatch.setattr(provider, "_build_runner", lambda _request: Runner())

    result = provider.run(request, lambda *_args: None, threading.Event())

    assert captured["video_path"] == str(clipped)
    assert captured["remote_task_options"]["label_schema"] == {
        "action": {"type": "single_label", "labels": ["header"]}
    }
    assert result.items[0]["events"] == [{
        "head": "play", "label": "header", "position_ms": 302_250
    }]


def test_remote_vqa_captures_and_reuses_video_session(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    sessions = RemoteVqaSessionCache()
    provider = _remote_provider("question_answer", "vqa-model", sessions=sessions)
    calls = []

    class Runner:
        last_remote_session_id = None

        def infer(self, **kwargs):
            calls.append(("infer", kwargs))
            if kwargs.get("video_path"):
                self.last_remote_session_id = "session-1"
                return {"data": [{"answer_text": "A pass."}]}
            return {"data": [{"answer_text": "A shot."}]}

    runner = Runner()
    monkeypatch.setattr(provider, "_build_runner", lambda _request: runner)
    first = _request("question_answer", video, model_id="vqa-model")
    first.parameters["question"] = "What happened first?"
    second = _request("question_answer", video, model_id="vqa-model")
    second.parameters["question"] = "What happened next?"

    first_result = provider.run(first, lambda *_args: None, threading.Event())
    second_result = provider.run(second, lambda *_args: None, threading.Event())

    assert first_result.items[0]["answer"] == "A pass."
    assert second_result.items[0]["answer"] == "A shot."
    assert [name for name, _payload in calls] == ["infer", "infer"]
    first_call = calls[0][1]
    assert first_call["video_path"] == str(video)
    assert first_call["question"] == "What happened first?"
    assert first_call["use_wandb"] is False
    followup = calls[-1][1]
    assert followup == {
        "question": "What happened next?",
        "session_id": "session-1",
    }


@pytest.mark.parametrize("status", [404, 410])
def test_remote_vqa_session_cache_isolated_expires_and_recovers_stale_session(
    tmp_path, monkeypatch, status
):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    now = [100.0]
    sessions = RemoteVqaSessionCache(clock=lambda: now[0])
    sessions.TTL_SECONDS = 10
    provider = _remote_provider("question_answer", "vqa-model", sessions=sessions)
    request = _request("question_answer", video, model_id="vqa-model")
    request.parameters["question"] = "Question?"
    key = provider._vqa_session_key(request, request.items[0])
    sessions.put(key, "stale")
    calls = []

    class Runner:
        last_remote_session_id = None

        def infer(self, **kwargs):
            calls.append(("infer", kwargs))
            if kwargs.get("session_id"):
                raise RuntimeError(
                    f"Remote server returned HTTP {status}: session expired"
                )
            self.last_remote_session_id = "fresh"
            return {"data": [{"answer_text": "Recovered"}]}

    monkeypatch.setattr(provider, "_build_runner", lambda _request: Runner())
    result = provider.run(request, lambda *_args: None, threading.Event())
    assert result.items[0]["answer"] == "Recovered"
    assert [name for name, _payload in calls] == ["infer", "infer"]
    assert sessions.get(key) == "fresh"

    other = provider._vqa_session_key(
        _request("question_answer", video, model_id="other-model"), request.items[0]
    )
    assert sessions.get(other) is None
    now[0] = 111.0
    assert sessions.get(key) is None


def test_remote_sends_multiple_videos_as_official_manifest(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    second = tmp_path / "second.mp4"
    video.write_bytes(b"video")
    second.write_bytes(b"video-2")
    provider = _remote_provider("classification")
    multiple = _request("classification", video)
    multiple.items[0].inputs.append(
        InferenceInput(str(second), metadata={"view": "reverse"})
    )
    captured = {}

    class Runner:
        def infer(self, **kwargs):
            captured.update(kwargs)
            with open(kwargs["test_set"], encoding="utf-8") as handle:
                captured["manifest"] = json.load(handle)
            return {"data": [{"labels": {"action": {"label": "shot"}}}]}

    monkeypatch.setattr(provider, "_build_runner", lambda _request: Runner())
    result = provider.run(multiple, lambda *_args: None, threading.Event())

    assert result.items[0]["labels"]["action"]["label"] == "shot"
    assert "video_path" not in captured
    assert captured["remote_mode"] == "full_test_set"
    inputs = captured["manifest"]["data"][0]["inputs"]
    assert [source["path"] for source in inputs] == [str(video), str(second)]
    assert inputs[1]["view"] == "reverse"


def test_remote_localization_clips_all_videos_before_manifest(tmp_path, monkeypatch):
    videos = [tmp_path / "front.mp4", tmp_path / "reverse.mp4"]
    for video in videos:
        video.write_bytes(b"video")
    request = InferenceRequest(
        task="localization",
        model_id="loc-model",
        backend="remote",
        items=[
            InferenceItem(
                "sample",
                [InferenceInput(str(video)) for video in videos],
                timeline_offset_ms=10_000,
            )
        ],
        parameters={"start_ms": 1_000, "end_ms": 3_000, "head": "play"},
    )
    clipped_sources = []
    captured = {}

    class ClipWorker:
        def __init__(self, path, *_args, **_kwargs):
            self.path = path

        def _clip_video_if_needed(self, output_dir):
            clipped = Path(output_dir) / Path(self.path).name
            clipped.write_bytes(b"clip")
            clipped_sources.append(str(clipped))
            return str(clipped), 1_000

    class Runner:
        def infer(self, **kwargs):
            with open(kwargs["test_set"], encoding="utf-8") as handle:
                captured.update(json.load(handle))
            return {
                "data": [
                    {
                        "events": [
                            {
                                "head": "action",
                                "label": "pass",
                                "position_ms": 250,
                            }
                        ]
                    }
                ]
            }

    monkeypatch.setattr(
        "controllers.localization.loc_inference.LocInferenceWorker", ClipWorker
    )
    provider = _remote_provider("localization", "loc-model")
    monkeypatch.setattr(provider, "_build_runner", lambda _request: Runner())

    result = provider.run(request, lambda *_args: None, threading.Event())

    manifest_paths = [source["path"] for source in captured["data"][0]["inputs"]]
    assert manifest_paths == clipped_sources
    assert result.items[0]["events"] == [
        {"head": "play", "label": "pass", "position_ms": 11_250}
    ]


def test_remote_rejects_non_video_and_multiple_vqa_inputs(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    provider = _remote_provider("classification")

    h5 = _request("classification", video)
    h5.items[0].inputs[0] = InferenceInput(str(video), "player_joints_h5")
    with pytest.raises(InferenceError, match="video inputs"):
        provider.run(h5, lambda *_args: None, threading.Event())

    vqa_provider = _remote_provider("question_answer")
    vqa = _request("question_answer", video)
    vqa.items[0].inputs.append(InferenceInput(str(video)))
    with pytest.raises(InferenceError, match="exactly one video"):
        vqa_provider.run(vqa, lambda *_args: None, threading.Event())


def test_remote_provider_discards_cancelled_item_before_starting_next(
    tmp_path, monkeypatch
):
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    first.write_bytes(b"video")
    second.write_bytes(b"video")
    request = InferenceRequest(
        task="classification",
        model_id="model",
        backend="remote",
        items=[
            InferenceItem("one", [InferenceInput(str(first))]),
            InferenceItem("two", [InferenceInput(str(second))]),
        ],
    )
    cancel = threading.Event()
    calls = []

    class Runner:
        def infer(self, **kwargs):
            calls.append(kwargs["video_path"])
            cancel.set()
            return {"data": [{"labels": {"action": {"label": "shot"}}}]}

    provider = _remote_provider("classification")
    monkeypatch.setattr(provider, "_build_runner", lambda _request: Runner())
    with pytest.raises(InferenceError) as error:
        provider.run(request, lambda *_args: None, cancel)
    assert error.value.code == "cancelled"
    assert calls == [str(first)]


def test_remote_malformed_result_and_network_error_mapping(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    request = _request("classification", video)
    provider = _remote_provider("classification")

    class Malformed:
        def infer(self, **_kwargs):
            return {"data": []}

    monkeypatch.setattr(provider, "_build_runner", lambda _request: Malformed())
    with pytest.raises(InferenceError) as malformed:
        provider.run(request, lambda *_args: None, threading.Event())
    assert malformed.value.code == "invalid_result"

    mapped = provider._inference_error(httpx.ConnectError("offline"))
    assert mapped.code == "network_error"
    assert mapped.retryable is True
    failed = provider._inference_error(
        RuntimeError("Remote inference job `job` failed: model crashed")
    )
    assert failed.code == "inference_error"
    assert failed.retryable is False
    bad_request = provider._inference_error(
        RuntimeError("Remote server returned HTTP 422: invalid options")
    )
    assert bad_request.code == "invalid_request"
    assert bad_request.retryable is False
