"""Transport-neutral contracts for local and remote inference."""

from __future__ import annotations

import copy
import os
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


INFERENCE_TASKS = (
    "classification",
    "localization",
    "description",
    "dense_description",
    "question_answer",
)


def _explicit_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ModelDescriptor:
    id: str
    display_name: str
    task: str
    version: str = ""
    available: bool = True
    unavailable_reason: str = ""
    accepted_input_types: tuple[str, ...] = ()
    min_inputs: int = 1
    max_inputs: int | None = None
    supports_time_range: bool = False
    config_path: str = ""
    weights: str = ""
    trusted_legacy: bool = False
    checkpoint_free: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ModelDescriptor":
        if not isinstance(payload, dict):
            raise TypeError("Model descriptor must be an object.")
        task = str(payload.get("task") or "").strip()
        if task not in INFERENCE_TASKS:
            raise ValueError(f"Unsupported inference task: {task!r}")
        model_id = str(payload.get("id") or "").strip()
        if not model_id:
            raise ValueError("Model descriptor id cannot be empty.")
        raw_max = payload.get("max_inputs")
        return cls(
            id=model_id,
            display_name=str(payload.get("display_name") or model_id),
            task=task,
            version=str(payload.get("version") or ""),
            available=bool(payload.get("available", True)),
            unavailable_reason=str(payload.get("unavailable_reason") or ""),
            accepted_input_types=tuple(str(value) for value in payload.get("accepted_input_types", []) or []),
            min_inputs=max(0, int(payload.get("min_inputs", 1) or 0)),
            max_inputs=None if raw_max in (None, "") else max(0, int(raw_max)),
            supports_time_range=bool(payload.get("supports_time_range", False)),
            config_path=str(payload.get("config_path") or ""),
            weights=str(payload.get("weights") or ""),
            trusted_legacy=_explicit_bool(payload.get("trusted_legacy", False)),
            checkpoint_free=_explicit_bool(payload.get("checkpoint_free", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["accepted_input_types"] = list(self.accepted_input_types)
        return payload


@dataclass(frozen=True)
class InferenceModelChoice:
    """A runnable model together with the provider that owns it."""

    backend: str
    descriptor: ModelDescriptor

    def __post_init__(self):
        if self.backend not in {"local", "remote"}:
            raise ValueError(f"Unsupported inference backend: {self.backend!r}")

    @property
    def key(self) -> tuple[str, str]:
        return self.backend, self.descriptor.id

    @property
    def display_name(self) -> str:
        provider = "Local" if self.backend == "local" else "Remote"
        return f"{provider} — {self.descriptor.display_name}"


@dataclass(frozen=True)
class InferenceLogEvent:
    """One immutable, timestamped event from an inference job."""

    timestamp: float
    state: str
    message: str
    level: str = "info"
    current: int = 0
    total: int = 0
    details: Any = None


@dataclass(frozen=True)
class InferenceQueueEntry:
    """Immutable presentation snapshot for one queued or recent inference job."""

    request_id: str
    backend: str
    task: str
    model_id: str
    sample_ids: tuple[str, ...]
    state: str
    message: str = ""
    current: int = 0
    total: int = 0
    queue_position: int = -1
    submitted_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    error_code: str = ""
    error_details: Any = None
    retryable: bool = False
    log_events: tuple[InferenceLogEvent, ...] = ()


@dataclass
class InferenceInput:
    path: str
    type: str = "video"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_sample_input(cls, item: dict[str, Any], resolved_path: str | None = None):
        metadata = copy.deepcopy(item)
        metadata.pop("path", None)
        input_type = str(metadata.pop("type", "video") or "video")
        return cls(path=str(resolved_path or item.get("path") or ""), type=input_type, metadata=metadata)

    def to_wire(self, asset: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {"type": self.type, **copy.deepcopy(self.metadata)}
        if asset is None:
            payload["path"] = self.path
        else:
            payload["asset"] = copy.deepcopy(asset)
        return payload


@dataclass
class InferenceItem:
    sample_id: str
    inputs: list[InferenceInput]
    sample: dict[str, Any] = field(default_factory=dict)
    item_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class InferenceRequest:
    task: str
    model_id: str
    items: list[InferenceItem]
    parameters: dict[str, Any] = field(default_factory=dict)
    schema: dict[str, Any] = field(default_factory=dict)
    backend: str = "local"
    # Immutable request-scoped snapshot of the saved provider setup. The run
    # dialog selects a model and runtime parameters but never edits this data.
    provider_config: dict[str, Any] = field(default_factory=dict)
    target_context: dict[str, Any] = field(default_factory=dict)
    # Local filesystem root of the open dataset. Providers may use this to
    # replace publisher-specific paths in disposable runtime configs; it is
    # never included in a remote job payload.
    dataset_root: str = ""
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self):
        if self.task not in INFERENCE_TASKS:
            raise ValueError(f"Unsupported inference task: {self.task!r}")
        if self.backend not in {"local", "remote"}:
            raise ValueError(f"Unsupported inference backend: {self.backend!r}")
        if not str(self.model_id or "").strip():
            raise ValueError("Inference model id cannot be empty.")
        if not self.items:
            raise ValueError("Inference requires at least one item.")


@dataclass(frozen=True)
class InferenceResult:
    request_id: str
    task: str
    model_id: str
    items: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class PendingPrediction:
    """A normalized, session-only prediction awaiting human review."""

    prediction_id: str
    request_id: str
    task: str
    sample_id: str
    model_id: str
    payload: dict[str, Any]
    confidence_score: float = 0.0
    target_context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, result: InferenceResult, item: dict[str, Any], payload: dict[str, Any], *, confidence=0.0, target_context=None):
        return cls(
            prediction_id=uuid.uuid4().hex,
            request_id=result.request_id,
            task=result.task,
            sample_id=str(item.get("sample_id") or ""),
            model_id=result.model_id,
            payload=copy.deepcopy(payload),
            confidence_score=max(0.0, min(1.0, float(confidence or 0.0))),
            target_context=copy.deepcopy(target_context or {}),
        )


class InferenceError(RuntimeError):
    def __init__(self, message: str, *, code: str = "inference_error", retryable: bool = False, details=None):
        super().__init__(str(message))
        self.code = str(code)
        self.retryable = bool(retryable)
        self.details = details


def resolve_sample_inputs(sample: dict[str, Any], project_json_path: str = "") -> list[InferenceInput]:
    """Resolve project-relative input paths without mutating the sample."""
    base_dir = os.path.dirname(project_json_path) if project_json_path else ""
    resolved = []
    for item in list(sample.get("inputs") or []):
        if not isinstance(item, dict) or not item.get("path"):
            continue
        path = os.path.expanduser(str(item["path"]))
        if not os.path.isabs(path) and base_dir:
            path = os.path.join(base_dir, path)
        resolved.append(InferenceInput.from_sample_input(item, os.path.abspath(path)))
    return resolved


def validate_result_payload(request: InferenceRequest, payload: Any) -> InferenceResult:
    """Validate the stable outer result envelope and task-native item fields."""
    if not isinstance(payload, dict):
        raise InferenceError("Inference result must be a JSON object.", code="invalid_result")
    raw_items = payload.get("items")
    if raw_items is None and isinstance(payload.get("result"), dict):
        raw_items = payload["result"].get("items")
    if not isinstance(raw_items, list):
        # Local OSL results commonly return a top-level data array.
        raw_items = payload.get("data")
    if not isinstance(raw_items, list):
        raise InferenceError("Inference result is missing an items array.", code="invalid_result")
    if len(raw_items) != len(request.items):
        raise InferenceError(
            "Inference result item count does not match the request "
            f"({len(raw_items)} returned for {len(request.items)} requested).",
            code="invalid_result",
        )

    required_field = {
        "classification": "labels",
        "localization": "events",
        "description": "captions",
        "dense_description": "dense_captions",
        "question_answer": "answer",
    }[request.task]
    request_by_item_id = {item.item_id: item for item in request.items}
    request_by_sample_id: dict[str, list[InferenceItem]] = {}
    for request_item in request.items:
        request_by_sample_id.setdefault(request_item.sample_id, []).append(request_item)
    normalized = []
    used_item_ids = set()
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise InferenceError(f"Result item {index} must be an object.", code="invalid_result")
        item = copy.deepcopy(raw)
        if required_field not in item:
            # OSL data items use id rather than item_id; preserve and correlate by order.
            if request.task == "question_answer" and isinstance(item.get("answers"), list):
                answers = item["answers"]
                if answers:
                    item["answer"] = copy.deepcopy(answers[0])
            if required_field not in item:
                raise InferenceError(
                    f"Result item {index} is missing {required_field!r}.", code="invalid_result"
                )
        raw_item_id = str(item.get("item_id") or "")
        raw_sample_id = str(item.get("sample_id") or "")
        request_item = request_by_item_id.get(raw_item_id) if raw_item_id else None
        if raw_item_id and request_item is None:
            raise InferenceError(
                f"Result item {index} has unknown request item ID {raw_item_id!r}.",
                code="invalid_result",
            )
        if request_item is None and raw_sample_id:
            sample_matches = request_by_sample_id.get(raw_sample_id, [])
            if len(sample_matches) == 1:
                request_item = sample_matches[0]
        if request_item is None and request.backend == "local" and index < len(request.items):
            request_item = request.items[index]
        if request_item is None:
            raise InferenceError(
                f"Result item {index} cannot be correlated to an inference request item.",
                code="invalid_result",
            )
        if request_item.item_id in used_item_ids:
            raise InferenceError(
                f"Result item {index} duplicates request item {request_item.item_id!r}.",
                code="invalid_result",
            )
        used_item_ids.add(request_item.item_id)
        # Never trust result-owned target identifiers. The immutable request is
        # the sole authority for where a prediction belongs.
        item["item_id"] = request_item.item_id
        item["sample_id"] = request_item.sample_id
        normalized.append(item)

    return InferenceResult(
        request_id=request.request_id,
        task=request.task,
        model_id=request.model_id,
        items=tuple(normalized),
    )
