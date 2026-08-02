"""Persistent application-wide inference preferences."""

from __future__ import annotations

import json
import os
from typing import Any

from inference_types import INFERENCE_TASKS


BACKEND_KEY = "inference/default_backend"
SERVER_URL_KEY = "inference/server_url"
SHARED_MAPPINGS_KEY = "inference/shared_mappings"
LOCAL_MODELS_KEY = "inference/local_models"
UPLOAD_MANIFESTS_KEY = "inference/upload_manifests"

DEFAULT_BACKEND = "local"
DEFAULT_SERVER_URL = "http://127.0.0.1:5000"


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
    models = _json_setting(settings, LOCAL_MODELS_KEY, [])
    out = []
    for model in models if isinstance(models, list) else []:
        if not isinstance(model, dict):
            continue
        task = str(model.get("task") or "")
        model_id = str(model.get("id") or "").strip()
        if task in INFERENCE_TASKS and model_id:
            out.append(dict(model))
    return out


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
