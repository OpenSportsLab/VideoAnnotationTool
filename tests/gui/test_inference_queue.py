import threading

import pytest

from controllers.inference_controller import InferenceController
from inference_types import (
    InferenceError,
    InferenceInput,
    InferenceItem,
    InferenceRequest,
    InferenceResult,
)


def _request(backend, model_id):
    return InferenceRequest(
        task="description",
        model_id=model_id,
        backend=backend,
        items=[
            InferenceItem(
                f"sample-{model_id}",
                [InferenceInput(f"/{model_id}.mp4")],
            )
        ],
    )


def _result(request):
    item = request.items[0]
    return InferenceResult(
        request.request_id,
        request.task,
        request.model_id,
        ({
            "item_id": item.item_id,
            "sample_id": item.sample_id,
            "captions": [{"text": request.model_id}],
        },),
    )


@pytest.mark.gui
def test_local_and_remote_queues_run_concurrently_and_each_remains_fifo(
    qtbot, monkeypatch
):
    controller = InferenceController()
    entered = {name: threading.Event() for name in ("local-1", "local-2", "remote-1", "remote-2")}
    release = {name: threading.Event() for name in entered}
    provider_constructions = []

    class Provider:
        def __init__(self, backend):
            self.backend = backend

        def run(self, request, progress, cancel_event):
            entered[request.model_id].set()
            progress("Running", 0, 0)
            while not release[request.model_id].wait(0.01):
                if cancel_event.is_set():
                    raise InferenceError("Cancelled", code="cancelled")
            return _result(request)

        def close(self):
            pass

    def provider(backend, _config=None):
        provider_constructions.append(backend)
        return Provider(backend)

    monkeypatch.setattr(controller, "_provider", provider)
    completed = []
    controller.inferenceCompleted.connect(lambda request_id, _result: completed.append(request_id))
    requests = [
        _request("local", "local-1"),
        _request("local", "local-2"),
        _request("remote", "remote-1"),
        _request("remote", "remote-2"),
    ]
    for request in requests:
        assert controller.enqueue_inference(request) is not None

    qtbot.waitUntil(lambda: entered["local-1"].is_set() and entered["remote-1"].is_set())
    assert not entered["local-2"].is_set()
    assert not entered["remote-2"].is_set()
    assert provider_constructions.count("local") == 1
    assert provider_constructions.count("remote") == 1
    queued = [entry for entry in controller.queue_snapshot() if entry.state == "queued"]
    assert {(entry.model_id, entry.queue_position) for entry in queued} == {
        ("local-2", 1),
        ("remote-2", 1),
    }

    release["local-1"].set()
    qtbot.waitUntil(entered["local-2"].is_set)
    assert not entered["remote-2"].is_set()
    release["remote-1"].set()
    qtbot.waitUntil(entered["remote-2"].is_set)
    release["local-2"].set()
    release["remote-2"].set()
    qtbot.waitUntil(lambda: len(completed) == 4)
    qtbot.waitUntil(lambda: not controller.has_running_inference())
    assert provider_constructions == ["local", "remote", "local", "remote"]
    assert controller.shutdown()


@pytest.mark.gui
def test_queued_cancel_is_immediate_and_active_cancel_suppresses_late_success(
    qtbot, monkeypatch
):
    controller = InferenceController()
    entered = threading.Event()
    release = threading.Event()

    class SlowProvider:
        def run(self, request, _progress, _cancel_event):
            entered.set()
            release.wait(2)
            return _result(request)

        def close(self):
            pass

    monkeypatch.setattr(controller, "_provider", lambda *_args, **_kwargs: SlowProvider())
    active = _request("local", "active")
    waiting = _request("local", "waiting")
    controller.enqueue_inference(active)
    controller.enqueue_inference(waiting)
    qtbot.waitUntil(entered.is_set)

    with qtbot.waitSignal(controller.inferenceCancelled, timeout=500) as signal:
        assert controller.cancel_request(waiting.request_id)
    assert signal.args == [waiting.request_id]
    assert any(
        entry.request_id == waiting.request_id and entry.state == "cancelled"
        for entry in controller.queue_snapshot()
    )

    completed = []
    controller.inferenceCompleted.connect(lambda *_args: completed.append(True))
    with qtbot.waitSignal(controller.inferenceCancelled, timeout=2000):
        assert controller.cancel_request(active.request_id)
        release.set()
    assert completed == []
    qtbot.waitUntil(lambda: not controller.has_running_inference())
    assert controller.shutdown()


