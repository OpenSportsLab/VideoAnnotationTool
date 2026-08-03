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
LOCAL_MODELS_SCHEMA_VERSION_KEY = "inference/local_models_schema_version"
LOCAL_MODELS_SCHEMA_VERSION = 2
UPLOAD_MANIFESTS_KEY = "inference/upload_manifests"

DEFAULT_SERVER_URL = "http://127.0.0.1:5000"
LAST_MODEL_KEY_PREFIX = "inference/last_model"

KNOWN_HF_LOCAL_MODEL_IDS = (
    "OpenSportsLab/OSL-cls-action-mvitv2",
    "OpenSportsLab/OSL-loc-snbas-2025-e2e",
    "OpenSportsLab/OSL-loc-snbas-2023-e2e",
)

# Filter defaults persisted by releases that shipped these retired models.
RETIRED_LOCAL_MODEL_IDS = frozenset(
    {
        "jeetv/snpro-classification-mvit",
        "jeetv/snpro-snbas-2024",
    }
)

TRUSTED_LEGACY_HF_MODEL_IDS = frozenset(
    {
        "OpenSportsLab/OSL-loc-snbas-2025-e2e",
        "OpenSportsLab/OSL-loc-snbas-2023-e2e",
    }
)


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


def trusted_legacy_allowed(model: dict[str, Any]) -> bool:
    """Return whether a registry entry may opt into pickle deserialization."""
    if str(model.get("task") or "") != "localization":
        return False
    model_id = str(model.get("id") or "").strip()
    repo_id = str(model.get("hf_repo_id") or "").strip()
    revision = str(model.get("hf_revision") or "main").strip() or "main"
    weights = str(model.get("weights") or "").strip()
    if not repo_id and weights == model_id:
        repo_id = model_id
    return bool(
        model.get("trusted_legacy", False)
        and model_id == repo_id
        and repo_id in TRUSTED_LEGACY_HF_MODEL_IDS
        and revision == "main"
    )


def _is_obsolete_seeded_model(model: dict[str, Any]) -> bool:
    """Identify model rows automatically inserted by earlier releases."""
    model_id = str(model.get("id") or "").strip()
    weights = str(model.get("weights") or "").strip()
    repo_id = str(model.get("hf_repo_id") or model_id).strip()
    return bool(
        model_id in KNOWN_HF_LOCAL_MODEL_IDS
        and repo_id == model_id
        and weights == model_id
    )


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
    try:
        schema_version = int(
            settings.value(LOCAL_MODELS_SCHEMA_VERSION_KEY, 0)
            if settings is not None
            else 0
        )
    except (TypeError, ValueError):
        schema_version = 0
    migrate_old_seeds = schema_version < LOCAL_MODELS_SCHEMA_VERSION
    models = configured if isinstance(configured, list) else []
    out_by_key = {}
    for model in models:
        if not isinstance(model, dict):
            continue
        task = str(model.get("task") or "")
        model_id = str(model.get("id") or "").strip()
        if model_id in RETIRED_LOCAL_MODEL_IDS or (
            migrate_old_seeds and _is_obsolete_seeded_model(model)
        ):
            continue
        if task in INFERENCE_TASKS and model_id:
            key = (task, model_id)
            merged = {**out_by_key.get(key, {}), **dict(model)}
            merged["trusted_legacy"] = trusted_legacy_allowed(merged)
            out_by_key[key] = merged
    return list(out_by_key.values())


def save_local_models(settings, models) -> None:
    settings.setValue(LOCAL_MODELS_KEY, json.dumps(list(models or [])))
    settings.setValue(LOCAL_MODELS_SCHEMA_VERSION_KEY, LOCAL_MODELS_SCHEMA_VERSION)


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
