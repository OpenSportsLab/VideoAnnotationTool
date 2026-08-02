import json
import hashlib
import threading
from pathlib import Path

import httpx
import pytest

from inference_providers import LocalInferenceProvider, RemoteInferenceProvider
from inference_settings import (
    LOCAL_MODELS_KEY,
    REMOTE_ENABLED_KEY,
    SHARED_MAPPINGS_KEY,
    UPLOAD_MANIFESTS_KEY,
    load_last_model_choice,
    load_local_models,
    save_last_model_choice,
)
from inference_types import (
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
    result = validate_result_payload(request, {"items": [{field: value}]})
    assert result.task == task
    assert result.items[0][field] == value
    assert result.items[0]["sample_id"] == "sample"


def test_local_provider_reports_missing_native_caption_apis():
    provider = LocalInferenceProvider(MemorySettings(), base_dir=str(Path(__file__).parents[1] / "annotation_tool"))
    description = provider.list_models("description")[0]
    dense = provider.list_models("dense_description")[0]
    assert description.available is False
    assert "DescriptionModel" in description.unavailable_reason
    assert dense.available is False
    assert "DenseDescriptionModel" in dense.unavailable_reason


def test_known_working_local_models_are_fresh_install_defaults(tmp_path):
    models = load_local_models(MemorySettings())
    assert [(model["task"], model["id"]) for model in models] == [
        ("classification", "jeetv/snpro-classification-mvit"),
        ("localization", "jeetv/snpro-snbas-2024"),
    ]
    assert models[0]["config_path"].endswith("config.yaml")
    assert models[1]["config_path"].endswith("loc_config.yaml")
    assert models[0].get("trusted_legacy", False) is False
    assert models[1]["trusted_legacy"] is True

    # Existing empty profiles are upgraded with the defaults.
    assert load_local_models(MemorySettings({LOCAL_MODELS_KEY: "[]"})) == models

    configured = load_local_models(MemorySettings({
        LOCAL_MODELS_KEY: json.dumps([{
            "task": "classification",
            "id": "custom/classifier",
            "display_name": "Custom",
            "config_path": str(tmp_path / "custom.yaml"),
        }])
    }))
    assert [model["id"] for model in configured] == [
        "jeetv/snpro-classification-mvit",
        "jeetv/snpro-snbas-2024",
        "custom/classifier",
    ]

    untrusted_override = load_local_models(MemorySettings({
        LOCAL_MODELS_KEY: json.dumps([{
            "task": "localization",
            "id": "jeetv/snpro-snbas-2024",
            "weights": "someone/other-checkpoint",
        }])
    }))
    localization = next(
        model for model in untrusted_override if model["task"] == "localization"
    )
    assert localization["trusted_legacy"] is False


def test_default_registry_does_not_duplicate_builtin_local_discovery():
    provider = LocalInferenceProvider(
        MemorySettings(),
        base_dir=str(Path(__file__).parents[1] / "annotation_tool"),
    )
    classification = provider.list_models("classification")
    localization = provider.list_models("localization")
    assert [model.id for model in classification] == ["jeetv/snpro-classification-mvit"]
    assert [model.id for model in localization] == ["jeetv/snpro-snbas-2024"]
    assert localization[0].trusted_legacy is True


def test_local_discovery_never_constructs_http_client(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("HTTP used for local inference")))
    controller = InferenceController(settings=MemorySettings(), base_dir=str(Path(__file__).parents[1] / "annotation_tool"))
    models = controller.discover_models("classification", "local", {"local_models": []})
    assert models and models[0].task == "classification"


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
        settings=MemorySettings({REMOTE_ENABLED_KEY: False}),
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
        "shared_mappings": [
            {"local_root": str(tmp_path), "root_id": "draft-root"}
        ],
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


def test_request_scoped_remote_mapping_does_not_use_saved_mapping(tmp_path):
    saved_root = tmp_path / "saved"
    draft_root = tmp_path / "draft"
    saved_root.mkdir()
    draft_root.mkdir()
    target = draft_root / "clip.mp4"
    target.write_bytes(b"video")
    settings = MemorySettings({SHARED_MAPPINGS_KEY: json.dumps([{"local_root": str(saved_root), "root_id": "saved"}])})
    provider = RemoteInferenceProvider(
        "http://server", settings,
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(500))),
        shared_mappings=[{"local_root": str(draft_root), "root_id": "draft"}],
    )
    assert provider._shared_asset(str(target)) == {"kind": "shared", "uri": "shared://draft/clip.mp4"}


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