@pytest.mark.gui
def test_waiting_request_keeps_submission_time_provider_snapshot(qtbot, monkeypatch):
    controller = InferenceController()
    entered = {"active": threading.Event(), "waiting": threading.Event()}
    release = {"active": threading.Event(), "waiting": threading.Event()}
    provider_configs = []

    class Provider:
        def __init__(self, config):
            self.config = config

        def run(self, request, _progress, _cancel_event):
            entered[request.model_id].set()
            release[request.model_id].wait(2)
            return _result(request)

        def close(self):
            pass

    def provider(_backend, config=None):
        provider_configs.append(config)
        return Provider(config)

    monkeypatch.setattr(controller, "_provider", provider)
    active = _request("local", "active")
    waiting = _request("local", "waiting")
    waiting.provider_config = {"local_models": [{"id": "original"}]}
    controller.enqueue_inference(active)
    controller.enqueue_inference(waiting)
    waiting.provider_config["local_models"][0]["id"] = "mutated"
    qtbot.waitUntil(entered["active"].is_set)
    release["active"].set()
    qtbot.waitUntil(entered["waiting"].is_set)

    assert provider_configs[1]["local_models"][0]["id"] == "original"
    release["waiting"].set()
    qtbot.waitUntil(lambda: not controller.has_running_inference())
    assert controller.shutdown()


@pytest.mark.gui
def test_failure_advances_only_its_lane_and_recent_history_is_bounded(
    qtbot, monkeypatch
):
    controller = InferenceController()

    class Provider:
        def run(self, request, _progress, _cancel_event):
            if request.model_id == "failure":
                raise InferenceError("Synthetic failure", code="synthetic")
            return _result(request)

        def close(self):
            pass

    monkeypatch.setattr(controller, "_provider", lambda *_args, **_kwargs: Provider())
    failures = []
    completions = []
    controller.inferenceFailed.connect(lambda request_id, *_args: failures.append(request_id))
    controller.inferenceCompleted.connect(lambda request_id, _result: completions.append(request_id))
    failed = _request("remote", "failure")
    following = _request("remote", "following")
    controller.enqueue_inference(failed)
    controller.enqueue_inference(following)
    qtbot.waitUntil(lambda: failures == [failed.request_id] and completions == [following.request_id])

    for index in range(21):
        controller.enqueue_inference(_request("local", f"history-{index}"))
    qtbot.waitUntil(
        lambda: len([entry for entry in controller.queue_snapshot() if entry.state in {"succeeded", "failed", "cancelled"}]) == 20,
        timeout=5000,
    )
    assert len(controller.queue_snapshot()) == 20
    controller.clear_queue_history()
    assert controller.queue_snapshot() == ()
    assert controller.enqueue_inference(following) is None
    assert controller.shutdown()


@pytest.mark.gui
def test_cancel_all_clears_both_waiting_queues_and_cancels_both_active_lanes(
    qtbot, monkeypatch
):
    controller = InferenceController()
    entered = {"local-active": threading.Event(), "remote-active": threading.Event()}
    release = {"local-active": threading.Event(), "remote-active": threading.Event()}

    class Provider:
        def run(self, request, _progress, _cancel_event):
            entered[request.model_id].set()
            release[request.model_id].wait(2)
            return _result(request)

        def close(self):
            pass

    monkeypatch.setattr(controller, "_provider", lambda *_args, **_kwargs: Provider())
    requests = [
        _request("local", "local-active"),
        _request("local", "local-waiting"),
        _request("remote", "remote-active"),
        _request("remote", "remote-waiting"),
    ]
    cancelled = []
    completed = []
    controller.inferenceCancelled.connect(cancelled.append)
    controller.inferenceCompleted.connect(lambda *_args: completed.append(True))
    for request in requests:
        controller.enqueue_inference(request)
    qtbot.waitUntil(lambda: all(event.is_set() for event in entered.values()))

    assert controller.cancel_all() == 4
    assert not any(entry.state == "queued" for entry in controller.queue_snapshot())
    release["local-active"].set()
    release["remote-active"].set()
    qtbot.waitUntil(lambda: len(cancelled) == 4)
    assert completed == []
    assert controller.shutdown()


@pytest.mark.gui
def test_shutdown_cancels_waiting_jobs_and_never_dispatches_them(qtbot, monkeypatch):
    controller = InferenceController()
    entered = {"active": threading.Event(), "waiting": threading.Event()}
    release = threading.Event()

    class Provider:
        def run(self, request, _progress, _cancel_event):
            entered[request.model_id].set()
            release.wait(2)
            return _result(request)

        def close(self):
            pass

    monkeypatch.setattr(controller, "_provider", lambda *_args, **_kwargs: Provider())
    controller.enqueue_inference(_request("local", "active"))
    controller.enqueue_inference(_request("local", "waiting"))
    qtbot.waitUntil(entered["active"].is_set)

    assert controller.shutdown(wait_ms=10) is False
    assert not entered["waiting"].is_set()
    release.set()
    assert controller.shutdown(wait_ms=2000)
    assert not entered["waiting"].is_set()
