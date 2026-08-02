"""Persistent application-wide inference preferences."""

from __future__ import annotations

import json
import os
from typing import Any

from inference_types import INFERENCE_TASKS


SERVER_URL_KEY = "inference/server_url"
REMOTE_ENABLED_KEY = "inference/remote_enabled"
SHARED_MAPPINGS_KEY = "inference/shared_mappings"
LOCAL_MODELS_KEY = "inference/local_models"
UPLOAD_MANIFESTS_KEY = "inference/upload_manifests"

DEFAULT_SERVER_URL = "http://127.0.0.1:5000"
LAST_MODEL_KEY_PREFIX = "inference/last_model"


def _setting_bool(value, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def remote_inference_enabled(settings) -> bool:
    value = settings.value(REMOTE_ENABLED_KEY, False) if settings is not None else False
    return _setting_bool(value)


def last_model_key(task: str) -> str:
    if task not in INFERENCE_TASKS:
        raise ValueError(f"Unsupported inference task: {task!r}")
    return f"{LAST_MODEL_KEY_PREFIX}/{task}"


def load_last_model_choice(settings, task: str) -> tuple[str, str] | None:
    payload = _json_setting(settings, last_model_key(task), {})
    if not isinstance(payload, dict):
        return None
    backend = str(payload.get("backend") or "")
    model_id = str(payload.get("model_id") or "").strip()
    if backend not in {"local", "remote"} or not model_id:
        return None
    return backend, model_id


def save_last_model_choice(settings, task: str, backend: str, model_id: str) -> None:
    backend = str(backend or "")
    model_id = str(model_id or "").strip()
    if settings is None or backend not in {"local", "remote"} or not model_id:
        return
    settings.setValue(
        last_model_key(task),
        json.dumps({"backend": backend, "model_id": model_id}),
    )
    settings.sync()


def default_local_models(base_dir: str = "") -> list[dict[str, Any]]:
    """Known-working OpenSportsLib models shown on a fresh installation."""
    config_root = os.path.abspath(base_dir or os.path.dirname(__file__))
    return [
        {
            "task": "classification",
            "id": "jeetv/snpro-classification-mvit",
            "display_name": "SNPro Classification MViT",
            "config_path": os.path.join(config_root, "config.yaml"),
            "weights": "jeetv/snpro-classification-mvit",
            "available": True,
            "accepted_input_types": ["video"],
        },
        {
            "task": "localization",
            "id": "jeetv/snpro-snbas-2024",
            "display_name": "SNBAS 2024 Localization",
            "config_path": os.path.join(config_root, "loc_config.yaml"),
            "weights": "jeetv/snpro-snbas-2024",
            "available": True,
            "accepted_input_types": ["video"],
            "supports_time_range": True,
            # This official legacy-format checkpoint predates PyTorch's safe
            # weights-only format. Never apply this opt-in to arbitrary models.
            "trusted_legacy": True,
        },
    ]


def _json_setting(settings, key: str, default):
    raw = settings.value(key, "") if settings is not None else ""
    if isinstance(raw, (list, dict)):
        return raw
    try:
        value = json.loads(str(raw or ""))
    except Exception:
        return default
    return value


def load_shared_mappings(settings) -> list[dict[str, str]]:
    mappings = _json_setting(settings, SHARED_MAPPINGS_KEY, [])
    out = []
    for mapping in mappings if isinstance(mappings, list) else []:
        if not isinstance(mapping, dict):
            continue
        local_root = os.path.abspath(os.path.expanduser(str(mapping.get("local_root") or "")))
        root_id = str(mapping.get("root_id") or "").strip()
        if local_root and root_id:
            out.append({"local_root": local_root, "root_id": root_id})
    return out


def save_shared_mappings(settings, mappings) -> None:
    settings.setValue(SHARED_MAPPINGS_KEY, json.dumps(load_mapping_payload(mappings)))


def load_mapping_payload(mappings) -> list[dict[str, str]]:
    out = []
    for mapping in list(mappings or []):
        if not isinstance(mapping, dict):
            continue
        local_root = str(mapping.get("local_root") or "").strip()
        root_id = str(mapping.get("root_id") or "").strip()
        if local_root and root_id:
            out.append({"local_root": os.path.abspath(os.path.expanduser(local_root)), "root_id": root_id})
    return out


def load_local_models(settings) -> list[dict[str, Any]]:
    configured = _json_setting(settings, LOCAL_MODELS_KEY, [])
    builtin_by_key = {
        (model["task"], model["id"]): model for model in default_local_models()
    }
    models = [*builtin_by_key.values(), *(configured if isinstance(configured, list) else [])]
    out_by_key = {}
    for model in models:
        if not isinstance(model, dict):
            continue
        task = str(model.get("task") or "")
        model_id = str(model.get("id") or "").strip()
        if task in INFERENCE_TASKS and model_id:
            key = (task, model_id)
            merged = {**out_by_key.get(key, {}), **dict(model)}
            builtin = builtin_by_key.get(key)
            if builtin and "trusted_legacy" not in model:
                configured_weights = str(merged.get("weights") or model_id)
                builtin_weights = str(builtin.get("weights") or model_id)
                merged["trusted_legacy"] = bool(
                    builtin.get("trusted_legacy", False)
                    and configured_weights == builtin_weights
                )
            out_by_key[key] = merged
    return list(out_by_key.values())


def save_local_models(settings, models) -> None:
    settings.setValue(LOCAL_MODELS_KEY, json.dumps(list(models or [])))


def load_upload_manifests(settings) -> dict[str, Any]:
    value = _json_setting(settings, UPLOAD_MANIFESTS_KEY, {})
    return value if isinstance(value, dict) else {}


def save_upload_manifests(settings, manifests: dict[str, Any]) -> None:
    settings.setValue(UPLOAD_MANIFESTS_KEY, json.dumps(manifests))
    settings.sync()


def normalize_server_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ValueError("Server URL must start with http:// or https://.")
    return url