def test_remote_provider_prefers_shared_mapping_and_polls_job(tmp_path):
    media_root = tmp_path / "media"
    media_root.mkdir()
    video = media_root / "clip.mp4"
    video.write_bytes(b"video")
    settings = MemorySettings({
        SHARED_MAPPINGS_KEY: json.dumps([{"local_root": str(media_root), "root_id": "datasets"}]),
    })
    submitted = {}

    def handler(request: httpx.Request):
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(200, json={"version": "1", "poll_interval_seconds": 0.01})
        if request.url.path.endswith("/jobs") and request.method == "POST":
            submitted.update(json.loads(request.content))
            return httpx.Response(200, json={"id": "job-1"})
        if request.url.path.endswith("/jobs/job-1"):
            return httpx.Response(200, json={
                "status": "succeeded",
                "result": {"items": [{"captions": [{"lang": "en", "text": "Caption"}]}]},
            })
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = RemoteInferenceProvider("http://server", settings, client=client)
    result = provider.run(_request("description", video), lambda *_args: None, threading.Event())

    assert result.items[0]["captions"][0]["text"] == "Caption"
    asset = submitted["items"][0]["inputs"][0]["asset"]
    assert asset == {"kind": "shared", "uri": "shared://datasets/clip.mp4"}


def test_remote_provider_streams_multipart_and_persists_completed_asset(tmp_path):
    video = tmp_path / "large.bin"
    video.write_bytes(b"0123456789")
    settings = MemorySettings()
    uploaded = {}
    completed_body = {}

    def handler(request: httpx.Request):
        path = request.url.path
        if path.endswith("/capabilities"):
            return httpx.Response(200, json={
                "multipart_part_size": 4,
                "max_parallel_parts": 2,
                "poll_interval_seconds": 0.01,
            })
        if path.endswith("/uploads") and request.method == "POST":
            return httpx.Response(200, json={
                "id": "upload-1",
                "part_size": 4,
                "part_url_template": "http://storage/part/{part_number}",
                "completed_parts": [],
            })
        if request.url.host == "storage" and request.method == "PUT":
            body = request.read()
            uploaded[int(path.rsplit("/", 1)[-1])] = body
            return httpx.Response(200, headers={"ETag": f'"etag-{len(body)}"'})
        if path.endswith("/uploads/upload-1/complete"):
            completed_body.update(json.loads(request.content))
            return httpx.Response(200, json={"asset_id": "asset-1"})
        if path.endswith("/jobs") and request.method == "POST":
            return httpx.Response(200, json={"id": "job-1"})
        if path.endswith("/jobs/job-1"):
            return httpx.Response(200, json={
                "status": "succeeded",
                "result": {"items": [{"captions": [{"text": "Done", "lang": "en"}]}]},
            })
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = RemoteInferenceProvider("http://server", settings, client=client)
    provider.run(_request("description", video), lambda *_args: None, threading.Event())

    assert uploaded == {1: b"0123", 2: b"4567", 3: b"89"}
    assert [part["number"] for part in completed_body["parts"]] == [1, 2, 3]
    manifests = json.loads(settings.value(UPLOAD_MANIFESTS_KEY))
    assert next(iter(manifests.values()))["asset_id"] == "asset-1"


def test_multipart_resume_skips_completed_parts_and_keeps_server_etag(tmp_path):
    video = tmp_path / "resume.bin"
    video.write_bytes(b"abcdefghij")
    settings = MemorySettings()
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(500)))
    provider = RemoteInferenceProvider("http://server", settings, client=client)
    key, stat = provider._manifest_key(str(video))
    settings.setValue(UPLOAD_MANIFESTS_KEY, json.dumps({key: {
        "upload_id": "upload-1", "path": str(video), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
    }}))
    uploaded_parts = []
    completed_body = {}

    def handler(request: httpx.Request):
        path = request.url.path
        if path.endswith("/uploads/upload-1") and request.method == "GET":
            return httpx.Response(200, json={
                "id": "upload-1", "part_size": 4,
                "part_url_template": "http://storage/part/{part_number}",
                "completed_parts": [{"number": 1, "etag": "server-etag-1", "sha256": "server-sha-1"}],
            })
        if request.url.host == "storage":
            uploaded_parts.append(int(path.rsplit("/", 1)[-1]))
            return httpx.Response(200, headers={"ETag": "etag"})
        if path.endswith("/uploads/upload-1/complete"):
            completed_body.update(json.loads(request.content))
            return httpx.Response(200, json={"asset_id": "asset-resumed"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    provider.client = httpx.Client(transport=httpx.MockTransport(handler))
    provider.capabilities = {"max_parallel_parts": 2}
    asset = provider._prepare_asset(str(video), lambda *_args: None, threading.Event())
    assert asset == {"kind": "upload", "id": "asset-resumed"}
    assert sorted(uploaded_parts) == [2, 3]
    assert completed_body["parts"][0]["etag"] == "server-etag-1"


def test_upload_part_retries_checksum_mismatch(tmp_path):
    video = tmp_path / "checksum.bin"
    video.write_bytes(b"payload")
    expected = hashlib.sha256(b"payload").hexdigest()
    attempts = 0

    def handler(request: httpx.Request):
        nonlocal attempts
        attempts += 1
        checksum = "wrong" if attempts == 1 else expected
        return httpx.Response(200, headers={"ETag": "etag", "X-Content-SHA256": checksum})

    provider = RemoteInferenceProvider(
        "http://server", MemorySettings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = provider._upload_part_with_retry(
        str(video), "upload", 1, len(b"payload"), len(b"payload"),
        {"part_url_template": "http://server/api/v1/upload-part/{part_number}"},
        threading.Event(),
    )
    assert result[0] == 1
    assert result[3] == expected
    assert attempts == 2
